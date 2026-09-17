"""Test phát hiện file trùng bằng SHA256."""

from __future__ import annotations

from pathlib import Path

from app.core.duplicate_detector import DuplicateDetector, compute_sha256


class TestComputeSha256:
    def test_cung_noi_dung_cung_hash(self, tmp_path: Path):
        a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
        a.write_bytes(b"noi dung giong nhau")
        b.write_bytes(b"noi dung giong nhau")
        assert compute_sha256(a) == compute_sha256(b)

    def test_khac_noi_dung_khac_hash(self, tmp_path: Path):
        a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
        a.write_bytes(b"noi dung mot")
        b.write_bytes(b"noi dung hai")
        assert compute_sha256(a) != compute_sha256(b)

    def test_do_dai_hash(self, tmp_path: Path):
        f = tmp_path / "a.pdf"
        f.write_bytes(b"x")
        assert len(compute_sha256(f)) == 64


class TestDuplicateDetector:
    def test_file_dau_tien_khong_phai_ban_trung(self):
        detector = DuplicateDetector()
        assert detector.register(Path("a.pdf"), "hash1") is None

    def test_file_thu_hai_cung_hash_tra_ve_ban_goc(self):
        detector = DuplicateDetector()
        detector.register(Path("a.pdf"), "hash1")
        original = detector.register(Path("b.pdf"), "hash1")
        assert original == Path("a.pdf")

    def test_ten_file_khac_nhau_khong_anh_huong(self):
        """Tên file không bao giờ là khoá — chỉ nội dung mới quyết định."""
        detector = DuplicateDetector()
        detector.register(Path("invoice.pdf"), "hash1")
        assert detector.register(Path("bản_sao_(1).pdf"), "hash1") == Path("invoice.pdf")

    def test_nhom_trung_ghi_nhan_day_du(self):
        detector = DuplicateDetector()
        detector.register(Path("a.pdf"), "h")
        detector.register(Path("b.pdf"), "h")
        detector.register(Path("c.pdf"), "h")
        group = detector.groups[0]
        assert group.count == 3
        assert group.original == Path("a.pdf")
        assert len(group.duplicates) == 2

    def test_dem_so_file_duy_nhat(self):
        detector = DuplicateDetector()
        detector.register(Path("a.pdf"), "h1")
        detector.register(Path("b.pdf"), "h1")
        detector.register(Path("c.pdf"), "h2")
        assert detector.unique_count == 2
