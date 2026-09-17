"""Kho cấu hình dạng key-value trong SQLite — dùng cho tuỳ chọn người dùng
thay đổi qua màn hình Settings (khác với ``config/*.yaml`` là cấu hình
triển khai ban đầu).
"""

from __future__ import annotations

from datetime import datetime

from app.database.database import Database

__all__ = ["SettingsRepository"]


class SettingsRepository:
    """Đọc/ghi cặp key-value trong bảng ``settings``.

    Args:
        db: Kết nối ``Database`` đã mở sẵn.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, key: str, default: str | None = None) -> str | None:
        row = self._db.connection.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row is not None else default

    def set(self, key: str, value: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, datetime.now().isoformat()),
            )

    def all(self) -> dict[str, str]:
        return {
            row["key"]: row["value"] for row in self._db.connection.execute("SELECT key, value FROM settings")
        }

    def delete(self, key: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))
