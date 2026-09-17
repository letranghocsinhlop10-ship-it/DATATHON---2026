"""Bóc reference của nhà cung cấp ra khỏi phần diễn giải của chứng từ ngân hàng.

Diễn giải thật trên chứng từ VPBank::

    So the 1111xxxx1234 GD thanh toan tai FACEBK <REFERENCE> DUBLIN IE

Hai điều bắt buộc, rút ra từ file mẫu:

1. Regex CHỈ được neo vào từ khoá nhà cung cấp (``FACEBK``). Không được neo
   vào cụm ``GD thanh toan tai`` vì hai chứng từ trong cùng một bộ viết khác
   nhau (``thanh toan tai`` và ``thanh toantai`` — dính liền, thiếu dấu cách).
2. Không được neo vào đuôi phía sau reference. Đuôi được khai báo trong
   config như một KỲ VỌNG ĐƯỢC KIỂM TRA: lệch thì gắn cảnh báo
   ``UNEXPECTED_MERCHANT_SUFFIX``, KHÔNG làm hỏng việc trích xuất.

Tuyệt đối không lấy nhầm mã giao dịch VPBank, số tài khoản, số thẻ hay số
tiền làm reference của nhà cung cấp.
"""

from __future__ import annotations

import logging
import re

from app.config_loader import MerchantConfig
from app.core.text_normalizer import flatten_whitespace, normalize_reference
from app.models.enums import FieldMethod
from app.models.extracted_field import ExtractedField

__all__ = ["CARD_LAST4_PATTERN", "extract_card_last4", "extract_merchant_reference"]

logger = logging.getLogger(__name__)

#: ``So the 1111xxxx1234`` -> bốn số cuối của thẻ.
CARD_LAST4_PATTERN = re.compile(r"\bSo\s+the\s+\d{4}[xX*]{4}(\d{4})\b")


def extract_card_last4(payment_detail: ExtractedField) -> ExtractedField:
    """Lấy 4 số cuối thẻ từ phần diễn giải.

    Args:
        payment_detail: Trường diễn giải đã trích xuất.

    Returns:
        ``ExtractedField`` chứa 4 chữ số, hoặc trường rỗng nếu không có.
    """
    if not payment_detail.found:
        return ExtractedField.missing(
            "card_last4", rule_id=payment_detail.rule_id, error="NO_PAYMENT_DETAIL"
        )

    text = flatten_whitespace(str(payment_detail.value))
    match = CARD_LAST4_PATTERN.search(text)
    if not match:
        return ExtractedField.missing(
            "card_last4", rule_id=payment_detail.rule_id, error="NOT_FOUND"
        )

    return ExtractedField(
        field_name="card_last4",
        value=match.group(1),
        raw_snippet=text,
        page_number=payment_detail.page_number,
        char_span=(match.start(1), match.end(1)),
        rule_id=payment_detail.rule_id,
        method=FieldMethod.DERIVED,
    )


def extract_merchant_reference(
    payment_detail: ExtractedField,
    merchant: MerchantConfig,
    *,
    reference_pattern: str,
    strip_inner_whitespace: bool = True,
) -> ExtractedField:
    """Lấy reference của nhà cung cấp đứng ngay sau từ khoá neo.

    Args:
        payment_detail: Trường diễn giải / nội dung thanh toán.
        merchant: Cấu hình từ khoá neo và đuôi kỳ vọng.
        reference_pattern: Pattern kiểm tra định dạng reference.
        strip_inner_whitespace: Truyền xuống ``normalize_reference``.

    Returns:
        ``ExtractedField`` chứa reference ĐÃ chuẩn hoá. Khi tìm thấy nhiều
        giá trị khác nhau, trả về trường rỗng với lỗi ``AMBIGUOUS_MATCH`` —
        hệ thống không tự chọn.
    """
    if not payment_detail.found:
        return ExtractedField.missing(
            "meta_reference", rule_id=payment_detail.rule_id, error="NO_PAYMENT_DETAIL"
        )

    text = flatten_whitespace(str(payment_detail.value))
    anchors = "|".join(re.escape(a) for a in merchant.anchors)
    pattern = re.compile(rf"\b(?:{anchors})\s+([A-Za-z0-9]{{6,24}})\b")

    matches = list(pattern.finditer(text))
    if not matches:
        logger.debug("Không thấy từ khoá nhà cung cấp %s trong: %r", merchant.anchors, text)
        return ExtractedField.missing(
            "meta_reference", rule_id=payment_detail.rule_id, error="MERCHANT_ANCHOR_NOT_FOUND"
        )

    normalized = {
        normalize_reference(
            m.group(1),
            pattern=reference_pattern,
            strip_inner_whitespace=strip_inner_whitespace,
        ).value
        for m in matches
    }
    if len(normalized) > 1:
        logger.warning("Diễn giải chứa %d reference khác nhau: %s", len(normalized), normalized)
        return ExtractedField.missing(
            "meta_reference", rule_id=payment_detail.rule_id, error="AMBIGUOUS_MATCH"
        )

    match = matches[0]
    result = normalize_reference(
        match.group(1),
        pattern=reference_pattern,
        strip_inner_whitespace=strip_inner_whitespace,
    )

    error: str | None = None
    if not result.is_valid_format:
        error = "REFERENCE_INVALID_FORMAT"
    elif merchant.expected_suffix:
        tail = text[match.end(1) :].strip()
        if not tail.upper().startswith(merchant.expected_suffix.upper()):
            # Chỉ cảnh báo. Giá trị reference VẪN được giữ nguyên.
            logger.info(
                "Đuôi diễn giải khác kỳ vọng %r: %r", merchant.expected_suffix, tail[:40]
            )
            error = "UNEXPECTED_MERCHANT_SUFFIX"

    return ExtractedField(
        field_name="meta_reference",
        value=result.value,
        raw_snippet=text,
        page_number=payment_detail.page_number,
        char_span=(match.start(1), match.end(1)),
        rule_id=payment_detail.rule_id,
        method=FieldMethod.DERIVED,
        error=error,
    )
