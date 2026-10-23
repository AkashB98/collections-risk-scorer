# collections-risk-scorer

**Delinquency prediction, risk-tier segmentation, and recovery prioritisation — the daily craft of a collections strategy team — as one transparent, runnable artifact.**

Collections and portfolio analysts do this work in spreadsheets and slide decks: score the book, cut it into risk tiers, decide who gets called first and why. This project turns that judgement into code a reviewer can run, test, and argue with: a deterministic synthetic loan book for a fictional lender (**Northstar Lending**), an explainable scoring model whose weights table *is* the model, tier segmentation with balance-at-risk, and a recovery-priority work queue ranked by expected recovery value per unit of effort. No black box, no ML library — every point of every score is attributable to a named feature.

> **Synthetic data only.** Every loan is fabricated by a seeded generator. No real borrower, account, or portfolio data is used anywhere in this project.

Stdlib-only Python. Zero network, zero API keys, zero external dependencies.

## Quickstart

```bash
# 1. Generate the synthetic Northstar Lending book (2,000 loans, seed 42)
python3 cli.py generate --count 2000 --seed 42 --out portfolio.jsonl

# 2. Score it (per-loan risk score, tier, and top risk factors as JSON)
python3 cli.py score --input portfolio.jsonl

# 3. Segment into risk tiers with balance-at-risk
python3 cli.py segment --input portfolio.jsonl

# 4. Build the collections work queue (top 10 calls to make first)
python3 cli.py prioritize --input portfolio.jsonl --limit 10

# 5. CI gate: exit 0 = pass, 1 = tier-D share above threshold, 2 = data-quality / IO error
python3 cli.py check --input portfolio.jsonl --max-tier-d-pct 15

# 6. One-command end-to-end demo (generate -> score -> segment -> prioritize -> serve)
python3 demo.py

# 7. Tiny localhost API: POST /score, GET /summary, GET /health on 127.0.0.1
python3 cli.py serve --port 8765
```

## The seeded book at a glance (seed 42, 2,000 loans)

| Tier | Label | Loans | Share | Balance | Avg DPD | Avg score |
|---|---|---|---|---|---|---|
| A | low | 1,046 | 52.3% | $10,073,364 | 1.3 | 0.116 |
| B | moderate | 691 | 34.6% | $7,633,672 | 18.2 | 0.360 |
| C | high | 227 | 11.4% | $2,735,472 | 59.9 | 0.597 |
| D | critical | 36 | 1.8% | $423,672 | 123.4 | 0.817 |

Balance at risk (tiers C + D): **$3,159,144** of $20,866,181 total. 726 loans are delinquent and enter the recovery queue; the top of the queue is a large, recoverable balance — not the deepest delinquency (see prioritisation below). These numbers are pinned by golden eval E2, so any change to the generator or the model shows up as an eval failure, not a surprise.

## How scoring works

The score is additive and fully transparent. Each feature contributes a bounded number of points; the contributions sum to the score, and `top_factors` reports the largest three for every loan.

| Feature | Max points | Rule |
|---|---|---|
| `credit_score_band` | 0.30 | poor 0.30 · fair 0.20 · good 0.10 · very_good 0.04 · excellent 0.00 |
| `days_past_due` | 0.25 | `min(DPD, 90) / 90 × 0.25` — current delinquency, capped at 90 days |
| `missed_payments` | 0.20 | `min(missed, 6) / 6 × 0.20` — payment history, capped at 6 |
| `dti_ratio` | 0.15 | ramps from 0 at DTI 0.20 to full at 0.70 |
| `income_band` | 0.05 | low 0.05 · lower_mid 0.03 · mid 0.015 · upper_mid 0.005 · high 0.00 |
| `apr` | 0.05 | ramps from 0 at 5% APR to full at 30% |

Tiers: **A** < 0.25 · **B** 0.25–0.50 · **C** 0.50–0.75 · **D** ≥ 0.75. A logistic-style squashing helper (`scorer.logistic_check`) is included for calibration comparisons, but the production score stays additive on purpose: a collections strategist must be able to explain any single score, factor by factor, to a reviewer or a regulator. Average scores come out strictly ordered by credit band on the seeded book (poor 0.558 > fair 0.380 > good 0.217 > very_good 0.115 > excellent 0.044) — pinned by eval E4.

**Recovery prioritisation.** Only delinquent loans enter the queue. Each is ranked by `priority_value = balance × recovery_probability / effort`, where recovery probability falls as risk rises but is lifted by recoverable collateral (home 0.90, secured_card 0.85, auto 0.80, personal 0.60, unsecured 0.50), and effort rises with days past due, missed payments, and unsecured status. The queue therefore favours large, recoverable, not-yet-hopeless balances — the calls that return the most dollars per collector hour — with `loan_id` as the deterministic tie-break.

**The generator.** A seeded PRNG (`random.Random(seed)`) draws bands, amounts, and terms, then derives delinquency from a latent propensity driven by credit band, DTI, and income — so the scorer has real signal to find, and worse-credit borrowers are measurably more delinquent on average (pinned by a unit test). Same seed, same book, byte-for-byte (eval E1 pins the JSONL md5).

## Architecture

