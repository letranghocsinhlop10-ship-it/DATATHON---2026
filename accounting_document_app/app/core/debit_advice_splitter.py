"""Tách file PDF gộp nhiều "Giấy báo nợ / Debit Advice" VietinBank thành
từng file PDF MỘT TRANG vật lý.

BỐI CẢNH (§E yêu cầu nghiệp vụ): một file như ``giay-bao-No.pdf`` có thể có
hàng chục trang, MỖI TRANG là một giao dịch/Debit Advice độc lập — khác hẳn
``VoucherSplitter`` (Phase 2) vốn xử lý trường hợp một chứng từ trải dài
NHIỀU trang. Ở đây một trang = một chứng từ hoàn chỉnh.

CHỈ tách trang thực sự có cấu trúc Debit Advice — dùng LẠI đúng
``DocumentClassifier``/``document_rules.yaml`` (loại ``VIETINBANK_DEBIT_ADVICE``)
để quyết định, không có luật riêng thứ hai: một trang phải vừa có nhãn
("GIẤY BÁO NỢ"/"Debit Advice") VỪA có ít nhất một field chính (số giao dịch,
ngày, số tiền...) mới được coi là hợp lệ — không tách mù mọi PDF nhiều trang.

Khi tách: dùng ``pymupdf.Document.insert_pdf`` để COPY NGUYÊN VẸN trang PDF
gốc sang file mới — không render lại, không đổi nội dung. File gốc không bao
giờ bị sửa/xoá/di chuyển.

File tách ra được ghi vào một thư mục "preprocessing" nằm CẠNH thư mục
nguồn của người dùng (vd. ``<ALL_DATA>/_DEBIT_SPLIT/``) — không bao
giờ ghi vào thư mục cài đặt ứng dụng / PyInstaller ``_internal``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pymupdf

from app.config_loader import ClassifierConfig
from app.core.document_classifier import DocumentClassifier
from app.core.pdf_reader import PageContent, PDFReadError, PDFReader
from app.core.text_normalizer import flatten_whitespace
from app.models.enums import DocumentType
from app.utils.file_utils import iter_pdf_files, safe_folder_name, unique_path

__all__ = ["SplitPage", "SplitProgress", "DebitAdviceSplitResult", "DebitAdviceSplitter"]

logger = logging.getLogger(__name__)

#: Dùng để đặt tên file tách ra cho dễ đọc (vd. ``DEBIT_ADVICE_3186.pdf``).
#: Đây CHỈ là gợi ý đặt tên — giá trị chính thức của ``transaction_number``
#: vẫn do luật trích xuất trong ``extraction_rules.yaml`` quyết định khi file
#: tách ra được SCAN lại như một PDF bình thường.
_TRANSACTION_NUMBER_RE = re.compile(
    r"Số giao dịch\s*/\s*Transaction number:?\s*([A-Za-z0-9]{2,20})", re.IGNORECASE
)


@dataclass(frozen=True)
class SplitPage:
    """Một trang đã được tách thành file PDF vật lý riêng."""

    source_pdf: Path
    source_page: int
    output_path: Path


@dataclass(frozen=True)
class SplitProgress:
    current: int
    total: int
    file_name: str
    message: str


@dataclass
class DebitAdviceSplitResult:
    """Kết quả một lượt quét + tách."""

    scanned_files: int = 0
    bundle_files: list[Path] = field(default_factory=list)
    split_pages: list[SplitPage] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def excluded_source_paths(self) -> set[Path]:
        """File gốc đã có bản tách vật lý — cần LOẠI khỏi lượt SCAN bình
        thường để không sinh chứng từ trùng (xem
        ``ScanService.scan_folder(..., exclude_paths=...)``)."""
        return set(self.bundle_files)


class DebitAdviceSplitter:
    """Quét một thư mục, tách mọi file có trang Debit Advice VietinBank.

    Args:
        classifier_config: Dùng LẠI luật phân loại chung (không có luật
            riêng) — một trang chỉ được tách khi ``DocumentClassifier`` xếp
            nó vào ``VIETINBANK_DEBIT_ADVICE`` với điểm đủ cao.
        reader: ``PDFReader`` tuỳ chỉnh, mặc định dùng cấu hình chuẩn.
        min_score: Điểm tối thiểu để coi một trang là Debit Advice hợp lệ.
            Tiêu đề song ngữ "GIẤY BÁO NỢ / Debit Advice" tự nó đã khớp CẢ
            HAI từ khoá ``must_have_any`` nên cho 2 điểm — mặc định 3.0 đòi
            hỏi thêm ít nhất MỘT field mạnh thật sự (số giao dịch, ngày...),
            đúng yêu cầu "có nhãn VÀ có field chính", không tách một trang
            chỉ lướt qua mỗi dòng tiêu đề mà không có dữ liệu giao dịch nào.
    """

    def __init__(
        self,
        classifier_config: ClassifierConfig,
        *,
        reader: PDFReader | None = None,
        min_score: float = 3.0,
    ) -> None:
        self._classifier = DocumentClassifier(classifier_config)
        self._reader = reader or PDFReader()
        self._min_score = min_score

    def split_folder(
        self,
        folder: Path | str,
        output_dir: Path | str,
        *,
        on_progress: Callable[[SplitProgress], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> DebitAdviceSplitResult:
        """Quét toàn bộ PDF trong ``folder``, tách những file có trang Debit Advice.

        Args:
            folder: Thư mục nguồn (vd. ``ALL_DATA``), quét đệ quy.
            output_dir: Thư mục ghi các trang đã tách — tự loại khỏi vùng quét
                để không tự tách lại chính kết quả của mình ở lần chạy sau.
            on_progress: Callback tiến độ sau mỗi file.
            should_cancel: Callback huỷ hợp tác — dừng SAU file đang xử lý.

        Returns:
            ``DebitAdviceSplitResult``.
        """
        folder = Path(folder)
        output_dir = Path(output_dir)
        output_dir_resolved = output_dir.resolve() if output_dir.exists() else output_dir

        candidates = [
            p
            for p in iter_pdf_files(folder)
            if output_dir_resolved not in p.resolve().parents and p.resolve() != output_dir_resolved
        ]
        result = DebitAdviceSplitResult()
        total = len(candidates)

        for index, path in enumerate(candidates, start=1):
            if should_cancel is not None and should_cancel():
                logger.info("Đã huỷ tách Giấy báo nợ sau %d/%d file", index - 1, total)
                break

            result.scanned_files += 1
            try:
                self._split_one(path, output_dir, result)
            except PDFReadError as exc:
                logger.warning("Không đọc được %s khi tìm Giấy báo nợ: %s", path.name, exc)
            except Exception:  # noqa: BLE001 - một file lỗi không được dừng cả lô
                logger.exception("Lỗi không lường trước khi tách %s", path.name)
                result.errors.append(f"Lỗi khi xử lý {path.name}")

            if on_progress is not None:
                on_progress(
                    SplitProgress(
                        current=index,
                        total=total,
                        file_name=path.name,
                        message=f"Đang tìm Giấy báo nợ {index} / {total}: {path.name}",
                    )
                )

        logger.info(
            "Tách Giấy báo nợ xong: %d file quét, %d file có Debit Advice, %d trang đã tách",
            result.scanned_files,
            len(result.bundle_files),
            len(result.split_pages),
        )
        return result

    # -------------------------------------------------------------- nội bộ

    def _split_one(self, path: Path, output_dir: Path, result: DebitAdviceSplitResult) -> None:
        content = self._reader.read(path)
        qualifying = [page for page in content.pages if self._page_is_debit_advice(page)]
        if not qualifying:
            return

        output_dir.mkdir(parents=True, exist_ok=True)
        result.bundle_files.append(path)

        src_doc = pymupdf.open(path)
        try:
            for page in qualifying:
                dest = unique_path(output_dir / self._derive_name(path, page))
                new_doc = pymupdf.open()
                try:
                    new_doc.insert_pdf(src_doc, from_page=page.number - 1, to_page=page.number - 1)
                    new_doc.save(dest)
                finally:
                    new_doc.close()
                result.split_pages.append(
                    SplitPage(source_pdf=path, source_page=page.number, output_path=dest)
                )
                logger.debug(
                    "Đã tách trang %d của %s -> %s", page.number, path.name, dest.name
                )
        finally:
            src_doc.close()

    def _page_is_debit_advice(self, page: PageContent) -> bool:
        classification = self._classifier.classify(flatten_whitespace(page.text))
        return (
            classification.document_type is DocumentType.VIETINBANK_DEBIT_ADVICE
            and classification.score >= self._min_score
        )

    @staticmethod
    def _derive_name(source: Path, page) -> str:
        match = _TRANSACTION_NUMBER_RE.search(flatten_whitespace(page.text))
        if match:
            return safe_folder_name(f"DEBIT_ADVICE_{match.group(1)}.pdf")
        return safe_folder_name(f"DEBIT_ADVICE_{source.stem}_p{page.number}.pdf")
