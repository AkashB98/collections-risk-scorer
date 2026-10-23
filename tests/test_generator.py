import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import (AGE_BANDS, COLLATERAL_TYPES, CREDIT_BANDS, INCOME_BANDS,
                       LOAN_FIELDS, REGIONS, generate_loans, loans_to_csv,
                       loans_to_jsonl)
from validation import validate_portfolio


class TestGenerator(unittest.TestCase):
    def test_default_count_and_ids(self):
        loans = generate_loans()
        self.assertEqual(len(loans), 2000)
        self.assertEqual(loans[0]["loan_id"], "NL-00001")
        self.assertEqual(loans[-1]["loan_id"], "NL-02000")

    def test_determinism_same_seed(self):
        self.assertEqual(generate_loans(200, seed=42), generate_loans(200, seed=42))

    def test_different_seed_differs(self):
        self.assertNotEqual(generate_loans(50, seed=1), generate_loans(50, seed=2))

    def test_zero_count(self):
        self.assertEqual(generate_loans(0, seed=42), [])

    def test_negative_count_raises(self):
        with self.assertRaises(ValueError):
            generate_loans(-1)

    def test_all_fields_present(self):
        for loan in generate_loans(100, seed=3):
            self.assertEqual(sorted(loan.keys()), sorted(LOAN_FIELDS))

    def test_bands_are_valid(self):
        for loan in generate_loans(300, seed=5):
            self.assertIn(loan["borrower_age_band"], AGE_BANDS)
            self.assertIn(loan["income_band"], INCOME_BANDS)
            self.assertIn(loan["credit_score_band"], CREDIT_BANDS)
            self.assertIn(loan["collateral_type"], COLLATERAL_TYPES)
            self.assertIn(loan["region"], REGIONS)

    def test_value_ranges(self):
        for loan in generate_loans(300, seed=5):
            self.assertGreater(loan["loan_amount"], 0)
            self.assertGreaterEqual(loan["balance"], 0)
            self.assertTrue(0 <= loan["dti_ratio"] <= 1.0)
            self.assertTrue(0 <= loan["days_past_due"] <= 365)
            self.assertTrue(0 <= loan["missed_payments"] <= 24)
            self.assertRegex(loan["origination_month"], r"^\d{4}-\d{2}$")

    def test_generated_portfolio_validates_clean(self):
        self.assertEqual(validate_portfolio(generate_loans(500, seed=9)), [])

    def test_unique_loan_ids(self):
        ids = [l["loan_id"] for l in generate_loans(500, seed=9)]
        self.assertEqual(len(ids), len(set(ids)))

    def test_worse_credit_more_delinquent_on_average(self):
        loans = generate_loans(2000, seed=42)
        poor = [l for l in loans if l["credit_score_band"] == "poor"]
        excellent = [l for l in loans if l["credit_score_band"] == "excellent"]
        avg = lambda rows: sum(l["days_past_due"] for l in rows) / len(rows)
        self.assertGreater(avg(poor), avg(excellent))

    def test_csv_roundtrip_shape(self):
        text = loans_to_csv(generate_loans(10, seed=1))
        lines = text.strip().splitlines()
        self.assertEqual(len(lines), 11)
        self.assertTrue(lines[0].startswith("loan_id,"))

    def test_jsonl_roundtrip(self):
        import json
        loans = generate_loans(10, seed=1)
        parsed = [json.loads(l) for l in loans_to_jsonl(loans).splitlines()]
        self.assertEqual(parsed, loans)

    def test_jsonl_deterministic_bytes(self):
        self.assertEqual(loans_to_jsonl(generate_loans(50, seed=42)),
                         loans_to_jsonl(generate_loans(50, seed=42)))


if __name__ == "__main__":
    unittest.main()
