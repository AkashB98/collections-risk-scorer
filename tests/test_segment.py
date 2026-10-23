import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import loan
from generator import generate_loans
from scorer import tier_for_score
from segment import TIER_THRESHOLDS, loans_by_tier, segment_portfolio


class TestSegment(unittest.TestCase):
    def setUp(self):
        self.loans = generate_loans(2000, seed=42)
        self.summary = segment_portfolio(self.loans)

    def test_tiers_partition_portfolio(self):
        total = sum(self.summary["tiers"][t]["count"] for t in "ABCD")
        self.assertEqual(total, 2000)
        self.assertEqual(self.summary["total_loans"], 2000)

    def test_tier_pcts_sum_to_100(self):
        pct = sum(self.summary["tiers"][t]["pct"] for t in "ABCD")
        self.assertAlmostEqual(pct, 100.0, delta=0.05)

    def test_balance_sums(self):
        total = sum(self.summary["tiers"][t]["total_balance"] for t in "ABCD")
        self.assertAlmostEqual(total, self.summary["total_balance"], delta=0.05)

    def test_balance_at_risk_is_c_plus_d(self):
        expected = (self.summary["tiers"]["C"]["total_balance"]
                    + self.summary["tiers"]["D"]["total_balance"])
        self.assertAlmostEqual(self.summary["balance_at_risk"], expected, delta=0.01)
        self.assertEqual(self.summary["tiers"]["A"]["balance_at_risk"], 0.0)
        self.assertEqual(self.summary["tiers"]["B"]["balance_at_risk"], 0.0)

    def test_tier_d_pct_matches(self):
        d = self.summary["tiers"]["D"]
        self.assertEqual(self.summary["tier_d_count"], d["count"])
        self.assertEqual(self.summary["tier_d_pct"], d["pct"])

    def test_avg_score_increases_across_tiers(self):
        avgs = [self.summary["tiers"][t]["avg_risk_score"] for t in "ABCD"
                if self.summary["tiers"][t]["count"]]
        self.assertEqual(avgs, sorted(avgs))

    def test_avg_dpd_increases_across_tiers(self):
        dpds = [self.summary["tiers"][t]["avg_days_past_due"] for t in "ABCD"
                if self.summary["tiers"][t]["count"]]
        self.assertEqual(dpds, sorted(dpds))

    def test_thresholds_match_scorer(self):
        self.assertEqual(tier_for_score(TIER_THRESHOLDS["B"] - 0.001), "A")
        self.assertEqual(tier_for_score(TIER_THRESHOLDS["B"]), "B")
        self.assertEqual(tier_for_score(TIER_THRESHOLDS["C"]), "C")
        self.assertEqual(tier_for_score(TIER_THRESHOLDS["D"]), "D")

    def test_empty_portfolio(self):
        s = segment_portfolio([])
        self.assertEqual(s["total_loans"], 0)
        self.assertEqual(s["total_balance"], 0.0)
        self.assertEqual(s["tier_d_pct"], 0.0)
        for t in "ABCD":
            self.assertEqual(s["tiers"][t]["count"], 0)
            self.assertEqual(s["tiers"][t]["avg_days_past_due"], 0.0)

    def test_single_tier_portfolio(self):
        clean = [loan(loan_id=f"NL-C{i}", credit_score_band="excellent",
                      income_band="high", apr=4.0, dti_ratio=0.1) for i in range(5)]
        s = segment_portfolio(clean)
        self.assertEqual(s["tiers"]["A"]["count"], 5)
        self.assertEqual(s["balance_at_risk"], 0.0)

    def test_loans_by_tier(self):
        d_loans = loans_by_tier(self.loans, "D")
        self.assertEqual(len(d_loans), self.summary["tiers"]["D"]["count"])
        with self.assertRaises(ValueError):
            loans_by_tier(self.loans, "Z")

    def test_delinquent_counts_consistent(self):
        for t in "ABCD":
            tier = self.summary["tiers"][t]
            self.assertLessEqual(tier["delinquent_count"], tier["count"])
        # Every tier-C/D loan in the generated book is delinquent by
        # construction of the scoring weights (DPD/missed dominate).
        self.assertEqual(self.summary["tiers"]["D"]["delinquent_count"],
                         self.summary["tiers"]["D"]["count"])

    def test_segment_deterministic(self):
        self.assertEqual(segment_portfolio(self.loans), self.summary)


if __name__ == "__main__":
    unittest.main()
