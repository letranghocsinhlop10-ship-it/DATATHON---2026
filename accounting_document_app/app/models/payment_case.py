"""Model ``PaymentCase`` — một khoản thanh toán (Meta/Facebook Ads) đã gộp bộ.

BANK-AGNOSTIC theo thiết kế: một case có thể được thanh toán qua VPBank
HOẶC VietinBank — matcher/UI/organizer không bao giờ giả định một ngân hàng
cụ thể, chỉ đọc field ``bank_name`` (suy ra từ ``document_type`` thực tế của
``main_payment``/``fees`` qua ``app/matching/payment_group_matcher.py:bank_name_of()``).

Khác với ``Dossier`` (Phase 3, ghép đúng-3-loại META/DEBIT/VAT bằng exact
reference duy nhất, một ngân hàng cố định VPBank), một payment case có thể
gồm nhiều loại nguồn khác nhau (Meta Bill, chứng từ ngân hàng CHÍNH, phí
ngân hàng, hoá đơn GTGT phí, dòng sao kê) và được ghép bởi
``app/matching/payment_group_matcher.py`` theo thang tín hiệu ưu tiên (exact
reference > expected_bank từ thẻ > mã giao dịch > ngày/giờ > số tiền) thay
vì chỉ so bằng nhau tuyệt đối.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.core.bank_statement_parser import BankTransaction
from app.models.document import Document
from app.models.enums import PaymentGroupStatus

__all__ = ["PaymentCase"]


@dataclass
class PaymentCase:
    """Một bộ chứng từ xoay quanh một khoản thanh toán, bất kể ngân hàng nào.

    Attributes:
        group_code: Mã hiển thị, vd. ``"2026-08-01_ABCD1234EF"``.
        reference: Reference Meta/Facebook đã chuẩn hoá — ``None`` khi case
            này được ghép qua fallback (không có reference).
        transaction_date: Ngày giao dịch dùng làm khoá phân biệt — cùng
            reference nhưng khác ngày KHÔNG được gộp chung.
        expected_bank: Ngân hàng suy ra từ 4 số cuối thẻ trên Meta Bill
            (``config/bank_mapping.yaml``) — ``None`` nếu không có thẻ hoặc
            không có ánh xạ. CHỈ để đối chiếu/hiển thị, không tự loại liên
            kết khi lệch với ngân hàng thực tế.
        meta_bill: Hoá đơn Meta/Facebook (``DocumentType.META_INVOICE``).
        main_payment: Chứng từ ngân hàng của khoản thanh toán CHÍNH — có thể
            là ``VPBANK_DEBIT_NOTE`` hoặc ``VIETINBANK_DEBIT_ADVICE``, đọc
            ngân hàng thực tế qua ``bank_name`` bên dưới.
        fees: Chứng từ phí ngân hàng đi kèm (0 hoặc nhiều, cùng ngân hàng
            với ``main_payment`` trong đa số trường hợp thật).
        vat_invoice: Hoá đơn GTGT của phí ngân hàng (nếu có) — ghép bằng
            đúng cơ chế exact reference như các chứng từ khác, KHÔNG ghép
            chỉ vì cùng ngày/số tiền.
        statement_rows: Dòng sao kê khớp được.
        supporting: Chứng từ hỗ trợ khác (vd. PDF trích xuất tự sinh từ sao
            kê khi không có phiếu ngân hàng gốc).
        status: Trạng thái khớp cuối cùng.
        confidence: Nhãn độ tin cậy ngắn gọn (khớp ``status`` nhưng dùng để
            hiển thị/Excel), vd. ``"HIGH"``/``"MEDIUM"``/``"LOW"``.
        reason: Giải thích NGƯỜI ĐỌC ĐƯỢC vì sao có kết quả này — bắt buộc
            khác rỗng, dùng trực tiếp cho cột ``match_reason`` khi xuất Excel.
        ambiguous_candidates: Số ứng viên gây mơ hồ (0 khi không mơ hồ) —
            phục vụ debug/hiển thị, không ảnh hưởng logic.
        group_id: Id sau khi lưu DB, ``None`` nếu chưa lưu (case hiện giữ
            trong bộ nhớ giữa các bước MATCH/ORGANIZE/EXPORT, chưa có bảng
            DB riêng — xem ghi chú trong README).
    """

    group_code: str
    reference: str | None = None
    transaction_date: date | None = None
    expected_bank: str | None = None
    meta_bill: Document | None = None
    main_payment: Document | None = None
    fees: list[Document] = field(default_factory=list)
    vat_invoice: Document | None = None
    statement_rows: list[BankTransaction] = field(default_factory=list)
    supporting: list[Document] = field(default_factory=list)
    status: PaymentGroupStatus = PaymentGroupStatus.UNMATCHED
    confidence: str = "NONE"
    reason: str = ""
    ambiguous_candidates: int = 0
    group_id: int | None = None

    @property
    def has_meta_bill(self) -> bool:
        return self.meta_bill is not None

    @property
    def has_main_payment(self) -> bool:
        return self.main_payment is not None

    @property
    def bank_name(self) -> str | None:
        """Ngân hàng THỰC TẾ của case — suy từ chứng từ ngân hàng đã ghép
        được (main trước, fee sau), KHÔNG phải ``expected_bank``."""
        from app.matching.payment_group_matcher import bank_name_of

        if self.main_payment is not None:
            return bank_name_of(self.main_payment)
        if self.fees:
            return bank_name_of(self.fees[0])
        return None

    @property
    def bank_mismatch(self) -> bool:
        """``True`` khi có cả hai tín hiệu nhưng LỆCH ngân hàng — tín hiệu
        hiển thị, KHÔNG tự loại liên kết (xem docstring module)."""
        actual = self.bank_name
        return self.expected_bank is not None and actual is not None and self.expected_bank != actual

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
        if self.meta_bill is not None:
            docs.append(self.meta_bill)
        docs.extend(self.bank_documents)
        if self.vat_invoice is not None:
            docs.append(self.vat_invoice)
        docs.extend(self.supporting)
        return docs

    @property
    def bank_total_debit(self):
        """Tổng số tiền ghi nợ ngân hàng của cả nhóm (main + fee)."""
        amounts = [d.total_amount for d in self.bank_documents if d.total_amount is not None]
        return sum(amounts) if amounts else None
