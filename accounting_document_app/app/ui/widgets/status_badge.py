"""Nhãn màu hiển thị trạng thái dossier — xanh/vàng/đỏ theo §18 Phase 1."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel

from app.models.enums import DossierStatus
from app.ui.view_models import status_color, status_label

__all__ = ["StatusBadge"]


class StatusBadge(QLabel):
    """Nhãn tròn có màu nền theo trạng thái, dùng lại ở nhiều màn hình.

    Args:
        status: Trạng thái ban đầu.
        parent: Widget cha.
    """

    def __init__(self, status: DossierStatus, parent=None) -> None:
        super().__init__(parent)
        self.set_status(status)

    def set_status(self, status: DossierStatus) -> None:
        """Cập nhật nhãn và màu theo trạng thái mới."""
        color = status_color(status)
        self.setText(f"● {status_label(status)}")
        self.setStyleSheet(f"color: {color}; font-weight: 600;")
