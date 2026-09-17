"""Kiểm tra một ``Dossier`` đã dựng — quyết định status cuối cùng.

Hai lớp luật, không bao giờ trộn lẫn:

* **BLOCKING** (bảng quyết định §7.1 Phase 1) — quyết định trực tiếp status
  hiển thị: thiếu chứng từ, trùng chứng từ, reference sai định dạng, hai
  khoá K1/K2 mâu thuẫn nhau. Một dossier có bất kỳ BLOCKING nào thì KHÔNG
  BAO GIỜ là ``VALID``.
* **WARNING/INFO** (§7.2 + `AMOUNT_CHAIN` phát hiện từ phụ lục mẫu) — chỉ
  đối chiếu chéo, hiển thị để kế toán tự kiểm tra. KHÔNG BAO GIỜ dùng để
  tạo, gỡ hay thay đổi liên kết đã ghép (§14 — nguyên tắc an toàn tối cao).

``DossierValidator`` là hàm thuần trên dữ liệu đã có sẵn trong bộ nhớ —
không đọc PDF lại, không truy vấn DB.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.models.document import Document
from app.models.dossier import Dossier, DossierIssue
from app.models.enums import DossierStatus, Severity, TextSource

__all__ = ["ValidationConfig", "DossierValidator"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidationConfig:
    """Ngưỡng và tuỳ chọn cho các kiểm tra chéo mức WARNING/INFO.

    Attributes:
        max_date_gap_days: Số ngày lệch tối đa giữa hoá đơn Meta và giao dịch
            ngân hàng trước khi cảnh báo ``DATE_GAP_TOO_LARGE``.
        amount_chain_tolerance: Sai lệch cho phép (VND) khi so
            ``debit.total == meta.total + vat.total``.
        company_tax_code: MST công ty (đã chuẩn hoá) để đối chiếu
            ``TAX_CODE_MISMATCH`` với MST khách hàng trên hoá đơn GTGT.
    """

    max_date_gap_days: int = 7
    amount_chain_tolerance: int = 0
    company_tax_code: str | None = None


class DossierValidator:
    """Áp luật kiểm tra lên một ``Dossier`` đã dựng.

    Args:
        config: Ngưỡng kiểm tra chéo; dùng mặc định nếu không truyền.
    """

    def __init__(self, config: ValidationConfig | None = None) -> None:
        self._config = config or ValidationConfig()

    def validate(
        self,
        dossier: Dossier,
        documents_by_id: dict[int, Document],
    ) -> Dossier:
        """Kiểm tra một dossier, ghi thêm issue và cập nhật ``status``.

        Args:
            dossier: Dossier đã dựng bởi ``DossierBuilder`` (issue của bước
                ghép — ``VAT_KEY_CONFLICT``, ``FT_CODE_NOT_IN_VAT``,
                ``META_REF_NOT_IN_VAT`` — đã có sẵn trong ``dossier.issues``).
            documents_by_id: Tra cứu ``Document`` theo ``document_id``.

        Returns:
            Chính ``dossier`` đã truyền vào (sửa tại chỗ), để tiện dùng
            trong vòng lặp xử lý lô.
        """
        meta = self._get(dossier.meta_document_id, documents_by_id)
        debit = self._get(dossier.debit_document_id, documents_by_id)
        vat = self._get(dossier.vat_document_id, documents_by_id)

        self._check_structure(dossier, meta, debit, vat)
        self._check_reference_format(dossier, meta)

        # Các kiểm tra chéo chỉ có ý nghĩa khi đủ dữ liệu để so sánh — không
        # BAO GIỜ được dùng để suy ra dossier thiếu/thừa chứng từ.
        self._check_amount_chain(dossier, meta, debit, vat)
        self._check_card_mismatch(dossier, meta, debit)
        self._check_date_gap(dossier, meta, debit)
        self._check_tax_code_mismatch(dossier, vat)
        self._check_vat_math(dossier, meta, "META_INVOICE")
        self._check_vat_math(dossier, vat, "VPBANK_VAT_INVOICE")
        self._check_ocr_sourced(dossier, meta, debit, vat)
        self._check_field_errors(dossier, meta, debit, vat)

        present_codes = {issue.code for issue in dossier.issues if issue.code in _STATUS_CODES}
        if any(issue.severity is Severity.BLOCKING for issue in dossier.issues):
            present_codes.add("NEEDS_REVIEW")
        dossier.status = Dossier.resolve_status(present_codes)
        return dossier

    # ------------------------------------------------------------- helper

    @staticmethod
    def _get(document_id: int | None, documents_by_id: dict[int, Document]) -> Document | None:
        if document_id is None:
            return None
        return documents_by_id.get(document_id)

    # --------------------------------------------------------- cấu trúc §7.1

    def _check_structure(
        self,
        dossier: Dossier,
        meta: Document | None,
        debit: Document | None,
        vat: Document | None,
    ) -> None:
        meta_count, debit_count, vat_count = dossier.meta_count, dossier.debit_count, dossier.vat_count

        if meta_count >= 2:
            self._add_missing_or_duplicate(dossier, "DUPLICATE_META", "Có nhiều hơn 1 hoá đơn Meta cùng reference")
        if debit_count >= 2:
            self._add_missing_or_duplicate(
                dossier, "DUPLICATE_DEBIT", "Có nhiều hơn 1 Debit Note cùng reference"
            )
        if vat_count >= 2:
            self._add_missing_or_duplicate(
                dossier, "DUPLICATE_VAT", "Có nhiều hơn 1 hoá đơn GTGT cùng reference"
            )

        if meta_count == 0:
            self._add_missing_or_duplicate(dossier, "MISSING_META", "Không tìm thấy hoá đơn Meta cho reference này")
        if debit_count == 0:
            self._add_missing_or_duplicate(dossier, "MISSING_DEBIT", "Không tìm thấy Debit Note cho reference này")
        if vat_count == 0:
            self._add_missing_or_duplicate(
                dossier, "MISSING_VAT", "Không tìm thấy hoá đơn GTGT phí ngân hàng cho reference này"
            )

    def _add_missing_or_duplicate(self, dossier: Dossier, code: str, description: str) -> None:
        dossier.add_issue(
            DossierIssue(code=code, severity=Severity.BLOCKING, description=description)
        )

    # ---------------------------------------------------- reference format

    def _check_reference_format(self, dossier: Dossier, meta: Document | None) -> None:
        if meta is None:
            return
        field = meta.field_of("reference_number")
        if field.found and field.error == "REFERENCE_INVALID_FORMAT":
            dossier.add_issue(
                DossierIssue(
                    code="INVALID_REFERENCE",
                    severity=Severity.BLOCKING,
                    description=(
                        f"Số tham chiếu {field.value!r} không khớp định dạng chuẩn — kiểm tra lại"
                    ),
                    document_id=meta.document_id,
                    suggested_action="Mở PDF gốc đối chiếu Số tham chiếu",
                )
            )

    # -------------------------------------------------------- amount chain

    def _check_amount_chain(
        self, dossier: Dossier, meta: Document | None, debit: Document | None, vat: Document | None
    ) -> None:
        if meta is None or debit is None or vat is None:
            return
        meta_total = meta.total_amount
        vat_total = vat.total_amount
        debit_total = debit.total_amount
        if not all(isinstance(x, Decimal) for x in (meta_total, vat_total, debit_total)):
            return

        expected = meta_total + vat_total
        diff = abs(expected - debit_total)
        if diff <= self._config.amount_chain_tolerance:
            dossier.add_issue(
                DossierIssue(
                    code="AMOUNT_CHAIN_OK",
                    severity=Severity.INFO,
                    description="debit = tổng hoá đơn Meta + tổng phí ngân hàng — khớp",
                )
            )
        else:
            dossier.add_issue(
                DossierIssue(
                    code="AMOUNT_CHAIN_BROKEN",
                    severity=Severity.WARNING,
                    description=(
                        f"Debit Note ghi {debit_total}, nhưng Meta + phí ngân hàng = {expected} "
                        f"(lệch {diff})"
                    ),
                    suggested_action="Kiểm tra có giao dịch nào bị gộp/thiếu trong Debit Note",
                )
            )

    # -------------------------------------------------------------- card

    def _check_card_mismatch(
        self, dossier: Dossier, meta: Document | None, debit: Document | None
    ) -> None:
        if meta is None or debit is None:
            return
        meta_card, debit_card = meta.card_last4, debit.card_last4
        if meta_card and debit_card and meta_card != debit_card:
            dossier.add_issue(
                DossierIssue(
                    code="CARD_MISMATCH",
                    severity=Severity.WARNING,
                    description=f"4 số cuối thẻ khác nhau: Meta={meta_card}, Debit Note={debit_card}",
                )
            )

    # -------------------------------------------------------------- ngày

    def _check_date_gap(
        self, dossier: Dossier, meta: Document | None, debit: Document | None
    ) -> None:
        if meta is None or debit is None:
            return
        meta_date, debit_date = meta.document_date, debit.transaction_date
        if not isinstance(meta_date, date) or not isinstance(debit_date, date):
            return
        gap = abs((meta_date - debit_date).days)
        if gap > self._config.max_date_gap_days:
            dossier.add_issue(
                DossierIssue(
                    code="DATE_GAP_TOO_LARGE",
                    severity=Severity.WARNING,
                    description=(
                        f"Ngày hoá đơn Meta ({meta_date}) và ngày giao dịch ngân hàng "
                        f"({debit_date}) lệch {gap} ngày, vượt ngưỡng {self._config.max_date_gap_days}"
                    ),
                )
            )

    # ------------------------------------------------------------- MST

    def _check_tax_code_mismatch(self, dossier: Dossier, vat: Document | None) -> None:
        if vat is None or not self._config.company_tax_code:
            return
        customer_tax_code = vat.value_of("tax_code")
        if customer_tax_code and customer_tax_code != self._config.company_tax_code:
            dossier.add_issue(
                DossierIssue(
                    code="TAX_CODE_MISMATCH",
                    severity=Severity.WARNING,
                    description=(
                        f"MST khách hàng trên hoá đơn GTGT ({customer_tax_code}) khác MST "
                        f"công ty đã cấu hình ({self._config.company_tax_code})"
                    ),
                    document_id=vat.document_id,
                )
            )

    # --------------------------------------------------------- toán hoá đơn

    def _check_vat_math(self, dossier: Dossier, doc: Document | None, label: str) -> None:
        if doc is None:
            return
        subtotal, vat_amount, total = doc.value_of("subtotal"), doc.value_of("vat_amount"), doc.total_amount
        if not isinstance(subtotal, Decimal) or not isinstance(total, Decimal):
            return
        vat_amount = vat_amount if isinstance(vat_amount, Decimal) else Decimal(0)
        if subtotal + vat_amount != total:
            dossier.add_issue(
                DossierIssue(
                    code="VAT_MATH_ERROR",
                    severity=Severity.WARNING,
                    description=(
                        f"{label}: tổng phụ ({subtotal}) + thuế ({vat_amount}) "
                        f"khác tổng tiền ghi trên hoá đơn ({total})"
                    ),
                    document_id=doc.document_id,
                )
            )

    # ------------------------------------------------------------- OCR

    def _check_ocr_sourced(
        self, dossier: Dossier, meta: Document | None, debit: Document | None, vat: Document | None
    ) -> None:
        for doc in (meta, debit, vat):
            if doc is not None and doc.text_source is not TextSource.TEXT_LAYER:
                dossier.add_issue(
                    DossierIssue(
                        code="OCR_SOURCED_DATA",
                        severity=Severity.INFO,
                        description=f"{doc.file_name} có dữ liệu đọc qua OCR — độ tin cậy thấp hơn",
                        document_id=doc.document_id,
                    )
                )

    # -------------------------------------------------------- lỗi trường

    def _check_field_errors(
        self, dossier: Dossier, meta: Document | None, debit: Document | None, vat: Document | None
    ) -> None:
        for doc in (meta, debit, vat):
            if doc is None:
                continue
            for field_name, error in doc.field_errors.items():
                if error == "UNEXPECTED_MERCHANT_SUFFIX":
                    dossier.add_issue(
                        DossierIssue(
                            code="UNEXPECTED_MERCHANT_SUFFIX",
                            severity=Severity.INFO,
                            description=(
                                f"{doc.file_name}: đuôi mô tả sau reference khác kỳ vọng cấu hình"
                            ),
                            document_id=doc.document_id,
                        )
                    )


#: Các mã issue quyết định status (dùng cho ``Dossier.resolve_status``).
_STATUS_CODES = {s.value for s in DossierStatus}
