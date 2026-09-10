"""Phase-1 orchestration: PDF Reader -> OCR fallback -> Classifier ->
Extractor, wrapped so that ANY failure on a single file becomes an
`ExtractedDocument(is_error=True, ...)` instead of raising — a single
bad PDF must never crash the batch (spec section 10).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.classification.classifier import classify_text
from app.core.config_loader import get_settings
from app.core.logging_config import get_logger
from app.extraction.bank_extractor import extract_bank_debit
from app.extraction.facebook_extractor import extract_facebook
from app.extraction.vat_invoice_extractor import extract_vat_invoice
from app.models.schema import DocType, ExtractedDocument
from app.pdf.ocr import ocr_page
from app.pdf.reader import PdfReadError, find_sibling_xml, read_pdf, sha256_of_file

log = get_logger("ingest")


def process_pdf_file(path: str | Path, source_role_folder: Optional[str] = None) -> ExtractedDocument:
    path = str(path)
    settings = get_settings()
    ocr_cfg = settings.get("ocr", {})

    # Hash the raw bytes up front (works even for a file that isn't a valid
    # PDF at all) so the file organizer can still deduplicate/skip-re-copy
    # error files consistently across reruns.
    try:
        file_hash = sha256_of_file(path)
    except OSError:
        file_hash = None

    try:
        pdf = read_pdf(path, min_chars_for_text_layer=ocr_cfg.get("min_chars_for_text_layer", 20))
    except PdfReadError as exc:
        log.error("Lỗi đọc file %s: %s", path, exc)
        return ExtractedDocument(
            doc_type=DocType.UNKNOWN,
            source_file=path,
            source_role_folder=source_role_folder,
            file_hash=file_hash,
            is_error=True,
            error_reason=str(exc),
        )
    except Exception as exc:  # pragma: no cover - defensive catch-all
        log.error("Lỗi không xác định khi đọc %s: %s", path, exc)
        return ExtractedDocument(
            doc_type=DocType.UNKNOWN,
            source_file=path,
            source_role_folder=source_role_folder,
            file_hash=file_hash,
            is_error=True,
            error_reason=f"Lỗi không xác định: {exc}",
        )

    used_ocr = False
    warnings: list[str] = []
    if not pdf.any_text_layer and ocr_cfg.get("enabled", True):
        for page in pdf.pages:
            if page.has_text_layer:
                continue
            ocr_text = ocr_page(
                path,
                page.index,
                dpi=ocr_cfg.get("dpi", 300),
                languages=ocr_cfg.get("languages", "vie+eng"),
            )
            if ocr_text:
                page.text = ocr_text
                used_ocr = True
            else:
                warnings.append(f"Trang {page.index} không có text layer và OCR không khả dụng/thất bại")

    full_text = pdf.full_text
    if not full_text.strip():
        return ExtractedDocument(
            doc_type=DocType.UNKNOWN,
            source_file=path,
            source_role_folder=source_role_folder,
            file_hash=pdf.file_hash,
            is_error=True,
            error_reason="Không trích xuất được text nào (kể cả sau OCR)",
            used_ocr=used_ocr,
            warnings=warnings,
        )

    doc_type, _scores = classify_text(full_text)

    try:
        if doc_type == DocType.FACEBOOK:
            doc = extract_facebook(full_text, path)
        elif doc_type == DocType.VAT_INVOICE:
            xml_path = find_sibling_xml(path)
            doc = extract_vat_invoice(full_text, path, xml_path=xml_path)
        elif doc_type == DocType.BANK_DEBIT:
            doc = extract_bank_debit(full_text, path)
        else:
            doc = ExtractedDocument(
                doc_type=DocType.UNKNOWN,
                source_file=path,
                raw_text=full_text,
                warnings=["Không nhận diện được loại chứng từ theo bộ từ khóa hiện có"],
            )
    except Exception as exc:  # pragma: no cover - defensive catch-all
        log.exception("Lỗi trích xuất dữ liệu từ %s", path)
        return ExtractedDocument(
            doc_type=doc_type,
            source_file=path,
            source_role_folder=source_role_folder,
            file_hash=pdf.file_hash,
            is_error=True,
            error_reason=f"Lỗi trích xuất dữ liệu: {exc}",
            used_ocr=used_ocr,
            raw_text=full_text,
        )

    doc.source_role_folder = source_role_folder
    doc.used_ocr = used_ocr
    doc.file_hash = pdf.file_hash
    doc.warnings = warnings + doc.warnings
    log.info(
        "Đã xử lý %s | loại=%s | ref=%s | ocr=%s | xml=%s",
        path,
        doc.doc_type,
        doc.reference_candidates,
        used_ocr,
        doc.used_xml_sidecar,
    )
    return doc


def discover_pdf_files(input_dir: str | Path) -> list[tuple[str, Optional[str]]]:
    """Walk INPUT/<role>/**.pdf (role folders are just where the tool looks
    for files — it still classifies by content, so misplaced files are
    handled gracefully). Returns (path, role_folder_name) pairs."""
    input_dir = Path(input_dir)
    settings = get_settings()
    roles = settings.get("input_roles", ["facebook", "vat", "bank"])

    found: list[tuple[str, Optional[str]]] = []
    seen: set[str] = set()

    for role in roles:
        role_dir = input_dir / role
        if not role_dir.is_dir():
            continue
        for pdf_path in sorted(role_dir.rglob("*.pdf")):
            found.append((str(pdf_path), role))
            seen.add(str(pdf_path))

    # also pick up any PDFs dropped directly under input_dir (no role
    # sub-folder) so the tool never silently ignores a file.
    if input_dir.is_dir():
        for pdf_path in sorted(input_dir.glob("*.pdf")):
            if str(pdf_path) not in seen:
                found.append((str(pdf_path), None))

    return found
