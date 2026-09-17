"""Trích xuất hoá đơn GTGT phí dịch vụ của VPBank.

Chứng từ này có hai khoá liên kết, cả hai đều được trích xuất:

* ``meta_reference``  — reference nhà cung cấp nằm trong *Nội dung thanh toán*.
  Đây là KHOÁ CHÍNH theo xác nhận nghiệp vụ.
* ``bank_transaction_code`` — suy ra từ trường *Số tham chiếu (Reference)* của
  chính hoá đơn, có dạng ``<Mã giao dịch>_<YYYYMMDD>``. Dùng làm KIỂM TRA CHÉO
  với ``transaction_code`` trên debit note.
"""

from __future__ import annotations

import logging
import re

from app.extractors.base_extractor import BaseExtractor
from app.extractors.merchant_reference import (
    extract_card_last4,
    extract_merchant_reference,
)
from app.extractors.rule_engine import ExtractionContext
from app.models.enums import DocumentType
from app.models.extracted_field import FieldSet
from app.utils import date_utils

__all__ = ["VPBankVatInvoiceExtractor", "BANK_REFERENCE_PATTERN"]

logger = logging.getLogger(__name__)

#: ``FT26000000000001_20260801`` -> (mã giao dịch, ngày).
BANK_REFERENCE_PATTERN = re.compile(r"^([A-Za-z0-9]{6,32})_(\d{8})$")


class VPBankVatInvoiceExtractor(BaseExtractor):
    """Extractor cho ``VPBANK_VAT_INVOICE``."""

    @property
    def document_type(self) -> DocumentType:
        return DocumentType.VPBANK_VAT_INVOICE

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
        self._split_bank_reference(fields)

    def _split_bank_reference(self, fields: FieldSet) -> None:
        """Tách ``<Mã giao dịch>_<YYYYMMDD>`` thành hai trường kiểm tra chéo.

        Việc tách chỉ là cắt chuỗi theo dấu ``_`` cố định — không phải fuzzy
        match. Nếu định dạng khác kỳ vọng, hai trường suy ra để rỗng kèm mã
        lỗi, còn giá trị gốc vẫn được giữ nguyên.
        """
        source = fields.get("reference_number")
        if not source.found:
            return

        match = BANK_REFERENCE_PATTERN.match(str(source.value).strip())
        if not match:
            logger.info(
                "Số tham chiếu ngân hàng không theo dạng <mã GD>_<yyyymmdd>: %r", source.value
            )
            fields.set(
                self._derive(
                    "bank_transaction_code",
                    None,
                    source=source,
                    error="BANK_REFERENCE_FORMAT_UNEXPECTED",
                )
            )
            return

        fields.set(self._derive("bank_transaction_code", match.group(1), source=source))
        try:
            fields.set(
                self._derive("bank_reference_date", date_utils.parse_compact_date(match.group(2)), source=source)
            )
        except date_utils.DateParseError:
            fields.set(
                self._derive(
                    "bank_reference_date", None, source=source, error="DATE_PARSE_FAILED"
                )
            )
