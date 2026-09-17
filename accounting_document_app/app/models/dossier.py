"""Model ``Dossier`` — một bộ hồ sơ ghép từ 1 Meta + 1 Debit Note + 1 VAT.

Xem luật đầy đủ ở ``docs/PHASE1_ARCHITECTURE.md`` §12-§17 và
``docs/PHASE1_ADDENDUM_SAMPLE_ANALYSIS.md`` §2.2 (luật K1/K2 cho VAT).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from app.models.enums import DossierStatus, MatchSource, Severity

__all__ = ["DossierIssue", "Dossier"]

#: Thứ tự ưu tiên khi một dossier có nhiều vấn đề cùng lúc — status hiển thị
#: là mã có độ ưu tiên CAO NHẤT (nhỏ nhất trong danh sách này) đang có mặt.
_STATUS_PRIORITY: tuple[DossierStatus, ...] = (
    DossierStatus.DUPLICATE_META,
    DossierStatus.DUPLICATE_DEBIT,
    DossierStatus.DUPLICATE_VAT,
    DossierStatus.INVALID_REFERENCE,
    DossierStatus.MISSING_META,
    DossierStatus.MISSING_DEBIT,
    DossierStatus.MISSING_VAT,
    DossierStatus.NEEDS_REVIEW,
    DossierStatus.VALID,
)


@dataclass(frozen=True)
class DossierIssue:
    """Một vấn đề phát hiện được trên một dossier.

    Attributes:
        code: Mã lỗi nghiệp vụ, ví dụ ``MISSING_VAT``, ``AMOUNT_CHAIN_BROKEN``.
        severity: ``BLOCKING`` chặn trạng thái ``VALID``; ``WARNING``/``INFO``
            chỉ hiển thị để người dùng đối chiếu, không chặn.
        description: Mô tả bằng tiếng Việt để hiển thị trực tiếp cho kế toán.
        document_id: Chứng từ liên quan, nếu vấn đề gắn với một file cụ thể.
        suggested_action: Gợi ý hành động, hiển thị ở sheet CHECK_ERROR.
    """

    code: str
    severity: Severity
    description: str
    document_id: int | None = None
    suggested_action: str | None = None


@dataclass
class Dossier:
    """Một bộ hồ sơ chi phí Marketing.

    Ba ``*_document_id`` chỉ giữ chứng từ CHÍNH (khi có nhiều bản trùng, các
    bản còn lại nằm trong ``extra_documents`` và trường chính để trống cho
    tới khi người dùng chọn — không tự động chọn thay).
    """

    dossier_code: str
    reference: str | None
    dossier_id: int | None = None

    meta_document_id: int | None = None
    debit_document_id: int | None = None
    vat_document_id: int | None = None

    #: Số chứng từ thực tế tìm thấy cho mỗi vai trò trong cùng khoá — nguồn
    #: chân lý DUY NHẤT để quyết định MISSING_*/DUPLICATE_* (bảng §7.1).
    #: KHÔNG được suy ngược từ ``extra_documents`` (danh sách đó không phân
    #: loại nên không thể tách "trùng Meta" hay "trùng Debit").
    meta_count: int = 0
    debit_count: int = 0
    vat_count: int = 0

    #: document_id của MỌI chứng từ thuộc khoá này (kể cả bản chính) — chỉ
    #: để hiển thị/audit ở UI, không dùng cho logic quyết định status.
    extra_documents: tuple[int, ...] = field(default_factory=tuple)

    card_last4: str | None = None
    transaction_date: date | None = None

    status: DossierStatus = DossierStatus.NEEDS_REVIEW
    match_source: MatchSource = MatchSource.AUTO_EXACT
    issues: list[DossierIssue] = field(default_factory=list)

    reviewed: bool = False
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None

    folder_path: str | None = None
    notes: str | None = None
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def is_complete(self) -> bool:
        """Có đủ cả ba chứng từ chính hay không (không xét duplicate/lỗi)."""
        return all([self.meta_document_id, self.debit_document_id, self.vat_document_id])

    @property
    def blocking_issues(self) -> tuple[DossierIssue, ...]:
        return tuple(i for i in self.issues if i.severity is Severity.BLOCKING)

    @property
    def warning_issues(self) -> tuple[DossierIssue, ...]:
        return tuple(i for i in self.issues if i.severity is Severity.WARNING)

    @property
    def has_blocking_issue(self) -> bool:
        return any(i.severity is Severity.BLOCKING for i in self.issues)

    def issue_codes(self) -> tuple[str, ...]:
        return tuple(i.code for i in self.issues)

    def add_issue(self, issue: DossierIssue) -> None:
        self.issues.append(issue)

    @staticmethod
    def resolve_status(present_codes: set[str]) -> DossierStatus:
        """Chọn status hiển thị theo thứ tự ưu tiên khi có nhiều mã lỗi.

        Args:
            present_codes: Tập mã ``DossierStatus`` đang áp dụng cho dossier
                (ví dụ có thể có cả ``MISSING_VAT`` và ``NEEDS_REVIEW`` cùng lúc).

        Returns:
            Status duy nhất, ưu tiên cao nhất, dùng để hiển thị và tô màu.
        """
        for candidate in _STATUS_PRIORITY:
            if candidate.value in present_codes:
                return candidate
        return DossierStatus.VALID
