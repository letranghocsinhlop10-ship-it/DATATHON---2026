# PHỤ LỤC PHASE 1 — PHÂN TÍCH 3 PDF MẪU

> **CẢNH BÁO BẢO MẬT:** repository `DATATHON---2026` đang ở chế độ **PUBLIC**.
> Toàn bộ giá trị trong tài liệu này đã được **thay bằng placeholder giả**
> (`<REF10>`, `<FTCODE>`, `<CIF>`, `<MST_KH>`, `<SO_TK>`…), **kể cả số tiền**.
> Chỉ **cấu trúc** (nhãn, thứ tự, dấu phân cách, lỗi thiếu dấu cách) là thật — đó mới là
> thứ regex cần. Số liệu thật nằm trong 3 file PDF mẫu của bạn.
> **Không commit PDF chứng từ thật, không commit fixture chứa MST / số tài khoản /
> tên khách hàng thật vào repo này.** Xem §8.

Ngày phân tích: 2026-09-17 · Công cụ: PyMuPDF 1.28.2 · 3 file mẫu thuộc **cùng một bộ**.

---

## 1. KẾT LUẬN NHANH

| Hạng mục | Kết quả |
|---|---|
| Lớp text | **Cả 3 file đều có text layer thật** (1.190 / 1.694+928 / 1.403 ký tự). **Không cần OCR.** |
| Mã hoá / mật khẩu | Không. `is_encrypted = False` cả 3. |
| Q1 — chuỗi sau `FACEBK` có phải reference Meta? | ✅ **ĐÚNG. Khớp chính xác 100%.** |
| Q3 — reference có dấu cách/gạch ngang? | ❌ Không. 10 ký tự `[A-Z0-9]` liền mạch. |
| Q5 — tiền tệ | ✅ **Toàn bộ VND.** Không có USD, **không cần quy đổi tỷ giá.** |
| Q6 — thuế nhà thầu FCT | ✅ **Không khấu trừ** (hoá đơn Meta ghi rõ — xem §5). |
| Q11/Q12 — PDF scan / có mật khẩu | Không (trên mẫu này). |
| Rủi ro R1 (token sau FACEBK) | **Đã đóng.** |
| Rủi ro mới phát hiện | **3 rủi ro nghiêm trọng** — xem §3. |

---

## 2. CHUỖI KHOÁ GHÉP — ĐÃ KIỂM CHỨNG

### 2.1 Khoá chính (đúng như thiết kế §12 Phase 1)

```
META_INVOICE        "Số tham chiếu: <REF10>"                     -> <REF10>
VPBANK_DEBIT_NOTE   "...GD thanh toan tai FACEBK <REF10> DUBLIN IE" -> <REF10>   ✅ KHỚP
VPBANK_VAT_INVOICE  "Nội dung thanh toán (Payment detail):
                     ...GD thanh toantai FACEBK <REF10> DUBLIN IE"  -> <REF10>   ✅ KHỚP
```

Định dạng thực tế của reference trên mẫu: **10 ký tự, chỉ gồm `A-Z` và `0-9`**, viết hoa sẵn, không dấu cách, không gạch ngang.
⇒ Pattern kiểm tra đề xuất: `^[A-Z0-9]{8,16}$` (nới hơn 10 để an toàn, cấu hình được trong `app_settings.yaml`).

### 2.2 KHOÁ THỨ HAI — PHÁT HIỆN MỚI, phải sửa §13 của Phase 1

Hoá đơn GTGT phí ngân hàng có **trường reference riêng của nó**:

```
VPBANK_VAT_INVOICE  "Số tham chiếu (Reference): <FTCODE>_20260801"
VPBANK_DEBIT_NOTE   "Mã giao dịch/Transaction code: <FTCODE>"
```

Tức là `vat.reference_number  ==  debit.transaction_code + "_" + YYYYMMDD`.

