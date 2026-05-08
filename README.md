# Medical Evidence MCP Server

An advanced Clinical Decision Support (CDS) agent and medical evidence synthesizer that acts as a secure bridge between FHIR patient data and external medical research databases. Built as a Model Context Protocol (MCP) server for integration with Gemini AI.

## Overview

This project provides:
- **HIPAA-Compliant Evidence Retrieval**: Anonymized querying of medical research without exposing Protected Health Information (PHI)
- **Local Knowledge Base**: ChromaDB-powered vector database of medical research with semantic search
- **PubMed Integration**: Direct access to current medical literature via NCBI Entrez API
- **Clinical Synthesis**: Evidence-based clinical insights linked to patient presentations
- **FHIR Context Extension**: Support for PromptOpinion FHIR context for secure patient data handling

## Features

- Query local vetted medical knowledge RAG base
- Search PubMed for specific medical evidence
- Ingest new research findings into ChromaDB
- Monitor and check for retracted research
- Generate composite clinical scores based on evidence
- FHIR patient data integration with privacy safeguards

## Prerequisites

- Python 3.8+
- Virtual environment manager (venv, conda, etc.)
- NCBI Entrez API access (free with email registration)
- Gemini API key (for AI integration)

## Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd medical-evidence-mcp
   ```

2. **Create and activate virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` with:
   ```
   ENTREZ_EMAIL=""
   ENTREZ_API_KEY=""
   GEMINI_API_KEY=""
   ```

## Configuration

### Gemini Settings

Configure MCP integration in `.gemini/settings.json`:

```json
{
  "mcpServers": {
    "medical-evidence": {
      "command": "<VENV_BIN_PATH>/python",
      "args": ["<PROJECT_ROOT>/server.py"]
    }
  }
}
```

Replace placeholders with actual paths:
- `<VENV_BIN_PATH>`: Path to virtual environment (e.g., `.venv/bin`)
- `<PROJECT_ROOT>`: Project root directory

## Usage

### Start the Server

```bash
python server.py
```

The server will start on `http://0.0.0.0:8000` by default (configurable via `MCP_PORT`).

### MCP Tools Available

#### `query_evidence`
Search the local ChromaDB knowledge base for medical evidence.
```
Input: Medical query (anonymized clinical concepts)
Output: Ranked evidence results with scoring
```

#### `search_pubmed`
Query PubMed for recent research.
```
Input: Medical keywords or MeSH terms
Output: PubMed results with abstracts
```

#### `ingest_to_chroma`
Add new research findings to the local database.
```
Input: Article metadata and embeddings
Output: Confirmation and database update
```

#### `get_new_research`
Retrieve recent publications on monitored topics.

#### `check_retractions`
Verify cited research hasn't been retracted (HIPAA critical step).

## Data Storage

- **ChromaDB**: Located in `chroma_data/` directory
  - Vector embeddings of medical literature
  - Semantic search capability
  - Persistent SQLite backend

## Architecture

```
medical-evidence-mcp/
├── server.py              # FastMCP server implementation
├── scoring.py             # Clinical scoring algorithms
├── requirements.txt       # Python dependencies
├── .env                   # Environment variables (not in git)
├── .gemini/
│   └── settings.json      # Gemini MCP configuration
├── chroma_data/           # Vector database (not in git)
└── README.md             # This file
```

## Security & Compliance

### HIPAA Compliance
- **Zero-Leak Mandate**: Never pass PHI to external tools
- **Anonymization**: All queries must translate patient data to generalized pathophysiological concepts
- **No PII in Searches**: Exclude names, MRNs, dates of birth, specific locations, raw patient quotes

### Example Safe Query Transformation
- ❌ **Unsafe**: "Jane Doe, DOB 1965, presents with hot flashes and FSH 89"
- ✅ **Safe**: "Adhesive capsulitis, dyslipidemia, and mood disorders during late menopause transition"

## Development

### Running Tests
```bash
python -m pytest tests/
```

### Monitoring
The server includes diagnostic logging for:
- Vector embedding distances
- Query performance metrics
- ChromaDB collection statistics

## Troubleshooting

### ChromaDB Embedding Score = 0
If vector search returns very high distances (200+) with score 0:
1. Check vector norms and L2 distances
2. Configure ChromaDB with cosine distance metric
3. Clear collection and re-ingest data

See [debugging notes](docs/debugging.md) for diagnostic scripts.

### Environment Issues
```bash
# Verify Python environment
python -c "import sys; print(sys.executable)"

# Check installed packages
pip list

# Reinstall dependencies
pip install --upgrade -r requirements.txt
```

## Contributing

1. Ensure all queries respect PHI protection rules
2. Test clinical scoring with known cases
3. Document any new MCP tools in this README

## References

- [Model Context Protocol](https://modelcontextprotocol.io/)
- [FHIR Standard](https://www.hl7.org/fhir/)
- [NCBI Entrez](https://www.ncbi.nlm.nih.gov/books/NBK25499/)
- [Sentence Transformers](https://www.sbert.net/)
- [ChromaDB](https://docs.trychroma.com/)

## License

MIT License

## Support

For issues, questions, or contributions, please open an issue or contact the development team research@harmonilab.org.
