"""Tiện ích dựng ``Document`` giả cho test tầng matching."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from app.models.document import Document
from app.models.enums import DocumentType, TextSource
from app.models.extracted_field import ExtractedField, FieldSet

_counter = 0


def make_doc(
    document_type: DocumentType,
    *,
    document_id: int | None = None,
    text_source: TextSource = TextSource.TEXT_LAYER,
    field_errors: dict[str, str] | None = None,
    **values,
) -> Document:
    """Dựng một ``Document`` với các trường tuỳ ý đã điền sẵn.

    ``document_id`` tự tăng nếu không truyền, để mỗi lời gọi cho ra một
    chứng từ phân biệt được (cần thiết cho các test so sánh danh sách).

    ``field_errors`` mô phỏng mã lỗi mà pipeline trích xuất thật sự gắn vào
    (ví dụ ``REFERENCE_INVALID_FORMAT``, ``UNEXPECTED_MERCHANT_SUFFIX``) —
    helper này KHÔNG tự chạy qua ``normalize_reference()``/rule engine thật,
    nên test nào cần kiểm tra hành vi phụ thuộc lỗi trường phải truyền rõ.
    """
    global _counter
    if document_id is None:
        _counter += 1
        document_id = _counter

    field_errors = field_errors or {}
    fields = FieldSet()
    for name, value in values.items():
        fields.set(
            ExtractedField(
                field_name=name, value=value, rule_id="test", error=field_errors.get(name)
            )
        )

    return Document(
        file_name=f"doc{document_id}.pdf",
        file_path=Path(f"doc{document_id}.pdf"),
        file_hash=f"hash{document_id}",
        document_type=document_type,
        text_source=text_source,
        fields=fields,
        document_id=document_id,
    )


def meta(reference_number: str, **values) -> Document:
    return make_doc(DocumentType.META_INVOICE, reference_number=reference_number, **values)


def debit(meta_reference: str, transaction_code: str | None = None, **values) -> Document:
    return make_doc(
        DocumentType.VPBANK_DEBIT_NOTE,
        meta_reference=meta_reference,
        transaction_code=transaction_code,
        **values,
    )


def vat(meta_reference: str | None, bank_transaction_code: str | None = None, **values) -> Document:
    return make_doc(
        DocumentType.VPBANK_VAT_INVOICE,
        meta_reference=meta_reference,
        bank_transaction_code=bank_transaction_code,
        **values,
    )


__all__ = ["make_doc", "meta", "debit", "vat", "date", "Decimal"]
