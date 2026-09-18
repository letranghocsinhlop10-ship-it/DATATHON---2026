"""Parse sao kê ngân hàng nhiều giao dịch thành từng ``BankTransaction``.

KHÁC HẲN các extractor khác trong ``app/extractors``: một file sao kê không
phải MỘT chứng từ, mà là NHIỀU giao dịch (§D yêu cầu nghiệp vụ) — nên không
dùng ``RuleEngine``/``FieldRule`` (thiết kế cho đúng một giá trị/field/chứng
từ), mà parse THEO DÒNG bằng một regex duy nhất khai báo trong
``config/bank_statement_rules.yaml`` (named groups), tương tự cách các
extractor khác được điều khiển hoàn toàn bằng YAML thay vì hard-code trong
Python.

CẢNH BÁO: dự án CHƯA có file sao kê thật để soi cấu trúc cột — xem cảnh báo
đầy đủ ở đầu ``config/bank_statement_rules.yaml``. Một dòng KHÔNG khớp
``row_pattern`` bị bỏ qua (ghi log), KHÔNG đoán để cố ép parse.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from app.core.pdf_reader import PDFReader
from app.core.text_normalizer import normalize_facebook_reference
from app.utils import date_utils
from app.utils.money_utils import MoneyFormat, parse_amount

__all__ = ["BankTransaction", "BankStatementRules", "load_bank_statement_rules", "BankStatementParser"]

logger = logging.getLogger(__name__)

_DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "bank_statement_rules.yaml"


@dataclass(frozen=True)
class BankTransaction:
    """Một giao dịch trong sao kê ngân hàng.

    Attributes:
        stt: Số thứ tự dòng trong file (1-based) — KHÔNG phải số thứ tự in
            trên sao kê (nếu có cột STT riêng, dùng ``transaction_id`` để
            đối chiếu thay vì tin vào STT).
        transaction_id: Mã giao dịch (vd. ``FT100000001``).
        value_date: Ngày giao dịch.
        transaction_time: Giờ giao dịch dạng chuỗi thô (không phải mọi sao
            kê đều có cột giờ).
        debit_amount: Số tiền ghi Nợ (tiền ra), ``None`` nếu dòng này không
            phải một khoản ghi nợ.
        credit_amount: Số tiền ghi Có (tiền vào).
        transaction_detail: Diễn giải thô của dòng.
        running_balance: Số dư sau giao dịch.
        facebook_reference: Reference Facebook/Meta bóc từ diễn giải (qua
            ``normalize_facebook_reference``), ``None`` nếu không có.
        source_pdf: File sao kê nguồn.
        source_page: Trang chứa dòng này (1-based).
    """

    stt: int
    transaction_id: str | None
    value_date: date | None
    transaction_time: str | None
    debit_amount: Decimal | None
    credit_amount: Decimal | None
    transaction_detail: str
    running_balance: Decimal | None
    facebook_reference: str | None
    source_pdf: Path
    source_page: int


@dataclass(frozen=True)
class BankStatementRules:
    """Luật parse sao kê của một ngân hàng, đã biên dịch sẵn."""

    bank: str
    row_pattern: re.Pattern[str]
    money_format: MoneyFormat


def load_bank_statement_rules(path: Path | None = None) -> dict[str, BankStatementRules]:
    """Nạp ``config/bank_statement_rules.yaml``.

    Returns:
        Ánh xạ tên ngân hàng (vd. ``"VPBANK"``) -> luật đã biên dịch.
    """
    path = path or _DEFAULT_RULES_PATH
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    result: dict[str, BankStatementRules] = {}
    for bank, cfg in (data.get("banks") or {}).items():
        money_cfg = cfg["money_format"]
        result[bank] = BankStatementRules(
            bank=bank,
            row_pattern=re.compile(cfg["row_pattern"]),
            money_format=MoneyFormat(
                thousands=str(money_cfg["thousands"]),
                decimal=str(money_cfg["decimal"]),
                currency_symbols=tuple(money_cfg.get("currency_symbols") or ()),
            ),
        )
    return result


class BankStatementParser:
    """Parse một file PDF sao kê thành danh sách ``BankTransaction``.

    Args:
        rules: Luật theo ngân hàng, mặc định nạp từ
            ``config/bank_statement_rules.yaml``.
        bank: Ngân hàng áp dụng — hiện chỉ có ``"VPBANK"``.
        reader: ``PDFReader`` tuỳ chỉnh.
    """

    def __init__(
        self,
        *,
        rules: dict[str, BankStatementRules] | None = None,
        bank: str = "VPBANK",
        reader: PDFReader | None = None,
    ) -> None:
        self._rules = rules or load_bank_statement_rules()
        if bank not in self._rules:
            raise KeyError(f"Chưa có luật parse sao kê cho ngân hàng: {bank}")
        self._rule = self._rules[bank]
        self._reader = reader or PDFReader()

    def parse(self, path: Path | str) -> list[BankTransaction]:
        """Đọc file PDF, trả về mọi dòng khớp ``row_pattern``.

        Args:
            path: File PDF sao kê.

        Returns:
            Danh sách ``BankTransaction`` theo thứ tự xuất hiện trong file.
            Dòng không khớp regex bị bỏ qua (ghi log DEBUG), không phải lỗi.
        """
        pdf_path = Path(path)
        content = self._reader.read(pdf_path)
        transactions: list[BankTransaction] = []
        stt = 0

        for page in content.pages:
            for line in page.text.splitlines():
                line = line.strip()
                if not line:
                    continue
                match = self._rule.row_pattern.search(line)
                if not match:
                    continue
                stt += 1
                transactions.append(self._build(match, stt, pdf_path, page.number))

        logger.info(
            "Parse sao kê %s (%s): %d dòng khớp trong %d trang",
            pdf_path.name, self._rule.bank, len(transactions), content.page_count,
        )
        return transactions

    def _build(self, match: re.Match[str], stt: int, source: Path, page_number: int) -> BankTransaction:
        groups = match.groupdict()

        value_date = None
        if groups.get("date"):
            try:
                value_date = date_utils.parse_dmy(groups["date"])
            except date_utils.DateParseError:
                logger.warning("%s trang %d: ngày không hợp lệ %r", source.name, page_number, groups["date"])

        debit = self._parse_optional_amount(groups.get("debit"), source, page_number)
        credit = self._parse_optional_amount(groups.get("credit"), source, page_number)
        balance = self._parse_optional_amount(groups.get("balance"), source, page_number)
        detail = (groups.get("detail") or "").strip()

        return BankTransaction(
            stt=stt,
            transaction_id=groups.get("txn_id"),
            value_date=value_date,
            transaction_time=groups.get("time"),
            debit_amount=debit,
            credit_amount=credit,
            transaction_detail=detail,
            running_balance=balance,
            facebook_reference=normalize_facebook_reference(detail),
            source_pdf=source,
            source_page=page_number,
        )

    def _parse_optional_amount(self, raw: str | None, source: Path, page_number: int) -> Decimal | None:
        if not raw:
            return None
        try:
            return parse_amount(raw, self._rule.money_format)
        except Exception:  # noqa: BLE001 - một số tiền lỗi không được làm hỏng cả dòng
            logger.warning("%s trang %d: không parse được số tiền %r", source.name, page_number, raw)
            return None
