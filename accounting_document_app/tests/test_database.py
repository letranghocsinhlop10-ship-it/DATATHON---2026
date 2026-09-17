"""Test tầng SQLite — schema, lưu/đọc Document và Dossier, key-value settings."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.database.database import Database
from app.database.document_repository import DocumentRepository
from app.database.dossier_repository import DossierRepository
from app.database.settings_repository import SettingsRepository
from app.models.document import Document
from app.models.dossier import Dossier, DossierIssue
from app.models.enums import DocumentType, DossierStatus, FieldMethod, Severity, TextSource
from app.models.extracted_field import ExtractedField, FieldSet


@pytest.fixture
def db():
    with Database(":memory:") as database:
        yield database


@pytest.fixture
def doc_repo(db):
    return DocumentRepository(db)


@pytest.fixture
def dossier_repo(db):
    return DossierRepository(db)


def _doc(name="x.pdf", document_type=DocumentType.META_INVOICE, **field_values) -> Document:
    fields = FieldSet()
    for field_name, value in field_values.items():
        fields.set(ExtractedField(field_name=field_name, value=value, rule_id="test"))
    return Document(
        file_name=name, file_path=Path(name), file_hash=f"hash-{name}",
        document_type=document_type, fields=fields,
    )


class TestSchema:
    def test_du_chin_bang(self, db):
        tables = {
            row[0]
            for row in db.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'"
            )
        }
        assert tables == {
            "processing_runs", "documents", "document_fields", "dossiers",
            "dossier_documents", "match_candidates", "errors", "settings", "audit_log",
        }

    def test_foreign_keys_bat(self, db):
        assert db.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


class TestDocumentRepositoryLuuVaDocLai:
    def test_luu_moi_tra_ve_id(self, doc_repo):
        doc_id = doc_repo.save(_doc())
        assert doc_id == 1
        assert doc_id == doc_repo.get(doc_id).document_id

    def test_khong_mat_gia_tri_decimal(self, doc_repo):
        doc_id = doc_repo.save(_doc(total_amount=Decimal("1100000")))
        back = doc_repo.get(doc_id)
        value = back.value_of("total_amount")
        assert value == Decimal("1100000")
        assert isinstance(value, Decimal)

    def test_khong_mat_ngay(self, doc_repo):
        from datetime import date
        doc_id = doc_repo.save(_doc(document_date=date(2026, 8, 1)))
        back = doc_repo.get(doc_id)
        assert back.value_of("document_date") == date(2026, 8, 1)

    def test_giu_nguyen_bang_chung_nguon(self, doc_repo):
        fields = FieldSet()
        fields.set(
            ExtractedField(
                field_name="reference_number",
                value="ABCD1234EF",
                raw_snippet="Số tham chiếu: ABCD1234EF",
                page_number=1,
                char_span=(10, 20),
                rule_id="meta.reference_number",
                method=FieldMethod.REGEX,
            )
        )
        doc = Document(file_name="x.pdf", file_path=Path("x.pdf"), file_hash="h", document_type=DocumentType.META_INVOICE, fields=fields)
        back = doc_repo.get(doc_repo.save(doc))
        field = back.field_of("reference_number")
        assert field.raw_snippet == "Số tham chiếu: ABCD1234EF"
        assert field.page_number == 1
        assert field.char_span == (10, 20)
        assert field.rule_id == "meta.reference_number"

    def test_truong_khong_doc_duoc_van_luu_duoc(self, doc_repo):
        fields = FieldSet()
        fields.set(ExtractedField.missing("reference_number", error="NOT_FOUND"))
        doc = Document(file_name="x.pdf", file_path=Path("x.pdf"), file_hash="h", document_type=DocumentType.META_INVOICE, fields=fields)
        back = doc_repo.get(doc_repo.save(doc))
        field = back.field_of("reference_number")
        assert field.value is None
        assert field.error == "NOT_FOUND"

    def test_luu_lai_ghi_de_khong_tao_ban_moi(self, doc_repo):
        doc = _doc()
        doc_id = doc_repo.save(doc)
        doc.notes = "đã sửa"
        doc_repo.save(doc)
        assert doc_repo.count() == 1
        assert doc_repo.get(doc_id).notes == "đã sửa"

    def test_luu_lai_thay_truong_cu_bang_truong_moi(self, doc_repo):
        """Lưu lại với field set khác phải XOÁ field cũ, không cộng dồn."""
        doc = _doc(reference_number="ABCD1234EF")
        doc_id = doc_repo.save(doc)
        doc.fields = FieldSet()
        doc.fields.set(ExtractedField(field_name="reference_number", value="ZZZZ9999YY"))
        doc_repo.save(doc)
        assert doc_repo.get(doc_id).value_of("reference_number") == "ZZZZ9999YY"

    def test_tim_theo_hash(self, doc_repo):
        doc_repo.save(_doc(name="a.pdf"))
        found = doc_repo.find_by_hash("hash-a.pdf")
        assert len(found) == 1
        assert found[0].file_name == "a.pdf"

    def test_nguon_text_duoc_giu(self, doc_repo):
        doc = _doc()
        doc.text_source = TextSource.OCR
        back = doc_repo.get(doc_repo.save(doc))
        assert back.text_source is TextSource.OCR

    def test_khong_ton_tai_tra_none(self, doc_repo):
        assert doc_repo.get(9999) is None


class TestDossierRepositoryLuuVaDocLai:
    def _save_three_docs(self, doc_repo):
        return [doc_repo.save(_doc(name=f"{i}.pdf")) for i in range(3)]

    def test_luu_va_doc_lai_du_lieu_co_ban(self, doc_repo, dossier_repo):
        meta_id, debit_id, vat_id = self._save_three_docs(doc_repo)
        dossier = Dossier(
            dossier_code="HS000001", reference="ABCD1234EF",
            meta_document_id=meta_id, debit_document_id=debit_id, vat_document_id=vat_id,
            meta_count=1, debit_count=1, vat_count=1,
            status=DossierStatus.VALID, extra_documents=(meta_id, debit_id, vat_id),
        )
        dossier_id = dossier_repo.save(dossier)
        back = dossier_repo.get(dossier_id)
        assert back.dossier_code == "HS000001"
        assert back.status is DossierStatus.VALID
        assert back.meta_document_id == meta_id

    def test_giu_nguyen_issues(self, doc_repo, dossier_repo):
        meta_id = doc_repo.save(_doc())
        dossier = Dossier(dossier_code="HS000001", reference="ABCD1234EF", meta_document_id=meta_id, meta_count=1)
        dossier.issues.append(
            DossierIssue(code="MISSING_DEBIT", severity=Severity.BLOCKING, description="thiếu debit note")
        )
        back = dossier_repo.get(dossier_repo.save(dossier))
        assert len(back.issues) == 1
        assert back.issues[0].code == "MISSING_DEBIT"
        assert back.issues[0].severity is Severity.BLOCKING

    def test_luu_lai_thay_the_issues_cu(self, doc_repo, dossier_repo):
        meta_id = doc_repo.save(_doc())
        dossier = Dossier(dossier_code="HS000001", reference="ABCD1234EF", meta_document_id=meta_id, meta_count=1)
        dossier.issues.append(DossierIssue(code="MISSING_DEBIT", severity=Severity.BLOCKING, description="x"))
        dossier_id = dossier_repo.save(dossier)

        dossier.issues = [DossierIssue(code="MISSING_VAT", severity=Severity.BLOCKING, description="y")]
        dossier_repo.save(dossier)

        back = dossier_repo.get(dossier_id)
        assert [i.code for i in back.issues] == ["MISSING_VAT"]

    def test_document_id_khong_ton_tai_bi_chan_boi_foreign_key(self, dossier_repo):
        dossier = Dossier(dossier_code="HS000001", reference="ABCD1234EF", meta_document_id=99999, meta_count=1)
        with pytest.raises(Exception):
            dossier_repo.save(dossier)

    def test_liet_ke_theo_trang_thai(self, doc_repo, dossier_repo):
        meta_id = doc_repo.save(_doc())
        d1 = Dossier(dossier_code="HS000001", reference="A", meta_document_id=meta_id, meta_count=1, status=DossierStatus.VALID)
        d2 = Dossier(dossier_code="HS000002", reference="B", meta_document_id=meta_id, meta_count=1, status=DossierStatus.MISSING_VAT)
        dossier_repo.save(d1)
        dossier_repo.save(d2)
        valid = dossier_repo.list_by_status(DossierStatus.VALID)
        assert len(valid) == 1
        assert valid[0].dossier_code == "HS000001"

    def test_vai_tro_chung_tu_trong_dossier_documents(self, doc_repo, dossier_repo):
        meta_id, debit_id, vat_id = self._save_three_docs(doc_repo)
        dossier = Dossier(
            dossier_code="HS000001", reference="ABCD1234EF",
            meta_document_id=meta_id, debit_document_id=debit_id, vat_document_id=vat_id,
            meta_count=1, debit_count=1, vat_count=1,
            extra_documents=(meta_id, debit_id, vat_id),
        )
        dossier_id = dossier_repo.save(dossier)
        roles = dict(dossier_repo.document_ids_of(dossier_id))
        assert roles[meta_id] == "META"
        assert roles[debit_id] == "DEBIT"
        assert roles[vat_id] == "VAT"


class TestSettingsRepository:
    def test_ghi_va_doc(self, db):
        repo = SettingsRepository(db)
        repo.set("input_folder", "C:/KETOAN/ALL_DATA")
        assert repo.get("input_folder") == "C:/KETOAN/ALL_DATA"

    def test_ghi_de_gia_tri_cu(self, db):
        repo = SettingsRepository(db)
        repo.set("k", "v1")
        repo.set("k", "v2")
        assert repo.get("k") == "v2"

    def test_khong_ton_tai_tra_mac_dinh(self, db):
        repo = SettingsRepository(db)
        assert repo.get("khong_co", default="mac_dinh") == "mac_dinh"

    def test_xoa(self, db):
        repo = SettingsRepository(db)
        repo.set("k", "v")
        repo.delete("k")
        assert repo.get("k") is None

    def test_lay_tat_ca(self, db):
        repo = SettingsRepository(db)
        repo.set("a", "1")
        repo.set("b", "2")
        assert repo.all() == {"a": "1", "b": "2"}


class TestVongDoiKetNoi:
    def test_dong_ket_noi_khong_loi(self):
        db = Database(":memory:")
        db.close()

    def test_context_manager_tu_dong_dong(self):
        with Database(":memory:") as db:
            assert db.connection is not None
