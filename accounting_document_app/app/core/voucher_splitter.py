"""Tách một file PDF chứa NHIỀU chứng từ thành từng chứng từ độc lập.

BỐI CẢNH (xác nhận nghiệp vụ Q13): một file PDF có thể gộp nhiều chứng từ —
ví dụ một bản in sao kê chứa 5 phiếu ghi nợ liên tiếp. Nếu xử lý cả file như
một chứng từ, regex của chứng từ này sẽ lấy nhầm dữ liệu của chứng từ kia và
toàn bộ việc ghép hồ sơ sẽ sai.

CÁCH TÁCH — chỉ dựa vào dấu hiệu chắc chắn, không suy đoán::

    trang có 'page_start_marker'  -> bắt đầu một chứng từ MỚI
    trang không có marker nào     -> trang tiếp theo của chứng từ liền trước

Marker được khai báo trong ``document_rules.yaml`` và phải là chuỗi CHỈ xuất
hiện ở trang đầu của chứng từ. Ví dụ hoá đơn Meta dùng ``"Hóa đơn thuế cho"``
(chỉ có ở trang 1) chứ KHÔNG dùng ``"Meta Platforms Ireland"`` (có cả ở trang 2,
sẽ cắt đôi hoá đơn).

AN TOÀN:

* Không tìm thấy marker nào -> giữ nguyên cả file làm MỘT chứng từ, đúng như
  hành vi cũ. Không đoán chỗ cắt.
* Trang đầu file không có marker -> phần đầu đó thành một đoạn riêng, gắn cờ
  ``LEADING_PAGES_WITHOUT_MARKER`` để người dùng kiểm tra.
* Một trang khớp marker của NHIỀU loại -> vẫn cắt tại đó nhưng không gán loại;
  việc phân loại do ``DocumentClassifier`` quyết định trên nội dung từng đoạn.

Marker chỉ quyết định RANH GIỚI. Loại chứng từ luôn do classifier quyết định,
để không có hai nguồn chân lý. Lệch nhau -> cờ ``SEGMENT_TYPE_CONFLICT``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config_loader import ClassifierConfig
from app.core.pdf_reader import PDFContent
from app.core.text_normalizer import flatten_whitespace
from app.models.enums import DocumentType

__all__ = ["DocumentSegment", "VoucherSplitter"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocumentSegment:
    """Một chứng từ logic nằm trong file PDF.

    Attributes:
        index: Thứ tự chứng từ trong file, bắt đầu từ 0.
        page_numbers: Các trang thuộc chứng từ này (bắt đầu từ 1).
        marker_type: Loại suy ra từ marker mở đầu; ``None`` khi không xác định.
        marker_text: Chuỗi marker đã khớp, để truy vết.
        issues: Các cờ cảnh báo phát sinh khi tách.
    """

    index: int
    page_numbers: tuple[int, ...]
    marker_type: DocumentType | None = None
    marker_text: str | None = None
    issues: tuple[str, ...] = ()

    @property
    def page_start(self) -> int:
        return self.page_numbers[0]

    @property
    def page_end(self) -> int:
        return self.page_numbers[-1]

    @property
    def page_count(self) -> int:
        return len(self.page_numbers)

    def content(self, source: PDFContent) -> PDFContent:
        """Trích phần nội dung PDF thuộc riêng chứng từ này."""
        return source.subset(self.page_numbers)


class VoucherSplitter:
    """Tách ``PDFContent`` thành các chứng từ độc lập theo marker trang đầu.

    Args:
        config: Bộ luật phân loại, nơi khai báo ``page_start_markers``.
    """

    def __init__(self, config: ClassifierConfig) -> None:
        self._config = config
        self._markers: list[tuple[str, DocumentType]] = [
            (marker, rule.document_type)
            for rule in config.rules
            for marker in rule.page_start_markers
        ]
        if not self._markers:
            logger.warning(
                "Chưa khai báo page_start_markers cho loại nào — "
                "mọi PDF sẽ được coi là chỉ chứa một chứng từ"
            )

    def split(self, content: PDFContent) -> list[DocumentSegment]:
        """Tách một file PDF thành danh sách chứng từ.

        Args:
            content: Nội dung PDF đã đọc.

        Returns:
            Danh sách ``DocumentSegment`` theo thứ tự trang. Luôn có ít nhất
            một phần tử khi file có trang; danh sách rỗng khi file không trang.
        """
        if not content.pages:
            return []

        starts = self._find_starts(content)

        if not starts:
            logger.debug(
                "%s: không thấy marker nào — coi cả file là một chứng từ",
                content.path.name,
            )
            return [
                DocumentSegment(
                    index=0,
                    page_numbers=tuple(p.number for p in content.pages),
                )
            ]

        return self._build_segments(content, starts)

    # ------------------------------------------------------------- nội bộ

    def _find_starts(
        self, content: PDFContent
    ) -> dict[int, tuple[DocumentType | None, str, tuple[str, ...]]]:
        """Tìm các trang mở đầu một chứng từ mới."""
        starts: dict[int, tuple[DocumentType | None, str, tuple[str, ...]]] = {}
        for page in content.pages:
            haystack = flatten_whitespace(page.text).lower()
            hits = [
                (marker, doc_type)
                for marker, doc_type in self._markers
                if marker.lower() in haystack
            ]
            if not hits:
                continue

            found_types = {doc_type for _, doc_type in hits}
            if len(found_types) == 1:
                marker, doc_type = hits[0]
                starts[page.number] = (doc_type, marker, ())
            else:
                # Một trang mang marker của nhiều loại: vẫn cắt, nhưng không
                # gán loại — để classifier quyết định trên nội dung.
                logger.warning(
                    "%s trang %d khớp marker của nhiều loại: %s",
                    content.path.name,
                    page.number,
                    sorted(t.value for t in found_types),
                )
                starts[page.number] = (None, hits[0][0], ("MARKER_AMBIGUOUS",))
        return starts

    def _build_segments(
        self,
        content: PDFContent,
        starts: dict[int, tuple[DocumentType | None, str, tuple[str, ...]]],
    ) -> list[DocumentSegment]:
        """Gom các trang thành đoạn, trang không có marker nối vào đoạn trước."""
        segments: list[DocumentSegment] = []
        current_pages: list[int] = []
        current_meta: tuple[DocumentType | None, str | None, tuple[str, ...]] = (
            None,
            None,
            ("LEADING_PAGES_WITHOUT_MARKER",),
        )

        def flush() -> None:
            if not current_pages:
                return
            doc_type, marker, issues = current_meta
            segments.append(
                DocumentSegment(
                    index=len(segments),
                    page_numbers=tuple(current_pages),
                    marker_type=doc_type,
                    marker_text=marker,
                    issues=issues,
                )
            )

        for page in content.pages:
            if page.number in starts:
                flush()
                doc_type, marker, issues = starts[page.number]
                current_pages = [page.number]
                current_meta = (doc_type, marker, issues)
            else:
                current_pages.append(page.number)
        flush()

        # Đoạn đầu không có marker mà file lại có marker ở trang sau: đó là
        # phần thừa cần người dùng xem, không phải chứng từ hoàn chỉnh.
        if segments and segments[0].page_start not in starts:
            logger.warning(
                "%s: %d trang đầu không có marker mở đầu chứng từ",
                content.path.name,
                segments[0].page_count,
            )

        if len(segments) > 1:
            logger.info(
                "%s chứa %d chứng từ: %s",
                content.path.name,
                len(segments),
                ", ".join(f"tr.{s.page_start}-{s.page_end}" for s in segments),
            )
        return segments
