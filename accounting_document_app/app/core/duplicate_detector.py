"""Phát hiện file PDF trùng lặp bằng SHA256.

Cùng một chứng từ có thể được tải về nhiều lần với tên khác nhau. Nội dung
giống hệt nhau thì chỉ xử lý một lần; các bản còn lại được đánh dấu
``DUPLICATE_FILE`` và trỏ về bản gốc — không xoá, không bỏ qua im lặng.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["compute_sha256", "DuplicateDetector", "DuplicateGroup"]

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 1024 * 1024


def compute_sha256(path: Path | str) -> str:
    """Tính SHA256 của một file, đọc theo khối để không ngốn bộ nhớ.

    Args:
        path: Đường dẫn file.

    Returns:
        Chuỗi hex 64 ký tự.

    Raises:
        OSError: Không đọc được file.
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class DuplicateGroup:
    """Nhóm các file có nội dung giống hệt nhau."""

    file_hash: str
    original: Path
    duplicates: list[Path] = field(default_factory=list)

    @property
    def count(self) -> int:
        return 1 + len(self.duplicates)


class DuplicateDetector:
    """Theo dõi hash của các file đã gặp trong một lô xử lý."""

    def __init__(self) -> None:
        self._seen: dict[str, Path] = {}
        self._groups: dict[str, DuplicateGroup] = {}

    def register(self, path: Path, file_hash: str) -> Path | None:
        """Đăng ký một file.

        Args:
            path: Đường dẫn file.
            file_hash: SHA256 đã tính sẵn.

        Returns:
            ``None`` nếu đây là file mới; nếu trùng, trả về đường dẫn file gốc
            đã gặp trước đó.
        """
        original = self._seen.get(file_hash)
        if original is None:
            self._seen[file_hash] = path
            return None

        group = self._groups.setdefault(
            file_hash, DuplicateGroup(file_hash=file_hash, original=original)
        )
        group.duplicates.append(path)
        logger.info("File trùng nội dung: %s == %s", path.name, original.name)
        return original

    @property
    def groups(self) -> tuple[DuplicateGroup, ...]:
        """Các nhóm file trùng đã phát hiện."""
        return tuple(self._groups.values())

    @property
    def unique_count(self) -> int:
        return len(self._seen)
