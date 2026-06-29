from mcp.server.fastmcp import FastMCP
import os
import sys
from dotenv import load_dotenv
from Bio import Entrez
import chromadb
from sentence_transformers import SentenceTransformer
from datetime import datetime, timedelta
from scoring import compute_composite_score

load_dotenv()
# Use environment variable if provided
os.environ["HF_HUB_OFFLINE"] = os.getenv("HF_HUB_OFFLINE", "1")


port = int(os.getenv("MCP_PORT"))

mcp = FastMCP(
    "AXIOM Medical Evidence Server",
    host="0.0.0.0",
    port=port
)

# --- PromptOpinion FHIR Context Extension ---
# Deleted
# --------------------------------------------

Entrez.email = os.getenv("ENTREZ_EMAIL")
Entrez.api_key = os.getenv("ENTREZ_API_KEY")

if not Entrez.email or not Entrez.api_key:
    raise ValueError("ENTREZ_EMAIL and ENTREZ_API_KEY environment variables must be set.")

@mcp.tool()
def search_pubmed(query: str, max_results: int = 5) -> str:
    """Search PubMed for medical research articles.
    
    Args:
        query: A medical research question or topic
        max_results: Number of articles to return (default 5)
    """
    try:
        # Search
        handle = Entrez.esearch(db="pubmed", term=query, retmax=max_results)
        results = Entrez.read(handle)
        handle.close()
        
        pmids = results["IdList"]
        if not pmids:
            return "No articles found."
        
        # Fetch details
        handle = Entrez.efetch(db="pubmed", id=pmids, rettype="abstract", retmode="xml")
        records = Entrez.read(handle)
        handle.close()
        
        # Format output
        output = []
        for article in records["PubmedArticle"]:
            medline = article["MedlineCitation"]
            art = medline["Article"]
            title = str(art["ArticleTitle"])
            pmid = str(medline["PMID"])
            
            # Get abstract (safely)
            abstract = ""
            if "Abstract" in art:
                abstract = " ".join(str(t) for t in art["Abstract"]["AbstractText"])
            
            # Get year (safely)
            year = "Unknown"
            if "DateCompleted" in medline:
                year = str(medline["DateCompleted"]["Year"])
            elif "Journal" in art and "JournalIssue" in art["Journal"] and "PubDate" in art["Journal"]["JournalIssue"]:
                pub_date = art["Journal"]["JournalIssue"]["PubDate"]
                if "Year" in pub_date:
                    year = str(pub_date["Year"])
            
            output.append(f"**PMID: {pmid}** ({year})\n**{title}**\n{abstract[:500]}...\n")
        
        return "\n---\n".join(output)
    except Exception as e:
        return f"Error searching PubMed: {str(e)}"



# Initialize once at module level
chroma_client = chromadb.PersistentClient(
    path="./chroma_data",
    settings=chromadb.Settings(
        is_persistent=True, 
        anonymized_telemetry=False
    )
)

collection = chroma_client.get_or_create_collection(
    name="medical_evidence",
    metadata={"hnsw:space": "cosine"}
)
embedder = SentenceTransformer("all-MiniLM-L6-v2")


