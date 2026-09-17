# Marketing Accounting Document Tool

Ứng dụng desktop Windows đọc, phân loại, ghép bộ chứng từ PDF chi phí
Marketing và xuất dữ liệu Excel phục vụ hạch toán.

**Trạng thái: PHASE 2 hoàn thành** — nhân xử lý chứng từ (đọc PDF, phân loại,
trích xuất) đã chạy và có test. Chưa có giao diện, chưa có database, chưa có
ghép bộ hồ sơ (Phase 3–5).

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
pytest                          # 157 test + doctest
```

Chạy thêm bộ test trên **PDF thật** (không kèm trong repo):

```bash
set ACCOUNTING_SAMPLE_DIR=C:\KETOAN\MAU
pytest tests/test_real_samples.py
```

---

## Kiến trúc

```
app/
  models/        Document · ExtractedField · enums            (thuần dữ liệu)
  core/          PDFReader · layout · classifier              (đọc & nhận dạng)
                 text_normalizer · duplicate_detector
  extractors/    rule_engine · 3 extractor · registry         (trích xuất)
  utils/         money · date · file · string · logging
  config_loader  nạp + kiểm tra YAML
config/          toàn bộ LUẬT NGHIỆP VỤ (không có luật nào nằm trong code)
tests/           157 test, fixture đã che số liệu
docs/            tài liệu thiết kế Phase 1 + phân tích file mẫu
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

## Lộ trình

| Phase | Nội dung | Trạng thái |
|---|---|---|
| 1 | Phân tích, kiến trúc, schema, thiết kế | ✅ `docs/PHASE1_ARCHITECTURE.md` |
| 1b | Phân tích 3 PDF mẫu | ✅ `docs/PHASE1_ADDENDUM_SAMPLE_ANALYSIS.md` |
| 1c | Phân tích file MISA thật | ✅ `docs/PHASE1_ADDENDUM_MISA_TEMPLATE.md` |
| 2 | Models, config, PDFReader, classifier, 3 extractor, test | ✅ |
| 2b | Tách PDF gộp nhiều chứng từ + mapping MISA | ✅ |
| 3 | Reference matcher, dossier builder/validator, SQLite | ⏳ |
| 4 | Giao diện PySide6 | ⏳ |
| 5 | Excel exporter, PDF organizer, báo cáo lỗi | ⏳ |
| 6 | Kiểm thử trên 300 file thật | ⏳ |
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
