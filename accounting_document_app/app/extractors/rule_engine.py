"""Bộ máy chạy luật trích xuất — biến ``FieldRule`` thành ``ExtractedField``.

Mọi giá trị trả về đều mang theo bằng chứng nguồn (trang, vị trí ký tự, đoạn
text gốc, id rule). Khi không đọc được, trường mang ``value=None`` kèm mã lỗi
— không bao giờ có giá trị bịa.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from app.config_loader import FieldRule
from app.core.pdf_reader import PDFContent
from app.core.text_normalizer import (
    flatten_whitespace,
    normalize_reference,
    normalize_tax_code,
)
from app.models.enums import DocumentType, FieldMethod
from app.models.extracted_field import ExtractedField
from app.utils import date_utils
from app.utils.money_utils import (
    AmountAmbiguousError,
    AmountParseError,
    MoneyFormat,
    parse_amount,
    parse_percent,
)

__all__ = ["ExtractionContext", "RuleEngine"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractionContext:
    """Mọi thứ một rule cần để chạy trên một chứng từ cụ thể."""

    content: PDFContent
    document_type: DocumentType
    money_format: MoneyFormat
    reference_pattern: str
    strip_inner_whitespace: bool = True


@dataclass(frozen=True)
class _RawMatch:
    """Một lần khớp thô, trước khi chuyển kiểu."""

    text: str
    snippet: str
    page_number: int | None
    span: tuple[int, int] | None


class RuleEngine:
    """Chạy các luật trích xuất trên nội dung một PDF."""

    def run(self, rule: FieldRule, ctx: ExtractionContext) -> ExtractedField:
        """Chạy một rule và trả về trường đã trích xuất.

        Args:
            rule: Luật cần chạy.
            ctx: Ngữ cảnh chứng từ đang xử lý.

        Returns:
            ``ExtractedField`` — luôn trả về một đối tượng, kể cả khi thất bại
            (khi đó ``value is None`` và ``error`` cho biết nguyên nhân).
        """
        try:
            matches = self._collect(rule, ctx)
        except Exception as exc:  # noqa: BLE001 - một rule hỏng không được làm sập cả file
            logger.exception("Rule %s lỗi khi chạy: %s", rule.rule_id, exc)
            return ExtractedField.missing(
                rule.field_name, rule_id=rule.rule_id, error="EXTRACT_FIELD_FAILED"
            )

        if not matches:
            return ExtractedField.missing(
                rule.field_name, rule_id=rule.rule_id, error="NOT_FOUND"
            )

        chosen = self._choose(rule, matches)
        if chosen is None:
            logger.warning(
                "Rule %s khớp %d giá trị khác nhau — không tự chọn",
                rule.rule_id,
                len({m.text for m in matches}),
            )
            return ExtractedField.missing(
                rule.field_name, rule_id=rule.rule_id, error="AMBIGUOUS_MATCH"
            )

        return self._convert(rule, ctx, chosen)

    # ------------------------------------------------------------ thu thập

    def _collect(self, rule: FieldRule, ctx: ExtractionContext) -> list[_RawMatch]:
        if rule.strategy == "label_right":
            return self._collect_label_right(rule, ctx)
        return self._collect_regex(rule, ctx)

    def _collect_regex(self, rule: FieldRule, ctx: ExtractionContext) -> list[_RawMatch]:
        """Quét từng trang trước để giữ được số trang, sau đó mới quét toàn file.

        Quét toàn file là phương án dự phòng cho giá trị bị PDF cắt ngang hai
        trang; khi đó không xác định được số trang nên để ``None``.
        """
        pattern = rule.compiled
        assert pattern is not None  # đã kiểm tra lúc nạp config

        matches: list[_RawMatch] = []
        for page in ctx.content.pages:
            haystack = (
                flatten_whitespace(page.text) if rule.strategy == "flat_regex" else page.text
            )
            matches.extend(self._scan(pattern, haystack, rule.group, page.number))

        if not matches:
            haystack = ctx.content.flat if rule.strategy == "flat_regex" else ctx.content.text
            matches.extend(self._scan(pattern, haystack, rule.group, None))
        return matches

    @staticmethod
    def _scan(pattern, haystack: str, group: int, page_number: int | None) -> list[_RawMatch]:
        found: list[_RawMatch] = []
        for match in pattern.finditer(haystack):
            try:
                text = match.group(group)
            except IndexError:  # pragma: no cover - group đã kiểm tra lúc nạp config
                continue
            if text is None:
                continue
            start = max(match.start() - 40, 0)
            end = min(match.end() + 40, len(haystack))
            found.append(
                _RawMatch(
                    text=text,
                    snippet=haystack[start:end].strip(),
                    page_number=page_number,
                    span=(match.start(group), match.end(group)),
                )
            )
        return found

    def _collect_label_right(self, rule: FieldRule, ctx: ExtractionContext) -> list[_RawMatch]:
        assert rule.label is not None
        found = ctx.content.find_label_right(rule.label)
        if found is None:
            return []
        raw_value, page_number = found

        value_pattern = rule.compiled_value
        if value_pattern is None:
            return [_RawMatch(text=raw_value.strip(), snippet=raw_value, page_number=page_number, span=None)]

        match = value_pattern.search(raw_value)
        if not match:
            logger.debug(
                "Rule %s: tìm thấy nhãn %r nhưng value_pattern không khớp %r",
                rule.rule_id,
                rule.label,
                raw_value,
            )
            return []
        try:
            text = match.group(rule.group)
        except IndexError:
            return []
        return [
            _RawMatch(
                text=text,
                snippet=f"{rule.label} {raw_value}".strip(),
                page_number=page_number,
                span=(match.start(rule.group), match.end(rule.group)),
            )
        ]

    # ------------------------------------------------------------- chọn lọc

    @staticmethod
    def _choose(rule: FieldRule, matches: list[_RawMatch]) -> _RawMatch | None:
        if rule.occurrence is not None:
            index = rule.occurrence - 1
            return matches[index] if 0 <= index < len(matches) else None

        distinct = {m.text for m in matches}
        if len(distinct) > 1 and rule.on_multiple == "ambiguous":
            return None
        return matches[-1] if rule.on_multiple == "last" else matches[0]

    # ----------------------------------------------------------- chuyển kiểu

    def _convert(
        self, rule: FieldRule, ctx: ExtractionContext, raw: _RawMatch
    ) -> ExtractedField:
        method = (
            FieldMethod.LABEL_RIGHT if rule.strategy == "label_right" else FieldMethod.REGEX
        )
        base = {
            "field_name": rule.field_name,
            "raw_snippet": raw.snippet,
            "page_number": raw.page_number,
            "char_span": raw.span,
            "rule_id": rule.rule_id,
            "method": method,
        }
        text = raw.text.strip()

        try:
            value = self._cast(rule, ctx, text)
        except _ConversionError as exc:
            logger.warning("Rule %s không chuyển được %r: %s", rule.rule_id, text, exc.code)
            return ExtractedField(**base, value=None, error=exc.code)

        error = None
        if rule.value_type == "reference":
            normalized = normalize_reference(
                text,
                pattern=ctx.reference_pattern,
                strip_inner_whitespace=ctx.strip_inner_whitespace,
            )
            value = normalized.value
            if not normalized.is_valid_format:
                error = "REFERENCE_INVALID_FORMAT"

        return ExtractedField(**base, value=value, error=error)

    @staticmethod
    def _cast(rule: FieldRule, ctx: ExtractionContext, text: str):
        kind = rule.value_type
        try:
            if kind in {"text", "reference"}:
                return text
            if kind == "tax_code":
                return normalize_tax_code(text)
            if kind == "money":
                return parse_amount(text, ctx.money_format)
            if kind == "percent":
                return parse_percent(text)
            if kind == "date_dmy":
                return date_utils.parse_dmy(text)
            if kind == "date_vi":
                return date_utils.parse_vietnamese_long_date(text)
            if kind == "date_compact":
                return date_utils.parse_compact_date(text)
        except AmountAmbiguousError as exc:
            raise _ConversionError(exc.code) from exc
        except AmountParseError as exc:
            raise _ConversionError(exc.code) from exc
        except date_utils.DateParseError as exc:
            raise _ConversionError(exc.code) from exc
        raise _ConversionError("UNSUPPORTED_TYPE")


class _ConversionError(Exception):
    """Lỗi chuyển kiểu, mang theo mã lỗi nghiệp vụ."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