@mcp.tool()
def ingest_to_chroma(query: str, max_results: int = 10) -> str:
    """Search PubMed and store results in the local knowledge base for later querying.
    
    Args:
        query: A medical research topic to search and store
        max_results: Number of articles to fetch and store
    """
    try:
        # Search PubMed
        handle = Entrez.esearch(db="pubmed", term=query, retmax=max_results)
        results = Entrez.read(handle)
        handle.close()
        
        pmids = results["IdList"]
        if not pmids:
            return "No articles found to ingest."
        
        # Fetch full details
        handle = Entrez.efetch(db="pubmed", id=pmids, rettype="abstract", retmode="xml")
        records = Entrez.read(handle)
        handle.close()
        
        ingested = 0
        skipped = 0
        
        for article in records["PubmedArticle"]:
            medline = article["MedlineCitation"]
            art = medline["Article"]
            pmid = str(medline["PMID"])
            title = str(art["ArticleTitle"])
            
            abstract = ""
            if "Abstract" in art:
                abstract = " ".join(str(t) for t in art["Abstract"]["AbstractText"])
            
            if not abstract:
                skipped += 1
                continue
            
            # Get metadata
            journal = str(art["Journal"]["Title"]) if "Journal" in art else "Unknown"
            year = "Unknown"
            if "DateCompleted" in medline:
                year = str(medline["DateCompleted"]["Year"])
            elif "Journal" in art and "JournalIssue" in art["Journal"] and "PubDate" in art["Journal"]["JournalIssue"]:
                pub_date = art["Journal"]["JournalIssue"]["PubDate"]
                if "Year" in pub_date:
                    year = str(pub_date["Year"])
            
            # Get publication type
            pub_types = []
            if "PublicationTypeList" in art:
                pub_types = [str(pt) for pt in art["PublicationTypeList"]]
            
            # Create document text
            doc_text = f"{title}\n\n{abstract}"
            doc_id = f"{pmid}_chunk_0"
            
            # Embed and store
            embedding = embedder.encode(doc_text).tolist()
            
            collection.upsert(
                ids=[doc_id],
                documents=[doc_text],
                embeddings=[embedding],
                metadatas=[{
                    "pmid": pmid,
                    "title": title,
                    "journal": journal,
                    "year": year,
                    "pub_types": ", ".join(pub_types),
                }]
            )
            ingested += 1
        
        return (
            f"Ingested {ingested} articles into knowledge base "
            f"(skipped {skipped} without abstracts). "
            f"Collection now has {collection.count()} documents."
        )
    except Exception as e:
        return f"Error during ingestion: {str(e)}"


@mcp.tool()
def query_evidence(question: str, top_k: int = 5) -> str:
    """Search the local knowledge base for evidence relevant to a clinical question.
    Results are re-ranked by evidence quality (study type + recency + relevance).
    
    Args:
        question: A clinical question to find evidence for
        top_k: Number of top results to return
    """
    if collection.count() == 0:
        return "Knowledge base is empty. Use ingest_to_chroma first to add articles."
    
    # Retrieve more candidates than needed (we'll re-rank)
    n_candidates = min(max(top_k * 5, 20), collection.count())
    query_embedding = embedder.encode(question).tolist()
    
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_candidates
    )
    
    if not results["documents"][0]:
        return "No relevant evidence found."
    
    # Score and re-rank
    scored_results = []
    for doc, metadata, distance in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0]
    ):
        similarity = 1 - distance
        score_info = compute_composite_score(
            similarity=similarity,
            pub_types_str=metadata.get("pub_types", ""),
            year_str=metadata.get("year", "Unknown")
        )
        scored_results.append({
            "doc": doc,
            "metadata": metadata,
            "scoring": score_info,
        })
    
    # Filter out retracted articles before ranking
    scored_results = [
        r for r in scored_results
        if r["metadata"].get("retraction_status") != "retracted"
    ]
    
    # Apply penalties for articles with expression of concern before final sort
    for result in scored_results:
        if result["metadata"].get("retraction_status") == "concern":
            result["scoring"]["composite_score"] *= 0.5  # Penalty
            result["warning"] = "Expression of concern issued for this article"

    # Sort by final composite score (not raw similarity)
    scored_results.sort(key=lambda x: x["scoring"]["composite_score"], reverse=True)
    
    # Now, take the top k results
    scored_results = scored_results[:top_k]
    
    # Format output
    output = []
    for i, result in enumerate(scored_results):
        s = result["scoring"]
        m = result["metadata"]
        warning_line = f"\n**{result['warning']}**" if "warning" in result else ""
        output.append(
            f"### Result {i+1}\n"
            f"**PMID**: {m['pmid']} | **Journal**: {m['journal']} | **Year**: {m['year']}\n"
            f"**Study Type**: {s['study_type']} | "
            f"**Composite Score**: {s['composite_score']:.3f} "
            f"(relevance: {s['similarity']:.2f} × "
            f"study: {s['study_type_boost']} × "
            f"recency: {s['recency_boost']:.2f}){warning_line}\n\n"
            f"{result['doc'][:600]}...\n"
        )
    
    header = (
        f"Found {len(output)} results, ranked by evidence quality "
        f"(from {collection.count()} stored articles):\n\n"
    )
    return header + "\n---\n".join(output)

