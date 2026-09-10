"""Shared helpers for all doc-type extractors.

Design principle (per spec): never assume a fixed text position.
- `find_labeled_value` locates a label anywhere in the text (VN or EN
  variant) and returns whatever follows it — same line first, then the
  next non-empty line(s) — because different PDF generators lay label
  and value out differently.
- `regex_first_match` / `regex_all_matches` are for values identified by
  their own shape (e.g. a bank FT-code) rather than by a nearby label —
  more robust when a PDF's table layout scrambles reading order.
- `normalize_amount` / `normalize_date` / `normalize_tax_code` centralize
  the messy real-world formatting differences seen across sources
  (comma vs dot thousands separators, VN long-form dates, etc).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from dateutil import parser as dateutil_parser

_VN_MONTHS_RE = re.compile(
    r"(?:(?P<h>\d{1,2}):(?P<mi>\d{2})\s+)?"
    r"(?:ngày\s+)?(?P<d>\d{1,2})\s+tháng\s+(?P<mo>\d{1,2})[,\s]+(?:năm\s+)?(?P<y>\d{4})",
    re.IGNORECASE,
)
_DMY_SLASH_RE = re.compile(r"\b(?P<d>\d{1,2})/(?P<mo>\d{1,2})/(?P<y>\d{4})\b")
_ISO_RE = re.compile(r"\b(?P<y>\d{4})-(?P<mo>\d{1,2})-(?P<d>\d{1,2})\b")


def find_labeled_value(text: str, labels: list[str], max_lookahead: int = 2) -> Optional[str]:
    """Find the value that follows any of `labels` in `text`.

    Tries longest label first (so "Mã số thuế (Tax code)" is preferred
    over a looser "Tax code" if both are configured). Returns the text
    remaining on the same line after the label, or — if that's empty —
    the next non-empty line(s) up to `max_lookahead` lines away.
    """
    if not text or not labels:
        return None
    lines = [l.strip() for l in text.splitlines()]

    for label in sorted(labels, key=len, reverse=True):
        label_l = label.lower()
        for i, line in enumerate(lines):
            idx = line.lower().find(label_l)
            if idx == -1:
                continue
            remainder = line[idx + len(label):].strip(" :\t-")
            if remainder:
                return remainder
            for j in range(i + 1, min(i + 1 + max_lookahead, len(lines))):
                candidate = lines[j].strip()
                if candidate:
                    return candidate
    return None


def regex_first_match(text: str, pattern: str, group: int = 1, flags=re.IGNORECASE) -> Optional[str]:
    m = re.search(pattern, text, flags)
    if not m:
        return None
    try:
        return m.group(group)
    except IndexError:
        return m.group(0)


def regex_all_matches(text: str, pattern: str, group: int = 1, flags=re.IGNORECASE) -> list[str]:
    out = []
    for m in re.finditer(pattern, text, flags):
        try:
            out.append(m.group(group))
        except IndexError:
            out.append(m.group(0))
    return out


def normalize_amount(raw: Optional[str], currency: Optional[str] = "VND") -> Optional[Decimal]:
    """Parse a money string into a Decimal, tolerant of mixed separator
    conventions seen across sources (e.g. "63.337 ₫" vs "97,079 VND").

    VND is assumed to have no fractional subunit in practice, so for VND
    both '.' and ',' are treated purely as thousands grouping. For other
    currencies, the last separator (if both appear) is assumed decimal.
    """
    if raw is None:
        return None
    s = re.sub(r"[^\d.,\-]", "", raw.strip())
    if not s or not re.search(r"\d", s):
        return None

    currency_u = (currency or "VND").upper()
    is_vnd = currency_u in ("VND", "VNĐ", "DONG", "Đ", "")

    try:
        if is_vnd:
            s = s.replace(".", "").replace(",", "")
            return Decimal(s)
        if "," in s and "." in s:
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:
            s = s.replace(",", "")
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def normalize_date(raw: Optional[str]) -> Optional[date]:
    """Best-effort date parsing across the formats observed in real
    documents: ISO (XML), dd/mm/yyyy, and VN long form with/without time
    ("18:00 24 tháng 7, 2026" / "ngày 24 tháng 07 năm 2026")."""
    if not raw:
        return None
    raw = raw.strip()

    m = _ISO_RE.search(raw)
    if m:
        try:
            return date(int(m["y"]), int(m["mo"]), int(m["d"]))
        except ValueError:
            pass

    m = _VN_MONTHS_RE.search(raw)
    if m:
        try:
            return date(int(m["y"]), int(m["mo"]), int(m["d"]))
        except ValueError:
            pass

    m = _DMY_SLASH_RE.search(raw)
    if m:
        try:
            return date(int(m["y"]), int(m["mo"]), int(m["d"]))
        except ValueError:
            pass

    try:
        return dateutil_parser.parse(raw, dayfirst=True, fuzzy=True).date()
    except (ValueError, OverflowError):
        return None


_TAX_CODE_CLEAN_RE = re.compile(r"[^0-9\-]")
_TAX_CODE_VALID_RE = re.compile(r"^\d{10}(-\d{3})?$")


def normalize_tax_code(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    cleaned = _TAX_CODE_CLEAN_RE.sub("", raw.strip())
    cleaned = cleaned.strip("-")
    return cleaned or None


def clean_code(raw: Optional[str]) -> Optional[str]:
    """Strip ALL whitespace from a short alnum code. PDF text extraction
    occasionally inserts spurious spaces mid-token from font kerning
    (observed even with legitimate PDFs), so any reference/transaction
    code should be normalized this way before use as a matching key."""
    if raw is None:
        return None
    cleaned = re.sub(r"\s+", "", raw)
    return cleaned or None


def is_standard_vn_tax_code(code: Optional[str]) -> bool:
    """Standard VN MST shape: 10 digits, optionally + '-' + 3 digits for a
    dependent unit. Foreign-contractor codes (e.g. Meta's "01-1038264-0")
    intentionally do NOT match this — validation treats those as a
    WARNING rather than FAIL (see validation_rules.yaml)."""
    if not code:
        return False
    return bool(_TAX_CODE_VALID_RE.match(code))
