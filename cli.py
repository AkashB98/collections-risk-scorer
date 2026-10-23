"""CLI: generate | score | segment | prioritize | check | demo | serve.

SYNTHETIC DATA ONLY — Northstar Lending is a fictional lender and every
portfolio handled here is fabricated sample data.

Exit codes:
  check : 0 = pass, 1 = tier-D share above threshold, 2 = usage / IO /
          data-quality error
  others: 0 = success, 2 = usage / IO error
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generator import generate_loans, loans_to_csv, loans_to_jsonl  # noqa: E402
from prioritize import prioritize  # noqa: E402
from scorer import score_loan, score_portfolio  # noqa: E402
from segment import segment_portfolio  # noqa: E402
from validation import validate_portfolio  # noqa: E402

EXIT_OK, EXIT_FAIL, EXIT_ERROR = 0, 1, 2
DEFAULT_MAX_TIER_D_PCT = 15.0


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True)


def _coerce_numbers(loan: Dict) -> Dict:
    out = dict(loan)
    for field in ("loan_amount", "balance", "apr", "dti_ratio"):
        if field in out and isinstance(out[field], str):
            try:
                out[field] = float(out[field])
            except ValueError:
                pass
    for field in ("term_months", "days_past_due", "missed_payments"):
        if field in out and isinstance(out[field], str):
            try:
                out[field] = int(float(out[field]))
            except ValueError:
                pass
    # CSV round-trip: integral floats for int fields.
    for field in ("term_months", "days_past_due", "missed_payments"):
        if isinstance(out.get(field), float) and out[field].is_integer():
            out[field] = int(out[field])
    return out


def load_portfolio(path: str) -> List[Dict]:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    stripped = text.strip()
    if not stripped:
        return []
    if path.endswith(".csv"):
        reader = csv.DictReader(io.StringIO(text))
        return [_coerce_numbers(dict(row)) for row in reader]
    if stripped.startswith("["):
        data = json.loads(stripped)
        return [_coerce_numbers(dict(x)) for x in data]
    loans = []
    for line in stripped.splitlines():
        if line.strip():
            loans.append(_coerce_numbers(json.loads(line)))
    return loans


def _load_or_error(path: str) -> Optional[List[Dict]]:
    try:
        return load_portfolio(path)
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
    except (ValueError, OSError) as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
    return None


def cmd_generate(args) -> int:
    loans = generate_loans(count=args.count, seed=args.seed)
    fmt = args.format
    if fmt is None:
        fmt = "csv" if (args.out and args.out.endswith(".csv")) else "jsonl"
    text = loans_to_csv(loans) if fmt == "csv" else loans_to_jsonl(loans)
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            print(f"error: cannot write {args.out}: {exc}", file=sys.stderr)
            return EXIT_ERROR
        print(f"generated {len(loans)} synthetic loans (seed={args.seed}) -> {args.out}")
    else:
        print(text, end="")
    return EXIT_OK


def cmd_score(args) -> int:
    loans = _load_or_error(args.input)
    if loans is None:
        return EXIT_ERROR
    scored = score_portfolio(loans)
    payload = {"count": len(scored), "scored": scored}
    text = canonical(payload) + "\n"
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            print(f"error: cannot write {args.out}: {exc}", file=sys.stderr)
            return EXIT_ERROR
        print(f"scored {len(scored)} loans -> {args.out}")
    else:
        print(text, end="")
    return EXIT_OK


def cmd_segment(args) -> int:
    loans = _load_or_error(args.input)
    if loans is None:
        return EXIT_ERROR
    print(canonical(segment_portfolio(loans)))
    return EXIT_OK


def cmd_prioritize(args) -> int:
    loans = _load_or_error(args.input)
    if loans is None:
        return EXIT_ERROR
    queue = prioritize(loans, limit=args.limit)
    print(canonical({"count": len(queue), "queue": queue}))
    return EXIT_OK


def cmd_check(args) -> int:
    loans = _load_or_error(args.input)
    if loans is None:
        return EXIT_ERROR
    issues = validate_portfolio(loans)
    if issues:
        for issue in issues[:20]:
            print(f"data-quality: {issue}")
        print(f"check FAIL (data quality): {len(issues)} issue(s)")
        return EXIT_ERROR
    summary = segment_portfolio(loans)
    tier_d_pct = summary["tier_d_pct"]
    print(f"loans={summary['total_loans']} tier_d_pct={tier_d_pct} "
          f"max_tier_d_pct={args.max_tier_d_pct} balance_at_risk={summary['balance_at_risk']}")
    if tier_d_pct > args.max_tier_d_pct:
        print("check FAIL: tier D share above threshold")
        return EXIT_FAIL
    print("check PASS")
    return EXIT_OK


def cmd_demo(args) -> int:
    import demo as demo_mod
    try:
        demo_mod.main()
    except AssertionError as exc:
        print(f"demo FAILED: {exc}", file=sys.stderr)
        return EXIT_FAIL
    return EXIT_OK


# ------------------------------------------------------------------- serve

class _State:
    """Mutable portfolio held by the serve process."""
    def __init__(self):
        self.loans: List[Dict] = generate_loans(count=200, seed=42)


_STATE = _State()


def get_state() -> _State:
    return _STATE


def reset_state(loans: Optional[List[Dict]] = None) -> None:
    _STATE.loans = list(loans) if loans is not None else generate_loans(count=200, seed=42)


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, payload: Any) -> None:
        self._send(code, (canonical(payload) + "\n").encode(), "application/json")

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            return self._send_json(200, {"status": "ok"})
        if self.path == "/summary":
            return self._send_json(200, segment_portfolio(_STATE.loans))
        return self._send_json(404, {"error": "unknown endpoint"})

    def do_POST(self):  # noqa: N802
        if self.path != "/score":
            return self._send_json(404, {"error": "unknown endpoint"})
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if isinstance(body, dict) and "loans" in body:
                loans = [_coerce_numbers(dict(x)) for x in body["loans"]]
                _STATE.loans = loans
                return self._send_json(200, {"count": len(loans),
                                             "scored": score_portfolio(loans)})
            if isinstance(body, dict) and "loan" in body:
                loan = _coerce_numbers(dict(body["loan"]))
                return self._send_json(200, score_loan(loan))
            if isinstance(body, dict) and "loan_id" in body:
                loan = _coerce_numbers(dict(body))
                return self._send_json(200, score_loan(loan))
            if isinstance(body, list):
                loans = [_coerce_numbers(dict(x)) for x in body]
                _STATE.loans = loans
                return self._send_json(200, {"count": len(loans),
                                             "scored": score_portfolio(loans)})
            raise ValueError("expected a loan object, {'loan': ...}, or {'loans': [...]}")
        except (ValueError, TypeError, KeyError) as exc:
            return self._send_json(400, {"error": f"bad request: {exc}"})

    def log_message(self, *a: Any) -> None:
        pass


def make_server(port: int) -> HTTPServer:
    return HTTPServer(("127.0.0.1", port), _Handler)


def cmd_serve(args) -> int:
    server = make_server(args.port)
    print(f"serving on http://127.0.0.1:{args.port}  (POST /score, GET /summary, GET /health)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="collections-risk-scorer",
        description="Synthetic collections risk scoring (Northstar Lending sample data).")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="generate a synthetic portfolio")
    g.add_argument("--count", type=int, default=2000)
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--out", default=None)
    g.add_argument("--format", choices=["csv", "jsonl"], default=None)
    g.set_defaults(func=cmd_generate)

    s = sub.add_parser("score", help="score a portfolio file")
    s.add_argument("--input", required=True)
    s.add_argument("--out", default=None)
    s.set_defaults(func=cmd_score)

    s = sub.add_parser("segment", help="tier segmentation + portfolio summary")
    s.add_argument("--input", required=True)
    s.set_defaults(func=cmd_segment)

    s = sub.add_parser("prioritize", help="recovery-priority work queue")
    s.add_argument("--input", required=True)
    s.add_argument("--limit", type=int, default=None)
    s.set_defaults(func=cmd_prioritize)

    c = sub.add_parser("check", help="CI gate: exit 0 pass / 1 tier-D breach / 2 error")
    c.add_argument("--input", required=True)
    c.add_argument("--max-tier-d-pct", type=float, default=DEFAULT_MAX_TIER_D_PCT)
    c.set_defaults(func=cmd_check)

    sub.add_parser("demo", help="run the end-to-end demo").set_defaults(func=cmd_demo)

    s = sub.add_parser("serve", help="localhost JSON API: POST /score, GET /summary")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(func=cmd_serve)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