@mcp.tool()
def get_new_research(topics: list[str], days_back: int = 30) -> str:
    """Check for new research on monitored topics and update the knowledge base.
    Updates both new articles and existing articles whose metadata has changed.
    
    Args:
        topics: List of medical topics to check for new research
        days_back: How many days back to search (default 30)
    """
    min_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y/%m/%d")
    max_date = datetime.now().strftime("%Y/%m/%d")
    
    total_new = 0
    total_updated = 0
    total_skipped = 0
    errors = []
    
    for topic in topics:
        try:
            # Search PubMed with date filter
            handle = Entrez.esearch(
                db="pubmed", term=topic, retmax=20,
                mindate=min_date, maxdate=max_date, datetype="pdat"
            )
            results = Entrez.read(handle)
            handle.close()
            
            pmids = results["IdList"]
            if not pmids:
                continue
            
            # Fetch details
            handle = Entrez.efetch(db="pubmed", id=pmids, rettype="abstract", retmode="xml")
            records = Entrez.read(handle)
            handle.close()
        
            for article in records["PubmedArticle"]:
                medline = article["MedlineCitation"]
                art = medline["Article"]
                pmid = str(medline["PMID"])
                title = str(art["ArticleTitle"])
                
                abstract = ""
                if "Abstract" in art:
                    abstract = " ".join(str(t) for t in art["Abstract"]["AbstractText"])
                
                if not abstract:
                    continue
                
                journal = str(art["Journal"]["Title"]) if "Journal" in art else "Unknown"
                year = "Unknown"
                if "DateCompleted" in medline:
                    year = str(medline["DateCompleted"]["Year"])
                elif "Journal" in art and "JournalIssue" in art["Journal"] and "PubDate" in art["Journal"]["JournalIssue"]:
                    pub_date = art["Journal"]["JournalIssue"]["PubDate"]
                    if "Year" in pub_date:
                        year = str(pub_date["Year"])
                
                pub_types = []
                if "PublicationTypeList" in art:
                    pub_types = [str(pt) for pt in art["PublicationTypeList"]]
                
                doc_id = f"{pmid}_chunk_0"
                doc_text = f"{title}\n\n{abstract}"
                
                new_metadata = {
                    "pmid": pmid,
                    "title": title,
                    "journal": journal,
                    "year": year,
                    "pub_types": ", ".join(pub_types),
                }
                
                # Check if already exists
                existing = collection.get(ids=[doc_id])
                
                if existing and existing["ids"]:
                    # Article exists — check if metadata changed
                    old_meta = existing["metadatas"][0]
                    changes = []
                    
                    if old_meta.get("pub_types", "") != new_metadata["pub_types"]:
                        changes.append("pub_types")
                    if old_meta.get("year", "") != new_metadata["year"]:
                        changes.append("year")
                    
                    if changes:
                        # Re-embed and update
                        embedding = embedder.encode(doc_text).tolist()
                        collection.update(
                            ids=[doc_id],
                            documents=[doc_text],
                            embeddings=[embedding],
                            metadatas=[new_metadata]
                        )
                        total_updated += 1
                    else:
                        total_skipped += 1
                else:
                    # New article — ingest
                    embedding = embedder.encode(doc_text).tolist()
                    collection.upsert(
                        ids=[doc_id],
                        documents=[doc_text],
                        embeddings=[embedding],
                        metadatas=[new_metadata]
                    )
                    total_new += 1
        except Exception as e:
            errors.append(f"  - '{topic}': {str(e)}")
    
    report = (
        f"Delta sync complete for {len(topics)} topics:\n"
        f"- New articles ingested: {total_new}\n"
        f"- Existing articles updated: {total_updated}\n"
        f"- Unchanged (skipped): {total_skipped}\n"
        f"- Knowledge base total: {collection.count()} documents"
    )
    if errors:
        report += f"\n\nErrors for {len(errors)} topic(s):\n" + "\n".join(errors)
    return report

