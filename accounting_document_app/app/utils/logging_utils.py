"""Cấu hình logging cho ứng dụng.

Ghi ra ``logs/app.log`` có xoay vòng, đồng thời ra console khi chạy dev.
Không ghi nội dung chứng từ vào log — chỉ ghi tên file, loại, mã lỗi.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

__all__ = ["setup_logging"]

_FORMAT = "%(asctime)s %(levelname)-7s %(name)-38s %(message)s"


def setup_logging(
    log_file: Path | str = "logs/app.log",
    *,
    level: str = "INFO",
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
    console: bool = True,
) -> logging.Logger:
    """Khởi tạo logger gốc của ứng dụng.

    Args:
        log_file: Đường dẫn file log; thư mục cha sẽ được tạo nếu chưa có.
        level: Mức log (``DEBUG``/``INFO``/``WARNING``/``ERROR``).
        max_bytes: Kích thước tối đa mỗi file log trước khi xoay vòng.
        backup_count: Số file log cũ giữ lại.
        console: Có ghi ra màn hình hay không.

    Returns:
        Logger gốc đã cấu hình.
    """
    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(_FORMAT)

    file_handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        root.addHandler(stream)

    return root
