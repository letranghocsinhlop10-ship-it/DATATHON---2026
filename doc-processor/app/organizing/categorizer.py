"""Document Classifier (2nd pass) / Categorizer stage.

Rolls everything the pipeline learned about a DocumentSet (completeness,
reconciliation, validation) into:
- a full `issues` list (kept for the Excel report — a set can have
  several issues at once), and
- a single `category` folder id, chosen by the configurable priority
  order in config/settings.yaml `categorizer.priority` — first match
  wins, so the most severe problem decides where the folder physically
  lives, without losing the other issues from the report.
"""
from __future__ import annotations

from app.core.config_loader import get_settings
from app.models.schema import CheckResult, CompletenessStatus, DocumentSet, MatchResult


def _collect_issues(ds: DocumentSet) -> list[str]:
    issues = list(ds.issues)  # matcher already may have set ERROR/DUPLICATE/INCOMPLETE/MISSING_REFERENCE

    def add(issue: str) -> None:
        if issue not in issues:
            issues.append(issue)

    for item in ds.validation:
        if item.rule_id == "TAX_CODE_PRESENT" and item.result == CheckResult.FAIL:
            add("MISSING_TAX_CODE")
        if item.rule_id == "PAYMENT_METHOD_PRESENT" and item.result == CheckResult.FAIL:
            add("PAYMENT_METHOD_ERROR")
        if item.rule_id == "REFERENCE_PRESENT" and item.result == CheckResult.FAIL:
            add("MISSING_REFERENCE")

    amount_recon = ds.reconciliation.get("amount")
    # PARTIAL_MATCH here means "2 of 3 docs agree, 1 doesn't" — still a real
    # discrepancy worth an accountant's attention, not just full MISMATCH.
    if amount_recon and amount_recon.result in (MatchResult.MISMATCH, MatchResult.PARTIAL_MATCH):
        add("AMOUNT_MISMATCH")

    if ds.completeness == CompletenessStatus.INCOMPLETE:
        add("INCOMPLETE")
    if ds.completeness == CompletenessStatus.DUPLICATE:
        add("DUPLICATE")
    if ds.completeness == CompletenessStatus.ERROR:
        add("ERROR")

    return issues


def categorize(ds: DocumentSet) -> DocumentSet:
    priority = get_settings().get("categorizer", {}).get("priority", [])

    ds.issues = _collect_issues(ds)

    category = None
    for entry in priority:
        when_issue = entry["when_issue"]
        if when_issue == "__default_valid__" or when_issue in ds.issues:
            category = entry["id"]
            break

    ds.category = category or "08_OTHER_ERROR"
    return ds
