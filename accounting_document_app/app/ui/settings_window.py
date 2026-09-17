"""Cửa sổ Settings — 4 tab theo wireframe §8.5 Phase 1.

Thư mục · Xử lý · Kế toán · Reference. Mọi thay đổi ghi vào bảng ``settings``
(ghi đè cấu hình mặc định đọc từ YAML lúc khởi động, không sửa file YAML —
giữ file YAML làm baseline có thể khôi phục qua nút "Khôi phục mặc định").
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.config_loader import AppSettings
from app.database.settings_repository import SettingsRepository

__all__ = ["SettingsWindow"]

logger = logging.getLogger(__name__)

#: key trong bảng settings <-> field của AppSettings (đơn giản hoá cho Phase 4).
_KEYS = (
    "paths.input_folder",
    "paths.output_folder",
    "paths.excel_folder",
    "paths.database",
    "paths.log_file",
    "processing.ocr_enabled",
    "processing.ocr_engine",
    "processing.min_chars_per_page",
    "processing.max_workers",
    "processing.force_rescan",
    "accounting.marketing_expense",
    "accounting.bank_fee_expense",
    "accounting.input_vat",
    "accounting.bank",
    "accounting.company_tax_code",
    "reference.pattern",
    "reference.strip_inner_whitespace",
    "reference.max_date_gap_days",
)


class SettingsWindow(QDialog):
    """Hộp thoại cấu hình người dùng.

    Args:
        settings_repo: Kho key-value trong SQLite.
        defaults: Cấu hình mặc định đọc từ YAML lúc khởi động — dùng để hiển
            thị giá trị ban đầu và cho nút "Khôi phục mặc định".
        parent: Widget cha.
    """

    def __init__(self, settings_repo: SettingsRepository, defaults: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self._repo = settings_repo
        self._defaults = defaults
        self._fields: dict[str, QWidget] = {}

        self.setWindowTitle("Settings")
        self.resize(600, 450)
        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        tabs = QTabWidget(self)

        tabs.addTab(self._build_folders_tab(), "Thư mục")
        tabs.addTab(self._build_processing_tab(), "Xử lý")
        tabs.addTab(self._build_accounting_tab(), "Kế toán")
        tabs.addTab(self._build_reference_tab(), "Reference")
        layout.addWidget(tabs)

        restore_button = QPushButton("Khôi phục mặc định", self)
        restore_button.clicked.connect(self._on_restore_defaults)
        layout.addWidget(restore_button)

        save_button = QPushButton("Lưu", self)
        save_button.clicked.connect(self._on_save)
        layout.addWidget(save_button)

    def _build_folders_tab(self) -> QWidget:
        widget = QWidget(self)
        form = QFormLayout(widget)
        for key, label in (
            ("paths.input_folder", "Thư mục PDF đầu vào"),
            ("paths.output_folder", "Thư mục xuất hồ sơ"),
            ("paths.excel_folder", "Thư mục xuất Excel"),
            ("paths.database", "File database"),
            ("paths.log_file", "File log"),
        ):
            edit = QLineEdit(widget)
            self._fields[key] = edit
            form.addRow(label, edit)
        return widget

    def _build_processing_tab(self) -> QWidget:
        widget = QWidget(self)
        form = QFormLayout(widget)

        ocr_checkbox = QCheckBox(widget)
        self._fields["processing.ocr_enabled"] = ocr_checkbox
        form.addRow("Bật OCR", ocr_checkbox)

        engine_combo = QComboBox(widget)
        engine_combo.addItems(["none", "tesseract", "paddle"])
        self._fields["processing.ocr_engine"] = engine_combo
        form.addRow("Engine OCR", engine_combo)

        min_chars_spin = QSpinBox(widget)
        min_chars_spin.setRange(1, 1000)
        self._fields["processing.min_chars_per_page"] = min_chars_spin
        form.addRow("Ngưỡng min_chars_per_page", min_chars_spin)

        workers_spin = QSpinBox(widget)
        workers_spin.setRange(1, 32)
        self._fields["processing.max_workers"] = workers_spin
        form.addRow("Số worker", workers_spin)

        force_checkbox = QCheckBox(widget)
        self._fields["processing.force_rescan"] = force_checkbox
        form.addRow("Force re-scan", force_checkbox)

        return widget

    def _build_accounting_tab(self) -> QWidget:
        widget = QWidget(self)
        form = QFormLayout(widget)
        for key, label in (
            ("accounting.marketing_expense", "TK Chi phí quảng cáo"),
            ("accounting.bank_fee_expense", "TK Phí ngân hàng"),
            ("accounting.input_vat", "TK Thuế GTGT đầu vào"),
            ("accounting.bank", "TK Ngân hàng"),
            ("accounting.company_tax_code", "MST công ty"),
        ):
            edit = QLineEdit(widget)
            self._fields[key] = edit
            form.addRow(label, edit)
        return widget

    def _build_reference_tab(self) -> QWidget:
        widget = QWidget(self)
        form = QFormLayout(widget)

        pattern_edit = QLineEdit(widget)
        self._fields["reference.pattern"] = pattern_edit
        form.addRow("Pattern hợp lệ", pattern_edit)

        strip_checkbox = QCheckBox(widget)
        self._fields["reference.strip_inner_whitespace"] = strip_checkbox
        form.addRow("Xoá khoảng trắng bên trong", strip_checkbox)

        gap_spin = QSpinBox(widget)
        gap_spin.setRange(0, 365)
        self._fields["reference.max_date_gap_days"] = gap_spin
        form.addRow("Ngưỡng lệch ngày (ngày)", gap_spin)

        return widget

    # ------------------------------------------------------------- tải/lưu

    def _load_values(self) -> None:
        defaults = {
            "processing.ocr_enabled": self._defaults.ocr_enabled,
            "processing.ocr_engine": self._defaults.ocr_engine,
            "processing.min_chars_per_page": self._defaults.min_chars_per_page,
            "processing.max_workers": self._defaults.max_workers,
            "reference.pattern": self._defaults.reference_pattern,
            "reference.strip_inner_whitespace": self._defaults.strip_inner_whitespace,
            "reference.max_date_gap_days": self._defaults.max_date_gap_days,
        }
        for key, widget in self._fields.items():
            stored = self._repo.get(key)
            value = stored if stored is not None else defaults.get(key, "")
            self._set_widget_value(widget, value)

    def _on_save(self) -> None:
        for key, widget in self._fields.items():
            self._repo.set(key, str(self._get_widget_value(widget)))
        QMessageBox.information(self, "Đã lưu", "Cấu hình đã được lưu.")
        self.accept()

    def _on_restore_defaults(self) -> None:
        confirm = QMessageBox.question(
            self, "Khôi phục mặc định", "Xoá mọi tuỳ chỉnh và dùng lại cấu hình mặc định từ config/*.yaml?"
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        for key in list(self._fields):
            self._repo.delete(key)
        self._load_values()

    @staticmethod
    def _set_widget_value(widget: QWidget, value) -> None:
        if isinstance(widget, QCheckBox):
            widget.setChecked(str(value) in ("True", "true", "1"))
        elif isinstance(widget, QSpinBox):
            widget.setValue(int(value) if value not in (None, "") else 0)
        elif isinstance(widget, QComboBox):
            index = widget.findText(str(value))
            widget.setCurrentIndex(index if index >= 0 else 0)
        elif isinstance(widget, QLineEdit):
            widget.setText(str(value) if value is not None else "")

    @staticmethod
    def _get_widget_value(widget: QWidget):
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QSpinBox):
            return widget.value()
        if isinstance(widget, QComboBox):
            return widget.currentText()
        if isinstance(widget, QLineEdit):
            return widget.text()
        return None
