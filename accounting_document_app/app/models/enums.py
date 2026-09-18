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
    "PaymentRole",
    "PaymentGroupStatus",
]


class DocumentType(str, Enum):
    """Loại chứng từ, xác định bằng nội dung text — không bao giờ bằng tên file.

    ``META_INVOICE`` chính là "Facebook Bill" — hoá đơn quảng cáo Meta/Facebook
    Ads (cùng một chứng từ thật, tên gọi khác nhau tuỳ ngữ cảnh nghiệp vụ).
    """

    META_INVOICE = "META_INVOICE"
    VPBANK_DEBIT_NOTE = "VPBANK_DEBIT_NOTE"
    VPBANK_VAT_INVOICE = "VPBANK_VAT_INVOICE"
    #: Một trang "GIẤY BÁO NỢ / Debit Advice" của VietinBank — sau khi đã
    #: được tách vật lý ra khỏi file gốc nhiều trang (xem
    #: ``app/core/debit_advice_splitter.py``).
    VIETINBANK_DEBIT_ADVICE = "VIETINBANK_DEBIT_ADVICE"
    #: Sao kê ngân hàng nhiều giao dịch — CHỈ dùng để CLASSIFY/ĐỊNH TUYẾN file
    #: sang ``app/core/bank_statement_parser.py``; không có extractor riêng vì
    #: một file sinh ra NHIỀU ``BankTransaction``, không phải một ``Document``.
    BANK_STATEMENT = "BANK_STATEMENT"
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


class PaymentRole(str, Enum):
    """Vai trò của một chứng từ/giao dịch bên trong một
    ``FacebookPaymentGroup`` (xem ``app/matching/payment_group_matcher.py``).
    """

    FACEBOOK_BILL = "FACEBOOK_BILL"
    MAIN_PAYMENT = "MAIN_PAYMENT"
    BANK_FEE = "BANK_FEE"
    STATEMENT_EXTRACT = "STATEMENT_EXTRACT"
    SUPPORTING = "SUPPORTING"


class PaymentGroupStatus(str, Enum):
    """Trạng thái khớp của một ``FacebookPaymentGroup``.

    Thứ tự tín hiệu ưu tiên xem §G — reference tuyệt đối luôn mạnh hơn số
    tiền; không bao giờ tự chọn khi có nhiều ứng viên mơ hồ.
    """

    MATCHED_HIGH = "MATCHED_HIGH"
    MATCHED = "MATCHED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    UNMATCHED = "UNMATCHED"
