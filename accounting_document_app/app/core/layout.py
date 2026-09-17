"""Trích xuất theo TOẠ ĐỘ — dành cho chứng từ có thứ tự text bị đảo.

VÌ SAO CẦN: trên hoá đơn GTGT của VPBank, PyMuPDF trả về text theo thứ tự
VẼ chứ không theo thứ tự ĐỌC, và thứ tự vẽ lại không nhất quán::

    text thô trả về:          bố cục thật trên giấy:
        00100001                  Ký hiệu (Serial):  1K26XXX
        1K26XXX                   Số (No.):          00100001
        Ký hiệu (Serial):         Ngày hóa đơn:      01/08/2026
        Số (No.):

Regex tuyến tính kiểu ``Số tham chiếu \\(Reference\\):\\s*(\\S+)`` sẽ lấy SAI
giá trị trên loại file này. Giải pháp: tìm ô chữ của NHÃN, rồi lấy các từ
nằm CÙNG DÒNG và BÊN PHẢI nhãn đó.

Module này thuần Python, không phụ thuộc PyMuPDF, nên test được bằng các ô
chữ dựng tay — không cần file PDF thật.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Sequence

__all__ = ["Rect", "Word", "label_right", "reading_order_text"]


@dataclass(frozen=True)
class Rect:
    """Hình chữ nhật bao quanh một đoạn chữ, theo hệ toạ độ PDF (gốc trên-trái)."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def y_center(self) -> float:
        return (self.y0 + self.y1) / 2.0


@dataclass(frozen=True)
class Word:
    """Một từ trên trang PDF kèm ô chữ bao quanh."""

    text: str
    rect: Rect

    @property
    def y_center(self) -> float:
        return self.rect.y_center


def label_right(
    words: Sequence[Word],
    label_rects: Sequence[Rect],
    *,
    y_tolerance: float = 4.0,
    x_gap: float = 0.0,
) -> tuple[str, Rect] | None:
    """Lấy phần chữ nằm cùng dòng và bên phải của một nhãn.

    Args:
        words: Toàn bộ từ trên trang.
        label_rects: Các ô chữ tìm được của nhãn (thường từ ``page.search_for``).
            Chỉ ô đầu tiên được dùng.
        y_tolerance: Sai số cho phép giữa tâm dòng của từ và tâm dòng của nhãn.
        x_gap: Khoảng lùi cho phép về bên trái nhãn, dùng khi nhãn bị tách ô.

    Returns:
        Cặp ``(chuỗi giá trị, ô chữ của nhãn)``, hoặc ``None`` nếu không tìm
        thấy nhãn hoặc bên phải nhãn không còn chữ nào.

    Examples:
        >>> label = Rect(33, 370, 160, 382)
        >>> ws = [Word("Số", Rect(33, 370, 50, 382)),
        ...       Word("tham", Rect(52, 370, 90, 382)),
        ...       Word("chiếu", Rect(92, 370, 160, 382)),
        ...       Word("FT123_20260801", Rect(162, 370, 300, 382))]
        >>> label_right(ws, [label])[0]
        'FT123_20260801'
    """
    if not label_rects:
        return None

    anchor = label_rects[0]
    center = anchor.y_center
    selected = [
        w
        for w in words
        if w.rect.x0 >= anchor.x1 - x_gap and abs(w.y_center - center) <= y_tolerance
    ]
    if not selected:
        return None

    selected.sort(key=lambda w: w.rect.x0)
    return " ".join(w.text for w in selected), anchor


def reading_order_text(words: Iterable[Word], *, y_tolerance: float = 3.0) -> str:
    """Dựng lại text theo thứ tự đọc thật: gom theo dòng, sắp trong dòng theo x.

    CẢNH BÁO: chỉ dùng cho chứng từ MỘT CỘT. Với chứng từ hai cột (debit note,
    hoá đơn Meta) hàm này sẽ GỘP NHẦM hai cột vào một dòng, ví dụ::

        "Tên Khách hàng: CONG TY CO    Tên Ngân hàng: VPBANK"

    Với các chứng từ đó phải dùng ``PDFReader.text`` (thứ tự block) thay thế.

    Args:
        words: Các từ trên trang.
        y_tolerance: Độ cao gom nhóm dòng, tính bằng point.

    Returns:
        Text nhiều dòng theo thứ tự đọc.
    """
    rows: dict[int, list[Word]] = defaultdict(list)
    for w in words:
        rows[round(w.rect.y0 / y_tolerance)].append(w)
    lines = []
    for key in sorted(rows):
        line = sorted(rows[key], key=lambda w: w.rect.x0)
        lines.append(" ".join(w.text for w in line))
    return "\n".join(lines)
