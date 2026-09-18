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

    def test_vietinbank_debit_advice_khong_co_match_key_luong_dossier_goc(self):
        """CỐ Ý ``None`` — luồng dossier gốc (K1/K2) chỉ xử lý 3 loại VPBank
        cố định, không phải nơi VietinBank tham gia ghép bộ (xem
        ``app/matching/payment_group_matcher.py`` cho luồng bank-agnostic)."""
        doc = _doc(DocumentType.VIETINBANK_DEBIT_ADVICE, facebook_reference="ABCD1234EF")
        assert doc.match_key is None


class TestDisplayReference:
    """``display_reference`` — CHỈ để hiển thị (CHUNG_TU/UI), không dùng để
    ghép bộ. Khác ``match_key`` đúng một điểm: có thêm VietinBank."""

    def test_vietinbank_debit_advice_hien_thi_dung_reference(self):
        doc = _doc(DocumentType.VIETINBANK_DEBIT_ADVICE, facebook_reference="ABCD1234EF")
        assert doc.display_reference == "ABCD1234EF"

    def test_cac_loai_khac_giu_nguyen_nhu_match_key(self):
        doc = _doc(DocumentType.VPBANK_DEBIT_NOTE, meta_reference="ABCD1234EF")
        assert doc.display_reference == doc.match_key == "ABCD1234EF"


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


class TestPhamViTrang:
    """Một file PDF có thể chứa nhiều chứng từ (Q13)."""

    def _doc_with_pages(self, start: int, end: int, index: int = 0) -> Document:
        return Document(
            file_name="gop.pdf",
            file_path=Path("gop.pdf"),
            file_hash="abc123",
            document_type=DocumentType.VPBANK_DEBIT_NOTE,
            page_start=start,
            page_end=end,
            segment_index=index,
        )

    def test_segment_id_phan_biet_cac_chung_tu_cung_file(self):
        first = self._doc_with_pages(1, 1, 0)
        second = self._doc_with_pages(2, 2, 1)
        assert first.file_hash == second.file_hash
        assert first.segment_id != second.segment_id

    def test_segment_id_gom_hash_va_pham_vi_trang(self):
        assert self._doc_with_pages(3, 4).segment_id == "abc123:3-4"

    def test_nhan_pham_vi_trang(self):
        assert self._doc_with_pages(1, 1).page_range_label == "trang 1"
        assert self._doc_with_pages(3, 4).page_range_label == "trang 3-4"
