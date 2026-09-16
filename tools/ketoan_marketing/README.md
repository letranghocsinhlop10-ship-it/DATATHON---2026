# Tự động xử lý chứng từ chi phí Marketing (Meta Ads + Ngân hàng) → MISA SME 2023

Công cụ đọc file ZIP/PDF/XML chứng từ, ghép cặp theo **Số tham chiếu** và xuất bảng
hạch toán sẵn sàng import vào MISA SME 2023.

## Cài đặt

```bash
pip install pdfplumber pypdf openpyxl
```

## Sử dụng

```bash
python3 process_chungtu.py hoadon_meta.pdf baono_bank.pdf invoice.zip -o ketqua
```

Đầu vào chấp nhận: file ZIP (kể cả ZIP lồng nhau), PDF, XML hóa đơn điện tử, hoặc cả thư mục.

## Đầu ra (trong thư mục `-o`)

| File | Mô tả |
|---|---|
| `bang_hach_toan_misa.xlsx` | Bảng hạch toán, import thẳng vào MISA |
| `bang_hach_toan_misa.csv` | Bản CSV (UTF-8 BOM, mở đúng font trong Excel) |
| `bang_hach_toan_misa.md` | Bảng Markdown để xem nhanh |
| `Bo_Chung_Tu_<SoThamChieu>.pdf` | Bộ chứng từ gộp các trang cùng số tham chiếu |

## Logic ghép cặp

1. **Hóa đơn Meta** — bắt `Số tham chiếu: XXXXXXXXXX`, số hóa đơn `FBADS-...`, Tổng phụ / VAT / Tổng.
2. **Giấy báo nợ ngân hàng** — bắt mã trong diễn giải `FACEBK XXXXXXXXXX`, ngày giao dịch, số tiền.
3. **Hóa đơn GTGT điện tử VN** — đọc ưu tiên file `.xml` (chuẩn TCT: `SHDon`, `TgTCThue`,
   `TgTThue`, `TgTTTBSo`); file `.pdf` cùng tên gốc được coi là bản thể hiện và gộp làm một
   chứng từ, chỉ dùng để ghép bộ PDF.
4. Các chứng từ trùng số tham chiếu được gom thành một bộ. Thiếu vế nào thì cột
   `Trang_Thai_Gop` báo rõ `Thiếu file: ...`.

## Lưu ý về số liệu

- Số tiền trong **XML** hóa đơn điện tử dùng dấu `.` làm **dấu thập phân** (`696.000` = 696 đ),
  khác với bản thể hiện PDF. Script xử lý riêng hai định dạng này.
- Hóa đơn GTGT phí ngân hàng đi kèm được tách thành **bút toán độc lập** (Nợ 6427 / Nợ 1331 / Có 1121).
- PDF scan không có lớp text sẽ được cảnh báo `cần OCR` thay vì trả về số liệu sai.
