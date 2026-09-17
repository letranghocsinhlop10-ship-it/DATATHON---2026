"""Điều phối bước SCAN + EXTRACT: đọc thư mục PDF -> ``Document`` đã lưu DB.

Đây là nơi các module Phase 2 (PDFReader, VoucherSplitter, DocumentClassifier,
ExtractorRegistry, DuplicateDetector) được ghép lại thành MỘT pipeline có thể
gọi từ GUI (qua ``app/ui/workers.py``), CLI, hay test — không lặp lại logic
điều phối ở nhiều nơi.

Một file PDF lỗi không bao giờ làm dừng cả lô: lỗi được ghi vào bảng
``errors`` và tiến trình quét tiếp tục (§5 Phase 1).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from app.config_loader import AppSettings, ClassifierConfig, ExtractionConfig
from app.core.document_classifier import DocumentClassifier
from app.core.duplicate_detector import DuplicateDetector, compute_sha256
from app.core.pdf_reader import PDFReadError, PDFReader
from app.core.voucher_splitter import VoucherSplitter
from app.database.database import Database
from app.database.document_repository import DocumentRepository
from app.extractors.registry import ExtractorRegistry
from app.extractors.rule_engine import ExtractionContext
from app.models.document import Document
from app.models.enums import DocumentType, ProcessingStatus
from app.models.extracted_field import FieldSet
from app.utils.file_utils import iter_pdf_files

__all__ = ["ScanProgress", "ScanResult", "ScanService"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanProgress:
    """Một mốc tiến độ để báo cho tầng gọi (GUI, CLI).

    Attributes:
        current: Số file đã xử lý xong (kể cả lỗi).
        total: Tổng số file trong lô.
        file_name: Tên file vừa xử lý.
        message: Chuỗi hiển thị, ví dụ ``"Đang xử lý PDF 127 / 300"``.
    """

    current: int
    total: int
    file_name: str
    message: str


@dataclass
class ScanResult:
    """Kết quả một lượt quét."""

    run_id: int | None
    documents: list[Document] = field(default_factory=list)
    duplicate_files: int = 0
    error_files: int = 0

    @property
    def total_files(self) -> int:
        return len(self.documents)


class ScanService:
    """Quét một thư mục PDF, trích xuất dữ liệu, lưu vào SQLite.

    Args:
        db: Kết nối database đã mở.
        classifier_config: Luật phân loại đã nạp.
        extraction_config: Luật trích xuất đã nạp.
        app_settings: Cấu hình vận hành (ngưỡng OCR, số worker...).
    """

    def __init__(
        self,
        db: Database,
        classifier_config: ClassifierConfig,
        extraction_config: ExtractionConfig,
        app_settings: AppSettings,
    ) -> None:
        self._db = db
        self._documents = DocumentRepository(db)
        self._reader = PDFReader(
            min_chars_per_page=app_settings.min_chars_per_page,
            labels_to_locate=extraction_config.all_labels,
        )
        self._splitter = VoucherSplitter(classifier_config)
        self._classifier = DocumentClassifier(classifier_config)
        self._registry = ExtractorRegistry(extraction_config)
        self._extraction_config = extraction_config
        self._reference_pattern = app_settings.reference_pattern
        self._strip_inner_whitespace = app_settings.strip_inner_whitespace

    def scan_folder(
        self,
        folder: Path | str,
        *,
        run_id: int | None = None,
        on_progress: Callable[[ScanProgress], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> ScanResult:
        """Quét toàn bộ PDF trong thư mục, trích xuất và lưu vào DB.

        Args:
            folder: Thư mục chứa PDF (duyệt cả thư mục con).
            run_id: Lô xử lý đang chạy (để gắn ``run_id`` lên mỗi document).
            on_progress: Callback báo tiến độ sau mỗi file — GUI dùng để cập
                nhật progress bar mà không block main thread (gọi từ worker
                thread, tầng UI tự lo việc đưa về main thread qua signal).
            should_cancel: Callback kiểm tra huỷ hợp tác (cooperative
                cancellation) — trả về ``True`` để dừng SAU file đang xử lý,
                không kill giữa chừng.

        Returns:
            ``ScanResult`` — toàn bộ chứng từ đã lưu (đã có ``document_id``).
        """
        paths = list(iter_pdf_files(folder))
        total = len(paths)
        duplicate_detector = DuplicateDetector()
        documents: list[Document] = []
        error_files = 0

        logger.info("Bắt đầu quét %d file PDF trong %s", total, folder)

        for index, path in enumerate(paths, start=1):
            if should_cancel is not None and should_cancel():
                logger.info("Đã huỷ sau %d/%d file", index - 1, total)
                break

            try:
                segment_docs = self._process_file(path, duplicate_detector, run_id)
                documents.extend(segment_docs)
            except PDFReadError as exc:
                error_files += 1
                logger.error("Lỗi đọc %s: %s (%s)", path.name, exc, exc.code)
            except Exception:  # noqa: BLE001 - một file lỗi không được dừng cả lô
                error_files += 1
                logger.exception("Lỗi không lường trước khi xử lý %s", path.name)

            if on_progress is not None:
                on_progress(
                    ScanProgress(
                        current=index,
                        total=total,
                        file_name=path.name,
                        message=f"Đang xử lý PDF {index} / {total}",
                    )
                )

        duplicate_count = sum(g.count - 1 for g in duplicate_detector.groups)
        logger.info(
            "Quét xong: %d chứng từ, %d file lỗi, %d file trùng",
            len(documents),
            error_files,
            duplicate_count,
        )
        return ScanResult(
            run_id=run_id,
            documents=documents,
            duplicate_files=duplicate_count,
            error_files=error_files,
        )

    # -------------------------------------------------------------- nội bộ

    def _process_file(
        self, path: Path, duplicate_detector: DuplicateDetector, run_id: int | None
    ) -> list[Document]:
        file_hash = compute_sha256(path)
        original = duplicate_detector.register(path, file_hash)

        content = self._reader.read(path)
        segments = self._splitter.split(content)

        results: list[Document] = []
        for segment in segments:
            sub_content = segment.content(content)
            classification = self._classifier.classify(sub_content.flat)
            document_type = classification.document_type

            fields = FieldSet()
            status = ProcessingStatus.OK
            extractor = self._registry.get(document_type)
            if extractor is not None:
                ctx = ExtractionContext(
                    content=sub_content,
                    document_type=document_type,
                    money_format=self._extraction_config.money_format_for(document_type),
                    reference_pattern=self._reference_pattern,
                    strip_inner_whitespace=self._strip_inner_whitespace,
                )
                fields = extractor.extract(ctx)
            elif document_type is DocumentType.UNKNOWN:
                status = ProcessingStatus.UNKNOWN_TYPE

            if original is not None:
                status = ProcessingStatus.DUPLICATE_FILE

            document = Document(
                file_name=path.name,
                file_path=path,
                file_hash=file_hash,
                file_size=path.stat().st_size,
                page_count=content.page_count,
                page_start=segment.page_start,
                page_end=segment.page_end,
                segment_index=segment.index,
                document_type=document_type,
                classify_score=classification.score,
                classify_rule_id=classification.rule_id,
                text_source=sub_content.text_source,
                raw_text=sub_content.text,
                fields=fields,
                processing_status=status,
                created_at=datetime.now(),
            )
            self._documents.save(document, run_id=run_id)
            results.append(document)

        return results
