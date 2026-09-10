"""Document Classifier stage.

Pure keyword-scoring — never assumes a fixed text position. Each doc
type has a list of keyword phrases (config/extraction_patterns.yaml);
whichever type has the most keyword hits in the document text wins. Ties
and "no keyword hit at all" resolve to UNKNOWN so the file lands in the
ERROR bucket instead of being silently misfiled.
"""
from __future__ import annotations

from app.core.config_loader import get_extraction_patterns
from app.models.schema import DocType


def classify_text(text: str) -> tuple[DocType, dict[str, int]]:
    patterns = get_extraction_patterns().get("classification", {})
    text_l = text.lower()

    scores: dict[str, int] = {}
    for doc_type_name, cfg in patterns.items():
        keywords = cfg.get("keywords", [])
        scores[doc_type_name] = sum(1 for kw in keywords if kw.lower() in text_l)

    best_type, best_score = None, 0
    for name, score in scores.items():
        if score > best_score:
            best_type, best_score = name, score

    if not best_type or best_score == 0:
        return DocType.UNKNOWN, scores

    try:
        return DocType(best_type), scores
    except ValueError:
        return DocType.UNKNOWN, scores
