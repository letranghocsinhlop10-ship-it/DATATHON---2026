"""Test PDF trích xuất tự sinh từ sao kê — §I yêu cầu nghiệp vụ."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pymupdf

from app.core.bank_statement_parser import BankTransaction
from app.exporters.statement_extract_pdf import generate_statement_extract_pdf


def _txn(**overrides):
    base = dict(
        stt=1,
        transaction_id="FT1",
        value_date=date(2026, 8, 1),
        transaction_time="10:00:00",
        debit_amount=Decimal("2558510"),
        credit_amount=None,
        transaction_detail="GD thanh toan tai FACEBK *ABCD1234EF",
        running_balance=Decimal("1000000"),
        facebook_reference="ABCD1234EF",
        source_pdf=Path("sao_ke.pdf"),
        source_page=3,
    )
    base.update(overrides)
    return BankTransaction(**base)


class TestSinhPdfCanhBaoRoRang:
    def test_co_du_ba_dong_canh_bao(self, tmp_path):
        dest = tmp_path / "extract.pdf"
        generate_statement_extract_pdf(_txn(), dest)

        doc = pymupdf.open(dest)
        text = doc[0].get_text("text")
        doc.close()

        assert "TRÍCH XUẤT GIAO DỊCH TỪ SAO KÊ" in text
        assert "TỰ ĐỘNG TẠO BỞI ACCOUNTING DOCUMENT TOOL" in text
        assert "KHÔNG PHẢI CHỨNG TỪ NGÂN HÀNG GỐC" in text

    def test_co_du_thong_tin_giao_dich(self, tmp_path):
        dest = tmp_path / "extract.pdf"
        generate_statement_extract_pdf(_txn(), dest)

        doc = pymupdf.open(dest)
        text = doc[0].get_text("text")
        doc.close()

        assert "FT1" in text
        assert "ABCD1234EF" in text
        assert "sao_ke.pdf" in text
        assert "3" in text

    def test_chi_mot_trang(self, tmp_path):
        dest = tmp_path / "extract.pdf"
        generate_statement_extract_pdf(_txn(), dest)
        doc = pymupdf.open(dest)
        try:
            assert doc.page_count == 1
        finally:
            doc.close()

    def test_tao_thu_muc_cha_neu_chua_co(self, tmp_path):
        dest = tmp_path / "sub" / "dir" / "extract.pdf"
        generate_statement_extract_pdf(_txn(), dest)
        assert dest.is_file()
