"""Full pipeline orchestrator, wiring every stage together in the order
from spec section 12:

PDF Reader -> OCR -> Classifier -> Extractor -> Reference Matcher ->
Reconciliation Engine -> Validation Engine -> Categorizer ->
File Organizer -> Excel/MISA Exporter -> Report
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from app.core.config_loader import get_settings
from app.core.logging_config import configure_logging, get_logger
from app.export.misa_exporter import write_misa_excel
from app.export.reconciliation_report import write_reconciliation_report
from app.export.extracted_data_exporter import write_extracted_data_excel
from app.ingest import discover_pdf_files, process_pdf_file
from app.zip_utils import extract_zips_in_place
from app.matching.reference_matcher import match_documents
from app.models.schema import CompletenessStatus, DocType, DocumentSet, DocumentStatus, ExtractedDocument, JobSummary
from app.organizing.categorizer import categorize
from app.organizing.file_organizer import organize_all
from app.reference_list.loader import discover_reference_list_files, load_all_reference_lists
from app.reference_list.merge import merge_reference_list
from app.validation.engine import validate_and_score

log = get_logger("pipeline")

ProgressCallback = Callable[[int, int, str], None]


def build_summary(document_sets: list[DocumentSet], total_files: int) -> JobSummary:
    return JobSummary(
        total_files=total_files,
        complete_sets=sum(1 for ds in document_sets if ds.completeness == CompletenessStatus.COMPLETE),
        incomplete_sets=sum(1 for ds in document_sets if ds.completeness == CompletenessStatus.INCOMPLETE),
        valid_sets=sum(1 for ds in document_sets if ds.document_status == DocumentStatus.VALID),
        error_files=sum(len(ds.error_files) for ds in document_sets if ds.completeness == CompletenessStatus.ERROR),
        duplicate_sets=sum(1 for ds in document_sets if ds.completeness == CompletenessStatus.DUPLICATE),
    )


def run_pipeline(
    input_dir: str | Path,
    output_dir: str | Path,
    progress_cb: Optional[ProgressCallback] = None,
) -> tuple[list[DocumentSet], JobSummary]:
    settings = get_settings()
    configure_logging(settings.get("log_file", "processing.log"))

    def report(done: int, total: int, stage: str) -> None:
        log.info("[%s/%s] %s", done, total, stage)
        if progress_cb:
            progress_cb(done, total, stage)

    n_extracted = extract_zips_in_place(input_dir)
    if n_extracted:
        log.info("Đã tự động giải nén %d file .zip trong input", n_extracted)

    files = discover_pdf_files(input_dir)
    total = len(files)
    report(0, total, "Đang quét file PDF trong thư mục input...")

    docs = []
    for i, (path, role) in enumerate(files, start=1):
        report(i - 1, total, f"Đang xử lý: {Path(path).name}")
        try:
            docs.append(process_pdf_file(path, role))
        except Exception as exc:
            # process_pdf_file already catches its own known failure points
            # and returns an is_error=True document instead of raising —
            # this is one more safety net so a truly unexpected exception
            # (e.g. a bad classifier/extractor config) still can't take
            # down the whole batch (spec section 10).
            log.exception("Lỗi không mong đợi khi xử lý %s", path)
            docs.append(
                ExtractedDocument(
                    doc_type=DocType.UNKNOWN,
                    source_file=path,
                    source_role_folder=role,
                    is_error=True,
                    error_reason=f"Lỗi không mong đợi: {exc}",
                )
            )
    report(total, total, "Đang ghép bộ theo số tham chiếu...")

    document_sets = match_documents(docs)

    ref_list_paths = discover_reference_list_files(input_dir)
    if ref_list_paths:
        report(total, total, "Đang đối chiếu với danh sách tham chiếu (Excel)...")
        entries = load_all_reference_lists(ref_list_paths)
        document_sets = merge_reference_list(document_sets, entries)

    report(total, total, "Đang đối chiếu & kiểm tra hợp lệ...")
    for ds in document_sets:
        validate_and_score(ds)
        categorize(ds)

    report(total, total, "Đang tổ chức thư mục OUTPUT...")
    organize_all(document_sets, output_dir)

    report(total, total, "Đang xuất Excel...")
    write_misa_excel(document_sets, Path(output_dir) / "misa_import.xlsx")
    write_reconciliation_report(document_sets, Path(output_dir) / "reconciliation_report.xlsx")
    write_extracted_data_excel(document_sets, Path(output_dir) / "extracted_data.xlsx")

    summary = build_summary(document_sets, total)
    report(total, total, "Hoàn tất")
    return document_sets, summary
