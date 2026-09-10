"""Tiny shared helpers for writing readable .xlsx sheets with openpyxl."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet


def cell_value(v):
    """openpyxl can't write Decimal/date-that-isn't-datetime.date cleanly
    in all cases and can't write arbitrary enums/None at all — normalize."""
    if v is None:
        return ""
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v
    if hasattr(v, "value"):  # Enum
        return v.value
    return v


def write_table(ws: Worksheet, headers: list[str], rows: list[list]) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    for row in rows:
        ws.append([cell_value(v) for v in row])
    _autosize(ws, headers)


def _autosize(ws: Worksheet, headers: list[str], max_width: int = 45) -> None:
    for i, header in enumerate(headers, start=1):
        col_letter = ws.cell(row=1, column=i).column_letter
        longest = len(str(header))
        for row in ws.iter_rows(min_row=2, min_col=i, max_col=i):
            val = row[0].value
            if val is not None:
                longest = max(longest, len(str(val)))
        ws.column_dimensions[col_letter].width = min(max_width, max(10, longest + 2))
