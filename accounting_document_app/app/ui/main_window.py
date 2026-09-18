"""Cửa sổ chính — theo wireframe §8.1 Phase 1.

Điều phối: chọn thư mục -> SCAN -> MATCH -> (VALIDATE nằm trong MATCH, xem
``MatchService``) -> ORGANIZE PDF -> EXPORT EXCEL. Hai bước cuối bị khoá cho
tới khi bước MATCH chạy xong ít nhất một lần.

Cửa sổ này chỉ điều phối UI — KHÔNG chứa logic nghiệp vụ. Toàn bộ quyết định
(phân loại, ghép, validate) nằm ở ``app/core``, ``app/matching``,
``app/services``; cửa sổ chỉ gọi service qua worker thread và vẽ kết quả.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.config_loader import AccountingConfig, AppSettings, ClassifierConfig, ExtractionConfig, MisaMappingConfig
from app.database.database import Database
from app.database.document_repository import DocumentRepository
from app.database.dossier_repository import DossierRepository
from app.database.processing_run_repository import ProcessingRunRepository
from app.models.dossier import Dossier
from app.models.enums import PaymentGroupStatus
from app.models.payment_case import PaymentCase
from app.services.export_service import ExportService
from app.services.match_service import MatchService
from app.services.organize_service import OrganizeService
from app.services.payment_group_service import PaymentGroupService
from app.services.prepare_data_service import PrepareDataService
from app.services.scan_service import ScanProgress, ScanResult, ScanService
from app.ui.view_models import dossier_to_row, payment_group_to_row, status_color
from app.ui.workers import (
    ExportWorker,
    MatchWorker,
    OrganizeWorker,
    PaymentGroupExportWorker,
    PaymentGroupMatchWorker,
    PaymentGroupOrganizeWorker,
    PrepareDataWorker,
    ScanWorker,
    ZipExtractWorker,
)

__all__ = ["MainWindow"]

logger = logging.getLogger(__name__)

_DOSSIER_COLUMNS = ("Hồ sơ", "Reference", "Ngày GD", "Meta", "Debit", "VAT", "Trạng thái", "Đã review")
#: Bank-agnostic — cột "Bank" hiển thị ngân hàng THỰC TẾ (VPBANK/VIETINBANK),
#: "Debit" = ✓ khi có chứng từ thanh toán chính từ BẤT KỲ ngân hàng nào.
_PAYMENT_GROUP_COLUMNS = ("Reference", "Bank", "Meta", "Debit", "Fee", "VAT", "Trạng thái")


class MainWindow(QMainWindow):
    """Cửa sổ chính của ứng dụng.

    Args:
        db: Kết nối database đã mở.
        classifier_config: Luật phân loại.
        extraction_config: Luật trích xuất.
        app_settings: Cấu hình vận hành.
        accounting_config: Cấu hình kế toán (tài khoản, MST công ty...).
        misa_config: Cấu hình mapping MISA đã resolve.
    """

    def __init__(
        self,
        db: Database,
        classifier_config: ClassifierConfig,
        extraction_config: ExtractionConfig,
        app_settings: AppSettings,
        accounting_config: AccountingConfig,
        misa_config: MisaMappingConfig,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._classifier_config = classifier_config
        self._extraction_config = extraction_config
        self._app_settings = app_settings
        self._accounting_config = accounting_config
        self._misa_config = misa_config

        self._runs = ProcessingRunRepository(db)
        self._documents = DocumentRepository(db)
        self._dossiers = DossierRepository(db)

        self._current_run_id: int | None = None
        self._scan_worker: ScanWorker | None = None
        self._match_worker: MatchWorker | None = None
        self._organize_worker: OrganizeWorker | None = None
        self._export_worker: ExportWorker | None = None
        self._zip_extract_worker: ZipExtractWorker | None = None
        self._dossier_rows: list[Dossier] = []
        self._last_dossier_count = 0

        # --- Luồng Facebook Payment Group (§L) — chạy song song, độc lập
        # với luồng dossier META/DEBIT/VAT ở trên, cùng dùng chung run_id.
        self._prepare_worker: PrepareDataWorker | None = None
        self._payment_group_match_worker: PaymentGroupMatchWorker | None = None
        self._payment_group_organize_worker: PaymentGroupOrganizeWorker | None = None
        self._payment_group_export_worker: PaymentGroupExportWorker | None = None
        self._bank_transactions: list = []
        self._payment_groups: list[PaymentCase] = []
        self._last_payment_group_count = 0

        self.setWindowTitle("Marketing Accounting Document Tool")
        self.resize(1100, 700)
        self._build_ui()
        self._update_button_states()

    # ------------------------------------------------------------- dựng UI

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        layout.addLayout(self._build_prepare_row())
        layout.addLayout(self._build_folder_row())
        layout.addLayout(self._build_action_row())
        layout.addLayout(self._build_payment_group_action_row())

        self._progress_bar = QProgressBar(self)
        self._progress_bar.setTextVisible(True)
        layout.addWidget(self._progress_bar)

        self._summary_label = QLabel("Chưa có dữ liệu — chọn thư mục nguồn và bấm Chuẩn bị dữ liệu", self)
        layout.addWidget(self._summary_label)

        self._tabs = QTabWidget(self)
        self._dossier_table = self._build_dossier_table()
        self._tabs.addTab(self._dossier_table, "Hồ sơ")
        self._payment_group_table = self._build_payment_group_table()
        self._tabs.addTab(self._payment_group_table, "Payment Case (Ngân hàng)")
        layout.addWidget(self._tabs)

        self.setStatusBar(QStatusBar(self))

    def _build_prepare_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Thư mục nguồn (ZIP + PDF lộn xộn):"))
        self._prepare_source_edit = QLineEdit(self)
        row.addWidget(self._prepare_source_edit)
        browse = QPushButton("Browse...", self)
        browse.clicked.connect(self._on_browse_prepare_source)
        row.addWidget(browse)

        self._prepare_button = QPushButton("📂 Chuẩn bị dữ liệu", self)
        self._prepare_button.setToolTip(
            "Tự động: lấy PDF từ ZIP + PDF rời -> tách Giấy báo nợ nhiều trang\n"
            "-> nhận diện & parse sao kê ngân hàng -> SCAN toàn bộ phần còn lại.\n"
            "Sau khi xong có thể bấm MATCH/ORGANIZE/EXPORT (Ngân hàng) bên dưới."
        )
        self._prepare_button.clicked.connect(self._on_prepare_clicked)
        row.addWidget(self._prepare_button)
        return row

    def _build_folder_row(self) -> QVBoxLayout:
        outer = QVBoxLayout()

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Thư mục PDF:"))
        self._input_folder_edit = QLineEdit(self)
        row1.addWidget(self._input_folder_edit)
        browse_input = QPushButton("Browse...", self)
        browse_input.clicked.connect(self._on_browse_input)
        row1.addWidget(browse_input)
        self._extract_zip_button = QPushButton("📦 Lấy PDF từ ZIP", self)
        self._extract_zip_button.setToolTip(
            "Chọn thư mục chứa các file .zip — tool tự giải nén, chỉ lấy PDF,\n"
            "đưa vào <thư mục nguồn>\\ALL_DATA (tự tạo nếu chưa có)."
        )
        self._extract_zip_button.clicked.connect(self._on_extract_zip_clicked)
        row1.addWidget(self._extract_zip_button)
        outer.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Thư mục xuất:"))
        self._output_folder_edit = QLineEdit(self)
        row2.addWidget(self._output_folder_edit)
        browse_output = QPushButton("Browse...", self)
        browse_output.clicked.connect(self._on_browse_output)
        row2.addWidget(browse_output)
        outer.addLayout(row2)

        return outer

    def _build_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()

        self._scan_button = QPushButton("① SCAN PDF", self)
        self._scan_button.clicked.connect(self._on_scan_clicked)
        row.addWidget(self._scan_button)

        self._match_button = QPushButton("② MATCH + VALIDATE", self)
        self._match_button.clicked.connect(self._on_match_clicked)
        row.addWidget(self._match_button)

        self._organize_button = QPushButton("③ ORGANIZE PDF", self)
        self._organize_button.setEnabled(False)
        self._organize_button.clicked.connect(self._on_organize_clicked)
        row.addWidget(self._organize_button)

        self._export_button = QPushButton("④ EXPORT EXCEL", self)
        self._export_button.setEnabled(False)
        self._export_button.clicked.connect(self._on_export_clicked)
        row.addWidget(self._export_button)

        self._cancel_button = QPushButton("Cancel", self)
        self._cancel_button.setEnabled(False)
        self._cancel_button.clicked.connect(self._on_cancel_clicked)
        row.addWidget(self._cancel_button)

        return row

    def _build_dossier_table(self) -> QTableWidget:
        table = QTableWidget(0, len(_DOSSIER_COLUMNS), self)
        table.setHorizontalHeaderLabels(_DOSSIER_COLUMNS)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.cellDoubleClicked.connect(self._on_dossier_row_double_clicked)
        return table

    def _build_payment_group_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Payment Case (Ngân hàng):"))

        self._payment_group_match_button = QPushButton("MATCH (Ngân hàng)", self)
        self._payment_group_match_button.clicked.connect(self._on_payment_group_match_clicked)
        row.addWidget(self._payment_group_match_button)

        self._payment_group_organize_button = QPushButton("ORGANIZE (Ngân hàng)", self)
        self._payment_group_organize_button.setEnabled(False)
        self._payment_group_organize_button.clicked.connect(self._on_payment_group_organize_clicked)
        row.addWidget(self._payment_group_organize_button)

        self._payment_group_export_button = QPushButton("EXPORT (Ngân hàng)", self)
        self._payment_group_export_button.setEnabled(False)
        self._payment_group_export_button.clicked.connect(self._on_payment_group_export_clicked)
        row.addWidget(self._payment_group_export_button)

        return row

    def _build_payment_group_table(self) -> QTableWidget:
        table = QTableWidget(0, len(_PAYMENT_GROUP_COLUMNS), self)
        table.setHorizontalHeaderLabels(_PAYMENT_GROUP_COLUMNS)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        return table

    # --------------------------------------------------------- điều khiển

    def _on_browse_input(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục chứa PDF")
        if folder:
            self._input_folder_edit.setText(folder)

    def _on_browse_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục xuất")
        if folder:
            self._output_folder_edit.setText(folder)

    def _on_browse_prepare_source(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục nguồn")
        if folder:
            self._prepare_source_edit.setText(folder)

    def _on_prepare_clicked(self) -> None:
        source = self._prepare_source_edit.text().strip()
        if not source or not Path(source).is_dir():
            QMessageBox.warning(self, "Thiếu thư mục", "Vui lòng chọn một thư mục nguồn hợp lệ.")
            return

        self._current_run_id = self._runs.start(source, self._output_folder_edit.text().strip() or None)
        service = PrepareDataService(self._db, self._classifier_config, self._extraction_config, self._app_settings)
        self._prepare_worker = PrepareDataWorker(service, source, self._current_run_id, parent=self)
        self._prepare_worker.progress.connect(self._on_prepare_progress)
        self._prepare_worker.finished_ok.connect(self._on_prepare_finished)
        self._prepare_worker.failed.connect(self._on_worker_failed)

        self._set_running(True)
        self._progress_bar.setValue(0)
        self._prepare_worker.start()

    def _on_prepare_progress(self, progress) -> None:
        self._progress_bar.setMaximum(max(progress.total, 1))
        self._progress_bar.setValue(progress.current)
        self._progress_bar.setFormat(f"[{progress.stage}] {progress.message}")

    def _on_prepare_finished(self, result) -> None:
        self._set_running(False)
        self._bank_transactions = result.bank_transactions
        # Tích hợp với luồng dossier META/DEBIT/VAT gốc: ALL_DATA vừa chuẩn
        # bị xong dùng thẳng được cho SCAN/MATCH/ORGANIZE/EXPORT hiện có,
        # không bắt người dùng chọn lại thư mục.
        self._input_folder_edit.setText(str(result.all_data_folder))

        scanned = result.scan_result.total_files if result.scan_result else 0
        summary = (
            f"ZIP đã quét: {result.zip_result.zip_scanned} · "
            f"PDF lấy từ ZIP: {result.zip_result.pdf_extracted} · "
            f"PDF rời: {result.loose_collect_result.copied} · "
            f"Debit Advice đã split: {len(result.split_result.split_pages)} · "
            f"Sao kê: {len(result.statement_files)} file / {len(result.bank_transactions)} giao dịch · "
            f"Đã SCAN: {scanned} chứng từ"
        )
        self._summary_label.setText(summary + " — sẵn sàng bấm MATCH (Ngân hàng) hoặc MATCH + VALIDATE.")
        self._update_button_states()

    def _on_extract_zip_clicked(self) -> None:
        source = QFileDialog.getExistingDirectory(self, "Chọn thư mục nguồn chứa file ZIP")
        if not source:
            return

        dest_path = Path(source) / "ALL_DATA"
        try:
            dest_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "Lỗi", f"Không tạo được thư mục ALL_DATA: {exc}")
            return

        self._zip_extract_worker = ZipExtractWorker(source, dest_path, parent=self)
        self._zip_extract_worker.progress.connect(self._on_scan_progress)
        self._zip_extract_worker.finished_ok.connect(self._on_zip_extract_finished)
        self._zip_extract_worker.failed.connect(self._on_worker_failed)

        self._set_running(True)
        self._progress_bar.setValue(0)
        self._zip_extract_worker.start()

    def _on_zip_extract_finished(self, result) -> None:
        self._set_running(False)
        self._input_folder_edit.setText(str(result.dest_folder))

        headline = f"Hoàn tất: {result.zip_scanned} ZIP - {result.pdf_extracted} PDF"
        if result.zip_errors:
            headline += f" - {result.zip_errors} lỗi"
        detail = (
            f"Đã quét: {result.zip_scanned} file ZIP\n"
            f"Đã lấy: {result.pdf_extracted} file PDF\n"
            f"Bỏ qua: {result.non_pdf_skipped} file không phải PDF\n"
            f"Lỗi: {result.zip_errors} file ZIP"
        )
        self._summary_label.setText(
            f"{headline} — đã đưa vào {result.dest_folder}. Sẵn sàng bấm SCAN PDF."
        )

        if result.error_messages or result.no_pdf_zip_names:
            lines = list(result.error_messages)
            lines += [f"Không tìm thấy PDF trong {name}" for name in result.no_pdf_zip_names]
            shown = lines[:15]
            message = detail + "\n\n" + "\n".join(shown)
            if len(lines) > len(shown):
                message += f"\n... và {len(lines) - len(shown)} dòng khác (xem logs/app.log)."
            QMessageBox.warning(self, "Lấy PDF từ ZIP — có cảnh báo", message)
        else:
            QMessageBox.information(self, "Lấy PDF từ ZIP", detail)
        self._update_button_states()

    def _on_scan_clicked(self) -> None:
        folder = self._input_folder_edit.text().strip()
        if not folder or not Path(folder).is_dir():
            QMessageBox.warning(self, "Thiếu thư mục", "Vui lòng chọn một thư mục PDF hợp lệ.")
            return

        self._current_run_id = self._runs.start(folder, self._output_folder_edit.text().strip() or None)
        service = ScanService(self._db, self._classifier_config, self._extraction_config, self._app_settings)
        self._scan_worker = ScanWorker(service, folder, self._current_run_id, parent=self)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.finished_ok.connect(self._on_scan_finished)
        self._scan_worker.failed.connect(self._on_worker_failed)

        self._set_running(True)
        self._progress_bar.setValue(0)
        self._scan_worker.start()

    def _on_match_clicked(self) -> None:
        if self._current_run_id is None:
            QMessageBox.warning(self, "Chưa quét", "Vui lòng chạy SCAN PDF trước.")
            return

        service = MatchService(self._db, self._app_settings)
        self._match_worker = MatchWorker(service, self._current_run_id, parent=self)
        self._match_worker.finished_ok.connect(self._on_match_finished)
        self._match_worker.failed.connect(self._on_worker_failed)

        self._set_running(True)
        self._match_worker.start()

    def _on_cancel_clicked(self) -> None:
        if self._scan_worker is not None and self._scan_worker.isRunning():
            self._scan_worker.request_cancel()
        if self._zip_extract_worker is not None and self._zip_extract_worker.isRunning():
            self._zip_extract_worker.request_cancel()
        if self._prepare_worker is not None and self._prepare_worker.isRunning():
            self._prepare_worker.request_cancel()

    def _on_scan_progress(self, progress: ScanProgress) -> None:
        self._progress_bar.setMaximum(progress.total)
        self._progress_bar.setValue(progress.current)
        self._progress_bar.setFormat(progress.message)

    def _on_scan_finished(self, result: ScanResult) -> None:
        self._set_running(False)
        self._summary_label.setText(
            f"Đã quét {result.total_files} chứng từ · {result.duplicate_files} trùng · "
            f"{result.error_files} lỗi. Bấm MATCH + VALIDATE để ghép bộ hồ sơ."
        )
        self._update_button_states()

    def _on_match_finished(self, result) -> None:
        self._set_running(False)
        self._dossier_rows = result.dossiers
        self._last_dossier_count = len(result.dossiers)
        self._populate_dossier_table(result.dossiers)
        valid = sum(1 for d in result.dossiers if status_color(d.status) == "#1e8e3e")
        self._summary_label.setText(
            f"Hồ sơ: {len(result.dossiers)} · Hợp lệ {valid} · "
            f"Chứng từ chưa ghép: {len(result.unmatched)}"
        )
        self._organize_button.setEnabled(len(result.dossiers) > 0)
        self._export_button.setEnabled(len(result.dossiers) > 0)
        self._update_button_states()

    def _on_organize_clicked(self) -> None:
        if self._current_run_id is None:
            QMessageBox.warning(self, "Chưa ghép hồ sơ", "Vui lòng chạy MATCH + VALIDATE trước.")
            return

        output_root = self._output_folder_edit.text().strip()
        if not output_root:
            output_root = QFileDialog.getExistingDirectory(self, "Chọn thư mục xuất PDF")
            if not output_root:
                return
            self._output_folder_edit.setText(output_root)

        service = OrganizeService(self._db)
        self._organize_worker = OrganizeWorker(service, self._current_run_id, output_root, parent=self)
        self._organize_worker.finished_ok.connect(self._on_organize_finished)
        self._organize_worker.failed.connect(self._on_worker_failed)

        self._set_running(True)
        self._organize_worker.start()

    def _on_organize_finished(self, result) -> None:
        self._set_running(False)
        self._update_button_states()
        message = (
            f"Đã copy {result.copied_files} file · {result.unmatched_files} chưa ghép · "
            f"{result.duplicate_files} trùng."
        )
        if result.errors:
            message += f"\n\n{len(result.errors)} lỗi:\n" + "\n".join(result.errors[:10])
            QMessageBox.warning(self, "Sắp xếp PDF — có lỗi", message)
        else:
            QMessageBox.information(self, "Đã sắp xếp PDF", message)

    def _on_export_clicked(self) -> None:
        if self._current_run_id is None:
            QMessageBox.warning(self, "Chưa ghép hồ sơ", "Vui lòng chạy MATCH + VALIDATE trước.")
            return

        # Q21: số chứng từ bắt đầu do kế toán tự nhập — app không suy đoán.
        voucher_start, ok = QInputDialog.getInt(
            self,
            "Số chứng từ bắt đầu",
            "Nhập số thứ tự bắt đầu cho Số chứng từ MISA (ví dụ 52601):",
            value=1,
            minValue=1,
            maxValue=999999,
        )
        if not ok:
            return

        excel_folder = self._output_folder_edit.text().strip() or "."
        default_name = f"{excel_folder}/ACCOUNTING_RESULT_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        output_path, _ = QFileDialog.getSaveFileName(self, "Lưu file Excel", default_name, "Excel (*.xlsx)")
        if not output_path:
            return

        service = ExportService(self._db, self._misa_config)
        self._export_worker = ExportWorker(
            service, self._current_run_id, output_path, voucher_start=voucher_start, parent=self
        )
        self._export_worker.finished_ok.connect(self._on_export_finished)
        self._export_worker.failed.connect(self._on_worker_failed)

        self._set_running(True)
        self._export_worker.start()

    def _on_export_finished(self, output_path) -> None:
        self._set_running(False)
        self._update_button_states()
        QMessageBox.information(self, "Đã xuất Excel", f"Đã lưu: {output_path}")

    def _on_payment_group_match_clicked(self) -> None:
        if self._current_run_id is None:
            QMessageBox.warning(self, "Chưa có dữ liệu", "Vui lòng bấm Chuẩn bị dữ liệu (hoặc SCAN PDF) trước.")
            return

        service = PaymentGroupService(self._db)
        self._payment_group_match_worker = PaymentGroupMatchWorker(
            service, self._current_run_id, self._bank_transactions, parent=self
        )
        self._payment_group_match_worker.finished_ok.connect(self._on_payment_group_match_finished)
        self._payment_group_match_worker.failed.connect(self._on_worker_failed)

        self._set_running(True)
        self._payment_group_match_worker.start()

    def _on_payment_group_match_finished(self, result) -> None:
        self._set_running(False)
        self._payment_groups = result.groups
        self._last_payment_group_count = len(result.groups)
        self._populate_payment_group_table(result.groups)

        matched = sum(
            1 for g in result.groups if g.status in (PaymentGroupStatus.MATCHED_HIGH, PaymentGroupStatus.MATCHED)
        )
        needs_review = sum(1 for g in result.groups if g.status is PaymentGroupStatus.NEEDS_REVIEW)
        unmatched = sum(1 for g in result.groups if g.status is PaymentGroupStatus.UNMATCHED)
        self._summary_label.setText(
            f"Payment Groups: {len(result.groups)} · Matched: {matched} · "
            f"Needs Review: {needs_review} · Unmatched: {unmatched}"
        )
        self._update_button_states()

    def _on_payment_group_organize_clicked(self) -> None:
        if not self._payment_groups:
            QMessageBox.warning(self, "Chưa ghép payment group", "Vui lòng bấm MATCH (Ngân hàng) trước.")
            return

        output_root = self._output_folder_edit.text().strip()
        if not output_root:
            output_root = QFileDialog.getExistingDirectory(self, "Chọn thư mục xuất PDF")
            if not output_root:
                return
            self._output_folder_edit.setText(output_root)

        service = PaymentGroupService(self._db)
        self._payment_group_organize_worker = PaymentGroupOrganizeWorker(
            service, self._payment_groups, output_root, parent=self
        )
        self._payment_group_organize_worker.finished_ok.connect(self._on_payment_group_organize_finished)
        self._payment_group_organize_worker.failed.connect(self._on_worker_failed)

        self._set_running(True)
        self._payment_group_organize_worker.start()

    def _on_payment_group_organize_finished(self, result) -> None:
        self._set_running(False)
        self._update_button_states()
        message = (
            f"Đã copy {result.copied_files} file · {result.generated_extracts} PDF trích xuất tự sinh "
            f"từ sao kê · {result.merged_files} bộ đã gộp."
        )
        if result.errors:
            message += f"\n\n{len(result.errors)} lỗi:\n" + "\n".join(result.errors[:10])
            QMessageBox.warning(self, "Sắp xếp Payment Group — có lỗi", message)
        else:
            QMessageBox.information(self, "Đã sắp xếp Payment Group", message)

    def _on_payment_group_export_clicked(self) -> None:
        if not self._payment_groups:
            QMessageBox.warning(self, "Chưa ghép payment group", "Vui lòng bấm MATCH (Ngân hàng) trước.")
            return

        excel_folder = self._output_folder_edit.text().strip() or "."
        default_name = f"{excel_folder}/FACEBOOK_PAYMENT_GROUPS_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        output_path, _ = QFileDialog.getSaveFileName(self, "Lưu file Excel", default_name, "Excel (*.xlsx)")
        if not output_path:
            return

        service = PaymentGroupService(self._db)
        self._payment_group_export_worker = PaymentGroupExportWorker(
            service, self._payment_groups, output_path, parent=self
        )
        self._payment_group_export_worker.finished_ok.connect(self._on_payment_group_export_finished)
        self._payment_group_export_worker.failed.connect(self._on_worker_failed)

        self._set_running(True)
        self._payment_group_export_worker.start()

    def _on_payment_group_export_finished(self, output_path) -> None:
        self._set_running(False)
        self._update_button_states()
        QMessageBox.information(self, "Đã xuất Excel", f"Đã lưu: {output_path}")

    def _on_worker_failed(self, message: str) -> None:
        self._set_running(False)
        QMessageBox.critical(self, "Lỗi xử lý", message)
        self._update_button_states()

    def _on_dossier_row_double_clicked(self, row: int, _column: int) -> None:
        if row < 0 or row >= len(self._dossier_rows):
            return
        dossier = self._dossier_rows[row]
        # Nhập trễ để tránh vòng phụ thuộc import với dossier_detail_window.
        from app.ui.dossier_detail_window import DossierDetailWindow

        detail = DossierDetailWindow(dossier, self._documents, self._dossiers, parent=self)
        if detail.exec():
            self._populate_dossier_table(self._dossier_rows)  # phản ánh review/ghi chú vừa lưu

    # --------------------------------------------------------------- vẽ

    def _populate_dossier_table(self, dossiers: list[Dossier]) -> None:
        table = self._dossier_table
        table.setRowCount(len(dossiers))
        for row_index, dossier in enumerate(dossiers):
            row = dossier_to_row(dossier)
            values = (
                row.dossier_code,
                row.reference,
                row.transaction_date,
                row.meta_mark,
                row.debit_mark,
                row.vat_mark,
                row.status_text,
                "✔" if row.reviewed else "",
            )
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                if col_index == 6:
                    item.setForeground(Qt.GlobalColor.black)
                    item.setBackground(_qcolor(row.status_color))
                table.setItem(row_index, col_index, item)

    def _populate_payment_group_table(self, groups: list[PaymentCase]) -> None:
        table = self._payment_group_table
        table.setRowCount(len(groups))
        for row_index, case in enumerate(groups):
            row = payment_group_to_row(case)
            # Đúng thứ tự _PAYMENT_GROUP_COLUMNS: Reference|Bank|Meta|Debit|Fee|VAT|Trạng thái
            values = (
                row.reference,
                row.bank,
                row.meta_mark,
                row.debit_mark,
                row.fee_count,
                row.vat_mark,
                row.status_text,
            )
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                if col_index == 6:
                    item.setForeground(Qt.GlobalColor.black)
                    item.setBackground(_qcolor(row.status_color))
                elif col_index == 1 and row.has_warning:
                    # Bank lệch expected_bank (thẻ Meta Bill) — cảnh báo màu
                    # vàng, KHÔNG tự loại liên kết, chỉ để người dùng thấy.
                    item.setForeground(Qt.GlobalColor.black)
                    item.setBackground(_qcolor("#f9ab00"))
                table.setItem(row_index, col_index, item)

    def _set_running(self, running: bool) -> None:
        self._scan_button.setEnabled(not running)
        self._match_button.setEnabled(not running)
        self._organize_button.setEnabled(not running and self._last_dossier_count > 0)
        self._export_button.setEnabled(not running and self._last_dossier_count > 0)
        self._extract_zip_button.setEnabled(not running)
        self._prepare_button.setEnabled(not running)
        self._payment_group_match_button.setEnabled(not running)
        self._payment_group_organize_button.setEnabled(not running and self._last_payment_group_count > 0)
        self._payment_group_export_button.setEnabled(not running and self._last_payment_group_count > 0)
        # Cancel chỉ có ý nghĩa hợp tác cho SCAN, LẤY PDF TỪ ZIP và CHUẨN BỊ
        # DỮ LIỆU (xem app/ui/workers.py) — các bước MATCH/ORGANIZE/EXPORT
        # (cả luồng dossier lẫn luồng Facebook payment group) không hỗ trợ
        # huỷ giữa chừng, chạy ngắn và ghi file một lần nên cố ý không cho
        # bấm Cancel trong lúc chúng chạy.
        self._cancel_button.setEnabled(
            running
            and (
                (self._scan_worker is not None and self._scan_worker.isRunning())
                or (self._zip_extract_worker is not None and self._zip_extract_worker.isRunning())
                or (self._prepare_worker is not None and self._prepare_worker.isRunning())
            )
        )

    def _update_button_states(self) -> None:
        has_run = self._current_run_id is not None
        self._match_button.setEnabled(has_run)
        self._organize_button.setEnabled(self._last_dossier_count > 0)
        self._export_button.setEnabled(self._last_dossier_count > 0)
        self._payment_group_match_button.setEnabled(has_run)
        self._payment_group_organize_button.setEnabled(self._last_payment_group_count > 0)
        self._payment_group_export_button.setEnabled(self._last_payment_group_count > 0)


def _qcolor(hex_color: str):
    from PySide6.QtGui import QColor

    return QColor(hex_color)
