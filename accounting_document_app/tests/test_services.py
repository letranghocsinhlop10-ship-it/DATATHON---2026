"""Test tầng service — điều phối pipeline scan/match trên fixture đã che số."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.database.database import Database
from app.database.document_repository import DocumentRepository
from app.database.processing_run_repository import ProcessingRunRepository
from app.services.match_service import MatchService
from app.services.scan_service import ScanProgress, ScanService
from helpers import make_content
from vat_layout import build_vat_page


@pytest.fixture
def db():
    with Database(":memory:") as database:
        yield database


@pytest.fixture
def scanner(db, classifier_config, extraction_config, app_settings):
    return ScanService(db, classifier_config, extraction_config, app_settings)


@pytest.fixture
def matcher(db, app_settings):
    return MatchService(db, app_settings)


class TestScanServiceTrenThuMucRong:
    def test_thu_muc_khong_co_pdf(self, scanner, tmp_path):
        result = scanner.scan_folder(tmp_path, run_id=None)
        assert result.total_files == 0
        assert result.error_files == 0

    def test_bao_tien_do_dung_so_luong(self, scanner, tmp_path):
        calls: list[ScanProgress] = []
        scanner.scan_folder(tmp_path, run_id=None, on_progress=calls.append)
        assert calls == []  # không có file nào để báo tiến độ


class TestScanServiceGhiVaoDb:
    def test_luu_document_co_run_id(self, db, scanner, tmp_path):
        """Không có PDF thật -> dùng thư mục rỗng, chỉ kiểm tra cơ chế run_id
        không lỗi khi danh sách rỗng; việc lưu thật được test qua fixture PDF
        ở test_real_samples.py (ACCOUNTING_SAMPLE_DIR)."""
        runs = ProcessingRunRepository(db)
        run_id = runs.start(str(tmp_path))
        result = scanner.scan_folder(tmp_path, run_id=run_id)
        assert result.run_id == run_id
        runs.finish(run_id, total_files=result.total_files)
        assert runs.get(run_id)["status"] == "COMPLETED"


class TestHuyHopTac:
    def test_should_cancel_dung_giua_chung(self, scanner, tmp_path):
        # Tạo 2 file PDF giả (nội dung rác) để có gì đó lặp qua; PDFReader sẽ
        # lỗi PDF_OPEN_FAILED cho từng file nhưng vòng lặp vẫn phải dừng đúng
        # lúc should_cancel() trả True.
        (tmp_path / "a.pdf").write_bytes(b"khong phai pdf that")
        (tmp_path / "b.pdf").write_bytes(b"khong phai pdf that")
        (tmp_path / "c.pdf").write_bytes(b"khong phai pdf that")

        calls = []
        result = scanner.scan_folder(
            tmp_path,
            run_id=None,
            on_progress=calls.append,
            should_cancel=lambda: len(calls) >= 1,
        )
        assert len(calls) == 1  # dừng ngay sau file đầu tiên

    def test_file_loi_khong_lam_dung_ca_lo(self, scanner, tmp_path):
        (tmp_path / "a.pdf").write_bytes(b"khong phai pdf that")
        (tmp_path / "b.pdf").write_bytes(b"khong phai pdf that")
        result = scanner.scan_folder(tmp_path, run_id=None)
        assert result.error_files == 2
        assert result.total_files == 0


class TestMatchServiceTuChungTuCoSan:
    def test_ghep_va_luu_dossier(
        self, db, matcher, classifier_config, extraction_config, app_settings, registry
    ):
        from app.core.document_classifier import DocumentClassifier
        from app.database.document_repository import DocumentRepository
        from app.database.processing_run_repository import ProcessingRunRepository
        from app.models.document import Document
        from helpers import make_context, read_fixture

        run_id = ProcessingRunRepository(db).start("tests/fixtures")

        # Dựng 3 Document từ fixture text (không cần PDF thật), lưu qua
        # DocumentRepository trước để có document_id thật.
        docs_repo = DocumentRepository(db)
        classifier = DocumentClassifier(classifier_config)

        built = []
        for page, name in [
            (read_fixture("vpbank_debit_note.txt"), "debit.pdf"),
            (build_vat_page(), "vat.pdf"),
            (read_fixture("meta_invoice.txt") + read_fixture("meta_invoice_page2.txt"), "meta.pdf"),
        ]:
            content = make_content([page], name=name)
            document_type = classifier.classify(content.flat).document_type
            extractor = registry.get(document_type)
            fields = extractor.extract(make_context(content, document_type, extraction_config, app_settings))
            doc = Document(
                file_name=name, file_path=Path(name), file_hash=f"hash-{name}",
                document_type=document_type, fields=fields,
            )
            docs_repo.save(doc, run_id=run_id)
            built.append(doc)

        result = matcher.match_documents(built, run_id=run_id)
        assert len(result.dossiers) == 1
        assert result.dossiers[0].status.value == "VALID"
        assert result.dossiers[0].dossier_id is not None  # đã lưu DB
