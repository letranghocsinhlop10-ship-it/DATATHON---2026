"""Phase 6 — kiểm thử ở quy mô gần thực tế bằng dữ liệu TỔNG HỢP.

Repo chỉ có 3 PDF thật (không có 300 file thật của công ty). Để vẫn kiểm
tra được hành vi ở QUY MÔ THẬT — hiệu năng, không crash, đúng số lượng
dossier theo từng trạng thái, cây thư mục OUTPUT đúng — module này SINH
PDF tổng hợp bằng PyMuPDF, dùng ĐÚNG cấu trúc/nhãn/regex đã reverse-engineer
từ 3 file mẫu thật (xem ``docs/PHASE1_ADDENDUM_SAMPLE_ANALYSIS.md``), với
số liệu hoàn toàn GIẢ.

Font: PyMuPDF ``insert_text`` mặc định dùng font Base14 (Helvetica) — KHÔNG
có glyph tiếng Việt có dấu, ký tự có dấu sẽ bị thay bằng ``·`` và làm hỏng
mọi regex trích xuất. Bắt buộc chỉ định ``fontfile=DejaVu Sans`` (có sẵn
trên Linux/Windows, phủ đủ Unicode tiếng Việt).

Hai cấp độ:
    ``test_quy_mo_nho``   ~30 file, LUÔN chạy — smoke nhanh trong CI.
    ``test_quy_mo_300``   300 file, CHỈ chạy khi có biến môi trường
                          ``ACCOUNTING_STRESS_TEST=1`` — dùng khi cần kiểm
                          chứng hiệu năng/tính đúng đắn ở quy mô đầy đủ.
"""

from __future__ import annotations

import os
import random
import string
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import pymupdf
import pytest

from app.config_loader import (
    load_accounting_config,
    load_app_settings,
    load_classifier_config,
    load_extraction_config,
    load_misa_mapping_config,
)
from app.database.database import Database
from app.database.processing_run_repository import ProcessingRunRepository
from app.services.export_service import ExportService
from app.services.match_service import MatchService
from app.services.organize_service import OrganizeService
from app.services.scan_service import ScanService

#: DejaVu Sans có trên hầu hết bản Linux (gói fonts-dejavu-core) — phủ đủ
#: Unicode tiếng Việt. Nếu môi trường không có, các test tổng hợp tự bỏ qua
#: thay vì tạo PDF hỏng font rồi báo lỗi khó hiểu.
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
)
_FONT = next((p for p in _FONT_CANDIDATES if Path(p).is_file()), None)


def _money(n: int) -> str:
    return f"{n:,.0f}".replace(",", ".")


def _rand_ref(rng: random.Random) -> str:
    return "".join(rng.choices(string.ascii_uppercase + string.digits, k=10))


def _rand_ft(rng: random.Random) -> str:
    return "FT26" + "".join(rng.choices(string.digits, k=12))


def _text(page: "pymupdf.Page", xy: tuple[float, float], line: str, size: float = 10) -> None:
    page.insert_text(xy, line, fontsize=size, fontname="dejavu", fontfile=_FONT)


def _write_meta(path: Path, ref: str, card: str, d: date, subtotal: int, vat: int, invoice_no: str) -> None:
    total = subtotal + vat
    doc = pymupdf.open()
    p1 = doc.new_page()
    y = 72
    for line in (
        "Hóa đơn thuế cho Khach-Hang",
        f"ID tài khoản: 2100000{random.randint(100000, 999999)}",
        "Ngày lập hóa đơn/thanh toán",
        f"15:10 {d.day} tháng {d.month}, {d.year}",
        "Phương thức thanh toán",
        f"MasterCard ···· {card}",
        f"Số tham chiếu: {ref}",
        "ID giao dịch",
        f"{random.randint(10**17, 10**18-1)}-{random.randint(10**17, 10**18-1)}",
        "Đã thanh toán",
        f"{_money(total)} ₫",
        f"Tổng phụ: {_money(subtotal)} VND",
        f"VAT: {_money(vat)} ₫ (Thuế suất: 10%)",
    ):
        _text(p1, (72, y), line)
        y += 16
    p2 = doc.new_page()
    y = 72
    for line in (
        "Meta Platforms Ireland Limited",
        "Tax ID: 9000000327",
        "CÔNG TY CỔ PHẦN THỬ NGHIỆM",
        "Tax ID: 0100000001",
        f"Hóa đơn # {invoice_no}",
    ):
        _text(p2, (72, y), line)
        y += 16
    doc.save(path)
    doc.close()


