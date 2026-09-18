"""Test lấy PDF từ ZIP — app/core/zip_extractor.py."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.core.zip_extractor import extract_pdfs_from_zips


def _make_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


@pytest.fixture
def source_dir(tmp_path):
    d = tmp_path / "data_tool_read_pdf"
    d.mkdir()
    return d


class TestChiLayPdfBoQuaKhac:
    def test_zip_co_pdf_va_xml_chi_lay_pdf(self, source_dir):
        _make_zip(
            source_dir / "invoice (1).zip",
            {"invoice.pdf": b"%PDF-1.4 fake pdf", "invoice.xml": b"<xml/>"},
        )
        dest = source_dir / "ALL_DATA"

        result = extract_pdfs_from_zips(source_dir, dest)

        assert result.zip_scanned == 1
        assert result.pdf_extracted == 1
        assert result.non_pdf_skipped == 1
        assert result.zip_errors == 0
        assert (dest / "invoice.pdf").read_bytes() == b"%PDF-1.4 fake pdf"
        assert not (dest / "invoice.xml").exists()


class TestPdfTrongSubfolderDuocLamPhang:
    def test_pdf_trong_folder_con_khong_giu_cay_thu_muc(self, source_dir):
        _make_zip(source_dir / "a.zip", {"folder1/folder2/invoice.pdf": b"noi dung pdf"})
        dest = source_dir / "ALL_DATA"

        result = extract_pdfs_from_zips(source_dir, dest)

        assert result.pdf_extracted == 1
        assert (dest / "invoice.pdf").is_file()
        assert not (dest / "folder1").exists()

    def test_ten_thanh_vien_co_path_traversal_khong_thoat_ra_ngoai(self, source_dir):
        """member.filename kiểu '../../evil.pdf' -> chỉ lấy basename, không
        bao giờ ghi ra ngoài thư mục đích (chống ZIP path traversal)."""
        _make_zip(source_dir / "evil.zip", {"../../evil.pdf": b"noi dung"})
        dest = source_dir / "ALL_DATA"

        result = extract_pdfs_from_zips(source_dir, dest)

        assert result.pdf_extracted == 1
        assert (dest / "evil.pdf").is_file()
        assert not (source_dir.parent / "evil.pdf").exists()
        assert not (source_dir / "evil.pdf").exists()  # không lọt ra ngoài ALL_DATA


class TestZipKhongCoPdf:
    def test_zip_khong_co_pdf_khong_tang_pdf_extracted(self, source_dir):
        _make_zip(source_dir / "no_pdf.zip", {"note.txt": b"khong lien quan"})
        dest = source_dir / "ALL_DATA"

        result = extract_pdfs_from_zips(source_dir, dest)

        assert result.zip_scanned == 1
        assert result.pdf_extracted == 0
        assert result.zip_errors == 0
        assert result.no_pdf_zip_names == ["no_pdf.zip"]


class TestZipLoiKhongLamCrashCaLo:
    def test_zip_corrupt_bi_dem_loi_va_khong_dung_lo(self, source_dir):
        (source_dir / "corrupt.zip").write_bytes(b"khong phai zip hop le")
        _make_zip(source_dir / "good.zip", {"invoice.pdf": b"pdf that"})
        dest = source_dir / "ALL_DATA"

        result = extract_pdfs_from_zips(source_dir, dest)

        assert result.zip_scanned == 2
        assert result.zip_errors == 1
        assert result.pdf_extracted == 1  # good.zip vẫn được xử lý
        assert len(result.error_messages) == 1
        assert "corrupt.zip" in result.error_messages[0]

    def test_zip_co_mat_khau_bi_dem_loi(self, source_dir, monkeypatch):
        """zipfile.ZipFile.read() ném RuntimeError khi member có mật khẩu mà
        không cung cấp mật khẩu — mô phỏng bằng monkeypatch vì stdlib
        zipfile không tạo được ZIP mã hoá khi ghi, chỉ đọc được ZIP mã hoá
        có sẵn."""
        _make_zip(source_dir / "locked.zip", {"invoice.pdf": b"noi dung bi khoa"})
        dest = source_dir / "ALL_DATA"

        def _fake_read(self, name, pwd=None):
            raise RuntimeError(f"File '{name}' is encrypted, password required for extraction")

        monkeypatch.setattr(zipfile.ZipFile, "read", _fake_read)

        result = extract_pdfs_from_zips(source_dir, dest)

        assert result.zip_scanned == 1
        assert result.zip_errors == 1
        assert result.pdf_extracted == 0
        assert "locked.zip" in result.error_messages[0]


class TestChayLaiKhongTaoTrung:
    def test_chay_lai_cung_zip_khong_sinh_file_hau_to(self, source_dir):
        _make_zip(source_dir / "a.zip", {"invoice.pdf": b"noi dung goc"})
        dest = source_dir / "ALL_DATA"

        first = extract_pdfs_from_zips(source_dir, dest)
        second = extract_pdfs_from_zips(source_dir, dest)
        third = extract_pdfs_from_zips(source_dir, dest)

        assert first.pdf_extracted == 1
        assert second.pdf_extracted == 1
        assert third.pdf_extracted == 1
        all_pdfs = sorted(p.name for p in dest.glob("*.pdf"))
        assert all_pdfs == ["invoice.pdf"]  # KHÔNG có invoice_2.pdf, invoice_3.pdf

    def test_hai_zip_khac_nhau_cung_ten_pdf_nhung_khac_noi_dung_duoc_danh_so(self, source_dir):
        _make_zip(source_dir / "a.zip", {"invoice.pdf": b"noi dung A"})
        _make_zip(source_dir / "b.zip", {"invoice.pdf": b"noi dung B khac han"})
        dest = source_dir / "ALL_DATA"

        result = extract_pdfs_from_zips(source_dir, dest)

        assert result.pdf_extracted == 2
        names = sorted(p.name for p in dest.glob("*.pdf"))
        assert names == ["invoice.pdf", "invoice_2.pdf"]

    def test_chay_lai_sau_khi_da_co_ban_khac_noi_dung_van_nhan_dung_ban_cu(self, source_dir):
        _make_zip(source_dir / "a.zip", {"invoice.pdf": b"noi dung A"})
        _make_zip(source_dir / "b.zip", {"invoice.pdf": b"noi dung B khac han"})
        dest = source_dir / "ALL_DATA"

        extract_pdfs_from_zips(source_dir, dest)
        result = extract_pdfs_from_zips(source_dir, dest)  # chạy lại lần 2

        assert result.pdf_extracted == 2  # nhận lại đúng 2 bản đã có, không thêm bản mới
        names = sorted(p.name for p in dest.glob("*.pdf"))
        assert names == ["invoice.pdf", "invoice_2.pdf"]


class TestChiQuetTrucTiepKhongDeQuy:
    def test_khong_quet_zip_trong_thu_muc_con(self, source_dir):
        sub = source_dir / "data_1"
        sub.mkdir()
        _make_zip(sub / "nested.zip", {"invoice.pdf": b"khong duoc quet"})
        dest = source_dir / "ALL_DATA"

        result = extract_pdfs_from_zips(source_dir, dest)

        assert result.zip_scanned == 0
        assert result.pdf_extracted == 0


class TestTaoThuMucDich:
    def test_tu_tao_all_data_neu_chua_co(self, source_dir):
        dest = source_dir / "ALL_DATA"
        assert not dest.exists()

        extract_pdfs_from_zips(source_dir, dest)

        assert dest.is_dir()


class TestProgressCallback:
    def test_goi_progress_dung_so_lan(self, source_dir):
        _make_zip(source_dir / "a.zip", {"invoice.pdf": b"1"})
        _make_zip(source_dir / "b.zip", {"invoice2.pdf": b"2"})
        dest = source_dir / "ALL_DATA"

        calls = []
        extract_pdfs_from_zips(source_dir, dest, on_progress=calls.append)

        assert len(calls) == 2
        assert calls[0].total == 2
        assert calls[1].current == 2


class TestHuyHopTac:
    def test_should_cancel_dung_sau_zip_dang_xu_ly(self, source_dir):
        _make_zip(source_dir / "a.zip", {"invoice.pdf": b"1"})
        _make_zip(source_dir / "b.zip", {"invoice2.pdf": b"2"})
        _make_zip(source_dir / "c.zip", {"invoice3.pdf": b"3"})
        dest = source_dir / "ALL_DATA"

        calls = []
        result = extract_pdfs_from_zips(
            source_dir, dest, on_progress=calls.append, should_cancel=lambda: len(calls) >= 1
        )

        assert result.zip_scanned == 1
