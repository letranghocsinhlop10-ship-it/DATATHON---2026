"""Test gom nhóm chứng từ theo khoá — nền tảng của việc ghép bộ."""

from __future__ import annotations

from app.matching.reference_matcher import ReferenceMatcher
from matching_helpers import debit, meta, vat


class TestGomNhomCoBanKhopChinhXac:
    def test_ba_chung_tu_cung_khoa_vao_mot_nhom(self):
        docs = [meta("ABCD1234EF"), debit("ABCD1234EF"), vat("ABCD1234EF")]
        result = ReferenceMatcher().match(docs)
        assert set(result.groups) == {"ABCD1234EF"}
        group = result.groups["ABCD1234EF"]
        assert len(group.metas) == 1
        assert len(group.debits) == 1
        assert len(group.vats) == 1
        assert result.unmatched == []

    def test_hai_khoa_khac_nhau_thanh_hai_nhom(self):
        docs = [meta("ABCD1234EF"), debit("ABCD1234EF"), meta("ZZZZ9999YY"), debit("ZZZZ9999YY")]
        result = ReferenceMatcher().match(docs)
        assert set(result.groups) == {"ABCD1234EF", "ZZZZ9999YY"}

    def test_lech_mot_ky_tu_khong_vao_cung_nhom(self):
        """Đây là bằng chứng exact-match: không fuzzy, không gần đúng."""
        docs = [meta("ABCD1234EF"), debit("ABCD1234EG")]
        result = ReferenceMatcher().match(docs)
        assert len(result.groups) == 2
        assert "ABCD1234EF" in result.groups
        assert "ABCD1234EG" in result.groups


class TestKhongCoKhoaThiChuaGhep:
    def test_reference_none_vao_unmatched(self):
        docs = [meta(None), debit("ABCD1234EF")]
        result = ReferenceMatcher().match(docs)
        assert len(result.unmatched) == 1
        assert result.unmatched[0].document_type.value == "META_INVOICE"

    def test_ca_ba_khong_co_khoa_deu_vao_unmatched(self):
        docs = [meta(None), debit(None), vat(None)]
        result = ReferenceMatcher().match(docs)
        assert len(result.unmatched) == 3
        assert result.groups == {}


class TestTrungLap:
    def test_hai_meta_cung_khoa_nam_chung_mot_nhom(self):
        docs = [meta("ABCD1234EF"), meta("ABCD1234EF"), debit("ABCD1234EF")]
        result = ReferenceMatcher().match(docs)
        assert len(result.groups["ABCD1234EF"].metas) == 2
