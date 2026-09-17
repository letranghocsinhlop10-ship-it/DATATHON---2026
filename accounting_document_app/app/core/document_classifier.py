"""Phân loại chứng từ dựa trên NỘI DUNG text, không bao giờ dựa trên tên file.

Luật nằm trong ``config/document_rules.yaml`` nên thêm ngân hàng hoặc nhà
cung cấp mới chỉ cần thêm một khối YAML.

Nguyên tắc an toàn: nếu từ hai loại trở lên cùng thoả điều kiện, kết quả là
``UNKNOWN`` kèm cờ ``ambiguous`` — hệ thống KHÔNG tự chọn loại có điểm cao
hơn, vì phân loại sai sẽ kéo theo trích xuất sai và ghép sai.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config_loader import ClassifierConfig, ClassifierTypeRule
from app.models.enums import DocumentType

__all__ = ["ClassificationResult", "DocumentClassifier"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClassificationResult:
    """Kết quả phân loại một chứng từ.

    Attributes:
        document_type: Loại chứng từ, hoặc ``UNKNOWN``.
        score: Điểm của loại được chọn.
        rule_id: Tên loại đã khớp, để truy vết.
        matched_keywords: Các từ khoá đã khớp — hiển thị cho người dùng khi
            cần giải thích vì sao file được xếp vào loại này.
        ambiguous: ``True`` khi nhiều loại cùng thoả.
        candidates: Điểm của tất cả các loại đã thoả điều kiện bắt buộc.
    """

    document_type: DocumentType
    score: float = 0.0
    rule_id: str | None = None
    matched_keywords: tuple[str, ...] = ()
    ambiguous: bool = False
    candidates: dict[str, float] = field(default_factory=dict)


class DocumentClassifier:
    """Chấm điểm text của một PDF theo từng bộ luật loại chứng từ.

    Args:
        config: Bộ luật đã nạp từ ``document_rules.yaml``.
    """

    def __init__(self, config: ClassifierConfig) -> None:
        self._config = config

    def classify(self, text: str) -> ClassificationResult:
        """Phân loại một chứng từ từ text của nó.

        Args:
            text: Text đã trích xuất (nên dùng text gộp khoảng trắng để
                keyword không bị PDF ngắt dòng làm hỏng).

        Returns:
            ``ClassificationResult``. Trả về ``UNKNOWN`` khi không loại nào
            thoả, hoặc khi có từ hai loại trở lên cùng thoả.
        """
        if not text or not text.strip():
            return ClassificationResult(document_type=DocumentType.UNKNOWN)

        haystack = text if self._config.case_sensitive else text.lower()

        matches: list[tuple[ClassifierTypeRule, float, tuple[str, ...]]] = []
        for rule in self._config.rules:
            scored = self._score(rule, haystack)
            if scored is not None:
                score, keywords = scored
                matches.append((rule, score, keywords))

        candidates = {rule.document_type.value: score for rule, score, _ in matches}

        if not matches:
            logger.debug("Không loại nào khớp — UNKNOWN")
            return ClassificationResult(
                document_type=DocumentType.UNKNOWN,
                candidates=candidates,
            )

        if len(matches) > 1:
            logger.warning("Nhiều loại cùng khớp: %s — trả UNKNOWN để người dùng kiểm tra", candidates)
            return ClassificationResult(
                document_type=DocumentType.UNKNOWN,
                ambiguous=True,
                candidates=candidates,
            )

        rule, score, keywords = matches[0]
        return ClassificationResult(
            document_type=rule.document_type,
            score=score,
            rule_id=rule.document_type.value,
            matched_keywords=keywords,
            candidates=candidates,
        )

    def _score(
        self, rule: ClassifierTypeRule, haystack: str
    ) -> tuple[float, tuple[str, ...]] | None:
        """Chấm điểm một loại. Trả ``None`` nếu loại bị loại thẳng."""

        def contains(needle: str) -> bool:
            probe = needle if self._config.case_sensitive else needle.lower()
            return probe in haystack

        for forbidden in rule.must_not_have:
            if contains(forbidden):
                return None

        required_hits = tuple(k for k in rule.must_have_any if contains(k))
        if not required_hits:
            return None

        strong_hits = tuple(k for k in rule.strong if contains(k))
        score = float(len(required_hits) + len(strong_hits))
        if score < rule.min_score:
            return None
        return score, required_hits + strong_hits
