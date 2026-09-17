"""Điều phối bước EXPORT EXCEL: dossier/document đã lưu -> file ``.xlsx``."""

from __future__ import annotations

import logging
from pathlib import Path

from app.config_loader import MisaMappingConfig
from app.database.database import Database
from app.database.document_repository import DocumentRepository
from app.database.dossier_repository import DossierRepository
from app.exporters.excel_exporter import ExcelExporter, ExportOptions

__all__ = ["ExportService"]

logger = logging.getLogger(__name__)


class ExportService:
    """Xuất Excel cho toàn bộ dossier/document của một lô đã ghép.

    Args:
        db: Kết nối database đã mở.
        misa_config: Cấu hình mapping MISA đã nạp.
    """

    def __init__(self, db: Database, misa_config: MisaMappingConfig) -> None:
        self._dossiers = DossierRepository(db)
        self._documents = DocumentRepository(db)
        self._exporter = ExcelExporter(misa_config)

    def export_run(
        self,
        run_id: int,
        output_path: Path | str,
        *,
        voucher_start: int,
        require_reviewed_for_misa: bool = False,
    ) -> Path:
        """Xuất file Excel cho một lô đã quét + ghép.

        Args:
            run_id: Lô xử lý.
            output_path: Đường dẫn file ``.xlsx`` đích.
            voucher_start: Số thứ tự bắt đầu cho Số chứng từ MISA (Q21).
            require_reviewed_for_misa: Chỉ đưa dossier đã review vào sheet MISA.

        Returns:
            Đường dẫn file đã ghi.
        """
        dossiers = self._dossiers.list_by_run(run_id)
        documents = {d.document_id: d for d in self._documents.list_by_run(run_id)}
        options = ExportOptions(voucher_start=voucher_start, require_reviewed_for_misa=require_reviewed_for_misa)
        result = self._exporter.export(dossiers, documents, output_path, options=options)
        logger.info("Đã xuất Excel cho lô %d: %s", run_id, result)
        return result
