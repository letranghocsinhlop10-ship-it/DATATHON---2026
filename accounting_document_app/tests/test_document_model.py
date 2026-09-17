"""Test model ``Document`` — đặc biệt là ``match_key``, khoá ghép hồ sơ."""

from __future__ import annotations

from pathlib import Path

from app.models.document import Document
from app.models.enums import DocumentType, ProcessingStatus
from app.models.extracted_field import ExtractedField, FieldSet


def _doc(document_type: DocumentType, **values) -> Document:
    fields = FieldSet()
    for name, value in values.items():
        fields.set(ExtractedField(field_name=name, value=value, rule_id="test"))
    return Document(
        file_name="x.pdf",
        file_path=Path("x.pdf"),
        file_hash="h",
        document_type=document_type,
        fields=fields,
    )


class TestMatchKey:
    def test_hoa_don_meta_dung_reference_cua_chinh_no(self):
        doc = _doc(DocumentType.META_INVOICE, reference_number="ABCD1234EF")
        assert doc.match_key == "ABCD1234EF"

    def test_debit_note_dung_reference_nha_cung_cap(self):
        doc = _doc(
            DocumentType.VPBANK_DEBIT_NOTE,
            reference_number=None,
            meta_reference="ABCD1234EF",
            transaction_code="FT26000000000001",
        )
        assert doc.match_key == "ABCD1234EF"

    def test_hoa_don_gtgt_dung_reference_nha_cung_cap_chu_khong_phai_cua_ngan_hang(self):
        """Khoá chính là reference nhà cung cấp, không phải số tham chiếu VPBank."""
        doc = _doc(
            DocumentType.VPBANK_VAT_INVOICE,
            reference_number="FT26000000000001_20260801",
            meta_reference="ABCD1234EF",
        )
        assert doc.match_key == "ABCD1234EF"

    def test_chung_tu_unknown_khong_co_khoa(self):
        doc = _doc(DocumentType.UNKNOWN, reference_number="ABCD1234EF")
        assert doc.match_key is None

    def test_khong_doc_duoc_reference_thi_khong_co_khoa(self):
        doc = _doc(DocumentType.VPBANK_DEBIT_NOTE, meta_reference=None)
        assert doc.match_key is None


class TestTruongThieu:
    def test_truong_chua_trich_xuat_tra_none(self):
        doc = _doc(DocumentType.META_INVOICE)
        assert doc.value_of("khong_ton_tai") is None

    def test_field_of_luon_tra_ve_doi_tuong(self):
        doc = _doc(DocumentType.META_INVOICE)
        field = doc.field_of("khong_ton_tai")
        assert field.found is False
        assert field.error == "NOT_EXTRACTED"


class TestLoi:
    def test_liet_ke_truong_loi(self):
        fields = FieldSet()
        fields.set(ExtractedField(field_name="a", value="x"))
        fields.set(ExtractedField(field_name="b", value=None, error="NOT_FOUND"))
        doc = Document(
            file_name="x.pdf",
            file_path=Path("x.pdf"),
            file_hash="h",
            document_type=DocumentType.META_INVOICE,
            fields=fields,
        )
        assert doc.has_errors is True
        assert doc.field_errors == {"b": "NOT_FOUND"}

    def test_trang_thai_mac_dinh(self):
        assert _doc(DocumentType.META_INVOICE).processing_status is ProcessingStatus.OK


class TestExtractedField:
    def test_sua_tay_giu_nguyen_bang_chung_cu(self):
        original = ExtractedField(
            field_name="reference_number",
            value="ABCD1234EF",
            raw_snippet="Số tham chiếu: ABCD1234EF",
            page_number=1,
            rule_id="meta.reference_number",
        )
        edited = original.replaced_by_user("ZZZZ9999YY")
        assert edited.value == "ZZZZ9999YY"
        assert edited.is_manual is True
        assert edited.raw_snippet == original.raw_snippet
        assert edited.rule_id == original.rule_id
