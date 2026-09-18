"""Điều phối MATCH/ORGANIZE/EXPORT của luồng Facebook Payment Group.

Khác với ``MatchService``/``OrganizeService``/``ExportService`` (luồng
dossier META/DEBIT/VAT gốc — mọi state đi qua DB), luồng payment group giữ
``FacebookPaymentGroup`` TRONG BỘ NHỚ giữa các bước thay vì thêm bảng DB
mới: ``match_run()`` trả thẳng danh sách để tầng gọi (GUI) giữ lại và
truyền tiếp cho ``organize()``/``export()`` — ``Document`` vẫn được SCAN và
lưu DB bình thường qua ``ScanService`` (không đổi gì ở đó).
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.bank_statement_parser import BankTransaction
from app.database.database import Database
from app.database.document_repository import DocumentRepository
from app.exporters.payment_group_exporter import PaymentGroupExporter
from app.exporters.payment_group_organizer import PaymentGroupOrganizeResult, PaymentGroupOrganizer
from app.matching.payment_group_matcher import PaymentGroupMatchResult, PaymentGroupMatcher
from app.models.facebook_payment_group import FacebookPaymentGroup

__all__ = ["PaymentGroupService"]

logger = logging.getLogger(__name__)


class PaymentGroupService:
    """Ghép + sắp xếp + xuất Excel cho luồng Facebook payment group.

    Args:
        db: Kết nối database đã mở.
    """

    def __init__(self, db: Database) -> None:
        self._documents = DocumentRepository(db)
        self._matcher = PaymentGroupMatcher()

    def match_run(
        self, run_id: int, bank_transactions: list[BankTransaction] | None = None
    ) -> PaymentGroupMatchResult:
        """Ghép payment group từ toàn bộ ``Document`` đã SCAN của một lô.

        Args:
            run_id: Lô xử lý (đã chạy ``PrepareDataService.prepare()``).
            bank_transactions: Dòng sao kê đã parse trong cùng lượt chuẩn bị
                dữ liệu (``PrepareResult.bank_transactions``).

        Returns:
            ``PaymentGroupMatchResult``.
        """
        documents = self._documents.list_by_run(run_id)
        result = self._matcher.match(documents, bank_transactions)
        logger.info("Ghép %d payment group cho run %d", len(result.groups), run_id)
        return result

    def organize(
        self, groups: list[FacebookPaymentGroup], output_root: Path | str
    ) -> PaymentGroupOrganizeResult:
        """Sắp xếp PDF theo từng payment group — xem ``PaymentGroupOrganizer``."""
        return PaymentGroupOrganizer(output_root).organize(groups)

    def export(self, groups: list[FacebookPaymentGroup], output_path: Path | str) -> Path:
        """Xuất Excel một sheet — xem ``PaymentGroupExporter``."""
        return PaymentGroupExporter().export(groups, output_path)
