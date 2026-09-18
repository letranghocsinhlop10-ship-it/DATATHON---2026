"""Ánh xạ "4 số cuối thẻ -> ngân hàng phát hành" — nạp từ ``config/bank_mapping.yaml``.

Dùng làm tín hiệu ``expected_bank`` (LEVEL 2, sau exact reference) trong
``app/matching/payment_group_matcher.py``: Facebook/Meta Bill ghi 4 số cuối
thẻ, ta suy ra NGÂN HÀNG PHÁT HÀNH kỳ vọng, rồi đối chiếu với ngân hàng thực
tế của chứng từ đã khớp reference. Lệch nhau KHÔNG được tự loại liên kết —
chỉ hạ xuống ``NEEDS_REVIEW`` để người dùng xem lại.

Module riêng, không đi qua ``app/config_loader.py`` (giống cách
``bank_statement_parser.py`` tự nạp ``bank_statement_rules.yaml``) — cấu
hình có hình dạng khác hẳn (không phải rule trích xuất/phân loại).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

__all__ = ["BankMappingConfig", "load_bank_mapping_config"]

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "bank_mapping.yaml"


@dataclass(frozen=True)
class BankMappingConfig:
    """Ánh xạ 4 số cuối thẻ -> tên ngân hàng (đã chuẩn hoá uppercase)."""

    card_last4_to_bank: dict[str, str]

    def expected_bank_for(self, card_last4: str | None) -> str | None:
        """Ngân hàng kỳ vọng phát hành thẻ, ``None`` nếu không có ánh xạ."""
        if not card_last4:
            return None
        return self.card_last4_to_bank.get(card_last4.strip())


def load_bank_mapping_config(path: Path | None = None) -> BankMappingConfig:
    """Nạp ``config/bank_mapping.yaml``.

    Args:
        path: Đường dẫn file; mặc định ``config/bank_mapping.yaml``.

    Returns:
        ``BankMappingConfig``. File thiếu/rỗng -> ánh xạ rỗng (không lỗi),
        vì đây là tín hiệu PHỤ, thiếu vẫn phải chạy được, không chặn cả app.
    """
    path = path or _DEFAULT_PATH
    if not path.is_file():
        logger.warning("Không tìm thấy %s — bỏ qua tín hiệu expected_bank", path)
        return BankMappingConfig(card_last4_to_bank={})

    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = data.get("card_last4_to_bank") or {}
    mapping = {str(card).strip(): str(bank).strip().upper() for card, bank in raw.items()}
    return BankMappingConfig(card_last4_to_bank=mapping)