**Đây là khoá mạnh hơn** khoá `FACEBK` để nối VAT invoice với Debit Note, vì nó là trường có nhãn rõ ràng của chính VPBank, không phải chuỗi trôi nổi trong diễn giải.

**Sửa lại luật ghép file thứ ba (thay cho §13 Phase 1):**

```
Ghép VAT_INVOICE vào dossier khi THOẢ MÃN ÍT NHẤT MỘT trong hai, bằng so sánh chuỗi TUYỆT ĐỐI:

  K1 (ưu tiên):  vat.reference_number.split("_")[0]  ==  debit.transaction_code
  K2          :  vat.meta_reference                  ==  meta.reference_number

  - K1 và K2 cùng khớp            -> ghép, link_source = AUTO_EXACT, confidence cao
  - Chỉ K1 khớp                   -> ghép, ghi issue INFO: META_REF_NOT_IN_VAT
  - Chỉ K2 khớp                   -> ghép, ghi issue INFO: FT_CODE_NOT_IN_VAT
  - K1 và K2 MÂU THUẪN            -> KHÔNG GHÉP, status = NEEDS_REVIEW,
                                     error VAT_KEY_CONFLICT  <-- luật an toàn §14 vẫn nguyên
  - Không khoá nào khớp           -> MISSING_BANK_VAT_INVOICE
```

Việc tách `_20260801` là **cắt chuỗi theo dấu `_` cố định**, không phải fuzzy match. Ngày phía sau dùng làm kiểm tra chéo (WARNING nếu ≠ ngày giao dịch).

### 2.3 Các trường đối chiếu phụ (chỉ để kiểm tra, KHÔNG dùng để ghép)

| Trường | Meta | Debit | VAT | Ghi chú |
|---|:---:|:---:|:---:|---|
| 4 số cuối thẻ | ✅ `····1234` | ✅ `So the 1111xxxx1234` | ✅ trong payment detail | trùng khớp cả 3 |
| Mã KH / CIF | — | ✅ `<CIF>` | ✅ `<CIF>` | trùng khớp |
| MST khách hàng | ✅ `<MST_KH_KIEU_META>` | — | ✅ `<MST_KH>` | **khác format** — xem §3.3 |
| Ngày | 1 tháng 8, 2026 | 01/08/2026 | 01/08/2026 | cùng ngày |

---

## 3. BA RỦI RO KỸ THUẬT MỚI (phải xử lý trong Phase 2)

### 3.1 🔴 NGHIÊM TRỌNG — Thứ tự text của hoá đơn VPBank bị ĐẢO so với bố cục

Trên `VPBANK_VAT_INVOICE`, PyMuPDF `get_text("text")` trả về **giá trị trước, nhãn sau**:

```
text thô thực tế:          bố cục thật trên giấy:
    <SO_HD>                   Ký hiệu (Serial):  <SERIAL>      (nhãn x=394, giá trị x=525)
    <SERIAL>                    Số (No.):          <SO_HD>
    01/08/2026                 Ngày hóa đơn:      01/08/2026
    Ký hiệu (Serial):
    Số (No.):
    Ngày hóa đơn (Date):
```

Và nó **không nhất quán**: dòng `Mã số thuế (Tax code): <MST_KH>` lại theo thứ tự nhãn→giá trị bình thường.

⇒ **Regex tuyến tính kiểu `Số tham chiếu \(Reference\):\s*(\S+)` sẽ TRẢ VỀ SAI GIÁ TRỊ trên file này.**
Với yêu cầu "không ghép sai chứng từ", đây là lỗi không chấp nhận được.

**Giải pháp đã prototype và kiểm chứng thành công — chiến lược `label_right`:**

```
1. Tìm bbox của nhãn:  page.search_for("Số tham chiếu")
2. Lấy các word có tâm y nằm trong ±4pt của tâm y nhãn VÀ có x0 >= nhãn.x1
3. Sắp theo x tăng dần, nối bằng dấu cách
4. Áp value_pattern để bóc phần thừa (nhãn tiếng Anh xuống dòng, cặp nhãn thứ hai cùng dòng)
```

