# PHASE 1 — PHÂN TÍCH & THIẾT KẾ
# Marketing Accounting Document Tool (Windows Desktop)

> **Trạng thái:** Phase 1 — thiết kế. **Chưa viết code ứng dụng.**
> Tài liệu này là hợp đồng kỹ thuật cho Phase 2–7. Mọi thay đổi nghiệp vụ phải cập nhật tại đây trước khi sửa code.

---

## 0. TÓM TẮT ĐIỀU HÀNH

Ứng dụng đọc ~300 file PDF trộn lẫn trong một thư mục, tự phân loại thành 3 loại chứng từ, trích xuất dữ liệu, **ghép bộ hồ sơ bằng so sánh chuỗi tuyệt đối trên Số tham chiếu (reference)**, cho phép kế toán review/sửa tay, sau đó **copy** (không di chuyển, không xoá) PDF thành từng thư mục hồ sơ và xuất Excel 4 sheet phục vụ hạch toán MISA SME 2023.

Ba nguyên tắc chi phối toàn bộ thiết kế:

| # | Nguyên tắc | Hệ quả kỹ thuật |
|---|-----------|-----------------|
| 1 | **Không suy đoán dữ liệu** | Không đọc được ⇒ `None`. Không có giá trị mặc định ngầm. Không fuzzy, không AI/LLM trong đường quyết định. |
| 2 | **Không ghép sai còn hơn không ghép** | Chỉ auto-match khi `normalize(A) == normalize(B)`. Mọi nghi ngờ ⇒ `NEEDS_REVIEW`, không bao giờ `VALID`. |
| 3 | **Mọi con số phải truy vết được về PDF gốc** | Mỗi field lưu kèm *provenance*: trang, offset, đoạn text gốc, id của rule regex đã match. |

---

## 1. KIẾN TRÚC ĐỀ XUẤT

### 1.1 Mô hình phân lớp (Layered + Ports & Adapters)

```
┌──────────────────────────────────────────────────────────────┐
│  PRESENTATION  (app/ui)  — PySide6                           │
│  MainWindow · ReviewWindow · DossierDetailWindow ·           │
│  DocumentPreview · SettingsWindow                            │
│  -> chỉ hiển thị + phát lệnh. KHÔNG chứa nghiệp vụ.          │
└───────────────▲──────────────────────────────────────────────┘
                │ Qt Signals / Slots (QThread worker)
┌───────────────┴──────────────────────────────────────────────┐
│  APPLICATION  (app/services)                                 │
│  ScanService · ExtractService · MatchService ·               │
│  OrganizeService · ExportService · ProcessingRunManager      │
│  -> điều phối use-case, transaction, progress, cancel        │
└───────────────▲──────────────────────────────────────────────┘
                │ gọi thuần Python, không biết Qt
┌───────────────┴──────────────────────────────────────────────┐
│  DOMAIN  (app/models, app/matching, app/core rules)          │
│  Document · Dossier · ExtractedField · ReferenceMatcher ·    │
│  DossierBuilder · DossierValidator · normalize_reference()   │
│  -> thuần logic, không I/O, 100% unit-testable               │
└───────────────▲──────────────────────────────────────────────┘
                │ interface (Protocol / ABC)
┌───────────────┴──────────────────────────────────────────────┐
│  INFRASTRUCTURE                                              │
│  core/pdf_reader (PyMuPDF) · core/ocr_provider (Tesseract/   │
│  PaddleOCR) · extractors/* (regex rules từ YAML) ·           │
│  database/* (SQLite) · exporters/* (openpyxl, shutil) ·      │
│  config loader (YAML) · logging                              │
└──────────────────────────────────────────────────────────────┘
```

**Chiều phụ thuộc luôn hướng vào trong.** Domain không import PySide6, không import fitz, không import sqlite3. Nhờ vậy toàn bộ luật ghép cặp test được bằng `pytest` không cần PDF thật, không cần GUI.

### 1.2 Các điểm mở rộng (plug-in points)

Bốn nơi cần "dễ thêm ngân hàng / nhà cung cấp mới" — tất cả đều là **registry + YAML**, không phải `if/elif`:

| Điểm mở rộng | Cơ chế | Thêm mới bằng cách |
|---|---|---|
| Phân loại chứng từ | `ClassifierRegistry` đọc `config/document_rules.yaml` | Thêm 1 block YAML mô tả keyword + trọng số |
| Trích xuất trường | `ExtractorRegistry` map `document_type -> Extractor` | Thêm 1 class kế thừa `BaseExtractor` + 1 block rules YAML |
| Đọc PDF / OCR | `PDFTextSource` / `OCRProvider` (Protocol) | Viết adapter mới, khai báo trong settings |
| Xuất MISA | `misa_mapping.yaml` (cột đích ← biểu thức nguồn) | Sửa file mapping, **không sửa code** |

### 1.3 Quyết định kỹ thuật chốt trong Phase 1

| Vấn đề | Quyết định | Lý do |
|---|---|---|
| Kiểu số tiền | `decimal.Decimal`, lưu DB dạng `TEXT` (chuỗi thập phân chính xác) + cột `currency` | Không bao giờ dùng `float` cho tiền. VND không có phần lẻ nhưng hoá đơn Meta có thể là USD 2 chữ số thập phân |
| Kiểu ngày | `datetime.date`, lưu `TEXT` ISO `YYYY-MM-DD` | Sort/so sánh đúng trong SQLite; format hiển thị `dd/mm/yyyy` chỉ ở tầng UI |
| Song song hoá | `QThread` cho worker + `ProcessPoolExecutor` cho parse PDF | Parse PDF là CPU-bound; UI không bao giờ block |
| Nguồn chân lý (source of truth) | **SQLite**. UI chỉ đọc từ DB | Đóng app mở lại vẫn còn kết quả; review dở dang không mất |
| Tính bất biến của file gốc | Toàn bộ pipeline mở PDF ở chế độ read-only; tầng organize chỉ dùng `shutil.copy2` | Yêu cầu §21 |
| Offline | Không có thư viện HTTP trong `requirements.txt`; model OCR đóng gói sẵn vào EXE | Yêu cầu §3 |

---

## 2. PROCESSING PIPELINE

### 2.1 Sơ đồ tổng thể

```
[1] SCAN          duyệt thư mục -> danh sách *.pdf -> SHA256 -> phát hiện DUPLICATE_FILE
      │
      ▼
[2] READ          PyMuPDF get_text("text") theo từng trang
      │           ├─ đủ text (≥ min_chars_per_page)  -> TEXT_LAYER
      │           └─ thiếu text / PDF scan           -> OCR fallback  -> OCR
      │           lỗi mở file / file mã hoá          -> status=ERROR, ghi bảng errors, ĐI TIẾP
      ▼
[3] NORMALIZE     Unicode NFC, bỏ ký tự zero-width, chuẩn hoá xuống dòng, giữ nguyên bản raw_text
      │
      ▼
[4] CLASSIFY      chấm điểm keyword theo document_rules.yaml
      │           -> META_INVOICE | VPBANK_DEBIT_NOTE | VPBANK_VAT_INVOICE | UNKNOWN
      ▼
[5] EXTRACT       Extractor tương ứng chạy danh sách rule regex có thứ tự ưu tiên
      │           mỗi field -> ExtractedField(value, raw_snippet, page, span, rule_id, method)
      ▼
[6] PERSIST       ghi documents + document_fields (trong 1 transaction / 1 processing_run)
      │
      ▼
[7] MATCH         gom nhóm theo reference_key -> exact string equality
      │
      ▼
[8] BUILD         tạo Dossier cho từng reference_key
      │
      ▼
[9] VALIDATE      áp bộ luật §7 -> status + danh sách issue (blocking / warning)
      │
      ▼
[10] REVIEW       kế toán xem, sửa tay, mark reviewed  (vòng lặp, có thể quay lại [9])
      │
      ▼
[11] ORGANIZE     COPY PDF -> OUTPUT/HSxxxxxx_<REF>/01_..02_..03_..
      │                       + NEEDS_REVIEW/ UNMATCHED/ DUPLICATES/
      ▼
[12] EXPORT       ACCOUNTING_RESULT.xlsx (4 sheet)
```

