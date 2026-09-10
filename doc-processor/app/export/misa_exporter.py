"""MISA import spreadsheet exporter.

The column list/headers come entirely from config/misa_column_mapping.yaml
(a placeholder until the real MISA import template is available) — this
module only supplies the RESOLVERS that know how to pull a named field
out of a DocumentSet. Adding/renaming/reordering a column that already
has a resolver is a YAML-only change.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from openpyxl import Workbook

from app.core.config_loader import get_misa_column_mapping
from app.export.excel_utils import write_table
from app.models.schema import CheckResult, DocumentSet, ExtractedDocument

_DEFAULT_PRIORITY: dict[str, tuple[str, ...]] = {
    "invoice_number": ("vat_invoice", "facebook"),
    "invoice_date": ("vat_invoice", "facebook"),
    "seller": ("vat_invoice", "facebook"),
    "buyer": ("vat_invoice", "facebook", "bank_debit"),
    "tax_code": ("vat_invoice", "facebook"),
    "description": ("vat_invoice", "facebook", "bank_debit"),
    "amount_before_vat": ("vat_invoice", "facebook"),
    "vat_amount": ("vat_invoice", "facebook"),
    "total_amount": ("vat_invoice", "facebook", "bank_debit"),
    "currency": ("vat_invoice", "facebook", "bank_debit"),
    "payment_method": ("facebook", "bank_debit"),
}


def _pick(ds: DocumentSet, attr: str, order: tuple[str, ...]) -> object:
    for role in order:
        doc: Optional[ExtractedDocument] = getattr(ds, role, None)
        if doc is not None:
            value = getattr(doc, attr, None)
            if value not in (None, "", []):
                return value
    return None


def _summarize_check_result(ds: DocumentSet) -> str:
    fails = [i.rule_id for i in ds.validation if i.result == CheckResult.FAIL]
    warns = [i.rule_id for i in ds.validation if i.result == CheckResult.WARNING]
    if fails:
        return f"FAIL: {', '.join(fails)}"
    if warns:
        return f"WARNING: {', '.join(warns)}"
    return "PASS"


RESOLVERS: dict[str, Callable[[DocumentSet], object]] = {
    "reference": lambda ds: ds.reference,
    "invoice_number": lambda ds: _pick(ds, "invoice_number", _DEFAULT_PRIORITY["invoice_number"]),
    "invoice_date": lambda ds: _pick(ds, "invoice_date", _DEFAULT_PRIORITY["invoice_date"]),
    "seller": lambda ds: _pick(ds, "seller", _DEFAULT_PRIORITY["seller"]),
    "buyer": lambda ds: _pick(ds, "buyer", _DEFAULT_PRIORITY["buyer"]),
    "tax_code": lambda ds: _pick(ds, "tax_code", _DEFAULT_PRIORITY["tax_code"]),
    "description": lambda ds: _pick(ds, "description", _DEFAULT_PRIORITY["description"]),
    "amount_before_vat": lambda ds: _pick(ds, "amount_before_vat", _DEFAULT_PRIORITY["amount_before_vat"]),
    "vat_amount": lambda ds: _pick(ds, "vat_amount", _DEFAULT_PRIORITY["vat_amount"]),
    "total_amount": lambda ds: _pick(ds, "total_amount", _DEFAULT_PRIORITY["total_amount"]),
    "currency": lambda ds: _pick(ds, "currency", _DEFAULT_PRIORITY["currency"]),
    "payment_method": lambda ds: _pick(ds, "payment_method", _DEFAULT_PRIORITY["payment_method"]),
    "bank_transaction_date": lambda ds: ds.bank_debit.transaction_date if ds.bank_debit else None,
    "document_status": lambda ds: ds.document_status,
    "completeness": lambda ds: ds.completeness,
    "category": lambda ds: ds.category or "",
    "check_result": _summarize_check_result,
    "issue": lambda ds: "; ".join(ds.issues) if ds.issues else "",
    "source_folder": lambda ds: ds.output_folder or "",
}


def build_misa_rows(document_sets: list[DocumentSet]) -> tuple[list[str], list[list]]:
    mapping = get_misa_column_mapping().get("columns", [])
    headers = [col["header"] for col in mapping]

    rows: list[list] = []
    for ds in document_sets:
        row = []
        for col in mapping:
            resolver = RESOLVERS.get(col["field"])
            row.append(resolver(ds) if resolver else None)
        rows.append(row)
    return headers, rows


def write_misa_excel(document_sets: list[DocumentSet], path: str | Path) -> Path:
    headers, rows = build_misa_rows(document_sets)
    wb = Workbook()
    ws = wb.active
    ws.title = "MISA Import"
    write_table(ws, headers, rows)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
