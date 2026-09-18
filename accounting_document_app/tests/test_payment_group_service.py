"""Test tích hợp PaymentGroupService: match từ DB, organize, export."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import openpyxl
import pytest

from app.database.database import Database
from app.database.document_repository import DocumentRepository
from app.database.processing_run_repository import ProcessingRunRepository
from app.models.enums import DocumentType, PaymentGroupStatus
from app.services.payment_group_service import PaymentGroupService
from matching_helpers import make_doc
from pdf_synth import FONT, write_pdf

pytestmark = pytest.mark.skipif(FONT is None, reason="Không tìm thấy font DejaVu Sans trong môi trường này")


@pytest.fixture
def db():
    with Database(":memory:") as database:
        yield database


class TestPaymentGroupServiceEndToEnd:
    def test_match_organize_export_tu_du_lieu_da_luu_db(self, db, tmp_path):
        run_id = ProcessingRunRepository(db).start(str(tmp_path))
        docs_repo = DocumentRepository(db)

        bill = make_doc(
            DocumentType.META_INVOICE,
            reference_number="ABCD1234EF",
            total_amount=Decimal("2530672"),
            document_date=date(2026, 8, 1),
        )
        bill.document_id = None  # để DocumentRepository tự INSERT (id giả từ make_doc chỉ dùng cho test thuần)
        bill.file_path = tmp_path / "bill.pdf"
        write_pdf(bill.file_path, [["hoa don facebook"]])

        note = make_doc(
            DocumentType.VPBANK_DEBIT_NOTE,
            meta_reference="ABCD1234EF",
            transaction_code="FT100000001",
            total_amount=Decimal("2558510"),
            transaction_date=date(2026, 8, 1),
            payment_detail="GD thanh toan tai FACEBK *ABCD1234EF",
        )
        note.document_id = None
        note.file_path = tmp_path / "note.pdf"
        write_pdf(note.file_path, [["phieu ghi no"]])

        docs_repo.save(bill, run_id=run_id)
        docs_repo.save(note, run_id=run_id)

        service = PaymentGroupService(db)
        match_result = service.match_run(run_id)

        assert len(match_result.groups) == 1
        group = match_result.groups[0]
        assert group.status is PaymentGroupStatus.MATCHED_HIGH

        organize_result = service.organize(match_result.groups, tmp_path / "OUTPUT")
        assert organize_result.copied_files == 2
        folder = tmp_path / "OUTPUT" / group.group_code
        assert (folder / "01_Meta_Invoice.pdf").is_file()
        assert (folder / "02_VPBank_Main_Debit.pdf").is_file()

        excel_path = service.export(match_result.groups, tmp_path / "payment_groups.xlsx")
        wb = openpyxl.load_workbook(excel_path)
        sheet = wb["PAYMENT_CASE"]
        assert sheet.max_row == 2  # header + 1 group