Kết quả chạy thử trên file mẫu (12/12 trường đúng):

| Nhãn | Giá trị lấy được |
|---|---|
| `Ký hiệu (Serial):` | `(Serial): <SERIAL>` → sau `value_pattern` → `<SERIAL>` ✅ |
| `Số (No.):` | `(No.): <SO_HD>` → `<SO_HD>` ✅ |
| `Ngày hóa đơn (Date):` | `(Date): 01/08/2026` ✅ |
| `Mã khách hàng (CIF):` | `(CIF): <CIF>` ✅ |
| `Mã số thuế` | `(Tax code): <MST_KH>` ✅ |
| `Số tham chiếu` | `(Reference): <FTCODE>_20260801` ✅ |
| `Cộng tiền hàng` | `(Subtotal): 20.000` ✅ |
| `Tiền thuế GTGT` | `(Value added tax): 2.000` ✅ |
| `Tổng cộng tiền thanh toán` | `(Total): 22.000` ✅ |
| `Nội dung thanh toán` | `(Payment detail): So the ... FACEBK <REF10> DUBLIN IE` ✅ |

**Quan trọng:** chiến lược này **chỉ áp dụng cho `VPBANK_VAT_INVOICE`**.
Thử nghiệm cho thấy nếu dựng lại text theo toạ độ cho **Debit Note** và **Meta Invoice** thì
**làm HỎNG** dữ liệu, vì hai file đó có bố cục 2 cột và sẽ bị gộp nhầm:

```
sai:  "Tên Khách hàng/Customer Name: CONG TY CO   Tên Ngân hàng/Bank's Name: VPBANK"
```

⇒ **Kết luận thiết kế:** `PDFReader` phải cung cấp **3 chế độ đọc**, mỗi extractor tự chọn:

| Chế độ | Nội dung | Dùng cho |
|---|---|---|
| `text` | `get_text("text")` — thứ tự block | META_INVOICE, VPBANK_DEBIT_NOTE |
| `flat` | `text` + gộp mọi whitespace/xuống dòng thành 1 space | mọi regex bắc cầu qua nhiều dòng (xem §3.2) |
| `words` | list `(x0,y0,x1,y1,word)` + hàm `label_right()` | VPBANK_VAT_INVOICE |

Mỗi rule trong `extraction_rules.yaml` khai báo `strategy: text_regex | flat_regex | label_right`.

### 3.2 🔴 NGHIÊM TRỌNG — Diễn giải bị NGẮT DÒNG giữa chừng, và có lỗi thiếu dấu cách

Debit Note, text thô:

```
Diễn giải/Details: So the 1111xxxx1234 GD thanh toan      <- hết dòng
tai FACEBK <REF10> DUBLIN IE                              <- dòng mới
```

`FACEBK` và reference nằm ở **dòng khác** với nhãn `Diễn giải`.
⇒ Regex **bắt buộc** chạy trên chế độ `flat` (đã gộp xuống dòng), không được chạy line-by-line.

Hoá đơn GTGT, cùng nội dung nhưng **thiếu dấu cách**: `GD thanh toantai FACEBK <REF10>`
(mẫu gốc: `thanh toan tai` / `thanh toantai` — hai file viết khác nhau).

⇒ Regex **tuyệt đối không được** dựa vào `"GD thanh toan tai"`. Chỉ neo vào token `FACEBK`:

```yaml
- id: debit.meta_reference
  strategy: flat_regex
  pattern: '\bFACEBK\s+([A-Z0-9]{8,16})\b'
  merchant_anchors: [FACEBK, FACEBOOK, FB]    # mở rộng sau
  on_multiple_match: AMBIGUOUS_ERROR          # không tự chọn cái đầu tiên
```

Và `card_last4`:
```yaml
  pattern: '\bSo the\s+\d{4}[x*]{4}(\d{4})\b'
```

### 3.3 🟠 Dấu phân cách nghìn KHÁC NHAU giữa 3 chứng từ

