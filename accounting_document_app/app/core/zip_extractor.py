"""Lấy PDF ra khỏi các file ZIP nằm trực tiếp trong một thư mục nguồn.

Người dùng tải hàng loạt hoá đơn dưới dạng ``invoice (1).zip``,
``invoice (2).zip``... mỗi ZIP thường chứa một PDF + một XML (hoặc nằm
trong thư mục con). Module này chỉ lấy PDF, bỏ mọi thứ khác, và ghi phẳng
(không tạo lại cây thư mục con của ZIP) vào một thư mục đích — mặc định
``<thư_mục_nguồn>/ALL_DATA`` — để thư mục đó dùng thẳng làm nguồn cho
``ScanService``.

Chỉ dùng thư viện chuẩn (``zipfile``, ``pathlib``, ``zlib``) — không thêm
dependency mới.

An toàn:
    * Chỉ đọc ``member.filename`` để lấy ``Path(...).name`` (bỏ mọi phần
      thư mục cha) trước khi ghi — không bao giờ ghép nguyên
      ``member.filename`` vào đường dẫn đích, nên không thể bị ZIP path
      traversal (``../../evil.pdf``).
    * Không bao giờ ghi đè file đã có. Nhận biết một PDF đã được giải nén ở
      lần chạy trước bằng CRC32 + kích thước (so với chính file đã nằm
      trong thư mục đích) — quét lại cùng một ZIP nhiều lần KHÔNG sinh ra
      ``invoice_1.pdf``, ``invoice_2.pdf``... trùng lặp. Chỉ khi nội dung
      THỰC SỰ khác (trùng tên nhưng khác file) mới được đánh số mới. Cách
      này không cần lưu thêm file metadata nào (không ghi gì vào thư mục
      cài đặt ứng dụng / PyInstaller ``_internal``) — trạng thái coi như đã
      nằm sẵn trong chính các PDF đã giải nén.
    * Một ZIP lỗi (hỏng, không đọc được, có mật khẩu) không làm dừng cả lô
      — bị bỏ qua, ghi lỗi, và tiếp tục ZIP tiếp theo.
"""

from __future__ import annotations

import logging
import shutil
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.utils.file_utils import iter_pdf_files

__all__ = [
    "ZipExtractProgress",
    "ZipExtractResult",
    "extract_pdfs_from_zips",
    "LooseCollectResult",
    "collect_loose_pdfs",
]

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 1024 * 1024
_ZIP_READ_ERRORS = (zipfile.BadZipFile, RuntimeError, OSError, NotImplementedError)


@dataclass(frozen=True)
class ZipExtractProgress:
    """Một mốc tiến độ khi xử lý danh sách ZIP.

    Attributes:
        current: Số ZIP đã xử lý xong (kể cả lỗi).
        total: Tổng số ZIP tìm thấy.
        zip_name: Tên ZIP vừa xử lý.
        message: Chuỗi hiển thị cho progress bar.
    """

    current: int
    total: int
    zip_name: str
    message: str


@dataclass
class ZipExtractResult:
    """Kết quả một lượt lấy PDF từ ZIP.

    Attributes:
        dest_folder: Thư mục đích đã ghi PDF vào (thường là ``ALL_DATA``).
        zip_scanned: Số file ZIP đã quét.
        pdf_extracted: Số PDF đã có trong thư mục đích sau lượt chạy này
            (gồm cả PDF mới ghi VÀ PDF đã tồn tại từ lần chạy trước được
            nhận diện lại qua CRC32 — không phải chỉ đếm file mới ghi).
        non_pdf_skipped: Số member không phải PDF đã bỏ qua (XML, ảnh...).
        zip_errors: Số ZIP không đọc được (hỏng / có mật khẩu / lỗi I/O).
        error_messages: Thông báo lỗi người-đọc-được cho từng ZIP lỗi.
        no_pdf_zip_names: Tên các ZIP quét được nhưng không chứa PDF nào.
    """

    dest_folder: Path
    zip_scanned: int = 0
    pdf_extracted: int = 0
    non_pdf_skipped: int = 0
    zip_errors: int = 0
    error_messages: list[str] = field(default_factory=list)
    no_pdf_zip_names: list[str] = field(default_factory=list)


