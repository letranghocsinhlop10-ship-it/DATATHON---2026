# Công cụ xử lý bộ chứng từ kế toán (Facebook Bill / Hóa đơn VAT / Giấy báo nợ NH)

Tool tự động: nhận diện loại chứng từ từ PDF (không cần đổi tên file), trích xuất dữ liệu, ghép 3 loại chứng từ theo **số tham chiếu**, đối chiếu chéo, kiểm tra hợp lệ, phân loại vào thư mục OUTPUT, và xuất 2 file Excel (bảng nhập MISA + báo cáo đối chiếu) — qua một Web UI đơn giản.

> Kế hoạch triển khai đầy đủ (kiến trúc, data model, các quyết định thiết kế) nằm trong lịch sử trao đổi lúc lập plan; tài liệu này chỉ tập trung vào cách cài đặt/vận hành.

## 1. Cài đặt

Yêu cầu: Python 3.11+.

```bash
cd doc-processor
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### OCR (tuỳ chọn)

PDF chủ yếu là văn bản gốc nên OCR chỉ là fallback. Nếu muốn xử lý PDF dạng scan/ảnh chụp, cài thêm Tesseract (không phải gói pip):

- Ubuntu/Debian: `sudo apt install tesseract-ocr tesseract-ocr-vie tesseract-ocr-eng`
- macOS: `brew install tesseract tesseract-lang`
- Windows: cài từ https://github.com/UB-Mannheim/tesseract/wiki

Nếu không cài, tool **không crash** — các trang không có text layer sẽ được đánh dấu cảnh báo và đưa vào diện cần xem lại thủ công.

## 2. Chạy Web UI

```bash
uvicorn app.main:app --reload
```

Mở http://127.0.0.1:8000/. Giao diện:

1. **Nhập file** — kéo-thả hoặc bấm "chọn file" để chọn nhiều file `.pdf` / `.zip` / `.xlsx` / `.xls` cùng lúc, rồi bấm **Tải file lên**. Tool tự nhận diện loại chứng từ qua nội dung, **không cần** đặt tên hay sắp xếp file trước. File `.zip` (hóa đơn điện tử PDF+XML nén sẵn) được tự động giải nén; file `.xlsx`/`.xls` được hiểu là **danh sách số tham chiếu cần đối chiếu** (xem mục 4). Sau khi tải lên, ô "Input Folder" tự điền — không cần biết đường dẫn thật trên server.
   - Nếu bạn đang chạy tool ngay trên máy có sẵn thư mục dữ liệu, có thể bỏ qua bước upload và mở phần "Hoặc nhập đường dẫn thư mục có sẵn trên máy chủ" để gõ trực tiếp đường dẫn (ví dụ `INPUT`) — cách này cũng tự động giải nén mọi file `.zip` tìm thấy trong thư mục.
2. Bấm **Process Documents** — progress bar cập nhật theo thời gian thực.
3. Xem **Summary** (Total files / Complete sets / Incomplete / Valid / Errors / Duplicates) và bảng **Preview** (Reference | Status | Issue | Amount | Folder).
4. **Export MISA Excel** / **Export Reconciliation Report** để tải 2 file `.xlsx`. **View Errors** để lọc riêng các bộ có vấn đề. **Open Output Folder** cố gắng mở trình quản lý file của máy đang chạy server (chỉ có tác dụng khi chạy local); nếu không mở được, đường dẫn tuyệt đối sẽ hiển thị để copy thủ công.

## 3. Chạy không cần UI (script/CI)

```python
from app.pipeline import run_pipeline

document_sets, summary = run_pipeline("INPUT", "OUTPUT")
print(summary)
```

## 4. Cấu trúc thư mục Input/Output

```
INPUT/
├── facebook/   # PDF bất kỳ tên, tool tự nhận diện qua nội dung
├── vat/        # có thể kèm .xml cùng tên (hóa đơn điện tử VN) — tool ưu tiên đọc XML để lấy số liệu chính xác hơn PDF
├── bank/
├── *.zip       # tự động giải nén tại chỗ (không cần giải nén tay), dù nằm ở gốc hay trong facebook/vat/bank/
└── *.xlsx|*.xls  # (tuỳ chọn) danh sách số tham chiếu cần đối chiếu — xem bên dưới

