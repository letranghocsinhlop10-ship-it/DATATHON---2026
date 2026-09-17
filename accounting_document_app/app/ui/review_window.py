"""Cửa sổ Review — chứng từ chưa ghép được, theo wireframe §8.3 Phase 1.

Hai bảng: bên trái là chứng từ chưa có khoá (kèm lý do không ghép được),
bên phải là gợi ý ghép tay từ ``CandidateSuggester``. GHÉP TAY LUÔN LÀ HÀNH
ĐỘNG CỦA NGƯỜI DÙNG — không có đường code nào ở đây tự tạo liên kết; bấm
"Ghép tay" chỉ tạo dossier mới với ``match_source=MANUAL`` sau khi người
dùng xác nhận.
"""

from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.database.dossier_repository import DossierRepository
from app.matching.candidate_suggester import CandidateSuggester, MatchCandidate
from app.models.document import Document
from app.models.dossier import Dossier
from app.models.enums import DossierStatus, MatchSource

__all__ = ["ReviewWindow"]

logger = logging.getLogger(__name__)

#: Lý do KHÔNG ghép được, hiển thị cho kế toán — không suy đoán, chỉ mô tả.
_UNMATCHED_REASONS = {
    "META_INVOICE": "REFERENCE_NOT_FOUND — không đọc được Số tham chiếu",
    "VPBANK_DEBIT_NOTE": "REFERENCE_NOT_FOUND — không đọc được reference trong diễn giải",
    "VPBANK_VAT_INVOICE": "REFERENCE_NOT_FOUND — không đọc được reference trong nội dung thanh toán",
    "UNKNOWN": "UNKNOWN_TYPE — không phân loại được chứng từ",
}


