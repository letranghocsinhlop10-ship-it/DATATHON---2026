"""Test parse sao kê VPBank nhiều giao dịch.

LƯU Ý: chưa có file sao kê thật (xem cảnh báo ở đầu
``config/bank_statement_rules.yaml``) — dữ liệu dưới đây tự dựng, đúng hình
dạng ``row_pattern`` hiện tại. Khi có file thật, test này là nơi đầu tiên
cần cập nhật lại cùng với ``row_pattern``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.bank_statement_parser import BankStatementParser
from pdf_synth import FONT, write_pdf

pytestmark = pytest.mark.skipif(FONT is None, reason="Không tìm thấy font DejaVu Sans trong môi trường này")


@pytest.fixture
def statement_pdf(tmp_path):
    path = tmp_path / "sao_ke.pdf"
    lines = [
        "SAO KE TAI KHOAN / STATEMENT OF ACCOUNT",
        "FT26000000000001 15/08/2026 10:00:00 GD thanh toan tai FACEBK *ABCD1234EF DUBLIN IE 2,558,510 50,441,490",
        "FT26000000000002 16/08/2026 11:15:00 Chuyen khoan noi bo khong lien quan 1,000,000 51,441,490",
    ]
    write_pdf(path, [lines])
    return path


class TestParseTungDong:
    def test_chi_lay_dong_khop_regex(self, statement_pdf):
        parser = BankStatementParser()
        transactions = parser.parse(statement_pdf)
        assert len(transactions) == 2  # dòng tiêu đề không khớp -> bị bỏ qua

    def test_dong_dau_co_du_truong(self, statement_pdf):
        parser = BankStatementParser()
        transactions = parser.parse(statement_pdf)
        first = transactions[0]
        assert first.transaction_id == "FT26000000000001"
        assert first.value_date.isoformat() == "2026-08-15"
        assert first.transaction_time == "10:00:00"
        assert first.debit_amount == Decimal("2558510")
        assert first.running_balance == Decimal("50441490")
        assert first.facebook_reference == "ABCD1234EF"
        assert "FACEBK" in first.transaction_detail

    def test_dong_khong_lien_quan_facebook_thi_reference_none(self, statement_pdf):
        parser = BankStatementParser()
        transactions = parser.parse(statement_pdf)
        second = transactions[1]
        assert second.transaction_id == "FT26000000000002"
        assert second.facebook_reference is None

    def test_source_pdf_va_page_duoc_gan_dung(self, statement_pdf):
        parser = BankStatementParser()
        transactions = parser.parse(statement_pdf)
        for txn in transactions:
            assert txn.source_pdf == statement_pdf
            assert txn.source_page == 1


class TestNganHangKhongHoTro:
    def test_bank_la_khong_ton_tai_bao_loi_ro_rang(self):
        with pytest.raises(KeyError):
            BankStatementParser(bank="KHONG_TON_TAI")
