"""Transparent delinquency risk scoring.

A weighted, additive score in [0, 1]. Every point of the score is
attributable to a named feature — ``contributions`` sum exactly to the
score (within float tolerance) and ``top_factors`` ranks them. There is
no black box: the weights table below IS the model, and it is printed in
the README so a collections strategist can argue with it.

Weight budget (sums to 1.00 at the maximum of every feature):
  credit_score_band  0.30   strongest single predictor in the book
  days_past_due      0.25   current delinquency is the loudest signal
  missed_payments    0.20   payment history
  dti_ratio          0.15   leverage / affordability stress
  income_band        0.05   cushion against shocks
  apr                0.05   priced-in risk (and payment burden)
"""

from __future__ import annotations

import math
from typing import Dict, List

CREDIT_CONTRIBUTION = {"poor": 0.30, "fair": 0.20, "good": 0.10,
                       "very_good": 0.04, "excellent": 0.0}
INCOME_CONTRIBUTION = {"low": 0.05, "lower_mid": 0.03, "mid": 0.015,
                       "upper_mid": 0.005, "high": 0.0}

WEIGHTS = {
    "credit_score_band": 0.30,
    "days_past_due": 0.25,
    "missed_payments": 0.20,
    "dti_ratio": 0.15,
    "income_band": 0.05,
    "apr": 0.05,
}


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


def contributions_for(loan: Dict) -> Dict[str, float]:
    """Per-feature contributions; keys match WEIGHTS, values in [0, w]."""
    credit = CREDIT_CONTRIBUTION.get(str(loan.get("credit_score_band", "")), 0.10)
    dpd = min(int(loan.get("days_past_due", 0) or 0), 90) / 90.0 * 0.25
    missed = min(int(loan.get("missed_payments", 0) or 0), 6) / 6.0 * 0.20
    dti_raw = float(loan.get("dti_ratio", 0.0) or 0.0)
    dti = _clamp01((dti_raw - 0.20) / 0.50) * 0.15
    income = INCOME_CONTRIBUTION.get(str(loan.get("income_band", "")), 0.015)
    apr_raw = float(loan.get("apr", 0.0) or 0.0)
    apr = _clamp01((apr_raw - 5.0) / 25.0) * 0.05
    return {
        "credit_score_band": round(credit, 6),
        "days_past_due": round(dpd, 6),
        "missed_payments": round(missed, 6),
        "dti_ratio": round(dti, 6),
        "income_band": round(income, 6),
        "apr": round(apr, 6),
    }


def risk_score(loan: Dict) -> float:
    """Additive score in [0, 1]; higher = more likely to roll deeper."""
    return round(_clamp01(sum(contributions_for(loan).values())), 6)


def tier_for_score(score: float) -> str:
    if score >= 0.75:
        return "D"
    if score >= 0.50:
        return "C"
    if score >= 0.25:
        return "B"
    return "A"


def score_loan(loan: Dict) -> Dict:
    contrib = contributions_for(loan)
    score = round(_clamp01(sum(contrib.values())), 6)
    ranked = sorted(contrib.items(), key=lambda kv: (-kv[1], kv[0]))
    top = [{"factor": k, "contribution": v} for k, v in ranked if v > 0][:3]
    return {
        "loan_id": loan.get("loan_id"),
        "risk_score": score,
        "tier": tier_for_score(score),
        "contributions": contrib,
        "top_factors": top,
    }


def score_portfolio(loans: List[Dict]) -> List[Dict]:
    return [score_loan(loan) for loan in loans]


def logistic_check(score: float) -> float:
    """Logistic-style squashing kept for reference / calibration checks.

    The production score stays additive (explainability sums must hold);
    this helper documents the logistic view: p = 1/(1+e^-(k*(s-0.5))).
    It is monotonic in ``score`` and maps 0.5 -> 0.5.
    """
    return 1.0 / (1.0 + math.exp(-8.0 * (score - 0.5)))
