"""Test tích hợp toàn bộ bước "Chuẩn bị dữ liệu" (§L bước 1-6).

Dựng một thư mục nguồn lộn xộn thật (ZIP + PDF rời + bundle nhiều trang) và
kiểm tra PrepareDataService điều phối đúng cả 6 bước, không sinh chứng từ
trùng, không quét lại chính kết quả tiền xử lý của mình.
"""

from __future__ import annotations

import zipfile

import pytest

from app.database.database import Database
from app.models.enums import DocumentType
from app.services.prepare_data_service import PrepareDataService
from pdf_synth import FONT, write_pdf

pytestmark = pytest.mark.skipif(FONT is None, reason="Không tìm thấy font DejaVu Sans trong môi trường này")

_DEBIT_NOTE_ZIP = [
    "PHIẾU GIAO DỊCH GHI NỢ/DEBIT NOTE",
    "Ngày/Transaction Date: 01/08/2026",
    "Tên Khách hàng/Customer Name: CONG TY TEST",
    "Mã giao dịch/Transaction code: FT99999999",
    "Loại tiền/Currency: VND",
    "Số tiền/Amount: 100,000 VND",
    "Diễn giải/Details: GD thanh toan tai FACEBK *ZIPREF001 DUBLIN IE",
]

_STATEMENT_PAGE = [
    "SAO KE TAI KHOAN / STATEMENT OF ACCOUNT",
    "Ngay giao dich Phat sinh No Phat sinh Co So du",
    "FT88888888 05/08/2026 09:00:00 GD thanh toan tai FACEBK *STMTREF002 DUBLIN IE 500,000 900,000",
]

_BUNDLE_MAIN = [
    "GIẤY BÁO NỢ / Debit Advice",
    "Số giao dịch / Transaction number: 7002",
    "Ngày thực hiện / Transaction date: 10-08-2026 08:00:00",
    "Số tiền bằng số / Amount in figures: 2,000,000 VND",
    "Nội dung / Remarks: GD thanh toan tai FACEBK *BUNDLEREF003",
]
_BUNDLE_FEE = [
    "GIẤY BÁO NỢ / Debit Advice",
    "Số giao dịch / Transaction number: 7001",
    "Ngày thực hiện / Transaction date: 10-08-2026 08:00:00",
    "Số tiền bằng số / Amount in figures: 15,000 VND",
    "Nội dung / Remarks: Phi GD thanh toan tai FACEBK *BUNDLEREF003",
]
_BUNDLE_COVER = ["NGAN HANG TMCP CONG THUONG VIET NAM", "Bang ke thang 08/2026"]


@pytest.fixture
def db():
    with Database(":memory:") as database:
        yield database


@pytest.fixture
def source_dir(tmp_path):
    d = tmp_path / "data_tool_read_pdf"
    d.mkdir()

    zip_pdf_dir = tmp_path / "_zip_src"
    zip_pdf_dir.mkdir()
    write_pdf(zip_pdf_dir / "note.pdf", [_DEBIT_NOTE_ZIP])
    with zipfile.ZipFile(d / "invoice (1).zip", "w") as zf:
        zf.write(zip_pdf_dir / "note.pdf", arcname="note.pdf")

    write_pdf(d / "sao_ke.pdf", [_STATEMENT_PAGE])
    write_pdf(d / "giay-bao-No.pdf", [_BUNDLE_COVER, _BUNDLE_MAIN, _BUNDLE_FEE])
    return d


class TestChuanBiDuLieuDayDu:
    def test_zip_duoc_giai_nen_vao_all_data(
        self, db, classifier_config, extraction_config, app_settings, source_dir
    ):
        service = PrepareDataService(db, classifier_config, extraction_config, app_settings)
        result = service.prepare(source_dir, run_id=None)

        assert result.all_data_folder == source_dir / "ALL_DATA"
        assert (result.all_data_folder / "note.pdf").is_file()
        assert result.zip_result.pdf_extracted == 1

    def test_bundle_duoc_tach_dung_hai_trang(
        self, db, classifier_config, extraction_config, app_settings, source_dir
    ):
        service = PrepareDataService(db, classifier_config, extraction_config, app_settings)
        result = service.prepare(source_dir, run_id=None)

        assert len(result.split_result.split_pages) == 2
        assert len(result.split_result.bundle_files) == 1

    def test_sao_ke_duoc_nhan_dien_va_parse(
        self, db, classifier_config, extraction_config, app_settings, source_dir
    ):
        service = PrepareDataService(db, classifier_config, extraction_config, app_settings)
        result = service.prepare(source_dir, run_id=None)

        assert len(result.statement_files) == 1
        assert len(result.bank_transactions) == 1
        assert result.bank_transactions[0].facebook_reference == "STMTREF002"

    def test_scan_khong_bi_trung_va_khong_quet_lai_bundle_goc(
        self, db, classifier_config, extraction_config, app_settings, source_dir
    ):
        service = PrepareDataService(db, classifier_config, extraction_config, app_settings)
        result = service.prepare(source_dir, run_id=None)

        assert result.scan_result is not None
        types = [d.document_type for d in result.scan_result.documents]
        # 1 debit note (từ ZIP) + 2 trang Giấy báo nợ đã tách — KHÔNG có bản
        # "ảo" của giay-bao-No.pdf gốc, KHÔNG có sao_ke.pdf (được parse riêng).
        assert types.count(DocumentType.VPBANK_DEBIT_NOTE) == 1
        assert types.count(DocumentType.VIETINBANK_DEBIT_ADVICE) == 2
        assert types.count(DocumentType.BANK_STATEMENT) == 0
        assert len(result.scan_result.documents) == 3

    def test_ket_qua_scan_da_luu_db(
        self, db, classifier_config, extraction_config, app_settings, source_dir
    ):
        from app.database.processing_run_repository import ProcessingRunRepository

        run_id = ProcessingRunRepository(db).start(str(source_dir))
        service = PrepareDataService(db, classifier_config, extraction_config, app_settings)
        result = service.prepare(source_dir, run_id=run_id)

        for doc in result.scan_result.documents:
            assert doc.document_id is not None