| Chứng từ | Ví dụ trên file | Ý nghĩa thật |
|---|---|---|
| Meta Invoice | `1.100.000 ₫` / `1.000.000 VND` | dấu **chấm** = phân cách nghìn |
| Debit Note | `1,122,000 VND` | dấu **phẩy** = phân cách nghìn |
| VAT Invoice | `20.000` · `2.000` · `22.000` | dấu **chấm** = phân cách nghìn |

**Đây là cái bẫy nguy hiểm nhất về số liệu:** nếu `money_utils` tự động đoán,
`2.000` (= hai nghìn đồng) rất dễ bị đọc thành `2,000` (hai phẩy không).
Sai số 1000 lần trong sổ kế toán.

⇒ **Cấm auto-detect.** Mỗi loại chứng từ khai báo cứng trong config:

```yaml
money_format:
  META_INVOICE:       {thousands: ".", decimal: ",", currency_symbols: ["₫","VND"]}
  VPBANK_DEBIT_NOTE:  {thousands: ",", decimal: ".", currency_symbols: ["VND"]}
  VPBANK_VAT_INVOICE: {thousands: ".", decimal: ",", currency_symbols: []}
```

Kèm luật an toàn: nếu chuỗi tiền có phần "thập phân" đúng 3 chữ số (`2.000`) mà config
khai `decimal: "."` ⇒ báo `AMOUNT_PARSE_AMBIGUOUS`, trả `None`, **không đoán**.

---

## 4. KIỂM CHỨNG SỐ HỌC — CHUỖI TIỀN KHÉP KÍN HOÀN HẢO

> Số liệu dưới đây là **minh hoạ** (đã thay giá trị thật, giữ nguyên quan hệ toán học).
> Trên file mẫu thật, cả ba đẳng thức đều khớp **chính xác đến từng đồng**.

```
Hoá đơn Meta   : 1.000.000 (tổng phụ) + 100.000 (VAT 10%) = 1.100.000  ✅ khớp số ghi trên HĐ
Hoá đơn phí NH :    20.000 (tiền hàng) +   2.000 (VAT 10%) =    22.000  ✅ khớp số ghi trên HĐ
Debit Note     : 1.100.000 +  22.000                       = 1.122.000  ✅ khớp số ghi trên debit
```

**Đây là phát hiện nghiệp vụ quan trọng:** VPBank ghi nợ **một lần duy nhất** cho
(tiền quảng cáo Meta **đã gồm VAT**) **+** (phí dịch vụ ngân hàng **đã gồm VAT**).

⇒ **Luật kiểm tra chéo mới, thêm vào §7.2 Phase 1:**

| Mã | Luật | Severity |
|---|---|---|
| `AMOUNT_CHAIN_OK` | `debit.amount == meta.total_amount + vat_invoice.total_amount` | INFO (bằng chứng bộ chứng từ đúng) |
| `AMOUNT_CHAIN_BROKEN` | đẳng thức trên sai | **WARNING mạnh** — gần như chắc chắn ghép nhầm hoặc thiếu chứng từ |

Luật này **không** được dùng để tự ghép (vẫn tuân thủ §14), nhưng là **thước đo tin cậy tốt nhất**
để xác nhận một dossier `VALID` thực sự đúng — và để phát hiện trường hợp một debit note
gộp nhiều giao dịch Meta (Q2), vì khi đó đẳng thức sẽ vỡ.

---

## 5. TRẢ LỜI CÂU HỎI NGHIỆP VỤ TỪ CHÍNH FILE MẪU

### Q5 — Tiền tệ: **VND, không cần tỷ giá**
Hoá đơn Meta ghi thẳng `1.100.000 ₫` / `Tổng phụ: 1.000.000 VND`. Không có USD.
Hoá đơn VPBank có cột `Tỷ giá (Exchange rate)` nhưng **để trống**.
⇒ Bỏ rủi ro R3. App **không** thực hiện bất kỳ phép quy đổi tỷ giá nào.

