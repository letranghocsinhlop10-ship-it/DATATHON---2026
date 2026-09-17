"""Sắp xếp PDF gốc thành cây thư mục theo hồ sơ — theo §21/§10 Phase 1.

Nguyên tắc bất di bất dịch: CHỈ ``shutil.copy2``. KHÔNG sửa, KHÔNG xoá,
KHÔNG di chuyển file gốc — file gốc trong thư mục người dùng chọn không bao
giờ bị đụng tới.

Cấu trúc xuất::

    OUTPUT/
        HS000001_ABCD1234EF/
            01_META_INVOICE.pdf
            02_VPBANK_DEBIT_NOTE.pdf
            03_VPBANK_VAT_INVOICE.pdf
            _manifest.txt
        NEEDS_REVIEW/
            HS000002_XYZ987QWE/
                01_META_INVOICE.pdf
                _MISSING_02_VPBANK_DEBIT_NOTE.txt
                03_VPBANK_VAT_INVOICE.pdf
        UNMATCHED/
            REFERENCE_NOT_FOUND/file088.pdf
            UNKNOWN_TYPE/abc123.pdf
        DUPLICATES/
            <sha256-prefix>/file_a.pdf
            <sha256-prefix>/file_b.pdf
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.models.document import Document
from app.models.dossier import Dossier
from app.models.enums import DocumentType, DossierStatus, ProcessingStatus
from app.utils.file_utils import copy_preserving, safe_folder_name

__all__ = ["OrganizeResult", "PdfOrganizer"]

logger = logging.getLogger(__name__)

_ROLE_LABELS = {
    DocumentType.META_INVOICE: "META_INVOICE",
    DocumentType.VPBANK_DEBIT_NOTE: "VPBANK_DEBIT_NOTE",
    DocumentType.VPBANK_VAT_INVOICE: "VPBANK_VAT_INVOICE",
}
_ROLE_ORDER = {
    DocumentType.META_INVOICE: 1,
    DocumentType.VPBANK_DEBIT_NOTE: 2,
    DocumentType.VPBANK_VAT_INVOICE: 3,
}


@dataclass
class OrganizeResult:
    """Kết quả một lượt sắp xếp file."""

    dossier_folders: dict[str, Path] = field(default_factory=dict)
    copied_files: int = 0
    unmatched_files: int = 0
    duplicate_files: int = 0
    errors: list[str] = field(default_factory=list)


class PdfOrganizer:
    """Copy PDF gốc vào thư mục OUTPUT theo hồ sơ đã ghép.

    Args:
        output_root: Thư mục gốc để tạo cây OUTPUT.
    """

    def __init__(self, output_root: Path | str) -> None:
        self._output_root = Path(output_root)

    def organize(self, dossiers: list[Dossier], all_documents: list[Document]) -> OrganizeResult:
        """Sắp xếp toàn bộ chứng từ của một lô đã ghép.

        Args:
            dossiers: Dossier đã validate (``dossier.folder_path`` được cập
                nhật tại chỗ trỏ về thư mục vừa tạo).
            all_documents: TOÀN BỘ chứng từ của lô (kể cả chưa ghép, trùng),
                để xác định phần UNMATCHED/DUPLICATES.

        Returns:
            ``OrganizeResult`` — thống kê để hiển thị cho người dùng.
        """
        result = OrganizeResult()
        assigned_ids: set[int] = set()

        for dossier in dossiers:
            documents_by_role = self._group_dossier_documents(dossier, all_documents)
            assigned_ids.update(
                doc.document_id
                for docs in documents_by_role.values()
                for doc in docs
                if doc.document_id is not None
            )
            self._organize_one_dossier(dossier, documents_by_role, result)

        for document in all_documents:
            if document.processing_status is ProcessingStatus.DUPLICATE_FILE:
                self._copy_duplicate(document, result)
            elif document.document_id not in assigned_ids:
                self._copy_unmatched(document, result)

        return result

    # ------------------------------------------------------------- dossier

    @staticmethod
    def _group_dossier_documents(
        dossier: Dossier, all_documents: list[Document]
    ) -> dict[DocumentType, list[Document]]:
        by_id = {d.document_id: d for d in all_documents if d.document_id is not None}
        groups: dict[DocumentType, list[Document]] = {t: [] for t in _ROLE_LABELS}
        for document_id in dossier.extra_documents:
            document = by_id.get(document_id)
            if document is not None and document.document_type in groups:
                groups[document.document_type].append(document)
        return groups

    def _organize_one_dossier(
        self,
        dossier: Dossier,
        documents_by_role: dict[DocumentType, list[Document]],
        result: OrganizeResult,
    ) -> None:
        folder_name = f"{dossier.dossier_code}_{safe_folder_name(dossier.reference or 'NOREF')}"
        base = self._output_root if dossier.status is DossierStatus.VALID else self._output_root / "NEEDS_REVIEW"
        target_dir = base / folder_name

        manifest_lines = [
            f"Hồ sơ: {dossier.dossier_code}",
            f"Reference: {dossier.reference or '(không có)'}",
            f"Trạng thái: {dossier.status.value}",
            f"Xuất lúc: {datetime.now().isoformat(timespec='seconds')}",
            "",
        ]

        for document_type, label in _ROLE_LABELS.items():
            prefix = _ROLE_ORDER[document_type]
            docs = documents_by_role[document_type]

            if not docs:
                note_path = target_dir / f"_MISSING_{prefix:02d}_{label}.txt"
                self._write_text(note_path, f"Không tìm thấy chứng từ {label} cho hồ sơ {dossier.dossier_code}.")
                continue

            if len(docs) > 1:
                note_path = target_dir / f"_DUPLICATE_{prefix:02d}_{label}.txt"
                listing = "\n".join(f"- {d.file_name} ({d.file_path})" for d in docs)
                self._write_text(
                    note_path,
                    f"Có {len(docs)} chứng từ {label} cùng reference — cần người dùng chọn bản chính:\n{listing}",
                )
                for index, document in enumerate(docs, start=1):
                    suffix = chr(ord("a") + index - 1)
                    dest = target_dir / f"{prefix:02d}_{label}_{suffix}.pdf"
                    self._copy(document, dest, result, manifest_lines)
                continue

            dest = target_dir / f"{prefix:02d}_{label}.pdf"
            self._copy(docs[0], dest, result, manifest_lines)

        if any(documents_by_role.values()):
            self._write_text(target_dir / "_manifest.txt", "\n".join(manifest_lines))
            dossier.folder_path = str(target_dir)
            result.dossier_folders[dossier.dossier_code] = target_dir

    # --------------------------------------------------------- unmatched/dup

    def _copy_unmatched(self, document: Document, result: OrganizeResult) -> None:
        reason = self._unmatched_reason(document)
        dest = self._output_root / "UNMATCHED" / reason / document.file_name
        self._copy(document, dest, result, None)
        result.unmatched_files += 1

    @staticmethod
    def _unmatched_reason(document: Document) -> str:
        if document.document_type is DocumentType.UNKNOWN:
            return "UNKNOWN_TYPE"
        if document.processing_status is ProcessingStatus.NEEDS_OCR:
            return "NEEDS_OCR"
        if document.processing_status is ProcessingStatus.ERROR:
            return "ERROR"
        if document.match_key is None:
            return "REFERENCE_NOT_FOUND"
        return "OTHER"

    def _copy_duplicate(self, document: Document, result: OrganizeResult) -> None:
        hash_prefix = document.file_hash[:16] if document.file_hash else "unknown"
        dest = self._output_root / "DUPLICATES" / hash_prefix / document.file_name
        self._copy(document, dest, result, None)
        result.duplicate_files += 1

    # -------------------------------------------------------------- helpers

    def _copy(
        self,
        document: Document,
        dest: Path,
        result: OrganizeResult,
        manifest_lines: list[str] | None,
    ) -> None:
        try:
            written = copy_preserving(document.file_path, dest)
            result.copied_files += 1
            if manifest_lines is not None:
                manifest_lines.append(
                    f"{written.name}  <-  {document.file_name}  (gốc: {document.file_path}, "
                    f"SHA256: {document.file_hash})"
                )
        except OSError as exc:
            message = f"Không copy được {document.file_path} -> {dest}: {exc}"
            logger.error(message)
            result.errors.append(message)

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
