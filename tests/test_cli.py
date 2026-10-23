import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cli as cli_mod
from cli import EXIT_ERROR, EXIT_FAIL, EXIT_OK, main as cli_main, make_server
from generator import generate_loans, loans_to_jsonl
from helpers import loan


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli_main(argv)
    return code, out.getvalue(), err.getvalue()


class CliBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="crs-test-")
        self.good = os.path.join(self.tmp, "good.jsonl")
        with open(self.good, "w", encoding="utf-8") as fh:
            fh.write(loans_to_jsonl(generate_loans(60, seed=7)))


class TestGenerateScoreSegment(CliBase):
    def test_generate_to_file(self):
        out_path = os.path.join(self.tmp, "gen.jsonl")
        code, out, _ = run_cli(["generate", "--count", "25", "--seed", "3",
                                "--out", out_path])
        self.assertEqual(code, EXIT_OK)
        with open(out_path, encoding="utf-8") as fh:
            self.assertEqual(len(fh.read().strip().splitlines()), 25)

    def test_generate_csv(self):
        out_path = os.path.join(self.tmp, "gen.csv")
        code, _, _ = run_cli(["generate", "--count", "10", "--seed", "3",
                              "--out", out_path])
        self.assertEqual(code, EXIT_OK)
        with open(out_path, encoding="utf-8") as fh:
            lines = fh.read().strip().splitlines()
        self.assertEqual(len(lines), 11)
        self.assertTrue(lines[0].startswith("loan_id,"))

    def test_generate_deterministic_file(self):
        p1, p2 = os.path.join(self.tmp, "a.jsonl"), os.path.join(self.tmp, "b.jsonl")
        run_cli(["generate", "--count", "30", "--seed", "42", "--out", p1])
        run_cli(["generate", "--count", "30", "--seed", "42", "--out", p2])
        with open(p1, "rb") as a, open(p2, "rb") as b:
            self.assertEqual(a.read(), b.read())

    def test_score_command(self):
        code, out, _ = run_cli(["score", "--input", self.good])
        self.assertEqual(code, EXIT_OK)
        payload = json.loads(out)
        self.assertEqual(payload["count"], 60)
        self.assertEqual(len(payload["scored"]), 60)

    def test_score_missing_file(self):
        code, _, err = run_cli(["score", "--input", "/tmp/nope-xyz.jsonl"])
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("not found", err)

    def test_score_csv_input(self):
        csv_path = os.path.join(self.tmp, "in.csv")
        run_cli(["generate", "--count", "15", "--seed", "3", "--out", csv_path])
        code, out, _ = run_cli(["score", "--input", csv_path])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(out)["count"], 15)

    def test_segment_command(self):
        code, out, _ = run_cli(["segment", "--input", self.good])
        self.assertEqual(code, EXIT_OK)
        summary = json.loads(out)
        self.assertEqual(summary["total_loans"], 60)
        self.assertEqual(sum(summary["tiers"][t]["count"] for t in "ABCD"), 60)

    def test_prioritize_command_and_limit(self):
        code, out, _ = run_cli(["prioritize", "--input", self.good, "--limit", "3"])
        self.assertEqual(code, EXIT_OK)
        payload = json.loads(out)
        self.assertLessEqual(payload["count"], 3)
        values = [q["priority_value"] for q in payload["queue"]]
        self.assertEqual(values, sorted(values, reverse=True))


class TestCheckGate(CliBase):
    def test_check_passes_with_permissive_threshold(self):
        code, out, _ = run_cli(["check", "--input", self.good,
                                "--max-tier-d-pct", "100"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("PASS", out)

    def test_check_fails_when_threshold_zero_and_d_present(self):
        # Build a portfolio that is entirely tier D.
        bad_loans = [loan(loan_id=f"NL-D{i:03d}", credit_score_band="poor",
                          income_band="low", apr=30.0, dti_ratio=0.85,
                          days_past_due=120, missed_payments=8)
                     for i in range(10)]
        path = os.path.join(self.tmp, "alld.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(loans_to_jsonl(bad_loans))
        code, out, _ = run_cli(["check", "--input", path, "--max-tier-d-pct", "15"])
        self.assertEqual(code, EXIT_FAIL)
        self.assertIn("FAIL", out)

    def test_check_data_quality_is_error(self):
        bad = loan()
        del bad["balance"]
        path = os.path.join(self.tmp, "bad.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(bad) + "\n")
        code, out, _ = run_cli(["check", "--input", path])
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("data-quality", out)

    def test_check_missing_file_is_error(self):
        code, _, _ = run_cli(["check", "--input", "/tmp/nope-xyz.jsonl"])
        self.assertEqual(code, EXIT_ERROR)

    def test_check_malformed_json_is_error(self):
        path = os.path.join(self.tmp, "junk.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json\n")
        code, _, _ = run_cli(["check", "--input", path])
        self.assertEqual(code, EXIT_ERROR)


class TestServe(CliBase):
    def setUp(self):
        super().setUp()
        cli_mod.reset_state(generate_loans(40, seed=7))
        self.server = make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        cli_mod.reset_state()

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}",
                                    timeout=10) as resp:
            return resp.status, json.loads(resp.read())

    def _post(self, path, payload):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())

    def test_health(self):
        status, body = self._get("/health")
        self.assertEqual((status, body), (200, {"status": "ok"}))

    def test_summary(self):
        status, body = self._get("/summary")
        self.assertEqual(status, 200)
        self.assertEqual(body["total_loans"], 40)

    def test_score_single_loan_matches_local(self):
        from scorer import score_loan
        target = generate_loans(40, seed=7)[0]
        status, body = self._post("/score", target)
        self.assertEqual(status, 200)
        self.assertEqual(body, score_loan(target))

    def test_score_batch_updates_summary(self):
        loans = generate_loans(12, seed=99)
        status, body = self._post("/score", {"loans": loans})
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 12)
        _, summary = self._get("/summary")
        self.assertEqual(summary["total_loans"], 12)

    def test_unknown_endpoint_404(self):
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/nope")
        self.assertEqual(ctx.exception.code, 404)

    def test_bad_body_400(self):
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/score", {"unexpected": 1})
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
