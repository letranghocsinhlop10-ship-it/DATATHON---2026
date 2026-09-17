"""Nạp và kiểm tra các file cấu hình YAML.

Toàn bộ luật nghiệp vụ (keyword phân loại, regex trích xuất, tài khoản kế
toán, định dạng tiền) nằm trong ``config/``. Module này biến chúng thành
dataclass đã kiểm tra, để lỗi cấu hình bị phát hiện ngay lúc khởi động chứ
không phải giữa chừng khi đang xử lý 300 file.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.models.enums import DocumentType
from app.utils.money_utils import MoneyFormat

__all__ = [
    "ConfigError",
    "ClassifierTypeRule",
    "ClassifierConfig",
    "FieldRule",
    "ExtractionConfig",
    "AppSettings",
    "SupplierConfig",
    "AccountingPolicy",
    "AccountingConfig",
    "MisaVoucherNumberConfig",
    "MisaLineRule",
    "MisaColumn",
    "MisaMappingConfig",
    "load_classifier_config",
    "load_extraction_config",
    "load_app_settings",
    "load_accounting_config",
    "load_misa_mapping_config",
    "DEFAULT_CONFIG_DIR",
]

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

_VALID_STRATEGIES = {"flat_regex", "text_regex", "label_right"}
_VALID_TYPES = {
    "text",
    "reference",
    "tax_code",
    "money",
    "percent",
    "date_dmy",
    "date_vi",
    "date_compact",
}
_VALID_ON_MULTIPLE = {"first", "last", "ambiguous"}
_REGEX_FLAGS = {
    "MULTILINE": re.MULTILINE,
    "IGNORECASE": re.IGNORECASE,
    "DOTALL": re.DOTALL,
}


class ConfigError(ValueError):
    """Cấu hình sai định dạng hoặc thiếu trường bắt buộc."""


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"Không tìm thấy file cấu hình: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML sai cú pháp: {path} — {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"File cấu hình phải là một mapping: {path}")
    return data


# ---------------------------------------------------------------- classifier


@dataclass(frozen=True)
class ClassifierTypeRule:
    """Luật nhận dạng một loại chứng từ."""

    document_type: DocumentType
    description: str
    must_have_any: tuple[str, ...]
    strong: tuple[str, ...]
    must_not_have: tuple[str, ...]
    min_score: int
    #: Chuỗi báo hiệu một chứng từ MỚI bắt đầu tại trang này (tách PDF gộp).
    page_start_markers: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClassifierConfig:
    """Toàn bộ luật phân loại."""

    case_sensitive: bool
    rules: tuple[ClassifierTypeRule, ...]


def load_classifier_config(path: Path | None = None) -> ClassifierConfig:
    """Nạp ``document_rules.yaml``.

    Args:
        path: Đường dẫn file; mặc định ``config/document_rules.yaml``.

    Returns:
        ``ClassifierConfig`` đã kiểm tra.

    Raises:
        ConfigError: Thiếu trường bắt buộc hoặc loại chứng từ không hợp lệ.
    """
    path = path or DEFAULT_CONFIG_DIR / "document_rules.yaml"
    data = _read_yaml(path)
    types = data.get("types") or {}
    if not types:
        raise ConfigError(f"{path} không khai báo loại chứng từ nào")

    rules: list[ClassifierTypeRule] = []
    for name, cfg in types.items():
        try:
            document_type = DocumentType(name)
        except ValueError as exc:
            raise ConfigError(f"Loại chứng từ không hợp lệ trong {path}: {name}") from exc
        must_have_any = tuple(cfg.get("must_have_any") or ())
        if not must_have_any:
            raise ConfigError(f"{name} phải khai báo must_have_any")
        rules.append(
            ClassifierTypeRule(
                document_type=document_type,
                description=str(cfg.get("description", "")),
                must_have_any=must_have_any,
                strong=tuple(cfg.get("strong") or ()),
                must_not_have=tuple(cfg.get("must_not_have") or ()),
                min_score=int(cfg.get("min_score", 1)),
                page_start_markers=tuple(cfg.get("page_start_markers") or ()),
            )
        )
    return ClassifierConfig(
        case_sensitive=bool(data.get("case_sensitive", False)),
        rules=tuple(rules),
    )


# ---------------------------------------------------------------- extraction


@dataclass(frozen=True)
class FieldRule:
    """Một luật trích xuất trường.

    Attributes:
        rule_id: Id duy nhất, được ghi vào ``document_fields.rule_id`` để truy vết.
        field_name: Tên trường nghiệp vụ trong ``Document``.
        strategy: ``flat_regex`` | ``text_regex`` | ``label_right``.
        pattern: Regex (với hai chiến lược regex).
        label: Nhãn cần định vị (với ``label_right``).
        value_pattern: Regex bóc giá trị khỏi chuỗi bên phải nhãn.
        value_type: Kiểu dữ liệu đích.
        group: Nhóm bắt trong regex, mặc định 1.
        occurrence: Lấy lần khớp thứ mấy (1-based).
        on_multiple: Xử lý khi có nhiều lần khớp khác giá trị nhau.
        required: Thiếu trường này thì chứng từ bị đánh dấu cần kiểm tra.
        flags: Cờ regex.
    """

    rule_id: str
    field_name: str
    strategy: str
    value_type: str
    pattern: str | None = None
    label: str | None = None
    value_pattern: str | None = None
    group: int = 1
    occurrence: int | None = None
    on_multiple: str = "first"
    required: bool = False
    flags: int = 0

    @property
    def compiled(self) -> re.Pattern[str] | None:
        """Regex đã biên dịch, ``None`` với chiến lược ``label_right`` không có pattern."""
        if self.pattern is None:
            return None
        return re.compile(self.pattern, self.flags)

    @property
    def compiled_value(self) -> re.Pattern[str] | None:
        if self.value_pattern is None:
            return None
        return re.compile(self.value_pattern, self.flags)


@dataclass(frozen=True)
class MerchantConfig:
    """Cấu hình nhận diện reference của nhà cung cấp trong diễn giải ngân hàng."""

    anchors: tuple[str, ...]
    expected_suffix: str | None


@dataclass(frozen=True)
class ExtractionConfig:
    """Toàn bộ luật trích xuất, gom theo loại chứng từ."""

    rules_by_type: dict[DocumentType, tuple[FieldRule, ...]]
    money_formats: dict[DocumentType, MoneyFormat]
    merchant: MerchantConfig

    def rules_for(self, document_type: DocumentType) -> tuple[FieldRule, ...]:
        return self.rules_by_type.get(document_type, ())

    def money_format_for(self, document_type: DocumentType) -> MoneyFormat:
        try:
            return self.money_formats[document_type]
        except KeyError as exc:
            raise ConfigError(
                f"Chưa khai báo money_format cho {document_type.value}. "
                "Không được đoán dấu phân cách hàng nghìn."
            ) from exc

    def labels_for(self, document_type: DocumentType) -> tuple[str, ...]:
        """Các nhãn cần định vị toạ độ khi đọc PDF của loại chứng từ này."""
        return tuple(
            r.label for r in self.rules_for(document_type) if r.strategy == "label_right" and r.label
        )

    @property
    def all_labels(self) -> tuple[str, ...]:
        labels: list[str] = []
        for document_type in self.rules_by_type:
            labels.extend(self.labels_for(document_type))
        return tuple(dict.fromkeys(labels))


def _parse_flags(raw: Any, rule_id: str) -> int:
    flags = 0
    for name in raw or ():
        try:
            flags |= _REGEX_FLAGS[str(name).upper()]
        except KeyError as exc:
            raise ConfigError(f"Cờ regex không hỗ trợ ở rule {rule_id}: {name}") from exc
    return flags


def load_extraction_config(path: Path | None = None) -> ExtractionConfig:
    """Nạp ``extraction_rules.yaml``.

    Args:
        path: Đường dẫn file; mặc định ``config/extraction_rules.yaml``.

    Returns:
        ``ExtractionConfig`` đã kiểm tra, mọi regex đã biên dịch thử.

    Raises:
        ConfigError: Regex sai cú pháp, chiến lược lạ, hoặc thiếu trường.
    """
    path = path or DEFAULT_CONFIG_DIR / "extraction_rules.yaml"
    data = _read_yaml(path)

    money_formats: dict[DocumentType, MoneyFormat] = {}
    for name, cfg in (data.get("money_format") or {}).items():
        try:
            document_type = DocumentType(name)
        except ValueError as exc:
            raise ConfigError(f"money_format có loại lạ: {name}") from exc
        try:
            money_formats[document_type] = MoneyFormat(
                thousands=str(cfg["thousands"]),
                decimal=str(cfg["decimal"]),
                currency_symbols=tuple(cfg.get("currency_symbols") or ()),
            )
        except (KeyError, ValueError) as exc:
            raise ConfigError(f"money_format của {name} không hợp lệ: {exc}") from exc

    merchant_raw = data.get("merchant") or {}
    merchant = MerchantConfig(
        anchors=tuple(merchant_raw.get("anchors") or ("FACEBK",)),
        expected_suffix=merchant_raw.get("expected_suffix"),
    )

    rules_by_type: dict[DocumentType, tuple[FieldRule, ...]] = {}
    for name, cfg in (data.get("types") or {}).items():
        try:
            document_type = DocumentType(name)
        except ValueError as exc:
            raise ConfigError(f"types có loại lạ: {name}") from exc
        default_strategy = str(cfg.get("default_strategy", "flat_regex"))
        rules: list[FieldRule] = []
        for raw in cfg.get("rules") or ():
            rules.append(_build_rule(raw, default_strategy, path))
        rules_by_type[document_type] = tuple(rules)

    config = ExtractionConfig(
        rules_by_type=rules_by_type,
        money_formats=money_formats,
        merchant=merchant,
    )
    logger.debug(
        "Đã nạp %d loại chứng từ, %d rule trích xuất",
        len(rules_by_type),
        sum(len(v) for v in rules_by_type.values()),
    )
    return config


def _build_rule(raw: dict[str, Any], default_strategy: str, path: Path) -> FieldRule:
    rule_id = str(raw.get("id") or "")
    if not rule_id:
        raise ConfigError(f"Có rule thiếu 'id' trong {path}")
    field_name = str(raw.get("field") or "")
    if not field_name:
        raise ConfigError(f"Rule {rule_id} thiếu 'field'")

    strategy = str(raw.get("strategy") or default_strategy)
    if strategy not in _VALID_STRATEGIES:
        raise ConfigError(f"Rule {rule_id} có strategy lạ: {strategy}")

    value_type = str(raw.get("type") or "text")
    if value_type not in _VALID_TYPES:
        raise ConfigError(f"Rule {rule_id} có type lạ: {value_type}")

    on_multiple = str(raw.get("on_multiple") or "first")
    if on_multiple not in _VALID_ON_MULTIPLE:
        raise ConfigError(f"Rule {rule_id} có on_multiple lạ: {on_multiple}")

    flags = _parse_flags(raw.get("flags"), rule_id)
    rule = FieldRule(
        rule_id=rule_id,
        field_name=field_name,
        strategy=strategy,
        value_type=value_type,
        pattern=raw.get("pattern"),
        label=raw.get("label"),
        value_pattern=raw.get("value_pattern"),
        group=int(raw.get("group", 1)),
        occurrence=int(raw["occurrence"]) if raw.get("occurrence") is not None else None,
        on_multiple=on_multiple,
        required=bool(raw.get("required", False)),
        flags=flags,
    )

    if strategy in {"flat_regex", "text_regex"} and not rule.pattern:
        raise ConfigError(f"Rule {rule_id} dùng {strategy} nhưng thiếu 'pattern'")
    if strategy == "label_right" and not rule.label:
        raise ConfigError(f"Rule {rule_id} dùng label_right nhưng thiếu 'label'")

    # Biên dịch thử ngay lúc nạp để lỗi regex lộ ra sớm.
    try:
        rule.compiled
        rule.compiled_value
    except re.error as exc:
        raise ConfigError(f"Rule {rule_id} có regex sai cú pháp: {exc}") from exc
    return rule


# ---------------------------------------------------------------- settings


@dataclass
class AppSettings:
    """Cấu hình vận hành đọc từ ``app_settings.yaml``."""

    min_chars_per_page: int = 80
    ocr_enabled: bool = False
    ocr_engine: str = "none"
    max_workers: int = 4
    reference_pattern: str = r"^[A-Z0-9]{8,16}$"
    strip_inner_whitespace: bool = True
    max_date_gap_days: int = 7
    amount_chain_tolerance: int = 0
    log_level: str = "INFO"
    raw: dict[str, Any] = field(default_factory=dict)


def load_app_settings(path: Path | None = None) -> AppSettings:
    """Nạp ``app_settings.yaml``.

    Args:
        path: Đường dẫn file; mặc định ``config/app_settings.yaml``.

    Returns:
        ``AppSettings``. Trường thiếu sẽ dùng giá trị mặc định an toàn.
    """
    path = path or DEFAULT_CONFIG_DIR / "app_settings.yaml"
    data = _read_yaml(path)
    processing = data.get("processing") or {}
    reference = data.get("reference") or {}
    validation = data.get("validation") or {}
    logging_cfg = data.get("logging") or {}

    pattern = str(reference.get("pattern") or r"^[A-Z0-9]{8,16}$")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ConfigError(f"reference.pattern sai cú pháp: {exc}") from exc

    return AppSettings(
        min_chars_per_page=int(processing.get("min_chars_per_page", 80)),
        ocr_enabled=bool(processing.get("ocr_enabled", False)),
        ocr_engine=str(processing.get("ocr_engine", "none")),
        max_workers=int(processing.get("max_workers", 4)),
        reference_pattern=pattern,
        strip_inner_whitespace=bool(reference.get("strip_inner_whitespace", True)),
        max_date_gap_days=int(validation.get("max_date_gap_days", 7)),
        amount_chain_tolerance=int(validation.get("amount_chain_tolerance", 0)),
        log_level=str(logging_cfg.get("level", "INFO")),
        raw=data,
    )


# ------------------------------------------------------------- accounting.yaml


@dataclass(frozen=True)
class SupplierConfig:
    """Một nhà cung cấp khai báo trong ``accounting.yaml`` — dùng làm
    "Đối tượng Có" khi xuất MISA (Q22: đối tượng là MÃ SỐ THUẾ)."""

    object_code: str
    name: str


@dataclass(frozen=True)
class AccountingPolicy:
    """Chính sách kế toán — app chỉ LÀM THEO, không tự quyết định (§23)."""

    withhold_foreign_contractor_tax: bool
    deduct_meta_input_vat: bool
    book_bank_fee: bool
    deduct_bank_fee_input_vat: bool
    export_payment_entry: bool
    recompute_vat_from_rate: bool


@dataclass(frozen=True)
class AccountingConfig:
    """Toàn bộ ``config/accounting.yaml`` đã kiểm tra.

    Attributes:
        company_name: Tên công ty, hiển thị trên chứng từ MISA.
        company_tax_code: MST công ty đã chuẩn hoá (chỉ chữ số), dùng đối
            chiếu ``TAX_CODE_MISMATCH``. ``None`` nếu chưa cấu hình.
        accounts: Ánh xạ tên tài khoản -> mã tài khoản, ví dụ
            ``{"marketing_expense": "6417"}``.
        suppliers: Ánh xạ tên nhà cung cấp -> ``SupplierConfig``.
        policy: Cờ chính sách kế toán.
    """

    company_name: str
    company_tax_code: str | None
    accounts: dict[str, str]
    suppliers: dict[str, SupplierConfig]
    policy: AccountingPolicy

    def account(self, name: str) -> str:
        """Lấy mã tài khoản theo tên, báo lỗi rõ ràng nếu thiếu."""
        try:
            return self.accounts[name]
        except KeyError as exc:
            raise ConfigError(
                f"accounting.yaml thiếu tài khoản '{name}' trong mục accounts"
            ) from exc

    def supplier(self, name: str) -> SupplierConfig:
        try:
            return self.suppliers[name]
        except KeyError as exc:
            raise ConfigError(
                f"accounting.yaml thiếu nhà cung cấp '{name}' trong mục suppliers"
            ) from exc


def load_accounting_config(path: Path | None = None) -> AccountingConfig:
    """Nạp ``config/accounting.yaml``.

    Args:
        path: Đường dẫn file; mặc định ``config/accounting.yaml``.

    Returns:
        ``AccountingConfig`` đã kiểm tra.

    Raises:
        ConfigError: Thiếu mục bắt buộc.
    """
    from app.core.text_normalizer import normalize_tax_code

    path = path or DEFAULT_CONFIG_DIR / "accounting.yaml"
    data = _read_yaml(path)

    company = data.get("company") or {}
    accounts_raw = data.get("accounts") or {}
    if not accounts_raw:
        raise ConfigError(f"{path} thiếu mục 'accounts'")
    accounts = {str(k): str(v) for k, v in accounts_raw.items()}

    suppliers_raw = data.get("suppliers") or {}
    suppliers: dict[str, SupplierConfig] = {}
    for name, cfg in suppliers_raw.items():
        if "object_code" not in cfg:
            raise ConfigError(f"suppliers.{name} thiếu 'object_code'")
        suppliers[name] = SupplierConfig(
            object_code=str(cfg["object_code"]), name=str(cfg.get("name", name))
        )

    policy_raw = data.get("policy") or {}
    policy = AccountingPolicy(
        withhold_foreign_contractor_tax=bool(policy_raw.get("withhold_foreign_contractor_tax", False)),
        deduct_meta_input_vat=bool(policy_raw.get("deduct_meta_input_vat", False)),
        book_bank_fee=bool(policy_raw.get("book_bank_fee", False)),
        deduct_bank_fee_input_vat=bool(policy_raw.get("deduct_bank_fee_input_vat", False)),
        export_payment_entry=bool(policy_raw.get("export_payment_entry", False)),
        recompute_vat_from_rate=bool(policy_raw.get("recompute_vat_from_rate", False)),
    )

    raw_tax_code = company.get("tax_code") or None
    return AccountingConfig(
        company_name=str(company.get("name", "")),
        company_tax_code=normalize_tax_code(raw_tax_code) if raw_tax_code else None,
        accounts=accounts,
        suppliers=suppliers,
        policy=policy,
    )


# ------------------------------------------------------------ misa_mapping.yaml

#: Khớp ``${accounts.xxx}`` hoặc ``${parameters.xxx}`` — chỉ giải quyết ở
#: LÚC NẠP CONFIG. Không khớp ``${meta.xxx}``/``${bank_vat.xxx}``/``${debit.xxx}``
#: vì hai namespace đó chỉ có giá trị THẬT tại lúc xuất Excel (theo từng dossier).
_STATIC_PLACEHOLDER_RE = re.compile(r"\$\{(accounts|parameters)\.([A-Za-z0-9_]+)\}")


def _resolve_static_placeholders(text: str, accounts: dict[str, str], parameters: dict[str, str]) -> str:
    """Thay ``${accounts.X}``/``${parameters.X}`` bằng giá trị thật lúc nạp config."""

    namespaces = {"accounts": accounts, "parameters": parameters}

    def _sub(match: re.Match[str]) -> str:
        ns, key = match.group(1), match.group(2)
        try:
            return str(namespaces[ns][key])
        except KeyError as exc:
            raise ConfigError(f"Không giải quyết được placeholder ${{{ns}.{key}}}") from exc

    return _STATIC_PLACEHOLDER_RE.sub(_sub, text)


@dataclass(frozen=True)
class MisaVoucherNumberConfig:
    """Quy tắc đánh Số chứng từ MISA — xem Q21: số bắt đầu do người dùng nhập."""

    prefix: str
    digits: int
    start: int | None
    increment: int

    def format(self, sequence: int) -> str:
        return f"{self.prefix}{sequence:0{self.digits}d}"


@dataclass(frozen=True)
class MisaLineRule:
    """Một dòng bút toán MISA sinh ra từ một dossier ``VALID``.

    Attributes:
        rule_id: Định danh, ví dụ ``meta_ad_expense``.
        enabled: Dòng có được sinh ra không — tắt khi chưa xác nhận nghiệp vụ.
        condition: Biểu thức Python hạn chế, chỉ được tham chiếu ``meta``,
            ``debit``, ``bank_vat`` (thuộc tính = tên trường, ví dụ
            ``meta.subtotal is not None``). Không có tên nào khác lọt vào
            namespace khi eval — xem ``MisaExporter._evaluate``.
        debit_account / credit_account: Mã tài khoản, ĐÃ resolve từ
            ``${accounts.*}``/``${parameters.*}`` lúc nạp config.
        amount_expr: Biểu thức lấy số tiền, dạng ``"<role>.<field>"``.
        credit_object: Mã đối tượng Có, đã resolve tĩnh (có thể ``None``).
        description_template: Mẫu diễn giải — phần ``${accounts.*}``/
            ``${parameters.*}`` đã resolve, còn lại ``${meta.xxx}`` /
            ``${bank_vat.xxx}`` chờ resolve theo từng dossier lúc xuất.
    """

    rule_id: str
    enabled: bool
    condition: str
    debit_account: str
    credit_account: str
    amount_expr: str
    credit_object: str | None
    description_template: str


@dataclass(frozen=True)
class MisaColumn:
    """Một trong 34 cột của file import MISA — thứ tự PHẢI giữ nguyên."""

    header: str
    source: str | None
    number_format: str | None = None


@dataclass(frozen=True)
class MisaMappingConfig:
    """Toàn bộ ``config/misa_mapping.yaml`` đã kiểm tra và resolve tĩnh."""

    sheet_name: str
    header_row: int
    cost_center_label: str
    voucher_number: MisaVoucherNumberConfig
    supplier_object_code: str
    lines: tuple[MisaLineRule, ...]
    columns: tuple[MisaColumn, ...]


def load_misa_mapping_config(
    accounting: AccountingConfig, path: Path | None = None
) -> MisaMappingConfig:
    """Nạp ``config/misa_mapping.yaml``, resolve placeholder tĩnh.

    Args:
        accounting: Cấu hình kế toán đã nạp — cung cấp namespace ``accounts``
            cho placeholder ``${accounts.*}``.
        path: Đường dẫn file; mặc định ``config/misa_mapping.yaml``.

    Returns:
        ``MisaMappingConfig`` — mọi ``${accounts.*}``/``${parameters.*}`` đã
        thay bằng giá trị thật; ``${meta.*}``/``${bank_vat.*}``/``${debit.*}``
        vẫn còn nguyên, chờ resolve theo từng dossier lúc xuất Excel.

    Raises:
        ConfigError: Thiếu mục bắt buộc hoặc placeholder không giải quyết được.
    """
    path = path or DEFAULT_CONFIG_DIR / "misa_mapping.yaml"
    data = _read_yaml(path)

    params_raw = data.get("parameters") or {}
    parameters = {
        k: v for k, v in params_raw.items() if not isinstance(v, dict)
    }

    voucher_raw = params_raw.get("voucher_number") or {}
    voucher_number = MisaVoucherNumberConfig(
        prefix=str(voucher_raw.get("prefix", "")),
        digits=int(voucher_raw.get("digits", 6)),
        start=int(voucher_raw["start"]) if voucher_raw.get("start") is not None else None,
        increment=int(voucher_raw.get("increment", 1)),
    )

    def resolve(text: str | None) -> str | None:
        if text is None:
            return None
        return _resolve_static_placeholders(str(text), accounting.accounts, parameters)

    lines: list[MisaLineRule] = []
    for raw in data.get("lines") or ():
        rule_id = str(raw.get("id") or "")
        if not rule_id:
            raise ConfigError(f"{path}: có dòng MISA thiếu 'id'")
        lines.append(
            MisaLineRule(
                rule_id=rule_id,
                enabled=bool(raw.get("enabled", True)),
                condition=str(raw.get("condition", "True")),
                debit_account=resolve(raw.get("debit_account")) or "",
                credit_account=resolve(raw.get("credit_account")) or "",
                amount_expr=str(raw.get("amount") or ""),
                credit_object=resolve(raw.get("credit_object")),
                description_template=resolve(raw.get("description")) or "",
            )
        )
        if not lines[-1].amount_expr:
            raise ConfigError(f"Dòng MISA {rule_id} thiếu 'amount'")

    columns: list[MisaColumn] = []
    for raw in data.get("columns") or ():
        header = str(raw.get("header") or "")
        if not header:
            raise ConfigError(f"{path}: có cột thiếu 'header'")
        columns.append(
            MisaColumn(
                header=header,
                source=raw.get("source"),
                number_format=raw.get("format"),
            )
        )
    if len(columns) != 34:
        logger.warning(
            "misa_mapping.yaml có %d cột, khác 34 cột của mẫu MISA SME 2023 thật", len(columns)
        )

    return MisaMappingConfig(
        sheet_name=str(data.get("sheet_name") or "Chứng từ nghiệp vụ khác"),
        header_row=int(data.get("header_row", 1)),
        cost_center_label=str(parameters.get("cost_center_label", "")),
        voucher_number=voucher_number,
        supplier_object_code=str(parameters.get("supplier_object_code", "")),
        lines=tuple(lines),
        columns=tuple(columns),
    )