Bước 1–6 idempotent theo `file_hash`: chạy lại trên cùng thư mục sẽ tái sử dụng kết quả cũ trừ khi người dùng chọn *Force re-scan*.

### 2.2 Chi tiết bước [2] READ — luật quyết định OCR

```python
# pseudo-spec, không phải code sản phẩm
text_chars   = tổng ký tự "có nghĩa" (loại whitespace) của trang
image_ratio  = diện tích ảnh / diện tích trang

if text_chars >= cfg.min_chars_per_page:          -> TEXT_LAYER, không OCR
elif not cfg.ocr_enabled:                          -> status = NEEDS_OCR (không tự đoán)
else:                                              -> OCR trang đó (render 300 DPI)
```

Ngưỡng `min_chars_per_page` nằm trong `app_settings.yaml`, mặc định đề xuất **80**. `document.text_source` lưu `TEXT_LAYER | OCR | MIXED` để Excel/log truy vết được file nào đã qua OCR — **trường này bắt buộc hiển thị trên UI** vì độ tin cậy dữ liệu OCR thấp hơn.

### 2.3 Xử lý lỗi

Một PDF hỏng **không bao giờ** làm dừng lô. Mọi exception được bắt tại ranh giới `process_one_file()`, ghi vào bảng `errors` với `error_code`, `file_path`, traceback rút gọn; document được đánh `processing_status = ERROR`; pipeline tiếp tục. Cuối lô, UI hiện banner: *"Đã xử lý 300 file, 4 file lỗi — xem tab Errors"*.

Bộ mã lỗi đề xuất: `PDF_OPEN_FAILED`, `PDF_ENCRYPTED`, `PDF_EMPTY_TEXT`, `OCR_FAILED`, `CLASSIFY_UNKNOWN`, `REFERENCE_NOT_FOUND`, `REFERENCE_INVALID_FORMAT`, `EXTRACT_FIELD_FAILED`, `AMOUNT_PARSE_FAILED`, `DATE_PARSE_FAILED`, `FILE_DUPLICATE`, `COPY_FAILED`, `EXPORT_FAILED`.

---

## 3. CẤU TRÚC THƯ MỤC DỰ ÁN

Giữ đúng cây thư mục bạn đề xuất, bổ sung các module cần thiết (đánh dấu `+`):

```
accounting_document_app/
    main.py
    app/
        __init__.py
        ui/
            main_window.py
            dossier_detail_window.py
            document_preview.py
            settings_window.py
            review_window.py
          + widgets/            # bảng dossier, badge trạng thái, ô tiền/ngày
          + view_models.py      # chuyển domain object -> dòng bảng (không logic nghiệp vụ)
          + workers.py          # QThread/QRunnable wrapper + progress + cancel
        core/
            pdf_reader.py
            document_classifier.py
            text_normalizer.py
            duplicate_detector.py
          + ocr_provider.py     # Protocol + TesseractProvider / PaddleProvider
        extractors/
            base_extractor.py
            meta_invoice_extractor.py
            vpbank_debit_extractor.py
            vpbank_vat_extractor.py
          + rule_engine.py      # chạy danh sách rule regex từ YAML, trả ExtractedField
          + registry.py
        matching/
            reference_matcher.py
            dossier_builder.py
            dossier_validator.py
          + candidate_suggester.py   # GỢI Ý cho người dùng, KHÔNG auto-match
        models/
            document.py
            dossier.py
            extracted_field.py
          + enums.py            # DocumentType, DossierStatus, ErrorCode, TextSource
          + processing_run.py
        database/
            database.py
            document_repository.py
            dossier_repository.py
          + migrations/         # 001_init.sql, 002_...
          + error_repository.py
          + settings_repository.py
      + services/
            scan_service.py
            extract_service.py
            match_service.py
            organize_service.py
            export_service.py
        exporters/
            excel_exporter.py
            pdf_organizer.py
            misa_exporter.py
        utils/
            money_utils.py
            date_utils.py
            string_utils.py
            file_utils.py
            logging_utils.py
      + config_loader.py        # đọc + validate YAML, trả dataclass config
    config/
        document_rules.yaml
        accounting.yaml
        app_settings.yaml
      + extraction_rules.yaml   # regex cho từng loại chứng từ
      + misa_mapping.yaml       # mapping app field -> cột MISA
    database/
        accounting_app.db
    logs/
        app.log
    tests/
      + fixtures/               # text đã trích xuất (.txt) từ PDF mẫu - KHÔNG commit PDF thật
        test_reference_normalizer.py
        test_classifier.py
        test_meta_extractor.py
        test_debit_extractor.py
        test_vat_extractor.py
        test_matcher.py
        test_validator.py
        test_excel_exporter.py
    requirements.txt
    README.md
    build.bat
```

Lý do tách `services/`: UI hiện tại là PySide6, nhưng nếu sau này cần chạy batch bằng dòng lệnh (`--scan --export`) thì chỉ cần gọi service, không phải viết lại nghiệp vụ.

---

## 4. SQLITE DATABASE SCHEMA

Bật `PRAGMA foreign_keys = ON`, `journal_mode = WAL`.

