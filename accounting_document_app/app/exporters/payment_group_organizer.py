"""Sắp xếp PDF theo Facebook Payment Group — §J yêu cầu nghiệp vụ.

Một ``FacebookPaymentGroup`` = một thư mục::

    OUTPUT/
        FB_<reference>_<ngày>/
            00_FULL_DOCUMENT_SET.pdf   (gộp, tuỳ chọn — xem create_merged)
            01_Facebook_Bill.pdf
            02_Main_Debit_Advice.pdf (hoặc VPBank_Debit_Note.pdf)
            03_Bank_Fee_01.pdf
            04_Bank_Fee_02.pdf
            05_Bank_Statement_Extract.pdf   (tự sinh — chỉ khi KHÔNG có
                                              phiếu ngân hàng gốc, xem §I)
            _manifest.txt
        NEEDS_REVIEW/
            FB_.../...

Thứ tự ưu tiên đúng §J: Facebook Bill (1) -> thanh toán chính (2) -> phí
(3) -> sao kê/hỗ trợ (4) -> khác (5).

CHỈ ``copy_preserving`` (dựa trên ``shutil.copy2``) — không bao giờ sửa,
xoá hay di chuyển file gốc, giống hệt nguyên tắc của ``PdfOrganizer``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from app.exporters.statement_extract_pdf import generate_statement_extract_pdf
from app.models.enums import DocumentType, PaymentGroupStatus
from app.models.facebook_payment_group import FacebookPaymentGroup
from app.utils.file_utils import copy_preserving, safe_folder_name, unique_path

__all__ = ["PaymentGroupOrganizeResult", "PaymentGroupOrganizer"]

logger = logging.getLogger(__name__)


@dataclass
class PaymentGroupOrganizeResult:
    """Kết quả một lượt sắp xếp payment group."""

    group_folders: dict[str, Path] = field(default_factory=dict)
    copied_files: int = 0
    generated_extracts: int = 0
    merged_files: int = 0
    errors: list[str] = field(default_factory=list)


class PaymentGroupOrganizer:
    """Copy PDF gốc vào thư mục OUTPUT theo từng payment group.

    Args:
        output_root: Thư mục gốc để tạo cây OUTPUT.
        create_merged: Có ghi thêm ``00_FULL_DOCUMENT_SET.pdf`` (gộp toàn bộ
            file của group bằng ``pymupdf.insert_pdf``) khi group có từ 2
            file trở lên hay không.
    """

    def __init__(self, output_root: Path | str, *, create_merged: bool = True) -> None:
        self._output_root = Path(output_root)
        self._generate_dir = self._output_root / "_GENERATED"
        self._create_merged = create_merged

    def organize(self, groups: list[FacebookPaymentGroup]) -> PaymentGroupOrganizeResult:
        """Sắp xếp toàn bộ payment group của một lô.

        Args:
            groups: Kết quả từ ``PaymentGroupMatcher.match()``.

        Returns:
            ``PaymentGroupOrganizeResult``.
        """
        result = PaymentGroupOrganizeResult()
        for group in groups:
            self._organize_one(group, result)
        return result

    # -------------------------------------------------------------- nội bộ

    def _organize_one(self, group: FacebookPaymentGroup, result: PaymentGroupOrganizeResult) -> None:
        entries = self._collect_entries(group, result)
        if not entries:
            return

        target_dir = self._target_dir(group)
        entries.sort(key=lambda e: e[0])

        copied_paths: list[Path] = []
        manifest_lines = [
            f"Payment group: {group.group_code}",
            f"Facebook reference: {group.facebook_reference or '(không có)'}",
            f"Trạng thái: {group.status.value}",
            f"Lý do: {group.reason}",
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
        result.group_folders[group.group_code] = target_dir

        if self._create_merged and len(copied_paths) > 1:
            self._write_merged(group, copied_paths, target_dir, result)

    def _collect_entries(
        self, group: FacebookPaymentGroup, result: PaymentGroupOrganizeResult
    ) -> list[tuple[int, str, Path]]:
        entries: list[tuple[int, str, Path]] = []

        if group.facebook_bill is not None:
            entries.append((1, "Facebook_Bill", group.facebook_bill.file_path))

        if group.main_payment is not None:
            label = (
                "Main_Debit_Advice"
                if group.main_payment.document_type is DocumentType.VIETINBANK_DEBIT_ADVICE
                else "VPBank_Debit_Note"
            )
            entries.append((2, label, group.main_payment.file_path))
        elif group.statement_rows:
            # §I: không có phiếu ngân hàng gốc nhưng đã khớp được dòng sao
            # kê -> sinh PDF trích xuất RÕ RÀNG không phải chứng từ gốc.
            txn = group.statement_rows[0]
            gen_name = f"VPBANK_TRANSACTION_EXTRACT_{txn.transaction_id or group.group_code}.pdf"
            gen_dest = unique_path(self._generate_dir / safe_folder_name(gen_name))
            try:
                generate_statement_extract_pdf(txn, gen_dest)
                entries.append((2, "Bank_Statement_Extract", gen_dest))
                result.generated_extracts += 1
            except OSError:
                logger.exception("Không sinh được PDF trích xuất sao kê cho %s", group.group_code)
                result.errors.append(f"Không sinh được PDF trích xuất sao kê cho {group.group_code}")

        fee_count = len(group.fees)
        for index, fee in enumerate(group.fees, start=1):
            suffix = f"_{index:02d}" if fee_count > 1 else ""
            entries.append((3, f"Bank_Fee{suffix}", fee.file_path))

        support_count = len(group.supporting)
        for index, doc in enumerate(group.supporting, start=1):
            suffix = f"_{index:02d}" if support_count > 1 else ""
            entries.append((5, f"Other_Supporting{suffix}", doc.file_path))

        return entries

    def _target_dir(self, group: FacebookPaymentGroup) -> Path:
        folder_name = safe_folder_name(group.group_code)
        base = self._output_root
        if group.status in (PaymentGroupStatus.NEEDS_REVIEW, PaymentGroupStatus.UNMATCHED):
            base = self._output_root / "NEEDS_REVIEW"
        return base / folder_name

    def _write_merged(
        self,
        group: FacebookPaymentGroup,
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
            logger.exception("Không gộp được file cho payment group %s", group.group_code)
            result.errors.append(f"Không gộp được file cho {group.group_code}")

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