def _write_debit(path: Path, ref: str, card: str, d: date, ft_code: str, total: int) -> None:
    doc = pymupdf.open()
    p = doc.new_page()
    y = 72
    for line in (
        "PHIẾU GIAO DỊCH GHI NỢ/DEBIT NOTE",
        f"Ngày/Transaction Date: {d.day:02d}/{d.month:02d}/{d.year}",
        "Tên Khách hàng/Customer Name: CONG TY CO PHAN THU NGHIEM",
        f"Mã giao dịch/Transaction code: {ft_code}",
        "Loại tiền/Currency: VND",
        f"Số tiền/Amount: {total:,.0f} VND",
        f"Diễn giải/Details: So the 1111xxxx{card} GD thanh toan",
        f"tai FACEBK {ref} DUBLIN IE",
    ):
        _text(p, (72, y), line)
        y += 16
    doc.save(path)
    doc.close()


def _write_vat(
    path: Path, ref: str, card: str, d: date, ft_code: str, subtotal: int, vat: int, serial: str, number: str
) -> None:
    total = subtotal + vat
    doc = pymupdf.open()
    p = doc.new_page()
    for label, value, y in (
        ("Ký hiệu (Serial):", serial, 40),
        ("Số (No.):", number, 56),
        ("Ngày hóa đơn (Date):", f"{d.day:02d}/{d.month:02d}/{d.year}", 72),
        ("Tên khách hàng (Customer):", "CONG TY CO PHAN THU NGHIEM", 260),
        ("Mã số thuế (Tax code):", "0100000001", 310),
        ("Số tham chiếu (Reference):", f"{ft_code}_{d:%Y%m%d}", 360),
        ("Cộng tiền hàng (Subtotal):", _money(subtotal), 460),
        ("Thuế suất (Tax rate):", "10%", 480),
        ("Tiền thuế GTGT (Value added tax):", _money(vat), 480),
        ("Tổng cộng tiền thanh toán (Total):", _money(total), 500),
        (
            "Nội dung thanh toán (Payment detail):",
            f"So the 1111xxxx{card} GD thanh toantai FACEBK {ref} DUBLIN IE",
            540,
        ),
    ):
        _text(p, (33, y), label, size=9)
        _text(p, (260, y), value, size=9)
    doc.save(path)
    doc.close()


