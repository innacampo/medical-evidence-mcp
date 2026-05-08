import math
from datetime import datetime

# Study type evidence hierarchy
STUDY_TYPE_BOOSTS = {
    "meta-analysis": 1.30,
    "systematic review": 1.25,
    "randomized controlled trial": 1.20,
    "clinical trial": 1.15,
    "cohort study": 1.10,
    "case-control study": 1.05,
    "case reports": 1.00,
    "review": 0.95,
    "editorial": 0.90,
    "comment": 0.90,
}

def classify_study_type(pub_types_str: str) -> tuple[str, float]:
    """Classify study type from PubMed publication types and return boost."""
    pub_types_lower = pub_types_str.lower()
    
    for study_type, boost in STUDY_TYPE_BOOSTS.items():
        if study_type in pub_types_lower:
            return study_type, boost
    
    return "other", 1.0

def recency_boost(year_str: str, current_year: int = None) -> float:
    if current_year is None:
        current_year = datetime.now().year
    try:
        year = int(year_str)
        age = current_year - year
        return math.exp(-0.03 * age)
    except (ValueError, TypeError):
        return 0.8  # Unknown year gets slight penalty

def compute_composite_score(
    similarity: float,
    pub_types_str: str,
    year_str: str
) -> dict:
    """Compute composite score with full breakdown."""
    study_type, study_boost = classify_study_type(pub_types_str)
    rec_boost = recency_boost(year_str)
    
    composite = similarity * study_boost * rec_boost
    
    return {
        "composite_score": round(composite, 4),
        "similarity": round(similarity, 4),
        "study_type": study_type,
        "study_type_boost": study_boost,
        "recency_boost": round(rec_boost, 4),
    }