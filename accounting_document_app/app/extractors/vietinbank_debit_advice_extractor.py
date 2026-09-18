"""Trích xuất một trang "GIẤY BÁO NỢ / Debit Advice" của VietinBank.

Mỗi file ở đây LUÔN là một PDF MỘT TRANG — kết quả của
``app/core/debit_advice_splitter.py`` tách vật lý từ file gốc nhiều trang.
Ngoài các trường có nhãn rõ ràng, extractor còn suy ra hai trường không có
nhãn trên chứng từ:

* ``facebook_reference`` — bóc từ ``remarks`` bằng
  ``normalize_facebook_reference`` (giống cách ``VPBankDebitNoteExtractor``
  bóc ``meta_reference`` từ ``payment_detail``).
* ``payment_role`` — ``BANK_FEE`` nếu diễn giải bắt đầu bằng "Phi GD..."
  (phí giao dịch), ngược lại ``MAIN_PAYMENT`` khi có tham chiếu Facebook.
  Đây là tín hiệu THÔ cho ``app/matching/payment_group_matcher.py`` quyết
  định cuối cùng — bản thân field này không tự tạo/loại bỏ liên kết nào.
"""

from __future__ import annotations

import logging

from app.core.text_normalizer import classify_bank_remark_role, normalize_facebook_reference
from app.extractors.base_extractor import BaseExtractor
from app.extractors.rule_engine import ExtractionContext
from app.models.enums import DocumentType, FieldMethod
from app.models.extracted_field import ExtractedField, FieldSet

__all__ = ["VietinBankDebitAdviceExtractor"]

logger = logging.getLogger(__name__)


class VietinBankDebitAdviceExtractor(BaseExtractor):
    """Extractor cho ``VIETINBANK_DEBIT_ADVICE``."""

    @property
    def document_type(self) -> DocumentType:
        return DocumentType.VIETINBANK_DEBIT_ADVICE

    def post_process(self, ctx: ExtractionContext, fields: FieldSet) -> None:
        remarks = fields.get("remarks")
        fields.set(self._extract_facebook_reference(remarks))
        fields.set(self._extract_payment_role(remarks))

    @staticmethod
    def _extract_facebook_reference(remarks: ExtractedField) -> ExtractedField:
        if not remarks.found:
            return ExtractedField.missing(
                "facebook_reference", rule_id=remarks.rule_id, error="NO_REMARKS"
            )
        value = normalize_facebook_reference(str(remarks.value))
        if value is None:
            return ExtractedField.missing(
                "facebook_reference", rule_id=remarks.rule_id, error="MERCHANT_ANCHOR_NOT_FOUND"
            )
        return ExtractedField(
            field_name="facebook_reference",
            value=value,
            raw_snippet=remarks.raw_snippet,
            page_number=remarks.page_number,
            rule_id=remarks.rule_id,
            method=FieldMethod.DERIVED,
        )

    @staticmethod
    def _extract_payment_role(remarks: ExtractedField) -> ExtractedField:
        if not remarks.found:
            return ExtractedField.missing(
                "payment_role", rule_id=remarks.rule_id, error="NO_REMARKS"
            )
        role = classify_bank_remark_role(str(remarks.value))
        return ExtractedField(
            field_name="payment_role",
            value=role,
            raw_snippet=remarks.raw_snippet,
            page_number=remarks.page_number,
            rule_id=remarks.rule_id,
            method=FieldMethod.DERIVED,
        )
