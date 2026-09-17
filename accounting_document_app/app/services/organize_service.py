"""Điều phối bước ORGANIZE PDF: copy PDF gốc vào cây thư mục theo hồ sơ."""

from __future__ import annotations

import logging
from pathlib import Path

from app.database.database import Database
from app.database.document_repository import DocumentRepository
from app.database.dossier_repository import DossierRepository
from app.exporters.pdf_organizer import OrganizeResult, PdfOrganizer

__all__ = ["OrganizeService"]

logger = logging.getLogger(__name__)


class OrganizeService:
    """Sắp xếp PDF gốc cho toàn bộ dossier của một lô đã ghép.

    Args:
        db: Kết nối database đã mở.
    """

    def __init__(self, db: Database) -> None:
        self._dossiers = DossierRepository(db)
        self._documents = DocumentRepository(db)

    def organize_run(self, run_id: int, output_root: Path | str) -> OrganizeResult:
        """Copy PDF gốc vào ``output_root`` theo cấu trúc §10 Phase 1.

        Args:
            run_id: Lô xử lý.
            output_root: Thư mục gốc để tạo cây OUTPUT.

        Returns:
            ``OrganizeResult`` — thống kê + đường dẫn từng thư mục hồ sơ.
        """
        dossiers = self._dossiers.list_by_run(run_id)
        documents = self._documents.list_by_run(run_id)

        result = PdfOrganizer(output_root).organize(dossiers, documents)

        for dossier in dossiers:
            if dossier.folder_path:
                self._dossiers.save(dossier, run_id=run_id)  # lưu lại folder_path mới cập nhật

        logger.info(
            "Đã sắp xếp lô %d: %d file copy, %d chưa ghép, %d trùng, %d lỗi",
            run_id,
            result.copied_files,
            result.unmatched_files,
            result.duplicate_files,
            len(result.errors),
        )
        return result
