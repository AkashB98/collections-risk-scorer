"""Recovery-priority ranking for the collections work queue.

Only delinquent loans enter the queue (days_past_due > 0 or
missed_payments > 0). Each is ranked by expected recovery value per unit
of effort:

    priority_value = balance * recovery_probability / effort

recovery_probability falls as risk rises (a tier-D loan is less likely to
cure) but is lifted by recoverable collateral; effort rises with how deep
and how repeated the delinquency is. The ranking therefore favours large,
recoverable, not-yet-hopeless balances — the loans a collections team
should call first — over tiny or near-charge-off balances.
"""

from __future__ import annotations

from typing import Dict, List

from scorer import score_loan

COLLATERAL_RECOVERY = {"home": 0.90, "auto": 0.80, "secured_card": 0.85,
                       "personal": 0.60, "unsecured": 0.50}
DEFAULT_COLLATERAL_RECOVERY = 0.60


def recovery_probability(loan: Dict, risk_score: float) -> float:
    collateral_factor = COLLATERAL_RECOVERY.get(
        str(loan.get("collateral_type", "")), DEFAULT_COLLATERAL_RECOVERY)
    prob = (1.0 - risk_score * 0.75) * collateral_factor
    return round(min(0.95, max(0.02, prob)), 6)


def effort_estimate(loan: Dict) -> float:
    dpd = int(loan.get("days_past_due", 0) or 0)
    missed = int(loan.get("missed_payments", 0) or 0)
    effort = 1.0 + dpd / 60.0 + missed * 0.15
    if str(loan.get("collateral_type", "")) == "unsecured":
        effort += 0.30
    return round(effort, 6)


def is_delinquent(loan: Dict) -> bool:
    return int(loan.get("days_past_due", 0) or 0) > 0 or \
        int(loan.get("missed_payments", 0) or 0) > 0


def prioritize(loans: List[Dict], limit: int | None = None) -> List[Dict]:
    """Return the prioritised work queue, best first.

    Ordering: priority_value descending, loan_id ascending as the
    deterministic tie-break.
    """
    queue: List[Dict] = []
    for loan in loans:
        if not is_delinquent(loan):
            continue
        scored = score_loan(loan)
        balance = float(loan.get("balance", 0) or 0)
        rec_prob = recovery_probability(loan, scored["risk_score"])
        effort = effort_estimate(loan)
        priority_value = round(balance * rec_prob / effort, 4) if effort else 0.0
        queue.append({
            "loan_id": loan.get("loan_id"),
            "risk_score": scored["risk_score"],
            "tier": scored["tier"],
            "balance": balance,
            "days_past_due": int(loan.get("days_past_due", 0) or 0),
            "missed_payments": int(loan.get("missed_payments", 0) or 0),
            "recovery_probability": rec_prob,
            "effort": effort,
            "priority_value": priority_value,
            "expected_recovery": round(balance * rec_prob, 2),
        })
    queue.sort(key=lambda r: (-r["priority_value"], str(r["loan_id"])))
    for idx, row in enumerate(queue, start=1):
        row["rank"] = idx
    if limit is not None:
        if limit < 0:
            raise ValueError("limit must be >= 0")
        queue = queue[:limit]
    return queue
