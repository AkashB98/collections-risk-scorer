"""Golden evals for collections-risk-scorer.

SYNTHETIC DATA ONLY (fictional Northstar Lending portfolio). Every eval
is deterministic: run_evals.py writes eval_report.json and the file must
be byte-identical across runs. No timestamps, ports, or temp paths enter
the report — only names, booleans, pinned counts and pinned hashes.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import threading
import urllib.request
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import EXIT_ERROR, EXIT_FAIL, EXIT_OK, main as cli_main, load_portfolio, make_server, reset_state  # noqa: E402
from generator import generate_loans, loans_to_jsonl  # noqa: E402
from prioritize import prioritize  # noqa: E402
from scorer import WEIGHTS, contributions_for, risk_score, score_loan, score_portfolio, tier_for_score  # noqa: E402
from segment import segment_portfolio  # noqa: E402
from validation import validate_loan, validate_portfolio  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURE = os.path.join(ROOT, "fixtures", "sample_portfolio.jsonl")
RESULTS = []

EXPECTED_TIERS = {"A": 1046, "B": 691, "C": 227, "D": 36}
EXPECTED_FIXTURE_TIERS = {"A": 16, "B": 11, "C": 2, "D": 1}


def check(name, passed, detail=""):
    RESULTS.append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return passed


def _run_cli(argv):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return cli_main(argv)


def main():
    print("== golden evals: collections-risk-scorer ==")
    loans = generate_loans(2000, seed=42)

    # E1: generator determinism (bytes pinned)
    text1 = loans_to_jsonl(generate_loans(2000, seed=42))
    text2 = loans_to_jsonl(generate_loans(2000, seed=42))
    md5 = hashlib.md5(text1.encode()).hexdigest()
    check("E1 generator determinism (seed=42, 2000 loans)",
          text1 == text2 and len(loans) == 2000, f"jsonl_md5={md5}")

    # E2: portfolio tier counts pinned
    summary = segment_portfolio(loans)
    counts = {t: summary["tiers"][t]["count"] for t in "ABCD"}
    check("E2 tier counts pinned for seed=42 portfolio",
          counts == EXPECTED_TIERS and summary["tier_d_pct"] == 1.8, f"{counts}")

    # E3: explainability sums hold for every loan
    ok = all(abs(sum(s["contributions"].values()) - s["risk_score"]) < 1e-4
             for s in score_portfolio(loans))
    check("E3 explainability contributions sum to score (all 2000 loans)", ok)

    # E4: average risk strictly ordered by credit band
    from collections import defaultdict
    by_band = defaultdict(list)
    for loan, s in zip(loans, score_portfolio(loans)):
        by_band[loan["credit_score_band"]].append(s["risk_score"])
    avgs = [sum(by_band[b]) / len(by_band[b])
            for b in ("poor", "fair", "good", "very_good", "excellent")]
    check("E4 avg risk ordered poor > fair > good > very_good > excellent",
          avgs == sorted(avgs, reverse=True) and len(set(avgs)) == 5,
          f"avgs={[round(a, 4) for a in avgs]}")

    # E5: tier boundaries pinned
    bounds_ok = (tier_for_score(0.2499) == "A" and tier_for_score(0.25) == "B"
                 and tier_for_score(0.50) == "C" and tier_for_score(0.75) == "D"
                 and tier_for_score(0.0) == "A" and tier_for_score(1.0) == "D")
    check("E5 tier boundaries at 0.25 / 0.50 / 0.75 pinned", bounds_ok)

    # E6: prioritisation pinned (queue size, top loan, ordering)
    queue = prioritize(loans)
    values = [q["priority_value"] for q in queue]
    check("E6 recovery queue pinned (726 delinquent, top NL-01029)",
          len(queue) == 726 and queue[0]["loan_id"] == "NL-01029"
          and values == sorted(values, reverse=True)
          and all(q["days_past_due"] > 0 or q["missed_payments"] > 0 for q in queue),
          f"top_priority={queue[0]['priority_value']}")

    # E7: validation catches planted defects, clean book passes
    import copy
    bad = copy.deepcopy(loans[0])
    bad["dti_ratio"] = 1.7
    bad["credit_score_band"] = "terrible"
    planted = validate_loan(bad)
    check("E7 validation flags planted defects, generated book clean",
          len(planted) == 2 and validate_portfolio(loans) == [],
          f"planted={planted}")

    # E8: weights budget — sums to 1, every contribution within its weight
    within = all(0.0 <= v <= WEIGHTS[k] + 1e-9
                 for loan in loans for k, v in contributions_for(loan).items())
    check("E8 weights sum to 1.00 and bound every contribution",
          abs(sum(WEIGHTS.values()) - 1.0) < 1e-9 and within)

    # E9: monotonicity spot lattice (credit x DPD grid never decreases)
    base = dict(loans[0])
    mono = True
    for band in ("excellent", "good", "poor"):
        prev = -1.0
        for dpd in (0, 30, 60, 90):
            s = risk_score(dict(base, credit_score_band=band, days_past_due=dpd))
            mono = mono and s >= prev
            prev = s
    check("E9 score monotonic in days_past_due within each credit band", mono)

    # E10: CLI check exit codes 0 / 1 / 2
    import tempfile
    tmp = tempfile.mkdtemp(prefix="crs-evals-")
    good_path = os.path.join(tmp, "good.jsonl")
    with open(good_path, "w", encoding="utf-8") as fh:
        fh.write(loans_to_jsonl(generate_loans(50, seed=7)))
    all_d = [dict(l, credit_score_band="poor", income_band="low", apr=30.0,
                  dti_ratio=0.85, days_past_due=120, missed_payments=8)
             for l in generate_loans(10, seed=7)]
    d_path = os.path.join(tmp, "alld.jsonl")
    with open(d_path, "w", encoding="utf-8") as fh:
        fh.write(loans_to_jsonl(all_d))
    codes = (_run_cli(["check", "--input", good_path, "--max-tier-d-pct", "100"]),
             _run_cli(["check", "--input", d_path, "--max-tier-d-pct", "15"]),
             _run_cli(["check", "--input", "/tmp/no-such-portfolio-xyz.jsonl"]))
    check("E10 CLI check exit codes 0/1/2",
          codes == (EXIT_OK, EXIT_FAIL, EXIT_ERROR), f"codes={codes}")

    # E11: serve round-trip matches local scoring + summary
    reset_state(generate_loans(50, seed=7))
    server = make_server(0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/score",
                                     data=json.dumps(loans[0]).encode(),
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            served = json.loads(resp.read())
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/summary", timeout=10) as resp:
            summ = json.loads(resp.read())
        serve_ok = served == score_loan(loans[0]) and summ["total_loans"] == 50
    finally:
        server.shutdown()
        server.server_close()
        reset_state()
    check("E11 serve round-trip matches local score + summary", serve_ok)

    # E12: bundled fixture pinned (30 synthetic loans, tier counts, clean)
    fixture = load_portfolio(FIXTURE)
    fx = segment_portfolio(fixture)
    fx_counts = {t: fx["tiers"][t]["count"] for t in "ABCD"}
    check("E12 fixture portfolio pinned (30 loans, tiers A16/B11/C2/D1)",
          len(fixture) == 30 and fx_counts == EXPECTED_FIXTURE_TIERS
          and validate_portfolio(fixture) == [], f"{fx_counts}")

    passed = sum(1 for r in RESULTS if r["passed"])
    total = len(RESULTS)
    summary_doc = {"passed": passed, "total": total,
                   "all_passed": passed == total, "evals": RESULTS}
    with open(os.path.join(HERE, "eval_report.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(summary_doc, sort_keys=True) + "\n")
    print(f"\n{passed}/{total} evals passed -> evals/eval_report.json")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
