"""PDF Reader stage: get raw text out of a PDF, page by page.

Never assumes a fixed layout — just returns the linear text stream per
page plus a page image (for OCR fallback) when the page looks like it
has no usable text layer.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from app.core.logging_config import get_logger

log = get_logger("pdf.reader")


class PdfReadError(Exception):
    """Raised when a PDF cannot be opened/parsed at all."""


@dataclass
class PageContent:
    index: int
    text: str
    has_text_layer: bool


@dataclass
class PdfContent:
    path: str
    pages: list[PageContent]
    file_hash: str

    @property
    def full_text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    @property
    def any_text_layer(self) -> bool:
        return any(p.has_text_layer for p in self.pages)


def sha256_of_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_pdf(path: str | Path, min_chars_for_text_layer: int = 20) -> PdfContent:
    """Extract text per page. Raises PdfReadError on unreadable/corrupt files.

    A page is flagged `has_text_layer=False` when it yields fewer than
    `min_chars_for_text_layer` characters of text — the caller (pipeline)
    then decides whether to run OCR on it.
    """
    path = str(path)
    try:
        doc = fitz.open(path)
    except Exception as exc:  # pragma: no cover - fitz raises various types
        raise PdfReadError(f"Không mở được PDF: {exc}") from exc

    try:
        pages: list[PageContent] = []
        for i, page in enumerate(doc):
            try:
                text = page.get_text("text") or ""
            except Exception as exc:  # pragma: no cover
                log.warning("Lỗi đọc text trang %s của %s: %s", i, path, exc)
                text = ""
            pages.append(
                PageContent(
                    index=i,
                    text=text,
                    has_text_layer=len(text.strip()) >= min_chars_for_text_layer,
                )
            )
    finally:
        doc.close()

    if not pages:
        raise PdfReadError("PDF không có trang nào")

    return PdfContent(path=path, pages=pages, file_hash=sha256_of_file(path))


def find_sibling_xml(pdf_path: str | Path) -> Path | None:
    """Vietnamese e-invoice PDFs are frequently shipped with a same-stem
    .xml sidecar (the actual signed invoice; the PDF is just a display
    rendering). If present in the same folder, prefer it for extraction.
    """
    p = Path(pdf_path)
    candidate = p.with_suffix(".xml")
    if candidate.exists():
        return candidate
    # some exports lowercase/uppercase differently or add a numeric prefix
    # shared with the pdf (e.g. "1_ABC.pdf" / "1_ABC.xml") - already covered
    # by with_suffix above. Also try case-insensitive match in the folder.
    for f in p.parent.glob(f"{p.stem}.*"):
        if f.suffix.lower() == ".xml":
            return f
    return None