class ReviewWindow(QWidget):
    """Màn hình review chứng từ chưa ghép được.

    Args:
        unmatched: Chứng từ không thuộc dossier nào.
        dossier_repo: Repository để lưu dossier ghép tay.
        next_dossier_index: Số thứ tự tiếp theo để đặt mã hồ sơ ghép tay
            (tránh trùng mã với các dossier tự động đã dựng).
        parent: Widget cha.
    """

    def __init__(
        self,
        unmatched: list[Document],
        dossier_repo: DossierRepository,
        *,
        next_dossier_index: int = 1,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._unmatched = list(unmatched)
        self._dossier_repo = dossier_repo
        self._next_index = next_dossier_index
        self._candidates: list[MatchCandidate] = []
        self._by_id = {d.document_id: d for d in self._unmatched if d.document_id is not None}

        self.setWindowTitle("Chứng từ chưa ghép")
        self.resize(900, 500)
        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Chứng từ chưa ghép được: {len(self._unmatched)}"))

        tables_row = QHBoxLayout()

        left = QVBoxLayout()
        left.addWidget(QLabel("Chứng từ chưa ghép"))
        self._unmatched_table = QTableWidget(0, 3, self)
        self._unmatched_table.setHorizontalHeaderLabels(("File", "Loại", "Lý do"))
        self._unmatched_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._unmatched_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._unmatched_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._unmatched_table.itemSelectionChanged.connect(self._on_selection_changed)
        left.addWidget(self._unmatched_table)
        tables_row.addLayout(left)

        right = QVBoxLayout()
        right.addWidget(QLabel("Gợi ý ghép tay (CHƯA GHÉP — cần xác nhận)"))
        self._candidate_table = QTableWidget(0, 3, self)
        self._candidate_table.setHorizontalHeaderLabels(("Chứng từ gợi ý", "Tín hiệu khớp", "Điểm"))
        self._candidate_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._candidate_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._candidate_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        right.addWidget(self._candidate_table)

        self._link_button = QPushButton("→ Ghép tay", self)
        self._link_button.setEnabled(False)
        self._link_button.clicked.connect(self._on_link_clicked)
        right.addWidget(self._link_button)
        tables_row.addLayout(right)

        layout.addLayout(tables_row)

        layout.addWidget(QLabel("Nội dung gốc của chứng từ đang chọn (để đối chiếu số liệu):"))
        self._raw_text_view = QPlainTextEdit(self)
        self._raw_text_view.setReadOnly(True)
        layout.addWidget(self._raw_text_view)

    def _refresh(self) -> None:
        self._unmatched_table.setRowCount(len(self._unmatched))
        for row, doc in enumerate(self._unmatched):
            reason = _UNMATCHED_REASONS.get(doc.document_type.value, "Không xác định được lý do")
            for col, value in enumerate((doc.file_name, doc.document_type.value, reason)):
                self._unmatched_table.setItem(row, col, QTableWidgetItem(value))

        self._candidates = CandidateSuggester().suggest(self._unmatched)
        self._candidate_table.setRowCount(len(self._candidates))
        for row, candidate in enumerate(self._candidates):
            target = self._by_id.get(candidate.target_document_id)
            target_name = target.file_name if target else str(candidate.target_document_id)
            self._candidate_table.setItem(row, 0, QTableWidgetItem(target_name))
            self._candidate_table.setItem(row, 1, QTableWidgetItem(", ".join(candidate.signals)))
            self._candidate_table.setItem(row, 2, QTableWidgetItem(str(candidate.score)))

    def _on_selection_changed(self) -> None:
        rows = self._unmatched_table.selectionModel().selectedRows()
        if not rows:
            self._raw_text_view.setPlainText("")
            self._link_button.setEnabled(False)
            return
        doc = self._unmatched[rows[0].row()]
        self._raw_text_view.setPlainText(doc.raw_text)
        # Chỉ cho ghép khi có gợi ý liên quan tới đúng chứng từ đang chọn.
        relevant = [c for c in self._candidates if c.source_document_id == doc.document_id]
        self._link_button.setEnabled(bool(relevant) and bool(self._candidate_table.selectionModel().selectedRows()))

    def _on_link_clicked(self) -> None:
        source_rows = self._unmatched_table.selectionModel().selectedRows()
        candidate_rows = self._candidate_table.selectionModel().selectedRows()
        if not source_rows or not candidate_rows:
            return

        source_doc = self._unmatched[source_rows[0].row()]
        candidate = self._candidates[candidate_rows[0].row()]
        target_doc = self._by_id.get(candidate.target_document_id)
        if target_doc is None:
            return

        confirm = QMessageBox.question(
            self,
            "Xác nhận ghép tay",
            f"Ghép {source_doc.file_name} với {target_doc.file_name}?\n\n"
            f"Tín hiệu: {', '.join(candidate.signals)}\n\n"
            "Đây là liên kết THỦ CÔNG do bạn xác nhận, không phải hệ thống tự động ghép.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._create_manual_dossier(source_doc, target_doc)

    def _create_manual_dossier(self, a: Document, b: Document) -> None:
        by_role = {a.document_type.value: a, b.document_type.value: b}
        dossier = Dossier(
            dossier_code=f"HS{self._next_index:06d}",
            reference=None,  # ghép tay: reference hai bên không khớp tự động
            meta_document_id=by_role.get("META_INVOICE", None) and by_role["META_INVOICE"].document_id,
            debit_document_id=by_role.get("VPBANK_DEBIT_NOTE", None) and by_role["VPBANK_DEBIT_NOTE"].document_id,
            vat_document_id=by_role.get("VPBANK_VAT_INVOICE", None) and by_role["VPBANK_VAT_INVOICE"].document_id,
            meta_count=1 if "META_INVOICE" in by_role else 0,
            debit_count=1 if "VPBANK_DEBIT_NOTE" in by_role else 0,
            vat_count=1 if "VPBANK_VAT_INVOICE" in by_role else 0,
            extra_documents=(a.document_id, b.document_id),
            status=DossierStatus.NEEDS_REVIEW,  # ghép tay KHÔNG BAO GIỜ tự thành VALID
            match_source=MatchSource.MANUAL,
            notes="Ghép tay từ màn hình Review — cần kế toán xác nhận lại reference.",
        )
        self._dossier_repo.save(dossier)
        self._next_index += 1

        for doc in (a, b):
            self._unmatched.remove(doc)
            self._by_id.pop(doc.document_id, None)
        self._refresh()

        QMessageBox.information(
            self, "Đã ghép", f"Đã tạo {dossier.dossier_code} (NEEDS_REVIEW) — vào Hồ sơ để kiểm tra lại."
        )
