"""Data-quality validation for loan portfolio files.

Returns a list of human-readable issue strings; an empty list means the
portfolio is clean. Validation never raises on bad *data* — it reports —
so the CLI ``check`` gate can map issues to exit code 2.
"""

from __future__ import annotations

from typing import Dict, List

from generator import (AGE_BANDS, COLLATERAL_TYPES, CREDIT_BANDS,
                       INCOME_BANDS, LOAN_FIELDS, REGIONS)

REQUIRED_FIELDS = LOAN_FIELDS


def validate_loan(loan: Dict, index: int = 0) -> List[str]:
    issues: List[str] = []
    lid = loan.get("loan_id", f"<row {index}>")
    for field in REQUIRED_FIELDS:
        if field not in loan or loan[field] is None or loan[field] == "":
            issues.append(f"{lid}: missing field '{field}'")
    if issues:
        return issues

    if loan["borrower_age_band"] not in AGE_BANDS:
        issues.append(f"{lid}: invalid borrower_age_band '{loan['borrower_age_band']}'")
    if loan["income_band"] not in INCOME_BANDS:
        issues.append(f"{lid}: invalid income_band '{loan['income_band']}'")
    if loan["credit_score_band"] not in CREDIT_BANDS:
        issues.append(f"{lid}: invalid credit_score_band '{loan['credit_score_band']}'")
    if loan["collateral_type"] not in COLLATERAL_TYPES:
        issues.append(f"{lid}: invalid collateral_type '{loan['collateral_type']}'")
    if loan["region"] not in REGIONS:
        issues.append(f"{lid}: invalid region '{loan['region']}'")

    def _is_number(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    if not _is_number(loan["loan_amount"]) or loan["loan_amount"] <= 0:
        issues.append(f"{lid}: loan_amount must be > 0")
    if not _is_number(loan["balance"]) or loan["balance"] < 0:
        issues.append(f"{lid}: balance must be >= 0")
    if _is_number(loan.get("balance")) and _is_number(loan.get("loan_amount")) \
            and loan["balance"] > loan["loan_amount"] * 1.5:
        issues.append(f"{lid}: balance implausibly exceeds loan_amount")
    if not _is_number(loan["apr"]) or not (0 <= loan["apr"] <= 40):
        issues.append(f"{lid}: apr out of range [0, 40]")
    if not _is_number(loan["dti_ratio"]) or not (0 <= loan["dti_ratio"] <= 1.0):
        issues.append(f"{lid}: dti_ratio out of range [0, 1]")
    if not isinstance(loan["days_past_due"], int) or isinstance(loan["days_past_due"], bool) \
            or not (0 <= loan["days_past_due"] <= 365):
        issues.append(f"{lid}: days_past_due must be int in [0, 365]")
    if not isinstance(loan["missed_payments"], int) or isinstance(loan["missed_payments"], bool) \
            or not (0 <= loan["missed_payments"] <= 24):
        issues.append(f"{lid}: missed_payments must be int in [0, 24]")
    if not isinstance(loan["term_months"], int) or isinstance(loan["term_months"], bool) \
            or loan["term_months"] <= 0:
        issues.append(f"{lid}: term_months must be a positive int")
    om = str(loan["origination_month"])
    if len(om) != 7 or om[4] != "-" or not om[:4].isdigit() or not om[5:].isdigit():
        issues.append(f"{lid}: origination_month must be YYYY-MM")
    return issues


def validate_portfolio(loans: List[Dict]) -> List[str]:
    issues: List[str] = []
    if not loans:
        issues.append("portfolio is empty")
        return issues
    seen = set()
    for i, loan in enumerate(loans):
        issues.extend(validate_loan(loan, index=i))
        lid = loan.get("loan_id")
        if lid in seen:
            issues.append(f"{lid}: duplicate loan_id")
        seen.add(lid)
    return issues