```sql
-- =====================================================================
-- 4.1  LÔ XỬ LÝ
-- =====================================================================
CREATE TABLE processing_runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at        TEXT    NOT NULL,           -- ISO8601
    finished_at       TEXT,
    input_folder      TEXT    NOT NULL,
    output_folder     TEXT,
    app_version       TEXT    NOT NULL,
    config_snapshot   TEXT,                       -- JSON toàn bộ config lúc chạy
    total_files       INTEGER DEFAULT 0,
    processed_files   INTEGER DEFAULT 0,
    error_files       INTEGER DEFAULT 0,
    status            TEXT    NOT NULL            -- RUNNING|COMPLETED|CANCELLED|FAILED
);

-- =====================================================================
-- 4.2  CHỨNG TỪ
-- =====================================================================
CREATE TABLE documents (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER REFERENCES processing_runs(id),
    file_name           TEXT    NOT NULL,
    file_path           TEXT    NOT NULL,
    file_size           INTEGER,
    file_modified_at    TEXT,
    file_hash           TEXT    NOT NULL,          -- SHA256 hex
    page_count          INTEGER,

    document_type       TEXT    NOT NULL,          -- META_INVOICE|VPBANK_DEBIT_NOTE|
                                                   -- VPBANK_VAT_INVOICE|UNKNOWN
    classify_score      REAL,
    classify_rule_id    TEXT,

    text_source         TEXT,                      -- TEXT_LAYER|OCR|MIXED|NONE
    raw_text            TEXT,

    -- danh tính bên liên quan
    company_name        TEXT,
    tax_code            TEXT,
    customer_id         TEXT,

    -- thời gian
    document_date       TEXT,                      -- YYYY-MM-DD
    transaction_date    TEXT,

    -- khoá ghép
    reference_number    TEXT,                      -- ref GỐC của chính chứng từ
    reference_norm      TEXT,                      -- đã normalize - dùng để JOIN
    meta_reference      TEXT,                      -- ref Meta tìm thấy TRONG debit/VAT
    meta_reference_norm TEXT,

    -- định danh chứng từ
    invoice_number      TEXT,
    invoice_serial      TEXT,
    transaction_id      TEXT,
    transaction_code    TEXT,
    bank_account        TEXT,
    card_last4          TEXT,

    -- tiền (chuỗi thập phân chính xác, KHÔNG dùng REAL)
    currency            TEXT,
    subtotal            TEXT,
    vat_rate            TEXT,
    vat_amount          TEXT,
    total_amount        TEXT,

    payment_detail      TEXT,

    processing_status   TEXT    NOT NULL,          -- OK|ERROR|NEEDS_OCR|DUPLICATE_FILE|UNKNOWN_TYPE
    duplicate_of_id     INTEGER REFERENCES documents(id),
    notes               TEXT,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);

CREATE INDEX idx_doc_hash       ON documents(file_hash);
CREATE INDEX idx_doc_type       ON documents(document_type);
CREATE INDEX idx_doc_ref_norm   ON documents(reference_norm);
CREATE INDEX idx_doc_metaref    ON documents(meta_reference_norm);
CREATE UNIQUE INDEX uq_doc_run_hash ON documents(run_id, file_hash);

-- =====================================================================
-- 4.3  PROVENANCE TỪNG TRƯỜNG  (cột sống của "dễ kiểm tra lại")
-- =====================================================================
CREATE TABLE document_fields (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id   INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    field_name    TEXT    NOT NULL,       -- 'reference_number', 'total_amount', ...
    value_text    TEXT,                   -- giá trị đã chuẩn hoá (NULL nếu không đọc được)
    raw_snippet   TEXT,                   -- đoạn text gốc chứa giá trị
    page_number   INTEGER,
    char_start    INTEGER,
    char_end      INTEGER,
    rule_id       TEXT,                   -- id rule trong extraction_rules.yaml
    method        TEXT NOT NULL,          -- REGEX|OCR_REGEX|MANUAL|DERIVED
    confidence    REAL,
    is_manual     INTEGER NOT NULL DEFAULT 0,
    edited_by     TEXT,
    edited_at     TEXT
);
CREATE INDEX idx_field_doc ON document_fields(document_id, field_name);

-- =====================================================================
-- 4.4  HỒ SƠ
-- =====================================================================
CREATE TABLE dossiers (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            INTEGER REFERENCES processing_runs(id),
    dossier_code      TEXT    NOT NULL,          -- 'HS000001'
    reference         TEXT,                      -- reference_norm (NULL nếu nhóm không có ref)
    meta_document_id  INTEGER REFERENCES documents(id),
    debit_document_id INTEGER REFERENCES documents(id),
    vat_document_id   INTEGER REFERENCES documents(id),
    card_last4        TEXT,
    transaction_date  TEXT,
    status            TEXT    NOT NULL,          -- xem §7.3
    match_source      TEXT    NOT NULL,          -- AUTO_EXACT|MANUAL
    reviewed          INTEGER NOT NULL DEFAULT 0,
    reviewed_by       TEXT,
    reviewed_at       TEXT,
    folder_path       TEXT,
    notes             TEXT,
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL
);
CREATE UNIQUE INDEX uq_dossier_code ON dossiers(run_id, dossier_code);
CREATE INDEX idx_dossier_ref ON dossiers(reference);

-- Quan hệ N-N để giữ được CẢ các bản trùng (2 Meta cùng ref) cho người dùng review
CREATE TABLE dossier_documents (
    dossier_id   INTEGER NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    role         TEXT    NOT NULL,   -- META|DEBIT|VAT|EXTRA
    is_primary   INTEGER NOT NULL DEFAULT 1,
    link_source  TEXT    NOT NULL,   -- AUTO_EXACT|MANUAL
    linked_at    TEXT    NOT NULL,
    PRIMARY KEY (dossier_id, document_id)
);

-- =====================================================================
-- 4.5  GỢI Ý GHÉP (chỉ hiển thị - KHÔNG BAO GIỜ tự áp dụng)
-- =====================================================================
CREATE TABLE match_candidates (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER REFERENCES processing_runs(id),
    source_doc_id    INTEGER NOT NULL REFERENCES documents(id),
    target_doc_id    INTEGER NOT NULL REFERENCES documents(id),
    signals          TEXT NOT NULL,   -- JSON: ["SAME_CARD","SAME_DATE","SAME_AMOUNT"]
    score            REAL NOT NULL,   -- chỉ để SẮP XẾP danh sách gợi ý
    decision         TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING|ACCEPTED|REJECTED
    decided_by       TEXT,
    decided_at       TEXT
);

-- =====================================================================
-- 4.6  LỖI & CẤU HÌNH
-- =====================================================================
CREATE TABLE errors (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER REFERENCES processing_runs(id),
    document_id  INTEGER REFERENCES documents(id),
    dossier_id   INTEGER REFERENCES dossiers(id),
    severity     TEXT NOT NULL,      -- BLOCKING|WARNING|INFO
    error_code   TEXT NOT NULL,
    description  TEXT NOT NULL,
    file_name    TEXT,
    suggested_action TEXT,
    created_at   TEXT NOT NULL,
    resolved     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_error_run ON errors(run_id, severity);

CREATE TABLE settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE audit_log (               -- mọi thao tác sửa tay của kế toán
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity      TEXT NOT NULL,         -- DOCUMENT|DOSSIER|FIELD
    entity_id   INTEGER NOT NULL,
    action      TEXT NOT NULL,         -- LINK|UNLINK|EDIT_FIELD|MARK_REVIEWED|CREATE_DOSSIER
    old_value   TEXT,
    new_value   TEXT,
    actor       TEXT,
    created_at  TEXT NOT NULL
);
```

**Ghi chú thiết kế:** `dossiers` giữ 3 cột `*_document_id` để truy vấn/UI nhanh, còn `dossier_documents` giữ toàn bộ quan hệ kể cả bản trùng. Khi có 2 Meta cùng reference: cả hai nằm trong `dossier_documents` với `role='META'`, `is_primary=0`, và `dossiers.meta_document_id = NULL` cho tới khi người dùng chọn bản chính.

---

## 5. PYTHON DATA MODELS (đặc tả, chưa phải code sản phẩm)

### 5.1 Enum

