"""Shared loan builders for the test suite (not a test module)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def loan(**overrides):
    base = {
        "loan_id": "NL-TEST01",
        "borrower_age_band": "35-44",
        "income_band": "mid",
        "loan_amount": 10000.0,
        "term_months": 36,
        "apr": 10.0,
        "credit_score_band": "good",
        "dti_ratio": 0.30,
        "days_past_due": 0,
        "missed_payments": 0,
        "balance": 7000.0,
        "collateral_type": "auto",
        "region": "Midwest",
        "origination_month": "2025-06",
    }
    base.update(overrides)
    return base
