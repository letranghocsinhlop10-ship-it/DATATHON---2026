from decimal import Decimal

from app.extraction.base import normalize_amount, normalize_date, normalize_tax_code, is_standard_vn_tax_code
from app.ingest import process_pdf_file
from app.models.schema import DocType
from tests.fixtures.generate_sample_pdfs import (
    make_bank_debit_note,
    make_facebook_bill,
    make_scanned_blank_pdf,
    make_vat_invoice,
)


# ---- base helpers -----------------------------------------------------

def test_normalize_amount_dot_thousands():
    assert normalize_amount("63.337", "VND") == Decimal("63337")


def test_normalize_amount_comma_thousands():
    assert normalize_amount("97,079", "VND") == Decimal("97079")


def test_normalize_amount_xml_style_grouping():
    assert normalize_amount("633.000", "VND") == Decimal("633000")


def test_normalize_amount_foreign_currency_decimal():
    assert normalize_amount("1,234.56", "USD") == Decimal("1234.56")


def test_normalize_amount_none_on_garbage():
    assert normalize_amount("", "VND") is None
    assert normalize_amount(None, "VND") is None


def test_normalize_date_vn_long_form_with_time():
    d = normalize_date("18:00 24 tháng 7, 2026")
    assert d is not None and d.isoformat() == "2026-07-24"


def test_normalize_date_slash_form():
    d = normalize_date("25/07/2026")
    assert d.isoformat() == "2026-07-25"


def test_normalize_date_iso():
    d = normalize_date("2026-07-24")
    assert d.isoformat() == "2026-07-24"


def test_normalize_tax_code_and_validity():
    assert normalize_tax_code("0110382640") == "0110382640"
    assert is_standard_vn_tax_code("0110382640") is True
    assert is_standard_vn_tax_code("01-1038264-0") is False  # foreign-contractor shape


# ---- end-to-end extractor tests on synthetic PDFs ----------------------

def test_facebook_extraction_end_to_end(tmp_path):
    path = make_facebook_bill(tmp_path / "fb.pdf")
    doc = process_pdf_file(path, source_role_folder="facebook")

    assert not doc.is_error
    assert doc.doc_type == DocType.FACEBOOK
    assert "76NQZZMDK2" in doc.reference_candidates
    assert doc.invoice_number == "FBADS-445-106372463"
    assert doc.total_amount == Decimal("63337")
    assert doc.amount_before_vat == Decimal("57579")
    assert doc.vat_amount == Decimal("5758")
    assert doc.vat_rate == "10%"
    assert doc.invoice_date.isoformat() == "2026-07-24"
    assert doc.tax_code == "01-1038264-0"


def test_bank_debit_extraction_end_to_end(tmp_path):
    path = make_bank_debit_note(tmp_path / "bank.pdf")
    doc = process_pdf_file(path, source_role_folder="bank")

    assert not doc.is_error
    assert doc.doc_type == DocType.BANK_DEBIT
    assert "76NQZZMDK2" in doc.reference_candidates  # embedded FACEBK code
    assert "FT26205136372705" in doc.reference_candidates  # explicit transaction code
    assert doc.total_amount == Decimal("63337")
    assert doc.transaction_date.isoformat() == "2026-07-25"
    assert doc.bank_info and "VPBANK" in doc.bank_info


def test_vat_invoice_extraction_with_xml_sidecar(tmp_path):
    pdf_path = tmp_path / "vat.pdf"
    xml_path = tmp_path / "vat.xml"
    make_vat_invoice(pdf_path, xml_path)
    doc = process_pdf_file(pdf_path, source_role_folder="vat")

    assert not doc.is_error
    assert doc.doc_type == DocType.VAT_INVOICE
    assert doc.used_xml_sidecar is True
    # amounts must come from XML (633.000 -> 633000), not the ambiguous PDF text
    assert doc.amount_before_vat == Decimal("633000")
    assert doc.vat_amount == Decimal("63000")
    assert doc.total_amount == Decimal("696000")
    assert doc.tax_code == "0110382640"
    assert doc.seller_tax_code == "0100233583"
    # reference + payment detail must come from PDF (shape-based), not XML
    assert "FT26205034015973_20260724" in doc.reference_candidates
    assert "76NQZZMDK2" in doc.reference_candidates
    assert doc.description and "FACEBK" in doc.description


def test_vat_invoice_extraction_without_xml_falls_back_to_pdf(tmp_path):
    pdf_path = tmp_path / "vat_no_xml.pdf"
    make_vat_invoice(pdf_path, xml_path=None, include_xml=False)
    doc = process_pdf_file(pdf_path, source_role_folder="vat")

    assert not doc.is_error
    assert doc.used_xml_sidecar is False
    assert any("Không có XML" in w for w in doc.warnings)
    # reference extraction must still work (shape-based, PDF-only anyway)
    assert "FT26205034015973_20260724" in doc.reference_candidates


def test_no_text_layer_without_ocr_marks_warning_not_crash(tmp_path):
    path = make_scanned_blank_pdf(tmp_path / "scan.pdf")
    doc = process_pdf_file(path, source_role_folder="bank")
    # Environment has no Tesseract installed -> should degrade gracefully,
    # never raise, and end up UNKNOWN/ERROR rather than crash the batch.
    assert doc.is_error is True
    assert doc.error_reason
