"""Tiện ích chuỗi dùng chung cho hiển thị."""

from __future__ import annotations

import re

__all__ = ["truncate", "collapse_spaces", "mask_digits"]


def truncate(text: str | None, limit: int = 60, suffix: str = "…") -> str:
    """Cắt ngắn chuỗi để hiển thị trên bảng."""
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - len(suffix)] + suffix


def collapse_spaces(text: str | None) -> str:
    """Gộp khoảng trắng liên tiếp thành một dấu cách."""
    return re.sub(r"\s+", " ", text).strip() if text else ""


def mask_digits(text: str | None, keep_last: int = 4) -> str:
    """Che chữ số, chỉ giữ ``keep_last`` số cuối — dùng khi ghi log.

    Examples:
        >>> mask_digits("600000001")
        '*****0001'
    """
    if not text:
        return ""
    digits = [c for c in text if c.isdigit()]
    if len(digits) <= keep_last:
        return text
    cut = len(digits) - keep_last
    seen = 0
    out = []
    for char in text:
        if char.isdigit() and seen < cut:
            out.append("*")
            seen += 1
        else:
            out.append(char)
    return "".join(out)
