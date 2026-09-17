"""Phân tích chuỗi tiền tệ thành ``Decimal`` — tuyệt đối không dùng ``float``.

BỐI CẢNH: ba loại chứng từ trong cùng một bộ dùng DẤU PHÂN CÁCH KHÁC NHAU::

    Hoá đơn Meta       1.100.000 ₫      dấu chấm  = phân cách nghìn
    Debit Note         1,122,000 VND    dấu phẩy  = phân cách nghìn
    Hoá đơn GTGT       20.000           dấu chấm  = phân cách nghìn

Nếu để hàm tự đoán, chuỗi ``2.000`` có thể bị hiểu thành hai phẩy không —
sai 1000 lần trong sổ kế toán. Vì vậy mỗi loại chứng từ PHẢI khai báo cứng
định dạng của mình trong config, và hàm này TỪ CHỐI đoán khi gặp trường hợp
nhập nhằng.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

__all__ = [
    "MoneyFormat",
    "AmountParseError",
    "AmountAmbiguousError",
    "parse_amount",
    "parse_percent",
    "format_vnd",
]


class AmountParseError(ValueError):
    """Chuỗi không phải là số tiền hợp lệ theo định dạng đã khai báo."""

    code = "AMOUNT_PARSE_FAILED"


class AmountAmbiguousError(AmountParseError):
    """Chuỗi có thể hiểu theo hai cách — hàm từ chối đoán."""

    code = "AMOUNT_PARSE_AMBIGUOUS"


@dataclass(frozen=True)
class MoneyFormat:
    """Định dạng số tiền của một loại chứng từ.

    Attributes:
        thousands: Ký tự phân cách hàng nghìn (``"."`` hoặc ``","``).
        decimal: Ký tự phân cách thập phân.
        currency_symbols: Các ký hiệu tiền tệ cần bóc bỏ trước khi parse.
    """

    thousands: str
    decimal: str
    currency_symbols: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.thousands == self.decimal:
            raise ValueError(
                "thousands và decimal không được trùng nhau: "
                f"{self.thousands!r}"
            )


def parse_amount(raw: str | None, fmt: MoneyFormat) -> Decimal:
    """Chuyển chuỗi tiền tệ thành ``Decimal`` theo định dạng đã khai báo.

    Args:
        raw: Chuỗi thô, ví dụ ``"1.100.000 ₫"`` hoặc ``"1,122,000 VND"``.
        fmt: Định dạng của loại chứng từ đang xử lý.

    Returns:
        Số tiền dạng ``Decimal``, giữ nguyên độ chính xác.

    Raises:
        AmountParseError: Chuỗi rỗng hoặc không phải số hợp lệ.
        AmountAmbiguousError: Chuỗi có đúng một dấu phân cách thập phân theo
            config nhưng theo sau là đúng 3 chữ số — không phân biệt được với
            cách viết phân cách hàng nghìn. Hàm từ chối đoán.

    Examples:
        >>> vn = MoneyFormat(thousands=".", decimal=",", currency_symbols=("₫", "VND"))
        >>> parse_amount("1.100.000 ₫", vn)
        Decimal('1100000')
        >>> en = MoneyFormat(thousands=",", decimal=".", currency_symbols=("VND",))
        >>> parse_amount("1,122,000 VND", en)
        Decimal('1122000')
    """
    if raw is None:
        raise AmountParseError("Chuỗi tiền tệ rỗng")

    text = raw.strip()
    for symbol in fmt.currency_symbols:
        text = text.replace(symbol, "")
    text = text.replace(" ", " ")
    text = re.sub(r"[\s]", "", text)
    text = text.strip()

    if not text:
        raise AmountParseError(f"Chuỗi tiền tệ rỗng sau khi bóc ký hiệu: {raw!r}")

    negative = text.startswith("-")
    if negative:
        text = text[1:]

    if not re.fullmatch(r"[0-9%s%s]+" % (re.escape(fmt.thousands), re.escape(fmt.decimal)), text):
        raise AmountParseError(f"Chuỗi chứa ký tự không hợp lệ: {raw!r}")

    # Bẫy nhập nhằng: đúng một dấu thập phân, theo sau là đúng 3 chữ số,
    # và không có dấu phân cách nghìn nào -> không thể phân biệt
    # "hai nghìn" với "hai phẩy không không không".
    if (
        text.count(fmt.decimal) == 1
        and fmt.thousands not in text
        and re.fullmatch(r"\d+%s\d{3}" % re.escape(fmt.decimal), text)
    ):
        raise AmountAmbiguousError(
            f"Không phân biệt được phân cách nghìn hay thập phân: {raw!r}. "
            "Kiểm tra lại money_format của loại chứng từ này."
        )

    if text.count(fmt.decimal) > 1:
        raise AmountParseError(f"Nhiều hơn một dấu thập phân: {raw!r}")

    integer_part, _, decimal_part = text.partition(fmt.decimal)
    groups = integer_part.split(fmt.thousands)
    if len(groups) > 1:
        # Nhóm đầu 1..3 chữ số, các nhóm sau bắt buộc đúng 3 chữ số.
        if not groups[0] or len(groups[0]) > 3 or not all(len(g) == 3 for g in groups[1:]):
            raise AmountParseError(f"Phân nhóm hàng nghìn không hợp lệ: {raw!r}")
    digits = "".join(groups)
    if not digits.isdigit():
        raise AmountParseError(f"Phần nguyên không hợp lệ: {raw!r}")

    if decimal_part and not decimal_part.isdigit():
        raise AmountParseError(f"Phần thập phân không hợp lệ: {raw!r}")

    try:
        value = Decimal(digits + ("." + decimal_part if decimal_part else ""))
    except InvalidOperation as exc:  # pragma: no cover - đã chặn ở trên
        raise AmountParseError(f"Không chuyển được sang Decimal: {raw!r}") from exc

    return -value if negative else value


def parse_percent(raw: str | None) -> Decimal:
    """Đọc thuế suất dạng ``"10%"`` hoặc ``"10"`` thành ``Decimal("10")``.

    Args:
        raw: Chuỗi thuế suất.

    Returns:
        Thuế suất theo đơn vị phần trăm (10% -> ``Decimal("10")``).

    Raises:
        AmountParseError: Không đọc được.
    """
    if raw is None:
        raise AmountParseError("Thuế suất rỗng")
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*%?", raw.strip())
    if not match:
        raise AmountParseError(f"Không đọc được thuế suất: {raw!r}")
    return Decimal(match.group(1).replace(",", "."))


def format_vnd(value: Decimal | None) -> str:
    """Định dạng số tiền để hiển thị trên giao diện (phân cách nghìn bằng dấu chấm)."""
    if value is None:
        return ""
    quantized = value.quantize(Decimal("1")) if value == value.to_integral_value() else value
    return f"{quantized:,}".replace(",", ".")