def _iter_top_level_zips(source_folder: Path) -> list[Path]:
    """Chỉ lấy file ``.zip`` nằm TRỰC TIẾP trong ``source_folder`` — không đệ quy."""
    return sorted(
        path
        for path in source_folder.iterdir()
        if path.is_file() and path.suffix.lower() == ".zip"
    )


def _file_crc32(path: Path) -> int:
    crc = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            crc = zlib.crc32(chunk, crc)
    return crc & 0xFFFFFFFF


def _resolve_target(dest_folder: Path, flat_name: str, member_crc: int, member_size: int) -> tuple[Path, bool]:
    """Chọn đường dẫn ghi cho một PDF, tránh cả ghi đè lẫn trùng lặp giả.

    Duyệt qua ``flat_name``, ``flat_name_2``, ``flat_name_3``... So sánh
    CRC32 + kích thước với file đã có ở mỗi vị trí: khớp thì coi là PDF này
    ĐÃ được giải nén trước đó (không ghi lại). Không khớp thì thử số tiếp
    theo. Chỉ dừng ở một tên chưa từng tồn tại khi không tìm được vị trí
    nào có nội dung trùng.

    Returns:
        ``(đường_dẫn_đích, is_new)`` — ``is_new=False`` nghĩa là PDF này đã
        nằm sẵn ở đó, không cần ghi lại.
    """
    stem, suffix = Path(flat_name).stem, Path(flat_name).suffix
    candidate = dest_folder / flat_name
    index = 2
    while candidate.exists():
        if candidate.stat().st_size == member_size and _file_crc32(candidate) == member_crc:
            return candidate, False
        candidate = dest_folder / f"{stem}_{index}{suffix}"
        index += 1
    return candidate, True


def _process_one_zip(zip_path: Path, dest: Path, result: ZipExtractResult) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        members = [m for m in archive.infolist() if not m.is_dir()]
        pdf_members = [m for m in members if Path(m.filename).name.lower().endswith(".pdf")]
        result.non_pdf_skipped += len(members) - len(pdf_members)

        if not pdf_members:
            result.no_pdf_zip_names.append(zip_path.name)
            logger.info("Không tìm thấy PDF trong %s", zip_path.name)
            return

        for member in pdf_members:
            flat_name = Path(member.filename).name
            if not flat_name:
                continue
            target, is_new = _resolve_target(dest, flat_name, member.CRC, member.file_size)
            if is_new:
                data = archive.read(member)  # RuntimeError nếu ZIP có mật khẩu
                target.write_bytes(data)
                logger.debug("Đã lấy %s từ %s -> %s", member.filename, zip_path.name, target.name)
            result.pdf_extracted += 1