```python
class DocumentType(str, Enum):
    META_INVOICE       = "META_INVOICE"
    VPBANK_DEBIT_NOTE  = "VPBANK_DEBIT_NOTE"
    VPBANK_VAT_INVOICE = "VPBANK_VAT_INVOICE"
    UNKNOWN            = "UNKNOWN"

class TextSource(str, Enum):
    TEXT_LAYER = "TEXT_LAYER"; OCR = "OCR"; MIXED = "MIXED"; NONE = "NONE"

class ProcessingStatus(str, Enum):
    OK = "OK"; ERROR = "ERROR"; NEEDS_OCR = "NEEDS_OCR"
    DUPLICATE_FILE = "DUPLICATE_FILE"; UNKNOWN_TYPE = "UNKNOWN_TYPE"

class DossierStatus(str, Enum):
    VALID              = "VALID"
    MISSING_META       = "MISSING_META"
    MISSING_DEBIT      = "MISSING_DEBIT"
    MISSING_VAT        = "MISSING_VAT"
    DUPLICATE_META     = "DUPLICATE_META"
    DUPLICATE_DEBIT    = "DUPLICATE_DEBIT"
    DUPLICATE_VAT      = "DUPLICATE_VAT"
    INVALID_REFERENCE  = "INVALID_REFERENCE"
    NEEDS_REVIEW       = "NEEDS_REVIEW"

class FieldMethod(str, Enum):
    REGEX = "REGEX"; OCR_REGEX = "OCR_REGEX"; MANUAL = "MANUAL"; DERIVED = "DERIVED"
```

### 5.2 ExtractedField — hạt nhân truy vết

```python
@dataclass(frozen=True)
class ExtractedField(Generic[T]):
    """Một giá trị trích xuất kèm toàn bộ bằng chứng nguồn.

    value is None  <=>  không đọc được. KHÔNG BAO GIỜ suy đoán giá trị thay thế.
    """
    field_name:  str
    value:       T | None
    raw_snippet: str | None = None
    page_number: int | None = None
    char_span:   tuple[int, int] | None = None
    rule_id:     str | None = None
    method:      FieldMethod = FieldMethod.REGEX
    confidence:  float | None = None
    is_manual:   bool = False

    @property
    def found(self) -> bool: return self.value is not None
```

`T` cụ thể: `str`, `date`, `Decimal`.

### 5.3 Document

```python
@dataclass
class Document:
    # --- định danh file ---
    document_id: int | None
    file_name: str
    file_path: Path
    file_hash: str                      # SHA256
    file_size: int
    page_count: int | None

    # --- phân loại ---
    document_type: DocumentType
    classify_score: float | None
    classify_rule_id: str | None

    # --- text ---
    text_source: TextSource
    raw_text: str
    pages_text: list[str] = field(default_factory=list)

    # --- các trường trích xuất (tất cả là ExtractedField) ---
    company_name:     ExtractedField[str]
    tax_code:         ExtractedField[str]
    customer_id:      ExtractedField[str]
    document_date:    ExtractedField[date]
    transaction_date: ExtractedField[date]
    reference_number: ExtractedField[str]     # ref của chính chứng từ
    meta_reference:   ExtractedField[str]     # ref Meta tìm thấy bên trong debit/VAT
    invoice_number:   ExtractedField[str]
    invoice_serial:   ExtractedField[str]
    transaction_id:   ExtractedField[str]
    transaction_code: ExtractedField[str]
    bank_account:     ExtractedField[str]
    card_last4:       ExtractedField[str]
    currency:         ExtractedField[str]
    subtotal:         ExtractedField[Decimal]
    vat_rate:         ExtractedField[Decimal]
    vat_amount:       ExtractedField[Decimal]
    total_amount:     ExtractedField[Decimal]
    payment_detail:   ExtractedField[str]

    processing_status: ProcessingStatus
    duplicate_of_id: int | None = None
    notes: str | None = None

    # --- khoá ghép đã chuẩn hoá (tính 1 lần, cache) ---
    @property
    def match_key(self) -> str | None:
        """Khoá dùng để ghép bộ.

        META_INVOICE  -> normalize(reference_number)
        DEBIT / VAT   -> normalize(meta_reference)
        """
```

### 5.4 Dossier

```python
@dataclass
class DossierIssue:
    code: str                  # MISSING_VAT, AMOUNT_MISMATCH, ...
    severity: Severity         # BLOCKING | WARNING | INFO
    description: str
    document_id: int | None = None
    suggested_action: str | None = None

@dataclass
class Dossier:
    dossier_id: int | None
    dossier_code: str                    # HS000001
    reference: str | None                # reference_norm
    meta_document_id: int | None
    debit_document_id: int | None
    vat_document_id: int | None
    extra_documents: list[int] = field(default_factory=list)   # bản trùng
    card_last4: str | None = None
    transaction_date: date | None = None
    status: DossierStatus = DossierStatus.NEEDS_REVIEW
    match_source: MatchSource = MatchSource.AUTO_EXACT
    issues: list[DossierIssue] = field(default_factory=list)
    reviewed: bool = False
    folder_path: Path | None = None
    notes: str | None = None

    @property
    def is_complete(self) -> bool:
        return all([self.meta_document_id, self.debit_document_id, self.vat_document_id])
```

---

## 6. THIẾT KẾ EXACT REFERENCE MATCHING

### 6.1 `normalize_reference()` — đặc tả chính xác

```
INPUT : chuỗi thô lấy từ PDF (có thể None)
OUTPUT: chuỗi đã chuẩn hoá, hoặc None

B1. None / rỗng                     -> None
B2. Unicode NFKC normalize          (gộp ký tự full-width, ligature)
B3. Xoá ký tự vô hình: U+200B..U+200D, U+FEFF, soft hyphen U+00AD
B4. strip() hai đầu
B5. Xoá dấu câu bao quanh: . , ; : ) ( [ ] " ' * -  ở HAI ĐẦU (không xoá ở giữa)
B6. Gộp mọi khoảng trắng liên tiếp thành 1 space
B7. Xoá TOÀN BỘ space còn lại        <-- xem Câu hỏi Q3, mặc định BẬT
B8. .upper()  (ASCII uppercase)
B9. Nếu kết quả rỗng                -> None
B10. Kiểm tra pattern hợp lệ từ config (mặc định ^[A-Z0-9]{6,24}$)
     - khớp     -> trả về chuỗi
     - không khớp -> trả về chuỗi NHƯNG gắn cờ INVALID_REFERENCE_FORMAT
```

**TUYỆT ĐỐI CẤM** trong hàm này:
- `O -> 0`, `I -> 1`, `l -> 1`, `B -> 8`, `S -> 5`, `Z -> 2`
- bỏ dấu tiếng Việt trên reference
- cắt bớt ký tự, đệm thêm ký tự
- Levenshtein / difflib / fuzzywuzzy / rapidfuzz
- bất kỳ lời gọi LLM nào

Hàm này là hàm thuần, không I/O, không log — và là hàm được test kỹ nhất trong project.

### 6.2 Thuật toán ghép (deterministic, O(n))

```
Bước 1 — Tính khoá:
    metas  = {doc.id: key}  với doc.type == META_INVOICE,  key = norm(doc.reference_number)
    debits = {doc.id: key}  với doc.type == VPBANK_DEBIT_NOTE, key = norm(doc.meta_reference)
    vats   = {doc.id: key}  với doc.type == VPBANK_VAT_INVOICE, key = norm(doc.meta_reference)

    Chứng từ có key == None  ->  KHÔNG vào bước gom nhóm.
                                 -> bucket UNMATCHED, error REFERENCE_NOT_FOUND

Bước 2 — Gom nhóm (dict of lists, không sort, không heuristic):
    groups: dict[str, {"meta": [...], "debit": [...], "vat": [...]}]
    for each doc: groups[key][role].append(doc)

Bước 3 — Mỗi key sinh đúng 1 Dossier.
Bước 4 — Đếm len() từng role -> quyết định status theo bảng §7.
```

