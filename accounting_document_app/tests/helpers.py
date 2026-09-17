"""Hàm tiện ích dùng chung trong test (tách khỏi conftest để import được)."""

from __future__ import annotations

from pathlib import Path

from app.core.pdf_reader import PageContent, PDFContent
from app.extractors.rule_engine import ExtractionContext
from app.models.enums import DocumentType, TextSource

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def read_fixture(name: str) -> str:
    """Đọc một fixture text."""
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_content(pages: list[PageContent] | list[str], name: str = "fixture.pdf") -> PDFContent:
    """Dựng ``PDFContent`` từ danh sách trang (text thuần hoặc ``PageContent``)."""
    built = [
        p if isinstance(p, PageContent) else PageContent(number=i + 1, text=p)
        for i, p in enumerate(pages)
    ]
    return PDFContent(
        path=Path(name),
        page_count=len(built),
        pages=built,
        text_source=TextSource.TEXT_LAYER,
    )


def make_context(
    content: PDFContent,
    document_type: DocumentType,
    extraction_config,
    app_settings,
) -> ExtractionContext:
    """Dựng ngữ cảnh trích xuất cho một chứng từ."""
    return ExtractionContext(
        content=content,
        document_type=document_type,
        money_format=extraction_config.money_format_for(document_type),
        reference_pattern=app_settings.reference_pattern,
        strip_inner_whitespace=app_settings.strip_inner_whitespace,
    )
