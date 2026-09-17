"""Test extractor hoá đơn GTGT VPBank — loại có thứ tự text bị đảo."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.enums import DocumentType, FieldMethod
from helpers import make_content, make_context
from vat_layout import build_vat_page


def _extract(registry, extraction_config, app_settings):
    content = make_content([build_vat_page()], name="vat.pdf")
    ctx = make_context(content, DocumentType.VPBANK_VAT_INVOICE, extraction_config, app_settings)
    return registry.get(DocumentType.VPBANK_VAT_INVOICE).extract(ctx)


class TestBoCucBiDao:
    def test_text_tho_co_gia_tri_truoc_nhan(self):
        """Ghi nhận đặc điểm của file thật: giá trị được VẼ trước nhãn."""
        lines = build_vat_page().text.splitlines()
        assert lines[0] == "1K26XXX"
        assert lines[1] == "Ký hiệu (Serial):"

    def test_van_lay_dung_nho_label_right(self, registry, extraction_config, app_settings):
        fields = _extract(registry, extraction_config, app_settings)
        assert fields.value("invoice_serial") == "1K26XXX"
        assert fields.value("invoice_number") == "00100001"

    def test_phuong_phap_duoc_ghi_lai_de_truy_vet(
        self, registry, extraction_config, app_settings
    ):
        fields = _extract(registry, extraction_config, app_settings)
        assert fields.get("invoice_serial").method is FieldMethod.LABEL_RIGHT


class TestTruongBatBuoc:
    def test_khong_thieu_truong_bat_buoc(self, registry, extraction_config, app_settings):
        fields = _extract(registry, extraction_config, app_settings)
        assert registry.get(DocumentType.VPBANK_VAT_INVOICE).missing_required(fields) == ()

    def test_ngay_hoa_don(self, registry, extraction_config, app_settings):
        fields = _extract(registry, extraction_config, app_settings)
        assert fields.value("document_date") == date(2026, 8, 1)


class TestSoTien:
    def test_doc_dung_ba_con_so(self, registry, extraction_config, app_settings):
        fields = _extract(registry, extraction_config, app_settings)
        assert fields.value("subtotal") == Decimal("20000")
        assert fields.value("vat_amount") == Decimal("2000")
        assert fields.value("total_amount") == Decimal("22000")

    def test_dang_thuc_noi_bo_khop(self, registry, extraction_config, app_settings):
        fields = _extract(registry, extraction_config, app_settings)
        assert fields.value("subtotal") + fields.value("vat_amount") == fields.value("total_amount")

    def test_thue_suat_khong_bi_lay_du_khi_hai_cap_nhan_cung_dong(
        self, registry, extraction_config, app_settings
    ):
        """Nhãn 'Thuế suất' và 'Tiền thuế GTGT' nằm cùng một dòng y."""
        fields = _extract(registry, extraction_config, app_settings)
        assert fields.value("vat_rate") == Decimal("10")
        assert fields.value("vat_amount") == Decimal("2000")


class TestHaiKhoaLienKet:
    def test_khoa_chinh_la_reference_nha_cung_cap(
        self, registry, extraction_config, app_settings
    ):
        fields = _extract(registry, extraction_config, app_settings)
        assert fields.value("meta_reference") == "ABCD1234EF"

    def test_khoa_kiem_tra_cheo_tach_tu_so_tham_chieu_ngan_hang(
        self, registry, extraction_config, app_settings
    ):
        fields = _extract(registry, extraction_config, app_settings)
        assert fields.value("reference_number") == "FT26000000000001_20260801"
        assert fields.value("bank_transaction_code") == "FT26000000000001"
        assert fields.value("bank_reference_date") == date(2026, 8, 1)

    def test_thieu_dau_cach_trong_dien_giai_van_lay_duoc(
        self, registry, extraction_config, app_settings
    ):
        """File thật ghi 'thanh toantai' (dính liền) thay vì 'thanh toan tai'."""
        fields = _extract(registry, extraction_config, app_settings)
        assert "thanh toantai" in fields.value("payment_detail")
        assert fields.value("meta_reference") == "ABCD1234EF"


class TestMaSoThue:
    def test_phan_biet_mst_ben_ban_va_ben_mua(self, registry, extraction_config, app_settings):
        fields = _extract(registry, extraction_config, app_settings)
        assert fields.value("seller_tax_code") == "0100000002"
        assert fields.value("tax_code") == "0100000001"
