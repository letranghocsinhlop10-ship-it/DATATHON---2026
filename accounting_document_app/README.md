# Marketing Accounting Document Tool

Ứng dụng desktop Windows đọc, phân loại, ghép bộ chứng từ PDF chi phí
Marketing và xuất dữ liệu Excel phục vụ hạch toán.

**Trạng thái: PHASE 5 hoàn thành** — xuất Excel 4 sheet và sắp xếp PDF theo
hồ sơ đã chạy, kiểm chứng bằng cách bấm nút thật qua GUI (không chỉ gọi
service) trên toàn bộ 4 bước SCAN → MATCH → ORGANIZE → EXPORT với 3 PDF
thật, mở lại file .xlsx bằng openpyxl để đối chiếu từng ô với số liệu gốc.

---

## Nguyên tắc chi phối

| # | Nguyên tắc | Thể hiện trong code |
|---|-----------|---------------------|
| 1 | Không suy đoán dữ liệu | Không đọc được ⇒ `value is None` kèm mã lỗi. Không có giá trị mặc định ngầm. |
| 2 | Không ghép sai còn hơn không ghép | `references_match()` chỉ so sánh chuỗi tuyệt đối. Không fuzzy, không AI. |
| 3 | Mọi con số truy vết được về PDF gốc | Mỗi `ExtractedField` mang theo trang, vị trí ký tự, đoạn text gốc, id rule. |

---

## Cài đặt và chạy test

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
pytest                          # 290 test + doctest
```

Chạy ứng dụng:

```bash
python main.py
```

Chạy thêm bộ test trên **PDF thật** (không kèm trong repo — repo công khai):

```bash
set ACCOUNTING_SAMPLE_DIR=C:\KETOAN\MAU
pytest tests/test_real_samples.py tests/test_ui_smoke.py
```

Test GUI chạy trên Qt thật ở chế độ ``offscreen`` (không cần màn hình) —
không phải chỉ kiểm tra cú pháp dựng widget.

---

## Kiến trúc

```
app/
  models/        Document · Dossier · ExtractedField · enums   (thuần dữ liệu)
  core/          PDFReader · layout · classifier · voucher_splitter
                 text_normalizer · duplicate_detector
  extractors/    rule_engine · 3 extractor · registry          (trích xuất)
  matching/      reference_matcher · dossier_builder ·         (ghép bộ)
                 dossier_validator · candidate_suggester
  database/      Database (schema SQLite) · document_repository ·
                 dossier_repository · settings_repository ·
                 processing_run_repository
  exporters/     excel_exporter (4 sheet) · misa_exporter          (xuất)
                 (template ${accounts.*}/${meta.*}) · pdf_organizer
  services/      scan_service · match_service · export_service ·
                 organize_service                  (điều phối pipeline)
  ui/            main_window · dossier_detail_window · review_window ·
                 document_preview · settings_window · workers (QThread) ·
                 view_models (thuần, không Qt) · widgets/status_badge
  utils/         money · date · file · string · logging
  config_loader  nạp + kiểm tra YAML (kể cả accounting.yaml, misa_mapping.yaml)
