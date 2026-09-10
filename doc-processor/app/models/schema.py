"""Core data models shared across the whole pipeline.

Kept as plain pydantic models (not tied to any single module) so every
stage of the pipeline (PDF Reader -> OCR -> Classifier -> Extractor ->
Reference Matcher -> Reconciliation -> Validation -> Categorizer ->
File Organizer -> Exporters) speaks the same schema.
"""
from __future__ import annotations

from datetime import date as date_
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class DocType(str, Enum):
    FACEBOOK = "facebook"
    VAT_INVOICE = "vat_invoice"
    BANK_DEBIT = "bank_debit"
    UNKNOWN = "unknown"


class CompletenessStatus(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    DUPLICATE = "DUPLICATE"
    ERROR = "ERROR"


class MatchResult(str, Enum):
    MATCH = "MATCH"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    MISMATCH = "MISMATCH"
    MISSING = "MISSING"


class CheckResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    NOT_FOUND = "NOT_FOUND"


class DocumentStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class ExtractedDocument(BaseModel):
    """Everything pulled out of a single PDF (+ optional XML sidecar)."""

    doc_type: DocType = DocType.UNKNOWN
    source_file: str
    source_role_folder: Optional[str] = None  # facebook / vat / bank (from INPUT/<role>/)
    file_hash: Optional[str] = None

    # Linking
    reference_candidates: list[str] = Field(default_factory=list)
    reference: Optional[str] = None  # chosen/normalized reference, filled by matcher

    # Invoice-ish fields
    invoice_number: Optional[str] = None
    invoice_date: Optional[date_] = None
    seller: Optional[str] = None
    buyer: Optional[str] = None
    seller_tax_code: Optional[str] = None
    tax_code: Optional[str] = None  # buyer tax code (kept as `tax_code` per spec naming)
    amount_before_vat: Optional[Decimal] = None
    vat_amount: Optional[Decimal] = None
    vat_rate: Optional[str] = None
    total_amount: Optional[Decimal] = None
    currency: Optional[str] = None
    payment_method: Optional[str] = None
    bank_info: Optional[str] = None
    transaction_date: Optional[date_] = None
    description: Optional[str] = None

    # Diagnostics
    raw_text: str = ""
    used_ocr: bool = False
    used_xml_sidecar: bool = False
    xml_sidecar_path: Optional[str] = None
    extraction_confidence: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    is_error: bool = False
    error_reason: Optional[str] = None

    model_config = ConfigDict(use_enum_values=False)


class ReconciliationField(BaseModel):
    result: MatchResult
    values: dict[str, Optional[str]] = Field(default_factory=dict)  # doc_type -> normalized value shown
    detail: Optional[str] = None


class ValidationItem(BaseModel):
    rule_id: str
    field: str
    result: CheckResult
    severity: str = "FAIL"  # FAIL | WARNING (severity of a FAIL-type result)
    detail: Optional[str] = None


class DocumentSet(BaseModel):
    reference: str
    facebook: Optional[ExtractedDocument] = None
    vat_invoice: Optional[ExtractedDocument] = None
    bank_debit: Optional[ExtractedDocument] = None

    # extra copies beyond the first one seen per doc_type -> DUPLICATE
    duplicate_facebook: list[ExtractedDocument] = Field(default_factory=list)
    duplicate_vat_invoice: list[ExtractedDocument] = Field(default_factory=list)
    duplicate_bank_debit: list[ExtractedDocument] = Field(default_factory=list)

    # unreadable / unclassifiable files that could not be placed in any of
    # the 3 roles above (see matching/reference_matcher.py) — each gets its
    # own synthetic DocumentSet with completeness=ERROR.
    error_files: list[ExtractedDocument] = Field(default_factory=list)

    completeness: CompletenessStatus = CompletenessStatus.INCOMPLETE
    reconciliation: dict[str, ReconciliationField] = Field(default_factory=dict)
    validation: list[ValidationItem] = Field(default_factory=list)
    document_status: DocumentStatus = DocumentStatus.NEEDS_REVIEW

    category: Optional[str] = None
    issues: list[str] = Field(default_factory=list)
    output_folder: Optional[str] = None

    @property
    def present_docs(self) -> dict[str, ExtractedDocument]:
        out = {}
        if self.facebook:
            out["facebook"] = self.facebook
        if self.vat_invoice:
            out["vat_invoice"] = self.vat_invoice
        if self.bank_debit:
            out["bank_debit"] = self.bank_debit
        return out


class ErrorFile(BaseModel):
    source_file: str
    reason: str


class JobSummary(BaseModel):
    total_files: int = 0
    complete_sets: int = 0
    incomplete_sets: int = 0
    valid_sets: int = 0
    error_files: int = 0
    duplicate_sets: int = 0
