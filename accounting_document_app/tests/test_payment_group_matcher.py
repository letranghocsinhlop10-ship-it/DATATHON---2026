"""Test chấp nhận (§M) cho PaymentGroupMatcher — dùng dữ liệu GIẢ, không
phải giá trị thật từ bất kỳ chứng từ nào (repo công khai)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.bank_statement_parser import BankTransaction
from app.matching.payment_group_matcher import PaymentGroupMatcher
from app.models.enums import DocumentType, PaymentGroupStatus
from matching_helpers import make_doc, meta


def _vpbank_debit(meta_reference, transaction_code, *, amount, txn_date, is_fee=False, **extra):
    prefix = "Phi GD thanh toan tai" if is_fee else "GD thanh toan tai"
    return make_doc(
        DocumentType.VPBANK_DEBIT_NOTE,
        meta_reference=meta_reference,
        transaction_code=transaction_code,
        total_amount=amount,
        transaction_date=txn_date,
        payment_detail=f"{prefix} FACEBK *{meta_reference}",
        **extra,
    )


def _vietinbank_advice(reference, transaction_number, *, amount, txn_date, is_fee, **extra):
    return make_doc(
        DocumentType.VIETINBANK_DEBIT_ADVICE,
        facebook_reference=reference,
        transaction_number=transaction_number,
        total_amount=amount,
        transaction_date=txn_date,
        payment_role="BANK_FEE" if is_fee else "MAIN_PAYMENT",
        **extra,
    )


class TestKhopTuyetDoiDuTienKhacNhau:
    """TEST 1 — reference khớp tuyệt đối, amount khác nhau -> vẫn MATCHED_HIGH."""

    def test_amount_khac_nhau_van_matched_high(self):
        bill = meta("ABCD1234EF", total_amount=Decimal("2530672"), document_date=date(2026, 8, 1))
        note = _vpbank_debit(
            "ABCD1234EF", "FT100000001", amount=Decimal("2558510"), txn_date=date(2026, 8, 1)
        )

        result = PaymentGroupMatcher().match([bill, note])

        assert len(result.groups) == 1
        group = result.groups[0]
        assert group.status is PaymentGroupStatus.MATCHED_HIGH
        assert group.facebook_bill is bill
        assert group.main_payment is note
        assert "ABCD1234EF" in group.reason


class TestBoChungTuDayDuGomSaoKe:
    """TEST 2 — sao kê + debit note + bill cùng bộ -> một group duy nhất,
    mang cả 3 nguồn."""

    def test_ba_nguon_gop_thanh_mot_bo(self):
        bill = meta("ABCD1234EF", total_amount=Decimal("2530672"), document_date=date(2026, 8, 1))
        note = _vpbank_debit(
            "ABCD1234EF", "FT100000001", amount=Decimal("2558510"), txn_date=date(2026, 8, 1)
        )
        row = BankTransaction(
            stt=1,
            transaction_id="FT100000001",
            value_date=date(2026, 8, 1),
            transaction_time="10:00:00",
            debit_amount=Decimal("2558510"),
            credit_amount=None,
            transaction_detail="GD thanh toan tai FACEBK *ABCD1234EF",
            running_balance=Decimal("50000000"),
            facebook_reference="ABCD1234EF",
            source_pdf=None,
            source_page=1,
        )

        result = PaymentGroupMatcher().match([bill, note], [row])

        assert len(result.groups) == 1
        group = result.groups[0]
        assert group.status is PaymentGroupStatus.MATCHED_HIGH
        assert group.facebook_bill is bill
        assert group.main_payment is note
        assert group.statement_rows == [row]
        assert "FT100000001" in group.reason


class TestMainVaFeeCungGroup:
    """TEST 3/4 — 2 trang Debit Advice (main + fee) cùng reference + cùng
    ngày -> MỘT payment group, không phải 2 folder riêng."""

    def test_hai_trang_gop_thanh_mot_group(self):
        d = date(2026, 8, 31)
        main_page = _vietinbank_advice("ZZZZ111111", "3185", amount=Decimal("13066610"), txn_date=d, is_fee=False)
        fee_page = _vietinbank_advice("ZZZZ111111", "3186", amount=Decimal("114986"), txn_date=d, is_fee=True)

        result = PaymentGroupMatcher().match([fee_page, main_page])

        assert len(result.groups) == 1
        group = result.groups[0]
        assert group.main_payment is main_page
        assert group.fees == [fee_page]

    def test_fee_va_main_khac_reference_van_gop_dung_theo_tung_ref(self):
        d = date(2026, 8, 31)
        main1 = _vietinbank_advice("YYYY222222", "9101", amount=Decimal("22000000"), txn_date=d, is_fee=False)
        fee1 = _vietinbank_advice("YYYY222222", "9100", amount=Decimal("193600"), txn_date=d, is_fee=True)

        result = PaymentGroupMatcher().match([fee1, main1])

        assert len(result.groups) == 1
        assert result.groups[0].main_payment is main1
        assert result.groups[0].fees == [fee1]


class TestKhongMatchNhamTheoAmount:
    """TEST 5 — cùng số tiền, KHÁC reference -> không được gộp/nhầm."""

    def test_cung_amount_khac_reference_la_hai_group_rieng(self):
        d = date(2026, 8, 1)
        bill_a = meta("AAAA111111", total_amount=Decimal("1000000"), document_date=d)
        note_a = _vpbank_debit("AAAA111111", "FT1", amount=Decimal("1000000"), txn_date=d)
        bill_b = meta("BBBB222222", total_amount=Decimal("1000000"), document_date=d)
        note_b = _vpbank_debit("BBBB222222", "FT2", amount=Decimal("1000000"), txn_date=d)

        result = PaymentGroupMatcher().match([bill_a, note_a, bill_b, note_b])

        assert len(result.groups) == 2
        refs = {g.facebook_reference for g in result.groups}
        assert refs == {"AAAA111111", "BBBB222222"}
        for group in result.groups:
            assert group.status is PaymentGroupStatus.MATCHED_HIGH


class TestKhongGopNhamKhacNgay:
    """TEST 6 — cùng reference, KHÁC ngày -> 2 payment group riêng."""

    def test_cung_reference_khac_ngay_la_hai_group(self):
        bill1 = meta("ABC123XYZ9", total_amount=Decimal("500000"), document_date=date(2026, 8, 1))
        note1 = _vpbank_debit("ABC123XYZ9", "FT10", amount=Decimal("500000"), txn_date=date(2026, 8, 1))
        bill2 = meta("ABC123XYZ9", total_amount=Decimal("700000"), document_date=date(2026, 8, 15))
        note2 = _vpbank_debit("ABC123XYZ9", "FT20", amount=Decimal("700000"), txn_date=date(2026, 8, 15))

        result = PaymentGroupMatcher().match([bill1, note1, bill2, note2])

        assert len(result.groups) == 2
        dates = {g.transaction_date for g in result.groups}
        assert dates == {date(2026, 8, 1), date(2026, 8, 15)}


class TestAmbiguousKhongTuChon:
    """TEST 9 — nhiều ứng viên mơ hồ -> NEEDS_REVIEW, không force-match."""

    def test_hai_thanh_toan_chinh_cung_ref_cung_ngay_can_review(self):
        d = date(2026, 8, 1)
        bill = meta("DUP0000001", total_amount=Decimal("1000000"), document_date=d)
        note_a = _vpbank_debit("DUP0000001", "FT1", amount=Decimal("1000000"), txn_date=d)
        note_b = _vpbank_debit("DUP0000001", "FT2", amount=Decimal("1000000"), txn_date=d)

        result = PaymentGroupMatcher().match([bill, note_a, note_b])

        assert len(result.groups) == 1
        group = result.groups[0]
        assert group.status is PaymentGroupStatus.NEEDS_REVIEW
        assert group.main_payment is None  # không tự chọn 1 trong 2

    def test_fallback_amount_ngay_nhieu_ung_vien_can_review(self):
        """Không có reference cả hai phía, nhiều bill trùng amount+ngày với
        nhiều bank doc -> NEEDS_REVIEW, không tự ghép đôi bừa."""
        d = date(2026, 8, 1)
        bill_a = meta(None, total_amount=Decimal("999000"), document_date=d)
        bill_b = make_doc(
            DocumentType.META_INVOICE, total_amount=Decimal("999000"), document_date=d, reference_number=None
        )
        note_a = make_doc(
            DocumentType.VPBANK_DEBIT_NOTE,
            meta_reference=None,
            transaction_code="FT1",
            total_amount=Decimal("999000"),
            transaction_date=d,
            payment_detail="giao dich khac khong lien quan facebook",
        )
        note_b = make_doc(
            DocumentType.VPBANK_DEBIT_NOTE,
            meta_reference=None,
            transaction_code="FT2",
            total_amount=Decimal("999000"),
            transaction_date=d,
            payment_detail="giao dich khac khong lien quan facebook",
        )

        result = PaymentGroupMatcher().match([bill_a, bill_b, note_a, note_b])

        assert all(g.status is PaymentGroupStatus.NEEDS_REVIEW for g in result.groups)

    def test_fallback_amount_ngay_duy_nhat_thi_van_duoc_matched(self):
        d = date(2026, 8, 1)
        bill = make_doc(
            DocumentType.META_INVOICE, total_amount=Decimal("321000"), document_date=d, reference_number=None
        )
        note = make_doc(
            DocumentType.VPBANK_DEBIT_NOTE,
            meta_reference=None,
            transaction_code="FT9",
            total_amount=Decimal("321000"),
            transaction_date=d,
            payment_detail="giao dich khac khong lien quan facebook",
        )

        result = PaymentGroupMatcher().match([bill, note])

        assert len(result.groups) == 1
        group = result.groups[0]
        assert group.status is PaymentGroupStatus.MATCHED
        assert group.facebook_reference is None
        assert group.facebook_bill is bill
        assert group.main_payment is note
