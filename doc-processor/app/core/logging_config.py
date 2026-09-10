"""Structured logging setup.

Writes to `processing.log` (plain text, human readable) AND keeps a
Python logger that callers can attach handlers to. Every pipeline stage
should log through `get_logger(__name__)` rather than print().
"""
from __future__ import annotations

import logging
from pathlib import Path

_CONFIGURED = False


def configure_logging(log_file: str = "processing.log", level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger("doctool")
    root.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(Path(log_file), encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    root.addHandler(console_handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    if not _CONFIGURED:
        configure_logging()
    return logging.getLogger(f"doctool.{name}")
