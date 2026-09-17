"""Test tầng chuyển đổi domain object -> dữ liệu hiển thị (thuần, không Qt)."""

from __future__ import annotations

from app.models.enums import DossierStatus
from app.ui.view_models import (
    StatusColor,
    dossier_to_row,
    document_to_row,
    presence_mark,
    status_color,
    status_label,
)
from matching_helpers import date, meta


class TestPresenceMark:
    def test_khong_co_thi_dau_x(self):
        assert presence_mark(0) == "✗"

    def test_mot_ban_thi_mot_dau_check(self):
        assert presence_mark(1) == "✓"

    def test_hai_ban_thi_hai_dau_check(self):
        assert presence_mark(2) == "✓✓"


class TestStatusColor:
    def test_valid_la_xanh(self):
        assert status_color(DossierStatus.VALID) == StatusColor.GREEN

    def test_needs_review_la_vang(self):
        assert status_color(DossierStatus.NEEDS_REVIEW) == StatusColor.YELLOW

    def test_missing_la_do(self):
        assert status_color(DossierStatus.MISSING_VAT) == StatusColor.RED

    def test_duplicate_la_do(self):
        assert status_color(DossierStatus.DUPLICATE_META) == StatusColor.RED

    def test_moi_trang_thai_deu_co_mau(self):
        for status in DossierStatus:
            assert status_color(status) in (StatusColor.GREEN, StatusColor.YELLOW, StatusColor.RED)


class TestStatusLabel:
    def test_co_nhan_tieng_viet(self):
        assert status_label(DossierStatus.VALID) == "HỢP LỆ"

    def test_moi_trang_thai_deu_co_nhan(self):
        for status in DossierStatus:
            assert status_label(status)  # không rỗng


class TestDossierToRow:
    def test_chuyen_doi_day_du(self):
        from app.matching.dossier_builder import DossierBuilder
        from app.matching.dossier_validator import DossierValidator
        from matching_helpers import debit, vat

        docs = [meta("ABCD1234EF"), debit("ABCD1234EF", "FT1"), vat("ABCD1234EF", "FT1")]
        result = DossierBuilder().build(docs)
        docs_by_id = {d.document_id: d for d in docs}
        DossierValidator().validate(result.dossiers[0], docs_by_id)

        row = dossier_to_row(result.dossiers[0])
        assert row.dossier_code == "HS000001"
        assert row.reference == "ABCD1234EF"
        assert row.meta_mark == "✓"
        assert row.debit_mark == "✓"
        assert row.vat_mark == "✓"
        assert row.status_color == StatusColor.GREEN

    def test_thieu_reference_hien_thi_gach_ngang(self):
        from app.models.dossier import Dossier

        row = dossier_to_row(Dossier(dossier_code="HS000001", reference=None))
        assert row.reference == "—"


class TestDocumentToRow:
    def test_chuyen_doi_co_ban(self):
        m = meta("ABCD1234EF")
        m.document_id = 1
        row = document_to_row(m)
        assert row.document_id == 1
        assert row.reference == "ABCD1234EF"
        assert row.document_type == "META_INVOICE"
