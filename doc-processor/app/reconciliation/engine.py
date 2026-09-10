"""Reconciliation Engine stage.

Cross-checks the 3 documents in a DocumentSet against each other on 6
criteria (A-F per spec): Reference, Amount, Date, Tax code, Payment
information, Invoice information. Each criterion yields MATCH /
PARTIAL_MATCH / MISMATCH / MISSING, never a crash — missing data just
degrades the result rather than raising.

Design notes (see config/settings.yaml `reconciliation.applicable_roles`):
- A criterion is only compared across the doc roles that structurally
  carry that field (e.g. tax_code is only meaningful for facebook/
  vat_invoice — a bank debit note never prints a tax code).
- "invoice_info" deliberately checks *presence* of an invoice number on
  both sides rather than equality: Facebook's own invoice numbering and
  the VAT invoice's numbering are two independent systems and will
  never be literally equal.
- Amount/date use configurable tolerances (FX rounding, and invoice
  date vs. bank value date legitimately differing by a few days).
"""
from __future__ import annotations

import re
from datetime import date as date_
from decimal import Decimal
from typing import Callable, Optional

from app.core.config_loader import get_settings
from app.models.schema import DocumentSet, ExtractedDocument, MatchResult, ReconciliationField

_DIGIT_RUN_RE = re.compile(r"\d{4,}")


def _fmt(v) -> Optional[str]:
    if v is None or v == "":
        return None
    if isinstance(v, (set, frozenset)):
        return ", ".join(sorted(v)) or None
    return str(v)


def _get_reference_set(d: ExtractedDocument) -> Optional[set[str]]:
    if not d.reference_candidates:
        return None
    return {c.strip().upper() for c in d.reference_candidates if c}


def _get_amount(d: ExtractedDocument) -> Optional[Decimal]:
    return d.total_amount


def _get_date(d: ExtractedDocument) -> Optional[date_]:
    return d.invoice_date or d.transaction_date


def _get_tax_code(d: ExtractedDocument) -> Optional[str]:
    return d.tax_code.strip().upper() if d.tax_code else None


def _get_payment_method(d: ExtractedDocument) -> Optional[str]:
    return d.payment_method.strip() if d.payment_method else None


def _get_invoice_presence(d: ExtractedDocument) -> Optional[str]:
    return "HAS_INVOICE_NUMBER" if d.invoice_number else None


def _eq_reference(a: set[str], b: set[str]) -> bool:
    return bool(a & b)


def _eq_amount(a: Decimal, b: Decimal, tolerance_percent: float) -> bool:
    if a == b:
        return True
    base = max(abs(a), abs(b))
    if base == 0:
        return True
    diff_pct = abs(a - b) / base * 100
    return diff_pct <= Decimal(str(tolerance_percent))


def _eq_date(a: date_, b: date_, tolerance_days: int) -> bool:
    return abs((a - b).days) <= tolerance_days


def _eq_exact_ci(a: str, b: str) -> bool:
    return a == b


def _eq_tax_code(a: str, b: str) -> bool:
    # Compare by digits only: the same MST is legitimately printed with or
    # without dashes depending on the issuer (e.g. Meta's foreign-contractor
    # invoice shows "01-1038264-0", the matching VAT invoice/XML shows
    # "0110382640" — same 10-digit code).
    return re.sub(r"\D", "", a) == re.sub(r"\D", "", b)


def _eq_payment_method(a: str, b: str) -> bool:
    digits_a = set(_DIGIT_RUN_RE.findall(a))
    digits_b = set(_DIGIT_RUN_RE.findall(b))
    if digits_a and digits_b:
        # compare by shared trailing digits (masked card numbers only
        # reveal the last 4) rather than requiring full-string equality
        tails_a = {d[-4:] for d in digits_a}
        tails_b = {d[-4:] for d in digits_b}
        if tails_a & tails_b:
            return True
    return a.strip().lower() == b.strip().lower()


def _eq_invoice_presence(a: str, b: str) -> bool:
    return a == b


def _reconcile_field(
    ds: DocumentSet,
    applicable_roles: list[str],
    getter: Callable[[ExtractedDocument], object],
    equal_fn: Callable[[object, object], bool],
    missing_detail: str = "Không đủ chứng từ liên quan để đối chiếu tiêu chí này",
    incomplete_detail: str = "Thiếu dữ liệu trích xuất để đối chiếu",
) -> ReconciliationField:
    present_roles = [r for r in applicable_roles if getattr(ds, r, None) is not None]

    if len(present_roles) < 2:
        return ReconciliationField(
            result=MatchResult.MISSING,
            values={r: _fmt(getter(getattr(ds, r))) for r in present_roles},
            detail=missing_detail,
        )

    raw_values = {r: getter(getattr(ds, r)) for r in present_roles}
    display_values = {r: _fmt(v) for r, v in raw_values.items()}
    non_null = {r: v for r, v in raw_values.items() if v not in (None, "", set())}

    if len(non_null) < 2:
        return ReconciliationField(result=MatchResult.MISSING, values=display_values, detail=incomplete_detail)

    keys = list(non_null.keys())
    equal_count = 0
    total = 0
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            total += 1
            if equal_fn(non_null[keys[i]], non_null[keys[j]]):
                equal_count += 1

    has_missing_among_present = len(non_null) < len(present_roles)
    if equal_count == total:
        result = MatchResult.PARTIAL_MATCH if has_missing_among_present else MatchResult.MATCH
    elif equal_count > 0:
        result = MatchResult.PARTIAL_MATCH
    else:
        result = MatchResult.MISMATCH

    detail = None
    if result != MatchResult.MATCH and has_missing_among_present:
        missing_roles = [r for r in present_roles if r not in non_null]
        detail = f"Không có dữ liệu ở: {', '.join(missing_roles)}"

    return ReconciliationField(result=result, values=display_values, detail=detail)


def reconcile(ds: DocumentSet) -> dict[str, ReconciliationField]:
    settings = get_settings().get("reconciliation", {})
    applicable = settings.get("applicable_roles", {})
    amount_tol = settings.get("amount_tolerance_percent", 1.0)
    date_tol = settings.get("date_tolerance_days", 5)

    fields: dict[str, ReconciliationField] = {}

    fields["reference"] = _reconcile_field(
        ds, applicable.get("reference", []), _get_reference_set, _eq_reference
    )
    fields["amount"] = _reconcile_field(
        ds, applicable.get("amount", []), _get_amount, lambda a, b: _eq_amount(a, b, amount_tol)
    )
    fields["date"] = _reconcile_field(
        ds, applicable.get("date", []), _get_date, lambda a, b: _eq_date(a, b, date_tol)
    )
    fields["tax_code"] = _reconcile_field(
        ds, applicable.get("tax_code", []), _get_tax_code, _eq_tax_code
    )
    fields["payment_method"] = _reconcile_field(
        ds, applicable.get("payment_method", []), _get_payment_method, _eq_payment_method
    )
    fields["invoice_info"] = _reconcile_field(
        ds, applicable.get("invoice_info", []), _get_invoice_presence, _eq_invoice_presence,
        missing_detail="Không đủ chứng từ để đối chiếu thông tin hóa đơn",
        incomplete_detail="Thiếu số hóa đơn ở một trong hai chứng từ",
    )

    return fields
