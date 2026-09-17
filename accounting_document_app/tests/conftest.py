"""Fixture dùng chung cho toàn bộ test."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Chạy Qt không cần màn hình thật — bắt buộc set TRƯỚC khi PySide6 được
# import ở bất kỳ đâu (test UI hoặc chính app).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
for extra in (ROOT, ROOT / "tests", ROOT / "tests" / "fixtures"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from app.config_loader import (  # noqa: E402
    load_accounting_config,
    load_app_settings,
    load_classifier_config,
    load_extraction_config,
    load_misa_mapping_config,
)
from app.extractors.registry import ExtractorRegistry  # noqa: E402


@pytest.fixture(scope="session")
def classifier_config():
    return load_classifier_config()


@pytest.fixture(scope="session")
def extraction_config():
    return load_extraction_config()


@pytest.fixture(scope="session")
def app_settings():
    return load_app_settings()


@pytest.fixture(scope="session")
def registry(extraction_config):
    return ExtractorRegistry(extraction_config)


@pytest.fixture(scope="session")
def accounting_config():
    return load_accounting_config()


@pytest.fixture(scope="session")
def misa_config(accounting_config):
    return load_misa_mapping_config(accounting_config)
