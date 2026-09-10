"""Extractor for Facebook / Meta Ads tax invoices.

Calibrated against a real Meta Platforms Ireland Ltd invoice PDF
("Hóa đơn thuế cho ..."), which — unlike the VAT invoice PDF — extracts
in clean top-to-bottom reading order, so label-adjacency works well here.
"""
from __future__ import annotations

from app.core.config_loader import get_extraction_patterns
from app.extraction.base import (
    clean_code,
    find_labeled_value,
    normalize_amount,
    normalize_date,
    normalize_tax_code,
    regex_all_matches,
    regex_first_match,
)
from app.extraction.common import detect_currency, leading_number, percent_in
from app.models.schema import DocType, ExtractedDocument


def extract_facebook(text: str, source_file: str) -> ExtractedDocument:
    cfg = get_extraction_patterns().get("facebook", {})
    labels = cfg.get("labels", {})
    regex = cfg.get("regex", {})

    warnings: list[str] = []
    currency = detect_currency(text)

    reference = clean_code(find_labeled_value(text, labels.get("reference", [])))
    ref_embedded = clean_code(regex_first_match(text, regex.get("reference_embedded", "(?!)")))
    reference_candidates = [r for r in (reference, ref_embedded) if r]

    invoice_number = find_labeled_value(text, labels.get("invoice_number", []))
    invoice_date_raw = find_labeled_value(text, labels.get("invoice_date", []))
    invoice_date = normalize_date(invoice_date_raw)

    payment_method = find_labeled_value(text, labels.get("payment_method", []))
    description = find_labeled_value(text, labels.get("description", []))

    subtotal_raw = find_labeled_value(text, labels.get("amount_before_vat", []))
    amount_before_vat = normalize_amount(leading_number(subtotal_raw), currency)

    total_raw = find_labeled_value(text, labels.get("total_amount", []))
    total_amount = normalize_amount(leading_number(total_raw), currency)

    vat_block = find_labeled_value(text, labels.get("vat_block", []))
    vat_amount = normalize_amount(leading_number(vat_block), currency)
    vat_rate = percent_in(vat_block) or regex_first_match(text, regex.get("vat_rate", "(?!)"))
    if vat_rate and not vat_rate.endswith("%"):
        vat_rate = f"{vat_rate}%"

    tax_ids = regex_all_matches(text, regex.get("tax_ids_in_order", "(?!)"))
    seller_tax_code = normalize_tax_code(tax_ids[0]) if len(tax_ids) >= 1 else None
    buyer_tax_code = normalize_tax_code(tax_ids[1]) if len(tax_ids) >= 2 else None

    seller_hint = cfg.get("seller_hint", "Meta Platforms")
    seller = seller_hint if seller_hint.lower() in text.lower() else None

    # Buyer name: this bill's layout is [seller name, seller address lines,
    # "Tax ID: <seller>", buyer name, buyer address lines, "Tax ID: <buyer>"]
    # (verified against a real Meta invoice) — so the buyer block always
    # starts on the line right after the SELLER's Tax ID line, regardless
    # of how many address lines follow it.
    buyer = None
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    tax_id_line_indices = [i for i, l in enumerate(lines) if l.lower().startswith("tax id")]
    if tax_id_line_indices and tax_id_line_indices[0] + 1 < len(lines):
        buyer = lines[tax_id_line_indices[0] + 1]

    if not reference_candidates:
        warnings.append("Không tìm thấy Số tham chiếu trên Facebook bill")
    if total_amount is None:
        warnings.append("Không trích xuất được tổng số tiền thanh toán")

    confidence = sum(
        1
        for v in [reference_candidates, invoice_number, invoice_date, total_amount, buyer_tax_code]
        if v
    ) / 5

    return ExtractedDocument(
        doc_type=DocType.FACEBOOK,
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
        payment_method=payment_method,
        transaction_date=invoice_date,
        description=description,
        raw_text=text,
        extraction_confidence=confidence,
        warnings=warnings,
    )
