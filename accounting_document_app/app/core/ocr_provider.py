"""Giao diện OCR — cho phép thay engine mà không sửa phần còn lại của app.

Ở Phase 2 chỉ có ``NullOCRProvider``. Ba file mẫu đều có lớp text thật nên
OCR chưa cần thiết; khi phát hiện PDF scan, hệ thống đánh dấu ``NEEDS_OCR``
và để người dùng quyết định, thay vì tự đoán nội dung.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

__all__ = ["OCRProvider", "NullOCRProvider", "OCRResult"]

logger = logging.getLogger(__name__)


class OCRResult:
    """Kết quả OCR một trang."""

    def __init__(self, text: str, confidence: float | None = None) -> None:
        self.text = text
        self.confidence = confidence


@runtime_checkable
class OCRProvider(Protocol):
    """Giao diện mọi engine OCR phải tuân theo."""

    name: str

    def is_available(self) -> bool:
        """Engine đã sẵn sàng chạy offline chưa."""

    def recognize(self, image_bytes: bytes, *, language: str = "vie") -> OCRResult:
        """Nhận dạng chữ trong một ảnh trang."""


class NullOCRProvider:
    """Engine rỗng — luôn báo không khả dụng.

    Dùng làm mặc định để ứng dụng chạy được mà không cần cài Tesseract,
    và để đảm bảo hệ thống không bao giờ *âm thầm* bỏ qua PDF scan.
    """

    name = "none"

    def is_available(self) -> bool:
        return False

    def recognize(self, image_bytes: bytes, *, language: str = "vie") -> OCRResult:
        raise RuntimeError(
            "Chưa cấu hình engine OCR. Bật OCR trong Settings hoặc kiểm tra "
            "file PDF thủ công."
        )
