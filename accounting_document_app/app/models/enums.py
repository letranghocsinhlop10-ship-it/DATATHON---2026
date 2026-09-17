"""Các kiểu liệt kê dùng chung cho toàn ứng dụng.

Mọi enum đều kế thừa ``str`` để ghi thẳng xuống SQLite/YAML/Excel mà không
cần chuyển đổi, đồng thời vẫn so sánh được với chuỗi thô đọc từ database.
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "DocumentType",
    "TextSource",
    "ProcessingStatus",
    "FieldMethod",
    "Severity",
    "MatchSource",
    "DossierStatus",
]


class DocumentType(str, Enum):
    """Loại chứng từ, xác định bằng nội dung text — không bao giờ bằng tên file."""

    META_INVOICE = "META_INVOICE"
    VPBANK_DEBIT_NOTE = "VPBANK_DEBIT_NOTE"
    VPBANK_VAT_INVOICE = "VPBANK_VAT_INVOICE"
    UNKNOWN = "UNKNOWN"


class TextSource(str, Enum):
    """Nguồn gốc của text đã trích xuất.

    ``OCR`` và ``MIXED`` phải được hiển thị cho người dùng vì độ tin cậy
    thấp hơn hẳn ``TEXT_LAYER``.
    """

    TEXT_LAYER = "TEXT_LAYER"
    OCR = "OCR"
    MIXED = "MIXED"
    NONE = "NONE"


class ProcessingStatus(str, Enum):
    """Trạng thái xử lý của một file PDF."""

    OK = "OK"
    ERROR = "ERROR"
    NEEDS_OCR = "NEEDS_OCR"
    DUPLICATE_FILE = "DUPLICATE_FILE"
    UNKNOWN_TYPE = "UNKNOWN_TYPE"


class FieldMethod(str, Enum):
    """Cách một giá trị được tạo ra — phục vụ truy vết."""

    REGEX = "REGEX"
    LABEL_RIGHT = "LABEL_RIGHT"
    DERIVED = "DERIVED"
    OCR_REGEX = "OCR_REGEX"
    MANUAL = "MANUAL"


class Severity(str, Enum):
    """Mức độ nghiêm trọng của một vấn đề phát hiện được."""

    BLOCKING = "BLOCKING"
    WARNING = "WARNING"
    INFO = "INFO"


class MatchSource(str, Enum):
    """Nguồn gốc của một liên kết chứng từ.

    ``AUTO_EXACT`` là liên kết duy nhất hệ thống được phép tự tạo — và chỉ
    khi hai reference bằng nhau tuyệt đối sau chuẩn hoá.
    """

    AUTO_EXACT = "AUTO_EXACT"
    MANUAL = "MANUAL"


class DossierStatus(str, Enum):
    """Trạng thái một bộ hồ sơ. Chi tiết luật xem ``docs/PHASE1_ARCHITECTURE.md`` §7."""

    VALID = "VALID"
    MISSING_META = "MISSING_META"
    MISSING_DEBIT = "MISSING_DEBIT"
    MISSING_VAT = "MISSING_VAT"
    DUPLICATE_META = "DUPLICATE_META"
    DUPLICATE_DEBIT = "DUPLICATE_DEBIT"
    DUPLICATE_VAT = "DUPLICATE_VAT"
    INVALID_REFERENCE = "INVALID_REFERENCE"
    NEEDS_REVIEW = "NEEDS_REVIEW"
