"""Sắp xếp PDF theo Payment Case — bank-agnostic (VPBank/VietinBank).

Một ``PaymentCase`` = một thư mục::

    OUTPUT/
        <ngày>_<reference>/
            00_FULL_DOCUMENT_SET.pdf   (gộp, tuỳ chọn — xem create_merged)
            01_Meta_Invoice.pdf
            02_<Ngân_hàng>_Main_Debit.pdf   (vd. VPBank / VietinBank)
            03_<Ngân_hàng>_Bank_Fee.pdf
            04_VAT_Invoice.pdf
            05_Bank_Statement_Extract.pdf   (tự sinh — chỉ khi KHÔNG có
                                              phiếu ngân hàng gốc)
            _manifest.txt
        NEEDS_REVIEW/
            <ngày>_<reference>/...

Thứ tự ưu tiên: Meta Bill (1) -> thanh toán chính (2) -> phí (3) -> hoá đơn
GTGT (4) -> sao kê/hỗ trợ (5) -> khác (6). Tên file lấy ĐÚNG ngân hàng thực
tế qua ``bank_name_of()`` — không bao giờ hard-code "VPBank" cho mọi
trường hợp.

CHỈ ``copy_preserving`` (dựa trên ``shutil.copy2``) — không bao giờ sửa,
xoá hay di chuyển file gốc, giống hệt nguyên tắc của ``PdfOrganizer``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from app.exporters.statement_extract_pdf import generate_statement_extract_pdf
from app.matching.payment_group_matcher import bank_name_of
from app.models.enums import PaymentGroupStatus
from app.models.payment_case import PaymentCase
from app.utils.file_utils import copy_preserving, safe_folder_name, unique_path

__all__ = ["PaymentGroupOrganizeResult", "PaymentGroupOrganizer"]

logger = logging.getLogger(__name__)

#: Tên hiển thị (title-case) cho từng mã ngân hàng nội bộ — chỉ dùng để đặt
#: tên file cho dễ đọc, KHÔNG ảnh hưởng logic ghép/so khớp.
_BANK_DISPLAY_NAME = {"VPBANK": "VPBank", "VIETINBANK": "VietinBank"}


def _bank_display_name(bank: str | None) -> str:
    return _BANK_DISPLAY_NAME.get(bank or "", bank or "Bank")


@dataclass
class PaymentGroupOrganizeResult:
    """Kết quả một lượt sắp xếp payment case."""

    group_folders: dict[str, Path] = field(default_factory=dict)
    copied_files: int = 0
    generated_extracts: int = 0
    merged_files: int = 0
    errors: list[str] = field(default_factory=list)


class PaymentGroupOrganizer:
    """Copy PDF gốc vào thư mục OUTPUT theo từng payment case.

    Args:
        output_root: Thư mục gốc để tạo cây OUTPUT.
        create_merged: Có ghi thêm ``00_FULL_DOCUMENT_SET.pdf`` (gộp toàn bộ
            file của case bằng ``pymupdf.insert_pdf``) khi case có từ 2 file
            trở lên hay không.
    """

    def __init__(self, output_root: Path | str, *, create_merged: bool = True) -> None:
        self._output_root = Path(output_root)
        self._generate_dir = self._output_root / "_GENERATED"
        self._create_merged = create_merged

    def organize(self, groups: list[PaymentCase]) -> PaymentGroupOrganizeResult:
        """Sắp xếp toàn bộ payment case của một lô.

        Args:
            groups: Kết quả từ ``PaymentGroupMatcher.match()``.

        Returns:
            ``PaymentGroupOrganizeResult``.
        """
        result = PaymentGroupOrganizeResult()
        for case in groups:
            self._organize_one(case, result)
        return result

    # -------------------------------------------------------------- nội bộ

    def _organize_one(self, case: PaymentCase, result: PaymentGroupOrganizeResult) -> None:
        entries = self._collect_entries(case, result)
        if not entries:
            return

        target_dir = self._target_dir(case)
        entries.sort(key=lambda e: e[0])

        copied_paths: list[Path] = []
        manifest_lines = [
            f"Payment case: {case.group_code}",
            f"Reference: {case.reference or '(không có)'}",
            f"Ngân hàng: {case.bank_name or '(không rõ)'} (kỳ vọng: {case.expected_bank or '(không có thẻ)'})",
            f"Trạng thái: {case.status.value}",
            f"Lý do: {case.reason}",
            "",
        ]
        for index, (_, label, source) in enumerate(entries, start=1):
            dest = target_dir / f"{index:02d}_{label}.pdf"
            try:
                written = copy_preserving(source, dest)
            except OSError as exc:
                message = f"Không copy được {source} -> {dest}: {exc}"
                logger.error(message)
                result.errors.append(message)
                continue
            copied_paths.append(written)
            result.copied_files += 1
            manifest_lines.append(f"{written.name}  <-  {source}")

        if not copied_paths:
            return

        self._write_text(target_dir / "_manifest.txt", "\n".join(manifest_lines))
        result.group_folders[case.group_code] = target_dir

        if self._create_merged and len(copied_paths) > 1:
            self._write_merged(case, copied_paths, target_dir, result)

    def _collect_entries(
        self, case: PaymentCase, result: PaymentGroupOrganizeResult
    ) -> list[tuple[int, str, Path]]:
        entries: list[tuple[int, str, Path]] = []

        if case.meta_bill is not None:
            entries.append((1, "Meta_Invoice", case.meta_bill.file_path))

        if case.main_payment is not None:
            bank_label = _bank_display_name(bank_name_of(case.main_payment))
            entries.append((2, f"{bank_label}_Main_Debit", case.main_payment.file_path))
        elif case.statement_rows:
            # Không có phiếu ngân hàng gốc nhưng đã khớp được dòng sao kê ->
            # sinh PDF trích xuất RÕ RÀNG không phải chứng từ gốc.
            txn = case.statement_rows[0]
            gen_name = f"VPBANK_TRANSACTION_EXTRACT_{txn.transaction_id or case.group_code}.pdf"
            gen_dest = unique_path(self._generate_dir / safe_folder_name(gen_name))
            try:
                generate_statement_extract_pdf(txn, gen_dest)
                entries.append((2, "Bank_Statement_Extract", gen_dest))
                result.generated_extracts += 1
            except OSError:
                logger.exception("Không sinh được PDF trích xuất sao kê cho %s", case.group_code)
                result.errors.append(f"Không sinh được PDF trích xuất sao kê cho {case.group_code}")

        fee_count = len(case.fees)
        for index, fee in enumerate(case.fees, start=1):
            bank_label = _bank_display_name(bank_name_of(fee))
            suffix = f"_{index:02d}" if fee_count > 1 else ""
            entries.append((3, f"{bank_label}_Bank_Fee{suffix}", fee.file_path))

        if case.vat_invoice is not None:
            entries.append((4, "VAT_Invoice", case.vat_invoice.file_path))

        support_count = len(case.supporting)
        for index, doc in enumerate(case.supporting, start=1):
            suffix = f"_{index:02d}" if support_count > 1 else ""
            entries.append((6, f"Other_Supporting{suffix}", doc.file_path))

        return entries

    def _target_dir(self, case: PaymentCase) -> Path:
        folder_name = safe_folder_name(case.group_code)
        base = self._output_root
        if case.status in (PaymentGroupStatus.NEEDS_REVIEW, PaymentGroupStatus.UNMATCHED):
            base = self._output_root / "NEEDS_REVIEW"
        return base / folder_name

    def _write_merged(
        self,
        case: PaymentCase,
        copied_paths: list[Path],
        target_dir: Path,
        result: PaymentGroupOrganizeResult,
    ) -> None:
        merged_dest = target_dir / "00_FULL_DOCUMENT_SET.pdf"
        try:
            merged = pymupdf.open()
            try:
                for path in copied_paths:
                    with pymupdf.open(path) as src:
                        merged.insert_pdf(src)
                merged.save(merged_dest)
            finally:
                merged.close()
            result.merged_files += 1
        except Exception:  # noqa: BLE001 - gộp lỗi không được làm mất các file đã copy
            logger.exception("Không gộp được file cho payment case %s", case.group_code)
            result.errors.append(f"Không gộp được file cho {case.group_code}")

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
