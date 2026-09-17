"""Điều phối bước MATCH + VALIDATE: ``Document`` đã lưu -> ``Dossier`` đã lưu.

Ghép các module Phase 3 (``DossierBuilder``, ``DossierValidator``,
``CandidateSuggester``) thành một bước gọi được từ GUI/CLI, tương tự
``ScanService`` cho bước quét.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config_loader import AppSettings
from app.database.database import Database
from app.database.document_repository import DocumentRepository
from app.database.dossier_repository import DossierRepository
from app.matching.candidate_suggester import CandidateSuggester, MatchCandidate
from app.matching.dossier_builder import DossierBuilder
from app.matching.dossier_validator import DossierValidator, ValidationConfig
from app.models.dossier import Dossier
from app.models.document import Document

__all__ = ["MatchResult", "MatchService"]

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """Kết quả một lượt ghép bộ hồ sơ."""

    dossiers: list[Dossier] = field(default_factory=list)
    unmatched: list[Document] = field(default_factory=list)
    candidates: list[MatchCandidate] = field(default_factory=list)


class MatchService:
    """Ghép bộ hồ sơ từ toàn bộ chứng từ của một lô, kiểm tra, lưu DB.

    Args:
        db: Kết nối database đã mở.
        app_settings: Cấu hình vận hành (ngưỡng lệch ngày...).
        company_tax_code: MST công ty đã chuẩn hoá, để đối chiếu
            ``TAX_CODE_MISMATCH``; ``None`` nếu chưa cấu hình.
    """

    def __init__(
        self,
        db: Database,
        app_settings: AppSettings,
        *,
        company_tax_code: str | None = None,
    ) -> None:
        self._db = db
        self._documents = DocumentRepository(db)
        self._dossiers = DossierRepository(db)
        self._builder = DossierBuilder()
        self._validator = DossierValidator(
            ValidationConfig(
                max_date_gap_days=app_settings.max_date_gap_days,
                amount_chain_tolerance=app_settings.amount_chain_tolerance,
                company_tax_code=company_tax_code,
            )
        )
        self._suggester = CandidateSuggester()

    def match_run(self, run_id: int) -> MatchResult:
        """Ghép bộ hồ sơ cho toàn bộ chứng từ thuộc một lô đã quét.

        Args:
            run_id: Lô xử lý (khoá ``documents.run_id``).

        Returns:
            ``MatchResult`` — dossier đã lưu DB, chứng từ chưa ghép, và gợi ý
            ghép tay (``CandidateSuggester`` — chỉ hiển thị, không tự ghép).
        """
        documents = self._documents.list_by_run(run_id)
        return self.match_documents(documents, run_id=run_id)

    def match_documents(self, documents: list[Document], *, run_id: int | None = None) -> MatchResult:
        """Ghép bộ hồ sơ từ danh sách chứng từ đã có ``document_id``.

        Args:
            documents: Chứng từ đã trích xuất (thường từ ``ScanService``).
            run_id: Lô xử lý, để gắn lên dossier khi lưu.

        Returns:
            ``MatchResult`` đầy đủ.
        """
        build_result = self._builder.build(documents)
        documents_by_id = {d.document_id: d for d in documents if d.document_id is not None}

        for dossier in build_result.dossiers:
            self._validator.validate(dossier, documents_by_id)
            self._dossiers.save(dossier, run_id=run_id)

        candidates = self._suggester.suggest(build_result.unmatched)

        logger.info(
            "Ghép xong: %d dossier, %d chứng từ chưa ghép, %d gợi ý",
            len(build_result.dossiers),
            len(build_result.unmatched),
            len(candidates),
        )
        return MatchResult(
            dossiers=build_result.dossiers,
            unmatched=build_result.unmatched,
            candidates=candidates,
        )
