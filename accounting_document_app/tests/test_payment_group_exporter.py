"""Test xuất Excel cho Payment Case — bank-agnostic."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import openpyxl

from app.core.bank_statement_parser import BankTransaction
from app.exporters.payment_group_exporter import PaymentGroupExporter
from app.models.enums import DocumentType, PaymentGroupStatus
from app.models.payment_case import PaymentCase
from matching_helpers import make_doc


def _read_row(out):
    wb = openpyxl.load_workbook(out)
    sheet = wb["PAYMENT_CASE"]
    header = [c.value for c in sheet[1]]
    return {h: sheet.cell(row=2, column=i + 1).value for i, h in enumerate(header)}


class TestXuatExcel:
    def test_mot_case_mot_dong(self, tmp_path):
        bill = make_doc(
            DocumentType.META_INVOICE,
            reference_number="ABCD1234EF",
            transaction_id="123-456",
            invoice_number="FBADS-1-1",
            total_amount=Decimal("2530672"),
            document_date=date(2026, 8, 1),
        )
        main = make_doc(
            DocumentType.VPBANK_DEBIT_NOTE,
            meta_reference="ABCD1234EF",
            transaction_code="FT100000001",
            total_amount=Decimal("2558510"),
            card_last4="1234",
        )
        case = PaymentCase(
            group_code="2026-08-01_ABCD1234EF",
            reference="ABCD1234EF",
            transaction_date=date(2026, 8, 1),
            meta_bill=bill,
            main_payment=main,
            status=PaymentGroupStatus.MATCHED_HIGH,
            confidence="HIGH",
            reason="Reference khớp tuyệt đối: ABCD1234EF",
        )

        out = tmp_path / "payment_case.xlsx"
        PaymentGroupExporter().export([case], out)
        row = _read_row(out)

        assert row["Reference"] == "ABCD1234EF"
        assert row["Meta_Paid_Amount"] == 2530672
        assert row["Bank"] == "VPBANK"
        assert row["Bank_Transaction_ID"] == "FT100000001"
        assert row["Bank_Main_Amount"] == 2558510
        assert row["Card_Last4"] == "1234"
        assert row["Match_Status"] == "MATCHED_HIGH"
        assert not row["Bank_Mismatch"]  # "" ghi ra Excel đọc lại thành None
        assert "ABCD1234EF" in row["Match_Reason"]

    def test_tong_phi_tinh_dung_khi_co_nhieu_fee(self, tmp_path):
        main = make_doc(DocumentType.VIETINBANK_DEBIT_ADVICE, transaction_number="9001", total_amount=Decimal("100"))
        fee1 = make_doc(DocumentType.VIETINBANK_DEBIT_ADVICE, transaction_number="9000", total_amount=Decimal("10"))
        fee2 = make_doc(DocumentType.VIETINBANK_DEBIT_ADVICE, transaction_number="8999", total_amount=Decimal("5"))
        case = PaymentCase(
            group_code="X", main_payment=main, fees=[fee1, fee2],
            status=PaymentGroupStatus.MATCHED_HIGH,
        )
        out = tmp_path / "payment_case.xlsx"
        PaymentGroupExporter().export([case], out)
        row = _read_row(out)

        assert row["Bank_Fee_Amount"] == 15
        assert row["Bank_Total_Debit"] == 115  # main + hai fee
        assert row["Bank"] == "VIETINBANK"

    def test_khong_co_phieu_ngan_hang_goc_ghi_ro_trich_xuat_tu_sao_ke(self, tmp_path):
        bill = make_doc(DocumentType.META_INVOICE, reference_number="ABCD1234EF")
        row_data = BankTransaction(
            stt=1, transaction_id="FT1", value_date=date(2026, 8, 1), transaction_time="10:00",
            debit_amount=Decimal("1"), credit_amount=None, transaction_detail="x",
            running_balance=Decimal("1"), facebook_reference="ABCD1234EF",
            source_pdf=None, source_page=1,
        )
        case = PaymentCase(
            group_code="2026-08-01_ABCD1234EF", meta_bill=bill, main_payment=None,
            statement_rows=[row_data], status=PaymentGroupStatus.MATCHED,
        )
        out = tmp_path / "payment_case.xlsx"
        PaymentGroupExporter().export([case], out)
        row = _read_row(out)

        assert row["Main_Bank_File"] == "(trích xuất từ sao kê)"

    def test_vat_invoice_duoc_ghi_dung_cot(self, tmp_path):
        vat = make_doc(
            DocumentType.VPBANK_VAT_INVOICE, invoice_number="00100001", total_amount=Decimal("2200")
        )
        case = PaymentCase(group_code="X", vat_invoice=vat, status=PaymentGroupStatus.MATCHED)
        out = tmp_path / "payment_case.xlsx"
        PaymentGroupExporter().export([case], out)
        row = _read_row(out)

        assert row["VAT_Invoice_Number"] == "00100001"
        assert row["VAT_Amount"] == 2200

    def test_bank_mismatch_duoc_ghi_x(self, tmp_path):
        bill = make_doc(DocumentType.META_INVOICE, reference_number="ABCD1234EF", card_last4="1234")
        main = make_doc(DocumentType.VIETINBANK_DEBIT_ADVICE, transaction_number="1", total_amount=Decimal("1"))
        case = PaymentCase(
            group_code="X", reference="ABCD1234EF", meta_bill=bill, main_payment=main,
            expected_bank="VPBANK", status=PaymentGroupStatus.NEEDS_REVIEW,
        )
        out = tmp_path / "payment_case.xlsx"
        PaymentGroupExporter().export([case], out)
        row = _read_row(out)

        assert row["Expected_Bank"] == "VPBANK"
        assert row["Bank"] == "VIETINBANK"
        assert row["Bank_Mismatch"] == "x"
