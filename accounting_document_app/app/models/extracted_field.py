"""``ExtractedField`` — hạt nhân truy vết của toàn hệ thống.

Mỗi giá trị đọc được từ PDF không bao giờ là một chuỗi trần, mà luôn đi kèm
bằng chứng nguồn: trang nào, vị trí ký tự nào, rule nào đã sinh ra nó. Nhờ
vậy kế toán bấm vào một con số trên Excel là truy ngược được về đúng đoạn
text trong PDF gốc.

Quy ước bất di bất dịch: ``value is None`` nghĩa là KHÔNG ĐỌC ĐƯỢC. Hệ thống
không bao giờ điền giá trị mặc định, không bao giờ suy đoán.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from app.models.enums import FieldMethod

__all__ = ["ExtractedField"]

T = TypeVar("T")


@dataclass(frozen=True)
class ExtractedField(Generic[T]):
    """Một giá trị trích xuất kèm toàn bộ bằng chứng nguồn.

    Attributes:
        field_name: Tên trường nghiệp vụ, ví dụ ``reference_number``.
        value: Giá trị đã chuẩn hoá, hoặc ``None`` nếu không đọc được.
        raw_snippet: Đoạn text gốc trong PDF đã sinh ra giá trị này.
        page_number: Số trang (bắt đầu từ 1) chứa giá trị.
        char_span: Vị trí ``(start, end)`` trong text đã dùng để match.
        rule_id: Id của rule trong ``config/extraction_rules.yaml``.
        method: Cách giá trị được tạo ra.
        confidence: Độ tin cậy, chỉ có ý nghĩa với dữ liệu OCR.
        is_manual: ``True`` nếu người dùng đã sửa tay giá trị này.
        error: Mã lỗi khi không trích xuất được (ví dụ ``AMOUNT_PARSE_AMBIGUOUS``).
    """

    field_name: str
    value: T | None = None
    raw_snippet: str | None = None
    page_number: int | None = None
    char_span: tuple[int, int] | None = None
    rule_id: str | None = None
    method: FieldMethod = FieldMethod.REGEX
    confidence: float | None = None
    is_manual: bool = False
    error: str | None = None

    @property
    def found(self) -> bool:
        """``True`` khi trường đã đọc được giá trị."""
        return self.value is not None

    @classmethod
    def missing(
        cls,
        field_name: str,
        *,
        rule_id: str | None = None,
        error: str | None = None,
        method: FieldMethod = FieldMethod.REGEX,
    ) -> "ExtractedField[T]":
        """Tạo một trường rỗng — dùng khi rule không match hoặc parse thất bại."""
        return cls(
            field_name=field_name,
            value=None,
            rule_id=rule_id,
            error=error,
            method=method,
        )

    def replaced_by_user(self, new_value: T) -> "ExtractedField[T]":
        """Trả về bản sao mang giá trị người dùng nhập tay.

        Bằng chứng nguồn cũ được giữ nguyên trong ``raw_snippet`` để đối chiếu.
        """
        return ExtractedField(
            field_name=self.field_name,
            value=new_value,
            raw_snippet=self.raw_snippet,
            page_number=self.page_number,
            char_span=self.char_span,
            rule_id=self.rule_id,
            method=FieldMethod.MANUAL,
            confidence=None,
            is_manual=True,
            error=None,
        )


@dataclass(frozen=True)
class FieldSet:
    """Tập các trường trích xuất của một chứng từ.

    Dùng dict thay vì thuộc tính cố định để thêm ngân hàng / nhà cung cấp mới
    không phải sửa model — một yêu cầu bắt buộc của dự án.
    """

    fields: dict[str, ExtractedField] = field(default_factory=dict)

    def get(self, name: str) -> ExtractedField:
        """Lấy trường theo tên; trả về trường rỗng nếu chưa từng được trích xuất."""
        return self.fields.get(name, ExtractedField.missing(name, error="NOT_EXTRACTED"))

    def value(self, name: str):
        """Lấy thẳng giá trị của trường, ``None`` nếu không có."""
        return self.get(name).value

    def set(self, extracted: ExtractedField) -> None:
        """Ghi một trường vào tập."""
        self.fields[extracted.field_name] = extracted

    def __contains__(self, name: object) -> bool:
        return name in self.fields
