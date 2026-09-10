from app.classification.classifier import classify_text
from app.models.schema import DocType


def test_classify_facebook():
    text = "Hóa đơn thuế cho ABC\nMeta Platforms Ireland Limited\nMeta quảng cáo\nID tài khoản: 123"
    doc_type, scores = classify_text(text)
    assert doc_type == DocType.FACEBOOK


def test_classify_vat_invoice():
    text = "HÓA ĐƠN GIÁ TRỊ GIA TĂNG\nKý hiệu (Serial): K26TSA\nBản thể hiện của hóa đơn điện tử"
    doc_type, _ = classify_text(text)
    assert doc_type == DocType.VAT_INVOICE


def test_classify_bank_debit():
    text = "PHIẾU GIAO DỊCH GHI NỢ/DEBIT NOTE\nMã giao dịch/Transaction code: FT123\nDebit Account"
    doc_type, _ = classify_text(text)
    assert doc_type == DocType.BANK_DEBIT


def test_classify_unknown_for_unrelated_text():
    doc_type, scores = classify_text("Just some random unrelated document with no keywords.")
    assert doc_type == DocType.UNKNOWN
    assert all(v == 0 for v in scores.values())