So sánh duy nhất được phép trong toàn hệ thống:

```python
if meta_key == debit_key:   # Python str.__eq__, không hơn
```

### 6.3 Ma trận quyết định ghép

| meta_key | debit_key | Kết quả | Ghi chú |
|---|---|---|---|
| `"ABC123"` | `"ABC123"` | **MATCH** | |
| `"ABC123"` | `"abc123"` | **MATCH** | sau B8 uppercase |
| `" abc123 "` | `"ABC123"` | **MATCH** | sau B4 strip |
| `"ABC123"` | `"ABC124"` | NO MATCH | |
| `"ABC123"` | `"ABCI23"` | **NO MATCH** | I ≠ 1, không đổi |
| `"ABC123"` | `"ABC1230"` | NO MATCH | không prefix match |
| `"ABC123"` | `None` | NO MATCH | debit vào UNMATCHED |
| `None` | `"ABC123"` | NO MATCH | meta vào UNMATCHED |

### 6.4 Gợi ý ghép tay (candidate suggester) — ranh giới an toàn

Để kế toán không phải dò 300 file bằng mắt, hệ thống **được phép gợi ý** nhưng **không được phép quyết định**:

- Tín hiệu dùng để gợi ý: `SAME_CARD_LAST4`, `SAME_AMOUNT`, `DATE_WITHIN_N_DAYS`, `SAME_TAX_CODE`.
- Kết quả ghi vào `match_candidates` với `decision='PENDING'`.
- Chỉ hiển thị trong **Review Window**, kèm nhãn đỏ: *"GỢI Ý — chưa được ghép. Người dùng phải xác nhận."*
- Khi người dùng bấm Accept: tạo link với `link_source='MANUAL'`, ghi `audit_log`, dossier status chuyển `NEEDS_REVIEW` (không tự thành `VALID`), `reviewed` do người dùng bấm riêng.
- **Không có đường code nào** cho phép candidate tự chuyển thành dossier hợp lệ.

### 6.5 REFERENCE_MISMATCH (theo §34)

Nếu người dùng khẳng định 2 file thuộc cùng bộ nhưng reference khác nhau, hệ thống:
1. Báo `REFERENCE_MISMATCH` kèm 2 giá trị đã normalize và ảnh chụp đoạn text gốc;
2. Cho phép ghép tay (ghi `audit_log`, `match_source='MANUAL'`);
3. Trong Excel, cột `Notes` của dossier ghi rõ `MANUAL_LINK: REFERENCE_MISMATCH meta=X debit=Y`.

Hệ thống **không** vì thế mà nới luật tự động.

---

## 7. LUẬT KIỂM TRA HỒ SƠ (DOSSIER VALIDATION)

### 7.1 Bảng quyết định theo số lượng chứng từ mỗi nhóm reference

| #Meta | #Debit | #VAT | Status | Severity |
|:---:|:---:|:---:|---|---|
| 1 | 1 | 1 | `VALID` | — |
| 1 | 1 | 0 | `MISSING_VAT` | BLOCKING |
| 1 | 0 | 1 | `MISSING_DEBIT` | BLOCKING |
| 1 | 0 | 0 | `MISSING_DEBIT` (+`MISSING_VAT`) | BLOCKING |
| 0 | 1 | 1 | `MISSING_META` | BLOCKING |
| 0 | 1 | 0 | `MISSING_META` (+`MISSING_VAT`) | BLOCKING |
| 0 | 0 | 1 | `MISSING_META` (+`MISSING_DEBIT`) | BLOCKING |
| ≥2 | * | * | `DUPLICATE_META` | BLOCKING |
| * | ≥2 | * | `DUPLICATE_DEBIT` | BLOCKING |
| * | * | ≥2 | `DUPLICATE_VAT` | BLOCKING |

Khi có nhiều lỗi cùng lúc, `dossiers.status` lấy lỗi **ưu tiên cao nhất** theo thứ tự:
`DUPLICATE_* > INVALID_REFERENCE > MISSING_META > MISSING_DEBIT > MISSING_VAT > NEEDS_REVIEW > VALID`,
còn **toàn bộ** lỗi được liệt kê trong `issues` và sheet `CHECK_ERROR`.

### 7.2 Kiểm tra bổ sung (chỉ WARNING — không hạ `VALID` thành `INVALID`, nhưng chặn `reviewed=auto`)

| Mã | Luật | Severity |
|---|---|---|
| `AMOUNT_MISMATCH_META_DEBIT` | `meta.total_amount != debit.amount` (cùng currency) | WARNING |
| `CARD_MISMATCH` | `meta.card_last4 != debit.card_last4` (cả hai đều có giá trị) | WARNING |
| `DATE_GAP_TOO_LARGE` | `abs(meta.date - debit.date) > cfg.max_date_gap_days` | WARNING |
| `TAX_CODE_MISMATCH` | MST trên VAT invoice ≠ MST công ty trong settings | WARNING |
| `VAT_MATH_ERROR` | `subtotal + vat_amount != total_amount` (sai lệch > 1 đơn vị) | WARNING |
| `OCR_SOURCED_DATA` | bất kỳ chứng từ nào trong bộ có `text_source = OCR` | INFO |
| `CURRENCY_MISMATCH` | meta là USD, debit là VND | INFO (chờ luật FX — Q5) |

Quy tắc vàng: **các tín hiệu này chỉ để kiểm tra chéo, không bao giờ dùng để tạo hoặc thay đổi liên kết.**

### 7.3 Vòng đời trạng thái

```
        (build)                (validate)
 nhóm ref ──────► Dossier ─────────────► VALID ──┐
                     │                            ├─► reviewed=1 ─► ORGANIZE + EXPORT
                     ├──► MISSING_* ──┐           │
                     ├──► DUPLICATE_* ├─► NEEDS_REVIEW ──(user sửa tay)──► re-validate
                     └──► INVALID_REFERENCE ─┘
```

- `VALID` **không tự động** kéo theo `reviewed = 1`; kế toán vẫn có thể bật chế độ *"Chỉ xuất hồ sơ đã review"* trong Settings.
- Re-validate là hàm thuần chạy lại trên state hiện tại — sửa tay xong bấm *Re-validate* là thấy kết quả ngay, không cần scan lại PDF.

---

## 8. GUI WIREFRAME

### 8.1 Main Window

