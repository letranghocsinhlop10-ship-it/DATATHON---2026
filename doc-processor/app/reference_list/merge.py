"""Cross-checks a reference list (see loader.py) against the DocumentSets
already produced by the reference matcher.

For each entry in the list:
- a DocumentSet with a matching reference is found -> marked FOUND (or
  AMOUNT_MISMATCH if the list gave an expected amount that doesn't
  agree with the extracted total, within the usual tolerance);
- nothing matches at all -> a new all-empty DocumentSet is created so
  the gap surfaces in the UI/report/OUTPUT tree just like any other
  issue, instead of silently vanishing.

This never affects the plain PDF-only workflow: with an empty entry
list, `merge_reference_list` is a no-op.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from rapidfuzz import fuzz

from app.core.config_loader import get_settings
from app.core.logging_config import get_logger
from app.models.schema import CompletenessStatus, DocumentSet, ReferenceListEntry

log = get_logger("reference_list.merge")

_FUZZY_MAX_LEN = 14  # same rationale as reference_matcher: only short human-facing codes


def _normalize(s: str) -> str:
    return s.strip().upper()


def _actual_amount(ds: DocumentSet) -> Optional[Decimal]:
    for role in ("vat_invoice", "facebook", "bank_debit"):
        doc = getattr(ds, role, None)
        if doc is not None and doc.total_amount is not None:
            return doc.total_amount
    return None


def _find_matching_set(entry: ReferenceListEntry, document_sets: list[DocumentSet], fuzzy_threshold: int) -> Optional[DocumentSet]:
    key = _normalize(entry.reference)

    for ds in document_sets:
        if _normalize(ds.reference) == key:
            return ds
    for ds in document_sets:
        for doc in ds.present_docs.values():
            if key in {_normalize(c) for c in doc.reference_candidates}:
                return ds

    if len(key) <= _FUZZY_MAX_LEN:
        best_ds, best_score = None, 0
        for ds in document_sets:
            cand = _normalize(ds.reference)
            if len(cand) > _FUZZY_MAX_LEN:
                continue
            score = fuzz.ratio(key, cand)
            if score > best_score:
                best_score, best_ds = score, ds
        if best_ds is not None and best_score >= fuzzy_threshold:
            return best_ds
    return None


def merge_reference_list(document_sets: list[DocumentSet], entries: list[ReferenceListEntry]) -> list[DocumentSet]:
    if not entries:
        return document_sets

    settings = get_settings()
    amount_tolerance = settings.get("reconciliation", {}).get("amount_tolerance_percent", 1.0)
    fuzzy_threshold = settings.get("matching", {}).get("fuzzy_threshold", 85)

    new_sets: list[DocumentSet] = []

    for entry in entries:
        ds = _find_matching_set(entry, document_sets, fuzzy_threshold)

        if ds is None:
            log.info("Reference list: '%s' không khớp chứng từ nào đã xử lý", entry.reference)
            new_sets.append(
                DocumentSet(
                    reference=entry.reference,
                    completeness=CompletenessStatus.INCOMPLETE,
                    issues=["MISSING_ALL_DOCUMENTS"],
                    reference_list_status="NOT_FOUND",
                    reference_list_note=(
                        f"Có trong danh sách đối chiếu ({entry.source_file}, dòng {entry.row_number}) "
                        "nhưng không tìm thấy chứng từ PDF nào tương ứng."
                    ),
                )
            )
            continue

        if entry.expected_amount is None:
            ds.reference_list_status = "FOUND"
            continue

        actual = _actual_amount(ds)
        if actual is None:
            ds.reference_list_status = "FOUND"
            ds.reference_list_note = "Danh sách có số tiền kỳ vọng nhưng chứng từ không trích xuất được số tiền để so sánh."
            continue

        base = max(abs(actual), abs(entry.expected_amount)) or Decimal(1)
        diff_pct = abs(actual - entry.expected_amount) / base * 100
        if diff_pct <= Decimal(str(amount_tolerance)):
            ds.reference_list_status = "FOUND"
        else:
            ds.reference_list_status = "AMOUNT_MISMATCH"
            ds.reference_list_note = f"Danh sách kỳ vọng {entry.expected_amount}, thực tế trích xuất {actual}."
            if "REFERENCE_LIST_AMOUNT_MISMATCH" not in ds.issues:
                ds.issues.append("REFERENCE_LIST_AMOUNT_MISMATCH")

    return document_sets + new_sets
