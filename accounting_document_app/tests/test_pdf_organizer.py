"""Test sắp xếp PDF — dùng file .txt giả làm 'PDF' (organizer chỉ copy byte,
không đọc nội dung) để không cần PDF thật vẫn kiểm tra đúng cây thư mục."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.exporters.pdf_organizer import PdfOrganizer
from app.matching.dossier_builder import DossierBuilder
from app.matching.dossier_validator import DossierValidator
from app.models.document import Document
from app.models.enums import DocumentType, ProcessingStatus
from matching_helpers import debit, meta, vat


def _write_fake_pdf(tmp_path: Path, doc: Document) -> Document:
    """Gán ``file_path`` thành file thật trên đĩa (nội dung không quan trọng —
    organizer chỉ copy byte nguyên vẹn, không đọc lại PDF)."""
    real = tmp_path / doc.file_name
    real.write_bytes(f"noi dung gia cua {doc.file_name}".encode())
    doc.file_path = real
    return doc


def _build_and_validate(tmp_path, docs):
    for d in docs:
        _write_fake_pdf(tmp_path, d)
    result = DossierBuilder().build(docs)
    docs_by_id = {d.document_id: d for d in docs}
    validator = DossierValidator()
    for dossier in result.dossiers:
        validator.validate(dossier, docs_by_id)
    return result


class TestBoDuBaChungTu:
    def test_tao_dung_cau_truc_thu_muc(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        docs = [meta("ABCD1234EF"), debit("ABCD1234EF", "FT1"), vat("ABCD1234EF", "FT1")]
        result = _build_and_validate(src, docs)

        out = tmp_path / "OUTPUT"
        organize_result = PdfOrganizer(out).organize(result.dossiers, docs)

        folder = out / "HS000001_ABCD1234EF"
        assert (folder / "01_META_INVOICE.pdf").is_file()
        assert (folder / "02_VPBANK_DEBIT_NOTE.pdf").is_file()
        assert (folder / "03_VPBANK_VAT_INVOICE.pdf").is_file()
        assert (folder / "_manifest.txt").is_file()
        assert organize_result.copied_files == 3

    def test_khong_dung_thu_muc_needs_review(self, tmp_path):
        """Hồ sơ VALID nằm thẳng trong OUTPUT/, không qua NEEDS_REVIEW/."""
        src = tmp_path / "src"
        src.mkdir()
        docs = [meta("ABCD1234EF"), debit("ABCD1234EF", "FT1"), vat("ABCD1234EF", "FT1")]
        result = _build_and_validate(src, docs)

        out = tmp_path / "OUTPUT"
        PdfOrganizer(out).organize(result.dossiers, docs)
        assert (out / "HS000001_ABCD1234EF").is_dir()
        assert not (out / "NEEDS_REVIEW").exists()

    def test_khong_dung_gi_toi_file_goc(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        docs = [meta("ABCD1234EF"), debit("ABCD1234EF", "FT1"), vat("ABCD1234EF", "FT1")]
        result = _build_and_validate(src, docs)
        original_bytes = {d.file_path: d.file_path.read_bytes() for d in docs}

        PdfOrganizer(tmp_path / "OUTPUT").organize(result.dossiers, docs)

        for path, content in original_bytes.items():
            assert path.read_bytes() == content  # file gốc không đổi
            assert path.is_file()  # file gốc vẫn còn (không bị move/xoá)


class TestThieuChungTu:
    def test_thieu_vat_vao_needs_review_kem_ghi_chu(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        docs = [meta("ABCD1234EF"), debit("ABCD1234EF", "FT1")]
        result = _build_and_validate(src, docs)

        out = tmp_path / "OUTPUT"
        PdfOrganizer(out).organize(result.dossiers, docs)

        folder = out / "NEEDS_REVIEW" / "HS000001_ABCD1234EF"
        assert (folder / "01_META_INVOICE.pdf").is_file()
        assert (folder / "02_VPBANK_DEBIT_NOTE.pdf").is_file()
        assert (folder / "_MISSING_03_VPBANK_VAT_INVOICE.txt").is_file()
        assert not (folder / "03_VPBANK_VAT_INVOICE.pdf").exists()


class TestTrungLap:
    def test_hai_meta_cung_reference_deu_duoc_copy_kem_hau_to(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        docs = [meta("ABCD1234EF"), meta("ABCD1234EF"), debit("ABCD1234EF", "FT1")]
        result = _build_and_validate(src, docs)

        out = tmp_path / "OUTPUT"
        PdfOrganizer(out).organize(result.dossiers, docs)

        folder = out / "NEEDS_REVIEW" / "HS000001_ABCD1234EF"
        assert (folder / "01_META_INVOICE_a.pdf").is_file()
        assert (folder / "01_META_INVOICE_b.pdf").is_file()
        assert (folder / "_DUPLICATE_01_META_INVOICE.txt").is_file()
        assert not (folder / "01_META_INVOICE.pdf").exists()  # không tự chọn bản nào


class TestChungTuChuaGhep:
    def test_unknown_type_vao_thu_muc_rieng(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        from matching_helpers import make_doc

        docs = [make_doc(DocumentType.UNKNOWN)]
        for d in docs:
            _write_fake_pdf(src, d)

        result = PdfOrganizer(tmp_path / "OUTPUT").organize([], docs)
        assert (tmp_path / "OUTPUT" / "UNMATCHED" / "UNKNOWN_TYPE" / docs[0].file_name).is_file()
        assert result.unmatched_files == 1

    def test_reference_not_found_vao_thu_muc_rieng(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        docs = [meta(None)]
        for d in docs:
            _write_fake_pdf(src, d)

        result = PdfOrganizer(tmp_path / "OUTPUT").organize([], docs)
        assert (tmp_path / "OUTPUT" / "UNMATCHED" / "REFERENCE_NOT_FOUND" / docs[0].file_name).is_file()


class TestFileTrungLapByteHash:
    def test_duplicate_file_vao_thu_muc_duplicates(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        original = meta("ABCD1234EF")
        original.file_hash = "deadbeef" * 8
        copy = meta("ABCD1234EF")
        copy.file_hash = original.file_hash
        copy.processing_status = ProcessingStatus.DUPLICATE_FILE
        copy.duplicate_of_id = original.document_id
        for d in (original, copy):
            _write_fake_pdf(src, d)

        result = PdfOrganizer(tmp_path / "OUTPUT").organize([], [original, copy])
        dup_folder = tmp_path / "OUTPUT" / "DUPLICATES" / original.file_hash[:16]
        assert (dup_folder / copy.file_name).is_file()
        assert result.duplicate_files == 1


class TestTenThuMucAnToan:
    def test_khong_co_reference_dung_noref(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        docs = [debit(None)]  # match_key None -> dossier.reference None
        result = _build_and_validate(src, docs)

        # debit không có match_key -> vào unmatched, không tạo dossier nào
        assert result.unmatched == docs
