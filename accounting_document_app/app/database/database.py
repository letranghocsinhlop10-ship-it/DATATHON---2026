"""Kết nối và schema SQLite.

Lưu ý khác biệt so với schema đề xuất ở ``docs/PHASE1_ARCHITECTURE.md`` §4:
bảng ``documents`` gốc trong Phase 1 có cột cứng cho từng trường nghiệp vụ
(``company_name``, ``tax_code``, ``subtotal``...). Phase 2 đã đổi
``Document`` sang lưu trường bằng ``FieldSet`` (dict) để thêm ngân hàng/nhà
cung cấp mới không phải sửa model — vì vậy DB cũng đổi theo: mọi trường
nghiệp vụ nằm trong bảng ``document_fields`` (đã có sẵn trong thiết kế gốc,
dùng làm bảng CHÍNH thay vì bảng phụ). Bảng ``documents`` chỉ giữ các cột
cấu trúc (danh tính file, loại, trạng thái).

Toàn bộ tiền lưu dạng TEXT (chuỗi thập phân của ``Decimal``) — không bao giờ
dùng kiểu REAL của SQLite cho tiền.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

__all__ = ["Database"]

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS processing_runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at        TEXT    NOT NULL,
    finished_at       TEXT,
    input_folder      TEXT    NOT NULL,
    output_folder     TEXT,
    app_version       TEXT    NOT NULL,
    total_files       INTEGER NOT NULL DEFAULT 0,
    processed_files   INTEGER NOT NULL DEFAULT 0,
    error_files       INTEGER NOT NULL DEFAULT 0,
    status            TEXT    NOT NULL DEFAULT 'RUNNING'
);

CREATE TABLE IF NOT EXISTS documents (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER REFERENCES processing_runs(id) ON DELETE SET NULL,
    file_name           TEXT    NOT NULL,
    file_path           TEXT    NOT NULL,
    file_size           INTEGER,
    file_hash           TEXT    NOT NULL,
    page_count          INTEGER,
    page_start          INTEGER NOT NULL DEFAULT 1,
    page_end            INTEGER,
    segment_index       INTEGER NOT NULL DEFAULT 0,

    document_type       TEXT    NOT NULL,
    classify_score      REAL,
    classify_rule_id    TEXT,

    text_source         TEXT    NOT NULL DEFAULT 'NONE',
    raw_text            TEXT,

    processing_status   TEXT    NOT NULL DEFAULT 'OK',
    duplicate_of_id     INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    error_code          TEXT,
    notes               TEXT,
    created_at          TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_doc_hash ON documents(file_hash);
CREATE INDEX IF NOT EXISTS idx_doc_type ON documents(document_type);
CREATE INDEX IF NOT EXISTS idx_doc_run  ON documents(run_id);

CREATE TABLE IF NOT EXISTS document_fields (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id   INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    field_name    TEXT    NOT NULL,
    value_text    TEXT,
    value_type    TEXT    NOT NULL DEFAULT 'text',   -- text|decimal|date|bool
    raw_snippet   TEXT,
    page_number   INTEGER,
    char_start    INTEGER,
    char_end      INTEGER,
    rule_id       TEXT,
    method        TEXT    NOT NULL DEFAULT 'REGEX',
    confidence    REAL,
    is_manual     INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    edited_by     TEXT,
    edited_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_field_doc ON document_fields(document_id, field_name);
CREATE UNIQUE INDEX IF NOT EXISTS uq_field_doc_name ON document_fields(document_id, field_name);

CREATE TABLE IF NOT EXISTS dossiers (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            INTEGER REFERENCES processing_runs(id) ON DELETE SET NULL,
    dossier_code      TEXT    NOT NULL,
    reference         TEXT,
    meta_document_id  INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    debit_document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    vat_document_id   INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    meta_count        INTEGER NOT NULL DEFAULT 0,
    debit_count       INTEGER NOT NULL DEFAULT 0,
    vat_count         INTEGER NOT NULL DEFAULT 0,
    card_last4        TEXT,
    transaction_date  TEXT,
    status            TEXT    NOT NULL,
    match_source      TEXT    NOT NULL DEFAULT 'AUTO_EXACT',
    reviewed          INTEGER NOT NULL DEFAULT 0,
    reviewed_by       TEXT,
    reviewed_at       TEXT,
    folder_path       TEXT,
    notes             TEXT,
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_dossier_run_code ON dossiers(run_id, dossier_code);
CREATE INDEX IF NOT EXISTS idx_dossier_ref ON dossiers(reference);

CREATE TABLE IF NOT EXISTS dossier_documents (
    dossier_id   INTEGER NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    role         TEXT    NOT NULL,   -- META|DEBIT|VAT|EXTRA
    linked_at    TEXT    NOT NULL,
    PRIMARY KEY (dossier_id, document_id)
);

CREATE TABLE IF NOT EXISTS match_candidates (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER REFERENCES processing_runs(id) ON DELETE SET NULL,
    source_doc_id    INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    target_doc_id    INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    signals          TEXT    NOT NULL,
    score            REAL    NOT NULL,
    decision         TEXT    NOT NULL DEFAULT 'PENDING',
    decided_by       TEXT,
    decided_at       TEXT
);

CREATE TABLE IF NOT EXISTS errors (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            INTEGER REFERENCES processing_runs(id) ON DELETE SET NULL,
    document_id       INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    dossier_id        INTEGER REFERENCES dossiers(id) ON DELETE CASCADE,
    severity          TEXT    NOT NULL,
    error_code        TEXT    NOT NULL,
    description       TEXT    NOT NULL,
    suggested_action  TEXT,
    created_at        TEXT    NOT NULL,
    resolved          INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_error_dossier ON errors(dossier_id);
CREATE INDEX IF NOT EXISTS idx_error_run ON errors(run_id, severity);

CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity      TEXT NOT NULL,      -- DOCUMENT|DOSSIER|FIELD
    entity_id   INTEGER NOT NULL,
    action      TEXT NOT NULL,
    old_value   TEXT,
    new_value   TEXT,
    actor       TEXT,
    created_at  TEXT NOT NULL
);
"""


class Database:
    """Bọc một kết nối SQLite: schema, transaction, đóng/mở.

    Args:
        path: Đường dẫn file ``.db``, hoặc ``":memory:"`` cho test.

    Ví dụ dùng như context manager::

        with Database("database/accounting_app.db") as db:
            ...
    """

    def __init__(self, path: Path | str = ":memory:") -> None:
        self.path = path if path == ":memory:" else Path(path)
        if isinstance(self.path, Path):
            self.path.parent.mkdir(parents=True, exist_ok=True)

        # check_same_thread=False: các bước SCAN/MATCH chạy trong QThread
        # riêng (app/ui/workers.py) nhưng dùng chung một Database với
        # MainWindow ở main thread. An toàn trong app này vì UI khoá nút bấm
        # suốt lúc worker chạy (MainWindow._set_running) nên KHÔNG BAO GIỜ có
        # hai thread cùng đụng DB một lúc — chỉ nới lỏng kiểm tra "cùng
        # thread" của sqlite3, không tự thêm truy cập đồng thời thật sự.
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()
        logger.debug("Schema SQLite đã sẵn sàng (version=%d) tại %s", SCHEMA_VERSION, self.path)

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Context manager: commit khi thành công, rollback khi có lỗi."""
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
