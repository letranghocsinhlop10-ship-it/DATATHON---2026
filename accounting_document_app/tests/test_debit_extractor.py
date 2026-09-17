"""Test extractor Phiếu giao dịch ghi nợ VPBank."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.enums import DocumentType
from helpers import make_content, make_context, read_fixture


def _extract(registry, extraction_config, app_settings, text: str | None = None):
    content = make_content([text or read_fixture("vpbank_debit_note.txt")], name="debit.pdf")
    ctx = make_context(content, DocumentType.VPBANK_DEBIT_NOTE, extraction_config, app_settings)
    return registry.get(DocumentType.VPBANK_DEBIT_NOTE).extract(ctx)


class TestTruongCoNhan:
    def test_khong_thieu_truong_bat_buoc(self, registry, extraction_config, app_settings):
        fields = _extract(registry, extraction_config, app_settings)
        assert registry.get(DocumentType.VPBANK_DEBIT_NOTE).missing_required(fields) == ()

    def test_ma_giao_dich(self, registry, extraction_config, app_settings):
        fields = _extract(registry, extraction_config, app_settings)
        assert fields.value("transaction_code") == "FT26000000000001"

    def test_ngay_giao_dich(self, registry, extraction_config, app_settings):
        fields = _extract(registry, extraction_config, app_settings)
        assert fields.value("transaction_date") == date(2026, 8, 1)

    def test_so_tien_doc_dau_phay_la_phan_cach_nghin(
        self, registry, extraction_config, app_settings
    ):
        fields = _extract(registry, extraction_config, app_settings)
        assert fields.value("total_amount") == Decimal("1122000")

    def test_ten_khach_hang_bi_ngat_dong_van_lay_du(
        self, registry, extraction_config, app_settings
    ):
        """Tên bị PDF cắt thành 'CONG TY CO' / 'PHAN ABC XYZ'."""
        fields = _extract(registry, extraction_config, app_settings)
        assert fields.value("company_name") == "CONG TY CO PHAN ABC XYZ"

    def test_ma_khach_hang_va_so_tai_khoan(self, registry, extraction_config, app_settings):
        fields = _extract(registry, extraction_config, app_settings)
        assert fields.value("customer_id") == "20000001"
        assert fields.value("bank_account") == "600000001"


class TestBocTuDienGiai:
    def test_bon_so_cuoi_the(self, registry, extraction_config, app_settings):
        fields = _extract(registry, extraction_config, app_settings)
        assert fields.value("card_last4") == "1234"

    def test_reference_nha_cung_cap(self, registry, extraction_config, app_settings):
        fields = _extract(registry, extraction_config, app_settings)
        assert fields.value("meta_reference") == "ABCD1234EF"

    def test_dien_giai_bi_ngat_dong_van_lay_duoc_reference(
        self, registry, extraction_config, app_settings
    ):
        """FACEBK và reference nằm ở DÒNG KHÁC với nhãn 'Diễn giải'."""
        fields = _extract(registry, extraction_config, app_settings)
        detail = fields.value("payment_detail")
        assert "FACEBK ABCD1234EF" in detail

    def test_khong_lay_nham_ma_giao_dich_lam_reference(
        self, registry, extraction_config, app_settings
    ):
        fields = _extract(registry, extraction_config, app_settings)
        assert fields.value("meta_reference") != fields.value("transaction_code")

    def test_khong_lay_nham_so_tai_khoan_hay_so_the(
        self, registry, extraction_config, app_settings
    ):
        fields = _extract(registry, extraction_config, app_settings)
        reference = fields.value("meta_reference")
        assert reference not in {"600000001", "1111xxxx1234", "1234"}
