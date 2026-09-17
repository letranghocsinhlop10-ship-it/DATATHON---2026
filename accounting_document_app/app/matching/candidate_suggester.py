"""Gợi ý ghép tay cho chứng từ chưa có khoá — KHÔNG BAO GIỜ tự động ghép.

Ranh giới an toàn (§12.4 Phase 1): các tín hiệu dưới đây (cùng số thẻ, cùng
ngày, cùng số tiền) chỉ được dùng để XẾP HẠNG gợi ý hiển thị cho người dùng
trong màn hình Review. Không có đường code nào ở đây tạo ra một liên kết —
việc ghép chỉ xảy ra khi người dùng bấm "Accept" ở tầng UI/service khác,
và khi đó ``match_source`` luôn được ghi là ``MANUAL``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.models.document import Document
from app.models.enums import DocumentType

__all__ = ["MatchCandidate", "CandidateSuggester"]

#: Trọng số từng tín hiệu khi xếp hạng gợi ý — chỉ ảnh hưởng THỨ TỰ hiển thị.
_SIGNAL_WEIGHT = {
    "SAME_CARD_LAST4": 3,
    "SAME_AMOUNT": 2,
    "DATE_WITHIN_WINDOW": 1,
}


@dataclass(frozen=True)
class MatchCandidate:
    """Một gợi ý ghép — CHƯA phải là liên kết, chỉ hiển thị để xác nhận.

    Attributes:
        source_document_id: Chứng từ đang thiếu cặp (ví dụ một Meta lẻ).
        target_document_id: Chứng từ được gợi ý ghép cùng.
        signals: Các tín hiệu đã khớp, để hiển thị lý do gợi ý.
        score: Điểm xếp hạng — CHỈ để sắp thứ tự, không phải ngưỡng quyết định.
    """

    source_document_id: int
    target_document_id: int
    signals: tuple[str, ...] = field(default_factory=tuple)
    score: float = 0.0


class CandidateSuggester:
    """Sinh gợi ý ghép cho các chứng từ nằm trong danh sách "chưa có khoá".

    Args:
        date_window_days: Hai chứng từ được coi là "cùng ngày" nếu lệch
            không quá số ngày này.
    """

    def __init__(self, *, date_window_days: int = 3) -> None:
        self._date_window_days = date_window_days

    def suggest(self, unmatched: list[Document]) -> list[MatchCandidate]:
        """Sinh gợi ý giữa các chứng từ chưa ghép được, khác loại nhau.

        Args:
            unmatched: Chứng từ không có ``match_key`` (từ ``MatchResult``
                hoặc ``BuildResult``).

        Returns:
            Danh sách gợi ý, điểm cao xếp trước. Rỗng nếu không đủ dữ liệu
            để so sánh hoặc không có tín hiệu nào khớp.
        """
        candidates: list[MatchCandidate] = []
        for i, source in enumerate(unmatched):
            if source.document_id is None:
                continue
            for target in unmatched[i + 1 :]:
                if target.document_id is None:
                    continue
                if source.document_type is target.document_type:
                    # Chỉ gợi ý GHÉP CHÉO giữa các loại khác nhau — hai chứng
                    # từ cùng loại không bao giờ thuộc cùng một bộ hồ sơ.
                    continue
                signals = self._signals(source, target)
                if not signals:
                    continue
                score = sum(_SIGNAL_WEIGHT[s] for s in signals)
                candidates.append(
                    MatchCandidate(
                        source_document_id=source.document_id,
                        target_document_id=target.document_id,
                        signals=signals,
                        score=score,
                    )
                )

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    def _signals(self, a: Document, b: Document) -> tuple[str, ...]:
        signals: list[str] = []

        if a.card_last4 and b.card_last4 and a.card_last4 == b.card_last4:
            signals.append("SAME_CARD_LAST4")

        if a.total_amount is not None and b.total_amount is not None and a.total_amount == b.total_amount:
            signals.append("SAME_AMOUNT")

        date_a = a.transaction_date if isinstance(a.transaction_date, date) else a.document_date
        date_b = b.transaction_date if isinstance(b.transaction_date, date) else b.document_date
        if (
            isinstance(date_a, date)
            and isinstance(date_b, date)
            and abs((date_a - date_b).days) <= self._date_window_days
        ):
            signals.append("DATE_WITHIN_WINDOW")

        return tuple(signals)
