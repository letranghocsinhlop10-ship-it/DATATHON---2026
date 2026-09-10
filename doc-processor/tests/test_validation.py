from datetime import date
from decimal import Decimal

from app.models.schema import CheckResult, DocType, DocumentStatus, DocumentSet, ExtractedDocument
from app.validation.engine import validate_and_score


def _doc(doc_type, **kwargs) -> ExtractedDocument:
    defaults = dict(source_file=f"/tmp/{doc_type.value}.pdf")
    defaults.update(kwargs)
    return ExtractedDocument(doc_type=doc_type, **defaults)


def _valid_full_set() -> DocumentSet:
    fb = _doc(
        DocType.FACEBOOK,
        reference_candidates=["ABC123"],
        total_amount=Decimal("63337"),
        invoice_date=date(2026, 7, 24),
        tax_code="0110382640",
        payment_method="MasterCard **** 4966",
        invoice_number="FBADS-1",
        buyer="CONG TY ABC",
        vat_amount=Decimal("5758"),
        description="Meta quang cao",
    )
    vat = _doc(
        DocType.VAT_INVOICE,
        reference_candidates=["ABC123"],
        total_amount=Decimal("63337"),
        invoice_date=date(2026, 7, 24),
        tax_code="0110382640",
        invoice_number="K26TSA-001",
        buyer="CONG TY ABC",
        vat_amount=Decimal("5758"),
        description="Thanh toan facebook",
    )
    bank = _doc(
        DocType.BANK_DEBIT,
        reference_candidates=["ABC123"],
        total_amount=Decimal("63337"),
        transaction_date=date(2026, 7, 25),
        payment_method="Thẻ 5223xx4966",
        buyer="CONG TY ABC",
        description="GD FACEBK ABC123",
    )
    return DocumentSet(reference="ABC123", facebook=fb, vat_invoice=vat, bank_debit=bank)


def test_fully_valid_set_status_valid():
    ds = validate_and_score(_valid_full_set())
    assert ds.document_status == DocumentStatus.VALID
    assert all(item.result == CheckResult.PASS for item in ds.validation)


def test_missing_tax_code_fails_and_invalidates():
    ds = _valid_full_set()
    ds.facebook.tax_code = None
    ds.vat_invoice.tax_code = None
    ds = validate_and_score(ds)
    tax_code_rule = next(i for i in ds.validation if i.rule_id == "TAX_CODE_PRESENT")
    assert tax_code_rule.result == CheckResult.FAIL
    assert ds.document_status == DocumentStatus.INVALID


def test_incomplete_set_fails_set_complete_rule():
    ds = _valid_full_set()
    ds.bank_debit = None
    ds = validate_and_score(ds)
    rule = next(i for i in ds.validation if i.rule_id == "SET_COMPLETE")
    assert rule.result == CheckResult.FAIL
    assert ds.document_status == DocumentStatus.INVALID


def test_foreign_tax_code_format_is_warning_not_fail():
    ds = _valid_full_set()
    ds.facebook.tax_code = "01-1038264-0"  # foreign-contractor shape, still "present"
    ds.vat_invoice.tax_code = "01-1038264-0"
    ds = validate_and_score(ds)
    presence_rule = next(i for i in ds.validation if i.rule_id == "TAX_CODE_PRESENT")
    format_rule = next(i for i in ds.validation if i.rule_id == "TAX_CODE_FORMAT")
    assert presence_rule.result == CheckResult.PASS
    assert format_rule.result == CheckResult.WARNING
    assert ds.document_status == DocumentStatus.NEEDS_REVIEW


def test_reconciliation_mismatch_fails_validation():
    ds = _valid_full_set()
    ds.vat_invoice.total_amount = Decimal("999999999")
    ds.bank_debit.total_amount = Decimal("111111111")
    ds = validate_and_score(ds)
    rule = next(i for i in ds.validation if i.rule_id == "NO_RECONCILIATION_MISMATCH")
    assert rule.result == CheckResult.FAIL
    assert ds.document_status == DocumentStatus.INVALID


def test_synthetic_missing_reference_fails_reference_rule():
    fb = _doc(DocType.FACEBOOK, reference_candidates=[])
    ds = DocumentSet(reference="NOREF__somefile", facebook=fb)
    ds = validate_and_score(ds)
    rule = next(i for i in ds.validation if i.rule_id == "REFERENCE_PRESENT")
    assert rule.result == CheckResult.FAIL
    assert ds.document_status == DocumentStatus.INVALID


def test_not_found_when_no_relevant_doc_present():
    fb = _doc(DocType.FACEBOOK, reference_candidates=["X"], total_amount=Decimal("1"), payment_method="Card")
    ds = DocumentSet(reference="X", facebook=fb)  # no vat_invoice at all
    ds = validate_and_score(ds)
    # invoice_number rule only looks at facebook/vat_invoice roles; facebook
    # has none set here -> should be FAIL/WARNING not NOT_FOUND (facebook IS present)
    invoice_rule = next(i for i in ds.validation if i.rule_id == "INVOICE_NUMBER_PRESENT")
    assert invoice_rule.result == CheckResult.WARNING
