"""reconciliation_report.xlsx exporter (spec section 8).

Sheets: Summary, Valid, Errors, Missing, Duplicates, MISA Import.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Optional

from openpyxl import Workbook

from app.export.excel_utils import write_table
from app.export.misa_exporter import build_misa_rows
from app.models.schema import CompletenessStatus, DocumentSet, DocumentStatus

_RECON_HEADERS = [
    "Reference",
    "Facebook Amount",
    "VAT Amount",
    "Bank Amount",
    "Difference",
    "Reference Match",
    "Amount Match",
    "Date Match",
    "Tax Code Check",
    "Payment Method Check",
    "Invoice Info Check",
    "Document Completeness",
    "Final Status",
    "Issue",
]


def _amount(ds: DocumentSet, role: str) -> Optional[Decimal]:
    doc = getattr(ds, role, None)
    return doc.total_amount if doc else None


def _difference(amounts: list[Optional[Decimal]]) -> Optional[Decimal]:
    present = [a for a in amounts if a is not None]
    if len(present) < 2:
        return None
    return max(present) - min(present)


def _recon_result(ds: DocumentSet, key: str) -> str:
    field = ds.reconciliation.get(key)
    return field.result.value if field else "N/A"


def build_reconciliation_rows(document_sets: list[DocumentSet]) -> list[list]:
    rows = []
    for ds in document_sets:
        fb_amt, vat_amt, bank_amt = _amount(ds, "facebook"), _amount(ds, "vat_invoice"), _amount(ds, "bank_debit")
        rows.append(
            [
                ds.reference,
                fb_amt,
                vat_amt,
                bank_amt,
                _difference([fb_amt, vat_amt, bank_amt]),
                _recon_result(ds, "reference"),
                _recon_result(ds, "amount"),
                _recon_result(ds, "date"),
                _recon_result(ds, "tax_code"),
                _recon_result(ds, "payment_method"),
                _recon_result(ds, "invoice_info"),
                ds.completeness.value if hasattr(ds.completeness, "value") else ds.completeness,
                ds.document_status.value if hasattr(ds.document_status, "value") else ds.document_status,
                "; ".join(ds.issues) if ds.issues else "",
            ]
        )
    return rows


def build_summary_rows(document_sets: list[DocumentSet]) -> list[list]:
    total = len(document_sets)

    def count_completeness(status: CompletenessStatus) -> int:
        return sum(1 for ds in document_sets if ds.completeness == status)

    def count_status(status: DocumentStatus) -> int:
        return sum(1 for ds in document_sets if ds.document_status == status)

    return [
        ["Tổng số bộ chứng từ", total],
        ["COMPLETE", count_completeness(CompletenessStatus.COMPLETE)],
        ["INCOMPLETE", count_completeness(CompletenessStatus.INCOMPLETE)],
        ["DUPLICATE", count_completeness(CompletenessStatus.DUPLICATE)],
        ["ERROR", count_completeness(CompletenessStatus.ERROR)],
        ["VALID", count_status(DocumentStatus.VALID)],
        ["NEEDS_REVIEW", count_status(DocumentStatus.NEEDS_REVIEW)],
        ["INVALID", count_status(DocumentStatus.INVALID)],
    ]


def write_reconciliation_report(document_sets: list[DocumentSet], path: str | Path) -> Path:
    wb = Workbook()

    ws_summary = wb.active
    ws_summary.title = "Summary"
    write_table(ws_summary, ["Chỉ tiêu", "Số lượng"], build_summary_rows(document_sets))

    recon_rows = build_reconciliation_rows(document_sets)

    ws_valid = wb.create_sheet("Valid")
    write_table(
        ws_valid, _RECON_HEADERS,
        [row for row, ds in zip(recon_rows, document_sets) if ds.document_status == DocumentStatus.VALID],
    )

    ws_errors = wb.create_sheet("Errors")
    write_table(
        ws_errors, _RECON_HEADERS,
        [
            row for row, ds in zip(recon_rows, document_sets)
            if ds.document_status == DocumentStatus.INVALID or ds.completeness == CompletenessStatus.ERROR
        ],
    )

    ws_missing = wb.create_sheet("Missing")
    write_table(
        ws_missing, _RECON_HEADERS,
        [row for row, ds in zip(recon_rows, document_sets) if ds.completeness == CompletenessStatus.INCOMPLETE],
    )

    ws_dup = wb.create_sheet("Duplicates")
    write_table(
        ws_dup, _RECON_HEADERS,
        [row for row, ds in zip(recon_rows, document_sets) if ds.completeness == CompletenessStatus.DUPLICATE],
    )

    ws_all = wb.create_sheet("All Sets")
    write_table(ws_all, _RECON_HEADERS, recon_rows)

    misa_headers, misa_rows = build_misa_rows(document_sets)
    ws_misa = wb.create_sheet("MISA Import")
    write_table(ws_misa, misa_headers, misa_rows)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
