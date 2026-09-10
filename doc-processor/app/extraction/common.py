"""Small helpers shared by 2+ extractors but not general enough for base.py."""
from __future__ import annotations

import re
from typing import Optional


def detect_currency(text: str) -> str:
    """Very lightweight currency sniff: VND unless a foreign symbol/code
    clearly dominates. Defaults to VND since that's the norm for all
    three document types in this workflow."""
    if re.search(r"\bUSD\b|\$\s?\d", text):
        if not re.search(r"₫|VND|VNĐ", text):
            return "USD"
    return "VND"


def leading_number(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"[\d][\d.,]*", text)
    return m.group(0) if m else None


def percent_in(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"(\d+)\s*%", text)
    return f"{m.group(1)}%" if m else None
