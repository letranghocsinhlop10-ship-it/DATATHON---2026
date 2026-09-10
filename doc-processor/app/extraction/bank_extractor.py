"""Extractor for bank debit advices / transaction notes (Phiếu giao dịch
ghi nợ / Giấy báo Nợ). Calibrated on a VPBank "DEBIT NOTE" PDF, which
extracts cleanly in label: value reading order."""
from __future__ import annotations

from app.core.config_loader import get_extraction_patterns
from app.extraction.base import (
    clean_code,
    find_labeled_value,
    normalize_amount,
    normalize_date,
    regex_first_match,
)
from app.extraction.common import detect_currency, leading_number
from app.models.schema import DocType, ExtractedDocument


def extract_bank_debit(text: str, source_file: str) -> ExtractedDocument:
    cfg = get_extraction_patterns().get("bank_debit", {})
    labels = cfg.get("labels", {})
    regex = cfg.get("regex", {})

    warnings: list[str] = []

    reference_raw = find_labeled_value(text, labels.get("reference", []))
    # bank transaction codes are sometimes suffixed like "FT123\BNK" — keep
    # just the code itself.
    reference = clean_code(reference_raw.split("\\")[0].strip()) if reference_raw else None
    ref_embedded = clean_code(regex_first_match(text, regex.get("reference_embedded", "(?!)")))
    reference_candidates = [r for r in (reference, ref_embedded) if r]

    transaction_date = normalize_date(find_labeled_value(text, labels.get("transaction_date", [])))
    buyer = find_labeled_value(text, labels.get("buyer", []))
    bank_name = find_labeled_value(text, labels.get("bank_name", []))
    account_no = find_labeled_value(text, labels.get("account_no", []))
    currency_raw = find_labeled_value(text, labels.get("currency", []))
    currency = (currency_raw or detect_currency(text) or "VND").strip().upper()

    amount_raw = find_labeled_value(text, labels.get("total_amount", []))
    total_amount = normalize_amount(leading_number(amount_raw), currency)

    description = find_labeled_value(text, labels.get("description", []))
    masked_card = regex_first_match(text, regex.get("masked_card", "(?!)"))
    payment_method = f"Thẻ {masked_card}" if masked_card else None

    bank_info = " - ".join(filter(None, [bank_name, account_no]))

    if not reference_candidates:
        warnings.append("Không tìm thấy Mã giao dịch/Reference trên giấy báo nợ")
    if total_amount is None:
        warnings.append("Không trích xuất được số tiền giao dịch")

    confidence = sum(
        1 for v in [reference_candidates, transaction_date, total_amount, bank_name] if v
    ) / 4

    return ExtractedDocument(
        doc_type=DocType.BANK_DEBIT,
        source_file=source_file,
        reference_candidates=reference_candidates,
        buyer=buyer,
        total_amount=total_amount,
        currency=currency,
        payment_method=payment_method,
        bank_info=bank_info or None,
        transaction_date=transaction_date,
        description=description,
        raw_text=text,
        extraction_confidence=confidence,
        warnings=warnings,
    )
