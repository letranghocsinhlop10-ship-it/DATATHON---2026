"""Theo dõi vòng đời một lô xử lý (``processing_runs``).

Mỗi lần người dùng bấm SCAN, một bản ghi mới được tạo để: (1) gắn
``run_id`` lên toàn bộ document/dossier sinh ra trong lô đó, (2) lưu lại
``input_folder``/``output_folder`` đã dùng, phục vụ truy vết sau này.
"""

from __future__ import annotations

from datetime import datetime

from app.database.database import Database

__all__ = ["ProcessingRunRepository"]

APP_VERSION = "0.1.0-phase4"


class ProcessingRunRepository:
    """CRUD tối thiểu cho bảng ``processing_runs``.

    Args:
        db: Kết nối ``Database`` đã mở sẵn.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def start(self, input_folder: str, output_folder: str | None = None) -> int:
        """Tạo một lô mới, trạng thái ``RUNNING``.

        Returns:
            ``run_id`` vừa tạo.
        """
        with self._db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO processing_runs (started_at, input_folder, output_folder, app_version, status)
                VALUES (?, ?, ?, ?, 'RUNNING')
                """,
                (datetime.now().isoformat(), input_folder, output_folder, APP_VERSION),
            )
            return int(cursor.lastrowid)

    def finish(
        self,
        run_id: int,
        *,
        status: str = "COMPLETED",
        total_files: int = 0,
        processed_files: int = 0,
        error_files: int = 0,
    ) -> None:
        """Đóng một lô — ghi thời điểm kết thúc và số liệu tổng hợp."""
        with self._db.transaction() as conn:
            conn.execute(
                """
                UPDATE processing_runs
                SET finished_at = ?, status = ?, total_files = ?, processed_files = ?, error_files = ?
                WHERE id = ?
                """,
                (datetime.now().isoformat(), status, total_files, processed_files, error_files, run_id),
            )

    def get(self, run_id: int) -> dict | None:
        row = self._db.connection.execute(
            "SELECT * FROM processing_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def latest(self) -> dict | None:
        row = self._db.connection.execute(
            "SELECT * FROM processing_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row is not None else None