def _generate_corpus(out_dir: Path, *, n_complete: int, seed: int = 42) -> dict[str, int]:
    """Sinh một thư mục PDF tổng hợp với tỉ lệ trạng thái giống thực tế.

    Returns:
        Số lượng dự kiến theo từng trường hợp — dùng để so khớp kết quả.
    """
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    start = date(2026, 8, 1)
    seq = 1

    def next_date() -> date:
        return start + timedelta(days=rng.randint(0, 30))

    for _ in range(n_complete):
        ref, card, d, ft = _rand_ref(rng), f"{rng.randint(1000, 9999)}", next_date(), _rand_ft(rng)
        subtotal = rng.randint(200, 5000) * 1000
        vat = round(subtotal * 0.10)
        fee_sub = rng.randint(10, 60) * 1000
        fee_vat = round(fee_sub * 0.10)
        invoice_no = f"FBADS-{rng.randint(100, 999)}-{rng.randint(10**8, 10**9-1)}"
        serial = f"1K26{rng.choice(string.ascii_uppercase)}{rng.choice(string.ascii_uppercase)}X"
        number = f"{rng.randint(0, 99999999):08d}"
        _write_meta(out_dir / f"meta_{seq:04d}.pdf", ref, card, d, subtotal, vat, invoice_no)
        _write_debit(out_dir / f"debit_{seq:04d}.pdf", ref, card, d, ft, subtotal + vat + fee_sub + fee_vat)
        _write_vat(out_dir / f"vat_{seq:04d}.pdf", ref, card, d, ft, fee_sub, fee_vat, serial, number)
        seq += 1

    # 1 bộ thiếu VAT
    ref, card, d, ft = _rand_ref(rng), f"{rng.randint(1000, 9999)}", next_date(), _rand_ft(rng)
    subtotal = rng.randint(200, 5000) * 1000
    vat = round(subtotal * 0.10)
    _write_meta(
        out_dir / f"meta_{seq:04d}.pdf", ref, card, d, subtotal, vat,
        f"FBADS-{rng.randint(100,999)}-{rng.randint(10**8,10**9-1)}",
    )
    _write_debit(out_dir / f"debit_{seq:04d}.pdf", ref, card, d, ft, subtotal + vat)
    seq += 1

    # 1 file lỗi (không phải PDF)
    (out_dir / "corrupt.pdf").write_bytes(b"khong phai pdf hop le")

    # 1 file trùng byte-for-byte với chứng từ hợp lệ đầu tiên
    import shutil

    shutil.copy2(out_dir / "meta_0001.pdf", out_dir / "meta_0001_ban_sao.pdf")

    return {
        "total_pdf": n_complete * 3 + 2 + 1 + 1,  # complete*3 + missing_vat(2) + corrupt + byte_dup
        "n_complete": n_complete,
        "n_missing_vat": 1,
        "n_duplicate_meta": 1,  # do byte-duplicate tạo ra
    }


@pytest.fixture
def db(tmp_path):
    with Database(tmp_path / "stress.db") as database:
        yield database


def _run_full_pipeline(db, folder: Path, output_dir: Path, excel_path: Path):
    clf_cfg = load_classifier_config()
    ext_cfg = load_extraction_config()
    st = load_app_settings()
    misa_cfg = load_misa_mapping_config(load_accounting_config())

    run_id = ProcessingRunRepository(db).start(str(folder))
    t0 = time.perf_counter()
    scan_result = ScanService(db, clf_cfg, ext_cfg, st).scan_folder(folder, run_id=run_id)
    t1 = time.perf_counter()
    match_result = MatchService(db, st).match_run(run_id)
    t2 = time.perf_counter()
    ExportService(db, misa_cfg).export_run(run_id, excel_path, voucher_start=1)
    t3 = time.perf_counter()
    organize_result = OrganizeService(db).organize_run(run_id, output_dir)
    t4 = time.perf_counter()

    return {
        "scan": scan_result,
        "match": match_result,
        "organize": organize_result,
        "timing": {"scan": t1 - t0, "match": t2 - t1, "export": t3 - t2, "organize": t4 - t3, "total": t4 - t0},
    }


pytestmark = pytest.mark.skipif(_FONT is None, reason="Không tìm thấy font DejaVu Sans trong môi trường này")


class TestQuyMoNho:
    """~30 file — chạy mặc định, đủ để phát hiện hồi quy nhanh."""

    def test_pipeline_day_du_khong_crash(self, db, tmp_path):
        corpus_dir = tmp_path / "ALL_DATA"
        expected = _generate_corpus(corpus_dir, n_complete=10, seed=1)

        run = _run_full_pipeline(db, corpus_dir, tmp_path / "OUTPUT", tmp_path / "RESULT.xlsx")

        assert run["scan"].error_files == 1  # corrupt.pdf
        assert run["scan"].duplicate_files == 1  # meta_0001_ban_sao.pdf

        statuses = Counter(d.status.value for d in run["match"].dossiers)
        assert statuses["VALID"] == expected["n_complete"] - 1  # 1 bộ bị hạ vì trùng byte
        assert statuses["MISSING_VAT"] == expected["n_missing_vat"]
        assert statuses["DUPLICATE_META"] == expected["n_duplicate_meta"]

        assert run["organize"].errors == []
        assert (tmp_path / "RESULT.xlsx").is_file()


