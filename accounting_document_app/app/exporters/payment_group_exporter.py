"""Xuất Excel cho Facebook Payment Group — §K yêu cầu nghiệp vụ.

Một sheet riêng (KHÔNG đụng vào ``ExcelExporter``/4 sheet MISA hiện có —
đây là báo cáo bổ sung cho luồng ghép theo Facebook payment group, độc lập
với luồng dossier META/DEBIT/VAT gốc). Mỗi ``FacebookPaymentGroup`` = một
dòng, đủ để kế toán đối chiếu KHÔNG cần mở lại từng PDF.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.matching.payment_group_matcher import bank_doc_txn_id
from app.models.document import Document
from app.models.enums import DocumentType
from app.models.facebook_payment_group import FacebookPaymentGroup

__all__ = ["PaymentGroupExporter"]

logger = logging.getLogger(__name__)

_HEADER_FILL = PatternFill("solid", fgColor="1F2937")
_HEADER_FONT = Font(color="FFFFFF", bold=True, size=10)
_SHEET_NAME = "FACEBOOK_PAYMENT_GROUP"

_HEADERS = [
    "Group_Code",
    "Facebook_Reference",
    "Facebook_Transaction_ID",
    "Facebook_Invoice_Number",
    "Facebook_Paid_Amount",
    "Facebook_Payment_Date",
    "Bank",
    "Bank_Transaction_ID",
    "Bank_Main_Amount",
    "Bank_Fee_Amount",
    "Bank_Total_Debit",
    "Bank_Transaction_Date",
    "Card_Last4",
    "Facebook_Bill_File",
    "Main_Bank_File",
    "Fee_Bank_Files",
    "Statement_Source",
    "Statement_Page",
    "Match_Status",
    "Match_Confidence",
    "Match_Reason",
]


def _bank_name(doc: Document | None) -> str | None:
    if doc is None:
        return None
    return "VIETINBANK" if doc.document_type is DocumentType.VIETINBANK_DEBIT_ADVICE else "VPBANK"


def _num(value: Decimal | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)


class PaymentGroupExporter:
    """Dựng workbook 1 sheet từ danh sách ``FacebookPaymentGroup``."""

    def export(self, groups: list[FacebookPaymentGroup], output_path: Path | str) -> Path:
        """Xuất ``output_path`` — mỗi group một dòng.

        Args:
            groups: Kết quả từ ``PaymentGroupMatcher.match()``.
            output_path: Đường dẫn file ``.xlsx`` đích.

        Returns:
            ``output_path`` sau khi ghi xong.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        workbook = Workbook()
        workbook.remove(workbook.active)
        sheet = self._new_sheet(workbook, _SHEET_NAME, _HEADERS)

        for group in groups:
            sheet.append(self._row(group))

        self._autosize(sheet, _HEADERS)
        workbook.save(output_path)
        logger.info("Đã xuất %s: %s (%d payment group)", _SHEET_NAME, output_path, len(groups))
        return output_path

    @staticmethod
    def _row(group: FacebookPaymentGroup) -> list:
        bill = group.facebook_bill
        main = group.main_payment
        fee_amount = sum((f.total_amount for f in group.fees if f.total_amount is not None), Decimal(0))
        statement = group.statement_rows[0] if group.statement_rows else None
        main_bank_file = (
            main.file_name if main is not None else ("(trích xuất từ sao kê)" if statement else None)
        )

        return [
            group.group_code,
            group.facebook_reference,
            bill.value_of("transaction_id") if bill else None,
            bill.value_of("invoice_number") if bill else None,
            _num(bill.total_amount) if bill else None,
            bill.document_date if bill else None,
            _bank_name(main) or _bank_name(group.fees[0] if group.fees else None),
            bank_doc_txn_id(main) if main else None,
            _num(main.total_amount) if main else None,
            _num(fee_amount) if group.fees else None,
            _num(group.bank_total_debit),
            group.transaction_date,
            (main.card_last4 if main else None) or (bill.card_last4 if bill else None),
            bill.file_name if bill else None,
            main_bank_file,
            "; ".join(f.file_name for f in group.fees) or None,
            statement.source_pdf.name if statement and statement.source_pdf else None,
            statement.source_page if statement else None,
            group.status.value,
            group.confidence,
            group.reason,
        ]

    @staticmethod
    def _new_sheet(workbook: Workbook, title: str, headers: list[str]) -> Worksheet:
        sheet = workbook.create_sheet(title=title[:31])
        sheet.append(headers)
        for col_index in range(1, len(headers) + 1):
            cell = sheet.cell(row=1, column=col_index)
            cell.fill = _HEADER_FILL
            cell.font = _HEADER_FONT
            cell.alignment = Alignment(vertical="center")
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"
        return sheet

    @staticmethod
    def _autosize(sheet: Worksheet, headers: list[str], *, max_width: int = 42) -> None:
        for col_index, header in enumerate(headers, start=1):
            width = len(header) + 2
            for row_index in range(2, min(sheet.max_row, 200) + 1):
                value = sheet.cell(row=row_index, column=col_index).value
                if value is not None:
                    width = max(width, len(str(value)) + 2)
            sheet.column_dimensions[get_column_letter(col_index)].width = min(width, max_width)
