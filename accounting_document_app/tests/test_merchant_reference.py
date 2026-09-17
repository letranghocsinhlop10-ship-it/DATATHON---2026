"""Test bóc reference nhà cung cấp khỏi diễn giải ngân hàng.

Đây là nơi dễ lấy nhầm nhất: trong cùng một câu có số thẻ, mã giao dịch và
reference. Lấy nhầm = ghép sai hồ sơ kế toán.
"""

from __future__ import annotations

import pytest

from app.config_loader import MerchantConfig
from app.extractors.merchant_reference import (
    extract_card_last4,
    extract_merchant_reference,
)
from app.models.enums import FieldMethod
from app.models.extracted_field import ExtractedField

MERCHANT = MerchantConfig(anchors=("FACEBK", "FACEBOOK"), expected_suffix="DUBLIN IE")
PATTERN = r"^[A-Z0-9]{8,16}$"


def _detail(text: str) -> ExtractedField:
    return ExtractedField(field_name="payment_detail", value=text, rule_id="test.detail")


def _reference(text: str):
    return extract_merchant_reference(_detail(text), MERCHANT, reference_pattern=PATTERN)


class TestNeoVaoTuKhoaNhaCungCap:
    def test_dien_giai_debit_note(self):
        text = "So the 1111xxxx1234 GD thanh toan tai FACEBK ABCD1234EF DUBLIN IE"
        assert _reference(text).value == "ABCD1234EF"

    def test_dien_giai_hoa_don_thieu_dau_cach(self):
        """Hoá đơn GTGT ghi 'thanh toantai' — regex không được phụ thuộc cụm này."""
        text = "So the 1111xxxx1234 GD thanh toantai FACEBK ABCD1234EF DUBLIN IE"
        assert _reference(text).value == "ABCD1234EF"

    def test_van_lay_duoc_khi_duoi_khac_ky_vong(self):
        """Đuôi là KỲ VỌNG ĐƯỢC KIỂM TRA, không phải điều kiện bắt buộc."""
        text = "So the 1111xxxx1234 GD thanh toan tai FACEBK ABCD1234EF fb me ads IE"
        result = _reference(text)
        assert result.value == "ABCD1234EF"
        assert result.error == "UNEXPECTED_MERCHANT_SUFFIX"

    def test_duoi_dung_ky_vong_thi_khong_canh_bao(self):
        text = "GD thanh toan tai FACEBK ABCD1234EF DUBLIN IE"
        assert _reference(text).error is None

    def test_ho_tro_nhieu_tu_khoa_neo(self):
        text = "GD thanh toan tai FACEBOOK ABCD1234EF DUBLIN IE"
        assert _reference(text).value == "ABCD1234EF"


class TestKhongLayNham:
    def test_khong_lay_so_the(self):
        text = "So the 1111xxxx1234 GD thanh toan tai FACEBK ABCD1234EF DUBLIN IE"
        assert _reference(text).value != "1111xxxx1234"

    def test_khong_lay_ma_giao_dich_vpbank(self):
        text = "FT26000000000001 GD thanh toan tai FACEBK ABCD1234EF DUBLIN IE"
        assert _reference(text).value == "ABCD1234EF"

    def test_khong_co_tu_khoa_neo_thi_tra_none(self):
        text = "So the 1111xxxx1234 GD thanh toan tai SHOPEE ABCD1234EF"
        result = _reference(text)
        assert result.value is None
        assert result.error == "MERCHANT_ANCHOR_NOT_FOUND"

    def test_nhieu_reference_khac_nhau_thi_khong_tu_chon(self):
        text = "FACEBK ABCD1234EF DUBLIN IE va FACEBK ZZZZ9999YY DUBLIN IE"
        result = _reference(text)
        assert result.value is None
        assert result.error == "AMBIGUOUS_MATCH"

    def test_cung_mot_reference_lap_lai_thi_van_lay_duoc(self):
        text = "FACEBK ABCD1234EF DUBLIN IE ... FACEBK ABCD1234EF DUBLIN IE"
        assert _reference(text).value == "ABCD1234EF"


class TestChuanHoa:
    def test_chu_thuong_duoc_viet_hoa(self):
        text = "GD thanh toan tai FACEBK abcd1234ef DUBLIN IE"
        assert _reference(text).value == "ABCD1234EF"

    def test_khong_co_dien_giai_thi_bao_loi_ro_rang(self):
        empty = ExtractedField.missing("payment_detail")
        result = extract_merchant_reference(empty, MERCHANT, reference_pattern=PATTERN)
        assert result.value is None
        assert result.error == "NO_PAYMENT_DETAIL"


class TestCardLast4:
    def test_lay_bon_so_cuoi(self):
        text = "So the 1111xxxx1234 GD thanh toan tai FACEBK ABCD1234EF"
        result = extract_card_last4(_detail(text))
        assert result.value == "1234"
        assert result.method is FieldMethod.DERIVED

    def test_khong_co_thi_tra_none(self):
        result = extract_card_last4(_detail("GD thanh toan tai FACEBK ABCD1234EF"))
        assert result.value is None
        assert result.error == "NOT_FOUND"

    @pytest.mark.parametrize("masked", ["1111xxxx1234", "1111XXXX1234", "1111****1234"])
    def test_cac_kieu_che_so_the(self, masked):
        result = extract_card_last4(_detail(f"So the {masked} GD thanh toan"))
        assert result.value == "1234"
