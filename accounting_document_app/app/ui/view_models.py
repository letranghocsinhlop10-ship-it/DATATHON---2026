"""Chuyển domain object (``Dossier``, ``Document``) thành dữ liệu hiển thị.

Module này KHÔNG import PySide6 và KHÔNG chứa logic nghiệp vụ — chỉ format.
Nhờ vậy test được bằng dữ liệu thuần, không cần QApplication.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.document import Document
from app.models.dossier import Dossier
from app.models.enums import DossierStatus, PaymentGroupStatus, Severity
from app.models.payment_case import PaymentCase
from app.utils.date_utils import format_display
from app.utils.money_utils import format_vnd

__all__ = [
    "StatusColor",
    "STATUS_LABELS",
    "STATUS_COLORS",
    "DossierRow",
    "DocumentRow",
    "PaymentGroupRow",
    "dossier_to_row",
    "document_to_row",
    "payment_group_to_row",
    "status_color",
    "status_label",
    "presence_mark",
    "payment_group_status_color",
    "payment_group_status_label",
]


class StatusColor:
    """Ba màu tô theo §18 Phase 1 — hex để dùng trực tiếp trong Qt style sheet."""

    GREEN = "#1e8e3e"
    YELLOW = "#f9ab00"
    RED = "#d93025"


#: Nhãn tiếng Việt hiển thị cho từng trạng thái dossier.
STATUS_LABELS: dict[DossierStatus, str] = {
    DossierStatus.VALID: "HỢP LỆ",
    DossierStatus.MISSING_META: "THIẾU META",
    DossierStatus.MISSING_DEBIT: "THIẾU DEBIT NOTE",
    DossierStatus.MISSING_VAT: "THIẾU HĐ GTGT",
    DossierStatus.DUPLICATE_META: "TRÙNG META",
    DossierStatus.DUPLICATE_DEBIT: "TRÙNG DEBIT NOTE",
    DossierStatus.DUPLICATE_VAT: "TRÙNG HĐ GTGT",
    DossierStatus.INVALID_REFERENCE: "REFERENCE SAI ĐỊNH DẠNG",
    DossierStatus.NEEDS_REVIEW: "CẦN KIỂM TRA LẠI",
}

#: Màu tô theo trạng thái — xanh=VALID, vàng=NEEDS_REVIEW, đỏ=còn lại.
STATUS_COLORS: dict[DossierStatus, str] = {
    DossierStatus.VALID: StatusColor.GREEN,
    DossierStatus.NEEDS_REVIEW: StatusColor.YELLOW,
}


def status_color(status: DossierStatus) -> str:
    """Màu hex tương ứng một trạng thái dossier."""
    return STATUS_COLORS.get(status, StatusColor.RED)


def status_label(status: DossierStatus) -> str:
    """Nhãn tiếng Việt tương ứng một trạng thái dossier."""
    return STATUS_LABELS.get(status, status.value)


def presence_mark(count: int) -> str:
    """Ký hiệu hiển thị số lượng chứng từ của một vai trò trong bảng chính.

    Examples:
        >>> presence_mark(0)
        '✗'
        >>> presence_mark(1)
        '✓'
        >>> presence_mark(2)
        '✓✓'
    """
    if count == 0:
        return "✗"
    return "✓" * count


@dataclass(frozen=True)
class DossierRow:
    """Một dòng trong bảng Hồ sơ (§8.1)."""

    dossier_id: int | None
    dossier_code: str
    reference: str
    transaction_date: str
    meta_mark: str
    debit_mark: str
    vat_mark: str
    status_text: str
    status_color: str
    reviewed: bool
    has_warning: bool


def dossier_to_row(dossier: Dossier) -> DossierRow:
    """Chuyển một ``Dossier`` thành dòng bảng hiển thị.

    Args:
        dossier: Dossier đã qua ``DossierValidator``.

    Returns:
        ``DossierRow`` — không còn logic quyết định, chỉ để vẽ lên bảng.
    """
    return DossierRow(
        dossier_id=dossier.dossier_id,
        dossier_code=dossier.dossier_code,
        reference=dossier.reference or "—",
        transaction_date=format_display(dossier.transaction_date) or "—",
        meta_mark=presence_mark(dossier.meta_count),
        debit_mark=presence_mark(dossier.debit_count),
        vat_mark=presence_mark(dossier.vat_count),
        status_text=status_label(dossier.status),
        status_color=status_color(dossier.status),
        reviewed=dossier.reviewed,
        has_warning=any(i.severity is Severity.WARNING for i in dossier.issues),
    )


@dataclass(frozen=True)
class DocumentRow:
    """Một dòng trong tab Chứng từ (§8.1, tab thứ hai)."""

    document_id: int | None
    file_name: str
    document_type: str
    reference: str
    total_amount: str
    document_date: str
    status: str


def document_to_row(document: Document) -> DocumentRow:
    """Chuyển một ``Document`` thành dòng bảng hiển thị."""
    return DocumentRow(
        document_id=document.document_id,
        file_name=document.file_name,
        document_type=document.document_type.value,
        reference=document.display_reference or document.reference_number or "—",
        total_amount=format_vnd(document.total_amount) or "—",
        document_date=format_display(document.document_date) or "—",
        status=document.processing_status.value,
    )


#: Nhãn tiếng Việt cho trạng thái payment group (§G/§L).
PAYMENT_GROUP_STATUS_LABELS: dict[PaymentGroupStatus, str] = {
    PaymentGroupStatus.MATCHED_HIGH: "KHỚP CAO",
    PaymentGroupStatus.MATCHED: "ĐÃ KHỚP",
    PaymentGroupStatus.NEEDS_REVIEW: "CẦN KIỂM TRA",
    PaymentGroupStatus.UNMATCHED: "CHƯA KHỚP",
}

#: Màu tô theo trạng thái payment group — xanh=khớp cao, xanh nhạt=đã khớp,
#: vàng=cần kiểm tra, đỏ=chưa khớp.
PAYMENT_GROUP_STATUS_COLORS: dict[PaymentGroupStatus, str] = {
    PaymentGroupStatus.MATCHED_HIGH: StatusColor.GREEN,
    PaymentGroupStatus.MATCHED: "#4285f4",
    PaymentGroupStatus.NEEDS_REVIEW: StatusColor.YELLOW,
}


def payment_group_status_color(status: PaymentGroupStatus) -> str:
    """Màu hex tương ứng một trạng thái payment group."""
    return PAYMENT_GROUP_STATUS_COLORS.get(status, StatusColor.RED)


def payment_group_status_label(status: PaymentGroupStatus) -> str:
    """Nhãn tiếng Việt tương ứng một trạng thái payment group."""
    return PAYMENT_GROUP_STATUS_LABELS.get(status, status.value)


@dataclass(frozen=True)
class PaymentGroupRow:
    """Một dòng trong bảng chính (bank-agnostic):
    Reference | Bank | Meta | Debit | Fee | VAT | Status."""

    group_code: str
    reference: str
    bank: str
    meta_mark: str
    debit_mark: str
    fee_count: str
    vat_mark: str
    status_text: str
    status_color: str
    has_warning: bool


def payment_group_to_row(case: PaymentCase) -> PaymentGroupRow:
    """Chuyển một ``PaymentCase`` thành dòng bảng hiển thị.

    ``debit_mark`` = ✓ nếu có ``main_payment`` — bất kể VPBank hay
    VietinBank (bank-agnostic, không đặc cách ngân hàng nào).
    """
    bank = case.bank_name or case.expected_bank or "—"
    return PaymentGroupRow(
        group_code=case.group_code,
        reference=case.reference or "—",
        bank=bank,
        meta_mark=presence_mark(1 if case.meta_bill else 0),
        debit_mark=presence_mark(1 if case.main_payment else 0),
        fee_count=str(len(case.fees)) if case.fees else "—",
        vat_mark=presence_mark(1 if case.vat_invoice else 0),
        status_text=payment_group_status_label(case.status),
        status_color=payment_group_status_color(case.status),
        has_warning=case.bank_mismatch,
    )