### Q6 — Thuế nhà thầu FCT: **KHÔNG khấu trừ, KHÔNG hạch toán FCT**
Hoá đơn Meta ghi nguyên văn ở trang 2:

> *"Meta Platforms Ireland Limited đã đăng ký thuế tại Việt Nam và sẽ nộp FCT cho GDT.
> Vui lòng không khấu trừ/khấu lưu FCT, đồng thời thanh toán đầy đủ theo hóa đơn."*

Meta có **Tax ID Việt Nam** in trên hoá đơn (mã nhà cung cấp nước ngoài).
⇒ Công ty **không** phải trích nộp thay FCT. Bút toán FCT bị loại khỏi thiết kế MISA.

### Q7 — VAT của Meta: **VẪN CẦN BẠN QUYẾT** ⚠️
Hoá đơn Meta có `VAT: 100.000 ₫ (Thuế suất: 10%)` — nhưng đây là **hoá đơn nước ngoài**
(`Hóa đơn # FBADS-...`), **không phải hoá đơn GTGT điện tử mẫu Việt Nam**.
Việc số VAT này **có được kê khai khấu trừ vào TK 1331 hay không** là quyết định
chính sách kế toán/thuế của công ty bạn, **app không được tự quyết** (§23).
👉 Xem câu hỏi Q7-bis ở §7.

---

## 6. BỘ RULE ĐỀ XUẤT CHO PHASE 2 (dựa trên dữ liệu thật, không giả định)

### 6.1 Phân loại — ⚠️ BỘ KEYWORD Ở §6 PHASE 1 BỊ SAI, phải thay

Kiểm chứng trên file mẫu:

| Keyword (đề xuất ban đầu) | Meta | Debit | VAT | Kết luận |
|---|:---:|:---:|:---:|---|
| `HÓA ĐƠN GIÁ TRỊ GIA TĂNG` | 0 | 0 | **0** | ❌ **KHÔNG TỒN TẠI** trên hoá đơn VPBank |
| `VAT INVOICE` | 0 | 0 | **0** | ❌ **KHÔNG TỒN TẠI** |
| `VPBank` | 0 | **4** | **1** | ⚠️ xuất hiện ở CẢ HAI ⇒ không phân biệt được |

Hoá đơn GTGT của VPBank tự gọi mình là **"Bản thể hiện của hóa đơn điện tử"**, không hề có
cụm "GIÁ TRỊ GIA TĂNG". Nếu dùng bộ keyword cũ, file này sẽ bị phân loại `UNKNOWN`.

**Bộ rule mới (đã kiểm chứng, phân biệt 3/3 file):**

```yaml
META_INVOICE:
  must_have_any: ["Meta Platforms Ireland", "Meta quảng cáo", "Hóa đơn thuế cho"]
  strong:        ["Số tham chiếu:", "ID giao dịch", "FBADS-"]
  must_not_have: ["PHIẾU GIAO DỊCH GHI NỢ", "Ký hiệu (Serial)"]

VPBANK_DEBIT_NOTE:
  must_have_any: ["PHIẾU GIAO DỊCH GHI NỢ", "DEBIT NOTE"]
  strong:        ["Mã giao dịch/Transaction code", "Diễn giải/Details", "Tài khoản nợ"]
  must_not_have: ["Ký hiệu (Serial)"]

VPBANK_VAT_INVOICE:
  must_have_any: ["Ký hiệu (Serial)", "Bản thể hiện của hóa đơn điện tử"]
  strong:        ["Nội dung thanh toán (Payment detail)", "Cộng tiền hàng (Subtotal)",
                  "einvoice.vpbank.com.vn", "Ngân hàng TMCP Việt Nam Thịnh Vượng"]
  must_not_have: ["PHIẾU GIAO DỊCH GHI NỢ"]
```