config/          toàn bộ LUẬT NGHIỆP VỤ (không có luật nào nằm trong code)
tests/           339 test, fixture đã che số liệu
docs/            tài liệu thiết kế Phase 1 + phân tích file mẫu + MISA
main.py          điểm vào ứng dụng
```

Chiều phụ thuộc hướng vào trong: `models` không import gì, `core`/`extractors`
không import PySide6, không import sqlite3. Toàn bộ luật nghiệp vụ test được
mà không cần PDF thật, không cần giao diện.

### Thêm ngân hàng / nhà cung cấp mới

Không sửa code sẵn có:

1. Thêm một khối vào `config/document_rules.yaml` (luật phân loại).
2. Thêm một khối vào `config/extraction_rules.yaml` (regex + định dạng tiền).
3. Nếu cần hậu xử lý riêng: viết lớp con `BaseExtractor`, đăng ký ở
   `app/extractors/registry.py`.

---

## Xuất kết quả

* `ExcelExporter` — 4 sheet đúng §22 Phase 1: `HO_SO` (1 dossier/dòng),
  `CHUNG_TU` (1 PDF/dòng, kể cả chưa ghép/lỗi/trùng — không file nào biến
  mất im lặng), sheet MISA (tên lấy từ `misa_mapping.yaml`), `CHECK_ERROR`
  (BLOCKING trước, WARNING/INFO sau). Tiền luôn ghi số thật (`int` khi VND
  nguyên đồng) để Excel `SUM()` được trực tiếp — không bao giờ ghi chuỗi.
* `MisaExporter` — template hai lớp: `${accounts.*}`/`${parameters.*}`
  resolve TĨNH lúc nạp config; `${meta.*}`/`${bank_vat.*}` resolve ĐỘNG theo
  từng dossier lúc xuất. `condition`/`amount` là biểu thức hạn chế
  (`role.field`), không dùng `eval()` trên dữ liệu PDF. Số tiền luôn lấy từ
  hoá đơn — không bao giờ tự tính lại theo thuế suất.
* `PdfOrganizer` — chỉ `shutil.copy2`, không sửa/xoá/di chuyển file gốc.
  Hồ sơ thiếu chứng từ → `_MISSING_0N_<ROLE>.txt`; trùng chứng từ → giữ lại
  TẤT CẢ kèm hậu tố `_a`/`_b`, không tự chọn bản chính; file trùng byte
  (SHA256) → `DUPLICATES/<hash-prefix>/`, tách biệt `UNMATCHED/<lý do>/`.

**Kiểm chứng bằng bấm nút GUI thật, không chỉ gọi service:** test tích hợp
lái đúng cả 4 nút (SCAN → MATCH → ORGANIZE → EXPORT) qua worker thread trên
3 PDF thật, rồi mở lại `.xlsx` bằng `openpyxl` đối chiếu từng ô — số tiền
trong sheet MISA khớp chính xác dữ liệu gốc (2.300.611 / 230.061 / 25.307 /
2.531), thư mục `OUTPUT/HS000001_.../01_META_INVOICE.pdf` chứa đúng file,
và MD5 file gốc không đổi sau khi tổ chức lại.

## Giao diện — điều phối, không chứa logic nghiệp vụ

* `app/services/` ghép các module Phase 2–3 thành hai bước gọi được:
  `ScanService.scan_folder()` và `MatchService.match_run()`. GUI, CLI hay
  test đều gọi service này — không lặp logic điều phối ở nhiều nơi.
* `app/ui/workers.py` bọc service bằng `QThread` để không block UI; huỷ là
  **hợp tác** (`request_cancel()` chỉ bật cờ, dừng SAU file đang xử lý,
  không kill thread giữa chừng).
* `app/ui/view_models.py` thuần Python, không import PySide6 — chuyển
  `Dossier`/`Document` thành dữ liệu hiển thị, test được không cần Qt.
* `MainWindow` → `DossierDetailWindow` (double-click) → `ReviewWindow`
  (chứng từ chưa ghép, gợi ý ghép tay) → `SettingsWindow` — đúng theo
  wireframe §8 Phase 1. Ghép tay ở `ReviewWindow` luôn tạo dossier
  `NEEDS_REVIEW` + `match_source=MANUAL`, không bao giờ tự thành `VALID`.

**Một bug thread-safety thật đã bị bắt bởi test tích hợp GUI**: `sqlite3`
mặc định cấm dùng chung connection giữa các thread; `ScanWorker` chạy trong
`QThread` riêng nhưng dùng chung `Database` tạo ở main thread. Test lái
đúng luồng bấm SCAN → chờ worker → bấm MATCH trên PDF thật đã phát hiện lỗi
này ngay (`sqlite3.ProgrammingError`) — sửa bằng `check_same_thread=False`,
an toàn vì UI khoá nút bấm suốt lúc worker chạy nên không bao giờ có hai
thread cùng đụng DB một lúc.

## Ghép bộ hồ sơ — luật K1/K2 cho hoá đơn GTGT

Ghép bằng SO SÁNH CHUỖI TUYỆT ĐỐI duy nhất (`==`), không fuzzy, không AI:

* **META ↔ DEBIT**: `normalize(meta.reference_number) == normalize(debit.meta_reference)`
* **VAT** gắn vào bộ khi thoả ít nhất một trong hai khoá:
  * K1: `vat.bank_transaction_code == debit.transaction_code` (tách từ
    chính `Số tham chiếu` của hoá đơn VPBank)
  * K2: `vat.meta_reference == meta.reference_number` (khoá chính — đã
    kiểm chứng trên 3 file mẫu, khớp 100%)
* K1 và K2 **mâu thuẫn nhau** (trỏ hai bộ khác nhau) ⇒ `VAT_KEY_CONFLICT`,
  ép về `NEEDS_REVIEW` dù đủ ba chứng từ — không bao giờ tự chọn.
* `CandidateSuggester` chỉ **gợi ý** ghép tay bằng tín hiệu phụ (cùng thẻ,
  cùng ngày, cùng tiền) — không có đường code nào để gợi ý tự trở thành
  liên kết đã ghép.

## Ba đặc điểm của chứng từ thật mà code phải xử lý

Rút ra từ phân tích file mẫu (`docs/PHASE1_ADDENDUM_SAMPLE_ANALYSIS.md`):

1. **Thứ tự text của hoá đơn GTGT VPBank bị đảo** — giá trị được vẽ trước
   nhãn, và không nhất quán giữa các dòng. Regex tuyến tính lấy sai giá trị.
   ⇒ Loại chứng từ này dùng chiến lược `label_right` (tìm ô chữ của nhãn, lấy
   chữ bên phải cùng dòng). Xem `app/core/layout.py`.

2. **Dấu phân cách nghìn khác nhau giữa ba loại chứng từ** — Meta dùng dấu
   chấm, debit note dùng dấu phẩy. Đoán sai là sai 1000 lần.
   ⇒ Khai báo cứng trong `config/extraction_rules.yaml`; gặp chuỗi nhập nhằng
   thì `AmountAmbiguousError`, không đoán.

3. **Một file PDF có thể chứa nhiều chứng từ** — xử lý cả file như một chứng
   từ sẽ khiến regex lấy nhầm dữ liệu của chứng từ khác.
   ⇒ `VoucherSplitter` cắt file theo `page_start_markers`; trang không có
   marker được coi là trang tiếp theo của chứng từ liền trước (nhờ vậy hoá
   đơn Meta 2 trang không bị cắt đôi). Không tìm thấy marker thì giữ nguyên
   cả file — không đoán chỗ cắt.

4. **Diễn giải bị ngắt dòng và thiếu dấu cách** — hai chứng từ trong cùng một
   bộ ghi `thanh toan tai` và `thanh toantai`.
   ⇒ Regex chỉ neo vào từ khoá nhà cung cấp (`FACEBK`), chạy trên text đã gộp
   dòng. Đuôi mô tả là *kỳ vọng được kiểm tra*, không phải điều kiện bắt buộc.

---

## Kiểm thử ở quy mô lớn (Phase 6)

Repo chỉ có 3 PDF thật, không có 300 file thật của công ty. Để vẫn kiểm tra
được hành vi ở quy mô thật, `tests/test_stress_synthetic.py` **sinh PDF tổng
hợp** bằng PyMuPDF — đúng cấu trúc/nhãn/regex đã reverse-engineer từ 3 file
mẫu thật, nhưng số liệu hoàn toàn giả — rồi chạy nguyên vẹn pipeline
scan → match → export → organize qua đó, không phải qua script thủ công.

Hai cấp độ, cùng chạy qua `pytest`:

* `TestQuyMoNho` — ~30 file, chạy mặc định (smoke nhanh, không cần biến môi
  trường nào).
* `TestQuyMo300File` — đúng 300 file, chỉ chạy khi đặt
  `ACCOUNTING_STRESS_TEST=1`:

  ```bash
  ACCOUNTING_STRESS_TEST=1 pytest tests/test_stress_synthetic.py -v
  ```

  Kết quả đã xác nhận: 300 file → 99 bộ hồ sơ (95 VALID, 3 MISSING_VAT,
  1 DUPLICATE_META — phát sinh tự nhiên từ một file trùng byte-for-byte,
  đúng thiết kế "byte-duplicate cũng là business-duplicate"). 4 file không
  liên quan (không khớp được tham chiếu nào) không bị gán bừa vào bộ hồ sơ
  nào — đúng nguyên tắc "không đoán, không tự ghép". Toàn bộ 300 file PDF
  được copy đúng vị trí trong `OUTPUT/`, không file nào bị mất. Tổng thời
  gian pipeline (scan + match + export + organize) ~4 giây — không có dấu
  hiệu độ phức tạp bậc hai (O(n²)) ở quy mô này.

  Lưu ý riêng khi viết bộ sinh dữ liệu: font Base14 mặc định của
  `page.insert_text()` trong PyMuPDF không có glyph tiếng Việt có dấu (âm
  thầm thay bằng `·`), làm hỏng mọi regex trích xuất của các file debit
  note tổng hợp. Đây là lỗi của *bộ sinh dữ liệu kiểm thử*, không phải lỗi
  của ứng dụng — khắc phục bằng cách chỉ định tường minh
  `fontname="dejavu", fontfile=".../DejaVuSans.ttf"` cho mọi lệnh chèn chữ.

---

## Lộ trình

| Phase | Nội dung | Trạng thái |
|---|---|---|
| 1 | Phân tích, kiến trúc, schema, thiết kế | ✅ `docs/PHASE1_ARCHITECTURE.md` |
| 1b | Phân tích 3 PDF mẫu | ✅ `docs/PHASE1_ADDENDUM_SAMPLE_ANALYSIS.md` |
| 1c | Phân tích file MISA thật | ✅ `docs/PHASE1_ADDENDUM_MISA_TEMPLATE.md` |
| 2 | Models, config, PDFReader, classifier, 3 extractor, test | ✅ |
| 2b | Tách PDF gộp nhiều chứng từ + mapping MISA | ✅ |
| 3 | Reference matcher, dossier builder/validator, SQLite | ✅ |
| 4 | Giao diện PySide6 | ✅ |
| 5 | Excel exporter, PDF organizer | ✅ |
| 6 | Kiểm thử ở quy mô ~300 file | ✅ `tests/test_stress_synthetic.py` |
| 7 | Đóng gói EXE bằng PyInstaller | ⏳ |

---

## Sơ đồ hạch toán (theo file MISA thật của công ty)

Một hoá đơn Meta sinh **đúng 2 dòng**, cả hai đều `6417 / 331`, đối tượng Có
là MST Việt Nam của Meta:

| Dòng | Nội dung | TK Nợ | TK Có | Số tiền |
|---|---|---|---|---|
| 1 | Chi phí quảng cáo | 6417 | 331 | `Tổng phụ` trên hoá đơn |
| 2 | Thuế GTGT | 6417 | 331 | `VAT` trên hoá đơn |

Không kê khai thuế GTGT đầu vào (toàn bộ nhóm cột thuế của MISA bỏ trống).
Số thuế **luôn lấy từ hoá đơn**, không tự tính `tổng phụ × thuế suất`.

## Câu hỏi nghiệp vụ còn mở

* **Q19** — Phí dịch vụ ngân hàng VPBank hạch toán ở đâu? File MISA mẫu không
  có dòng nào cho phí này. Hiện `bank_fee_*` để `enabled: false`.
* **Q20** — Bút toán chi tiền `331 / 1121` căn cứ Debit Note có cần app xuất
  không, hay kế toán làm riêng?
* **Q21** — Số chứng từ bắt đầu mỗi đợt import: nhập tay hay app nhớ số cuối?
* **Q22** — Mã `Đối tượng Có` cho nhà cung cấp mới lấy từ đâu?
* **Q14 / Q15** — Chạy một máy hay thư mục mạng; phiên bản Windows.

---

## Lưu ý bảo mật

Repo này **công khai**. Không commit:

* file PDF chứng từ thật (`.gitignore` đã chặn `*.pdf`)
* fixture chứa MST, số tài khoản, CIF, mã giao dịch, tên khách hàng thật
* file database và log

Fixture trong `tests/fixtures/` giữ nguyên **cấu trúc** (nhãn, thứ tự, dấu
phân cách, cả lỗi thiếu dấu cách) nhưng mọi **giá trị** đều là số giả.
