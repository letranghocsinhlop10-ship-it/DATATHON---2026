"""Test đọc ngày từ ba định dạng xuất hiện trên chứng từ thật."""

from __future__ import annotations

from datetime import date

import pytest

from app.utils import date_utils


class TestParseDmy:
    def test_dinh_dang_chuan(self):
        assert date_utils.parse_dmy("01/08/2026") == date(2026, 8, 1)

    def test_lay_duoc_trong_cau_dai(self):
        assert date_utils.parse_dmy("Ngày/Transaction Date: 01/08/2026") == date(2026, 8, 1)

    def test_ngay_khong_hop_le(self):
        with pytest.raises(date_utils.DateParseError):
            date_utils.parse_dmy("32/13/2026")

    def test_khong_tim_thay(self):
        with pytest.raises(date_utils.DateParseError):
            date_utils.parse_dmy("không có ngày")


class TestParseVietnameseLongDate:
    def test_dang_chu_co_gio(self):
        assert date_utils.parse_vietnamese_long_date("15:10 1 tháng 8, 2026") == date(2026, 8, 1)

    def test_dang_chu_khong_dau_phay(self):
        assert date_utils.parse_vietnamese_long_date("30 tháng 7 2026") == date(2026, 7, 30)

    def test_khong_nham_voi_dd_mm_yyyy(self):
        with pytest.raises(date_utils.DateParseError):
            date_utils.parse_vietnamese_long_date("01/08/2026")


class TestParseCompactDate:
    def test_hau_to_cua_reference_ngan_hang(self):
        assert date_utils.parse_compact_date("FT26000000000001_20260801") == date(2026, 8, 1)

    def test_chuoi_so_thuan(self):
        assert date_utils.parse_compact_date("20260801") == date(2026, 8, 1)


class TestFormatDisplay:
    def test_hien_thi_kieu_viet_nam(self):
        assert date_utils.format_display(date(2026, 8, 1)) == "01/08/2026"

    def test_none_tra_chuoi_rong(self):
        assert date_utils.format_display(None) == ""
