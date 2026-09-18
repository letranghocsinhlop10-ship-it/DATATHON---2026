"""Điều phối bước "Chuẩn bị dữ liệu" — §L bước 1-6.

Gộp theo đúng thứ tự nghiệp vụ:

    1. ZIP -> lấy PDF vào ``ALL_DATA`` (``app/core/zip_extractor.py``)
    2/3. Tách vật lý mọi "Giấy báo nợ" nhiều trang thành PDF một trang
         (``app/core/debit_advice_splitter.py``)
    4. Nhận diện + parse sao kê ngân hàng nhiều giao dịch
         (``app/core/bank_statement_parser.py``)
    5/6. SCAN (classify + extract) toàn bộ phần còn lại — TÁI SỬ DỤNG
         nguyên ``ScanService`` sẵn có (Phase 2/4), chỉ loại trừ những file
         đã được xử lý riêng ở bước 2-4 qua ``exclude_paths``.

Đây là bước CHUẨN BỊ chạy TRƯỚC pipeline SCAN/MATCH/ORGANIZE/EXPORT gốc —
không sửa pipeline đó, chỉ dọn input cho nó (và cho
``PaymentGroupMatcher``). Một file lỗi ở bất kỳ bước nào không được làm
dừng cả lô — ghi log, bỏ qua, tiếp tục file kế tiếp.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.config_loader import AppSettings, ClassifierConfig, ExtractionConfig
from app.core.bank_statement_parser import BankStatementParser, BankTransaction
from app.core.debit_advice_splitter import DebitAdviceSplitResult, DebitAdviceSplitter
from app.core.document_classifier import DocumentClassifier
from app.core.pdf_reader import PDFReadError, PDFReader
from app.core.zip_extractor import LooseCollectResult, ZipExtractResult, collect_loose_pdfs, extract_pdfs_from_zips
from app.database.database import Database
from app.models.enums import DocumentType
from app.services.scan_service import ScanResult, ScanService
from app.utils.file_utils import iter_pdf_files

__all__ = ["PrepareProgress", "PrepareResult", "PrepareDataService"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PrepareProgress:
    """Một mốc tiến độ — ``stage`` cho biết đang ở bước nào trong §L."""

    stage: str
    current: int
    total: int
    message: str


@dataclass
class PrepareResult:
    """Kết quả đầy đủ một lượt "Chuẩn bị dữ liệu"."""

    all_data_folder: Path
    zip_result: ZipExtractResult
    loose_collect_result: LooseCollectResult
    split_result: DebitAdviceSplitResult
    statement_files: list[Path] = field(default_factory=list)
    bank_transactions: list[BankTransaction] = field(default_factory=list)
    scan_result: ScanResult | None = None


class PrepareDataService:
    """Chạy đủ 6 bước chuẩn bị dữ liệu từ một thư mục nguồn lộn xộn.

    Args:
        db: Kết nối database đã mở (dùng cho bước SCAN cuối).
        classifier_config: Luật phân loại.
        extraction_config: Luật trích xuất.
        app_settings: Cấu hình vận hành.
    """

    def __init__(
        self,
        db: Database,
        classifier_config: ClassifierConfig,
        extraction_config: ExtractionConfig,
        app_settings: AppSettings,
    ) -> None:
        self._db = db
        self._classifier_config = classifier_config
        self._extraction_config = extraction_config
        self._app_settings = app_settings
        self._classifier = DocumentClassifier(classifier_config)
        self._reader = PDFReader(min_chars_per_page=app_settings.min_chars_per_page)

    def prepare(
        self,
        source_folder: Path | str,
        *,
        run_id: int | None,
        on_progress: Callable[[PrepareProgress], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> PrepareResult:
        """Chạy đủ 6 bước, trả về mọi kết quả trung gian để hiển thị summary.

        Args:
            source_folder: Thư mục nguồn lộn xộn của người dùng (chứa ZIP,
                PDF rời, ``ALL_DATA``/``data_1``... nếu đã có từ trước).
            run_id: Lô xử lý — gắn lên mọi ``Document`` được SCAN.
            on_progress: Callback tiến độ, gọi nhiều lần qua từng bước.
            should_cancel: Callback huỷ hợp tác — kiểm tra giữa các bước VÀ
                giữa từng file trong mỗi bước.

        Returns:
            ``PrepareResult``.
        """
        source = Path(source_folder)
        all_data = source / "ALL_DATA"

        def report(stage: str, p) -> None:
            if on_progress is not None:
                on_progress(PrepareProgress(stage=stage, current=p.current, total=p.total, message=p.message))

        zip_result = extract_pdfs_from_zips(
            source, all_data,
            on_progress=lambda p: report("ZIP", p),
            should_cancel=should_cancel,
        )
        # PDF rời nằm ngay trong thư mục nguồn (không qua ZIP nào) — vd. "PDF
        # Facebook Bill", "PDF phiếu giao dịch VPBank" nằm cạnh các file .zip
        # trong cấu trúc thực tế — cũng phải được gom vào ALL_DATA để SCAN
        # cùng một lượt, không chỉ nội dung lấy ra từ ZIP.
        loose_result = collect_loose_pdfs(source, all_data)

        split_output = all_data / "_SPLIT_DEBIT_ADVICE"
        splitter = DebitAdviceSplitter(self._classifier_config, reader=self._reader)
        split_result = splitter.split_folder(
            all_data, split_output,
            on_progress=lambda p: report("SPLIT", p),
            should_cancel=should_cancel,
        )

        statement_files, bank_transactions = self._parse_bank_statements(
            all_data,
            split_output,
            split_result.excluded_source_paths,
            on_progress=on_progress,
            should_cancel=should_cancel,
        )

        exclude_paths = split_result.excluded_source_paths | set(statement_files)
        scan_service = ScanService(self._db, self._classifier_config, self._extraction_config, self._app_settings)
        scan_result = scan_service.scan_folder(
            all_data,
            run_id=run_id,
            exclude_paths=exclude_paths,
            on_progress=lambda p: report("SCAN", p),
            should_cancel=should_cancel,
        )

        return PrepareResult(
            all_data_folder=all_data,
            zip_result=zip_result,
            loose_collect_result=loose_result,
            split_result=split_result,
            statement_files=statement_files,
            bank_transactions=bank_transactions,
            scan_result=scan_result,
        )

    # -------------------------------------------------------------- nội bộ

    def _parse_bank_statements(
        self,
        all_data: Path,
        split_output: Path,
        bundle_files: set[Path],
        *,
        on_progress: Callable[[PrepareProgress], None] | None,
        should_cancel: Callable[[], bool] | None,
    ) -> tuple[list[Path], list[BankTransaction]]:
        split_output_resolved = split_output.resolve() if split_output.exists() else split_output
        bundle_resolved = {p.resolve() for p in bundle_files}

        candidates = [
            p
            for p in iter_pdf_files(all_data)
            if split_output_resolved not in p.resolve().parents and p.resolve() not in bundle_resolved
        ]
        total = len(candidates)
        statement_files: list[Path] = []
        transactions: list[BankTransaction] = []
        parser: BankStatementParser | None = None

        for index, path in enumerate(candidates, start=1):
            if should_cancel is not None and should_cancel():
                logger.info("Đã huỷ nhận diện sao kê sau %d/%d file", index - 1, total)
                break
            try:
                content = self._reader.read(path)
                classification = self._classifier.classify(content.flat)
                if classification.document_type is DocumentType.BANK_STATEMENT:
                    if parser is None:
                        parser = BankStatementParser(reader=self._reader)
                    transactions.extend(parser.parse(path))
                    statement_files.append(path)
            except PDFReadError as exc:
                logger.warning("Không đọc được %s khi tìm sao kê: %s", path.name, exc)
            except Exception:  # noqa: BLE001 - một file lỗi không được dừng cả lô
                logger.exception("Lỗi không lường trước khi kiểm tra sao kê %s", path.name)

            if on_progress is not None:
                on_progress(
                    PrepareProgress(
                        stage="STATEMENT",
                        current=index,
                        total=total,
                        message=f"Đang kiểm tra sao kê {index} / {total}: {path.name}",
                    )
                )

        return statement_files, transactions
