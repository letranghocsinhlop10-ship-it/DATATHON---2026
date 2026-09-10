"""Parser for the Vietnamese e-invoice XML sidecar.

Vietnamese e-invoices (all providers use a similar shape derived from
Circular 78 / Decree 123) ship the signed structured data as XML; the
PDF next to it is only a human-readable rendering. When the XML is
present we trust it for the "core" invoice fields — it's far more
reliable than regex-scraping a PDF table whose visual layout doesn't
always match its text extraction order (see vat_invoice_extractor.py).

The two fields the workflow needs that are NOT part of the XML (in the
sample seen) are the bank's own "Số tham chiếu" and "Nội dung thanh
toán" — those still come from the PDF text.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

from app.extraction.base import normalize_amount, normalize_date, normalize_tax_code


def _text(el: Optional[ET.Element]) -> Optional[str]:
    if el is None or el.text is None:
        return None
    t = el.text.strip()
    return t or None


def parse_vat_invoice_xml(xml_path: str | Path) -> dict:
    """Returns a plain dict of normalized fields; missing tags -> None.
    Never raises for a well-formed-but-unexpected-schema XML — callers
    should treat an empty dict as "XML parse didn't help, fall back to PDF".
    """
    try:
        tree = ET.parse(str(xml_path))
    except ET.ParseError:
        return {}
    root = tree.getroot()

    # Namespaces vary a lot by provider; search by local tag name so this
    # works across the common variants without needing per-provider config.
    def find(*tag_path: str) -> Optional[ET.Element]:
        node = root
        for tag in tag_path:
            found = None
            for child in node.iter():
                if child.tag.split("}")[-1] == tag:
                    found = child
                    break
            if found is None:
                return None
            node = found
        return node

    currency = _text(find("DVTTe")) or "VND"

    khhdon = _text(find("KHHDon"))
    shdon = _text(find("SHDon"))
    invoice_number = None
    if khhdon and shdon:
        invoice_number = f"{khhdon}-{shdon}"
    elif shdon:
        invoice_number = shdon

    return {
        "invoice_number": invoice_number,
        "invoice_serial": khhdon,
        "invoice_no_raw": shdon,
        "invoice_date": normalize_date(_text(find("NLap"))),
        "seller": _text(find("NBan", "Ten")),
        "seller_tax_code": normalize_tax_code(_text(find("NBan", "MST"))),
        "buyer": _text(find("NMua", "Ten")),
        "buyer_tax_code": normalize_tax_code(_text(find("NMua", "MST"))),
        "bank_info": _text(find("NMua", "STKNHang")),
        "currency": currency,
        "amount_before_vat": normalize_amount(_text(find("TgTCThue")), currency),
        "vat_amount": normalize_amount(_text(find("TgTThue")), currency),
        "total_amount": normalize_amount(_text(find("TgTTTBSo")), currency),
        "vat_rate": _text(find("TSuat")),
    }
