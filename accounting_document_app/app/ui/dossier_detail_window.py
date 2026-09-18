"""Cửa sổ chi tiết một dossier — theo wireframe §8.2 Phase 1.

Hiển thị 3 khối META/DEBIT/VAT (hoặc "THIẾU" nếu trống), cho phép mở PDF gốc,
ghi chú, và đánh dấu đã review. Đây là công cụ để kế toán TỰ KIỂM CHỨNG dữ
liệu — mọi con số hiển thị ở đây đọc thẳng từ ``ExtractedField``, kèm
``raw_snippet`` để đối chiếu với PDF gốc.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
from datetime import datetime

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.database.document_repository import DocumentRepository
from app.database.dossier_repository import DossierRepository
from app.models.document import Document
from app.models.dossier import Dossier
from app.ui.view_models import status_color, status_label
from app.utils.date_utils import format_display
from app.utils.money_utils import format_vnd

__all__ = ["DossierDetailWindow"]

logger = logging.getLogger(__name__)


def open_with_default_viewer(path: str) -> None:
    """Mở một file bằng trình xem mặc định của hệ điều hành.

    Trên Windows dùng ``os.startfile`` (chỉ tồn tại trên Windows); trên
    macOS/Linux dùng lệnh hệ thống tương ứng, phục vụ chạy dev trên máy khác.
    """
    system = platform.system()
    if system == "Windows":
        os.startfile(path)  # type: ignore[attr-defined]
    elif system == "Darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)


class DossierDetailWindow(QDialog):
    """Hộp thoại chi tiết một dossier.

    Args:
        dossier: Dossier cần hiển thị.
        documents: Repository để tải chứng từ theo id.
        dossier_repo: Repository để lưu lại khi đánh dấu review / sửa ghi chú.
        parent: Widget cha.
    """

    def __init__(
        self,
        dossier: Dossier,
        documents: DocumentRepository,
        dossier_repo: DossierRepository,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._dossier = dossier
        self._documents = documents
        self._dossier_repo = dossier_repo

        self.setWindowTitle(f"HỒ SƠ {dossier.dossier_code}")
        self.resize(700, 600)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        d = self._dossier

        header = QHBoxLayout()
        header.addWidget(QLabel(f"<b>Reference: {d.reference or '—'}</b>"))
        status_lbl = QLabel(f"● {status_label(d.status)}")
        status_lbl.setStyleSheet(f"color: {status_color(d.status)}; font-weight: 600;")
        header.addWidget(status_lbl)
        header.addWidget(QLabel(f"Ngày GD: {format_display(d.transaction_date) or '—'}"))
        header.addWidget(QLabel(f"Thẻ: ****{d.card_last4 or '----'}"))
        header.addStretch()
        layout.addLayout(header)

        layout.addWidget(self._build_role_box("① META INVOICE", d.meta_document_id, d.meta_count))
        layout.addWidget(
            self._build_role_box("② CHỨNG TỪ THANH TOÁN NGÂN HÀNG", d.debit_document_id, d.debit_count)
        )
        layout.addWidget(self._build_role_box("③ VPBANK VAT INVOICE", d.vat_document_id, d.vat_count))

        if d.issues:
            issues_box = QGroupBox("Vấn đề phát hiện", self)
            issues_layout = QVBoxLayout(issues_box)
            for issue in d.issues:
                issues_layout.addWidget(QLabel(f"[{issue.severity.value}] {issue.code}: {issue.description}"))
            layout.addWidget(issues_box)

        notes_row = QHBoxLayout()
        notes_row.addWidget(QLabel("Ghi chú:"))
        self._notes_edit = QLineEdit(d.notes or "", self)
        notes_row.addWidget(self._notes_edit)
        layout.addLayout(notes_row)

        footer = QHBoxLayout()
        self._reviewed_checkbox = QCheckBox("Đã review", self)
        self._reviewed_checkbox.setChecked(d.reviewed)
        footer.addWidget(self._reviewed_checkbox)
        footer.addStretch()

        save_button = QPushButton("Lưu", self)
        save_button.clicked.connect(self._on_save)
        footer.addWidget(save_button)

        close_button = QPushButton("Đóng", self)
        close_button.clicked.connect(self.reject)
        footer.addWidget(close_button)
        layout.addLayout(footer)

    def _build_role_box(self, title: str, document_id: int | None, count: int) -> QGroupBox:
        box = QGroupBox(title, self)
        box_layout = QVBoxLayout(box)

        if count >= 2:
            box_layout.addWidget(QLabel(f"⚠ TRÙNG LẶP — {count} chứng từ cùng khoá, cần chọn bản chính"))
            return box

        if document_id is None:
            box_layout.addWidget(QLabel("⚠ THIẾU — không tìm thấy chứng từ cho bộ này"))
            return box

        document = self._documents.get(document_id)
        if document is None:  # pragma: no cover - dữ liệu không nhất quán, hiếm gặp
            box_layout.addWidget(QLabel("⚠ Không đọc được chứng từ từ database"))
            return box

        file_row = QHBoxLayout()
        file_row.addWidget(QLabel(f"File: {document.file_name} ({document.page_range_label})"))
        open_button = QPushButton("Mở PDF", self)
        open_button.clicked.connect(lambda: self._open_pdf(document))
        file_row.addWidget(open_button)
        box_layout.addLayout(file_row)

        box_layout.addWidget(
            QLabel(f"Reference: {document.match_key or '—'}    Tổng tiền: {format_vnd(document.total_amount)}")
        )
        if document.value_of("invoice_number"):
            box_layout.addWidget(QLabel(f"Số hoá đơn: {document.value_of('invoice_number')}"))
        box_layout.addWidget(QLabel(f"Nguồn text: {document.text_source.value}"))
        return box

    def _open_pdf(self, document: Document) -> None:
        try:
            open_with_default_viewer(str(document.file_path))
        except OSError as exc:
            QMessageBox.warning(self, "Không mở được file", str(exc))

    def _on_save(self) -> None:
        self._dossier.notes = self._notes_edit.text().strip() or None
        was_reviewed = self._dossier.reviewed
        self._dossier.reviewed = self._reviewed_checkbox.isChecked()
        if self._dossier.reviewed and not was_reviewed:
            self._dossier.reviewed_at = datetime.now()
        self._dossier_repo.save(self._dossier)
        self.accept()
