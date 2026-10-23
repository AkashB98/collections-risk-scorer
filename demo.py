"""End-to-end demo: generate -> score -> segment -> prioritize -> serve.

SYNTHETIC DATA ONLY (fictional Northstar Lending portfolio). Runs fully
offline; the serve round-trip is loopback-only on an ephemeral port.
Every stage asserts.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cli import EXIT_FAIL, EXIT_OK, main as cli_main, make_server, reset_state  # noqa: E402
from generator import generate_loans  # noqa: E402
from prioritize import prioritize  # noqa: E402
from scorer import score_loan, score_portfolio  # noqa: E402
from segment import segment_portfolio  # noqa: E402
from validation import validate_portfolio  # noqa: E402


def _request(port: int, path: str, payload=None, method: str = "GET"):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read())


def main() -> None:
    print("== 1. generate synthetic Northstar Lending portfolio (seed=42) ==")
    loans = generate_loans(count=2000, seed=42)
    again = generate_loans(count=2000, seed=42)
    assert loans == again, "generator must be deterministic"
    print(f"   {len(loans)} loans, deterministic re-generation verified")
    assert loans[0]["loan_id"] == "NL-00001"
    assert validate_portfolio(loans) == [], validate_portfolio(loans)[:3]

    print("\n== 2. score: explainability sums + tier ordering ==")
    scored = score_portfolio(loans)
    for s in scored:
        total = sum(s["contributions"].values())
        assert abs(total - s["risk_score"]) < 1e-4, (s["loan_id"], total, s["risk_score"])
        assert 0.0 <= s["risk_score"] <= 1.0
        assert s["tier"] in ("A", "B", "C", "D")
    worst = {"loan_id": "NL-X", "borrower_age_band": "25-34", "income_band": "low",
             "loan_amount": 5000, "term_months": 36, "apr": 30.0,
             "credit_score_band": "poor", "dti_ratio": 0.85,
             "days_past_due": 120, "missed_payments": 8, "balance": 4500,
             "collateral_type": "unsecured", "region": "West",
             "origination_month": "2025-06"}
    best = dict(worst, credit_score_band="excellent", income_band="high",
                apr=4.0, dti_ratio=0.10, days_past_due=0, missed_payments=0)
    assert score_loan(worst)["risk_score"] > score_loan(best)["risk_score"]
    assert score_loan(worst)["tier"] == "D" and score_loan(best)["tier"] == "A"
    print(f"   worst-case loan scores {score_loan(worst)['risk_score']} (D), "
          f"best-case {score_loan(best)['risk_score']} (A)")

    print("\n== 3. segment: tiers partition the portfolio ==")
    summary = segment_portfolio(loans)
    counts = {t: summary["tiers"][t]["count"] for t in "ABCD"}
    assert sum(counts.values()) == 2000, counts
    avg_scores = [summary["tiers"][t]["avg_risk_score"] for t in "ABCD"
                  if summary["tiers"][t]["count"]]
    assert avg_scores == sorted(avg_scores), "tier avg scores must increase A->D"
    print(f"   tiers={counts} balance_at_risk={summary['balance_at_risk']} "
          f"tier_d_pct={summary['tier_d_pct']}")

    print("\n== 4. prioritize: delinquent-only queue, best value first ==")
    queue = prioritize(loans, limit=10)
    assert queue, "expected a non-empty delinquent queue"
    assert all(q["days_past_due"] > 0 or q["missed_payments"] > 0 for q in queue)
    values = [q["priority_value"] for q in queue]
    assert values == sorted(values, reverse=True), "queue must be value-descending"
    assert [q["rank"] for q in queue] == list(range(1, len(queue) + 1))
    print(f"   top of queue: {queue[0]['loan_id']} tier {queue[0]['tier']} "
          f"balance {queue[0]['balance']} priority {queue[0]['priority_value']}")

    print("\n== 5. CLI check gate exit codes ==")
    import tempfile
    from generator import loans_to_jsonl
    tmp = tempfile.mkdtemp(prefix="crs-demo-")
    good_path = os.path.join(tmp, "good.jsonl")
    with open(good_path, "w", encoding="utf-8") as fh:
        fh.write(loans_to_jsonl(generate_loans(count=50, seed=7)))
    code_ok = cli_main(["check", "--input", good_path, "--max-tier-d-pct", "100"])
    code_err = cli_main(["check", "--input", "/tmp/no-such-portfolio-xyz.jsonl"])
    print(f"   permissive-threshold={code_ok} missing-file={code_err}")
    assert code_ok == EXIT_OK and code_err == 2

    print("\n== 6. live localhost serve round-trip ==")
    reset_state(generate_loans(count=50, seed=7))
    server = make_server(0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, health = _request(port, "/health")
        assert status == 200 and health == {"status": "ok"}
        status, one = _request(port, "/score", payload=loans[0], method="POST")
        assert status == 200 and one["loan_id"] == loans[0]["loan_id"]
        assert one == score_loan(loans[0]), "served score must match local score"
        status, summ = _request(port, "/summary")
        assert status == 200 and summ["total_loans"] == 50
        print("   POST /score matches local scoring; GET /summary totals 50 loans")
    finally:
        server.shutdown()
        server.server_close()
        reset_state()

    print("\nDemo OK: generate, score, segment, prioritize, check and serve verified.")


if __name__ == "__main__":
    main()
