"""Model ``FacebookPaymentGroup`` — một khoản thanh toán Facebook đã gộp bộ.

Khác với ``Dossier`` (Phase 3, ghép đúng-3-loại META/DEBIT/VAT bằng exact
reference duy nhất), một payment group có thể gồm nhiều loại nguồn khác
nhau (Facebook Bill, phiếu ngân hàng, dòng sao kê, nhiều trang phí) và được
ghép bởi ``app/matching/payment_group_matcher.py`` theo thang tín hiệu ưu
tiên (§G) thay vì chỉ so bằng nhau tuyệt đối.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.core.bank_statement_parser import BankTransaction
from app.models.document import Document
from app.models.enums import PaymentGroupStatus

__all__ = ["FacebookPaymentGroup"]


@dataclass
class FacebookPaymentGroup:
    """Một bộ chứng từ xoay quanh một khoản thanh toán Facebook.

    Attributes:
        group_code: Mã hiển thị, vd. ``"FB_ABCD1234EF_2026-08-01"``.
        facebook_reference: Reference Facebook đã chuẩn hoá — ``None`` khi
            nhóm này được ghép qua fallback (không có reference).
        transaction_date: Ngày giao dịch dùng làm khoá phân biệt (§H — cùng
            reference nhưng khác ngày KHÔNG được gộp chung).
        facebook_bill: Hoá đơn Meta/Facebook (``DocumentType.META_INVOICE``).
        main_payment: Chứng từ ngân hàng của khoản thanh toán CHÍNH.
        fees: Chứng từ phí ngân hàng đi kèm (0 hoặc nhiều).
        statement_rows: Dòng sao kê khớp được.
        supporting: Chứng từ hỗ trợ khác (vd. PDF trích xuất tự sinh từ sao
            kê khi không có phiếu ngân hàng gốc — xem §I).
        status: Trạng thái khớp cuối cùng.
        confidence: Nhãn độ tin cậy ngắn gọn (khớp ``status`` nhưng dùng để
            hiển thị/Excel), vd. ``"HIGH"``/``"MEDIUM"``/``"LOW"``.
        reason: Giải thích NGƯỜI ĐỌC ĐƯỢC vì sao có kết quả này — bắt buộc
            khác rỗng, dùng trực tiếp cho cột ``match_reason`` khi xuất Excel.
        ambiguous_candidates: Số ứng viên gây mơ hồ (0 khi không mơ hồ) —
            phục vụ debug/hiển thị, không ảnh hưởng logic.
        group_id: Id sau khi lưu DB, ``None`` nếu chưa lưu.
    """

    group_code: str
    facebook_reference: str | None = None
    transaction_date: date | None = None
    facebook_bill: Document | None = None
    main_payment: Document | None = None
    fees: list[Document] = field(default_factory=list)
    statement_rows: list[BankTransaction] = field(default_factory=list)
    supporting: list[Document] = field(default_factory=list)
    status: PaymentGroupStatus = PaymentGroupStatus.UNMATCHED
    confidence: str = "NONE"
    reason: str = ""
    ambiguous_candidates: int = 0
    group_id: int | None = None

    @property
    def has_facebook_bill(self) -> bool:
        return self.facebook_bill is not None

    @property
    def has_main_payment(self) -> bool:
        return self.main_payment is not None

    @property
    def bank_documents(self) -> list[Document]:
        """Toàn bộ chứng từ ngân hàng (chính + phí), theo đúng thứ tự."""
        docs = []
        if self.main_payment is not None:
            docs.append(self.main_payment)
        docs.extend(self.fees)
        return docs

    @property
    def all_documents(self) -> list[Document]:
        docs = []
        if self.facebook_bill is not None:
            docs.append(self.facebook_bill)
        docs.extend(self.bank_documents)
        docs.extend(self.supporting)
        return docs

    @property
    def bank_total_debit(self):
        """Tổng số tiền ghi nợ ngân hàng của cả nhóm (main + fee)."""
        amounts = [d.total_amount for d in self.bank_documents if d.total_amount is not None]
        return sum(amounts) if amounts else None
