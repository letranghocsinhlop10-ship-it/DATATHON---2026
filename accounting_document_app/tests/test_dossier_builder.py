"""Test dựng dossier — đánh số, trùng lặp, và luật K1/K2 cho hoá đơn GTGT."""

from __future__ import annotations

from app.matching.dossier_builder import DossierBuilder
from matching_helpers import debit, meta, vat


class TestDungCoBan:
    def test_bo_du_ba_chung_tu(self):
        docs = [meta("ABCD1234EF"), debit("ABCD1234EF", "FT26000001"), vat("ABCD1234EF", "FT26000001")]
        result = DossierBuilder().build(docs)
        assert len(result.dossiers) == 1
        d = result.dossiers[0]
        assert d.reference == "ABCD1234EF"
        assert (d.meta_count, d.debit_count, d.vat_count) == (1, 1, 1)
        assert d.meta_document_id is not None
        assert d.debit_document_id is not None
        assert d.vat_document_id is not None

    def test_thieu_vat(self):
        docs = [meta("ABCD1234EF"), debit("ABCD1234EF", "FT26000001")]
        d = DossierBuilder().build(docs).dossiers[0]
        assert (d.meta_count, d.debit_count, d.vat_count) == (1, 1, 0)
        assert d.vat_document_id is None

    def test_danh_so_on_dinh_theo_thu_tu_khoa(self):
        docs = [meta("ZZZZ9999YY"), meta("ABCD1234EF")]
        dossiers = DossierBuilder().build(docs).dossiers
        codes = {d.reference: d.dossier_code for d in dossiers}
        assert codes["ABCD1234EF"] == "HS000001"
        assert codes["ZZZZ9999YY"] == "HS000002"

    def test_chung_tu_khong_co_khoa_vao_unmatched(self):
        docs = [meta(None), debit("ABCD1234EF")]
        result = DossierBuilder().build(docs)
        assert len(result.unmatched) == 1
        assert len(result.dossiers) == 1  # nhóm ABCD1234EF (chỉ có debit)


class TestTrungLapKhongCoBanChinh:
    def test_hai_meta_cung_khoa_khong_chon_ban_chinh(self):
        docs = [meta("ABCD1234EF"), meta("ABCD1234EF")]
        d = DossierBuilder().build(docs).dossiers[0]
        assert d.meta_count == 2
        assert d.meta_document_id is None  # không tự chọn bản nào là chính

    def test_hai_meta_van_nam_trong_extra_documents(self):
        docs = [meta("ABCD1234EF"), meta("ABCD1234EF")]
        d = DossierBuilder().build(docs).dossiers[0]
        assert len(d.extra_documents) == 2


class TestThongTinHienThi:
    def test_lay_the_va_ngay_tu_chung_tu_dau_tien_co_gia_tri(self):
        docs = [
            meta("ABCD1234EF", card_last4=None, document_date="2026-08-01"),
            debit("ABCD1234EF", "FT26000001", card_last4="1234"),
        ]
        d = DossierBuilder().build(docs).dossiers[0]
        assert d.card_last4 == "1234"


class TestRescueK1:
    """Hoá đơn GTGT lạc nhóm (K2 thất bại) được cứu qua K1."""

    def test_vat_thieu_meta_reference_duoc_ghep_qua_ma_giao_dich(self):
        docs = [
            meta("ABCD1234EF"),
            debit("ABCD1234EF", "FT26000001"),
            vat(None, "FT26000001"),  # meta_reference đọc thất bại
        ]
        result = DossierBuilder().build(docs)
        assert len(result.unmatched) == 0
        d = result.dossiers[0]
        assert d.vat_count == 1
        codes = [i.code for i in d.issues]
        assert "META_REF_NOT_IN_VAT" in codes

    def test_khong_khop_ma_giao_dich_nao_thi_van_o_lai_unmatched(self):
        docs = [
            meta("ABCD1234EF"),
            debit("ABCD1234EF", "FT26000001"),
            vat(None, "FT_KHONG_KHOP"),
        ]
        result = DossierBuilder().build(docs)
        assert len(result.unmatched) == 1
        assert result.dossiers[0].vat_count == 0

    def test_ma_giao_dich_trung_o_nhieu_nhom_thi_khong_tu_chon(self):
        docs = [
            meta("ABCD1234EF"),
            debit("ABCD1234EF", "FT_TRUNG"),
            meta("ZZZZ9999YY"),
            debit("ZZZZ9999YY", "FT_TRUNG"),
            vat(None, "FT_TRUNG"),
        ]
        result = DossierBuilder().build(docs)
        assert len(result.unmatched) == 1
        assert all(d.vat_count == 0 for d in result.dossiers)


class TestKhongXacNhanDuocK1:
    def test_vat_khop_k2_nhung_ma_giao_dich_khac_thi_gan_co_info(self):
        docs = [
            meta("ABCD1234EF"),
            debit("ABCD1234EF", "FT26000001"),
            vat("ABCD1234EF", "FT_KHAC"),  # K2 khớp, K1 không khớp
        ]
        d = DossierBuilder().build(docs).dossiers[0]
        assert d.vat_count == 1  # vẫn ghép, vì K2 đã là bằng chứng đủ
        codes = [i.code for i in d.issues]
        assert "FT_CODE_NOT_IN_VAT" in codes

    def test_khop_ca_hai_khoa_thi_khong_co_canh_bao(self):
        docs = [
            meta("ABCD1234EF"),
            debit("ABCD1234EF", "FT26000001"),
            vat("ABCD1234EF", "FT26000001"),
        ]
        d = DossierBuilder().build(docs).dossiers[0]
        codes = [i.code for i in d.issues]
        assert "FT_CODE_NOT_IN_VAT" not in codes
        assert "VAT_KEY_CONFLICT" not in codes


class TestXungDotK1K2:
    def test_k2_tro_nhom_nay_k1_tro_nhom_khac_thi_gan_co_blocking(self):
        docs = [
            meta("ABCD1234EF"),
            debit("ABCD1234EF", "FT_AAA"),
            meta("ZZZZ9999YY"),
            debit("ZZZZ9999YY", "FT_BBB"),
            # K2 (meta_reference) trỏ nhóm ABCD1234EF, nhưng K1 trỏ nhóm ZZZZ9999YY
            vat("ABCD1234EF", "FT_BBB"),
        ]
        result = DossierBuilder().build(docs)
        home = next(d for d in result.dossiers if d.reference == "ABCD1234EF")
        assert home.vat_count == 1  # vẫn nằm ở nhà K2, không bị gỡ
        codes = {i.code: i.severity.value for i in home.issues}
        assert codes.get("VAT_KEY_CONFLICT") == "BLOCKING"

    def test_khong_bao_gio_tu_di_chuyen_sang_nhom_khac(self):
        """An toàn: dù mâu thuẫn, VAT vẫn ở nguyên nhóm K2 — không đoán."""
        docs = [
            meta("ABCD1234EF"),
            debit("ABCD1234EF", "FT_AAA"),
            meta("ZZZZ9999YY"),
            debit("ZZZZ9999YY", "FT_BBB"),
            vat("ABCD1234EF", "FT_BBB"),
        ]
        result = DossierBuilder().build(docs)
        other = next(d for d in result.dossiers if d.reference == "ZZZZ9999YY")
        assert other.vat_count == 0
