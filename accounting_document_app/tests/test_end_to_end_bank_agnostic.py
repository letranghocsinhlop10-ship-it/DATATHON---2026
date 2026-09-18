"""Test end-to-end bank-agnostic — đúng các kịch bản A-H trong yêu cầu nghiệp vụ.

A/B/D/E dùng ``matching_helpers.make_doc`` (nhanh, kiểm tra đúng logic
matcher không cần PDF thật). G/H dựng PDF THẬT trên đĩa và chạy trọn
PREPARE -> SPLIT -> REGISTER -> MATCH để chứng minh child PDF sau khi tách
thực sự được matcher/UI nhìn thấy — không chỉ tồn tại trên đĩa.

C và F đã có sẵn trong ``tests/test_payment_group_matcher.py``
(``TestMainVaFeeCungGroup``, ``TestKhongMatchNhamTheoAmount``) — không lặp
lại ở đây.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.database.database import Database
from app.database.processing_run_repository import ProcessingRunRepository
from app.matching.payment_group_matcher import PaymentGroupMatcher
from app.models.enums import DocumentType, PaymentGroupStatus
from app.services.payment_group_service import PaymentGroupService
from app.services.prepare_data_service import PrepareDataService
from matching_helpers import make_doc, meta
from pdf_synth import FONT, write_pdf

pytestmark = pytest.mark.skipif(FONT is None, reason="Không tìm thấy font DejaVu Sans trong môi trường này")


class TestA_MetaCardVPBankExactReference:
    """A — Meta card 4966 + VPBank exact reference => Debit ✓."""

    def test_debit_co_dau_check_va_dung_ngan_hang_vpbank(self):
        bill = meta("ABCD1234EF", card_last4="4966", total_amount=Decimal("1"), document_date=date(2026, 8, 1))
        note = make_doc(
            DocumentType.VPBANK_DEBIT_NOTE,
            meta_reference="ABCD1234EF",
            transaction_code="FT1",
            total_amount=Decimal("1"),
            transaction_date=date(2026, 8, 1),
            payment_detail="GD thanh toan tai FACEBK *ABCD1234EF",
        )

        result = PaymentGroupMatcher().match([bill, note])

        assert len(result.groups) == 1
        case = result.groups[0]
        assert case.main_payment is not None  # Debit = ✓
        assert case.bank_name == "VPBANK"
        assert case.expected_bank == "VPBANK"
        assert case.bank_mismatch is False
        assert case.status is PaymentGroupStatus.MATCHED_HIGH


class TestB_MetaCardVietinBankExactReference:
    """B — Meta card 2960 + VietinBank exact reference => Debit ✓."""

    def test_debit_co_dau_check_va_dung_ngan_hang_vietinbank(self):
        bill = meta("ABCD1234EF", card_last4="2960", total_amount=Decimal("1"), document_date=date(2026, 8, 1))
        advice = make_doc(
            DocumentType.VIETINBANK_DEBIT_ADVICE,
            facebook_reference="ABCD1234EF",
            transaction_number="7001",
            total_amount=Decimal("1"),
            transaction_date=date(2026, 8, 1),
            payment_role="MAIN_PAYMENT",
        )

        result = PaymentGroupMatcher().match([bill, advice])

        assert len(result.groups) == 1
        case = result.groups[0]
        assert case.main_payment is not None  # Debit = ✓
        assert case.bank_name == "VIETINBANK"
        assert case.expected_bank == "VIETINBANK"
        assert case.bank_mismatch is False
        assert case.status is PaymentGroupStatus.MATCHED_HIGH

    def test_reference_dung_nhung_bank_lech_expected_thi_needs_review_khong_tu_loai(self):
        """§3: reference khớp tuyệt đối nhưng ngân hàng thực tế KHÁC ngân
        hàng kỳ vọng từ thẻ -> NEEDS_REVIEW, main_payment vẫn được GIỮ LẠI
        (không tự loại liên kết)."""
        bill = meta("ABCD1234EF", card_last4="2960", total_amount=Decimal("1"), document_date=date(2026, 8, 1))
        note = make_doc(  # 2960 -> kỳ vọng VIETINBANK, nhưng chứng từ lại là VPBank
            DocumentType.VPBANK_DEBIT_NOTE,
            meta_reference="ABCD1234EF",
            transaction_code="FT1",
            total_amount=Decimal("1"),
            transaction_date=date(2026, 8, 1),
            payment_detail="GD thanh toan tai FACEBK *ABCD1234EF",
        )

        result = PaymentGroupMatcher().match([bill, note])

        assert len(result.groups) == 1
        case = result.groups[0]
        assert case.status is PaymentGroupStatus.NEEDS_REVIEW
        assert case.main_payment is note  # KHÔNG bị xoá/loại
        assert case.bank_mismatch is True


class TestD_MixedVPBankAndVietinBankSameBatch:
    """D — PDF VPBank + VietinBank trộn trong cùng một lô => phân loại đúng."""

    def test_hai_case_khac_ngan_hang_khong_lan_vao_nhau(self):
        d = date(2026, 8, 1)
        bill_vp = meta("VPREF00001", total_amount=Decimal("1"), document_date=d)
        note_vp = make_doc(
            DocumentType.VPBANK_DEBIT_NOTE,
            meta_reference="VPREF00001", transaction_code="FT1",
            total_amount=Decimal("1"), transaction_date=d,
            payment_detail="GD thanh toan tai FACEBK *VPREF00001",
        )
        bill_vt = meta("VTREF00002", total_amount=Decimal("1"), document_date=d)
        advice_vt = make_doc(
            DocumentType.VIETINBANK_DEBIT_ADVICE,
            facebook_reference="VTREF00002", transaction_number="7002",
            total_amount=Decimal("1"), transaction_date=d, payment_role="MAIN_PAYMENT",
        )

        result = PaymentGroupMatcher().match([bill_vp, note_vp, bill_vt, advice_vt])

        assert len(result.groups) == 2
        by_ref = {c.reference: c for c in result.groups}
        assert by_ref["VPREF00001"].bank_name == "VPBANK"
        assert by_ref["VTREF00002"].bank_name == "VIETINBANK"
        for case in result.groups:
            assert case.status is PaymentGroupStatus.MATCHED_HIGH


class TestE_VatExactReference:
    """E — VAT Invoice ghép ưu tiên bằng exact reference, không ghép nhầm
    theo amount/date."""

    def test_vat_dung_reference_duoc_ghep_vao_dung_case(self):
        d = date(2026, 8, 1)
        bill = meta("ABCD1234EF", total_amount=Decimal("1"), document_date=d)
        note = make_doc(
            DocumentType.VPBANK_DEBIT_NOTE,
            meta_reference="ABCD1234EF", transaction_code="FT1",
            total_amount=Decimal("1"), transaction_date=d,
            payment_detail="GD thanh toan tai FACEBK *ABCD1234EF",
        )
        vat = make_doc(
            DocumentType.VPBANK_VAT_INVOICE,
            meta_reference="ABCD1234EF",
            transaction_date=d,
            invoice_number="00100001",
            total_amount=Decimal("2200"),
        )

        result = PaymentGroupMatcher().match([bill, note, vat])

        assert len(result.groups) == 1
        case = result.groups[0]
        assert case.vat_invoice is vat

    def test_vat_khac_reference_khong_bi_ghep_nham_theo_amount(self):
        """VAT có reference KHÁC — dù trùng ngày — không được ghép vào case
        của reference khác chỉ vì tình cờ cùng ngày."""
        d = date(2026, 8, 1)
        bill = meta("ABCD1234EF", total_amount=Decimal("1"), document_date=d)
        note = make_doc(
            DocumentType.VPBANK_DEBIT_NOTE,
            meta_reference="ABCD1234EF", transaction_code="FT1",
            total_amount=Decimal("1"), transaction_date=d,
            payment_detail="GD thanh toan tai FACEBK *ABCD1234EF",
        )
        vat_khac_ref = make_doc(
            DocumentType.VPBANK_VAT_INVOICE,
            meta_reference="ZZZZ999999",  # khác hẳn reference của case trên
            transaction_date=d,
            invoice_number="00100002",
            total_amount=Decimal("9999"),
        )

        result = PaymentGroupMatcher().match([bill, note, vat_khac_ref])

        case = next(c for c in result.groups if c.reference == "ABCD1234EF")
        assert case.vat_invoice is None  # KHÔNG bị ghép nhầm

    def test_khong_co_reference_thi_khong_tu_ghep_qua_amount_date(self):
        """VAT không có reference -> không có đường fallback riêng trong
        bản này (xem README) -> không tham gia case nào."""
        d = date(2026, 8, 1)
        bill = meta("ABCD1234EF", total_amount=Decimal("1"), document_date=d)
        note = make_doc(
            DocumentType.VPBANK_DEBIT_NOTE,
            meta_reference="ABCD1234EF", transaction_code="FT1",
            total_amount=Decimal("1"), transaction_date=d,
            payment_detail="GD thanh toan tai FACEBK *ABCD1234EF",
        )
        vat_no_ref = make_doc(
            DocumentType.VPBANK_VAT_INVOICE,
            meta_reference=None,
            transaction_date=d,
            invoice_number="00100003",
            total_amount=Decimal("1"),  # cùng amount với note nhưng KHÔNG được suy đoán ghép
        )

        result = PaymentGroupMatcher().match([bill, note, vat_no_ref])

        case = next(c for c in result.groups if c.reference == "ABCD1234EF")
        assert case.vat_invoice is None


# --------------------------------------------------------------------- G/H


def _bundle_pages():
    main = [
        "GIẤY BÁO NỢ / Debit Advice",
        "Số giao dịch / Transaction number: 8002",
        "Ngày thực hiện / Transaction date: 22-08-2026 08:00:00",
        "Số tiền bằng số / Amount in figures: 5,000,000 VND",
        "Nội dung / Remarks: GD thanh toan tai FACEBK *PQRS445566",
    ]
    fee = [
        "GIẤY BÁO NỢ / Debit Advice",
        "Số giao dịch / Transaction number: 8001",
        "Ngày thực hiện / Transaction date: 22-08-2026 08:00:00",
        "Số tiền bằng số / Amount in figures: 50,000 VND",
        "Nội dung / Remarks: Phi GD thanh toan tai FACEBK *PQRS445566",
    ]
    cover = ["NGAN HANG TMCP CONG THUONG VIET NAM", "Bang ke thang 08/2026"]
    return [cover, main, fee]


@pytest.fixture
def db():
    with Database(":memory:") as database:
        yield database


class TestGH_MultiPageBundlePhysicalSplitAndVisibleToMatcher:
    """G — PDF Debit Advice nhiều trang thật sự tạo child PDF 1 trang trên
    đĩa. H — child PDF sau split phải được matcher/UI nhìn thấy (không chỉ
    nằm trên đĩa rồi bị bỏ quên)."""

    def test_child_pdf_duoc_tao_vat_ly_va_duoc_payment_case_nhin_thay(
        self, db, classifier_config, extraction_config, app_settings, tmp_path
    ):
        source_dir = tmp_path / "data_tool_read_pdf"
        source_dir.mkdir()
        write_pdf(source_dir / "giay-bao-No.pdf", _bundle_pages())

        original_bytes = (source_dir / "giay-bao-No.pdf").read_bytes()

        run_id = ProcessingRunRepository(db).start(str(source_dir))
        prepare_service = PrepareDataService(db, classifier_config, extraction_config, app_settings)
        prepare_result = prepare_service.prepare(source_dir, run_id=run_id)

        # G — child PDF vật lý thật sự tồn tại trên đĩa, file gốc còn nguyên.
        split_dir = prepare_result.all_data_folder / "_DEBIT_SPLIT"
        assert split_dir.is_dir()
        child_pdfs = list(split_dir.glob("*.pdf"))
        assert len(child_pdfs) == 2
        assert (source_dir / "giay-bao-No.pdf").read_bytes() == original_bytes

        # H — matcher (qua PaymentGroupService, đọc DB do REGISTER ghi vào)
        # phải nhìn thấy cả 2 trang đã tách, ghép đúng thành MỘT case.
        payment_service = PaymentGroupService(db)
        match_result = payment_service.match_run(run_id, prepare_result.bank_transactions)

        cases_with_ref = [c for c in match_result.groups if c.reference == "PQRS445566"]
        assert len(cases_with_ref) == 1
        case = cases_with_ref[0]
        assert case.main_payment is not None
        assert len(case.fees) == 1
        assert case.bank_name == "VIETINBANK"
        assert case.main_payment.file_path.parent == split_dir
        assert case.main_payment.file_path in child_pdfs