```
┌────────────────────────────────────────────────────────────────────────────────┐
│  MARKETING ACCOUNTING DOCUMENT TOOL                         [Settings] [Help]  │
├────────────────────────────────────────────────────────────────────────────────┤
│  Thư mục PDF :  [ C:\KETOAN\ALL_DATA                    ]  [ Browse... ]       │
│  Thư mục xuất:  [ C:\KETOAN\OUTPUT                      ]  [ Browse... ]       │
├────────────────────────────────────────────────────────────────────────────────┤
│  ① [ SCAN PDF ]  ② [ EXTRACT DATA ]  ③ [ MATCH ]  ④ [ VALIDATE ]              │
│                  ⑤ [ ORGANIZE PDF ]  ⑥ [ EXPORT EXCEL ]        [ Cancel ]      │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░  Đang xử lý PDF 127 / 300   (còn ~1 phút)      │
├────────────────────────────────────────────────────────────────────────────────┤
│  Tổng: 300 file │ Meta 100 │ Debit 99 │ VAT 97 │ Unknown 2 │ Lỗi 2 │ Trùng 0  │
│  Hồ sơ: 100 │ ● VALID 93 │ ● REVIEW 5 │ ● LỖI 2                                │
├────────────────────────────────────────────────────────────────────────────────┤
│  Lọc: [ Tất cả ▾ ]  Tìm reference: [________]   ☐ Chỉ hiện hồ sơ chưa review   │
│ ┌────────┬───────────┬──────────┬──────┬───────┬──────┬────────────────┬─────┐ │
│ │ Hồ sơ  │ Reference │ Ngày GD  │ Meta │ Debit │ VAT  │ Trạng thái     │ ✔   │ │
│ ├────────┼───────────┼──────────┼──────┼───────┼──────┼────────────────┼─────┤ │
│ │ HS0001 │ ABC123XYZ │ 24/07/26 │  ✓   │   ✓   │  ✓   │ ● VALID        │ ☑   │ │
│ │ HS0002 │ XYZ987QWE │ 25/07/26 │  ✓   │   ✓   │  ✗   │ ● MISSING VAT  │ ☐   │ │
│ │ HS0003 │ 76NQZZMDK2│ 25/07/26 │  ✓   │   ✗   │  ✗   │ ● NEEDS REVIEW │ ☐   │ │
│ │ HS0004 │ DUP55TT   │ 26/07/26 │ ✓✓   │   ✓   │  ✓   │ ● DUPLICATE META│ ☐  │ │
│ └────────┴───────────┴──────────┴──────┴───────┴──────┴────────────────┴─────┘ │
│  Double-click một dòng để mở chi tiết.                                         │
├────────────────────────────────────────────────────────────────────────────────┤
│  Tab:  [ Hồ sơ ]  [ Chứng từ (300) ]  [ Chưa ghép (4) ]  [ Lỗi (6) ]  [ Log ]  │
└────────────────────────────────────────────────────────────────────────────────┘
   ● xanh = VALID   ● vàng = NEEDS_REVIEW   ● đỏ = MISSING / DUPLICATE / ERROR
```

Nút ⑤ và ⑥ bị **disable** cho tới khi bước ④ chạy xong. Mỗi nút chạy trong worker thread, có `Cancel` thật (cooperative cancellation, không kill thread).

### 8.2 Dossier Detail Window (double-click)

```
┌─ HỒ SƠ HS0002 ────────────────────────────── Reference: XYZ987QWE ────────────┐
│ Trạng thái: ● MISSING_VAT      Ngày GD: 25/07/2026     Thẻ: ****4966          │
├────────────────────────────────────────────────────────────────────────────────┤
│ ┌── ① META INVOICE ───────────────────────────────────────────────┐            │
│ │ File     : invoice_2026_07.pdf              [ Mở PDF ] [ Xem ]  │            │
│ │ Số HĐ    : FBADS-2607-0091        Ref: XYZ987QWE  ← khớp ✓      │            │
│ │ Tiền hàng: 10.000.000   VAT 0%: 0      Tổng: 10.000.000 VND     │            │
│ │ Nguồn text: TEXT_LAYER                  [ Gỡ khỏi hồ sơ ]       │            │
│ └─────────────────────────────────────────────────────────────────┘            │
│ ┌── ② VPBANK DEBIT NOTE ──────────────────────────────────────────┐            │
│ │ File     : rptStatementTransDetail.pdf      [ Mở PDF ] [ Xem ]  │            │
│ │ Mã GD    : FT26207xxxx      Meta ref: XYZ987QWE  ← khớp ✓       │            │
│ │ Diễn giải: So the 5223xxxx4966 GD thanh toan tai FACEBK          │            │
│ │            XYZ987QWE fb me ads IE                               │            │
│ │ Số tiền  : 10.000.000 VND               [ Gỡ khỏi hồ sơ ]       │            │
│ └─────────────────────────────────────────────────────────────────┘            │
│ ┌── ③ VPBANK VAT INVOICE ─────────────────────── THIẾU ───────────┐            │
│ │  ⚠ Không tìm thấy hoá đơn GTGT phí ngân hàng có ref XYZ987QWE   │            │
│ │  Gợi ý (CHƯA GHÉP - cần xác nhận):                              │            │
│ │   • 00123457.pdf  ref=(không đọc được)  cùng thẻ 4966,          │            │
│ │     cùng ngày 25/07   [ Xem ] [ Ghép tay vào hồ sơ này ]         │            │
│ └─────────────────────────────────────────────────────────────────┘            │
├────────────────────────────────────────────────────────────────────────────────┤
│ Ghi chú: [_________________________________________________________]           │
│ [ Ghép thêm chứng từ... ] [ Chuyển sang hồ sơ khác ] [ Tạo hồ sơ mới ]         │
│                                    [ Kiểm tra lại ] [ Đánh dấu đã review ] [X] │
└────────────────────────────────────────────────────────────────────────────────┘
```

### 8.3 Review Window (chứng từ chưa ghép)

Hai bảng cạnh nhau: bên trái là chứng từ chưa ghép (kèm lý do: `REFERENCE_NOT_FOUND`, `UNKNOWN_TYPE`, `NEEDS_OCR`), bên phải là các hồ sơ đang thiếu đúng loại đó. Ở giữa là nút `→ Ghép tay`. Mọi thao tác ghi `audit_log`. Panel dưới hiển thị `raw_text` của file đang chọn với vùng match được **highlight** — đây là công cụ để kế toán tự kiểm chứng số liệu.

### 8.4 Document Preview

Version 1: render trang PDF bằng PyMuPDF (`page.get_pixmap()`) → `QPixmap` trong `QScrollArea`, kèm nút `Mở bằng trình xem mặc định` (`os.startfile`). Không nhúng Adobe/WebEngine (tránh phình EXE và rủi ro offline).

### 8.5 Settings Window

4 tab: **Thư mục** (input/output/excel/db/log) · **Xử lý** (bật OCR, engine OCR, ngưỡng `min_chars_per_page`, số worker, force re-scan) · **Kế toán** (các tài khoản từ `accounting.yaml`, MST công ty, thuế suất mặc định) · **Reference** (pattern hợp lệ, `strip_inner_whitespace`, `max_date_gap_days`). Mọi thay đổi ghi vào bảng `settings` + file YAML, có nút `Khôi phục mặc định`.

---

## 9. THIẾT KẾ EXCEL OUTPUT

File: `ACCOUNTING_RESULT_<YYYYMMDD_HHMMSS>.xlsx` (có timestamp để không ghi đè bản trước).

### Sheet 1 — `HO_SO` (1 dòng = 1 hồ sơ)

