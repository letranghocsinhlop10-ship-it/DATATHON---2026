# PHỤ LỤC — PHÂN TÍCH FILE MẪU MISA SME 2023

> Repo công khai: mọi giá trị nhận dạng đơn vị và số tiền trong tài liệu này
> đã được thay bằng placeholder. Chỉ **cấu trúc** là thật.

Nguồn: file `Mau chung tu nghiep vu khac VND.xls` do kế toán cung cấp —
**không phải template rỗng mà là dữ liệu THẬT đã hạch toán**: 128 dòng,
tương ứng 64 hoá đơn Meta của một tháng.

---

## 1. CẤU TRÚC FILE

| Mục | Giá trị |
|---|---|
| Sheet dùng để import | `Chứng từ nghiệp vụ khác` |
| Sheet phụ | `Công thức` — bảng nháp kế toán dùng công thức Excel ghép chuỗi diễn giải |
| Số cột | **34** (dòng 1 là tiêu đề) |
| Số cột thực sự dùng | **8** |
| Số cột bỏ trống hoàn toàn | **26** |

**Thứ tự 34 cột phải giữ nguyên** thì MISA mới đọc đúng, kể cả các cột bỏ trống.

### Tám cột được dùng

| Cột | Tiêu đề | Giá trị quan sát được |
|---|---|---|
| C01 | `Ngày chứng từ (*)` | = ngày trên hoá đơn Meta |
| C02 | `Ngày hạch toán (*)` | = C01, **128/128 dòng** |
| C03 | `Số chứng từ (*)` | `NVK` + 6 chữ số chạy liên tục |
| C04 | `Diễn giải` | xem §3 |
| C06 | `Diễn giải (Hạch toán)` | **giống hệt C04** |
| C07 | `TK Nợ (*)` | `6417` — **128/128 dòng, không có ngoại lệ** |
| C08 | `TK Có (*)` | `331` — **128/128 dòng** |
| C09 | `Số Tiền` | số nguyên, không phân cách |
| C11 | `Đối tượng Có` | MST Việt Nam của Meta — **128/128 dòng** |

### Toàn bộ nhóm cột thuế bỏ trống

`C20 Diễn giải (Thuế)` · `C21 TK thuế GTGT` · `C22 Tiền thuế GTGT` ·
`C23 % thuế GTGT` · `C24 Tỷ lệ tính thuế` · `C25 Giá trị HHDV chưa thuế` ·
`C26 Mẫu số HĐ` · `C27 Ngày hóa đơn` · `C28 Ký hiệu HĐ` · `C29 Số hóa đơn` ·
`C30 Nhóm HHDV mua vào` · `C31–C33 Đối tượng thuế`

→ **Xác nhận bằng dữ liệu** điều kế toán đã trả lời ở Q7: không kê khai thuế
GTGT đầu vào cho chi phí quảng cáo Meta.

---

## 2. SƠ ĐỒ HẠCH TOÁN THỰC TẾ

**Một hoá đơn Meta = đúng 2 dòng.** Kiểm chứng: 64 hoá đơn duy nhất, 64 dòng
"Hạch toán", 64 dòng "Thuế GTGT", **không hoá đơn nào thiếu cặp**.

| Dòng | Nội dung | TK Nợ | TK Có | Số tiền | Đối tượng Có |
|---|---|---|---|---|---|
| 1 | Chi phí quảng cáo | `6417` | `331` | `Tổng phụ` trên hoá đơn | MST Meta |
| 2 | Thuế GTGT | `6417` | `331` | `VAT` trên hoá đơn | MST Meta |

**Khác hẳn giả định ban đầu của Phase 1** (`6417/1121` và `1331` cho VAT):

* TK Có là **331 (phải trả người bán)**, không phải 1121. Việc chi tiền ngân
  hàng được hạch toán ở một loại chứng từ khác, không nằm trong file này.
* Thuế GTGT vào thẳng **6417**, không qua 1331.

⇒ Đã cập nhật `config/accounting.yaml` và `config/misa_mapping.yaml`.

