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


class TestScanServicePhatHienTrung:
    def test_file_trung_duoc_tro_duplicate_of_id_dung_ban_goc(self, db, scanner, tmp_path):
        """Hai file PDF THẬT giống hệt byte-for-byte -> file thứ 2 phải mang
        processing_status=DUPLICATE_FILE và duplicate_of_id trỏ đúng document
        của file gốc (không chỉ đánh dấu trạng thái mà bỏ trống liên kết)."""
        import pymupdf

        pdf_bytes_path = tmp_path / "_src.pdf"
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "PHIẾU GIAO DỊCH GHI NỢ/DEBIT NOTE\nMã giao dịch/Transaction code: FT1")
        doc.save(pdf_bytes_path)
        doc.close()
        raw = pdf_bytes_path.read_bytes()

        (tmp_path / "goc.pdf").write_bytes(raw)
        (tmp_path / "ban_sao.pdf").write_bytes(raw)  # byte-for-byte giống hệt
        pdf_bytes_path.unlink()

        runs = __import__(
            "app.database.processing_run_repository", fromlist=["ProcessingRunRepository"]
        ).ProcessingRunRepository(db)
        run_id = runs.start(str(tmp_path))

        result = scanner.scan_folder(tmp_path, run_id=run_id)
        assert result.total_files == 2
        assert result.duplicate_files == 1

        # iter_pdf_files() duyệt theo thứ tự alphabet của tên file, không phải
        # thứ tự tạo file -> không giả định file nào được coi là "bản gốc".
        by_status = {d.processing_status.value: d for d in result.documents}
        original = by_status["OK"]
        copy = by_status["DUPLICATE_FILE"]

        assert original.duplicate_of_id is None
        assert copy.duplicate_of_id == original.document_id


class TestExportService:
    def test_xuat_excel_tu_run_da_ghep(
        self, db, matcher, classifier_config, extraction_config, app_settings, registry, tmp_path
    ):
        import openpyxl

        from app.config_loader import load_accounting_config, load_misa_mapping_config
        from app.core.document_classifier import DocumentClassifier
        from app.database.processing_run_repository import ProcessingRunRepository
        from app.models.document import Document
        from app.services.export_service import ExportService
        from helpers import make_context, read_fixture

        run_id = ProcessingRunRepository(db).start("tests/fixtures")
        docs_repo = DocumentRepository(db)
        classifier = DocumentClassifier(classifier_config)

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

        matcher.match_run(run_id)

        misa_config = load_misa_mapping_config(load_accounting_config())
        export_service = ExportService(db, misa_config)
        out_path = export_service.export_run(run_id, tmp_path / "result.xlsx", voucher_start=1)

        assert out_path.is_file()
        wb = openpyxl.load_workbook(out_path)
        assert set(wb.sheetnames) == {"HO_SO", "CHUNG_TU", misa_config.sheet_name, "CHECK_ERROR"}
        ws = wb["HO_SO"]
        assert ws.max_row == 2  # header + 1 dossier VALID


class TestOrganizeService:
    def test_sap_xep_va_cap_nhat_folder_path(
        self, db, matcher, classifier_config, extraction_config, app_settings, registry, tmp_path
    ):
        from app.core.document_classifier import DocumentClassifier
        from app.database.dossier_repository import DossierRepository
        from app.database.processing_run_repository import ProcessingRunRepository
        from app.models.document import Document
        from app.services.organize_service import OrganizeService
        from helpers import make_context, read_fixture

        run_id = ProcessingRunRepository(db).start("tests/fixtures")
        docs_repo = DocumentRepository(db)
        classifier = DocumentClassifier(classifier_config)
        src_dir = tmp_path / "src"
        src_dir.mkdir()

        for page, name in [
            (read_fixture("vpbank_debit_note.txt"), "debit.pdf"),
            (build_vat_page(), "vat.pdf"),
            (read_fixture("meta_invoice.txt") + read_fixture("meta_invoice_page2.txt"), "meta.pdf"),
        ]:
            content = make_content([page], name=name)
            document_type = classifier.classify(content.flat).document_type
            extractor = registry.get(document_type)
            fields = extractor.extract(make_context(content, document_type, extraction_config, app_settings))
            real_path = src_dir / name
            real_path.write_bytes(f"gia {name}".encode())
            doc = Document(
                file_name=name, file_path=real_path, file_hash=f"hash-{name}",
                document_type=document_type, fields=fields,
            )
            docs_repo.save(doc, run_id=run_id)

        matcher.match_run(run_id)

        service = OrganizeService(db)
        out_root = tmp_path / "OUTPUT"
        result = service.organize_run(run_id, out_root)

        assert result.copied_files == 3
        folder = out_root / "HS000001_ABCD1234EF"
        assert (folder / "01_META_INVOICE.pdf").is_file()

        # folder_path phải được LƯU LẠI vào DB, không chỉ tồn tại trong bộ nhớ.
        reloaded = DossierRepository(db).get(
            db.connection.execute("SELECT id FROM dossiers").fetchone()["id"]
        )
        assert reloaded.folder_path == str(folder)