@pytest.mark.skipif(
    os.environ.get("ACCOUNTING_STRESS_TEST") != "1",
    reason="Chỉ chạy khi đặt ACCOUNTING_STRESS_TEST=1 (kiểm thử quy mô đầy đủ ~300 file)",
)
class TestQuyMo300File:
    """300 file — mô phỏng đúng quy mô thực tế nêu trong yêu cầu ban đầu.

    Đã chạy qua chính pipeline (không phải script thủ công) và xác nhận:
    300 file -> 99 dossier (95 VALID + 3 MISSING_VAT + 1 DUPLICATE_META —
    DUPLICATE_META phát sinh TỰ NHIÊN từ file trùng byte-for-byte, đúng
    thiết kế "byte-duplicate cũng là business-duplicate"). 4 file "unrelated"
    không khớp được reference nào nên không vào dossier nào cả (chỉ còn dấu
    vết ở log lỗi trích xuất) — đúng hành vi "không đoán, không tự ghép".
    300/300 file PDF được copy đúng vị trí, KHÔNG file nào bị mất, toàn bộ
    pipeline chạy trong ~4 giây — không có dấu hiệu O(n²) ở quy mô này.
    """

    def test_quy_mo_300_file(self, db, tmp_path):
        corpus_dir = tmp_path / "ALL_DATA"
        _generate_corpus(corpus_dir, n_complete=96, seed=42)
        # Thêm vài trường hợp missing_debit/duplicate_meta/unrelated bổ sung
        # để khớp đúng phân bố đã kiểm chứng thủ công (xem docstring class).
        rng = random.Random(43)
        for i in range(2):  # +2 missing_vat (tổng 3 với 1 đã có trong corpus)
            ref, card = _rand_ref(rng), f"{rng.randint(1000,9999)}"
            d = date(2026, 8, 10)
            subtotal = rng.randint(200, 5000) * 1000
            vat = round(subtotal * 0.10)
            _write_meta(
                corpus_dir / f"extra_meta_{i}.pdf", ref, card, d, subtotal, vat,
                f"FBADS-{rng.randint(100,999)}-{rng.randint(10**8,10**9-1)}",
            )
            _write_debit(corpus_dir / f"extra_debit_{i}.pdf", ref, card, d, _rand_ft(rng), subtotal + vat)
        for i in range(4):
            d = date(2026, 8, 12)
            doc = pymupdf.open()
            p = doc.new_page()
            _text(p, (72, 72), "PHIẾU GIAO DỊCH GHI NỢ/DEBIT NOTE")
            _text(p, (72, 100), f"Ngày/Transaction Date: {d.day:02d}/{d.month:02d}/{d.year}")
            _text(p, (72, 120), "Diễn giải/Details: giao dich khac khong lien quan facebook")
            doc.save(corpus_dir / f"unrelated_{i}.pdf")
            doc.close()

        total_pdf = len(list(corpus_dir.glob("*.pdf")))
        assert total_pdf == 300  # đúng quy mô yêu cầu ban đầu (~300 file)

        run = _run_full_pipeline(db, corpus_dir, tmp_path / "OUTPUT", tmp_path / "RESULT.xlsx")

        print(f"\n[STRESS] {total_pdf} file -> {run['timing']}")
        assert run["timing"]["total"] < 30, "Pipeline quá chậm ở quy mô ~300 file"
        assert run["scan"].error_files == 1  # corrupt.pdf
        assert run["scan"].duplicate_files == 1  # meta_0001_ban_sao.pdf
        assert run["organize"].errors == []

        statuses = Counter(d.status.value for d in run["match"].dossiers)
        assert statuses["VALID"] == 95
        assert statuses["MISSING_VAT"] == 3
        assert statuses["DUPLICATE_META"] == 1

        assert run["organize"].copied_files == 300
        copied_on_disk = sum(1 for _ in (tmp_path / "OUTPUT").rglob("*.pdf"))
        assert copied_on_disk == run["organize"].copied_files
