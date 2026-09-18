"""Test tách vật lý file PDF gộp nhiều Giấy báo nợ VietinBank."""

from __future__ import annotations

import pymupdf
import pytest

from app.core.debit_advice_splitter import DebitAdviceSplitter
from app.core.pdf_reader import PDFReader
from pdf_synth import FONT, write_pdf

pytestmark = pytest.mark.skipif(FONT is None, reason="Không tìm thấy font DejaVu Sans trong môi trường này")

_MAIN = [
    "GIẤY BÁO NỢ / Debit Advice",
    "Số giao dịch / Transaction number: 3185",
    "Ngày thực hiện / Transaction date: 31-08-2026 15:38:12",
    "Số tiền bằng số / Amount in figures: 13,066,610 VND",
    "Nội dung / Remarks: GD thanh toan tai FACEBK *YYYY222222",
]
_FEE = [
    "GIẤY BÁO NỢ / Debit Advice",
    "Số giao dịch / Transaction number: 3186",
    "Ngày thực hiện / Transaction date: 31-08-2026 15:38:12",
    "Số tiền bằng số / Amount in figures: 114,986 VND",
    "Nội dung / Remarks: Phi GD thanh toan tai FACEBK *YYYY222222",
]
_UNRELATED_COVER_PAGE = [
    "NGAN HANG TMCP CONG THUONG VIET NAM",
    "Bang ke giao dich thang 08/2026",
]


@pytest.fixture
def bundle_pdf(tmp_path):
    path = tmp_path / "ALL_DATA" / "giay-bao-No.pdf"
    path.parent.mkdir(parents=True)
    write_pdf(path, [_UNRELATED_COVER_PAGE, _MAIN, _FEE])
    return path


class TestChiTachTrangDatCauTruc:
    def test_bia_khong_co_cau_truc_khong_bi_tach(self, classifier_config, bundle_pdf, tmp_path):
        splitter = DebitAdviceSplitter(classifier_config)
        output_dir = tmp_path / "ALL_DATA" / "_DEBIT_SPLIT"

        result = splitter.split_folder(bundle_pdf.parent, output_dir)

        assert len(result.split_pages) == 2  # chỉ 2 trang Debit Advice thật, KHÔNG có trang bìa
        assert result.bundle_files == [bundle_pdf]

    def test_file_goc_giu_nguyen_ba_trang(self, classifier_config, bundle_pdf, tmp_path):
        splitter = DebitAdviceSplitter(classifier_config)
        output_dir = tmp_path / "ALL_DATA" / "_DEBIT_SPLIT"

        splitter.split_folder(bundle_pdf.parent, output_dir)

        doc = pymupdf.open(bundle_pdf)
        try:
            assert doc.page_count == 3
        finally:
            doc.close()


class TestFileTachLaVatLyMotTrang:
    def test_moi_file_tach_chi_co_mot_trang_va_doc_lai_dung_noi_dung(
        self, classifier_config, bundle_pdf, tmp_path
    ):
        splitter = DebitAdviceSplitter(classifier_config)
        output_dir = tmp_path / "ALL_DATA" / "_DEBIT_SPLIT"

        result = splitter.split_folder(bundle_pdf.parent, output_dir)

        reader = PDFReader()
        for split_page in result.split_pages:
            assert split_page.output_path.is_file()
            content = reader.read(split_page.output_path)
            assert content.page_count == 1
            assert "GIẤY BÁO NỢ" in content.text or "Debit Advice" in content.text

    def test_ten_file_lay_theo_so_giao_dich(self, classifier_config, bundle_pdf, tmp_path):
        splitter = DebitAdviceSplitter(classifier_config)
        output_dir = tmp_path / "ALL_DATA" / "_DEBIT_SPLIT"

        result = splitter.split_folder(bundle_pdf.parent, output_dir)

        names = sorted(p.output_path.name for p in result.split_pages)
        assert names == ["DEBIT_ADVICE_3185.pdf", "DEBIT_ADVICE_3186.pdf"]


class TestKhongTuTachLaiDauRa:
    def test_chay_lai_lan_hai_khong_tach_them_tu_thu_muc_dich(
        self, classifier_config, bundle_pdf, tmp_path
    ):
        splitter = DebitAdviceSplitter(classifier_config)
        output_dir = tmp_path / "ALL_DATA" / "_DEBIT_SPLIT"

        first = splitter.split_folder(bundle_pdf.parent, output_dir)
        # Lần 2: cùng thư mục nguồn (đã có output_dir con) — không được quét
        # lại chính các file vừa tách ra làm "bundle" mới.
        second = splitter.split_folder(bundle_pdf.parent, output_dir)

        assert len(first.split_pages) == 2
        assert second.scanned_files == 1  # chỉ còn giay-bao-No.pdf, output_dir bị loại khỏi vùng quét
        assert len(second.bundle_files) == 1


class TestKetHopVoiScanServiceQuaExcludePaths:
    def test_scan_loai_file_goc_nhung_van_quet_duoc_file_da_tach(
        self, db, classifier_config, extraction_config, app_settings, bundle_pdf, tmp_path
    ):
        from app.database.database import Database
        from app.services.scan_service import ScanService

        splitter = DebitAdviceSplitter(classifier_config)
        output_dir = tmp_path / "ALL_DATA" / "_DEBIT_SPLIT"
        split_result = splitter.split_folder(bundle_pdf.parent, output_dir)

        scanner = ScanService(db, classifier_config, extraction_config, app_settings)
        scan_result = scanner.scan_folder(
            bundle_pdf.parent, run_id=None, exclude_paths=split_result.excluded_source_paths
        )

        from app.models.enums import DocumentType

        types = {d.document_type for d in scan_result.documents}
        assert types == {DocumentType.VIETINBANK_DEBIT_ADVICE}
        assert len(scan_result.documents) == 2  # đúng 2 trang tách ra, KHÔNG có bản "ảo" từ file gốc


@pytest.fixture
def db():
    from app.database.database import Database

    with Database(":memory:") as database:
        yield database