Cơ chế: `must_have_any` bắt buộc ≥1; mỗi `strong` +1 điểm; `must_not_have` loại thẳng.
Nếu ≥2 loại cùng đạt ⇒ `UNKNOWN` + `CLASSIFY_AMBIGUOUS` (không tự chọn điểm cao hơn).

### 6.2 META_INVOICE — rule trích xuất

| Trường | Chế độ | Neo / Pattern | Giá trị mẫu |
|---|---|---|---|
| `reference_number` | flat_regex | `Số tham chiếu:\s*([A-Z0-9]{8,16})\b` | `<REF10>` |
| `account_id` | flat_regex | `ID tài khoản:\s*(\d{10,20})` | `<ACCOUNT_ID>` |
| `transaction_id` | text_regex | `ID giao dịch\s*\n\s*([\d]+-[\d]+)` | `<TXID_A>-<TXID_B>` |
| `invoice_number` | flat_regex | `Hóa đơn\s*#\s*(FBADS-[\w-]+)` | `FBADS-<so>-<so>` |
| `invoice_date` | flat_regex | `(\d{1,2}:\d{2})\s+(\d{1,2}) tháng (\d{1,2}), (\d{4})` | `15:10 1 tháng 8, 2026` |
| `card_last4` | flat_regex | `(?:MasterCard\|Visa)[^\d]{0,12}(\d{4})\b` | `1234` |
| `subtotal` | flat_regex | `Tổng phụ:\s*([\d.,]+)\s*(?:VND\|₫)` | `1.000.000` |
| `vat_amount` + `vat_rate` | flat_regex | `VAT:\s*([\d.,]+)\s*₫\s*\(Thuế suất:\s*(\d+)%\)` | `100.000` / `10` |
| `total_amount` | text_regex | `Đã thanh toán\s*\n\s*([\d.,]+)\s*₫` | `1.100.000` |
| `company_name` / `tax_code` (bên mua) | text_regex | khối sau `Meta Platforms Ireland Limited`, lấy `Tax ID:\s*([\d-]+)` **lần thứ 2** | `<MST_KH_KIEU_META>` |

⚠️ `Tax ID:` xuất hiện **2 lần** (Meta trước, khách hàng sau). Rule phải chỉ rõ thứ tự
(`occurrence: 2`), không được lấy bừa lần đầu.

⚠️ Ngày trên hoá đơn Meta là **tiếng Việt dạng chữ** (`1 tháng 8, 2026`) ⇒ `date_utils`
cần parser riêng cho `tháng`, không dùng `strptime` mặc định.

### 6.3 VPBANK_DEBIT_NOTE — rule trích xuất

| Trường | Chế độ | Neo / Pattern | Giá trị mẫu |
|---|---|---|---|
| `transaction_date` | flat_regex | `Ngày/Transaction Date:\s*(\d{2}/\d{2}/\d{4})` | `01/08/2026` |
| `customer_name` | text_regex | `Tên Khách hàng/Customer Name:\s*(.+)` (+nối dòng tiếp) | `CONG TY …` |
| `customer_id` | flat_regex | `Mã Khách hàng/Customer ID:\s*(\d+)` | `<CIF>` |
| `bank_account` | flat_regex | `Số tài khoản/Account No:\s*(\d+)` | `<SO_TK>` |
| `transaction_code` | flat_regex | `Mã giao dịch/Transaction code:\s*([A-Z0-9]+)` | `<FTCODE>` |
| `currency` | flat_regex | `Loại tiền/Currency:\s*([A-Z]{3})` | `VND` |
| `total_amount` | flat_regex | `Số tiền/Amount:\s*([\d.,]+)\s*([A-Z]{3})` | `1,122,000` |
| `payment_detail` | flat_regex | `Diễn giải/Details:\s*(.+?)(?=Phiếu này được in\|$)` | `So the …` |
| `card_last4` | flat_regex | `So the\s+\d{4}[x*]{4}(\d{4})` | `1234` |
| `meta_reference` | flat_regex | `\bFACEBK\s+([A-Z0-9]{8,16})\b` | `<REF10>` |

