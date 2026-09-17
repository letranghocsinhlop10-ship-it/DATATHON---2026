"""Lớp cơ sở cho mọi extractor.

Extractor = chạy bộ rule của loại chứng từ + hậu xử lý riêng của loại đó.
Thêm ngân hàng hoặc nhà cung cấp mới: viết một lớp con, khai báo bộ rule
trong YAML, đăng ký vào registry. Không sửa code sẵn có.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from app.config_loader import ExtractionConfig
from app.extractors.rule_engine import ExtractionContext, RuleEngine
from app.models.enums import DocumentType
from app.models.extracted_field import ExtractedField, FieldSet

__all__ = ["BaseExtractor"]

logger = logging.getLogger(__name__)


class BaseExtractor(ABC):
    """Khung chung: chạy rule từ YAML rồi gọi hậu xử lý của lớp con.

    Args:
        config: Cấu hình trích xuất đã nạp.
        engine: Bộ máy chạy rule; truyền vào để test thay thế được.
    """

    def __init__(self, config: ExtractionConfig, engine: RuleEngine | None = None) -> None:
        self._config = config
        self._engine = engine or RuleEngine()

    @property
    @abstractmethod
    def document_type(self) -> DocumentType:
        """Loại chứng từ mà extractor này phụ trách."""

    def extract(self, ctx: ExtractionContext) -> FieldSet:
        """Trích xuất toàn bộ trường của một chứng từ.

        Args:
            ctx: Ngữ cảnh chứng từ (nội dung PDF + định dạng tiền + luật ref).

        Returns:
            ``FieldSet`` chứa mọi trường, kể cả trường không đọc được.
        """
        result = FieldSet()
        for rule in self._config.rules_for(self.document_type):
            extracted = self._engine.run(rule, ctx)
            result.set(extracted)
            if rule.required and not extracted.found:
                logger.warning(
                    "%s: thiếu trường bắt buộc %s (rule %s, lỗi %s)",
                    ctx.content.path.name,
                    rule.field_name,
                    rule.rule_id,
                    extracted.error,
                )
        self.post_process(ctx, result)
        return result

    def post_process(self, ctx: ExtractionContext, fields: FieldSet) -> None:
        """Hậu xử lý sau khi chạy hết rule. Mặc định không làm gì."""

    def missing_required(self, fields: FieldSet) -> tuple[str, ...]:
        """Danh sách trường bắt buộc chưa đọc được."""
        return tuple(
            rule.field_name
            for rule in self._config.rules_for(self.document_type)
            if rule.required and not fields.get(rule.field_name).found
        )

    @staticmethod
    def _derive(
        field_name: str,
        value,
        *,
        source: ExtractedField,
        error: str | None = None,
    ) -> ExtractedField:
        """Tạo trường suy ra từ một trường khác, giữ nguyên bằng chứng nguồn."""
        from app.models.enums import FieldMethod

        return ExtractedField(
            field_name=field_name,
            value=value,
            raw_snippet=source.raw_snippet,
            page_number=source.page_number,
            rule_id=source.rule_id,
            method=FieldMethod.DERIVED,
            error=error,
        )
