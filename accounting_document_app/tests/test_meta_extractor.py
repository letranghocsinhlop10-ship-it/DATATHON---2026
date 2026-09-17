"""Test extractor hoá đơn Meta."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.enums import DocumentType
from helpers import make_content, make_context, read_fixture


def _extract(registry, extraction_config, app_settings):
    content = make_content(
        [read_fixture("meta_invoice.txt"), read_fixture("meta_invoice_page2.txt")],
        name="meta.pdf",
    )
    ctx = make_context(content, DocumentType.META_INVOICE, extraction_config, app_settings)
    return registry.get(DocumentType.META_INVOICE).extract(ctx), ctx


class TestTruongBatBuoc:
    def test_khong_thieu_truong_bat_buoc(self, registry, extraction_config, app_settings):
        fields, _ = _extract(registry, extraction_config, app_settings)
        assert registry.get(DocumentType.META_INVOICE).missing_required(fields) == ()

    def test_so_tham_chieu(self, registry, extraction_config, app_settings):
        fields, _ = _extract(registry, extraction_config, app_settings)
        assert fields.value("reference_number") == "ABCD1234EF"

    def test_ngay_hoa_don_dang_tieng_viet(self, registry, extraction_config, app_settings):
        fields, _ = _extract(registry, extraction_config, app_settings)
        assert fields.value("document_date") == date(2026, 8, 1)


class TestSoTien:
    def test_doc_dung_dau_cham_la_phan_cach_nghin(self, registry, extraction_config, app_settings):
        fields, _ = _extract(registry, extraction_config, app_settings)
        assert fields.value("subtotal") == Decimal("1000000")
        assert fields.value("vat_amount") == Decimal("100000")
        assert fields.value("total_amount") == Decimal("1100000")

    def test_thue_suat(self, registry, extraction_config, app_settings):
        fields, _ = _extract(registry, extraction_config, app_settings)
        assert fields.value("vat_rate") == Decimal("10")

    def test_kiem_tra_so_hoc_noi_bo(self, registry, extraction_config, app_settings):
        fields, _ = _extract(registry, extraction_config, app_settings)
        assert fields.value("vat_math_check") is True

    def test_tat_ca_tien_deu_la_decimal(self, registry, extraction_config, app_settings):
        fields, _ = _extract(registry, extraction_config, app_settings)
        for name in ("subtotal", "vat_amount", "total_amount"):
            assert isinstance(fields.value(name), Decimal)


class TestCacTruongKhac:
    def test_so_hoa_don(self, registry, extraction_config, app_settings):
        fields, _ = _extract(registry, extraction_config, app_settings)
        assert fields.value("invoice_number") == "FBADS-100-100000001"

    def test_id_giao_dich_giu_nguyen_dau_gach(self, registry, extraction_config, app_settings):
        fields, _ = _extract(registry, extraction_config, app_settings)
        assert fields.value("transaction_id") == "28000000000000001-28000000000000002"

    def test_bon_so_cuoi_the(self, registry, extraction_config, app_settings):
        fields, _ = _extract(registry, extraction_config, app_settings)
        assert fields.value("card_last4") == "1234"

    def test_phuong_thuc_thanh_toan(self, registry, extraction_config, app_settings):
        fields, _ = _extract(registry, extraction_config, app_settings)
        assert fields.value("payment_method") == "MasterCard"


class TestMaSoThue:
    def test_lay_dung_mst_ben_mua_chu_khong_phai_ben_ban(
        self, registry, extraction_config, app_settings
    ):
        """'Tax ID:' xuất hiện 2 lần — rule dùng occurrence để lấy đúng lần 2."""
        fields, _ = _extract(registry, extraction_config, app_settings)
        assert fields.value("tax_code") == "0100000001"
        assert fields.value("seller_tax_code") == "9000000000"

    def test_mst_da_bo_dau_gach(self, registry, extraction_config, app_settings):
        fields, _ = _extract(registry, extraction_config, app_settings)
        assert "-" not in fields.value("tax_code")


class TestTruyVet:
    def test_moi_truong_deu_co_bang_chung_nguon(
        self, registry, extraction_config, app_settings
    ):
        fields, _ = _extract(registry, extraction_config, app_settings)
        ref = fields.get("reference_number")
        assert ref.raw_snippet and "ABCD1234EF" in ref.raw_snippet
        assert ref.rule_id == "meta.reference_number"
        assert ref.page_number == 1

    def test_truong_o_trang_2_ghi_dung_so_trang(
        self, registry, extraction_config, app_settings
    ):
        fields, _ = _extract(registry, extraction_config, app_settings)
        assert fields.get("invoice_number").page_number == 2


class TestKhongDocDuocThiTraNone:
    def test_thieu_du_lieu_khong_bia_gia_tri(self, registry, extraction_config, app_settings):
        content = make_content(["Hóa đơn thuế cho ai đó\nMeta quảng cáo"], name="thieu.pdf")
        ctx = make_context(content, DocumentType.META_INVOICE, extraction_config, app_settings)
        fields = registry.get(DocumentType.META_INVOICE).extract(ctx)
        assert fields.value("reference_number") is None
        assert fields.value("total_amount") is None
        assert fields.get("reference_number").error == "NOT_FOUND"
