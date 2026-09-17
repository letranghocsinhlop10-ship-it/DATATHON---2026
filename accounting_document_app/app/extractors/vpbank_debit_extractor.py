"""Trích xuất Phiếu giao dịch ghi nợ (Debit Note) của VPBank."""

from __future__ import annotations

import logging

from app.extractors.base_extractor import BaseExtractor
from app.extractors.merchant_reference import (
    extract_card_last4,
    extract_merchant_reference,
)
from app.extractors.rule_engine import ExtractionContext
from app.models.enums import DocumentType
from app.models.extracted_field import FieldSet

__all__ = ["VPBankDebitNoteExtractor"]

logger = logging.getLogger(__name__)


class VPBankDebitNoteExtractor(BaseExtractor):
    """Extractor cho ``VPBANK_DEBIT_NOTE``.

    Ngoài các trường có nhãn rõ ràng, extractor còn bóc từ phần ``Diễn giải``:
    4 số cuối thẻ và reference của nhà cung cấp.
    """

    @property
    def document_type(self) -> DocumentType:
        return DocumentType.VPBANK_DEBIT_NOTE

    def post_process(self, ctx: ExtractionContext, fields: FieldSet) -> None:
        payment_detail = fields.get("payment_detail")
        fields.set(extract_card_last4(payment_detail))
        fields.set(
            extract_merchant_reference(
                payment_detail,
                self._config.merchant,
                reference_pattern=ctx.reference_pattern,
                strip_inner_whitespace=ctx.strip_inner_whitespace,
            )
        )
