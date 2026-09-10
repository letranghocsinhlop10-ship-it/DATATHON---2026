"""Loads the YAML config files once and exposes them as plain dicts.

Kept intentionally dumb (no schema validation layer) so a non-developer
can edit the YAML files without needing to know pydantic. Code that reads
these dicts should use .get() with sensible defaults.
"""
from __future__ import annotations

import functools
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


def _load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@functools.lru_cache(maxsize=None)
def get_settings() -> dict:
    return _load_yaml("settings.yaml")


@functools.lru_cache(maxsize=None)
def get_extraction_patterns() -> dict:
    return _load_yaml("extraction_patterns.yaml")


@functools.lru_cache(maxsize=None)
def get_validation_rules() -> dict:
    return _load_yaml("validation_rules.yaml")


@functools.lru_cache(maxsize=None)
def get_misa_column_mapping() -> dict:
    return _load_yaml("misa_column_mapping.yaml")


def clear_config_cache() -> None:
    """Useful for tests that swap in a different config directory/content."""
    get_settings.cache_clear()
    get_extraction_patterns.cache_clear()
    get_validation_rules.cache_clear()
    get_misa_column_mapping.cache_clear()
