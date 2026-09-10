"""OCR fallback stage.

Only invoked for pages the reader flagged as having no usable text layer
(scanned/photographed documents). Renders the page to an image with
PyMuPDF (no Poppler dependency) and feeds it to pytesseract.

Designed to fail soft: if Tesseract isn't installed on the machine, we
log a warning once and return None instead of crashing the whole job —
the caller marks the page/document with a warning so a human can review
it, per the "no crash on one bad file" requirement.
"""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

from app.core.logging_config import get_logger

log = get_logger("pdf.ocr")

_tesseract_available: bool | None = None


def is_ocr_available() -> bool:
    global _tesseract_available
    if _tesseract_available is not None:
        return _tesseract_available
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        _tesseract_available = True
    except Exception as exc:
        log.warning(
            "Tesseract OCR không khả dụng trên môi trường này (%s). "
            "Các trang PDF dạng scan sẽ bị bỏ qua OCR và đánh dấu warning.",
            exc,
        )
        _tesseract_available = False
    return _tesseract_available


def ocr_page(pdf_path: str | Path, page_index: int, dpi: int = 300, languages: str = "vie+eng") -> str | None:
    """Render one page to an image and OCR it. Returns None on any failure."""
    if not is_ocr_available():
        return None
    try:
        import pytesseract
        from PIL import Image
        import io

        doc = fitz.open(str(pdf_path))
        try:
            page = doc[page_index]
            zoom = dpi / 72
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            img = Image.open(io.BytesIO(pix.tobytes("png")))
        finally:
            doc.close()
        text = pytesseract.image_to_string(img, lang=languages)
        return text
    except Exception as exc:
        log.warning("OCR thất bại cho %s trang %s: %s", pdf_path, page_index, exc)
        return None
