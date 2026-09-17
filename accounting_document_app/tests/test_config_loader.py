"""Test nạp cấu hình — lỗi phải lộ ra ngay lúc khởi động."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config_loader import (
    ConfigError,
    load_classifier_config,
    load_extraction_config,
)
from app.models.enums import DocumentType


class TestNapCauHinhThat:
    def test_du_ba_loai_chung_tu(self, classifier_config):
        types = {r.document_type for r in classifier_config.rules}
        assert types == {
            DocumentType.META_INVOICE,
            DocumentType.VPBANK_DEBIT_NOTE,
            DocumentType.VPBANK_VAT_INVOICE,
        }

    def test_moi_loai_deu_co_dinh_dang_tien(self, extraction_config):
        for document_type in extraction_config.rules_by_type:
            assert extraction_config.money_format_for(document_type) is not None

    def test_dinh_dang_tien_khac_nhau_giua_cac_loai(self, extraction_config):
        meta = extraction_config.money_format_for(DocumentType.META_INVOICE)
        debit = extraction_config.money_format_for(DocumentType.VPBANK_DEBIT_NOTE)
        assert meta.thousands == "."
        assert debit.thousands == ","

    def test_hoa_don_gtgt_dung_chien_luoc_toa_do(self, extraction_config):
        rules = extraction_config.rules_for(DocumentType.VPBANK_VAT_INVOICE)
        assert all(r.strategy == "label_right" for r in rules)

    def test_cau_hinh_nha_cung_cap(self, extraction_config):
        assert "FACEBK" in extraction_config.merchant.anchors


class TestBaoLoiCauHinhSai:
    def _write(self, tmp_path: Path, content: str) -> Path:
        path = tmp_path / "rules.yaml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_thieu_file(self, tmp_path: Path):
        with pytest.raises(ConfigError):
            load_classifier_config(tmp_path / "khong_ton_tai.yaml")

    def test_loai_chung_tu_la(self, tmp_path: Path):
        path = self._write(tmp_path, "types:\n  LOAI_LA:\n    must_have_any: ['x']\n")
        with pytest.raises(ConfigError, match="không hợp lệ"):
            load_classifier_config(path)

    def test_thieu_must_have_any(self, tmp_path: Path):
        path = self._write(tmp_path, "types:\n  META_INVOICE:\n    strong: ['x']\n")
        with pytest.raises(ConfigError, match="must_have_any"):
            load_classifier_config(path)

    def test_regex_sai_cu_phap(self, tmp_path: Path):
        path = self._write(
            tmp_path,
            "types:\n  META_INVOICE:\n    rules:\n"
            "      - id: r1\n        field: f\n        pattern: '([unclosed'\n",
        )
        with pytest.raises(ConfigError, match="regex"):
            load_extraction_config(path)

    def test_strategy_la(self, tmp_path: Path):
        path = self._write(
            tmp_path,
            "types:\n  META_INVOICE:\n    rules:\n"
            "      - id: r1\n        field: f\n        strategy: bay_len\n        pattern: 'x'\n",
        )
        with pytest.raises(ConfigError, match="strategy"):
            load_extraction_config(path)

    def test_label_right_thieu_nhan(self, tmp_path: Path):
        path = self._write(
            tmp_path,
            "types:\n  META_INVOICE:\n    default_strategy: label_right\n    rules:\n"
            "      - id: r1\n        field: f\n",
        )
        with pytest.raises(ConfigError, match="label"):
            load_extraction_config(path)

    def test_thieu_money_format_thi_bao_loi_chu_khong_doan(self, tmp_path: Path):
        path = self._write(
            tmp_path,
            "types:\n  META_INVOICE:\n    rules:\n"
            "      - id: r1\n        field: f\n        pattern: 'x'\n",
        )
        config = load_extraction_config(path)
        with pytest.raises(ConfigError, match="money_format"):
            config.money_format_for(DocumentType.META_INVOICE)
