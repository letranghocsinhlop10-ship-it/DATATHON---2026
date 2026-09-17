"""Gom nhóm chứng từ theo khoá tham chiếu — bước đầu tiên của việc ghép bộ.

Đây là hàm THUẦN, không I/O, không phụ thuộc DB hay GUI: nhận danh sách
``Document`` đã trích xuất, trả về các nhóm theo ``match_key`` (đã chuẩn hoá
ở ``Document.match_key``, xem ``app/models/document.py``).

So sánh khoá là ``==`` trên chuỗi Python — không có bất kỳ phép so khớp mờ
nào ở đây hay bất cứ đâu trong hệ thống (§32 Phase 1: reference matching
phải deterministic, không dùng AI/LLM).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.models.document import Document
from app.models.enums import DocumentType

__all__ = ["ReferenceGroup", "MatchResult", "ReferenceMatcher"]


@dataclass
class ReferenceGroup:
    """Toàn bộ chứng từ có cùng một khoá tham chiếu.

    Attributes:
        key: Khoá đã chuẩn hoá (chung cho cả nhóm).
        metas: Hoá đơn Meta có ``reference_number`` == key.
        debits: Debit note có ``meta_reference`` == key.
        vats: Hoá đơn GTGT có ``meta_reference`` == key (khớp qua K2).
    """

    key: str
    metas: list[Document] = field(default_factory=list)
    debits: list[Document] = field(default_factory=list)
    vats: list[Document] = field(default_factory=list)

    def documents_of(self, document_type: DocumentType) -> list[Document]:
        return {
            DocumentType.META_INVOICE: self.metas,
            DocumentType.VPBANK_DEBIT_NOTE: self.debits,
            DocumentType.VPBANK_VAT_INVOICE: self.vats,
        }[document_type]

    @property
    def all_documents(self) -> list[Document]:
        return [*self.metas, *self.debits, *self.vats]


@dataclass
class MatchResult:
    """Kết quả gom nhóm toàn bộ chứng từ của một lô xử lý.

    Attributes:
        groups: Ánh xạ khoá đã chuẩn hoá -> nhóm chứng từ.
        unmatched: Chứng từ không có khoá (``match_key is None``) — không
            đọc được reference, hoặc loại ``UNKNOWN``/không hỗ trợ ghép.
    """

    groups: dict[str, ReferenceGroup] = field(default_factory=dict)
    unmatched: list[Document] = field(default_factory=list)

    def group_for(self, key: str) -> ReferenceGroup | None:
        return self.groups.get(key)


class ReferenceMatcher:
    """Gom danh sách ``Document`` thành các nhóm theo ``match_key``."""

    def match(self, documents: list[Document]) -> MatchResult:
        """Gom nhóm chứng từ.

        Args:
            documents: Toàn bộ chứng từ đã đọc và trích xuất trong một lô.

        Returns:
            ``MatchResult`` — nhóm theo khoá, và danh sách chứng từ chưa có khoá.
        """
        groups: dict[str, ReferenceGroup] = {}
        unmatched: list[Document] = []
        by_key: dict[str, list[Document]] = defaultdict(list)

        for doc in documents:
            key = doc.match_key
            if key is None:
                unmatched.append(doc)
                continue
            by_key[key].append(doc)

        for key, docs in by_key.items():
            group = ReferenceGroup(key=key)
            for doc in docs:
                if doc.document_type in (
                    DocumentType.META_INVOICE,
                    DocumentType.VPBANK_DEBIT_NOTE,
                    DocumentType.VPBANK_VAT_INVOICE,
                ):
                    group.documents_of(doc.document_type).append(doc)
                else:  # pragma: no cover - match_key đã lọc UNKNOWN thành None
                    unmatched.append(doc)
            groups[key] = group

        return MatchResult(groups=groups, unmatched=unmatched)
