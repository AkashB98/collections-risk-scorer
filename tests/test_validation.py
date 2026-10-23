import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import loan
from generator import generate_loans
from validation import validate_loan, validate_portfolio


class TestValidation(unittest.TestCase):
    def test_clean_loan_passes(self):
        self.assertEqual(validate_loan(loan()), [])

    def test_generated_portfolio_clean(self):
        self.assertEqual(validate_portfolio(generate_loans(200, seed=42)), [])

    def test_empty_portfolio_flagged(self):
        self.assertTrue(validate_portfolio([]))

    def test_missing_field(self):
        bad = loan()
        del bad["apr"]
        issues = validate_loan(bad)
        self.assertTrue(any("apr" in i for i in issues))

    def test_empty_string_field_is_missing(self):
        issues = validate_loan(loan(region=""))
        self.assertTrue(any("region" in i for i in issues))

    def test_invalid_bands(self):
        for field, value in (("credit_score_band", "terrible"),
                             ("income_band", "rich"),
                             ("borrower_age_band", "teen"),
                             ("collateral_type", "crypto"),
                             ("region", "Moon")):
            issues = validate_loan(loan(**{field: value}))
            self.assertTrue(any(field in i for i in issues), (field, issues))

    def test_negative_and_zero_amounts(self):
        self.assertTrue(validate_loan(loan(loan_amount=0)))
        self.assertTrue(validate_loan(loan(loan_amount=-5)))
        self.assertTrue(validate_loan(loan(balance=-1)))

    def test_balance_implausibly_above_amount(self):
        self.assertTrue(validate_loan(loan(loan_amount=1000.0, balance=5000.0)))
        # Balance modestly above amount (fees/interest) is tolerated.
        self.assertEqual(validate_loan(loan(loan_amount=1000.0, balance=1200.0)), [])

    def test_dti_range(self):
        self.assertTrue(validate_loan(loan(dti_ratio=1.2)))
        self.assertTrue(validate_loan(loan(dti_ratio=-0.1)))
        self.assertEqual(validate_loan(loan(dti_ratio=1.0)), [])

    def test_apr_range(self):
        self.assertTrue(validate_loan(loan(apr=45.0)))
        self.assertTrue(validate_loan(loan(apr=-1.0)))

    def test_dpd_and_missed_types(self):
        self.assertTrue(validate_loan(loan(days_past_due=-1)))
        self.assertTrue(validate_loan(loan(days_past_due=400)))
        self.assertTrue(validate_loan(loan(missed_payments=-1)))
        self.assertTrue(validate_loan(loan(days_past_due=True)))

    def test_bool_is_not_a_number(self):
        self.assertTrue(validate_loan(loan(loan_amount=True)))

    def test_origination_month_format(self):
        self.assertTrue(validate_loan(loan(origination_month="June 2025")))
        self.assertTrue(validate_loan(loan(origination_month="2025/06")))
        self.assertEqual(validate_loan(loan(origination_month="2025-06")), [])

    def test_term_months_positive(self):
        self.assertTrue(validate_loan(loan(term_months=0)))
        self.assertTrue(validate_loan(loan(term_months=-12)))

    def test_duplicate_loan_ids(self):
        issues = validate_portfolio([loan(loan_id="NL-DUP"), loan(loan_id="NL-DUP")])
        self.assertTrue(any("duplicate" in i for i in issues))

    def test_issues_name_the_loan(self):
        issues = validate_loan(loan(loan_id="NL-BAD9", apr=99.0))
        self.assertTrue(all(i.startswith("NL-BAD9") for i in issues))


if __name__ == "__main__":
    unittest.main()
