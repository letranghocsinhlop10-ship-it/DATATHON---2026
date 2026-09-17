"""Lưu/đọc ``Dossier`` vào SQLite.

Ba cột ``*_document_id`` phục vụ truy vấn nhanh; bảng ``dossier_documents``
giữ TOÀN BỘ quan hệ kể cả bản trùng (2 Meta cùng reference vẫn được giữ lại
cả hai, không mất dữ liệu — xem §17 Phase 1). ``dossier.issues`` được lưu
sang bảng ``errors`` để sheet ``CHECK_ERROR`` đọc trực tiếp từ DB.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Any

from app.database.database import Database
from app.models.dossier import Dossier, DossierIssue
from app.models.enums import DossierStatus, MatchSource, Severity

__all__ = ["DossierRepository"]

_ISO_DATE = "%Y-%m-%d"


class DossierRepository:
    """Repository CRUD tối thiểu cho ``Dossier``.

    Args:
        db: Kết nối ``Database`` đã mở sẵn.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, dossier: Dossier, *, run_id: int | None = None) -> int:
        """Lưu một dossier — insert nếu mới, update nếu đã có ``dossier_id``.

        Ghi đè toàn bộ quan hệ ``dossier_documents`` và ``errors`` liên quan
        theo trạng thái hiện tại của ``dossier`` (idempotent: gọi lại nhiều
        lần trên cùng dữ liệu cho cùng kết quả).

        Args:
            dossier: Dossier cần lưu.
            run_id: Lô xử lý sở hữu dossier này.

        Returns:
            ``dossier_id`` sau khi lưu.
        """
        now = datetime.now().isoformat()
        with self._db.transaction() as conn:
            if dossier.dossier_id is None:
                dossier.dossier_id = self._insert(conn, dossier, run_id, now)
            else:
                self._update(conn, dossier, run_id, now)
            self._save_document_links(conn, dossier)
            self._save_issues(conn, dossier, run_id)
        return dossier.dossier_id

    def get(self, dossier_id: int) -> Dossier | None:
        row = self._db.connection.execute(
            "SELECT * FROM dossiers WHERE id = ?", (dossier_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dossier(row)

    def list_by_run(self, run_id: int) -> list[Dossier]:
        rows = self._db.connection.execute(
            "SELECT * FROM dossiers WHERE run_id = ? ORDER BY dossier_code", (run_id,)
        ).fetchall()
        return [self._row_to_dossier(row) for row in rows]

    def list_by_status(self, status: DossierStatus, *, run_id: int | None = None) -> list[Dossier]:
        if run_id is None:
            rows = self._db.connection.execute(
                "SELECT * FROM dossiers WHERE status = ? ORDER BY dossier_code", (status.value,)
            ).fetchall()
        else:
            rows = self._db.connection.execute(
                "SELECT * FROM dossiers WHERE run_id = ? AND status = ? ORDER BY dossier_code",
                (run_id, status.value),
            ).fetchall()
        return [self._row_to_dossier(row) for row in rows]

    def document_ids_of(self, dossier_id: int) -> list[tuple[int, str]]:
        """Toàn bộ ``(document_id, role)`` thuộc dossier — kể cả bản trùng."""
        rows = self._db.connection.execute(
            "SELECT document_id, role FROM dossier_documents WHERE dossier_id = ?",
            (dossier_id,),
        ).fetchall()
        return [(row["document_id"], row["role"]) for row in rows]

    def count(self) -> int:
        return self._db.connection.execute("SELECT COUNT(*) FROM dossiers").fetchone()[0]

    # -------------------------------------------------------------- nội bộ

    @staticmethod
    def _insert(conn: sqlite3.Connection, dossier: Dossier, run_id: int | None, now: str) -> int:
        cursor = conn.execute(
            """
            INSERT INTO dossiers (
                run_id, dossier_code, reference,
                meta_document_id, debit_document_id, vat_document_id,
                meta_count, debit_count, vat_count,
                card_last4, transaction_date,
                status, match_source, reviewed, reviewed_by, reviewed_at,
                folder_path, notes, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            DossierRepository._values(dossier, run_id, now, created_at=now),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _update(conn: sqlite3.Connection, dossier: Dossier, run_id: int | None, now: str) -> None:
        conn.execute(
            """
            UPDATE dossiers SET
                run_id=?, dossier_code=?, reference=?,
                meta_document_id=?, debit_document_id=?, vat_document_id=?,
                meta_count=?, debit_count=?, vat_count=?,
                card_last4=?, transaction_date=?,
                status=?, match_source=?, reviewed=?, reviewed_by=?, reviewed_at=?,
                folder_path=?, notes=?, updated_at=?
            WHERE id=?
            """,
            (
                run_id,
                dossier.dossier_code,
                dossier.reference,
                dossier.meta_document_id,
                dossier.debit_document_id,
                dossier.vat_document_id,
                dossier.meta_count,
                dossier.debit_count,
                dossier.vat_count,
                dossier.card_last4,
                dossier.transaction_date.strftime(_ISO_DATE) if dossier.transaction_date else None,
                dossier.status.value,
                dossier.match_source.value,
                1 if dossier.reviewed else 0,
                dossier.reviewed_by,
                dossier.reviewed_at.isoformat() if dossier.reviewed_at else None,
                dossier.folder_path,
                dossier.notes,
                now,
                dossier.dossier_id,
            ),
        )

    @staticmethod
    def _values(dossier: Dossier, run_id: int | None, now: str, *, created_at: str) -> tuple[Any, ...]:
        return (
            run_id,
            dossier.dossier_code,
            dossier.reference,
            dossier.meta_document_id,
            dossier.debit_document_id,
            dossier.vat_document_id,
            dossier.meta_count,
            dossier.debit_count,
            dossier.vat_count,
            dossier.card_last4,
            dossier.transaction_date.strftime(_ISO_DATE) if dossier.transaction_date else None,
            dossier.status.value,
            dossier.match_source.value,
            1 if dossier.reviewed else 0,
            dossier.reviewed_by,
            dossier.reviewed_at.isoformat() if dossier.reviewed_at else None,
            dossier.folder_path,
            dossier.notes,
            created_at,
            now,
        )

    @staticmethod
    def _save_document_links(conn: sqlite3.Connection, dossier: Dossier) -> None:
        conn.execute("DELETE FROM dossier_documents WHERE dossier_id = ?", (dossier.dossier_id,))
        now = datetime.now().isoformat()
        primary_roles = {
            dossier.meta_document_id: "META",
            dossier.debit_document_id: "DEBIT",
            dossier.vat_document_id: "VAT",
        }
        seen: set[int] = set()
        for document_id in dossier.extra_documents:
            if document_id is None or document_id in seen:
                continue
            seen.add(document_id)
            role = primary_roles.get(document_id, "EXTRA")
            conn.execute(
                "INSERT INTO dossier_documents (dossier_id, document_id, role, linked_at) VALUES (?,?,?,?)",
                (dossier.dossier_id, document_id, role, now),
            )
        # Đề phòng primary không nằm trong extra_documents (ví dụ dossier dựng
        # thủ công không qua DossierBuilder).
        for document_id, role in primary_roles.items():
            if document_id is not None and document_id not in seen:
                conn.execute(
                    "INSERT INTO dossier_documents (dossier_id, document_id, role, linked_at) VALUES (?,?,?,?)",
                    (dossier.dossier_id, document_id, role, now),
                )

    @staticmethod
    def _save_issues(conn: sqlite3.Connection, dossier: Dossier, run_id: int | None) -> None:
        conn.execute("DELETE FROM errors WHERE dossier_id = ?", (dossier.dossier_id,))
        now = datetime.now().isoformat()
        for issue in dossier.issues:
            conn.execute(
                """
                INSERT INTO errors (
                    run_id, document_id, dossier_id, severity, error_code,
                    description, suggested_action, created_at
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    issue.document_id,
                    dossier.dossier_id,
                    issue.severity.value,
                    issue.code,
                    issue.description,
                    issue.suggested_action,
                    now,
                ),
            )

    def _row_to_dossier(self, row: sqlite3.Row) -> Dossier:
        issues = [
            DossierIssue(
                code=err["error_code"],
                severity=Severity(err["severity"]),
                description=err["description"],
                document_id=err["document_id"],
                suggested_action=err["suggested_action"],
            )
            for err in self._db.connection.execute(
                "SELECT * FROM errors WHERE dossier_id = ? ORDER BY id", (row["id"],)
            )
        ]
        extras = tuple(
            r["document_id"]
            for r in self._db.connection.execute(
                "SELECT document_id FROM dossier_documents WHERE dossier_id = ? ORDER BY document_id",
                (row["id"],),
            )
        )
        transaction_date = None
        if row["transaction_date"]:
            transaction_date = datetime.strptime(row["transaction_date"], _ISO_DATE).date()

        return Dossier(
            dossier_id=row["id"],
            dossier_code=row["dossier_code"],
            reference=row["reference"],
            meta_document_id=row["meta_document_id"],
            debit_document_id=row["debit_document_id"],
            vat_document_id=row["vat_document_id"],
            meta_count=row["meta_count"],
            debit_count=row["debit_count"],
            vat_count=row["vat_count"],
            extra_documents=extras,
            card_last4=row["card_last4"],
            transaction_date=transaction_date,
            status=DossierStatus(row["status"]),
            match_source=MatchSource(row["match_source"]),
            issues=issues,
            reviewed=bool(row["reviewed"]),
            reviewed_by=row["reviewed_by"],
            reviewed_at=datetime.fromisoformat(row["reviewed_at"]) if row["reviewed_at"] else None,
            folder_path=row["folder_path"],
            notes=row["notes"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
