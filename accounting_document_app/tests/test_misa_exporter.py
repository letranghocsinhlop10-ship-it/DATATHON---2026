"""Test sinh bút toán MISA — resolve template, điều kiện, số tiền."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.config_loader import load_accounting_config, load_misa_mapping_config
from app.exporters.misa_exporter import MisaExporter
from app.matching.dossier_builder import DossierBuilder
from app.matching.dossier_validator import DossierValidator
from matching_helpers import Decimal as D
from matching_helpers import date, debit, meta, vat


@pytest.fixture(scope="module")
def accounting_config():
    return load_accounting_config()


@pytest.fixture(scope="module")
def misa_config(accounting_config):
    return load_misa_mapping_config(accounting_config)


def _valid_dossier_and_docs():
    docs = [
        meta(
            "ABCD1234EF",
            subtotal=D("1000000"), vat_amount=D("100000"), total_amount=D("1100000"),
            invoice_number="FBADS-100-100000001", document_date=date(2026, 8, 1),
        ),
        debit("ABCD1234EF", "FT1", total_amount=D("1122000")),
        vat(
            "ABCD1234EF", "FT1",
            subtotal=D("20000"), vat_amount=D("2000"), total_amount=D("22000"),
            invoice_serial="1K26AAA", invoice_number="00100001", document_date=date(2026, 8, 1),
        ),
    ]
    result = DossierBuilder().build(docs)
    docs_by_id = {d.document_id: d for d in docs}
    DossierValidator().validate(result.dossiers[0], docs_by_id)
    return result.dossiers[0], docs_by_id


class TestSinhDuBonDong:
    def test_mot_ho_so_valid_sinh_bon_dong(self, misa_config):
        dossier, docs_by_id = _valid_dossier_and_docs()
        build = MisaExporter(misa_config).build([dossier], docs_by_id, voucher_start=1)
        assert len(build.rows) == 4
        assert [r.rule_id for r in build.rows] == [
            "meta_ad_expense", "meta_ad_vat", "bank_fee_expense", "bank_fee_vat",
        ]

    def test_so_tien_lay_dung_tu_hoa_don_khong_tu_tinh(self, misa_config):
        dossier, docs_by_id = _valid_dossier_and_docs()
        build = MisaExporter(misa_config).build([dossier], docs_by_id, voucher_start=1)
        amounts = [r.values["amount"] for r in build.rows]
        assert amounts == [D("1000000"), D("100000"), D("20000"), D("2000")]

    def test_tai_khoan_dung_theo_accounting_yaml(self, misa_config):
        dossier, docs_by_id = _valid_dossier_and_docs()
        build = MisaExporter(misa_config).build([dossier], docs_by_id, voucher_start=1)
        expense_row = build.rows[0]
        assert expense_row.values["debit_account"] == "6417"
        assert expense_row.values["credit_account"] == "331"

    def test_so_chung_tu_tang_dan_tu_voucher_start(self, misa_config):
        dossier, docs_by_id = _valid_dossier_and_docs()
        build = MisaExporter(misa_config).build([dossier], docs_by_id, voucher_start=52601)
        assert [r.values["voucher_number"] for r in build.rows] == [
            "NVK052601", "NVK052602", "NVK052603", "NVK052604",
        ]

    def test_dien_giai_co_so_hoa_don_va_ngay(self, misa_config):
        dossier, docs_by_id = _valid_dossier_and_docs()
        build = MisaExporter(misa_config).build([dossier], docs_by_id, voucher_start=1)
        desc = build.rows[0].values["description"]
        assert "FBADS-100-100000001" in desc
        assert "01/08/2026" in desc


class TestChiXuatDossierValid:
    def test_dossier_thieu_vat_khong_sinh_dong_nao(self, misa_config):
        """Dossier MISSING_VAT bị loại từ đầu (only_valid) — lý do thiếu đã
        có sẵn ở sheet CHECK_ERROR, không cần lặp lại trong 'skipped' (mục
        đó dành cho dossier VALID nhưng không dòng nào thoả điều kiện)."""
        docs = [meta("ABCD1234EF", subtotal=D("1000000")), debit("ABCD1234EF", "FT1")]
        result = DossierBuilder().build(docs)
        docs_by_id = {d.document_id: d for d in docs}
        DossierValidator().validate(result.dossiers[0], docs_by_id)
        assert result.dossiers[0].status.value == "MISSING_VAT"

        build = MisaExporter(misa_config).build(result.dossiers, docs_by_id, voucher_start=1)
        assert build.rows == []
        assert build.skipped == {}

    def test_only_valid_false_van_co_the_xuat_dossier_khac(self, misa_config):
        """Nếu tắt only_valid, dòng vẫn chỉ sinh khi CONDITION đúng — không
        phải cứ tắt cờ là bỏ qua kiểm tra dữ liệu."""
        docs = [meta("ABCD1234EF", subtotal=D("1000000"))]
        result = DossierBuilder().build(docs)
        docs_by_id = {d.document_id: d for d in docs}
        DossierValidator().validate(result.dossiers[0], docs_by_id)

        build = MisaExporter(misa_config).build(
            result.dossiers, docs_by_id, voucher_start=1, only_valid=False
        )
        rule_ids = [r.rule_id for r in build.rows]
        assert "meta_ad_expense" in rule_ids  # subtotal có -> sinh được
        assert "bank_fee_expense" not in rule_ids  # không có vat doc -> không sinh


class TestKhongKeKhaiThueMeta:
    def test_meta_vat_van_vao_6417_khong_vao_1331(self, misa_config):
        """Q7 đã xác nhận: KHÔNG khấu trừ vào 1331."""
        dossier, docs_by_id = _valid_dossier_and_docs()
        build = MisaExporter(misa_config).build([dossier], docs_by_id, voucher_start=1)
        vat_row = next(r for r in build.rows if r.rule_id == "meta_ad_vat")
        assert vat_row.values["debit_account"] == "6417"
        assert vat_row.values["credit_account"] == "331"


class TestYeuCauReview:
    def test_require_reviewed_bo_qua_dossier_chua_review(self, misa_config):
        dossier, docs_by_id = _valid_dossier_and_docs()
        dossier.reviewed = False
        build = MisaExporter(misa_config).build(
            [dossier], docs_by_id, voucher_start=1, require_reviewed=True
        )
        assert build.rows == []
        assert dossier.dossier_code in build.skipped

    def test_require_reviewed_giu_dossier_da_review(self, misa_config):
        dossier, docs_by_id = _valid_dossier_and_docs()
        dossier.reviewed = True
        build = MisaExporter(misa_config).build(
            [dossier], docs_by_id, voucher_start=1, require_reviewed=True
        )
        assert len(build.rows) == 4
