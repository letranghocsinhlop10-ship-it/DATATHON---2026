"""Test sắp xếp PDF theo Facebook Payment Group (§J)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pymupdf
import pytest

from app.core.bank_statement_parser import BankTransaction
from app.exporters.payment_group_organizer import PaymentGroupOrganizer
from app.models.enums import DocumentType, PaymentGroupStatus
from app.models.facebook_payment_group import FacebookPaymentGroup
from matching_helpers import make_doc
from pdf_synth import FONT, write_pdf

pytestmark = pytest.mark.skipif(FONT is None, reason="Không tìm thấy font DejaVu Sans trong môi trường này")


def _doc_with_file(tmp_path, document_type, name, **fields):
    path = tmp_path / "src" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    write_pdf(path, [[f"noi dung {name}"]])
    doc = make_doc(document_type, **fields)
    doc.file_path = path
    return doc


class TestBoDuDuDayDu:
    def test_dung_thu_tu_va_ten_file(self, tmp_path):
        bill = _doc_with_file(tmp_path, DocumentType.META_INVOICE, "bill.pdf", reference_number="ABCD1234EF")
        main = _doc_with_file(tmp_path, DocumentType.VPBANK_DEBIT_NOTE, "note.pdf", meta_reference="ABCD1234EF")
        fee = _doc_with_file(tmp_path, DocumentType.VIETINBANK_DEBIT_ADVICE, "fee.pdf", facebook_reference="ABCD1234EF")

        group = FacebookPaymentGroup(
            group_code="FB_ABCD1234EF_2026-08-01",
            facebook_reference="ABCD1234EF",
            transaction_date=date(2026, 8, 1),
            facebook_bill=bill,
            main_payment=main,
            fees=[fee],
            status=PaymentGroupStatus.MATCHED_HIGH,
            reason="test",
        )

        organizer = PaymentGroupOrganizer(tmp_path / "OUTPUT")
        result = organizer.organize([group])

        folder = tmp_path / "OUTPUT" / "FB_ABCD1234EF_2026-08-01"
        assert (folder / "01_Facebook_Bill.pdf").is_file()
        assert (folder / "02_VPBank_Debit_Note.pdf").is_file()
        assert (folder / "03_Bank_Fee.pdf").is_file()
        assert (folder / "_manifest.txt").is_file()
        assert result.copied_files == 3

    def test_file_goc_khong_bi_sua(self, tmp_path):
        bill = _doc_with_file(tmp_path, DocumentType.META_INVOICE, "bill.pdf", reference_number="ABCD1234EF")
        original_bytes = bill.file_path.read_bytes()
        group = FacebookPaymentGroup(
            group_code="FB_ABCD1234EF_2026-08-01", facebook_bill=bill, status=PaymentGroupStatus.UNMATCHED,
        )
        PaymentGroupOrganizer(tmp_path / "OUTPUT").organize([group])
        assert bill.file_path.read_bytes() == original_bytes


class TestFileGop:
    def test_gop_khi_co_tu_hai_file_tro_len(self, tmp_path):
        bill = _doc_with_file(tmp_path, DocumentType.META_INVOICE, "bill.pdf", reference_number="ABCD1234EF")
        main = _doc_with_file(tmp_path, DocumentType.VPBANK_DEBIT_NOTE, "note.pdf", meta_reference="ABCD1234EF")
        group = FacebookPaymentGroup(
            group_code="FB_ABCD1234EF_2026-08-01",
            facebook_bill=bill, main_payment=main, status=PaymentGroupStatus.MATCHED_HIGH,
        )
        result = PaymentGroupOrganizer(tmp_path / "OUTPUT").organize([group])
        merged = tmp_path / "OUTPUT" / "FB_ABCD1234EF_2026-08-01" / "00_FULL_DOCUMENT_SET.pdf"
        assert merged.is_file()
        assert result.merged_files == 1
        doc = pymupdf.open(merged)
        try:
            assert doc.page_count == 2
        finally:
            doc.close()

    def test_khong_gop_khi_chi_co_mot_file(self, tmp_path):
        bill = _doc_with_file(tmp_path, DocumentType.META_INVOICE, "bill.pdf", reference_number="ABCD1234EF")
        group = FacebookPaymentGroup(group_code="FB_X", facebook_bill=bill, status=PaymentGroupStatus.UNMATCHED)
        result = PaymentGroupOrganizer(tmp_path / "OUTPUT").organize([group])
        assert result.merged_files == 0
        assert not (tmp_path / "OUTPUT" / "FB_X" / "00_FULL_DOCUMENT_SET.pdf").exists()


class TestSinhPdfTrichXuatKhiThieuPhieuGoc:
    def test_co_dong_sao_ke_nhung_khong_co_phieu_goc(self, tmp_path):
        bill = _doc_with_file(tmp_path, DocumentType.META_INVOICE, "bill.pdf", reference_number="ABCD1234EF")
        row = BankTransaction(
            stt=1, transaction_id="FT1", value_date=date(2026, 8, 1), transaction_time="10:00:00",
            debit_amount=Decimal("100000"), credit_amount=None, transaction_detail="FACEBK *ABCD1234EF",
            running_balance=Decimal("1"), facebook_reference="ABCD1234EF",
            source_pdf=tmp_path / "sao_ke.pdf", source_page=1,
        )
        group = FacebookPaymentGroup(
            group_code="FB_ABCD1234EF_2026-08-01", facebook_bill=bill, main_payment=None,
            statement_rows=[row], status=PaymentGroupStatus.MATCHED,
        )
        result = PaymentGroupOrganizer(tmp_path / "OUTPUT").organize([group])

        folder = tmp_path / "OUTPUT" / "FB_ABCD1234EF_2026-08-01"
        assert (folder / "02_Bank_Statement_Extract.pdf").is_file()
        assert result.generated_extracts == 1
        doc = pymupdf.open(folder / "02_Bank_Statement_Extract.pdf")
        try:
            text = doc[0].get_text("text")
        finally:
            doc.close()
        assert "KHÔNG PHẢI CHỨNG TỪ NGÂN HÀNG GỐC" in text


class TestNeedsReviewDiVaoThuMucRieng:
    def test_needs_review_nam_trong_thu_muc_needs_review(self, tmp_path):
        bill = _doc_with_file(tmp_path, DocumentType.META_INVOICE, "bill.pdf", reference_number="ABCD1234EF")
        group = FacebookPaymentGroup(
            group_code="FB_ABCD1234EF_2026-08-01", facebook_bill=bill, status=PaymentGroupStatus.NEEDS_REVIEW,
        )
        result = PaymentGroupOrganizer(tmp_path / "OUTPUT").organize([group])
        assert (tmp_path / "OUTPUT" / "NEEDS_REVIEW" / "FB_ABCD1234EF_2026-08-01").is_dir()
