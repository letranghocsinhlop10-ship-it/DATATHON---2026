"""Test tách file PDF chứa nhiều chứng từ."""

from __future__ import annotations

from app.core.voucher_splitter import VoucherSplitter
from app.models.enums import DocumentType
from helpers import make_content, read_fixture
from vat_layout import build_vat_page

META_P1 = read_fixture("meta_invoice.txt")
META_P2 = read_fixture("meta_invoice_page2.txt")
DEBIT = read_fixture("vpbank_debit_note.txt")


def _split(classifier_config, pages):
    return VoucherSplitter(classifier_config).split(make_content(pages, name="gop.pdf"))


class TestFileChiCoMotChungTu:
    def test_mot_trang_mot_chung_tu(self, classifier_config):
        segments = _split(classifier_config, [DEBIT])
        assert len(segments) == 1
        assert segments[0].page_numbers == (1,)

    def test_hoa_don_hai_trang_KHONG_bi_cat_doi(self, classifier_config):
        """Trang 2 hoá đơn Meta chứa 'Meta Platforms Ireland' nhưng KHÔNG phải
        marker mở đầu — nếu chọn nhầm marker thì hoá đơn sẽ bị cắt đôi."""
        segments = _split(classifier_config, [META_P1, META_P2])
        assert len(segments) == 1
        assert segments[0].page_numbers == (1, 2)
        assert segments[0].marker_type is DocumentType.META_INVOICE


class TestFileGopNhieuChungTu:
    def test_ba_chung_tu_trong_mot_file(self, classifier_config):
        segments = _split(classifier_config, [DEBIT, build_vat_page().text, META_P1, META_P2])
        assert len(segments) == 3
        assert [s.page_numbers for s in segments] == [(1,), (2,), (3, 4)]

    def test_gan_dung_loai_theo_marker(self, classifier_config):
        segments = _split(classifier_config, [DEBIT, build_vat_page().text, META_P1, META_P2])
        assert [s.marker_type for s in segments] == [
            DocumentType.VPBANK_DEBIT_NOTE,
            DocumentType.VPBANK_VAT_INVOICE,
            DocumentType.META_INVOICE,
        ]

    def test_nam_debit_note_lien_tiep(self, classifier_config):
        segments = _split(classifier_config, [DEBIT] * 5)
        assert len(segments) == 5
        assert all(s.page_count == 1 for s in segments)

    def test_danh_so_thu_tu_lien_tuc(self, classifier_config):
        segments = _split(classifier_config, [DEBIT, DEBIT, DEBIT])
        assert [s.index for s in segments] == [0, 1, 2]


class TestAnToan:
    def test_khong_co_marker_thi_giu_nguyen_ca_file(self, classifier_config):
        """Không đoán chỗ cắt — giữ nguyên hành vi cũ."""
        segments = _split(classifier_config, ["nội dung lạ", "trang hai", "trang ba"])
        assert len(segments) == 1
        assert segments[0].page_numbers == (1, 2, 3)

    def test_trang_dau_khong_co_marker_thi_tach_rieng_va_gan_co(self, classifier_config):
        segments = _split(classifier_config, ["trang bìa không có gì", DEBIT])
        assert len(segments) == 2
        assert segments[0].page_numbers == (1,)
        assert "LEADING_PAGES_WITHOUT_MARKER" in segments[0].issues
        assert segments[1].marker_type is DocumentType.VPBANK_DEBIT_NOTE

    def test_file_rong_tra_danh_sach_rong(self, classifier_config):
        assert VoucherSplitter(classifier_config).split(make_content([])) == []

    def test_marker_cua_nhieu_loai_tren_mot_trang_thi_khong_gan_loai(
        self, classifier_config
    ):
        page = "PHIẾU GIAO DỊCH GHI NỢ và Ký hiệu (Serial): 1K26XXX trên cùng một trang"
        segments = _split(classifier_config, [page])
        assert len(segments) == 1
        assert segments[0].marker_type is None
        assert "MARKER_AMBIGUOUS" in segments[0].issues


class TestTachNoiDung:
    def test_moi_chung_tu_chi_thay_trang_cua_no(self, classifier_config):
        """Chống lấy nhầm dữ liệu: chứng từ sau không được thấy text chứng từ trước."""
        content = make_content([DEBIT, build_vat_page().text], name="gop.pdf")
        segments = VoucherSplitter(classifier_config).split(content)
        vat_content = segments[1].content(content)
        assert "PHIẾU GIAO DỊCH GHI NỢ" not in vat_content.text
        assert "Ký hiệu (Serial)" in vat_content.text

    def test_giu_nguyen_duong_dan_file_goc_de_truy_vet(self, classifier_config):
        content = make_content([DEBIT, DEBIT], name="gop.pdf")
        segments = VoucherSplitter(classifier_config).split(content)
        assert segments[1].content(content).path == content.path

    def test_so_trang_goc_duoc_giu_nguyen(self, classifier_config):
        content = make_content([DEBIT, DEBIT, DEBIT], name="gop.pdf")
        segments = VoucherSplitter(classifier_config).split(content)
        third = segments[2].content(content)
        assert third.pages[0].number == 3


class TestTrichXuatTrenFileGop:
    def test_moi_chung_tu_trich_xuat_doc_lap(
        self, classifier_config, extraction_config, app_settings, registry
    ):
        from app.core.document_classifier import DocumentClassifier
        from helpers import make_context

        content = make_content([DEBIT, build_vat_page(), META_P1, META_P2], name="gop.pdf")
        segments = VoucherSplitter(classifier_config).split(content)
        classifier = DocumentClassifier(classifier_config)

        keys = []
        for segment in segments:
            sub = segment.content(content)
            document_type = classifier.classify(sub.flat).document_type
            extractor = registry.get(document_type)
            fields = extractor.extract(
                make_context(sub, document_type, extraction_config, app_settings)
            )
            keys.append(
                fields.value("reference_number")
                if document_type is DocumentType.META_INVOICE
                else fields.value("meta_reference")
            )

        # Cả ba chứng từ đều ra cùng một khoá ghép.
        assert keys == ["ABCD1234EF"] * 3
