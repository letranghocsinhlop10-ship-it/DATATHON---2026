"""Sinh PDF tổng hợp có chữ tiếng Việt cho test cần file PDF THẬT trên đĩa.

Dùng khi test cần kiểm tra hành vi mức FILE (copy trang vật lý, đọc lại từ
đĩa...) — nếu chỉ cần test logic classify/extract thì dùng
``tests/helpers.py:make_content`` (dựng ``PDFContent`` trực tiếp từ text,
không cần PDF thật, nhanh hơn nhiều).

PyMuPDF ``insert_text`` mặc định dùng font Base14 (Helvetica) — KHÔNG có
glyph tiếng Việt có dấu, ký tự có dấu bị thay bằng ``·`` và làm hỏng mọi
regex trích xuất khi đọc lại. Bắt buộc chỉ định ``fontfile=DejaVu Sans``.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
)
FONT = next((p for p in _FONT_CANDIDATES if Path(p).is_file()), None)


def write_pdf(path: Path, pages: list[list[str]], *, size: float = 10, width: float = 1600) -> None:
    """Ghi một PDF nhiều trang, mỗi trang là danh sách dòng text.

    Args:
        path: Nơi ghi file.
        pages: Danh sách trang; mỗi trang là danh sách dòng (không xuống dòng
            trong một chuỗi — PyMuPDF ``insert_text`` không tự ngắt dòng và
            KHÔNG tự xuống dòng khi chạy quá lề phải — chữ nằm ngoài
            ``mediabox`` bị PyMuPDF loại khỏi ``get_text()``). Trang được
            tạo RỘNG (mặc định 1600pt, ~A4 x2.7) để chứa được một dòng dài
            kiểu sao kê ngân hàng nhiều cột mà không bị cắt mất cột cuối.
        size: Cỡ chữ.
        width: Chiều rộng trang (point) — nới ra nếu dòng dài hơn nữa.
    """
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page(width=width, height=842)
        y = 72
        for line in lines:
            page.insert_text((72, y), line, fontsize=size, fontname="dejavu", fontfile=FONT)
            y += 16
    doc.save(path)
    doc.close()
