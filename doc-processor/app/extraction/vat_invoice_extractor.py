"""Extractor for VAT invoices (Hóa đơn giá trị gia tăng).

Real-world calibration note: on the sample VPBank e-invoice PDF, the
buyer info block's labels and values come out of PyMuPDF's plain text
extraction *out of visual row order* (a 2-column label/value table whose
reading order doesn't follow the printed rows) — so naive
label-adjacency mis-pairs "Địa chỉ" and "Số tham chiếu". Two mitigations:

1. Whenever a same-stem .xml sidecar exists (the actual signed e-invoice;
   very common for VN invoices), it is authoritative for every field it
   carries — invoice number/date, seller/buyer, tax codes, amounts.
2. The two fields NOT present in that XML — reference and payment detail
   — are pulled from the PDF by matching their own distinctive SHAPE
   (regex over the whole text) rather than by adjacent label, which
   sidesteps the row-order problem entirely.

If no XML is present, we fall back to label-adjacency for everything,
which works for cleanly-ordered PDFs but should be treated as
lower-confidence (see `extraction_confidence`) until recalibrated
against more real samples of that specific provider's PDF layout.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.core.config_loader import get_extraction_patterns
from app.extraction.base import (
    clean_code,
    find_labeled_value,
    normalize_amount,
    normalize_date,
    normalize_tax_code,
    regex_first_match,
)
from app.extraction.common import detect_currency, leading_number, percent_in
from app.extraction.vat_xml_parser import parse_vat_invoice_xml
from app.models.schema import DocType, ExtractedDocument


def extract_vat_invoice(text: str, source_file: str, xml_path: Optional[str | Path] = None) -> ExtractedDocument:
    cfg = get_extraction_patterns().get("vat_invoice", {})
    labels = cfg.get("labels", {})
    regex = cfg.get("regex", {})

    warnings: list[str] = []
    used_xml = False
    xml_data: dict = {}
    if xml_path is not None:
        xml_data = parse_vat_invoice_xml(xml_path)
        used_xml = bool(xml_data)
        if not used_xml:
            warnings.append("Có file XML kèm theo nhưng parse thất bại, dùng fallback PDF text")

    currency = xml_data.get("currency") or detect_currency(text)

    # --- Reference & payment detail: shape-based, PDF-only (see module docstring) ---
    reference = clean_code(regex_first_match(text, regex.get("reference_shape", "(?!)"), group=0))
    if not reference:
        reference = clean_code(find_labeled_value(text, labels.get("reference", [])))
    ref_embedded = clean_code(regex_first_match(text, regex.get("reference_embedded", "(?!)")))
    reference_candidates = [r for r in (reference, ref_embedded) if r]

    payment_detail = find_labeled_value(text, labels.get("payment_detail", []))

    # --- Everything else: XML first, PDF label-adjacency fallback ---
    if used_xml:
        invoice_number = xml_data.get("invoice_number")
        invoice_date = xml_data.get("invoice_date")
        seller = xml_data.get("seller")
        seller_tax_code = xml_data.get("seller_tax_code")
        buyer = xml_data.get("buyer")
        buyer_tax_code = xml_data.get("buyer_tax_code")
        bank_info = xml_data.get("bank_info")
        amount_before_vat = xml_data.get("amount_before_vat")
        vat_amount = xml_data.get("vat_amount")
        vat_rate = xml_data.get("vat_rate")
        total_amount = xml_data.get("total_amount")
    else:
        serial = find_labeled_value(text, labels.get("invoice_serial", []))
        number = find_labeled_value(text, labels.get("invoice_no", []))
        invoice_number = f"{serial}-{number}" if serial and number else (number or serial)
        invoice_date = normalize_date(find_labeled_value(text, labels.get("invoice_date", [])))
        seller = find_labeled_value(text, labels.get("seller", []))
        seller_tax_code = normalize_tax_code(find_labeled_value(text, labels.get("seller_tax_code", [])))
        buyer = find_labeled_value(text, labels.get("buyer", []))
        buyer_tax_code = normalize_tax_code(find_labeled_value(text, labels.get("buyer_tax_code", [])))
        bank_info = None
        amount_before_vat = normalize_amount(
            leading_number(find_labeled_value(text, labels.get("amount_before_vat", []))), currency
        )
        vat_amount = normalize_amount(
            leading_number(find_labeled_value(text, labels.get("vat_amount", []))), currency
        )
        vat_rate = percent_in(find_labeled_value(text, labels.get("vat_rate", [])))
        total_amount = normalize_amount(
            leading_number(find_labeled_value(text, labels.get("total_amount", []))), currency
        )
        warnings.append("Không có XML kèm theo — số liệu lấy từ PDF text, độ tin cậy thấp hơn")

    if vat_rate and not str(vat_rate).endswith("%"):
        vat_rate = f"{vat_rate}%"

    if not reference_candidates:
        warnings.append("Không tìm thấy Số tham chiếu trên hóa đơn VAT")
    if total_amount is None:
        warnings.append("Không trích xuất được tổng tiền thanh toán")

    confidence = sum(
        1
        for v in [reference_candidates, invoice_number, invoice_date, total_amount, buyer_tax_code]
        if v
    ) / 5
    if used_xml:
        confidence = min(1.0, confidence + 0.2)

    return ExtractedDocument(
        doc_type=DocType.VAT_INVOICE,
        source_file=source_file,
        reference_candidates=reference_candidates,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        seller=seller,
        buyer=buyer,
        seller_tax_code=seller_tax_code,
        tax_code=buyer_tax_code,
        amount_before_vat=amount_before_vat,
        vat_amount=vat_amount,
        vat_rate=vat_rate,
        total_amount=total_amount,
        currency=currency,
        bank_info=bank_info,
        transaction_date=invoice_date,
        description=payment_detail,
        raw_text=text,
        used_xml_sidecar=used_xml,
        xml_sidecar_path=str(xml_path) if used_xml else None,
        extraction_confidence=confidence,
        warnings=warnings,
    )
