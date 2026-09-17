"""Test đọc số tiền — bảo vệ khỏi lỗi sai 1000 lần."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.utils.money_utils import (
    AmountAmbiguousError,
    AmountParseError,
    MoneyFormat,
    format_vnd,
    parse_amount,
    parse_percent,
)

META = MoneyFormat(thousands=".", decimal=",", currency_symbols=("₫", "VND"))
DEBIT = MoneyFormat(thousands=",", decimal=".", currency_symbols=("VND",))


class TestDinhDangKhacNhauGiuaChungTu:
    """Ba loại chứng từ trong cùng một bộ dùng dấu phân cách khác nhau."""

    def test_hoa_don_meta_dung_dau_cham(self):
        assert parse_amount("1.100.000 ₫", META) == Decimal("1100000")
        assert parse_amount("1.000.000 VND", META) == Decimal("1000000")

    def test_debit_note_dung_dau_phay(self):
        assert parse_amount("1,122,000 VND", DEBIT) == Decimal("1122000")

    def test_cung_mot_chuoi_doc_khac_nhau_theo_config(self):
        """``2.000`` là hai nghìn theo config Meta — đây chính là cái bẫy."""
        assert parse_amount("2.000", META) == Decimal("2000")
        with pytest.raises(AmountAmbiguousError):
            parse_amount("2.000", DEBIT)


class TestTuChoiDoan:
    def test_nhap_nhang_thi_bao_loi_chu_khong_doan(self):
        with pytest.raises(AmountAmbiguousError) as exc:
            parse_amount("2.531", DEBIT)
        assert exc.value.code == "AMOUNT_PARSE_AMBIGUOUS"

    def test_phan_nhom_hang_nghin_sai_thi_bao_loi(self):
        with pytest.raises(AmountParseError):
            parse_amount("1.23.456", META)

    def test_ky_tu_la_thi_bao_loi(self):
        with pytest.raises(AmountParseError):
            parse_amount("1.000.000 USD extra", META)

    def test_chuoi_rong_bao_loi(self):
        with pytest.raises(AmountParseError):
            parse_amount("", META)
        with pytest.raises(AmountParseError):
            parse_amount(None, META)


class TestGiaTriHopLe:
    def test_so_nho_khong_co_phan_cach(self):
        assert parse_amount("500", META) == Decimal("500")

    def test_thap_phan_that_su(self):
        assert parse_amount("1.234,56", META) == Decimal("1234.56")

    def test_so_am(self):
        assert parse_amount("-1.000", META) == Decimal("-1000")

    def test_khong_dung_float(self):
        assert isinstance(parse_amount("1.100.000", META), Decimal)


class TestChuoiTienKhepKin:
    """Kiểm chứng đẳng thức debit = meta_total + bank_fee_total."""

    def test_dang_thuc_khep_kin(self):
        meta_sub = parse_amount("1.000.000", META)
        meta_vat = parse_amount("100.000", META)
        meta_total = parse_amount("1.100.000", META)
        fee_sub = parse_amount("20.000", META)
        fee_vat = parse_amount("2.000", META)
        fee_total = parse_amount("22.000", META)
        debit = parse_amount("1,122,000", DEBIT)

        assert meta_sub + meta_vat == meta_total
        assert fee_sub + fee_vat == fee_total
        assert meta_total + fee_total == debit


class TestMoneyFormat:
    def test_khong_cho_phep_trung_dau_phan_cach(self):
        with pytest.raises(ValueError):
            MoneyFormat(thousands=".", decimal=".")


class TestParsePercent:
    def test_doc_thue_suat(self):
        assert parse_percent("10%") == Decimal("10")
        assert parse_percent("Thuế suất: 10 %") == Decimal("10")

    def test_thue_suat_thap_phan(self):
        assert parse_percent("8,5%") == Decimal("8.5")

    def test_khong_doc_duoc_bao_loi(self):
        with pytest.raises(AmountParseError):
            parse_percent("không có số")


class TestFormatVnd:
    def test_hien_thi_phan_cach_nghin(self):
        assert format_vnd(Decimal("1100000")) == "1.100.000"

    def test_none_tra_chuoi_rong(self):
        assert format_vnd(None) == ""
