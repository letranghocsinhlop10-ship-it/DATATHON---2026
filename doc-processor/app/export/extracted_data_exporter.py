"""Raw extracted-data workbook: one row per source PDF.

Unlike the MISA workbook (one consolidated row per matched set), this file
keeps every value extracted from every individual PDF for audit/debugging.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from app.export.excel_utils import write_table
from app.models.schema import DocumentSet, ExtractedDocument


HEADERS = [
    "Set Reference", "Document Type", "Source File", "Output Folder",
    "Reference Candidates", "Invoice Number", "Invoice Date", "Seller", "Buyer",
    "Seller Tax Code", "Buyer Tax Code", "Amount Before VAT", "VAT Amount",
    "VAT Rate", "Total Amount", "Currency", "Payment Method", "Bank Info",
    "Transaction Date", "Description", "Extraction Confidence", "Used OCR",
    "Used XML", "Warnings", "Error",
]


def _row(ds: DocumentSet, doc: ExtractedDocument) -> list:
    return [
        ds.reference, doc.doc_type, doc.source_file, ds.output_folder or "",
        "; ".join(doc.reference_candidates), doc.invoice_number, doc.invoice_date,
        doc.seller, doc.buyer, doc.seller_tax_code, doc.tax_code,
        doc.amount_before_vat, doc.vat_amount, doc.vat_rate, doc.total_amount,
        doc.currency, doc.payment_method, doc.bank_info, doc.transaction_date,
        doc.description, doc.extraction_confidence, doc.used_ocr,
        doc.used_xml_sidecar, "; ".join(doc.warnings), doc.error_reason or "",
    ]


def build_extracted_rows(document_sets: list[DocumentSet]) -> list[list]:
    rows: list[list] = []
    for ds in document_sets:
        docs = list(ds.present_docs.values())
        docs.extend(ds.duplicate_facebook)
        docs.extend(ds.duplicate_vat_invoice)
        docs.extend(ds.duplicate_bank_debit)
        docs.extend(ds.error_files)
        rows.extend(_row(ds, doc) for doc in docs)
    return rows


def write_extracted_data_excel(document_sets: list[DocumentSet], path: str | Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Extracted Data"
    write_table(ws, HEADERS, build_extracted_rows(document_sets))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
