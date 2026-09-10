"""Reference Matcher stage.

Groups ExtractedDocuments into DocumentSets by reference number. As
explained in the implementation plan, no single field is guaranteed to
carry an identical "reference" string across all 3 doc types in the
real world, so this does NOT do a plain `.reference == .reference`
join. Instead:

1. Every extractor already produced a list of `reference_candidates`
   (explicit reference field + any embedded/secondary codes).
2. Documents are unioned (union-find) whenever they share an exact
   (case-insensitive) candidate string.
3. Any clusters still unlinked are given one more pass with fuzzy
   matching (rapidfuzz) between their candidate strings, using a
   configurable threshold — this catches near-duplicates from OCR noise
   or minor formatting differences without over-merging unrelated sets.

Unreadable/unclassifiable documents never enter the grouping pool —
each becomes its own ERROR DocumentSet so a single bad file can't
corrupt an otherwise-good cluster.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz

from app.core.config_loader import get_settings
from app.core.logging_config import get_logger
from app.models.schema import CompletenessStatus, DocType, DocumentSet, ExtractedDocument

log = get_logger("matching")

_SLOT_BY_DOC_TYPE = {
    DocType.FACEBOOK: "facebook",
    DocType.VAT_INVOICE: "vat_invoice",
    DocType.BANK_DEBIT: "bank_debit",
}


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _normalize_candidate(c: str) -> str:
    return c.strip().upper()


def _is_problem_doc(doc: ExtractedDocument) -> bool:
    return doc.is_error or doc.doc_type == DocType.UNKNOWN


def _make_error_set(doc: ExtractedDocument) -> DocumentSet:
    stem = Path(doc.source_file).stem
    short_hash = (doc.file_hash or "")[:8]
    reference = f"ERROR__{stem}" + (f"__{short_hash}" if short_hash else "")
    return DocumentSet(
        reference=reference,
        completeness=CompletenessStatus.ERROR,
        issues=["ERROR"],
        error_files=[doc],
    )


def _make_missing_reference_set(doc: ExtractedDocument) -> DocumentSet:
    stem = Path(doc.source_file).stem
    reference = f"NOREF__{stem}"
    ds = DocumentSet(
        reference=reference,
        completeness=CompletenessStatus.INCOMPLETE,
        issues=["INCOMPLETE", "MISSING_REFERENCE"],
    )
    slot = _SLOT_BY_DOC_TYPE.get(doc.doc_type)
    if slot:
        setattr(ds, slot, doc)
    else:  # pragma: no cover - defensive; _is_problem_doc already filters UNKNOWN
        ds.error_files.append(doc)
    return ds


def match_documents(docs: list[ExtractedDocument]) -> list[DocumentSet]:
    settings = get_settings().get("matching", {})
    fuzzy_threshold = settings.get("fuzzy_threshold", 85)

    error_sets: list[DocumentSet] = []
    groupable: list[ExtractedDocument] = []

    for doc in docs:
        if _is_problem_doc(doc):
            error_sets.append(_make_error_set(doc))
        elif not doc.reference_candidates:
            error_sets.append(_make_missing_reference_set(doc))
        else:
            groupable.append(doc)

    n = len(groupable)
    uf = _UnionFind(n)

    # --- exact (case-insensitive) match pass ---
    candidate_to_indices: dict[str, list[int]] = defaultdict(list)
    for i, doc in enumerate(groupable):
        for c in doc.reference_candidates:
            candidate_to_indices[_normalize_candidate(c)].append(i)
    for indices in candidate_to_indices.values():
        for other in indices[1:]:
            uf.union(indices[0], other)

    # --- fuzzy fallback pass, only across clusters that didn't already merge ---
    clusters_before_fuzzy: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        clusters_before_fuzzy[uf.find(i)].append(i)

    # Fuzzy tolerance is meant to catch OCR/typo noise on the short,
    # human-facing merchant-style reference code (~10 chars, e.g.
    # "76NQZZMDK2") — NOT on long structured identifiers like a bank's
    # "FT<...>_<date>" transaction code, where two *different*
    # transactions on the same day are naturally >90% similar and would
    # otherwise be wrongly merged. So only short candidates participate.
    _FUZZY_MAX_LEN = 14
    cluster_ids = list(clusters_before_fuzzy.keys())
    cluster_candidates: dict[int, set[str]] = {
        cid: {
            _normalize_candidate(c)
            for idx in idxs
            for c in groupable[idx].reference_candidates
            if len(c) <= _FUZZY_MAX_LEN
        }
        for cid, idxs in clusters_before_fuzzy.items()
    }
    for a_pos in range(len(cluster_ids)):
        for b_pos in range(a_pos + 1, len(cluster_ids)):
            cid_a, cid_b = cluster_ids[a_pos], cluster_ids[b_pos]
            if uf.find(cid_a) == uf.find(cid_b):
                continue
            best = 0
            for ca in cluster_candidates[cid_a]:
                for cb in cluster_candidates[cid_b]:
                    score = fuzz.ratio(ca, cb)
                    if score > best:
                        best = score
            if best >= fuzzy_threshold:
                log.info("Fuzzy-matched reference clusters (score=%s): %s <-> %s", best, cid_a, cid_b)
                uf.union(cid_a, cid_b)

    # --- materialize clusters ---
    final_clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        final_clusters[uf.find(i)].append(i)

    result_sets: list[DocumentSet] = []
    for indices in final_clusters.values():
        cluster_docs = [groupable[i] for i in indices]
        result_sets.append(_build_document_set(cluster_docs))

    result_sets.extend(error_sets)
    return result_sets


def _canonical_reference(cluster_docs: list[ExtractedDocument]) -> str:
    counter = Counter(
        _normalize_candidate(c) for d in cluster_docs for c in d.reference_candidates
    )
    return counter.most_common(1)[0][0]


def _build_document_set(cluster_docs: list[ExtractedDocument]) -> DocumentSet:
    reference = _canonical_reference(cluster_docs)
    ds = DocumentSet(reference=reference)

    for doc in cluster_docs:
        doc.reference = reference
        slot = _SLOT_BY_DOC_TYPE[doc.doc_type]
        if getattr(ds, slot) is None:
            setattr(ds, slot, doc)
        else:
            getattr(ds, f"duplicate_{slot}").append(doc)

    has_duplicates = bool(ds.duplicate_facebook or ds.duplicate_vat_invoice or ds.duplicate_bank_debit)
    present_count = sum(1 for slot in ("facebook", "vat_invoice", "bank_debit") if getattr(ds, slot) is not None)

    issues: list[str] = []
    if has_duplicates:
        ds.completeness = CompletenessStatus.DUPLICATE
        issues.append("DUPLICATE")
    elif present_count == 3:
        ds.completeness = CompletenessStatus.COMPLETE
    else:
        ds.completeness = CompletenessStatus.INCOMPLETE
        issues.append("INCOMPLETE")

    ds.issues = issues
    return ds
