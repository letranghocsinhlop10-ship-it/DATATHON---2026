from datetime import date
from decimal import Decimal

from app.models.schema import DocType, DocumentSet, ExtractedDocument, MatchResult
from app.reconciliation.engine import reconcile


def _doc(doc_type, **kwargs) -> ExtractedDocument:
    defaults = dict(source_file=f"/tmp/{doc_type.value}.pdf")
    defaults.update(kwargs)
    return ExtractedDocument(doc_type=doc_type, **defaults)


def _full_set(**overrides) -> DocumentSet:
    fb = _doc(
        DocType.FACEBOOK,
        reference_candidates=["ABC123"],
        total_amount=Decimal("63337"),
        invoice_date=date(2026, 7, 24),
        tax_code="0110382640",
        payment_method="MasterCard **** 4966",
        invoice_number="FBADS-1",
    )
    vat = _doc(
        DocType.VAT_INVOICE,
        reference_candidates=["ABC123"],
        total_amount=Decimal("63337"),
        invoice_date=date(2026, 7, 24),
        tax_code="0110382640",
        invoice_number="K26TSA-001",
    )
    bank = _doc(
        DocType.BANK_DEBIT,
        reference_candidates=["ABC123"],
        total_amount=Decimal("63337"),
        transaction_date=date(2026, 7, 25),
        payment_method="Thẻ 5223xx4966",
    )
    ds = DocumentSet(reference="ABC123", facebook=fb, vat_invoice=vat, bank_debit=bank)
    for k, v in overrides.items():
        setattr(ds, k, v)
    return ds


def test_full_match_on_all_criteria():
    ds = _full_set()
    result = reconcile(ds)
    assert result["reference"].result == MatchResult.MATCH
    assert result["amount"].result == MatchResult.MATCH
    assert result["date"].result == MatchResult.MATCH  # 24th vs 25th within 5-day tolerance
    assert result["tax_code"].result == MatchResult.MATCH
    assert result["payment_method"].result == MatchResult.MATCH  # shared last-4 digits "4966"
    assert result["invoice_info"].result == MatchResult.MATCH  # both have an invoice number


def test_amount_mismatch_beyond_tolerance():
    ds = _full_set()
    # make every pair disagree so this is unambiguously MISMATCH, not
    # PARTIAL_MATCH (fb/vat would otherwise still agree with each other)
    ds.vat_invoice.total_amount = Decimal("500000")
    ds.bank_debit.total_amount = Decimal("100000")  # way off from 63337
    result = reconcile(ds)
    assert result["amount"].result == MatchResult.MISMATCH


def test_amount_within_tolerance_is_match():
    ds = _full_set()
    ds.bank_debit.total_amount = Decimal("63400")  # ~0.1% off, within 1% tolerance
    result = reconcile(ds)
    assert result["amount"].result == MatchResult.MATCH


def test_date_beyond_tolerance_is_mismatch():
    ds = _full_set()
    ds.vat_invoice.invoice_date = date(2026, 6, 1)
    ds.bank_debit.transaction_date = date(2026, 8, 15)  # weeks later, and off from vat too
    result = reconcile(ds)
    assert result["date"].result == MatchResult.MISMATCH


def test_tax_code_missing_on_one_doc_is_missing_result():
    ds = _full_set()
    ds.vat_invoice.tax_code = None
    result = reconcile(ds)
    assert result["tax_code"].result == MatchResult.MISSING


def test_reference_mismatch_when_no_common_candidate():
    ds = _full_set()
    ds.vat_invoice.reference_candidates = ["YYY888"]
    ds.bank_debit.reference_candidates = ["ZZZ999"]
    result = reconcile(ds)
    assert result["reference"].result == MatchResult.MISMATCH


def test_reference_partial_match_when_only_two_of_three_agree():
    ds = _full_set()
    ds.bank_debit.reference_candidates = ["ZZZ999"]
    result = reconcile(ds)
    assert result["reference"].result == MatchResult.PARTIAL_MATCH


def test_partial_match_when_only_some_agree():
    ds = _full_set()
    ds.bank_debit.total_amount = Decimal("999999")  # disagrees with fb & vat, which still agree
    result = reconcile(ds)
    assert result["amount"].result == MatchResult.PARTIAL_MATCH


def test_only_one_doc_present_everything_missing():
    fb = _doc(DocType.FACEBOOK, reference_candidates=["ABC123"], total_amount=Decimal("1000"))
    ds = DocumentSet(reference="ABC123", facebook=fb)
    result = reconcile(ds)
    assert all(r.result == MatchResult.MISSING for r in result.values())


def test_invoice_info_missing_when_vat_lacks_invoice_number():
    ds = _full_set()
    ds.vat_invoice.invoice_number = None
    result = reconcile(ds)
    assert result["invoice_info"].result == MatchResult.MISSING