### 6.4 VPBANK_VAT_INVOICE — rule trích xuất (**toàn bộ dùng `label_right`**)

| Trường | Nhãn neo | `value_pattern` | Giá trị mẫu |
|---|---|---|---|
| `invoice_serial` | `Ký hiệu (Serial):` | `^(?:\([^)]*\):)?\s*([A-Z0-9]{5,12})` | `<SERIAL>` |
| `invoice_number` | `Số (No.):` | `^(?:\([^)]*\):)?\s*(\d{4,12})` | `<SO_HD>` |
| `invoice_date` | `Ngày hóa đơn (Date):` | `(\d{2}/\d{2}/\d{4})` | `01/08/2026` |
| `seller_tax_code` | `MST` | `(\d{10,14})` | `<MST_VPBANK>` |
| `customer_name` | `Tên khách hàng (Customer):` | `^(?:\([^)]*\):)?\s*(.+)$` | `CONG TY …` |
| `customer_id` | `Mã khách hàng (CIF):` | `(\d+)` | `<CIF>` |
| `customer_tax_code` | `Mã số thuế` | `(\d{10,14})` | `<MST_KH>` |
| `reference_number` | `Số tham chiếu` | `([A-Z0-9]+)_(\d{8})` | `<FTCODE>_20260801` |
| `subtotal` | `Cộng tiền hàng` | `([\d.]+)\s*$` | `20.000` |
| `vat_rate` | `Thuế suất` | `(\d{1,2})%` | `10` |
| `vat_amount` | `Tiền thuế GTGT` | `([\d.]+)\s*$` | `2.000` |
| `total_amount` | `Tổng cộng tiền thanh toán` | `([\d.]+)\s*$` | `22.000` |
| `payment_detail` | `Nội dung thanh toán` | `^(?:\([^)]*\):)?\s*(.+)$` | `So the …` |
| `card_last4` | (từ payment_detail) | `So the\s+\d{4}[x*]{4}(\d{4})` | `1234` |
| `meta_reference` | (từ payment_detail) | `\bFACEBK\s+([A-Z0-9]{8,16})\b` | `<REF10>` |

⚠️ Nhãn `Thuế suất` và `Tiền thuế GTGT` **nằm cùng một dòng y** ⇒ `label_right("Thuế suất")`
trả về cả hai cặp. Bắt buộc phải có `value_pattern` giới hạn, đã kiểm chứng ở §3.1.

⚠️ `MST (Tax code):` (bên bán) và `Mã số thuế (Tax code):` (bên mua) là **hai nhãn khác nhau** —
không được dùng chung pattern `Tax code`.

### 6.5 Chuẩn hoá MST — bổ sung `normalize_tax_code()`

Meta ghi `<MST_KH_KIEU_META>`, VPBank ghi `<MST_KH>` → **cùng một MST**, khác cách trình bày.
⇒ Thêm hàm riêng: **chỉ giữ chữ số** (`re.sub(r"\D", "", s)`), dùng **duy nhất** cho việc
đối chiếu MST (`TAX_CODE_MISMATCH`).

**Hàm này TUYỆT ĐỐI KHÔNG được áp dụng cho `reference`** — quy tắc §11/§32 giữ nguyên
không đổi: reference không bị bóc bỏ bất kỳ ký tự nào.

---

## 7. CÂU HỎI CÒN LẠI

**Đã đóng nhờ file mẫu:** Q1 ✅ · Q3 ✅ · Q4 ✅ · Q5 ✅ · Q6 ✅ · Q11 ✅ · Q12 ✅

**Còn chặn Phase 2:**

- **Q2 (vẫn mở, quan trọng nhất).** Một Debit Note có bao giờ gộp **nhiều** hoá đơn Meta không?
  Trên bộ mẫu này là quan hệ 1-1 hoàn hảo (đẳng thức tiền ở §4 khép kín).
  Nếu bạn xác nhận **luôn luôn 1-1**, tôi chốt model 1-1 và dùng `AMOUNT_CHAIN` làm rào chắn.

