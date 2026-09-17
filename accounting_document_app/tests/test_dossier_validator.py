"""Test kiểm tra dossier — bảng quyết định §7.1 và các cảnh báo chéo §7.2."""

from __future__ import annotations

from decimal import Decimal

from app.matching.dossier_builder import DossierBuilder
from app.matching.dossier_validator import DossierValidator, ValidationConfig
from app.models.enums import DossierStatus, Severity, TextSource
from matching_helpers import Decimal as D
from matching_helpers import date, debit, meta, vat


def _build_and_validate(docs, config: ValidationConfig | None = None):
    result = DossierBuilder().build(docs)
    docs_by_id = {d.document_id: d for d in docs}
    validator = DossierValidator(config)
    for d in result.dossiers:
        validator.validate(d, docs_by_id)
    return result.dossiers[0]


class TestBangQuyetDinh:
    def test_du_ba_chung_tu_la_valid(self):
        docs = [meta("ABCD1234EF"), debit("ABCD1234EF", "FT1"), vat("ABCD1234EF", "FT1")]
        assert _build_and_validate(docs).status is DossierStatus.VALID

    def test_thieu_vat(self):
        docs = [meta("ABCD1234EF"), debit("ABCD1234EF", "FT1")]
        assert _build_and_validate(docs).status is DossierStatus.MISSING_VAT

    def test_thieu_debit(self):
        docs = [meta("ABCD1234EF"), vat("ABCD1234EF", "FT1")]
        assert _build_and_validate(docs).status is DossierStatus.MISSING_DEBIT

    def test_thieu_ca_debit_va_vat_uu_tien_missing_debit(self):
        docs = [meta("ABCD1234EF")]
        assert _build_and_validate(docs).status is DossierStatus.MISSING_DEBIT

    def test_chi_co_debit(self):
        docs = [debit("ABCD1234EF", "FT1")]
        assert _build_and_validate(docs).status is DossierStatus.MISSING_META

    def test_hai_meta_la_duplicate(self):
        docs = [meta("ABCD1234EF"), meta("ABCD1234EF"), debit("ABCD1234EF", "FT1"), vat("ABCD1234EF", "FT1")]
        assert _build_and_validate(docs).status is DossierStatus.DUPLICATE_META

    def test_hai_debit_la_duplicate(self):
        docs = [
            meta("ABCD1234EF"),
            debit("ABCD1234EF", "FT1"),
            debit("ABCD1234EF", "FT1"),
            vat("ABCD1234EF", "FT1"),
        ]
        assert _build_and_validate(docs).status is DossierStatus.DUPLICATE_DEBIT

    def test_hai_vat_la_duplicate(self):
        docs = [
            meta("ABCD1234EF"),
            debit("ABCD1234EF", "FT1"),
            vat("ABCD1234EF", "FT1"),
            vat("ABCD1234EF", "FT1"),
        ]
        assert _build_and_validate(docs).status is DossierStatus.DUPLICATE_VAT


class TestThuTuUuTien:
    def test_duplicate_meta_uu_tien_hon_missing_vat(self):
        """Dù thiếu VAT, có DUPLICATE_META vẫn phải hiện DUPLICATE_META."""
        docs = [meta("ABCD1234EF"), meta("ABCD1234EF"), debit("ABCD1234EF", "FT1")]
        assert _build_and_validate(docs).status is DossierStatus.DUPLICATE_META

    def test_invalid_reference_uu_tien_hon_missing_debit(self):
        docs = [
            meta("AB1", field_errors={"reference_number": "REFERENCE_INVALID_FORMAT"}),
            vat("AB1", "FT1"),
        ]
        d = _build_and_validate(docs)
        assert d.status is DossierStatus.INVALID_REFERENCE


class TestKhongTuDongGhepSaiTruDungKhoa:
    def test_reference_khac_nhau_khong_bao_gio_ghep(self):
        docs = [meta("ABCD1234EF"), debit("ZZZZ9999YY", "FT1")]
        result = DossierBuilder().build(docs)
        # Hai chứng từ tạo thành HAI dossier riêng biệt, không có dossier nào VALID.
        assert len(result.dossiers) == 2
        docs_by_id = {d.document_id: d for d in docs}
        validator = DossierValidator()
        for d in result.dossiers:
            validator.validate(d, docs_by_id)
            assert d.status is not DossierStatus.VALID


