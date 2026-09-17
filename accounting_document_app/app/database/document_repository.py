"""Lưu/đọc ``Document`` vào SQLite.

Mỗi trường trong ``FieldSet`` là một dòng trong ``document_fields``, giữ
nguyên toàn bộ bằng chứng nguồn (``raw_snippet``, ``page_number``,
``rule_id``...) — đây là cơ chế "truy vết được" ở tầng lưu trữ.

Tiền lưu dạng chuỗi thập phân của ``Decimal`` (cột ``value_type='decimal'``),
KHÔNG BAO GIỜ ép sang ``REAL`` của SQLite — tránh sai số dấu phẩy động.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.database.database import Database
from app.models.document import Document
from app.models.enums import DocumentType, FieldMethod, ProcessingStatus, TextSource
from app.models.extracted_field import ExtractedField, FieldSet

__all__ = ["DocumentRepository"]

_ISO = "%Y-%m-%d"


def _serialize_value(value: Any) -> tuple[str | None, str]:
    """Chuyển giá trị Python thành ``(value_text, value_type)`` để lưu DB."""
    if value is None:
        return None, "text"
    if isinstance(value, Decimal):
        return str(value), "decimal"
    if isinstance(value, date):
        return value.strftime(_ISO), "date"
    if isinstance(value, bool):
        return ("1" if value else "0"), "bool"
    return str(value), "text"


def _deserialize_value(value_text: str | None, value_type: str) -> Any:
    """Chiều ngược của ``_serialize_value``."""
    if value_text is None:
        return None
    if value_type == "decimal":
        return Decimal(value_text)
    if value_type == "date":
        return datetime.strptime(value_text, _ISO).date()
    if value_type == "bool":
        return value_text == "1"
    return value_text


class DocumentRepository:
    """Repository CRUD tối thiểu cho ``Document``.

    Args:
        db: Kết nối ``Database`` đã mở sẵn.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, document: Document, *, run_id: int | None = None) -> int:
        """Lưu một chứng từ (insert nếu mới, update nếu đã có ``document_id``).

        Args:
            document: Chứng từ cần lưu. ``document.document_id`` được cập
                nhật tại chỗ khi là bản ghi mới.
            run_id: Lô xử lý sở hữu chứng từ này.

        Returns:
            ``document_id`` sau khi lưu.
        """
        with self._db.transaction() as conn:
            if document.document_id is None:
                document.document_id = self._insert(conn, document, run_id)
            else:
                self._update(conn, document, run_id)
            self._save_fields(conn, document.document_id, document.fields)
        return document.document_id

    def get(self, document_id: int) -> Document | None:
        """Đọc lại một chứng từ đầy đủ (kèm toàn bộ field đã trích xuất)."""
        row = self._db.connection.execute(
            "SELECT * FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_document(row)

    def get_many(self, document_ids: list[int]) -> dict[int, Document]:
        """Đọc nhiều chứng từ cùng lúc — dùng cho ``DossierValidator``."""
        result: dict[int, Document] = {}
        for document_id in document_ids:
            doc = self.get(document_id)
            if doc is not None:
                result[document_id] = doc
        return result

    def find_by_hash(self, file_hash: str) -> list[Document]:
        """Tìm mọi chứng từ có cùng SHA256 — dùng để đối chiếu file trùng."""
        rows = self._db.connection.execute(
            "SELECT * FROM documents WHERE file_hash = ?", (file_hash,)
        ).fetchall()
        return [self._row_to_document(row) for row in rows]

    def list_by_run(self, run_id: int) -> list[Document]:
        rows = self._db.connection.execute(
            "SELECT * FROM documents WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
        return [self._row_to_document(row) for row in rows]

    def count(self) -> int:
        return self._db.connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]

    # -------------------------------------------------------------- nội bộ

    @staticmethod
    def _insert(conn: sqlite3.Connection, document: Document, run_id: int | None) -> int:
        cursor = conn.execute(
            """
            INSERT INTO documents (
                run_id, file_name, file_path, file_size, file_hash, page_count,
                page_start, page_end, segment_index,
                document_type, classify_score, classify_rule_id,
                text_source, raw_text,
                processing_status, duplicate_of_id, error_code, notes, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                document.file_name,
                str(document.file_path),
                document.file_size,
                document.file_hash,
                document.page_count,
                document.page_start,
                document.page_end,
                document.segment_index,
                document.document_type.value,
                document.classify_score,
                document.classify_rule_id,
                document.text_source.value,
                document.raw_text,
                document.processing_status.value,
                document.duplicate_of_id,
                document.error_code,
                document.notes,
                document.created_at.isoformat(),
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _update(conn: sqlite3.Connection, document: Document, run_id: int | None) -> None:
        conn.execute(
            """
            UPDATE documents SET
                run_id=?, file_name=?, file_path=?, file_size=?, file_hash=?, page_count=?,
                page_start=?, page_end=?, segment_index=?,
                document_type=?, classify_score=?, classify_rule_id=?,
                text_source=?, raw_text=?,
                processing_status=?, duplicate_of_id=?, error_code=?, notes=?
            WHERE id=?
            """,
            (
                run_id,
                document.file_name,
                str(document.file_path),
                document.file_size,
                document.file_hash,
                document.page_count,
                document.page_start,
                document.page_end,
                document.segment_index,
                document.document_type.value,
                document.classify_score,
                document.classify_rule_id,
                document.text_source.value,
                document.raw_text,
                document.processing_status.value,
                document.duplicate_of_id,
                document.error_code,
                document.notes,
                document.document_id,
            ),
        )

    @staticmethod
    def _save_fields(conn: sqlite3.Connection, document_id: int, fields: FieldSet) -> None:
        conn.execute("DELETE FROM document_fields WHERE document_id = ?", (document_id,))
        for name, field in fields.fields.items():
            value_text, value_type = _serialize_value(field.value)
            conn.execute(
                """
                INSERT INTO document_fields (
                    document_id, field_name, value_text, value_type, raw_snippet,
                    page_number, char_start, char_end, rule_id, method,
                    confidence, is_manual, error
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    document_id,
                    name,
                    value_text,
                    value_type,
                    field.raw_snippet,
                    field.page_number,
                    field.char_span[0] if field.char_span else None,
                    field.char_span[1] if field.char_span else None,
                    field.rule_id,
                    field.method.value,
                    field.confidence,
                    1 if field.is_manual else 0,
                    field.error,
                ),
            )

    def _row_to_document(self, row: sqlite3.Row) -> Document:
        fields = FieldSet()
        for field_row in self._db.connection.execute(
            "SELECT * FROM document_fields WHERE document_id = ?", (row["id"],)
        ):
            value = _deserialize_value(field_row["value_text"], field_row["value_type"])
            char_span = None
            if field_row["char_start"] is not None and field_row["char_end"] is not None:
                char_span = (field_row["char_start"], field_row["char_end"])
            fields.set(
                ExtractedField(
                    field_name=field_row["field_name"],
                    value=value,
                    raw_snippet=field_row["raw_snippet"],
                    page_number=field_row["page_number"],
                    char_span=char_span,
                    rule_id=field_row["rule_id"],
                    method=FieldMethod(field_row["method"]),
                    confidence=field_row["confidence"],
                    is_manual=bool(field_row["is_manual"]),
                    error=field_row["error"],
                )
            )

        return Document(
            document_id=row["id"],
            file_name=row["file_name"],
            file_path=Path(row["file_path"]),
            file_hash=row["file_hash"],
            file_size=row["file_size"] or 0,
            page_count=row["page_count"],
            page_start=row["page_start"],
            page_end=row["page_end"],
            segment_index=row["segment_index"],
            document_type=DocumentType(row["document_type"]),
            classify_score=row["classify_score"],
            classify_rule_id=row["classify_rule_id"],
            text_source=TextSource(row["text_source"]),
            raw_text=row["raw_text"] or "",
            fields=fields,
            processing_status=ProcessingStatus(row["processing_status"]),
            duplicate_of_id=row["duplicate_of_id"],
            error_code=row["error_code"],
            notes=row["notes"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