| # | Cột | Kiểu | Ghi chú |
|---|---|---|---|
| 1 | HoSo_ID | text | HS000001 |
| 2 | Reference | text | đã normalize |
| 3 | Status | text | tô màu theo trạng thái |
| 4 | Transaction_Date | date `dd/mm/yyyy` | |
| 5 | Card_Last4 | text | giữ số 0 đầu ⇒ định dạng text |
| 6 | Company_Name | text | |
| 7 | Tax_Code | text | |
| 8 | Meta_Invoice_Number | text | |
| 9 | Meta_Transaction_ID | text | |
| 10 | Meta_Subtotal | number `#,##0` | |
| 11 | Meta_VAT | number | |
| 12 | Meta_Total | number | |
| 13 | Debit_Transaction_Code | text | |
| 14 | Debit_Amount | number | |
| 15 | Bank_Invoice_Serial | text | |
| 16 | Bank_Invoice_Number | text | |
| 17 | Bank_Fee_Subtotal | number | |
| 18 | Bank_Fee_VAT | number | |
| 19 | Bank_Fee_Total | number | |
| 20 | Folder_Path | text | hyperlink tới thư mục hồ sơ |
| 21 | Notes | text | |
| + | *Currency* | text | **bổ sung** — bắt buộc nếu có hoá đơn USD |
| + | *Reviewed* | bool | **bổ sung** — ai đã duyệt, khi nào |
| + | *Text_Source* | text | **bổ sung** — cảnh báo dữ liệu từ OCR |

Ô trống = dữ liệu không đọc được. **Không điền 0, không điền "N/A".** Freeze panes dòng 1, AutoFilter toàn bộ.

### Sheet 2 — `CHUNG_TU` (1 dòng = 1 PDF, kể cả UNKNOWN / ERROR / DUPLICATE)

Đúng 17 cột bạn liệt kê, bổ sung `Text_Source`, `File_Hash`, `Page_Count`, `Processing_Status`. Đây là sheet đối chiếu "300 file vào — 300 dòng ra", đảm bảo không file nào biến mất im lặng.

### Sheet 3 — `MISA_IMPORT` (1 dòng = 1 **dòng hạch toán**, không phải 1 hồ sơ)

Đây là khác biệt quan trọng về nghiệp vụ: một bộ chứng từ sinh ra nhiều bút toán. Mẫu đề xuất cho 1 hồ sơ (chờ bạn xác nhận — Q6, Q7):

| Dòng | Diễn giải | TK Nợ | TK Có | Số tiền |
|---|---|---|---|---|
| 1 | Chi phí quảng cáo Facebook, ref ABC123 | `6417` | `1121` | Meta_Subtotal |
| 2 | Thuế GTGT đầu vào của phí quảng cáo (nếu có) | `1331` | `1121` | Meta_VAT |
| 3 | Phí dịch vụ ngân hàng VPBank | `6427` | `1121` | Bank_Fee_Subtotal |
| 4 | Thuế GTGT đầu vào phí ngân hàng | `1331` | `1121` | Bank_Fee_VAT |

Cột theo đúng danh sách bạn nêu (`So_chung_tu`, `Ngay_chung_tu`, `Ngay_hach_toan`, `Ma_doi_tuong`, `Ten_doi_tuong`, `Dien_giai`, `TK_No`, `TK_Co`, `So_tien`, `Ma_so_thue`, `So_hoa_don`, `Ky_hieu_hoa_don`, `Ngay_hoa_don`, `Tien_truoc_thue`, `Thue_suat`, `Tien_VAT`, `Reference`, `Transaction_ID`, `Card_Last4`, `HoSo_ID`).

**Cơ chế flexible (không hard-code MISA):** toàn bộ sheet này do `config/misa_mapping.yaml` điều khiển:

```yaml
version: 1
sheet_name: MISA_IMPORT
lines:                                  # định nghĩa các bút toán sinh ra từ 1 dossier
  - id: marketing_expense
    condition: "meta.subtotal is not None and meta.subtotal > 0"
    debit_account:  "${accounts.marketing_expense}"
    credit_account: "${accounts.bank}"
    amount: "meta.subtotal"
    description: "Chi phi quang cao Facebook - ref ${dossier.reference}"
  - id: marketing_input_vat
    condition: "meta.vat_amount is not None and meta.vat_amount > 0"
    ...
columns:                                # thứ tự & tên cột đúng file mẫu MISA
  - header: "So_chung_tu"   source: "dossier.dossier_code"
  - header: "Ngay_hach_toan" source: "dossier.transaction_date"  format: "dd/mm/yyyy"
```

Khi bạn gửi file Excel mẫu import của MISA SME 2023, tôi chỉ cần sửa khối `columns` (đổi `header`, đổi thứ tự, thêm cột trống bắt buộc) — **không đụng tới code**. Sheet chỉ xuất các hồ sơ `VALID` (và `reviewed` nếu bật tuỳ chọn); hồ sơ lỗi không bao giờ lọt vào file import.

### Sheet 4 — `CHECK_ERROR` (1 dòng = 1 issue)

`HoSo_ID | Reference | Error_Code | Severity | Description | File_Name | Suggested_Action`.
Sắp xếp BLOCKING trước, WARNING sau. Ví dụ:

```
HS0012 | ABC123 | MISSING_DEBIT | BLOCKING | Không tìm thấy Debit Note cho reference ABC123 | -            | Kiểm tra sao kê VPBank ngày 24/07
HS0004 | DUP55TT| DUPLICATE_META| BLOCKING | 2 hoá đơn Meta cùng reference               | a.pdf; b.pdf | Chọn bản chính, gỡ bản trùng
-      | -      | REFERENCE_NOT_FOUND | BLOCKING | Không đọc được số tham chiếu       | file088.pdf  | Mở file kiểm tra thủ công / bật OCR
```

*(Bổ sung khuyến nghị: Sheet 5 `TONG_HOP` — tổng số hồ sơ, tổng tiền theo trạng thái, để kế toán đối chiếu nhanh với sổ ngân hàng.)*

---

## 10. CẤU TRÚC THƯ MỤC XUẤT

```
OUTPUT/
    HS000001_ABC123XYZ/
        01_META_INVOICE.pdf
        02_VPBANK_DEBIT_NOTE.pdf
        03_VPBANK_VAT_INVOICE.pdf
        _manifest.txt              # tên file gốc, đường dẫn gốc, SHA256 (truy vết)
    HS000002_XYZ987QWE/
        01_META_INVOICE.pdf
        02_VPBANK_DEBIT_NOTE.pdf
        _MISSING_03_VPBANK_VAT_INVOICE.txt
    NEEDS_REVIEW/
        HS000003_76NQZZMDK2/...
    UNMATCHED/
        REFERENCE_NOT_FOUND/file088.pdf
        UNKNOWN_TYPE/abc123.pdf
    DUPLICATES/
        <sha256-prefix>/file_a.pdf, file_b.pdf
    ACCOUNTING_RESULT_20260917_143210.xlsx
```

Chỉ `shutil.copy2`. Nếu tên thư mục trùng: thêm hậu tố `_2`, `_3`, ghi log, không ghi đè. Nếu `reference = None`: tên thư mục là `HS000003_NOREF`.

---

## 11. NHỮNG RỦI RO ĐÃ NHẬN DIỆN

