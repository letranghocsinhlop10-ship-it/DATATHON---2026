"""Sinh các dòng bút toán MISA SME 2023 từ dossier ``VALID``.

Cơ chế template hai lớp (xem ``app/config_loader.py``):

1. ``${accounts.*}`` / ``${parameters.*}`` — đã resolve TĨNH lúc nạp
   ``config/misa_mapping.yaml`` (một lần, không phụ thuộc dossier).
2. ``${meta.field}`` / ``${bank_vat.field}`` / ``${debit.field}`` — resolve
   ĐỘNG ở đây, theo đúng chứng từ của TỪNG dossier. Có thể kèm hậu tố định
   dạng ``|dd/mm/yyyy`` cho ngày tháng.

``condition`` và ``amount`` là biểu thức hạn chế kiểu ``"<role>.<field>"`` —
được diễn giải bằng một trình đọc thuộc tính an toàn (``_RoleAccessor``),
KHÔNG dùng ``eval()`` trên dữ liệu PDF, chỉ trên chuỗi cấu hình do người
phát triển viết.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.config_loader import MisaLineRule, MisaMappingConfig
from app.models.document import Document
from app.models.dossier import Dossier
from app.utils.date_utils import format_display

__all__ = ["MisaRow", "MisaBuildResult", "MisaExporter"]

logger = logging.getLogger(__name__)

#: ``${role.field}`` hoặc ``${role.field|format}`` — role/field resolve động.
_ROW_PLACEHOLDER_RE = re.compile(r"\$\{(\w+)\.(\w+)(?:\|([^}]+))\}|\$\{(\w+)\.(\w+)\}")

#: Điều kiện chỉ được viết dưới dạng so sánh đơn giản nối bằng "and"/"or":
#:   <role>.<field> is not None
#:   <role>.<field> is None
#:   <role>.<field> > 0
#: Không hỗ trợ biểu thức lồng nhau hay hàm — cố ý hạn chế bề mặt cú pháp.
_CONDITION_TERM_RE = re.compile(
    r"^\s*(\w+)\.(\w+)\s*(is not None|is None|>|>=|<|<=|==|!=)\s*(None|-?\d+(?:\.\d+)?)?\s*$"
)


class _RoleAccessor:
    """Bọc một ``Document`` (hoặc ``None``) để đọc thuộc tính an toàn.

    ``getattr(accessor, "subtotal")`` -> ``document.value_of("subtotal")``.
    Khi ``document is None``, mọi thuộc tính trả về ``None`` — điều kiện dạng
    ``bank_vat.subtotal is not None`` vì vậy tự nhiên là ``False`` mà không
    cần kiểm tra ``bank_vat is None`` riêng.
    """

    def __init__(self, document: Document | None) -> None:
        self._document = document

    def get(self, field_name: str) -> Any:
        if self._document is None:
            return None
        if field_name == "total_amount":
            return self._document.total_amount
        return self._document.value_of(field_name)


@dataclass(frozen=True)
class MisaRow:
    """Một dòng bút toán MISA đã sinh cho một dossier.

    Attributes:
        dossier_code: Hồ sơ nguồn, để đối chiếu.
        rule_id: Dòng luật đã sinh ra bút toán này.
        values: Dữ liệu đã resolve, khớp thứ tự ``line.*`` trong luật —
            KHÔNG phải 34 cột cuối cùng (việc rải vào 34 cột do
            ``ExcelExporter`` làm, dùng ``MisaMappingConfig.columns``).
        missing_fields: Các placeholder trong ``description`` không đọc
            được (giá trị ``None``) — ghi lại để cảnh báo, KHÔNG chặn xuất.
    """

    dossier_code: str
    rule_id: str
    values: dict[str, Any] = field(default_factory=dict)
    missing_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class MisaBuildResult:
    rows: list[MisaRow] = field(default_factory=list)
    #: dossier_code -> lý do không sinh được dòng nào (ví dụ thiếu số chứng từ).
    skipped: dict[str, str] = field(default_factory=dict)


class MisaExporter:
    """Sinh danh sách ``MisaRow`` từ dossier + luật đã nạp.

    Args:
        config: ``MisaMappingConfig`` đã resolve placeholder tĩnh.
    """

    def __init__(self, config: MisaMappingConfig) -> None:
        self._config = config

    def build(
        self,
        dossiers: list[Dossier],
        documents_by_id: dict[int, Document],
        *,
        voucher_start: int,
        only_valid: bool = True,
        require_reviewed: bool = False,
    ) -> MisaBuildResult:
        """Sinh toàn bộ dòng bút toán cho một lô dossier.

        Args:
            dossiers: Dossier đã validate.
            documents_by_id: Tra cứu ``Document`` theo id.
            voucher_start: Số thứ tự BẮT ĐẦU cho ``Số chứng từ`` (Q21 — kế
                toán tự nhập, app không suy đoán).
            only_valid: Chỉ xuất dossier ``VALID`` (mặc định — đúng §9 Phase 1).
            require_reviewed: Chỉ xuất dossier đã ``reviewed=True``.

        Returns:
            ``MisaBuildResult`` — mỗi dòng bút toán kèm dossier nguồn, cộng
            danh sách dossier bị bỏ qua kèm lý do (để hiển thị, không âm thầm).
        """
        result = MisaBuildResult()
        sequence = voucher_start

        for dossier in dossiers:
            if only_valid and dossier.status.value != "VALID":
                continue
            if require_reviewed and not dossier.reviewed:
                result.skipped[dossier.dossier_code] = "Chưa được đánh dấu đã review"
                continue

            meta = _RoleAccessor(documents_by_id.get(dossier.meta_document_id))
            debit = _RoleAccessor(documents_by_id.get(dossier.debit_document_id))
            bank_vat = _RoleAccessor(documents_by_id.get(dossier.vat_document_id))
            roles = {"meta": meta, "debit": debit, "bank_vat": bank_vat}

            produced_any = False
            for rule in self._config.lines:
                if not rule.enabled:
                    continue
                if not self._evaluate_condition(rule.condition, roles):
                    continue

                amount = self._evaluate_amount(rule.amount_expr, roles)
                if amount is None:
                    logger.warning(
                        "%s: điều kiện dòng %s đúng nhưng amount %s vẫn None — bỏ qua dòng này",
                        dossier.dossier_code,
                        rule.rule_id,
                        rule.amount_expr,
                    )
                    continue

                description, missing = self._resolve_description(rule.description_template, roles)
                voucher_number = self._config.voucher_number.format(sequence)
                sequence += self._config.voucher_number.increment

                doc_date = meta.get("document_date") or debit.get("transaction_date")
                values = {
                    "voucher_number": voucher_number,
                    "document_date": doc_date,
                    "posting_date": doc_date,
                    "description": description,
                    "debit_account": rule.debit_account,
                    "credit_account": rule.credit_account,
                    "amount": amount,
                    "credit_object": rule.credit_object,
                }
                result.rows.append(
                    MisaRow(
                        dossier_code=dossier.dossier_code,
                        rule_id=rule.rule_id,
                        values=values,
                        missing_fields=missing,
                    )
                )
                produced_any = True

            if not produced_any:
                result.skipped[dossier.dossier_code] = (
                    "Không có dòng bút toán nào thoả điều kiện (kiểm tra lại dữ liệu hoá đơn)"
                )

        return result

    # ------------------------------------------------------------- helpers

    @staticmethod
    def _evaluate_condition(condition: str, roles: dict[str, _RoleAccessor]) -> bool:
        """Đánh giá điều kiện dạng ``A and B`` — mỗi vế qua ``_CONDITION_TERM_RE``."""
        terms = re.split(r"\s+(and|or)\s+", condition.strip())
        if not terms:
            return True

        values: list[bool] = []
        operators: list[str] = []
        for token in terms:
            if token in ("and", "or"):
                operators.append(token)
                continue
            values.append(MisaExporter._evaluate_term(token, roles))

        result = values[0]
        for operator, value in zip(operators, values[1:]):
            result = (result and value) if operator == "and" else (result or value)
        return result

    @staticmethod
    def _evaluate_term(term: str, roles: dict[str, _RoleAccessor]) -> bool:
        match = _CONDITION_TERM_RE.match(term)
        if not match:
            raise ValueError(f"Điều kiện MISA không hợp lệ (chỉ hỗ trợ so sánh đơn giản): {term!r}")
        role_name, field_name, op, literal = match.groups()
        if role_name not in roles:
            raise ValueError(f"Điều kiện tham chiếu role không tồn tại: {role_name}")
        value = roles[role_name].get(field_name)

        if op == "is not None":
            return value is not None
        if op == "is None":
            return value is None
        if value is None:
            return False  # so sánh số với None -> luôn False, không suy đoán
        number = Decimal(literal) if isinstance(value, Decimal) else float(literal)
        if op == ">":
            return value > number
        if op == ">=":
            return value >= number
        if op == "<":
            return value < number
        if op == "<=":
            return value <= number
        if op == "==":
            return value == number
        return value != number  # "!="

    @staticmethod
    def _evaluate_amount(expr: str, roles: dict[str, _RoleAccessor]) -> Decimal | None:
        role_name, _, field_name = expr.partition(".")
        if role_name not in roles or not field_name:
            raise ValueError(f"Biểu thức amount không hợp lệ: {expr!r}")
        return roles[role_name].get(field_name)

    @staticmethod
    def _resolve_description(
        template: str, roles: dict[str, _RoleAccessor]
    ) -> tuple[str, tuple[str, ...]]:
        missing: list[str] = []

        def _sub(match: re.Match[str]) -> str:
            role_name = match.group(1) or match.group(4)
            field_name = match.group(2) or match.group(5)
            fmt = match.group(3)

            if role_name not in roles:
                raise ValueError(f"Diễn giải MISA tham chiếu role không tồn tại: {role_name}")
            value = roles[role_name].get(field_name)
            if value is None:
                missing.append(f"{role_name}.{field_name}")
                return ""
            if isinstance(value, date) and fmt in ("dd/mm/yyyy", None):
                return format_display(value)
            return str(value)

        resolved = _ROW_PLACEHOLDER_RE.sub(_sub, template)
        resolved = re.sub(r"\s+", " ", resolved).strip()
        return resolved, tuple(missing)
