"""Trích xuất hoá đơn quảng cáo Meta / Facebook Ads.

Trường quan trọng nhất là ``reference_number`` — ``Số tham chiếu`` in trên
hoá đơn. Đây là khoá gốc để ghép cả bộ hồ sơ.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from app.extractors.base_extractor import BaseExtractor
from app.extractors.rule_engine import ExtractionContext
from app.models.enums import DocumentType
from app.models.extracted_field import FieldSet

__all__ = ["MetaInvoiceExtractor"]

logger = logging.getLogger(__name__)


class MetaInvoiceExtractor(BaseExtractor):
    """Extractor cho ``META_INVOICE``."""

    @property
    def document_type(self) -> DocumentType:
        return DocumentType.META_INVOICE

    def post_process(self, ctx: ExtractionContext, fields: FieldSet) -> None:
        """Kiểm tra chéo số học trong nội bộ hoá đơn.

        Không sửa số liệu — chỉ gắn mã cảnh báo để người dùng đối chiếu.
        """
        subtotal = fields.value("subtotal")
        vat_amount = fields.value("vat_amount")
        total = fields.value("total_amount")

        if isinstance(subtotal, Decimal) and isinstance(total, Decimal):
            vat = vat_amount if isinstance(vat_amount, Decimal) else Decimal(0)
            if subtotal + vat != total:
                logger.warning(
                    "%s: tổng phụ + VAT (%s) khác tổng tiền (%s)",
                    ctx.content.path.name,
                    subtotal + vat,
                    total,
                )
                fields.set(
                    self._derive(
                        "vat_math_check",
                        False,
                        source=fields.get("total_amount"),
                        error="VAT_MATH_ERROR",
                    )
                )
            else:
                fields.set(
                    self._derive("vat_math_check", True, source=fields.get("total_amount"))
                )
