from datetime import date
from decimal import Decimal

from app.models.schema import CompletenessStatus, DocType, DocumentSet, ExtractedDocument
from app.organizing.categorizer import categorize
from app.validation.engine import validate_and_score


def _doc(doc_type, **kwargs) -> ExtractedDocument:
    defaults = dict(source_file=f"/tmp/{doc_type.value}.pdf")
    defaults.update(kwargs)
    return ExtractedDocument(doc_type=doc_type, **defaults)


def _base_full_set() -> DocumentSet:
    fb = _doc(
        DocType.FACEBOOK, reference_candidates=["ABC123"], total_amount=Decimal("1000"),
        tax_code="0110382640", payment_method="Card", invoice_number="F1",
        invoice_date=date(2026, 1, 1), buyer="X", vat_amount=Decimal("100"), description="d",
    )
    vat = _doc(
        DocType.VAT_INVOICE, reference_candidates=["ABC123"], total_amount=Decimal("1000"),
        tax_code="0110382640", invoice_number="V1", invoice_date=date(2026, 1, 1), buyer="X",
        vat_amount=Decimal("100"), description="d",
    )
    bank = _doc(
        DocType.BANK_DEBIT, reference_candidates=["ABC123"], total_amount=Decimal("1000"),
        payment_method="Card", buyer="X", description="d",
    )
    return DocumentSet(reference="ABC123", facebook=fb, vat_invoice=vat, bank_debit=bank, completeness=CompletenessStatus.COMPLETE)


def test_valid_set_goes_to_01_valid():
    ds = validate_and_score(_base_full_set())
    ds = categorize(ds)
    assert ds.category == "01_VALID"


def test_missing_tax_code_routes_to_missing_tax_code_category():
    ds = _base_full_set()
    ds.facebook.tax_code = None
    ds.vat_invoice.tax_code = None
    ds = validate_and_score(ds)
    ds = categorize(ds)
    assert ds.category == "03_MISSING_TAX_CODE"
    assert "MISSING_TAX_CODE" in ds.issues


def test_payment_method_error_routes_correctly():
    ds = _base_full_set()
    ds.facebook.payment_method = None
    ds.bank_debit.payment_method = None
    ds = validate_and_score(ds)
    ds = categorize(ds)
    assert ds.category == "04_PAYMENT_METHOD_ERROR"


def test_amount_mismatch_routes_correctly():
    ds = _base_full_set()
    ds.vat_invoice.total_amount = Decimal("999999")
    ds.bank_debit.total_amount = Decimal("888888")
    ds = validate_and_score(ds)
    ds = categorize(ds)
    assert ds.category == "05_AMOUNT_MISMATCH"


def test_incomplete_routes_to_incomplete_category():
    ds = _base_full_set()
    ds.bank_debit = None
    ds.completeness = CompletenessStatus.INCOMPLETE
    ds.issues = ["INCOMPLETE"]
    ds = validate_and_score(ds)
    ds = categorize(ds)
    assert ds.category == "06_INCOMPLETE_DOCUMENT"


def test_duplicate_routes_before_other_issues():
    ds = _base_full_set()
    ds.facebook.tax_code = None  # would also trigger MISSING_TAX_CODE
    ds.vat_invoice.tax_code = None
    ds.duplicate_facebook = [_doc(DocType.FACEBOOK, reference_candidates=["ABC123"])]
    ds.completeness = CompletenessStatus.DUPLICATE
    ds.issues = ["DUPLICATE"]
    ds = validate_and_score(ds)
    ds = categorize(ds)
    # DUPLICATE has higher priority than MISSING_TAX_CODE in settings.yaml
    assert ds.category == "07_DUPLICATE"
    assert "MISSING_TAX_CODE" in ds.issues  # still recorded even though not the folder home


def test_error_set_routes_to_other_error():
    ds = DocumentSet(reference="ERROR__bad", completeness=CompletenessStatus.ERROR, issues=["ERROR"])
    ds = validate_and_score(ds)
    ds = categorize(ds)
    assert ds.category == "08_OTHER_ERROR"
