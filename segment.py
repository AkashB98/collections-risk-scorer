"""Risk-tier segmentation and portfolio summary."""

from __future__ import annotations

from typing import Dict, List

from scorer import score_loan, tier_for_score  # noqa: F401  (re-export)

TIERS = ["A", "B", "C", "D"]
TIER_LABELS = {"A": "low", "B": "moderate", "C": "high", "D": "critical"}
# Thresholds are the single source of truth; scorer.tier_for_score mirrors
# them and a test pins the two together.
TIER_THRESHOLDS = {"B": 0.25, "C": 0.50, "D": 0.75}


def segment_portfolio(loans: List[Dict]) -> Dict:
    """Segment loans by risk tier with per-tier portfolio aggregates."""
    buckets: Dict[str, List] = {t: [] for t in TIERS}
    scored = []
    for loan in loans:
        s = score_loan(loan)
        scored.append((loan, s))
        buckets[s["tier"]].append((loan, s))

    tiers: Dict[str, Dict] = {}
    for tier in TIERS:
        rows = buckets[tier]
        count = len(rows)
        total_balance = round(sum(float(r[0].get("balance", 0) or 0) for r in rows), 2)
        avg_dpd = round(sum(int(r[0].get("days_past_due", 0) or 0) for r in rows) / count, 2) if count else 0.0
        avg_score = round(sum(r[1]["risk_score"] for r in rows) / count, 4) if count else 0.0
        delinquent = sum(1 for r in rows if int(r[0].get("days_past_due", 0) or 0) > 0)
        tiers[tier] = {
            "label": TIER_LABELS[tier],
            "count": count,
            "pct": round(count / len(loans) * 100, 2) if loans else 0.0,
            "total_balance": total_balance,
            "balance_at_risk": total_balance if tier in ("C", "D") else 0.0,
            "avg_days_past_due": avg_dpd,
            "avg_risk_score": avg_score,
            "delinquent_count": delinquent,
        }

    total_balance = round(sum(float(l.get("balance", 0) or 0) for l in loans), 2)
    at_risk = round(tiers["C"]["total_balance"] + tiers["D"]["total_balance"], 2)
    return {
        "total_loans": len(loans),
        "total_balance": total_balance,
        "balance_at_risk": at_risk,
        "tier_d_count": tiers["D"]["count"],
        "tier_d_pct": tiers["D"]["pct"],
        "tiers": tiers,
    }


def loans_by_tier(loans: List[Dict], tier: str) -> List[Dict]:
    if tier not in TIERS:
        raise ValueError(f"unknown tier: {tier}")
    return [loan for loan in loans if score_loan(loan)["tier"] == tier]