---

## 3. MẪU DIỄN GIẢI

```
Dòng chi phí:
  Hạch toán chi phí quảng cáo facebook cho <ĐƠN VỊ>
  theo số hóa đơn <SỐ HĐ META> ngày <dd/mm/yyyy>

Dòng thuế:
  Thuế GTGT chi phí quảng cáo facebook cho <ĐƠN VỊ>
  theo số hóa đơn <SỐ HĐ META> ngày <dd/mm/yyyy>
```

* `<SỐ HĐ META>` là số hoá đơn Meta dạng `FBADS-<nhóm>-<số>`. File mẫu có ba
  nhóm khác nhau, mẫu PDF lại là nhóm thứ tư ⇒ regex hiện tại không neo vào
  nhóm, đúng.
* `<dd/mm/yyyy>` = ngày hoá đơn, **trùng C01 ở cả 128/128 dòng**.
* `<ĐƠN VỊ>` là chuỗi cố định của công ty ⇒ đưa vào Settings, không hard-code.
* File mẫu có chỗ thừa dấu cách (`Hạch toán  chi phí`) do ghép công thức Excel
  — app sinh chuỗi chuẩn, không tái tạo lỗi đánh máy.

---

## 4. SỐ CHỨNG TỪ

```
NVK + 6 chữ số, chạy LIÊN TỤC từ <START> tới <START+127>
```

Đã kiểm chứng: 128 số, **liên tục tuyệt đối, không trùng, không nhảy cóc**.

Sáu chữ số **không suy ra được** từ tháng/năm (dãy chạy vắt qua ranh giới mà
nếu là MMYY thì phải reset). Đây là dải số nội bộ do kế toán quản lý.

⇒ Thiết kế: app **không tự đoán** số bắt đầu. `misa_mapping.yaml` khai
`voucher_number.start: null`; trước khi xuất Excel, app hỏi kế toán nhập số
bắt đầu rồi tự tăng dần.

---

## 5. PHÁT HIỆN ĐÁNG CHÚ Ý: FILE MẪU CÓ MỘT DÒNG SAI SỐ

Kiểm tra quan hệ `dòng thuế == 10% × dòng chi phí` trên 64 cặp:

```
khớp:  63/64
lệch:   1/64   — thuế ghi tay thấp hơn 10% khoảng 32 đồng
```

Đây là lỗi nhập tay điển hình. Vì vậy `accounting.yaml` đặt
`recompute_vat_from_rate: false`: app **luôn lấy số thuế in trên hoá đơn**,
không tự tính `tổng phụ × thuế suất`. App chỉ *cảnh báo* khi hai số lệch nhau
(`VAT_MATH_ERROR`), quyền quyết định thuộc về kế toán.

---

## 6. CÂU HỎI PHÁT SINH TỪ FILE MẪU

* **Q19 (quan trọng).** File MISA mẫu **không có dòng nào cho phí dịch vụ ngân
  hàng VPBank**, dù mỗi bộ hồ sơ đều có hoá đơn GTGT phí ngân hàng. Phí này
  được hạch toán ở đâu — loại chứng từ MISA khác, hay hiện chưa hạch toán?
  Hiện `misa_mapping.yaml` để `bank_fee_expense` và `bank_fee_vat`
  **enabled: false**, app không tự sinh bút toán chưa được duyệt.

* **Q20.** TK Có là `331` (phải trả người bán). Vậy bút toán chi tiền
  (`331 / 1121`) căn cứ Debit Note có cần app xuất luôn không, hay kế toán
  làm riêng bằng chứng từ "Chi tiền gửi"?

* **Q21.** Số chứng từ bắt đầu của mỗi đợt import — kế toán nhập tay mỗi lần,
  hay app tự nhớ số cuối cùng đã dùng và tăng tiếp?

* **Q22.** `Đối tượng Có` luôn là MST của Meta. Khi thêm nhà cung cấp khác
  (Google Ads, TikTok), mã đối tượng lấy từ đâu — danh mục MISA hay MST?
