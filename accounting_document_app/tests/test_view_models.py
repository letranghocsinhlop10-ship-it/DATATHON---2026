"""Test tầng chuyển đổi domain object -> dữ liệu hiển thị (thuần, không Qt)."""

from __future__ import annotations

from app.models.enums import DocumentType, DossierStatus, PaymentGroupStatus
from app.models.payment_case import PaymentCase
from app.ui.view_models import (
    StatusColor,
    dossier_to_row,
    document_to_row,
    payment_group_status_color,
    payment_group_to_row,
    presence_mark,
    status_color,
    status_label,
)
from matching_helpers import date, make_doc, meta


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


class TestPaymentGroupToRow:
    def test_khop_cao_la_xanh_va_du_mark(self):
        bill = meta("ABCD1234EF")
        main = make_doc(DocumentType.VPBANK_DEBIT_NOTE, meta_reference="ABCD1234EF")
        case = PaymentCase(
            group_code="2026-08-01_ABCD1234EF",
            reference="ABCD1234EF",
            transaction_date=date(2026, 8, 1),
            meta_bill=bill,
            main_payment=main,
            status=PaymentGroupStatus.MATCHED_HIGH,
        )
        row = payment_group_to_row(case)
        assert row.meta_mark == "✓"
        assert row.debit_mark == "✓"
        assert row.bank == "VPBANK"
        assert row.status_color == StatusColor.GREEN
        assert payment_group_status_color(PaymentGroupStatus.MATCHED_HIGH) == StatusColor.GREEN

    def test_debit_mark_dung_ca_voi_vietinbank(self):
        main = make_doc(DocumentType.VIETINBANK_DEBIT_ADVICE, transaction_number="1")
        case = PaymentCase(group_code="X", main_payment=main, status=PaymentGroupStatus.MATCHED_HIGH)
        row = payment_group_to_row(case)
        assert row.debit_mark == "✓"
        assert row.bank == "VIETINBANK"

    def test_needs_review_la_vang(self):
        assert payment_group_status_color(PaymentGroupStatus.NEEDS_REVIEW) == StatusColor.YELLOW

    def test_khong_co_bill_hien_thi_dau_x(self):
        case = PaymentCase(group_code="X", status=PaymentGroupStatus.UNMATCHED)
        row = payment_group_to_row(case)
        assert row.meta_mark == "✗"
        assert row.reference == "—"
        assert row.bank == "—"

    def test_bank_mismatch_bao_co_warning(self):
        bill = meta("ABCD1234EF", card_last4="1234")
        main = make_doc(DocumentType.VIETINBANK_DEBIT_ADVICE, transaction_number="1")
        case = PaymentCase(
            group_code="X", reference="ABCD1234EF", meta_bill=bill, main_payment=main,
            expected_bank="VPBANK", status=PaymentGroupStatus.NEEDS_REVIEW,
        )
        row = payment_group_to_row(case)
        assert row.has_warning is True