def extract_pdfs_from_zips(
    source_folder: Path | str,
    dest_folder: Path | str,
    *,
    on_progress: Callable[[ZipExtractProgress], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> ZipExtractResult:
    """Quét mọi ``*.zip`` trực tiếp trong ``source_folder``, chỉ lấy PDF.

    Args:
        source_folder: Thư mục chứa các file ``.zip`` (không quét thư mục con).
        dest_folder: Thư mục đích ghi PDF (được tạo nếu chưa có).
        on_progress: Callback gọi sau mỗi ZIP.
        should_cancel: Callback kiểm tra huỷ hợp tác — dừng SAU ZIP đang xử lý.

    Returns:
        Thống kê đầy đủ của lượt chạy.
    """
    source = Path(source_folder)
    dest = Path(dest_folder)
    dest.mkdir(parents=True, exist_ok=True)

    zip_paths = _iter_top_level_zips(source)
    result = ZipExtractResult(dest_folder=dest)
    total = len(zip_paths)

    for index, zip_path in enumerate(zip_paths, start=1):
        if should_cancel is not None and should_cancel():
            logger.info("Người dùng huỷ lấy PDF từ ZIP sau %d/%d file", index - 1, total)
            break

        result.zip_scanned += 1
        if on_progress is not None:
            on_progress(
                ZipExtractProgress(
                    current=index,
                    total=total,
                    zip_name=zip_path.name,
                    message=f"Đang xử lý ZIP {index}/{total}: {zip_path.name}",
                )
            )

        try:
            _process_one_zip(zip_path, dest, result)
        except _ZIP_READ_ERRORS as exc:
            result.zip_errors += 1
            message = f"Không thể đọc {zip_path.name}: {exc}"
            result.error_messages.append(message)
            logger.warning(message)

    logger.info(
        "Lấy PDF từ ZIP hoàn tất: %d ZIP, %d PDF, %d bỏ qua, %d lỗi",
        result.zip_scanned, result.pdf_extracted, result.non_pdf_skipped, result.zip_errors,
    )
    return result


@dataclass
class LooseCollectResult:
    """Kết quả gom PDF rời (không nằm trong ZIP nào) vào thư mục đích."""

    scanned: int = 0
    copied: int = 0
    already_present: int = 0
    errors: list[str] = field(default_factory=list)


def collect_loose_pdfs(source_folder: Path | str, dest_folder: Path | str) -> LooseCollectResult:
    """Gom mọi PDF nằm TRỰC TIẾP trong ``source_folder`` (không phải từ ZIP,
    không đệ quy vào thư mục con) vào ``dest_folder``.

    BỐI CẢNH: thư mục nguồn thực tế của người dùng có thể chứa cả ZIP LẪN
    PDF rời cạnh nhau (vd. ``data_tool_read_pdf/`` có ``invoice (1).zip``
    VÀ ``facebook_bill.pdf`` nằm ngay cạnh nhau) — bước "Chuẩn bị dữ liệu"
    cần gom cả hai loại vào cùng một nơi (``ALL_DATA``) để SCAN một lượt.

    CỐ Ý không đệ quy vào thư mục con (vd. ``data_1/``, ``data_2/`` trong
    ví dụ cấu trúc thực tế) — đó có thể là dữ liệu của người dùng từ trước,
    không phải phần việc của bước chuẩn bị dữ liệu tự động; giống hệt cách
    ``extract_pdfs_from_zips`` chỉ quét ZIP trực tiếp trong thư mục nguồn.

    Dùng LẠI đúng cơ chế chống trùng CRC32 + kích thước của
    ``extract_pdfs_from_zips`` (``_resolve_target``) — quét lại nhiều lần
    không sinh file trùng.

    Args:
        source_folder: Thư mục nguồn.
        dest_folder: Thư mục đích (thường là ``ALL_DATA``, đã tồn tại hoặc
            được tạo mới).

    Returns:
        ``LooseCollectResult``.
    """
    source = Path(source_folder)
    dest = Path(dest_folder)
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()

    result = LooseCollectResult()
    for path in iter_pdf_files(source, recursive=False):
        if path.resolve().parent == dest_resolved:
            continue  # PDF đã nằm sẵn trong đích (vd. ALL_DATA chính là source_folder)

        result.scanned += 1
        try:
            crc = _file_crc32(path)
            size = path.stat().st_size
            target, is_new = _resolve_target(dest, path.name, crc, size)
            if is_new:
                shutil.copy2(path, target)
                result.copied += 1
            else:
                result.already_present += 1
        except OSError as exc:
            message = f"Không copy được {path.name}: {exc}"
            logger.warning(message)
            result.errors.append(message)

    logger.info(
        "Gom PDF rời hoàn tất: %d file quét, %d đã copy, %d đã có sẵn, %d lỗi",
        result.scanned, result.copied, result.already_present, len(result.errors),
    )
    return result
