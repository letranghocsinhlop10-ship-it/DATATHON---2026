"""Validation Engine stage.

Runs the configurable rule list in config/validation_rules.yaml against
a DocumentSet, producing one ValidationItem per rule (PASS / FAIL /
WARNING / NOT_FOUND) plus an overall DocumentStatus rollup.

Two rule `type`s:
- "generic_presence": checks that `attr` is non-empty on at least one of
  the given `roles`' documents. Covers most of spec section 4's "mở
  rộng thêm" criteria — adding a new one is a YAML edit, no code change.
- "special": needs bespoke logic (reference/tax-code-format/
  set-completeness/reconciliation-mismatch) — see RESOLVERS below.
"""
from __future__ import annotations

from typing import Callable

from app.core.config_loader import get_validation_rules
from app.core.logging_config import get_logger
from app.extraction.base import is_standard_vn_tax_code
from app.models.schema import CheckResult, DocumentSet, DocumentStatus, MatchResult, ValidationItem
from app.reconciliation.engine import reconcile

log = get_logger("validation")


def _generic_presence(ds: DocumentSet, rule: dict) -> tuple[CheckResult, str | None]:
    roles = rule.get("roles", ["facebook", "vat_invoice", "bank_debit"])
    attr = rule["attr"]
    any_present = any(getattr(ds, r, None) is not None for r in roles)
    if not any_present:
        return CheckResult.NOT_FOUND, f"Không có chứng từ nào trong {roles} để kiểm tra"

    for r in roles:
        doc = getattr(ds, r, None)
        if doc is not None and getattr(doc, attr, None) not in (None, "", []):
            return CheckResult.PASS, None

    severity = rule.get("severity", "WARNING")
    result = CheckResult.FAIL if severity == "FAIL" else CheckResult.WARNING
    return result, f"Không trích xuất được '{attr}' từ {roles}"


def _resolve_reference_present(ds: DocumentSet, rule: dict) -> tuple[CheckResult, str | None]:
    is_synthetic = ds.reference.startswith(("NOREF__", "ERROR__"))
    if is_synthetic:
        return CheckResult.FAIL, "Không nhận diện được số tham chiếu trên bộ chứng từ"
    return CheckResult.PASS, None


def _resolve_tax_code_format(ds: DocumentSet, rule: dict) -> tuple[CheckResult, str | None]:
    tax_code = None
    for role in ("facebook", "vat_invoice"):
        doc = getattr(ds, role, None)
        if doc is not None and doc.tax_code:
            tax_code = doc.tax_code
            break
    if not tax_code:
        return CheckResult.NOT_FOUND, "Chưa có mã số thuế để kiểm tra định dạng"
    if is_standard_vn_tax_code(tax_code):
        return CheckResult.PASS, None
    return CheckResult.WARNING, f"Mã số thuế '{tax_code}' không đúng định dạng chuẩn VN (có thể là MST nhà thầu nước ngoài)"


def _resolve_set_complete(ds: DocumentSet, rule: dict) -> tuple[CheckResult, str | None]:
    # Checked directly off slot presence (not the `completeness` enum) so
    # this rule stays correct even if a DocumentSet is constructed without
    # going through the reference matcher (e.g. in tests, or a future
    # caller) — one source of truth instead of two fields that could drift.
    missing = [
        name
        for name, role in (("Facebook bill", "facebook"), ("Hóa đơn VAT", "vat_invoice"), ("Giấy báo nợ NH", "bank_debit"))
        if getattr(ds, role, None) is None
    ]
    if not missing:
        return CheckResult.PASS, None
    return CheckResult.FAIL, f"Thiếu: {', '.join(missing)}"


def _resolve_no_reconciliation_mismatch(ds: DocumentSet, rule: dict) -> tuple[CheckResult, str | None]:
    if not ds.reconciliation:
        ds.reconciliation = reconcile(ds)
    mismatches = [k for k, v in ds.reconciliation.items() if v.result == MatchResult.MISMATCH]
    partials = [k for k, v in ds.reconciliation.items() if v.result == MatchResult.PARTIAL_MATCH]
    if mismatches:
        return CheckResult.FAIL, f"MISMATCH ở: {', '.join(mismatches)}"
    if partials:
        return CheckResult.WARNING, f"PARTIAL_MATCH ở: {', '.join(partials)}"
    return CheckResult.PASS, None


_RESOLVERS: dict[str, Callable[[DocumentSet, dict], tuple[CheckResult, str | None]]] = {
    "reference_present": _resolve_reference_present,
    "tax_code_format": _resolve_tax_code_format,
    "set_complete": _resolve_set_complete,
    "no_reconciliation_mismatch": _resolve_no_reconciliation_mismatch,
}


def validate(ds: DocumentSet) -> list[ValidationItem]:
    rules = get_validation_rules().get("rules", [])
    items: list[ValidationItem] = []

    for rule in rules:
        rule_type = rule.get("type", "generic_presence")
        try:
            if rule_type == "special":
                resolver = _RESOLVERS.get(rule["resolver"])
                if resolver is None:  # pragma: no cover - config typo guard
                    log.warning("Không tìm thấy resolver '%s' cho rule %s", rule.get("resolver"), rule["id"])
                    result, detail = CheckResult.NOT_FOUND, "Resolver không tồn tại"
                else:
                    result, detail = resolver(ds, rule)
            else:
                result, detail = _generic_presence(ds, rule)
        except Exception as exc:  # pragma: no cover - defensive, one bad rule shouldn't kill the batch
            log.exception("Lỗi khi chạy validation rule %s", rule.get("id"))
            result, detail = CheckResult.NOT_FOUND, f"Lỗi khi kiểm tra: {exc}"

        items.append(
            ValidationItem(
                rule_id=rule["id"],
                field=rule.get("attr", rule.get("resolver", rule["id"])),
                result=result,
                severity=rule.get("severity", "WARNING"),
                detail=detail,
            )
        )

    return items


def overall_status(items: list[ValidationItem]) -> DocumentStatus:
    rollup = get_validation_rules().get("status_rollup", {})
    has_fail = any(i.result == CheckResult.FAIL for i in items)
    has_warning = any(i.result == CheckResult.WARNING for i in items)

    if has_fail and rollup.get("invalid_if_any_fail", True):
        return DocumentStatus.INVALID
    if has_warning and rollup.get("needs_review_if_any_warning", True):
        return DocumentStatus.NEEDS_REVIEW
    return DocumentStatus.VALID


def validate_and_score(ds: DocumentSet) -> DocumentSet:
    """Runs validation + reconciliation (if not already done) and stores
    the results back onto the DocumentSet, per the pipeline order:
    Reconciliation Engine -> Validation Engine."""
    if not ds.reconciliation:
        ds.reconciliation = reconcile(ds)
    ds.validation = validate(ds)
    ds.document_status = overall_status(ds.validation)
    return ds
