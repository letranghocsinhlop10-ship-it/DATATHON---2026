"""Đọc text từ PDF bằng PyMuPDF, có ba chế độ phục vụ ba kiểu bố cục khác nhau.

    ``text``   thứ tự block của PyMuPDF — đúng cho chứng từ hai cột
               (hoá đơn Meta, debit note VPBank)
    ``flat``   như trên nhưng gộp hết khoảng trắng và xuống dòng — bắt buộc
               cho regex bắc cầu qua nhiều dòng (phần "Diễn giải")
    ``words``  danh sách từ kèm toạ độ — bắt buộc cho hoá đơn GTGT VPBank,
               nơi thứ tự vẽ text bị đảo so với bố cục

Một file lỗi không bao giờ làm dừng cả lô: lỗi được gói vào ``PDFReadError``
để tầng service ghi nhận rồi đi tiếp.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from app.core.layout import Rect, Word, label_right
from app.core.text_normalizer import flatten_whitespace, normalize_unicode
from app.models.enums import TextSource

__all__ = ["PDFReadError", "PageContent", "PDFContent", "PDFReader"]

logger = logging.getLogger(__name__)


class PDFReadError(RuntimeError):
    """Không đọc được file PDF.

    Attributes:
        code: Mã lỗi nghiệp vụ để ghi vào bảng ``errors``.
    """

    def __init__(self, message: str, code: str = "PDF_OPEN_FAILED") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class PageContent:
    """Nội dung một trang PDF ở cả ba chế độ."""

    number: int
    text: str
    words: list[Word] = field(default_factory=list)
    image_count: int = 0
    label_rects: dict[str, list[Rect]] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        """Số ký tự có nghĩa (đã bỏ khoảng trắng) — dùng để quyết định OCR."""
        return len("".join(self.text.split()))


@dataclass
class PDFContent:
    """Toàn bộ nội dung text của một file PDF."""

    path: Path
    page_count: int
    pages: list[PageContent]
    text_source: TextSource
    is_encrypted: bool = False

    @property
    def text(self) -> str:
        """Text toàn file theo thứ tự block, các trang nối bằng dòng trống."""
        return "\n".join(p.text for p in self.pages)

    @property
    def flat(self) -> str:
        """Text toàn file đã gộp mọi khoảng trắng về một dấu cách."""
        return flatten_whitespace(self.text)

    @property
    def char_count(self) -> int:
        return sum(p.char_count for p in self.pages)

    def page(self, number: int) -> PageContent:
        """Lấy trang theo số trang (bắt đầu từ 1)."""
        for p in self.pages:
            if p.number == number:
                return p
        raise IndexError(f"Không có trang {number} trong {self.path.name}")

    def subset(self, page_numbers: "list[int] | tuple[int, ...]") -> "PDFContent":
        """Trả về một ``PDFContent`` chỉ gồm các trang đã chọn.

        Dùng khi một file PDF chứa nhiều chứng từ: mỗi chứng từ được xử lý
        như một tài liệu độc lập trên đúng phần trang của nó, nên regex của
        chứng từ này không thể lấy nhầm dữ liệu của chứng từ kia.

        Args:
            page_numbers: Các số trang (bắt đầu từ 1) cần giữ lại.

        Returns:
            ``PDFContent`` mới; ``path`` giữ nguyên để vẫn truy vết được file gốc.

        Raises:
            IndexError: Có số trang không tồn tại.
        """
        wanted = list(page_numbers)
        pages = [self.page(n) for n in wanted]
        return PDFContent(
            path=self.path,
            page_count=len(pages),
            pages=pages,
            text_source=self.text_source,
            is_encrypted=self.is_encrypted,
        )

    def find_label_right(
        self,
        label: str,
        *,
        y_tolerance: float = 4.0,
    ) -> tuple[str, int] | None:
        """Tìm giá trị nằm bên phải một nhãn, quét lần lượt từng trang.

        Args:
            label: Chuỗi nhãn cần tìm, ví dụ ``"Số tham chiếu"``.
            y_tolerance: Sai số dòng tính bằng point.

        Returns:
            Cặp ``(giá trị, số trang)``, hoặc ``None`` nếu không tìm thấy.
        """
        for page in self.pages:
            rects = page.label_rects.get(label)
            if not rects:
                continue
            found = label_right(page.words, rects, y_tolerance=y_tolerance)
            if found:
                return found[0], page.number
        return None


class PDFReader:
    """Đọc PDF thành ``PDFContent``.

    Args:
        min_chars_per_page: Dưới ngưỡng này, trang bị coi là PDF scan và cần
            OCR. Mặc định 80 ký tự.
        labels_to_locate: Các nhãn cần định vị toạ độ sẵn khi đọc, phục vụ
            chiến lược ``label_right``. Truyền danh sách nhãn của loại chứng
            từ có bố cục đảo để không phải mở lại file.
    """

    def __init__(
        self,
        *,
        min_chars_per_page: int = 80,
        labels_to_locate: tuple[str, ...] = (),
    ) -> None:
        self.min_chars_per_page = min_chars_per_page
        self.labels_to_locate = labels_to_locate

    def read(self, path: Path | str) -> PDFContent:
        """Đọc toàn bộ text của một file PDF.

        Args:
            path: Đường dẫn tới file PDF.

        Returns:
            ``PDFContent`` với text ở cả ba chế độ.

        Raises:
            PDFReadError: File không tồn tại, bị mã hoá, hoặc PyMuPDF không
                mở được.
        """
        pdf_path = Path(path)
        if not pdf_path.is_file():
            raise PDFReadError(f"Không tìm thấy file: {pdf_path}", code="PDF_OPEN_FAILED")

        try:
            document = pymupdf.open(pdf_path)
        except Exception as exc:  # noqa: BLE001 - gói mọi lỗi của thư viện
            raise PDFReadError(f"Không mở được PDF {pdf_path.name}: {exc}") from exc

        try:
            if document.is_encrypted and not document.authenticate(""):
                raise PDFReadError(
                    f"PDF được bảo vệ bằng mật khẩu: {pdf_path.name}",
                    code="PDF_ENCRYPTED",
                )

            pages = [self._read_page(document, index) for index in range(document.page_count)]
            page_count = document.page_count
            is_encrypted = bool(document.is_encrypted)
        finally:
            document.close()

        text_source = self._decide_text_source(pages)
        logger.debug(
            "Đã đọc %s: %d trang, %d ký tự, nguồn=%s",
            pdf_path.name,
            page_count,
            sum(p.char_count for p in pages),
            text_source.value,
        )
        return PDFContent(
            path=pdf_path,
            page_count=page_count,
            pages=pages,
            text_source=text_source,
            is_encrypted=is_encrypted,
        )

    def _read_page(self, document: "pymupdf.Document", index: int) -> PageContent:
        """Đọc một trang ở cả ba chế độ."""
        page = document[index]
        raw_text = normalize_unicode(page.get_text("text"))
        words = [
            Word(text=w[4], rect=Rect(x0=w[0], y0=w[1], x1=w[2], y1=w[3]))
            for w in page.get_text("words")
        ]
        label_rects: dict[str, list[Rect]] = {}
        for label in self.labels_to_locate:
            hits = page.search_for(label)
            if hits:
                label_rects[label] = [Rect(h.x0, h.y0, h.x1, h.y1) for h in hits]

        return PageContent(
            number=index + 1,
            text=raw_text,
            words=words,
            image_count=len(page.get_images(full=True)),
            label_rects=label_rects,
        )

    def _decide_text_source(self, pages: list[PageContent]) -> TextSource:
        """Quyết định trang nào có lớp text thật, trang nào cần OCR.

        KHÔNG tự OCR ở tầng này — chỉ phân loại. Việc gọi OCR do tầng service
        quyết định dựa trên cấu hình của người dùng.
        """
        if not pages:
            return TextSource.NONE
        rich = [p for p in pages if p.char_count >= self.min_chars_per_page]
        if len(rich) == len(pages):
            return TextSource.TEXT_LAYER
        if not rich:
            return TextSource.NONE
        return TextSource.MIXED