| Module | Job |
|---|---|
| `generator.py` | Deterministic synthetic Northstar Lending portfolio (2,000 loans by default): bands, amounts, APR, DTI, delinquency behaviour, balance; CSV / JSONL serialisers |
| `scorer.py` | Transparent weighted scoring: per-feature `contributions` that sum to the 0–1 `risk_score`, `top_factors`, tier mapping, logistic reference helper |
| `segment.py` | Tier segmentation + portfolio summary: counts, share, total balance, balance at risk (C+D), avg DPD / score, delinquent counts per tier |
| `prioritize.py` | Recovery-priority work queue: delinquent-only, `balance × recovery_probability / effort`, collateral and effort models, deterministic ordering |
| `validation.py` | Data-quality gate: required fields, band vocabularies, numeric ranges, bool traps, duplicate `loan_id`s — reports issues, never raises on bad data |
| `cli.py` | `generate` / `score` / `segment` / `prioritize` / `check` (CI exit 0/1/2) / `demo` / `serve` (stdlib `http.server` on 127.0.0.1: `POST /score`, `GET /summary`, `GET /health`); CSV, JSONL, and JSON-array inputs |
| `demo.py` | End-to-end narrative with asserts: determinism, explainability sums, tier ordering, queue ordering, CLI exit codes, live localhost serve round-trip |
| `fixtures/` | 30-loan sample portfolio (`sample_portfolio.jsonl` + `.csv`, seed 42) with pinned tier counts A16 / B11 / C2 / D1 |

## Evals

`python3 evals/run_evals.py` → **12/12 golden evals**, report committed at `evals/eval_report.json` (md5 `5f73c5b2a67b4abb52ff46f94cd06bfe`, byte-identical across 3 verified runs):

- **E1** generator determinism — seed 42 JSONL bytes pinned by md5
- **E2** tier counts pinned for the seeded book (A 1046 / B 691 / C 227 / D 36, tier-D 1.8%)
- **E3** explainability contributions sum to the score for all 2,000 loans
- **E4** average risk strictly ordered by credit band
- **E5** tier boundaries at 0.25 / 0.50 / 0.75 pinned
- **E6** recovery queue pinned (726 delinquent loans, top loan and ordering)
- **E7** validation flags planted defects; the generated book validates clean
- **E8** weights sum to 1.00 and bound every contribution
- **E9** score monotonic in days-past-due within each credit band
- **E10** CLI `check` exit codes 0 / 1 / 2
- **E11** serve round-trip matches local scoring and summary exactly
- **E12** bundled fixture pinned (30 loans, tier counts, validates clean)

Unit tests: `python3 -m unittest discover -s tests` → **97 hermetic tests**, including a no-network enforcement test (sockets stubbed), generator determinism, score monotonicity (credit, DPD, missed payments, DTI), tier boundaries, explainability sums, prioritisation ordering and tie-breaks, data-quality validation, CLI exit codes, and serve round-trips.

## Development loop — what the checks validated

The suite passed on its first full run, so there are no staged "bugs caught" to report. What the tests and evals did do is validate three design decisions that could easily have been wrong:

1. **Tier D is unreachable without delinquency — by arithmetic, not by rule.** The non-delinquency features max out at 0.55 (credit 0.30 + DTI 0.15 + income 0.05 + APR 0.05), below the 0.75 tier-D threshold. The segmentation test pins the consequence on the seeded book: every tier-D loan is delinquent (`delinquent_count == count` for tier D). If a future weight change breaks that property, the test fails before the README claim does.
2. **Additive scoring survives rounding.** Contributions are rounded to 6 decimals; the explainability check (E3, plus a unit test over 300 loans) confirms the rounded contributions still sum to the rounded score within 1e-4 for every loan in the book. This is why the production score is additive rather than sigmoid-squashed — a logistic output would have broken the sum property the explainability story depends on.
3. **CSV input needs an explicit coercion layer.** CSV parses every value as a string; without `_coerce_numbers` in the loader, scored-from-CSV portfolios would silently misbehave (string DPD, float term months). `test_score_csv_input` and the CSV fixture pin the round-trip: generate → CSV → score/segment returns identical counts to the JSONL path.

## Scope and honest limits

- **The model is a teaching-grade scoring rule, not a production credit model.** Real collections models are fitted on observed roll rates and validated out-of-sample; this one's weights are documented judgement, chosen to be arguable-with, and the generator's latent propensity is built from the same intuitions — so "the scorer finds signal" is partly by construction. The honest claim is transparency and testability, not predictive power on real books.
- **Recovery probability and effort are heuristics,** not fitted cure-rate models. They encode a sensible ordering (secured, fresher, larger balances first), nothing more.
- **Bands, not raw values,** for age / income / credit keep the artifact free of anything resembling real borrower data — at the cost of granularity a real model would use.
- **The API is a demo surface.** It binds 127.0.0.1 only, holds its portfolio in memory, and resets on restart.

## Why this project

It takes the author's day-job craft — collections and portfolio analytics: delinquency prediction, risk segmentation, recovery prioritisation — and rebuilds it as an analytics-engineering artifact: a deterministic data generator with a data-quality gate, a transparent model with pinned golden evals, a CI check command, and a small API. The same discipline a forward-deployed engineer brings to a customer problem: make the logic inspectable, make the outputs reproducible, and make the failure modes exit codes.
