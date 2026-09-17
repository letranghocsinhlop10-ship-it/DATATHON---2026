"""Dựng bố cục hoá đơn GTGT VPBank để test chiến lược ``label_right``.

Fixture này TÁI TẠO đặc điểm nguy hiểm nhất của file thật: giá trị được VẼ
TRƯỚC nhãn trong luồng text, nhưng trên giấy thì nhãn nằm bên trái và giá trị
nằm bên phải. Nhờ dựng bằng toạ độ, test chạy được mà không cần PDF thật và
không chứa số liệu kế toán thật.
"""

from __future__ import annotations

from app.core.layout import Rect, Word
from app.core.pdf_reader import PageContent

#: (nhãn, giá trị, y). Nhãn ở x=33, giá trị ở x=162 — giống file thật.
ROWS: list[tuple[str, str, float]] = [
    ("Ký hiệu (Serial):", "1K26XXX", 38.9),
    ("Số (No.):", "00100001", 54.9),
    ("Ngày hóa đơn (Date):", "01/08/2026", 70.9),
    ("Đơn vị bán hàng (Seller):", "Ngân hàng TMCP Việt Nam Thịnh Vượng", 190.9),
    ("MST (Tax code):", "0100000002", 228.9),
    ("Tên khách hàng (Customer):", "CONG TY CO PHAN ABC XYZ", 277.9),
    ("Mã khách hàng (CIF):", "20000001", 296.9),
    ("Mã số thuế (Tax code):", "0100000001", 315.9),
    ("Số tham chiếu (Reference):", "FT26000000000001_20260801", 372.9),
    ("Cộng tiền hàng (Subtotal):", "20.000", 466.4),
    ("Tổng cộng tiền thanh toán (Total):", "22.000", 508.4),
    (
        "Nội dung thanh toán (Payment detail):",
        "So the 1111xxxx1234 GD thanh toantai FACEBK ABCD1234EF DUBLIN IE",
        550.4,
    ),
]

#: Dòng có HAI cặp nhãn/giá trị — bẫy khiến label_right lấy dư nếu thiếu
#: value_pattern giới hạn.
DOUBLE_ROW = (
    ("Thuế suất (Tax rate):", "10%", 33.0),
    ("Tiền thuế GTGT (Value added tax):", "2.000", 300.0),
    487.4,
)

_CHAR_WIDTH = 5.0
_LINE_HEIGHT = 11.0


def _lay_out(text: str, x_start: float, y: float) -> tuple[list[Word], Rect]:
    """Rải từng từ của một chuỗi theo chiều ngang, trả về từ và ô bao."""
    words: list[Word] = []
    cursor = x_start
    for token in text.split():
        width = len(token) * _CHAR_WIDTH
        words.append(Word(token, Rect(cursor, y, cursor + width, y + _LINE_HEIGHT)))
        cursor += width + _CHAR_WIDTH
    span = Rect(x_start, y, cursor - _CHAR_WIDTH, y + _LINE_HEIGHT)
    return words, span


def build_vat_page() -> PageContent:
    """Dựng một trang hoá đơn GTGT giả lập kèm toạ độ nhãn."""
    words: list[Word] = []
    label_rects: dict[str, list[Rect]] = {}
    draw_order: list[str] = []

    def add_pair(label: str, value: str, y: float, label_x: float) -> None:
        label_words, label_span = _lay_out(label, label_x, y)
        value_x = label_span.x1 + 2 * _CHAR_WIDTH
        value_words, _ = _lay_out(value, value_x, y)
        words.extend(label_words + value_words)
        label_rects.setdefault(label, []).append(label_span)
        # Đăng ký thêm biến thể nhãn ngắn (chỉ phần tiếng Việt), vì trên file
        # thật nhãn bị xuống dòng và search_for khớp phần tiếng Việt trước.
        short = label.split("(")[0].strip()
        if short and short != label:
            short_words, _ = _lay_out(short, label_x, y)
            short_span = Rect(
                label_x, y, label_x + sum(len(w.text) + 1 for w in short_words) * _CHAR_WIDTH, y + _LINE_HEIGHT
            )
            label_rects.setdefault(short, []).append(short_span)
        # Thứ tự VẼ đảo ngược: giá trị trước, nhãn sau.
        draw_order.append(value)
        draw_order.append(label)

    for label, value, y in ROWS:
        add_pair(label, value, y, 33.0)

    (l1, v1, x1), (l2, v2, x2), y_double = DOUBLE_ROW
    add_pair(l1, v1, y_double, x1)
    add_pair(l2, v2, y_double, x2)

    text = "\n".join(draw_order)
    return PageContent(number=1, text=text, words=words, label_rects=label_rects)
