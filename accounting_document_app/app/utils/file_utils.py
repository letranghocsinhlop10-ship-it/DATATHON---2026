"""Tiện ích thao tác file — chỉ ĐỌC và COPY, không bao giờ sửa/xoá file gốc."""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Iterator

__all__ = ["iter_pdf_files", "safe_folder_name", "unique_path", "copy_preserving"]

logger = logging.getLogger(__name__)

_INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_WINDOWS_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def iter_pdf_files(folder: Path | str, *, recursive: bool = True) -> Iterator[Path]:
    """Duyệt các file PDF trong thư mục.

    Args:
        folder: Thư mục gốc.
        recursive: Có duyệt thư mục con không.

    Yields:
        Đường dẫn từng file ``.pdf`` (không phân biệt hoa thường).
    """
    root = Path(folder)
    pattern = "**/*" if recursive else "*"
    for path in sorted(root.glob(pattern)):
        if path.is_file() and path.suffix.lower() == ".pdf":
            yield path


def safe_folder_name(name: str, *, max_length: int = 120) -> str:
    """Chuyển một chuỗi thành tên thư mục hợp lệ trên Windows.

    Args:
        name: Tên mong muốn.
        max_length: Độ dài tối đa.

    Returns:
        Tên đã bỏ ký tự cấm, tránh tên dành riêng của Windows.
    """
    cleaned = _INVALID_WINDOWS_CHARS.sub("_", name).strip(" .")
    cleaned = re.sub(r"\s+", "_", cleaned)[:max_length]
    if not cleaned:
        return "UNNAMED"
    if cleaned.upper() in _RESERVED_WINDOWS_NAMES:
        return f"_{cleaned}"
    return cleaned


def unique_path(path: Path) -> Path:
    """Trả về đường dẫn chưa tồn tại, thêm hậu tố ``_2``, ``_3``... nếu cần.

    Không bao giờ ghi đè dữ liệu đã có.
    """
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    index = 2
    while True:
        candidate = parent / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def copy_preserving(source: Path, destination: Path) -> Path:
    """Copy file, giữ nguyên metadata, không bao giờ ghi đè.

    Args:
        source: File nguồn (KHÔNG bị sửa, KHÔNG bị xoá, KHÔNG bị di chuyển).
        destination: Đường dẫn đích mong muốn.

    Returns:
        Đường dẫn thực tế đã ghi.

    Raises:
        OSError: Copy thất bại.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    target = unique_path(destination)
    shutil.copy2(source, target)
    logger.debug("Đã copy %s -> %s", source.name, target)
    return target
