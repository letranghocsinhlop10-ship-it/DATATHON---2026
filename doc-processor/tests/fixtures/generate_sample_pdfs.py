"""Generates synthetic PDF (+ XML) fixtures with FAKE data, structurally
modeled on the real sample documents used to calibrate the extractors
(see app/extraction/*.py docstrings) — no real customer data is used or
stored anywhere in this repo.

Each `make_*` function writes a PDF (and, for the VAT invoice, an
optional XML sidecar) to the given path and returns the path.
"""
from __future__ import annotations

from pathlib import Path
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

# reportlab's built-in fonts (Helvetica etc.) have no Vietnamese glyphs and
# silently mis-render diacritics. Register a Unicode TTF so fixtures use
# real Vietnamese text, matching what real accounting PDFs contain.
_VN_FONT_NAME = "DejaVuSans"
_VN_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]
for _font_path in _VN_FONT_CANDIDATES:
    if Path(_font_path).exists():
        pdfmetrics.registerFont(TTFont(_VN_FONT_NAME, _font_path))
        break
else:  # pragma: no cover - dev machines without dejavu installed
    _VN_FONT_NAME = "Helvetica"


def _wrap(line: str, max_chars: int = 90) -> list[str]:
    """Long lines drawn past the page's right edge get silently dropped by
    some PDF text extractors, so wrap before drawing rather than relying
    on the reader to cope with off-page content."""
    if len(line) <= max_chars:
        return [line]
    words = line.split(" ")
    out, cur = [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max_chars:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    if cur:
        out.append(cur)
    return out


def _draw_lines(c: canvas.Canvas, lines: list[str], start_y: float = 800, x: float = 40, leading: float = 16):
    c.setFont(_VN_FONT_NAME, 11)
    y = start_y
    for line in lines:
        for wrapped in _wrap(line):
            c.drawString(x, y, wrapped)
            y -= leading


def make_facebook_bill(
    path: str | Path,
    reference: str = "76NQZZMDK2",
    invoice_number: str = "FBADS-445-106372463",
    buyer_name: str = "CONG TY CO PHAN Y TE SCT",
    buyer_tax_id: str = "01-1038264-0",
    amount_before_vat: str = "57.579 VND",
    vat_amount: str = "5.758",
    vat_rate: str = "10",
    total_amount: str = "63.337",
    payment_method: str = "MasterCard ···· 4966",
    invoice_date: str = "18:00 24 tháng 7, 2026",
) -> str:
    path = str(path)
    c = canvas.Canvas(path, pagesize=A4)
    lines = [
        f"Hóa đơn thuế cho {buyer_name[:10]}",
        "ID tài khoản: 2125041618446844",
        "Ngày lập hóa đơn/thanh toán",
        invoice_date,
        "Phương thức thanh toán",
        payment_method,
        f"Số tham chiếu: {reference}",
        "ID giao dịch",
        "27977252678629140-27990458970641836",
        "Loại sản phẩm",
        "Meta quảng cáo",
        "Đã thanh toán",
        f"{total_amount} ₫",
        f"Tổng phụ: {amount_before_vat}",
        f"VAT: {vat_amount} ₫ (Thuế suất: {vat_rate}%)",
        "Meta Platforms Ireland Limited",
        "Merrion Road, Dublin 4, Ireland",
        "Tax ID: 9000000327",
        buyer_name,
        "Some Address, Vietnam",
        f"Tax ID: {buyer_tax_id}",
        f"Hóa đơn # {invoice_number}",
    ]
    _draw_lines(c, lines)
    c.save()
    return path


def make_bank_debit_note(
    path: str | Path,
    reference_code: str = "76NQZZMDK2",
    transaction_code: str = "FT26205136372705",
    transaction_date: str = "25/07/2026",
    customer_name: str = "CONG TY CO PHAN Y TE SCT",
    bank_name: str = "VPBANK",
    account_no: str = "632863969",
    amount: str = "63,337",
    currency: str = "VND",
) -> str:
    path = str(path)
    c = canvas.Canvas(path, pagesize=A4)
    lines = [
        "PHIẾU GIAO DỊCH GHI NỢ/DEBIT NOTE",
        f"Ngày/Transaction Date: {transaction_date}",
        f"Tên Khách hàng/Customer Name: {customer_name}",
        f"Tên Ngân hàng/Bank's Name: {bank_name}",
        f"Mã Khách hàng/Customer ID: 23965147",
        f"Số tài khoản/Account No: {account_no}",
        f"Mã giao dịch/Transaction code: {transaction_code}\\BNK",
        f"Loại tiền/Currency: {currency}",
        f"Số tiền/Amount: {amount} {currency}",
        f"Diễn giải/Details: GD the 5223xx4966 tai FACEBK {reference_code} fb me ads IE",
    ]
    _draw_lines(c, lines)
    c.save()
    return path


VAT_XML_TEMPLATE = """<HDon><DLHDon Id="1"><TTChung><PBan>2.0.1</PBan><THDon>Hóa đơn giá trị gia tăng</THDon>\
<KHMSHDon>1</KHMSHDon><KHHDon>{serial}</KHHDon><SHDon>{number}</SHDon><NLap>{date_iso}</NLap>\
<DVTTe>{currency}</DVTTe><TGia>1.00</TGia><HTTToan>CK</HTTToan></TTChung>\
<NDHDon><NBan><Ten>{seller}</Ten><MST>{seller_tax_code}</MST></NBan>\
<NMua><Ten>{buyer}</Ten><MST>{buyer_tax_code}</MST><STKNHang>{buyer_account}</STKNHang></NMua>\
<DSHHDVu><HHDVu><TChat>1</TChat><STT>1</STT><THHDVu>Thu tien hang hoa/dich vu</THHDVu>\
<SLuong>0</SLuong><DGia>0</DGia><ThTien>{amount_before_vat}</ThTien><TSuat>{vat_rate}%</TSuat></HHDVu></DSHHDVu>\
<TToan><THTTLTSuat><LTSuat><TSuat>{vat_rate}%</TSuat><ThTien>{amount_before_vat}</ThTien>\
<TThue>{vat_amount}</TThue></LTSuat></THTTLTSuat><TgTCThue>{amount_before_vat}</TgTCThue>\
<TgTThue>{vat_amount}</TgTThue><TgTTTBSo>{total_amount}</TgTTTBSo></TToan></NDHDon></DLHDon></HDon>"""


def make_vat_invoice(
    path: str | Path,
    xml_path: str | Path | None = None,
    reference_code: str = "76NQZZMDK2",
    bank_ref_code: str = "FT26205034015973_20260724",
    serial: str = "K26TSA",
    number: str = "00647095",
    date_ddmmyyyy: str = "24/07/2026",
    date_iso: str = "2026-07-24",
    seller: str = "Ngan hang TMCP Viet Nam Thinh Vuong",
    seller_tax_code: str = "0100233583",
    buyer: str = "CONG TY CO PHAN Y TE SCT",
    buyer_tax_code: str = "0110382640",
    buyer_account: str = "632863969",
    amount_before_vat: str = "633.000",
    vat_amount: str = "63.000",
    vat_rate: str = "10",
    total_amount: str = "696.000",
    currency: str = "VND",
    include_xml: bool = True,
) -> tuple[str, str | None]:
    path = str(path)
    c = canvas.Canvas(path, pagesize=A4)
    # Deliberately mimic the real-world "row order scrambled" quirk seen in
    # the calibration sample for the buyer info block only, since that's
    # exactly the case the reference extraction must be robust against.
    lines = [
        f"Số (No.): {number}",
        f"Ký hiệu (Serial): {serial}",
        f"Ngày hóa đơn (Date): {date_ddmmyyyy}",
        f"Đơn vị bán hàng (Seller): {seller}",
        f"MST (Tax code): {seller_tax_code}",
        buyer,
        "Tên khách hàng (Customer):",
        "23965147",
        "Mã khách hàng (CIF):",
        f"Mã số thuế (Tax code): {buyer_tax_code}",
        bank_ref_code,
        "Số tham chiếu (Reference):",
        "Some Address Line, Ha Noi",
        f"Nội dung thanh toán (Payment detail): GD FACEBK {reference_code} fb me ads IE",
        f"Cộng tiền hàng (Subtotal): {amount_before_vat}",
        f"Tiền thuế GTGT (Value added tax): {vat_amount}",
        f"Thuế suất (Tax rate): {vat_rate}%",
        f"Tổng cộng tiền thanh toán (Total): {total_amount}",
        "Bản thể hiện của hóa đơn điện tử (electronic invoice display)",
    ]
    _draw_lines(c, lines)
    c.save()

    xml_out = None
    if include_xml and xml_path is not None:
        xml_out = str(xml_path)
        content = VAT_XML_TEMPLATE.format(
            serial=serial,
            number=number,
            date_iso=date_iso,
            currency=currency,
            seller=seller,
            seller_tax_code=seller_tax_code,
            buyer=buyer,
            buyer_tax_code=buyer_tax_code,
            buyer_account=buyer_account,
            amount_before_vat=amount_before_vat,
            vat_amount=vat_amount,
            vat_rate=vat_rate,
            total_amount=total_amount,
        )
        Path(xml_out).write_text(content, encoding="utf-8")

    return path, xml_out


def make_scanned_blank_pdf(path: str | Path) -> str:
    """A PDF page with no text layer at all (simulates a scanned image
    when no drawImage is used — good enough to exercise the
    "no text layer -> OCR attempted -> OCR unavailable -> warning" path
    without needing a real scanned image or a working Tesseract binary)."""
    path = str(path)
    c = canvas.Canvas(path, pagesize=A4)
    c.rect(100, 700, 200, 50)  # draw a shape, not text
    c.save()
    return path


def make_corrupt_pdf(path: str | Path) -> str:
    path = str(path)
    Path(path).write_bytes(b"%PDF-1.4 not a real pdf body -- corrupted")
    return path