class TestVatKeyConflictEpNeedsReview:
    def test_du_ba_chung_tu_nhung_xung_dot_k1_k2_thi_khong_valid(self):
        docs = [
            meta("ABCD1234EF"),
            debit("ABCD1234EF", "FT_AAA"),
            meta("ZZZZ9999YY"),
            debit("ZZZZ9999YY", "FT_BBB"),
            vat("ABCD1234EF", "FT_BBB"),  # K2 khớp ABCD, K1 khớp ZZZZ
        ]
        result = DossierBuilder().build(docs)
        docs_by_id = {d.document_id: d for d in docs}
        validator = DossierValidator()
        home = next(d for d in result.dossiers if d.reference == "ABCD1234EF")
        validator.validate(home, docs_by_id)
        assert home.is_complete  # đủ 3 document_id
        assert home.status is DossierStatus.NEEDS_REVIEW  # nhưng KHÔNG valid


class TestAmountChain:
    def test_khop_dang_thuc_thi_info(self):
        docs = [
            meta("ABCD1234EF", subtotal=D("1000000"), vat_amount=D("100000"), total_amount=D("1100000")),
            debit("ABCD1234EF", "FT1", total_amount=D("1122000")),
            vat("ABCD1234EF", "FT1", subtotal=D("20000"), vat_amount=D("2000"), total_amount=D("22000")),
        ]
        d = _build_and_validate(docs)
        codes = [i.code for i in d.issues]
        assert "AMOUNT_CHAIN_OK" in codes
        assert "AMOUNT_CHAIN_BROKEN" not in codes

    def test_lech_dang_thuc_thi_warning(self):
        docs = [
            meta("ABCD1234EF", total_amount=D("1100000")),
            debit("ABCD1234EF", "FT1", total_amount=D("999999")),
            vat("ABCD1234EF", "FT1", total_amount=D("22000")),
        ]
        d = _build_and_validate(docs)
        issue = next(i for i in d.issues if i.code == "AMOUNT_CHAIN_BROKEN")
        assert issue.severity is Severity.WARNING
        # Cảnh báo KHÔNG được đổi trạng thái từ VALID.
        assert d.status is DossierStatus.VALID

    def test_thieu_du_lieu_thi_khong_kiem_tra(self):
        docs = [meta("ABCD1234EF"), debit("ABCD1234EF", "FT1"), vat("ABCD1234EF", "FT1")]
        d = _build_and_validate(docs)
        codes = [i.code for i in d.issues]
        assert "AMOUNT_CHAIN_OK" not in codes
        assert "AMOUNT_CHAIN_BROKEN" not in codes


class TestCardMismatch:
    def test_the_khac_nhau_thi_canh_bao(self):
        docs = [
            meta("ABCD1234EF", card_last4="1234"),
            debit("ABCD1234EF", "FT1", card_last4="9999"),
        ]
        d = _build_and_validate(docs)
        assert "CARD_MISMATCH" in [i.code for i in d.issues]

    def test_the_giong_nhau_thi_khong_canh_bao(self):
        docs = [
            meta("ABCD1234EF", card_last4="1234"),
            debit("ABCD1234EF", "FT1", card_last4="1234"),
        ]
        d = _build_and_validate(docs)
        assert "CARD_MISMATCH" not in [i.code for i in d.issues]


class TestDateGap:
    def test_lech_qua_nguong_thi_canh_bao(self):
        docs = [
            meta("ABCD1234EF", document_date=date(2026, 8, 1)),
            debit("ABCD1234EF", "FT1", transaction_date=date(2026, 8, 20)),
        ]
        d = _build_and_validate(docs, ValidationConfig(max_date_gap_days=7))
        assert "DATE_GAP_TOO_LARGE" in [i.code for i in d.issues]

    def test_trong_nguong_thi_khong_canh_bao(self):
        docs = [
            meta("ABCD1234EF", document_date=date(2026, 8, 1)),
            debit("ABCD1234EF", "FT1", transaction_date=date(2026, 8, 2)),
        ]
        d = _build_and_validate(docs, ValidationConfig(max_date_gap_days=7))
        assert "DATE_GAP_TOO_LARGE" not in [i.code for i in d.issues]


