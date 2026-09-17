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


class TestAccountingConfig:
    def test_nap_dung_tai_khoan_that(self):
        from app.config_loader import load_accounting_config

        config = load_accounting_config()
        assert config.account("marketing_expense") == "6417"
        assert config.account("supplier_payable") == "331"

    def test_tai_khoan_khong_ton_tai_bao_loi_ro_rang(self):
        from app.config_loader import load_accounting_config

        config = load_accounting_config()
        with pytest.raises(ConfigError, match="marketing_expense_khong_ton_tai"):
            config.account("marketing_expense_khong_ton_tai")

    def test_nha_cung_cap_meta_co_ma_so_thue(self):
        from app.config_loader import load_accounting_config

        config = load_accounting_config()
        assert config.supplier("meta").object_code == "9000000327"

    def test_thieu_accounts_bao_loi(self, tmp_path: Path):
        from app.config_loader import load_accounting_config

        path = tmp_path / "acc.yaml"
        path.write_text("company:\n  name: X\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="accounts"):
            load_accounting_config(path)

    def test_khong_khau_tru_thue_meta_theo_xac_nhan_q7(self):
        from app.config_loader import load_accounting_config

        config = load_accounting_config()
        assert config.policy.deduct_meta_input_vat is False


class TestMisaMappingConfig:
    def test_nap_dung_34_cot(self):
        from app.config_loader import load_accounting_config, load_misa_mapping_config

        misa = load_misa_mapping_config(load_accounting_config())
        assert len(misa.columns) == 34

    def test_placeholder_accounts_da_duoc_resolve(self):
        from app.config_loader import load_accounting_config, load_misa_mapping_config

        misa = load_misa_mapping_config(load_accounting_config())
        expense_line = next(l for l in misa.lines if l.rule_id == "meta_ad_expense")
        assert expense_line.debit_account == "6417"
        assert "${" not in expense_line.debit_account

    def test_placeholder_dossier_chua_resolve_luc_nap(self):
        """${meta.xxx} chỉ resolve lúc xuất Excel theo từng dossier, không
        phải lúc nạp config."""
        from app.config_loader import load_accounting_config, load_misa_mapping_config

        misa = load_misa_mapping_config(load_accounting_config())
        expense_line = next(l for l in misa.lines if l.rule_id == "meta_ad_expense")
        assert "${meta.invoice_number}" in expense_line.description_template

    def test_so_chung_tu_dinh_dang_dung(self):
        from app.config_loader import load_accounting_config, load_misa_mapping_config

        misa = load_misa_mapping_config(load_accounting_config())
        assert misa.voucher_number.format(52601) == "NVK052601"

    def test_placeholder_khong_giai_quyet_duoc_bao_loi(self, tmp_path: Path):
        from app.config_loader import load_accounting_config, load_misa_mapping_config

        acc = load_accounting_config()
        path = tmp_path / "misa.yaml"
        path.write_text(
            "lines:\n"
            "  - id: x\n"
            "    debit_account: '${accounts.khong_ton_tai}'\n"
            "    credit_account: '331'\n"
            "    amount: 'meta.subtotal'\n"
            "columns: []\n",
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="placeholder"):
            load_misa_mapping_config(acc, path)