- **Q17 (MỚI).** `Số tham chiếu (Reference)` của hoá đơn VPBank có **luôn** theo định dạng
  `<Mã giao dịch>_<YYYYMMDD>` không? Nếu có ngoại lệ, tôi sẽ để K1 là "ưu tiên" chứ không "bắt buộc".

- **Q18 (MỚI).** Chuỗi sau reference trên mẫu này là `DUBLIN IE`, nhưng mô tả ban đầu của bạn
  là `fb me ads IE`. Xác nhận: phần đuôi này **thay đổi tuỳ giao dịch** và regex
  **không được phụ thuộc** vào nó — đúng không?

**Còn mở nhưng chưa chặn (trả lời trước Phase 5):**

- **Q7-bis.** Số `VAT: 100.000 ₫ (10%)` trên hoá đơn Meta — công ty bạn **có kê khai khấu trừ**
  vào TK 1331 không, hay hạch toán toàn bộ `1.100.000` vào chi phí 6417?
  Đây là quyết định của kế toán trưởng, app chỉ làm theo cấu hình.
- **Q8.** File Excel mẫu import của MISA SME 2023.
- **Q9 / Q10.** `Ma_doi_tuong` và dải `So_chung_tu`.
- **Q13 / Q14 / Q15.** Một PDF có chứa nhiều chứng từ? · chạy 1 máy hay thư mục mạng? · Windows 10/11?

---

## 8. QUY TẮC DỮ LIỆU MẪU (bắt buộc tuân thủ)

Repo `DATATHON---2026` là **PUBLIC**. Vì vậy:

1. **KHÔNG** commit file PDF chứng từ thật.
2. **KHÔNG** commit fixture chứa MST, số tài khoản, CIF, tên khách hàng, mã giao dịch thật.
3. Fixture test trong `tests/fixtures/` phải là **text đã che số** — giữ nguyên *cấu trúc*
   (nhãn, thứ tự, dấu phân cách, lỗi thiếu dấu cách) vì đó mới là thứ regex cần test,
   thay toàn bộ *giá trị* bằng placeholder nhất quán.
4. Thêm vào `.gitignore`: `*.pdf`, `ALL_DATA/`, `OUTPUT/`, `database/*.db`, `logs/*.log`.
5. Nếu bạn muốn giữ fixture thật để test: dùng repo **private** riêng, hoặc để ngoài git.

---

## 9. ĐỀ XUẤT ĐIỀU CHỈNH PHASE 1 (tổng hợp)

| Mục Phase 1 | Thay đổi |
|---|---|
| §5 PDF Reader | Thêm 3 chế độ đọc `text` / `flat` / `words` + hàm `label_right()` |
| §6 Phân loại | **Thay bộ keyword** — `HÓA ĐƠN GIÁ TRỊ GIA TĂNG` và `VAT INVOICE` không tồn tại |
| §7 Model | Thêm `vat.reference_number` (khoá K1) là trường ghép, không chỉ để hiển thị |
| §11 Chuẩn hoá | Thêm `normalize_tax_code()` — **tách bạch**, không đụng `normalize_reference()` |
| §13 Ghép file thứ 3 | **Viết lại** theo K1/K2 ở §2.2 (có luật `VAT_KEY_CONFLICT`) |
| §7.2 Validation | Thêm `AMOUNT_CHAIN_OK` / `AMOUNT_CHAIN_BROKEN` |
| §11 Rủi ro | R1 **đóng** · R3 (tỷ giá) **đóng** · R4 (OCR) **đóng** trên mẫu này · thêm R8 dấu phân cách nghìn · R9 thứ tự text đảo |
| §9 MISA | **Bỏ** bút toán FCT (Meta tự nộp) |
| utils | `money_utils` cấu hình dấu phân cách theo từng loại chứng từ, **cấm auto-detect** |

**Chờ bạn trả lời Q2, Q17, Q18 để bắt đầu Phase 2.**