class TestTaxCodeMismatch:
    def test_mst_khac_cau_hinh_thi_canh_bao(self):
        docs = [meta("ABCD1234EF"), vat("ABCD1234EF", "FT1", tax_code="0100000001")]
        d = _build_and_validate(docs, ValidationConfig(company_tax_code="0200000002"))
        assert "TAX_CODE_MISMATCH" in [i.code for i in d.issues]

    def test_mst_khop_thi_khong_canh_bao(self):
        docs = [meta("ABCD1234EF"), vat("ABCD1234EF", "FT1", tax_code="0100000001")]
        d = _build_and_validate(docs, ValidationConfig(company_tax_code="0100000001"))
        assert "TAX_CODE_MISMATCH" not in [i.code for i in d.issues]

    def test_khong_cau_hinh_mst_thi_khong_kiem_tra(self):
        docs = [meta("ABCD1234EF"), vat("ABCD1234EF", "FT1", tax_code="bat_ky")]
        d = _build_and_validate(docs, ValidationConfig(company_tax_code=None))
        assert "TAX_CODE_MISMATCH" not in [i.code for i in d.issues]


class TestVatMathError:
    def test_meta_sai_toan_thi_canh_bao(self):
        docs = [
            meta("ABCD1234EF", subtotal=D("1000000"), vat_amount=D("100000"), total_amount=D("999999")),
        ]
        d = _build_and_validate(docs)
        issue = next(i for i in d.issues if i.code == "VAT_MATH_ERROR")
        assert "META_INVOICE" in issue.description

    def test_vat_invoice_sai_toan_thi_canh_bao(self):
        docs = [
            meta("ABCD1234EF"),
            vat("ABCD1234EF", "FT1", subtotal=D("20000"), vat_amount=D("2000"), total_amount=D("99999")),
        ]
        d = _build_and_validate(docs)
        issue = next(i for i in d.issues if i.code == "VAT_MATH_ERROR")
        assert "VPBANK_VAT_INVOICE" in issue.description

    def test_dung_toan_thi_khong_canh_bao(self):
        docs = [meta("ABCD1234EF", subtotal=D("1000000"), vat_amount=D("100000"), total_amount=D("1100000"))]
        d = _build_and_validate(docs)
        assert "VAT_MATH_ERROR" not in [i.code for i in d.issues]


class TestOcrSourcedData:
    def test_chung_tu_qua_ocr_thi_canh_bao(self):
        docs = [meta("ABCD1234EF", text_source=TextSource.OCR)]
        d = _build_and_validate(docs)
        assert "OCR_SOURCED_DATA" in [i.code for i in d.issues]

    def test_text_layer_thi_khong_canh_bao(self):
        docs = [meta("ABCD1234EF", text_source=TextSource.TEXT_LAYER)]
        d = _build_and_validate(docs)
        assert "OCR_SOURCED_DATA" not in [i.code for i in d.issues]


class TestCanhBaoKhongDoiTrangThai:
    def test_warning_va_info_khong_lam_mat_valid(self):
        """Nguyên tắc §7.2: cross-check chỉ hiển thị, không đổi liên kết/trạng thái."""
        docs = [
            meta("ABCD1234EF", card_last4="1234", text_source=TextSource.OCR),
            debit("ABCD1234EF", "FT1", card_last4="9999"),
            vat("ABCD1234EF", "FT1"),
        ]
        d = _build_and_validate(docs)
        assert d.status is DossierStatus.VALID
        assert any(i.severity is Severity.WARNING for i in d.issues)
        assert any(i.severity is Severity.INFO for i in d.issues)


class TestUnexpectedMerchantSuffix:
    def test_co_loi_thi_gan_co_info(self):
        docs = [
            meta("ABCD1234EF"),
            debit(
                "ABCD1234EF",
                "FT1",
                field_errors={"meta_reference": "UNEXPECTED_MERCHANT_SUFFIX"},
            ),
        ]
        d = _build_and_validate(docs)
        assert "UNEXPECTED_MERCHANT_SUFFIX" in [i.code for i in d.issues]

    def test_khong_co_loi_thi_khong_canh_bao(self):
        docs = [meta("ABCD1234EF"), debit("ABCD1234EF", "FT1")]
        d = _build_and_validate(docs)
        assert "UNEXPECTED_MERCHANT_SUFFIX" not in [i.code for i in d.issues]
