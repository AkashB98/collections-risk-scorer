"""Deterministic synthetic loan generator — Northstar Lending (fictional).

SYNTHETIC DATA ONLY. No real borrower data is ever used. Every loan is
fabricated from a seeded PRNG so the same seed always yields the same
portfolio, byte-for-byte.

Fields per loan:
  loan_id, borrower_age_band, income_band, loan_amount, term_months, apr,
  credit_score_band, dti_ratio, days_past_due, missed_payments, balance,
  collateral_type, region, origination_month
"""

from __future__ import annotations

import random
from typing import Dict, List

AGE_BANDS = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
AGE_WEIGHTS = [0.10, 0.28, 0.26, 0.18, 0.11, 0.07]

INCOME_BANDS = ["low", "lower_mid", "mid", "upper_mid", "high"]
INCOME_WEIGHTS = [0.18, 0.24, 0.28, 0.18, 0.12]
# Representative monthly income midpoint (USD) per band — used only to
# size loan_amount / balance plausibly.
INCOME_MIDPOINT = {"low": 2200, "lower_mid": 3600, "mid": 5400,
                   "upper_mid": 7800, "high": 12500}

CREDIT_BANDS = ["poor", "fair", "good", "very_good", "excellent"]
CREDIT_WEIGHTS = [0.14, 0.26, 0.30, 0.19, 0.11]
# Base APR (%) centre per credit band.
CREDIT_APR_CENTRE = {"poor": 24.0, "fair": 17.5, "good": 11.5,
                     "very_good": 8.0, "excellent": 5.5}
# Latent delinquency propensity per credit band (drives DPD / missed).
CREDIT_PROPENSITY = {"poor": 0.72, "fair": 0.48, "good": 0.26,
                     "very_good": 0.13, "excellent": 0.05}

COLLATERAL_TYPES = ["auto", "home", "personal", "secured_card", "unsecured"]
COLLATERAL_WEIGHTS = [0.30, 0.22, 0.20, 0.08, 0.20]

REGIONS = ["Northeast", "Southeast", "Midwest", "Southwest", "West"]
REGION_WEIGHTS = [0.18, 0.24, 0.22, 0.16, 0.20]

TERM_CHOICES = [12, 24, 36, 48, 60, 72]
TERM_WEIGHTS = [0.10, 0.18, 0.30, 0.22, 0.14, 0.06]

ORIGINATION_MONTHS = [f"2025-{m:02d}" for m in range(1, 13)] + \
                     [f"2026-{m:02d}" for m in range(1, 7)]

LOAN_FIELDS = ["loan_id", "borrower_age_band", "income_band", "loan_amount",
               "term_months", "apr", "credit_score_band", "dti_ratio",
               "days_past_due", "missed_payments", "balance",
               "collateral_type", "region", "origination_month"]

DEFAULT_SEED = 42
DEFAULT_COUNT = 2000


def _weighted(rng: random.Random, items, weights):
    return rng.choices(items, weights=weights, k=1)[0]


def generate_loans(count: int = DEFAULT_COUNT, seed: int = DEFAULT_SEED) -> List[Dict]:
    """Return ``count`` synthetic loans, deterministic for ``seed``."""
    if count < 0:
        raise ValueError("count must be >= 0")
    rng = random.Random(seed)
    loans: List[Dict] = []
    for i in range(count):
        credit = _weighted(rng, CREDIT_BANDS, CREDIT_WEIGHTS)
        income = _weighted(rng, INCOME_BANDS, INCOME_WEIGHTS)
        age = _weighted(rng, AGE_BANDS, AGE_WEIGHTS)
        collateral = _weighted(rng, COLLATERAL_TYPES, COLLATERAL_WEIGHTS)
        region = _weighted(rng, REGIONS, REGION_WEIGHTS)
        term = _weighted(rng, TERM_CHOICES, TERM_WEIGHTS)
        origination = rng.choice(ORIGINATION_MONTHS)

        # DTI: poorer credit + lower income drift higher.
        dti_base = {"poor": 0.44, "fair": 0.38, "good": 0.31,
                    "very_good": 0.25, "excellent": 0.19}[credit]
        dti = round(min(0.92, max(0.05, rng.gauss(dti_base, 0.09))), 4)

        apr = round(min(36.0, max(3.0, rng.gauss(CREDIT_APR_CENTRE[credit], 1.8))), 2)

        # Loan amount sized off income and collateral.
        collateral_mult = {"home": 6.0, "auto": 3.2, "personal": 1.6,
                           "secured_card": 0.5, "unsecured": 1.2}[collateral]
        amount_centre = INCOME_MIDPOINT[income] * collateral_mult
        loan_amount = round(max(500.0, rng.gauss(amount_centre, amount_centre * 0.28)), 2)

        # Delinquency behaviour driven by a latent propensity so the
        # scorer has real signal to find (worse credit / higher DTI ->
        # more likely delinquent).
        propensity = CREDIT_PROPENSITY[credit]
        propensity += max(0.0, (dti - 0.35)) * 0.55
        if income == "low":
            propensity += 0.06
        propensity = min(0.97, max(0.01, propensity))
        roll = rng.random()
        if roll > propensity:
            days_past_due = 0
            missed = 0
        else:
            severity = rng.random()
            if severity < 0.45:
                days_past_due = rng.randint(1, 29)
                missed = rng.randint(0, 1)
            elif severity < 0.78:
                days_past_due = rng.randint(30, 59)
                missed = rng.randint(1, 2)
            elif severity < 0.93:
                days_past_due = rng.randint(60, 89)
                missed = rng.randint(2, 4)
            else:
                days_past_due = rng.randint(90, 180)
                missed = rng.randint(4, 8)

        # Balance: a paid-down fraction of the original amount; delinquent
        # loans have paid down less.
        if days_past_due == 0:
            paid_fraction = rng.uniform(0.15, 0.75)
        else:
            paid_fraction = rng.uniform(0.02, 0.45)
        balance = round(loan_amount * (1.0 - paid_fraction), 2)
        if balance < 0:
            balance = 0.0

        loans.append({
            "loan_id": f"NL-{i + 1:05d}",
            "borrower_age_band": age,
            "income_band": income,
            "loan_amount": loan_amount,
            "term_months": term,
            "apr": apr,
            "credit_score_band": credit,
            "dti_ratio": dti,
            "days_past_due": days_past_due,
            "missed_payments": missed,
            "balance": balance,
            "collateral_type": collateral,
            "region": region,
            "origination_month": origination,
        })
    return loans


def loans_to_csv(loans: List[Dict]) -> str:
    import csv
    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=LOAN_FIELDS)
    writer.writeheader()
    for loan in loans:
        writer.writerow({k: loan[k] for k in LOAN_FIELDS})
    return buf.getvalue()


def loans_to_jsonl(loans: List[Dict]) -> str:
    import json
    return "".join(json.dumps(loan, sort_keys=True) + "\n" for loan in loans)
