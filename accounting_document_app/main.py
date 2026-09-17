"""Điểm vào của ứng dụng desktop.

Nạp cấu hình, mở database, khởi tạo giao diện. Chạy::

    python main.py
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.config_loader import (
    DEFAULT_CONFIG_DIR,
    load_accounting_config,
    load_app_settings,
    load_classifier_config,
    load_extraction_config,
    load_misa_mapping_config,
)
from app.database.database import Database
from app.ui.main_window import MainWindow
from app.utils.logging_utils import setup_logging

__all__ = ["main"]


def main() -> int:
    """Khởi động ứng dụng, trả về mã thoát của ``QApplication``."""
    app_settings = load_app_settings()
    setup_logging(
        DEFAULT_CONFIG_DIR.parent / "logs" / "app.log",
        level=app_settings.log_level,
        console=True,
    )
    logger = logging.getLogger(__name__)
    logger.info("Khởi động Marketing Accounting Document Tool")

    classifier_config = load_classifier_config()
    extraction_config = load_extraction_config()
    accounting_config = load_accounting_config()
    misa_config = load_misa_mapping_config(accounting_config)

    db_path = app_settings.raw.get("paths", {}).get("database") or "database/accounting_app.db"
    db_path = DEFAULT_CONFIG_DIR.parent / db_path

    app = QApplication(sys.argv)
    with Database(db_path) as db:
        window = MainWindow(
            db, classifier_config, extraction_config, app_settings, accounting_config, misa_config
        )
        window.show()
        return app.exec()


if __name__ == "__main__":
    sys.exit(main())
