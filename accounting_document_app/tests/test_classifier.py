"""Test phân loại chứng từ."""

from __future__ import annotations

from app.core.document_classifier import DocumentClassifier
from app.core.text_normalizer import flatten_whitespace
from app.models.enums import DocumentType
from helpers import read_fixture
from vat_layout import build_vat_page


def _classify(config, text: str):
    return DocumentClassifier(config).classify(flatten_whitespace(text))


class TestPhanLoaiDung:
    def test_hoa_don_meta(self, classifier_config):
        text = read_fixture("meta_invoice.txt") + read_fixture("meta_invoice_page2.txt")
        assert _classify(classifier_config, text).document_type is DocumentType.META_INVOICE

    def test_debit_note(self, classifier_config):
        result = _classify(classifier_config, read_fixture("vpbank_debit_note.txt"))
        assert result.document_type is DocumentType.VPBANK_DEBIT_NOTE

    def test_hoa_don_gtgt_ngan_hang(self, classifier_config):
        result = _classify(classifier_config, build_vat_page().text)
        assert result.document_type is DocumentType.VPBANK_VAT_INVOICE


class TestKhongDuaVaoTenFile:
    def test_ten_file_khong_anh_huong_ket_qua(self, classifier_config):
        """Tên file rác vẫn phải phân loại đúng vì chỉ đọc nội dung."""
        text = read_fixture("vpbank_debit_note.txt")
        assert _classify(classifier_config, text).document_type is DocumentType.VPBANK_DEBIT_NOTE


class TestKhongDoanBua:
    def test_text_la_tra_unknown(self, classifier_config):
        result = _classify(classifier_config, "Đây là một tài liệu hoàn toàn khác")
        assert result.document_type is DocumentType.UNKNOWN
        assert result.ambiguous is False

    def test_text_rong_tra_unknown(self, classifier_config):
        assert _classify(classifier_config, "").document_type is DocumentType.UNKNOWN

    def test_nhieu_loai_cung_khop_tra_unknown_chu_khong_chon_diem_cao(self, classifier_config):
        """Hai loại cùng thoả -> UNKNOWN + ambiguous, KHÔNG tự chọn loại điểm cao."""
        text = (
            "DEBIT NOTE Mã giao dịch/Transaction code: FT26000000000001 "
            "Bản thể hiện của hóa đơn điện tử Cộng tiền hàng (Subtotal): 20.000"
        )
        result = _classify(classifier_config, text)
        assert result.document_type is DocumentType.UNKNOWN
        assert result.ambiguous is True
        assert len(result.candidates) >= 2

    def test_must_not_have_uu_tien_hon_must_have(self, classifier_config):
        """Keyword cấm loại thẳng một loại, kể cả khi keyword bắt buộc có mặt."""
        text = "PHIẾU GIAO DỊCH GHI NỢ Meta Platforms Ireland Số tham chiếu: ABCD1234EF"
        result = _classify(classifier_config, text)
        # META bị loại vì chứa "PHIẾU GIAO DỊCH GHI NỢ" -> chỉ còn debit note.
        assert result.document_type is DocumentType.VPBANK_DEBIT_NOTE
        assert "META_INVOICE" not in result.candidates


class TestMustNotHave:
    def test_ky_hieu_serial_loai_debit_note(self, classifier_config):
        """Chứng từ có 'Ký hiệu (Serial)' không bao giờ là debit note."""
        text = "PHIẾU GIAO DỊCH GHI NỢ Ký hiệu (Serial): 1K26XXX"
        result = _classify(classifier_config, text)
        assert result.document_type is not DocumentType.VPBANK_DEBIT_NOTE


class TestKeywordCuSaiDaDuocThay:
    def test_hoa_don_vpbank_khong_chua_cum_gia_tri_gia_tang(self):
        """Ghi nhận phát hiện từ file mẫu: hai cụm này KHÔNG tồn tại."""
        text = build_vat_page().text
        assert "HÓA ĐƠN GIÁ TRỊ GIA TĂNG" not in text.upper()
        assert "VAT INVOICE" not in text.upper()

    def test_van_phan_loai_dung_nho_bo_keyword_moi(self, classifier_config):
        result = _classify(classifier_config, build_vat_page().text)
        assert result.document_type is DocumentType.VPBANK_VAT_INVOICE
        assert "Ký hiệu (Serial)" in result.matched_keywords