OUTPUT/
├── 01_VALID/<reference>/{01_Facebook.pdf, 02_VAT_Invoice.pdf(+.xml), 03_Bank_Debit.pdf}
├── 02_MISSING_REFERENCE/
├── 03_MISSING_TAX_CODE/
├── 04_PAYMENT_METHOD_ERROR/
├── 05_AMOUNT_MISMATCH/
├── 06_INCOMPLETE_DOCUMENT/<reference>/{... , MISSING_0X_<Loại>.txt}
├── 07_DUPLICATE/<reference>/{..., DUPLICATE_0X_<Loại>_2.pdf}
├── 08_OTHER_ERROR/<reference>/{file gốc, ERROR_REASON.txt}
├── 09_MISSING_ALL_DOCUMENTS/<reference>/{MISSING_01/02/03_*.txt}   # có trong danh sách Excel nhưng không tìm thấy PDF nào
├── misa_import.xlsx
├── reconciliation_report.xlsx      # có thêm sheet "Reference List Check" nếu có nộp file Excel danh sách
└── .manifest/state.json        # sổ theo dõi nội bộ để chạy lại không tạo trùng file/folder
```

File PDF/Excel gốc **không bao giờ** bị sửa hay xoá — mọi thao tác trong OUTPUT chỉ là copy.

### Danh sách tham chiếu để đối chiếu (Excel, tuỳ chọn)

Nếu bạn có sẵn danh sách các giao dịch cần có chứng từ (ví dụ export từ sao kê ngân hàng hoặc file theo dõi nội bộ), thả file `.xlsx`/`.xls` đó vào cùng input — tool tự nhận diện (không cần đặt ở thư mục riêng) và đối chiếu:

- Chỉ **bắt buộc** một cột chứa số tham chiếu — tên cột linh hoạt, tự nhận diện các biến thể như `Reference`, `Số tham chiếu`, `Ref`, `Mã giao dịch`... (không phân biệt hoa/thường, có/không dấu).
- Có thể thêm cột số tiền kỳ vọng (`Amount`, `Số tiền`, `Tổng tiền`...) để tool so sánh với số tiền trích xuất được (cùng ngưỡng dung sai % như đối chiếu 3 chứng từ).
- Mỗi dòng trong danh sách sẽ có 1 trong 3 kết quả: **FOUND** (khớp, số liệu đúng), **AMOUNT_MISMATCH** (khớp reference nhưng số tiền lệch), **NOT_FOUND** (không tìm thấy chứng từ PDF nào — được tạo thành một mục riêng trong `09_MISSING_ALL_DOCUMENTS/` để không bị bỏ sót).
- Không nộp file Excel nào → hành vi giữ nguyên như trước, không ảnh hưởng workflow thuần PDF.

## 5. File cấu hình (chỉnh không cần sửa code)

| File | Dùng để |
|---|---|
| `config/settings.yaml` | Đường dẫn mặc định, tham số OCR, ngưỡng dung sai đối chiếu (amount %, số ngày lệch), thứ tự ưu tiên phân loại folder |
| `config/extraction_patterns.yaml` | Từ khoá/regex nhận diện loại chứng từ và trích xuất từng field, theo từng loại chứng từ |
| `config/validation_rules.yaml` | Danh sách rule kiểm tra hợp lệ (PASS/FAIL/WARNING/NOT_FOUND), có thể thêm rule mới cho field đã có sẵn trên `ExtractedDocument` mà không cần sửa code |
| `config/misa_column_mapping.yaml` | **Mapping layer** cho bảng xuất MISA — hiện là placeholder theo danh sách cột đề xuất; khi có file mẫu import thật của MISA, chỉ cần sửa tên/thứ tự cột trong file này |

## 6. Kiến trúc module

```
Zip auto-extract (app/zip_utils.py)
  → PDF Reader (app/pdf/reader.py)
  → OCR fallback (app/pdf/ocr.py)
  → Document Classifier (app/classification/classifier.py)
  → Data Extractor (app/extraction/*)
  → Reference Matcher (app/matching/reference_matcher.py)
  → Reference List cross-check (app/reference_list/*, chỉ chạy nếu có file Excel)
  → Reconciliation Engine (app/reconciliation/engine.py)
  → Validation Engine (app/validation/engine.py)
  → Categorizer (app/organizing/categorizer.py)
  → File Organizer (app/organizing/file_organizer.py)
  → Excel/MISA Exporter (app/export/*)
orchestrated by app/pipeline.py, phục vụ qua app/main.py (FastAPI) + static/ (UI)
Upload trình duyệt: app/api/routes_upload.py (POST /api/upload) — lưu file vào UPLOADS/<uuid>/ rồi trả về input_dir để dùng tiếp với /api/process
```

Điểm thiết kế quan trọng (rút ra từ việc hiệu chỉnh trên PDF thật):

- **Reference Matcher không so khớp bằng 1 field cố định.** Mỗi extractor trả về nhiều `reference_candidates` (field tường minh + mã nhúng trong nội dung/diễn giải); matcher union các document theo bất kỳ candidate trùng nhau (exact → fuzzy), vì thực tế 3 loại chứng từ hiếm khi in cùng một nhãn "số tham chiếu" giống hệt nhau.
- **Hóa đơn VAT ưu tiên đọc file XML kèm theo** (chuẩn hoá đơn điện tử VN) cho các trường số tiền/MST/ngày — PDF hiển thị có thể làm tròn/thiếu số 0 hàng nghìn tuỳ template, trong khi XML là dữ liệu ký số gốc.
- Amount/Date đối chiếu có **dung sai cấu hình được** (chênh lệch tỷ giá, ngày hoá đơn khác ngày giao dịch ngân hàng vài ngày).
- Chạy lại không tạo trùng: `OUTPUT/.manifest/state.json` theo dõi hash từng file đã copy.

## 7. Test

```bash
pytest
```

Bộ test dùng PDF tổng hợp (sinh bằng `reportlab`, dữ liệu giả) mô phỏng đúng cấu trúc các mẫu PDF thật đã dùng để hiệu chỉnh — không có dữ liệu khách hàng thật nào trong repo.
