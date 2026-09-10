from decimal import Decimal

import pytest
from openpyxl import Workbook

from app.models.schema import CompletenessStatus, DocType, DocumentSet, ExtractedDocument
from app.organizing.categorizer import categorize
from app.reference_list.loader import ReferenceListFormatError, load_reference_list
from app.reference_list.merge import merge_reference_list
from app.validation.engine import validate_and_score


def _write_xlsx(path, headers, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


# ---- loader --------------------------------------------------------

def test_loader_reads_vietnamese_headers(tmp_path):
    path = _write_xlsx(
        tmp_path / "list.xlsx",
        ["Số tham chiếu", "Số tiền", "Ghi chú"],
        [["ABC123", 63337, "Facebook Q3"], ["DEF456", None, None]],
    )
    entries = load_reference_list(path)
    assert len(entries) == 2
    assert entries[0].reference == "ABC123"
    assert entries[0].expected_amount == Decimal("63337")
    assert entries[0].notes == "Facebook Q3"
    assert entries[1].reference == "DEF456"
    assert entries[1].expected_amount is None


def test_loader_reads_english_headers_case_insensitive(tmp_path):
    path = _write_xlsx(
        tmp_path / "list2.xlsx", ["Reference Number", "Amount"], [["XYZ789", "1,234"]]
    )
    entries = load_reference_list(path)
    assert entries[0].reference == "XYZ789"
    assert entries[0].expected_amount == Decimal("1234")


def test_loader_skips_empty_reference_rows(tmp_path):
    path = _write_xlsx(tmp_path / "list3.xlsx", ["Reference"], [["ABC1"], [None], [""], ["ABC2"]])
    entries = load_reference_list(path)
    assert [e.reference for e in entries] == ["ABC1", "ABC2"]


def test_loader_raises_when_no_reference_column(tmp_path):
    path = _write_xlsx(tmp_path / "bad.xlsx", ["Foo", "Bar"], [["1", "2"]])
    with pytest.raises(ReferenceListFormatError):
        load_reference_list(path)


# ---- merge ----------------------------------------------------------

def _doc(doc_type, **kwargs) -> ExtractedDocument:
    defaults = dict(source_file=f"/tmp/{doc_type.value}.pdf")
    defaults.update(kwargs)
    return ExtractedDocument(doc_type=doc_type, **defaults)


def _existing_set(reference="ABC123", amount="63337") -> DocumentSet:
    fb = _doc(DocType.FACEBOOK, reference_candidates=[reference], total_amount=Decimal(amount))
    return DocumentSet(reference=reference, facebook=fb, completeness=CompletenessStatus.INCOMPLETE)


def test_merge_marks_found_when_reference_matches():
    from app.models.schema import ReferenceListEntry

    ds = _existing_set()
    entry = ReferenceListEntry(reference="ABC123")
    result = merge_reference_list([ds], [entry])
    assert len(result) == 1
    assert result[0].reference_list_status == "FOUND"


def test_merge_flags_amount_mismatch():
    from app.models.schema import ReferenceListEntry

    ds = _existing_set(amount="63337")
    entry = ReferenceListEntry(reference="ABC123", expected_amount=Decimal("999999"))
    result = merge_reference_list([ds], [entry])
    assert result[0].reference_list_status == "AMOUNT_MISMATCH"
    assert "REFERENCE_LIST_AMOUNT_MISMATCH" in result[0].issues


def test_merge_amount_within_tolerance_is_found():
    from app.models.schema import ReferenceListEntry

    ds = _existing_set(amount="63337")
    entry = ReferenceListEntry(reference="ABC123", expected_amount=Decimal("63400"))  # ~0.1% off
    result = merge_reference_list([ds], [entry])
    assert result[0].reference_list_status == "FOUND"


def test_merge_creates_synthetic_set_when_not_found():
    from app.models.schema import ReferenceListEntry

    ds = _existing_set(reference="ABC123")
    entry = ReferenceListEntry(reference="NOWHERE999", source_file="list.xlsx", row_number=5)
    result = merge_reference_list([ds], [entry])
    assert len(result) == 2
    new_ds = next(s for s in result if s.reference == "NOWHERE999")
    assert new_ds.reference_list_status == "NOT_FOUND"
    assert "MISSING_ALL_DOCUMENTS" in new_ds.issues
    assert new_ds.facebook is None and new_ds.vat_invoice is None and new_ds.bank_debit is None


def test_merge_no_entries_is_noop():
    ds = _existing_set()
    result = merge_reference_list([ds], [])
    assert result == [ds]
    assert ds.reference_list_status is None


def test_merge_fuzzy_matches_short_code_typo():
    from app.models.schema import ReferenceListEntry

    ds = _existing_set(reference="76NQZZMDK2")
    entry = ReferenceListEntry(reference="76NQZZMDKZ")  # 1-char OCR-style typo
    result = merge_reference_list([ds], [entry])
    assert len(result) == 1
    assert result[0].reference_list_status == "FOUND"


# ---- categorizer routing --------------------------------------------

def test_missing_all_documents_routes_to_its_own_category():
    ds = DocumentSet(
        reference="NOWHERE1",
        completeness=CompletenessStatus.INCOMPLETE,
        issues=["MISSING_ALL_DOCUMENTS"],
        reference_list_status="NOT_FOUND",
    )
    ds = categorize(validate_and_score(ds))
    assert ds.category == "09_MISSING_ALL_DOCUMENTS"


def test_reference_list_amount_mismatch_routes_to_amount_mismatch_category():
    ds = _existing_set(amount="63337")
    ds.facebook.tax_code = "0110382640"
    ds.facebook.payment_method = "Card"
    ds.vat_invoice = _doc(
        DocType.VAT_INVOICE, reference_candidates=["ABC123"], total_amount=Decimal("63337"), tax_code="0110382640"
    )
    ds.bank_debit = _doc(
        DocType.BANK_DEBIT, reference_candidates=["ABC123"], total_amount=Decimal("63337"), payment_method="Card"
    )
    ds.reference_list_status = "AMOUNT_MISMATCH"
    ds.issues = ["REFERENCE_LIST_AMOUNT_MISMATCH"]
    ds = categorize(validate_and_score(ds))
    assert ds.category == "05_AMOUNT_MISMATCH"