| # | Rủi ro | Mức | Giảm thiểu |
|---|---|---|---|
| R1 | Token sau `FACEBK` trong diễn giải VPBank **không phải** reference Meta ở mọi mẫu | **CAO** | Chờ 3 PDF mẫu; viết regex có anchor keyword + charset + độ dài từ config; nếu không chắc ⇒ `None` |
| R2 | 1 debit note gộp nhiều giao dịch Meta | CAO | Cần xác nhận (Q2). Nếu có, model phải cho phép 1 debit thuộc N dossier ⇒ `dossier_documents` đã sẵn sàng N-N |
| R3 | Hoá đơn Meta bằng USD, debit bằng VND | TRUNG BÌNH | Lưu `currency` riêng; `AMOUNT_MISMATCH` hạ thành INFO khi khác currency; chờ luật tỷ giá (Q5) |
| R4 | PDF scan ⇒ OCR sai ký tự reference (O/0, I/1) | CAO | Không tự sửa ký tự. Đánh dấu `OCR_SOURCED_DATA`, buộc review thủ công |
| R5 | Font tiếng Việt trong PDF trích ra bị lỗi dấu | TRUNG BÌNH | Chuẩn hoá NFC + so khớp keyword cả bản có dấu và bản không dấu |
| R6 | Reference xuất hiện nhiều lần trong 1 file (ví dụ cả header và footer) | THẤP | Rule có thứ tự ưu tiên; nếu 2 giá trị khác nhau ⇒ `REFERENCE_AMBIGUOUS` ⇒ review |
| R7 | PyInstaller + PaddleOCR làm EXE > 1 GB | TRUNG BÌNH | Mặc định dùng Tesseract (nhẹ, offline, có gói tiếng Việt); Paddle là tuỳ chọn cài rời |

---

## 12. TIÊU CHÍ HOÀN THÀNH PHASE 2 (để thống nhất trước)

- `normalize_reference()` pass toàn bộ test trong §29, đặc biệt `ABC123` vs `ABCI23` ⇒ NO MATCH.
- Mỗi extractor chạy được trên fixture text của PDF mẫu, mọi field trả về `ExtractedField` có `raw_snippet`.
- Classifier đạt 100% trên 3 file mẫu và trả `UNKNOWN` (không đoán bừa) với file lạ.
- `pytest` chạy xanh, coverage domain ≥ 90%.
- Chưa cần GUI, chưa cần DB.

---

## 13. CÂU HỎI NGHIỆP VỤ CẦN BẠN XÁC NHẬN

**Nhóm A — Chặn Phase 2 (bắt buộc trả lời trước khi viết regex)**

- **Q1.** Gửi 3 PDF mẫu (1 Meta, 1 Debit Note, 1 VAT Invoice của **cùng một bộ**). Cần xác nhận: chuỗi đứng sau `FACEBK` trong phần *Diễn giải* của debit note **đúng là** giá trị của `Số tham chiếu` trên hoá đơn Meta? Nếu 3 file mẫu cho thấy 2 giá trị khác nhau, tôi sẽ báo `REFERENCE_MISMATCH` chứ không sửa luật để ép khớp.
- **Q2.** Một Debit Note có bao giờ tương ứng với **nhiều** hoá đơn Meta (thanh toán gộp) không? Và một hoá đơn GTGT phí ngân hàng có bao giờ gộp phí của nhiều giao dịch không? Câu trả lời quyết định quan hệ 1-1 hay 1-N.
- **Q3.** Reference Meta có bao giờ chứa **dấu cách hoặc dấu gạch ngang** ở giữa (ví dụ `76NQ ZZMD K2`) không? Mặc định tôi xoá toàn bộ space bên trong — nếu reference thật có dấu gạch ngang thì tôi phải giữ lại.
- **Q4.** Định dạng chuẩn của reference: độ dài cố định? Chỉ gồm `A-Z` và `0-9`? Bạn cho vài ví dụ thật (đã che thông tin nhạy cảm) để tôi đặt pattern kiểm tra.

**Nhóm B — Ảnh hưởng tới Excel / MISA**

- **Q5.** Hoá đơn Meta ghi bằng **VND hay USD**? Nếu USD: tỷ giá hạch toán lấy ở đâu (ghi trên debit note, hay nhập tay)? Ứng dụng có được phép tự tính `VND = USD × rate` không, hay chỉ lấy số VND thực tế ghi trên debit note?
- **Q6.** Meta Platforms Ireland là nhà thầu nước ngoài. Bộ chứng từ này có phát sinh **thuế nhà thầu (FCT)** cần hạch toán không, hay chỉ hạch toán chi phí + phí ngân hàng? Nếu có, TK nào và tính trên cơ sở nào?
- **Q7.** Xác nhận sơ đồ bút toán ở §9 Sheet 3 (4 dòng) đúng với thực tế công ty bạn chưa? Đặc biệt: phí ngân hàng hạch toán vào `6427` hay `6417`? VAT của Meta có được khấu trừ (`1331`) không?
- **Q8.** Gửi **file Excel mẫu import của MISA SME 2023** (chứng từ Nghiệp vụ khác / Mua dịch vụ). Chưa có file này tôi sẽ không hard-code bất kỳ tên cột nào.
- **Q9.** `Ma_doi_tuong` / `Ten_doi_tuong` lấy theo nhà cung cấp (Meta / VPBank) hay theo mã đối tượng có sẵn trong MISA? Nếu có sẵn, bạn cho danh mục mã.
- **Q10.** `So_chung_tu` dùng mã hồ sơ `HS000001` hay theo dải số chứng từ riêng của công ty (ví dụ `MKT07/001`)? Có reset theo tháng/năm không?

**Nhóm C — Vận hành**

- **Q11.** Trong ~300 file có file PDF scan (không có lớp text) không? Nếu không có, tôi để `ocr_enabled = false` mặc định ⇒ EXE nhẹ hơn nhiều.
- **Q12.** Có PDF nào đặt mật khẩu / bị khoá không?
- **Q13.** Một PDF có bao giờ chứa **nhiều chứng từ** (ví dụ 1 file gộp 5 debit note) không? Nếu có, cần thêm bước tách trang — ảnh hưởng lớn tới thiết kế, cần biết sớm.
- **Q14.** Phần mềm chạy 1 máy hay nhiều kế toán dùng chung thư mục mạng? (Quyết định SQLite local hay cần khoá ghi.)
- **Q15.** Windows phiên bản nào (10/11, 64-bit)? Có quyền cài đặt hay chỉ được chạy file EXE portable?
- **Q16.** Tên công ty + MST của bạn (để app tự kiểm tra `TAX_CODE_MISMATCH` trên hoá đơn VPBank). Có thể nhập trong Settings, không cần hard-code.

---

## 14. ĐỀ XUẤT BƯỚC TIẾP THEO

1. Bạn xác nhận/chỉnh sửa tài liệu này.
2. Bạn gửi **3 PDF mẫu** (Q1) — tôi sẽ trích text thô, dán lại cho bạn xem *chính xác* app đọc được gì, rồi mới viết regex.
3. Trả lời Q2–Q4 (chặn Phase 2). Q5–Q10 có thể trả lời muộn hơn, trước Phase 5.
4. Sau khi bạn duyệt, tôi bắt đầu **Phase 2**: models, config, PDFReader, classifier, 3 extractor, unit tests.

**Phase 1 kết thúc tại đây. Chờ xác nhận của bạn trước khi viết code.**
