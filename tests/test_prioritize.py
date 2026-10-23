import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import loan
from generator import generate_loans
from prioritize import (effort_estimate, is_delinquent, prioritize,
                        recovery_probability)
from scorer import score_loan


class TestPrioritize(unittest.TestCase):
    def test_current_loans_excluded(self):
        loans = [loan(loan_id="NL-A"), loan(loan_id="NL-B", days_past_due=10)]
        queue = prioritize(loans)
        self.assertEqual([q["loan_id"] for q in queue], ["NL-B"])

    def test_missed_only_counts_as_delinquent(self):
        self.assertTrue(is_delinquent(loan(missed_payments=1, days_past_due=0)))
        self.assertFalse(is_delinquent(loan()))

    def test_queue_sorted_by_priority_value_desc(self):
        queue = prioritize(generate_loans(500, seed=42))
        values = [q["priority_value"] for q in queue]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_ranks_are_sequential(self):
        queue = prioritize(generate_loans(200, seed=42))
        self.assertEqual([q["rank"] for q in queue], list(range(1, len(queue) + 1)))

    def test_priority_formula(self):
        l = loan(days_past_due=30, missed_payments=1, balance=10000.0)
        q = prioritize([l])[0]
        expected = round(10000.0 * q["recovery_probability"] / q["effort"], 4)
        self.assertAlmostEqual(q["priority_value"], expected, places=4)
        self.assertAlmostEqual(q["expected_recovery"],
                               round(10000.0 * q["recovery_probability"], 2), places=2)

    def test_bigger_balance_ranks_first_all_else_equal(self):
        small = loan(loan_id="NL-S", balance=1000.0, days_past_due=30, missed_payments=1)
        big = loan(loan_id="NL-L", balance=50000.0, days_past_due=30, missed_payments=1)
        queue = prioritize([small, big])
        self.assertEqual(queue[0]["loan_id"], "NL-L")

    def test_tie_break_by_loan_id(self):
        a = loan(loan_id="NL-B", balance=5000.0, days_past_due=30, missed_payments=1)
        b = loan(loan_id="NL-A", balance=5000.0, days_past_due=30, missed_payments=1)
        queue = prioritize([a, b])
        self.assertEqual([q["loan_id"] for q in queue], ["NL-A", "NL-B"])

    def test_limit(self):
        loans = generate_loans(200, seed=42)
        self.assertEqual(len(prioritize(loans, limit=5)), 5)
        self.assertEqual(prioritize(loans, limit=0), [])
        with self.assertRaises(ValueError):
            prioritize(loans, limit=-1)

    def test_recovery_probability_bounds_and_direction(self):
        low_risk = recovery_probability(loan(collateral_type="home"), 0.1)
        high_risk = recovery_probability(loan(collateral_type="home"), 0.9)
        self.assertGreater(low_risk, high_risk)
        for p in (low_risk, high_risk):
            self.assertTrue(0.0 < p <= 0.95)

    def test_collateral_lifts_recovery(self):
        secured = recovery_probability(loan(collateral_type="home"), 0.5)
        unsecured = recovery_probability(loan(collateral_type="unsecured"), 0.5)
        self.assertGreater(secured, unsecured)

    def test_effort_grows_with_delinquency(self):
        e1 = effort_estimate(loan(days_past_due=10, missed_payments=0))
        e2 = effort_estimate(loan(days_past_due=90, missed_payments=4))
        self.assertGreater(e2, e1)
        self.assertGreaterEqual(effort_estimate(loan()), 1.0)

    def test_queue_rows_carry_score_and_tier(self):
        l = loan(days_past_due=45, missed_payments=2)
        q = prioritize([l])[0]
        s = score_loan(l)
        self.assertEqual(q["risk_score"], s["risk_score"])
        self.assertEqual(q["tier"], s["tier"])

    def test_empty_and_no_delinquent(self):
        self.assertEqual(prioritize([]), [])
        self.assertEqual(prioritize([loan(), loan(loan_id="NL-Z")]), [])

    def test_deterministic(self):
        loans = generate_loans(200, seed=42)
        self.assertEqual(prioritize(loans), prioritize(loans))


if __name__ == "__main__":
    unittest.main()
