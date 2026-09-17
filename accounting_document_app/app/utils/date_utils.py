"""Đọc ngày tháng từ các định dạng xuất hiện trên chứng từ thật.

Ba loại chứng từ dùng ba cách ghi ngày khác nhau::

    Hoá đơn Meta       "15:10 1 tháng 8, 2026"   tiếng Việt, dạng chữ
    Debit Note         "01/08/2026"              dd/mm/yyyy
    Hoá đơn GTGT       "01/08/2026"              dd/mm/yyyy
    Reference VPBank   "..._20260801"            yyyymmdd nén
"""

from __future__ import annotations

import re
from datetime import date

__all__ = [
    "DateParseError",
    "parse_dmy",
    "parse_vietnamese_long_date",
    "parse_compact_date",
    "format_display",
]


class DateParseError(ValueError):
    """Không đọc được ngày từ chuỗi đã cho."""

    code = "DATE_PARSE_FAILED"


_DMY_RE = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b")
_VI_LONG_RE = re.compile(r"\b(\d{1,2})\s*tháng\s*(\d{1,2})\s*,?\s*(\d{4})\b", re.IGNORECASE)
# Lookaround thay cho \b: dấu gạch dưới là ký tự word nên \b không khớp
# ở ranh giới "FT...._20260801".
_COMPACT_RE = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)")


def _build(year: int, month: int, day: int, raw: str) -> date:
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise DateParseError(f"Ngày không hợp lệ: {raw!r}") from exc


def parse_dmy(raw: str | None) -> date:
    """Đọc ngày dạng ``dd/mm/yyyy`` (hoặc ``dd-mm-yyyy``, ``dd.mm.yyyy``).

    Args:
        raw: Chuỗi có chứa ngày.

    Returns:
        Đối tượng ``date``.

    Raises:
        DateParseError: Không tìm thấy hoặc ngày không hợp lệ.

    Examples:
        >>> parse_dmy("Ngày/Transaction Date: 01/08/2026")
        datetime.date(2026, 8, 1)
    """
    if raw is None:
        raise DateParseError("Chuỗi ngày rỗng")
    match = _DMY_RE.search(raw)
    if not match:
        raise DateParseError(f"Không tìm thấy ngày dd/mm/yyyy trong: {raw!r}")
    day, month, year = (int(g) for g in match.groups())
    return _build(year, month, day, raw)


def parse_vietnamese_long_date(raw: str | None) -> date:
    """Đọc ngày tiếng Việt dạng chữ, ví dụ ``"15:10 1 tháng 8, 2026"``.

    Phần giờ phút (nếu có) được bỏ qua — hệ thống chỉ hạch toán theo ngày.

    Args:
        raw: Chuỗi có chứa ngày dạng ``<ngày> tháng <tháng>, <năm>``.

    Returns:
        Đối tượng ``date``.

    Raises:
        DateParseError: Không tìm thấy hoặc ngày không hợp lệ.

    Examples:
        >>> parse_vietnamese_long_date("15:10 1 tháng 8, 2026")
        datetime.date(2026, 8, 1)
    """
    if raw is None:
        raise DateParseError("Chuỗi ngày rỗng")
    match = _VI_LONG_RE.search(raw)
    if not match:
        raise DateParseError(f"Không tìm thấy ngày tiếng Việt trong: {raw!r}")
    day, month, year = (int(g) for g in match.groups())
    return _build(year, month, day, raw)


def parse_compact_date(raw: str | None) -> date:
    """Đọc ngày dạng nén ``yyyymmdd`` — dùng cho hậu tố reference của VPBank.

    Args:
        raw: Chuỗi chứa 8 chữ số liền nhau.

    Returns:
        Đối tượng ``date``.

    Raises:
        DateParseError: Không tìm thấy hoặc ngày không hợp lệ.

    Examples:
        >>> parse_compact_date("FT26000000000001_20260801")
        datetime.date(2026, 8, 1)
    """
    if raw is None:
        raise DateParseError("Chuỗi ngày rỗng")
    match = _COMPACT_RE.search(raw)
    if not match:
        raise DateParseError(f"Không tìm thấy ngày yyyymmdd trong: {raw!r}")
    year, month, day = (int(g) for g in match.groups())
    return _build(year, month, day, raw)


def format_display(value: date | None) -> str:
    """Định dạng ngày để hiển thị cho kế toán (``dd/mm/yyyy``)."""
    return value.strftime("%d/%m/%Y") if value else ""
