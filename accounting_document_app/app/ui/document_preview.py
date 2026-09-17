"""Xem trước PDF — theo wireframe §8.4 Phase 1 (version 1).

Render trang bằng PyMuPDF thành ``QPixmap`` hiển thị trong ``QScrollArea``.
Không nhúng Adobe/WebEngine — tránh phình EXE và rủi ro offline. Luôn có nút
"Mở bằng trình xem mặc định" làm phương án dự phòng.
"""

from __future__ import annotations

import logging

import pymupdf
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
)

from app.ui.dossier_detail_window import open_with_default_viewer

__all__ = ["DocumentPreviewDialog"]

logger = logging.getLogger(__name__)

#: Độ phân giải render — đủ nét để đọc số trên hoá đơn mà không quá nặng.
_ZOOM = 2.0


class DocumentPreviewDialog(QDialog):
    """Hộp thoại xem trước PDF, từng trang một.

    Args:
        file_path: Đường dẫn file PDF gốc.
        parent: Widget cha.
    """

    def __init__(self, file_path: str, parent=None) -> None:
        super().__init__(parent)
        self._file_path = file_path
        self._page_index = 0
        self._page_count = 0

        self.setWindowTitle(f"Xem trước — {file_path}")
        self.resize(800, 900)
        self._build_ui()
        self._load_document()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self._page_spin = QSpinBox(self)
        self._page_spin.setMinimum(1)
        self._page_spin.valueChanged.connect(self._on_page_changed)
        toolbar.addWidget(QLabel("Trang:"))
        toolbar.addWidget(self._page_spin)
        self._page_count_label = QLabel("", self)
        toolbar.addWidget(self._page_count_label)
        toolbar.addStretch()

        open_button = QPushButton("Mở bằng trình xem mặc định", self)
        open_button.clicked.connect(self._on_open_external)
        toolbar.addWidget(open_button)
        layout.addLayout(toolbar)

        self._scroll_area = QScrollArea(self)
        self._image_label = QLabel(self)
        self._scroll_area.setWidget(self._image_label)
        self._scroll_area.setWidgetResizable(True)
        layout.addWidget(self._scroll_area)

    def _load_document(self) -> None:
        try:
            document = pymupdf.open(self._file_path)
        except Exception as exc:  # noqa: BLE001 - PDF hỏng vẫn phải hiện được dialog
            logger.error("Không mở được PDF để xem trước %s: %s", self._file_path, exc)
            self._image_label.setText(f"Không đọc được file:\n{exc}")
            return

        self._page_count = document.page_count
        self._page_spin.setMaximum(max(self._page_count, 1))
        self._page_count_label.setText(f"/ {self._page_count}")
        self._render_page(document, 0)
        document.close()

    def _render_page(self, document: "pymupdf.Document", index: int) -> None:
        page = document[index]
        pixmap_data = page.get_pixmap(matrix=pymupdf.Matrix(_ZOOM, _ZOOM))
        image = QImage(
            pixmap_data.samples,
            pixmap_data.width,
            pixmap_data.height,
            pixmap_data.stride,
            QImage.Format.Format_RGB888,
        )
        self._image_label.setPixmap(QPixmap.fromImage(image.copy()))

    def _on_page_changed(self, value: int) -> None:
        if self._page_count == 0:
            return
        try:
            document = pymupdf.open(self._file_path)
        except Exception as exc:  # noqa: BLE001
            logger.error("Không đọc lại được PDF khi đổi trang: %s", exc)
            return
        self._render_page(document, value - 1)
        document.close()

    def _on_open_external(self) -> None:
        open_with_default_viewer(self._file_path)