@mcp.tool()
def check_retractions() -> str:
    """Scan all stored articles for retraction notices. 
    SAFETY-CRITICAL: Retracted articles will be flagged and excluded from future queries.
    """
    # Get all stored PMIDs
    all_docs = collection.get()
    if not all_docs["ids"]:
        return "Knowledge base is empty. Nothing to scan."
    
    pmids = list(set(m["pmid"] for m in all_docs["metadatas"]))
    
    # Batch check retraction status
    retracted = []
    concerned = []
    batch_errors = []
    
    # Process in batches of 100
    for i in range(0, len(pmids), 100):
        batch = pmids[i:i+100]
        try:
            handle = Entrez.efetch(db="pubmed", id=batch, rettype="abstract", retmode="xml")
            records = Entrez.read(handle)
            handle.close()
        except Exception as e:
            batch_errors.append(f"  - Batch {i//100 + 1} (PMIDs {i+1}–{i+len(batch)}): {str(e)}")
            continue
        
        for article in records["PubmedArticle"]:
            medline = article["MedlineCitation"]
            art = medline["Article"]
            pmid = str(medline["PMID"])
            
            pub_types = []
            if "PublicationTypeList" in art:
                pub_types = [str(pt).lower() for pt in art["PublicationTypeList"]]
            
            status = "active"
            for pt in pub_types:
                if "retract" in pt:
                    status = "retracted"
                    break
                elif "expression of concern" in pt:
                    status = "concern"
            
            if status != "active":
                # Update metadata in ChromaDB
                doc_id = f"{pmid}_chunk_0"
                existing = collection.get(ids=[doc_id])
                if existing and existing["ids"]:
                    meta = existing["metadatas"][0]
                    meta["retraction_status"] = status
                    collection.update(ids=[doc_id], metadatas=[meta])
                    
                    if status == "retracted":
                        retracted.append(f"PMID:{pmid} - {meta.get('title', 'Unknown')}")
                    else:
                        concerned.append(f"PMID:{pmid} - {meta.get('title', 'Unknown')}")
    
    report = f"Retraction scan complete. Checked {len(pmids)} articles.\n\n"
    
    if retracted:
        report += f"RETRACTED ({len(retracted)}):\n"
        for r in retracted:
            report += f"  - {r}\n"
        report += "\nThese articles will be excluded from future queries.\n\n"
    
    if concerned:
        report += f"EXPRESSION OF CONCERN ({len(concerned)}):\n"
        for c in concerned:
            report += f"  - {c}\n"
        report += "\nThese articles will be flagged in future queries.\n\n"
    
    if not retracted and not concerned:
        report += "No retractions or concerns found. All articles are active."
    
    if batch_errors:
        report += f"\n\nErrors in {len(batch_errors)} batch(es) — those articles were not checked:\n"
        report += "\n".join(batch_errors)
    
    return report

transport = os.getenv("MCP_TRANSPORT")


if __name__ == "__main__":
    if transport == "streamable-http":
        print(f"Starting AXIOM MCP server (Streamable HTTP) on port {port}", file=sys.stderr)
        mcp.run(transport="streamable-http")  # Streamable HTTP
    elif transport == "sse":
        print(f"Starting AXIOM MCP server (SSE) on port {port}", file=sys.stderr)
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")