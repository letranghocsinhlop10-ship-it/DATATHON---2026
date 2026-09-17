"""Model ``Document`` — một file PDF sau khi đã đọc, phân loại và trích xuất."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from app.models.enums import DocumentType, ProcessingStatus, TextSource
from app.models.extracted_field import ExtractedField, FieldSet

__all__ = ["Document"]


@dataclass
class Document:
    """Một chứng từ PDF đã xử lý.

    Dữ liệu trích xuất nằm trong ``fields`` (dict) thay vì các thuộc tính cố
    định, để thêm ngân hàng / nhà cung cấp mới không phải sửa model. Các
    thuộc tính tiện ích bên dưới chỉ là lối truy cập có kiểu cho những trường
    dùng nhiều nhất.
    """

    file_name: str
    file_path: Path
    file_hash: str
    file_size: int = 0
    page_count: int | None = None
    document_id: int | None = None

    #: Phạm vi trang của chứng từ trong file PDF gốc (bắt đầu từ 1).
    #: Với PDF chỉ chứa một chứng từ thì là toàn bộ file.
    page_start: int = 1
    page_end: int | None = None
    #: Thứ tự chứng từ trong file (0 nếu file chỉ có một chứng từ).
    segment_index: int = 0

    document_type: DocumentType = DocumentType.UNKNOWN
    classify_score: float | None = None
    classify_rule_id: str | None = None

    text_source: TextSource = TextSource.NONE
    raw_text: str = ""

    fields: FieldSet = field(default_factory=FieldSet)

    processing_status: ProcessingStatus = ProcessingStatus.OK
    duplicate_of_id: int | None = None
    error_code: str | None = None
    notes: str | None = None
    created_at: datetime = field(default_factory=datetime.now)

    # ------------------------------------------------------------- truy cập

    @property
    def segment_id(self) -> str:
        """Định danh duy nhất của chứng từ = hash file + phạm vi trang.

        Cần thiết vì một file PDF có thể chứa nhiều chứng từ, nên riêng
        ``file_hash`` không còn đủ để phân biệt.
        """
        return f"{self.file_hash}:{self.page_start}-{self.page_end or self.page_start}"

    @property
    def page_range_label(self) -> str:
        """Nhãn phạm vi trang để hiển thị, ví dụ ``"trang 3-4"``."""
        end = self.page_end or self.page_start
        return f"trang {self.page_start}" if end == self.page_start else f"trang {self.page_start}-{end}"

    def field_of(self, name: str) -> ExtractedField:
        """Lấy trường kèm bằng chứng nguồn."""
        return self.fields.get(name)

    def value_of(self, name: str):
        """Lấy thẳng giá trị của một trường, ``None`` nếu không đọc được."""
        return self.fields.value(name)

    @property
    def reference_number(self) -> str | None:
        """Số tham chiếu của CHÍNH chứng từ này."""
        return self.fields.value("reference_number")

    @property
    def meta_reference(self) -> str | None:
        """Reference của nhà cung cấp tìm thấy BÊN TRONG chứng từ ngân hàng."""
        return self.fields.value("meta_reference")

    @property
    def transaction_code(self) -> str | None:
        return self.fields.value("transaction_code")

    @property
    def card_last4(self) -> str | None:
        return self.fields.value("card_last4")

    @property
    def total_amount(self) -> Decimal | None:
        return self.fields.value("total_amount")

    @property
    def document_date(self) -> date | None:
        return self.fields.value("document_date")

    @property
    def transaction_date(self) -> date | None:
        return self.fields.value("transaction_date") or self.fields.value("document_date")

    @property
    def match_key(self) -> str | None:
        """Khoá dùng để ghép bộ hồ sơ.

        Hoá đơn Meta dùng số tham chiếu của chính nó; chứng từ ngân hàng dùng
        reference của nhà cung cấp bóc ra từ phần diễn giải. Tất cả đều đã
        được chuẩn hoá bằng ``normalize_reference``.

        Returns:
            Khoá đã chuẩn hoá, hoặc ``None`` khi chứng từ không có khoá — khi
            đó nó KHÔNG bao giờ được ghép tự động.
        """
        if self.document_type is DocumentType.META_INVOICE:
            return self.reference_number
        if self.document_type in {
            DocumentType.VPBANK_DEBIT_NOTE,
            DocumentType.VPBANK_VAT_INVOICE,
        }:
            return self.meta_reference
        return None

    @property
    def has_errors(self) -> bool:
        """Có trường nào trích xuất lỗi không."""
        return any(f.error for f in self.fields.fields.values())

    @property
    def field_errors(self) -> dict[str, str]:
        """Bản đồ ``tên trường -> mã lỗi`` của các trường có vấn đề."""
        return {n: f.error for n, f in self.fields.fields.items() if f.error}

    def __repr__(self) -> str:  # pragma: no cover - tiện debug
        return (
            f"Document({self.file_name!r}, {self.document_type.value}, "
            f"key={self.match_key!r}, status={self.processing_status.value})"
        )
