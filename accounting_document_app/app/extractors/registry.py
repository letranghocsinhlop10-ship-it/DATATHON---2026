"""Sổ đăng ký extractor — nơi duy nhất ánh xạ loại chứng từ sang extractor.

Thêm nhà cung cấp hoặc ngân hàng mới: viết lớp extractor, đăng ký ở đây,
khai báo rule trong YAML. Không phải sửa bất kỳ chỗ nào khác.
"""

from __future__ import annotations

import logging

from app.config_loader import ExtractionConfig
from app.extractors.base_extractor import BaseExtractor
from app.extractors.meta_invoice_extractor import MetaInvoiceExtractor
from app.extractors.vpbank_debit_extractor import VPBankDebitNoteExtractor
from app.extractors.vpbank_vat_extractor import VPBankVatInvoiceExtractor
from app.models.enums import DocumentType

__all__ = ["ExtractorRegistry"]

logger = logging.getLogger(__name__)


class ExtractorRegistry:
    """Ánh xạ ``DocumentType`` -> extractor tương ứng."""

    def __init__(self, config: ExtractionConfig) -> None:
        self._extractors: dict[DocumentType, BaseExtractor] = {}
        for extractor_cls in (
            MetaInvoiceExtractor,
            VPBankDebitNoteExtractor,
            VPBankVatInvoiceExtractor,
        ):
            extractor = extractor_cls(config)
            self._extractors[extractor.document_type] = extractor

    def get(self, document_type: DocumentType) -> BaseExtractor | None:
        """Lấy extractor cho một loại chứng từ, ``None`` nếu chưa hỗ trợ."""
        extractor = self._extractors.get(document_type)
        if extractor is None:
            logger.debug("Chưa có extractor cho loại %s", document_type.value)
        return extractor

    def register(self, extractor: BaseExtractor) -> None:
        """Đăng ký thêm extractor (dùng cho plug-in hoặc test)."""
        self._extractors[extractor.document_type] = extractor

    @property
    def supported_types(self) -> tuple[DocumentType, ...]:
        return tuple(self._extractors)
