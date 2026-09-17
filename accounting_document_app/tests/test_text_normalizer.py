"""Test chuẩn hoá reference — bộ test QUAN TRỌNG NHẤT của dự án.

Một lỗi ở đây dẫn thẳng tới ghép sai chứng từ kế toán.
"""

from __future__ import annotations

import pytest

from app.core.text_normalizer import (
    flatten_whitespace,
    normalize_reference,
    normalize_tax_code,
    references_match,
)


class TestNormalizeReference:
    def test_uppercase_va_strip(self):
        assert normalize_reference(" 76nqzzmdk2 ").value == "76NQZZMDK2"

    def test_giu_nguyen_chuoi_da_chuan(self):
        assert normalize_reference("ABCD1234EF").value == "ABCD1234EF"

    def test_bóc_dau_cau_hai_dau_nhung_khong_boc_o_giua(self):
        assert normalize_reference("(ABCD1234EF).").value == "ABCD1234EF"
        # Dấu gạch ở GIỮA phải được giữ nguyên.
        assert normalize_reference("ABCD-1234EF").value == "ABCD-1234EF"

    def test_xoa_khoang_trang_ben_trong(self):
        assert normalize_reference("ABCD 1234 EF").value == "ABCD1234EF"

    def test_giu_khoang_trang_khi_tat_tuy_chon(self):
        result = normalize_reference("ABCD 1234", strip_inner_whitespace=False)
        assert result.value == "ABCD 1234"

    def test_chuoi_rong_tra_none(self):
        assert normalize_reference("").value is None
        assert normalize_reference("   ").value is None
        assert normalize_reference(None).value is None

    def test_loai_bo_ky_tu_vo_hinh(self):
        assert normalize_reference("ABCD​1234EF").value == "ABCD1234EF"

    def test_pattern_khong_hop_le_van_giu_nguyen_gia_tri(self):
        result = normalize_reference("AB1")
        assert result.value == "AB1"
        assert result.is_valid_format is False


class TestKhongBaoGioThayKyTuGiongNhau:
    """Các test này bảo vệ quy tắc quan trọng nhất: KHÔNG suy đoán ký tự."""

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("ABC12345", "ABCI2345"),   # I không thành 1
            ("ABC12345", "ABCl2345"),   # l thường không thành 1
            ("ABCO1234", "ABC01234"),   # O không thành 0
            ("ABCB1234", "ABC81234"),   # B không thành 8
            ("ABCS1234", "ABC51234"),   # S không thành 5
            ("ABCZ1234", "ABC21234"),   # Z không thành 2
        ],
    )
    def test_ky_tu_nhin_giong_nhau_van_khac_nhau(self, left, right):
        assert normalize_reference(left).value != normalize_reference(right).value


class TestReferencesMatch:
    def test_khop_khi_bang_nhau_tuyet_doi(self):
        a = normalize_reference("ABCD1234EF").value
        b = normalize_reference("abcd1234ef").value
        assert references_match(a, b) is True

    def test_khong_khop_khi_lech_mot_ky_tu(self):
        a = normalize_reference("ABCD1234EF").value
        b = normalize_reference("ABCD1234EG").value
        assert references_match(a, b) is False

    def test_khong_prefix_match(self):
        a = normalize_reference("ABCD1234EF").value
        b = normalize_reference("ABCD1234EF0").value
        assert references_match(a, b) is False

    def test_hai_none_khong_khop_nhau(self):
        assert references_match(None, None) is False

    def test_mot_ben_none_khong_khop(self):
        assert references_match("ABCD1234EF", None) is False


class TestNormalizeTaxCode:
    def test_bo_dau_gach_ngang(self):
        assert normalize_tax_code("01-0000000-1") == "0100000001"

    def test_giu_nguyen_chuoi_chi_co_so(self):
        assert normalize_tax_code("0100000001") == "0100000001"

    def test_hai_cach_viet_cung_mot_mst_thi_bang_nhau(self):
        assert normalize_tax_code("01-0000000-1") == normalize_tax_code("0100000001")

    def test_khong_con_chu_so_tra_none(self):
        assert normalize_tax_code("---") is None
        assert normalize_tax_code(None) is None


class TestFlattenWhitespace:
    def test_gop_xuong_dong(self):
        raw = "Diễn giải/Details: So the 1111xxxx1234 GD thanh toan\ntai FACEBK ABCD1234EF"
        assert "thanh toan tai FACEBK ABCD1234EF" in flatten_whitespace(raw)
