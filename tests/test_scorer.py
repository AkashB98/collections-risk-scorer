import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import loan
from scorer import (WEIGHTS, contributions_for, logistic_check, risk_score,
                    score_loan, score_portfolio, tier_for_score)
from generator import generate_loans


class TestScorer(unittest.TestCase):
    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(WEIGHTS.values()), 1.0, places=9)

    def test_clean_loan_is_low(self):
        s = score_loan(loan(credit_score_band="excellent", income_band="high",
                            apr=4.0, dti_ratio=0.10))
        self.assertEqual(s["risk_score"], 0.0)
        self.assertEqual(s["tier"], "A")

    def test_worst_loan_is_critical(self):
        s = score_loan(loan(credit_score_band="poor", income_band="low", apr=30.0,
                            dti_ratio=0.85, days_past_due=120, missed_payments=8))
        self.assertEqual(s["risk_score"], 1.0)
        self.assertEqual(s["tier"], "D")

    def test_score_in_unit_interval(self):
        for l in generate_loans(300, seed=11):
            self.assertTrue(0.0 <= risk_score(l) <= 1.0)

    def test_explainability_sums_to_score(self):
        for l in generate_loans(300, seed=11):
            s = score_loan(l)
            self.assertAlmostEqual(sum(s["contributions"].values()),
                                   s["risk_score"], places=4)

    def test_contribution_keys_match_weights(self):
        self.assertEqual(sorted(contributions_for(loan()).keys()), sorted(WEIGHTS.keys()))

    def test_each_contribution_within_weight(self):
        for l in generate_loans(200, seed=4):
            for k, v in contributions_for(l).items():
                self.assertTrue(0.0 <= v <= WEIGHTS[k] + 1e-9, (k, v))

    def test_top_factors_sorted_and_positive(self):
        s = score_loan(loan(credit_score_band="poor", days_past_due=60))
        vals = [f["contribution"] for f in s["top_factors"]]
        self.assertEqual(vals, sorted(vals, reverse=True))
        self.assertTrue(all(v > 0 for v in vals))
        self.assertLessEqual(len(s["top_factors"]), 3)
        self.assertEqual(s["top_factors"][0]["factor"], "credit_score_band")

    def test_monotonic_in_credit_band(self):
        scores = [risk_score(loan(credit_score_band=b))
                  for b in ("excellent", "very_good", "good", "fair", "poor")]
        self.assertEqual(scores, sorted(scores))
        self.assertLess(scores[0], scores[-1])

    def test_monotonic_in_dpd(self):
        scores = [risk_score(loan(days_past_due=d)) for d in (0, 15, 30, 60, 90, 150)]
        self.assertEqual(scores, sorted(scores))

    def test_monotonic_in_missed_payments(self):
        scores = [risk_score(loan(missed_payments=m)) for m in (0, 1, 2, 4, 6, 9)]
        self.assertEqual(scores, sorted(scores))

    def test_monotonic_in_dti(self):
        scores = [risk_score(loan(dti_ratio=d)) for d in (0.1, 0.3, 0.45, 0.6, 0.8)]
        self.assertEqual(scores, sorted(scores))

    def test_dpd_caps_at_90(self):
        self.assertEqual(risk_score(loan(days_past_due=90)),
                         risk_score(loan(days_past_due=300)))

    def test_missed_caps_at_6(self):
        self.assertEqual(risk_score(loan(missed_payments=6)),
                         risk_score(loan(missed_payments=20)))

    def test_tier_boundaries(self):
        self.assertEqual(tier_for_score(0.0), "A")
        self.assertEqual(tier_for_score(0.2499), "A")
        self.assertEqual(tier_for_score(0.25), "B")
        self.assertEqual(tier_for_score(0.4999), "B")
        self.assertEqual(tier_for_score(0.50), "C")
        self.assertEqual(tier_for_score(0.7499), "C")
        self.assertEqual(tier_for_score(0.75), "D")
        self.assertEqual(tier_for_score(1.0), "D")

    def test_score_portfolio_length_and_ids(self):
        loans = generate_loans(25, seed=2)
        scored = score_portfolio(loans)
        self.assertEqual(len(scored), 25)
        self.assertEqual([s["loan_id"] for s in scored],
                         [l["loan_id"] for l in loans])

    def test_scoring_deterministic(self):
        loans = generate_loans(50, seed=2)
        self.assertEqual(score_portfolio(loans), score_portfolio(loans))

    def test_logistic_check_monotonic_and_centred(self):
        self.assertAlmostEqual(logistic_check(0.5), 0.5, places=9)
        vals = [logistic_check(s) for s in (0.0, 0.25, 0.5, 0.75, 1.0)]
        self.assertEqual(vals, sorted(vals))
        self.assertTrue(all(0 < v < 1 for v in vals))

    def test_unknown_bands_get_default_contribution(self):
        # Unknown credit band must not crash; falls back to a mid value.
        s = score_loan(loan(credit_score_band="mystery", income_band="mystery"))
        self.assertTrue(0.0 <= s["risk_score"] <= 1.0)


if __name__ == "__main__":
    unittest.main()
