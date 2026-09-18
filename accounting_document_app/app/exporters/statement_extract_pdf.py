"""Sinh PDF "trích xuất giao dịch từ sao kê" khi không có phiếu ngân hàng gốc.

§I yêu cầu nghiệp vụ: khi một dòng sao kê đã khớp được vào một payment group
nhưng KHÔNG có ``VPBANK_DEBIT_NOTE``/``VIETINBANK_DEBIT_ADVICE`` vật lý tương
ứng, tool có thể tạo một PDF hỗ trợ để ``PaymentGroupOrganizer`` có gì đó
copy vào folder — nhưng file này TUYỆT ĐỐI không được trông giống chứng từ
ngân hàng gốc: không dùng logo ngân hàng, PHẢI ghi rõ đây là bản tự sinh.

Nếu ĐÃ có phiếu ngân hàng gốc thì không bao giờ gọi module này — organizer
luôn ưu tiên file gốc.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pymupdf

from app.core.bank_statement_parser import BankTransaction
from app.utils.date_utils import format_display

__all__ = ["generate_statement_extract_pdf"]

logger = logging.getLogger(__name__)

_FONT_PATH = Path(__file__).resolve().parent.parent.parent / "assets" / "fonts" / "DejaVuSans.ttf"

_DISCLAIMER = (
    "TRÍCH XUẤT GIAO DỊCH TỪ SAO KÊ",
    "TỰ ĐỘNG TẠO BỞI ACCOUNTING DOCUMENT TOOL",
    "KHÔNG PHẢI CHỨNG TỪ NGÂN HÀNG GỐC",
)


def generate_statement_extract_pdf(transaction: BankTransaction, dest_path: Path) -> Path:
    """Ghi một PDF một trang trình bày lại một dòng sao kê đã parse.

    Args:
        transaction: Giao dịch đã parse từ sao kê.
        dest_path: Đường dẫn ghi file — thư mục cha được tạo nếu chưa có.

    Returns:
        ``dest_path`` sau khi ghi xong.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page()

    def line(y: float, text: str, *, size: float = 11) -> float:
        kwargs = {"fontsize": size}
        if _FONT_PATH.is_file():
            kwargs["fontname"] = "dejavu"
            kwargs["fontfile"] = str(_FONT_PATH)
        else:  # pragma: no cover - chỉ xảy ra nếu asset font bị thiếu khỏi bundle
            logger.warning("Không tìm thấy font %s — chữ có dấu có thể hiển thị sai", _FONT_PATH)
        page.insert_text((56, y), text, **kwargs)
        return y + size * 1.8

    y = 60.0
    for text in _DISCLAIMER:
        y = line(y, text, size=13)
    y += 16

    amount = transaction.debit_amount if transaction.debit_amount is not None else transaction.credit_amount
    rows = (
        ("Ngày giao dịch", format_display(transaction.value_date)),
        ("Giờ giao dịch", transaction.transaction_time or "(không rõ)"),
        ("Mã giao dịch", transaction.transaction_id or "(không rõ)"),
        ("Số tiền", f"{amount:,}".replace(",", ".") if amount is not None else "(không rõ)"),
        ("Loại tiền", "VND"),
        ("Diễn giải", transaction.transaction_detail or ""),
        ("Facebook reference", transaction.facebook_reference or "(không có)"),
        ("File sao kê nguồn", transaction.source_pdf.name if transaction.source_pdf else "(không rõ)"),
        ("Trang nguồn", str(transaction.source_page)),
    )
    for label, value in rows:
        y = line(y, f"{label}: {value}")

    doc.save(dest_path)
    doc.close()
    logger.debug("Đã sinh PDF trích xuất sao kê: %s", dest_path)
    return dest_path
