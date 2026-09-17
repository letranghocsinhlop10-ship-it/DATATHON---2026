"""Test gợi ý ghép tay — CHỈ gợi ý, không bao giờ tự tạo liên kết."""

from __future__ import annotations

from app.matching.candidate_suggester import CandidateSuggester, MatchCandidate
from matching_helpers import date, debit, meta, vat


class TestGoiYCheoLoai:
    def test_cung_the_va_cung_ngay_thi_goi_y(self):
        docs = [
            meta(None, card_last4="1234", document_date=date(2026, 8, 1)),
            debit(None, card_last4="1234", transaction_date=date(2026, 8, 1)),
        ]
        candidates = CandidateSuggester().suggest(docs)
        assert len(candidates) == 1
        assert "SAME_CARD_LAST4" in candidates[0].signals

    def test_khong_co_tin_hieu_nao_thi_khong_goi_y(self):
        docs = [meta(None, card_last4="1234"), debit(None, card_last4="9999")]
        assert CandidateSuggester().suggest(docs) == []

    def test_khong_co_du_lieu_de_so_sanh_thi_khong_goi_y(self):
        docs = [meta(None), debit(None)]
        assert CandidateSuggester().suggest(docs) == []


class TestKhongGoiYCungLoai:
    def test_hai_meta_khong_bao_gio_goi_y(self):
        """Hai chứng từ cùng loại không bao giờ thuộc cùng một bộ hồ sơ."""
        docs = [
            meta(None, card_last4="1234", document_date=date(2026, 8, 1)),
            meta(None, card_last4="1234", document_date=date(2026, 8, 1)),
        ]
        assert CandidateSuggester().suggest(docs) == []


class TestXepHangTheoDiem:
    def test_nhieu_tin_hieu_hon_xep_truoc(self):
        docs = [
            meta(None, card_last4="1234", document_date=date(2026, 8, 1)),
            # chỉ khớp ngày
            debit(None, card_last4="0000", transaction_date=date(2026, 8, 1)),
            # khớp cả thẻ lẫn ngày
            debit(None, card_last4="1234", transaction_date=date(2026, 8, 1)),
        ]
        candidates = CandidateSuggester().suggest(docs)
        assert len(candidates) == 2
        assert candidates[0].score >= candidates[1].score
        assert "SAME_CARD_LAST4" in candidates[0].signals


class TestKhoangCachNgay:
    def test_trong_cua_so_thi_khop(self):
        docs = [
            meta(None, document_date=date(2026, 8, 1)),
            debit(None, transaction_date=date(2026, 8, 3)),
        ]
        candidates = CandidateSuggester(date_window_days=3).suggest(docs)
        assert len(candidates) == 1
        assert "DATE_WITHIN_WINDOW" in candidates[0].signals

    def test_ngoai_cua_so_thi_khong_khop(self):
        docs = [
            meta(None, document_date=date(2026, 8, 1)),
            debit(None, transaction_date=date(2026, 8, 10)),
        ]
        assert CandidateSuggester(date_window_days=3).suggest(docs) == []


class TestAnToanKhongTuGhep:
    def test_ket_qua_la_goi_y_khong_phai_lien_ket(self):
        """MatchCandidate không phải Dossier — không có trường status/VALID nào
        cho phép nó tự trở thành một liên kết đã ghép."""
        docs = [
            meta(None, card_last4="1234", document_date=date(2026, 8, 1)),
            debit(None, card_last4="1234", transaction_date=date(2026, 8, 1)),
        ]
        candidates = CandidateSuggester().suggest(docs)
        assert isinstance(candidates[0], MatchCandidate)
        assert not hasattr(candidates[0], "status")
