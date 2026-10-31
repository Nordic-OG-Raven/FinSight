# FinSight forecasting — engineering log & decisions

Durable record of the non-obvious forecasting/warehouse decisions, dead-ends, and bug post-mortems.
The lean pointer in agent memory references this file; keep the detail here, not there.

Live accuracy numbers live in `COVERAGE.md` / `TRACK_RECORD.md` (both read the ledger). This file is
the *why*.

---

## Coverage & framing (the honest pitch)

- Coverage = 13 tickers (NVDA, MSFT, AMZN, AVGO, GOOGL, AAPL, JPM, META, TSLA, NFLX, AMD, ORCL, CRM).
  Revenue logged for all; EPS only for NVDA + MSFT.
- **EPS-coverage ceiling (validated):** direct net-income modeling is worse than the revenue×margin
  chain everywhere (NVDA 45% vs 4.5% on the chain). For AVGO/AMZN/GOOGL/JPM, net income is dominated by
  one-time items / acquisition amortization / bank P&L that analysts model but a time-series can't
  (GOOGL NI swung $35B→$112B→$26B). EPS=NVDA/MSFT only is the honest statistical max. A real extension
  needs non-GAAP/adjusted-EPS modeling (strip amortization + one-offs) — a separate, larger effort.
- **Framing discipline:** we log EPS where the chain is *credible*. We EDGE consensus on NVDA EPS
  (4.5 vs 4.8%) but TRAIL it on MSFT (8.4 vs 5.7%); show both. Never say "where competitive" (overclaim).
- **Consensus reframe (humbling, keep it honest):** consensus beats our revenue on 11/13. We beat it
  only where guidance is the signal (NVDA, AVGO). Revenue is NOT "our strongest vs the street." The real
  edge is a leakage-safe, automated, calibrated system that MATCHES the street on stable names and BEATS
  it on guidance-driven hyper-growth. Consensus also beats us on Q4 across the board.

## Q4 forecasting

- Q1–Q3 are filed discretely; Q4 is only in the 10-K, so Q4 = annual − 9-month-YTD, each point dated to
  its original 10-K filing (leakage-safe), logged as a distinct metric `revenue_q4` (never blended with
  clean Q1–Q3). Code: `src/analysis/q4.py`.
- **Guidance-anchored Q4 (the win):** Q4 was the *worst* quarter (9.6% vs Q1–Q3 7.3%), which is backwards
  — industry-wide Q4 is the easiest (9 months known + full-year guidance; consensus ~1.9%). Root cause:
  `q4.py` routed every Q4 through a seasonal ratio and ignored guidance. Fix: a `guide_quarter` model =
  the Q3-release guidance targeting Q4 × the historical beat (the same guidance-beat used for Q1–Q3).
  Backtest-selected; eligibility rests on the company's *overall* guidance-beat reliability
  (`_guidance_overall_mape`, ≥6 pairs), not Q4-specific points (only ~5 exist), with a 12% MAPE cap that
  auto-rejects mis-parsed guidance (ORCL 15000%, CRM 92%). Walk-forward: NVDA 18→3.4, AMD 17→6.4,
  META 15→4.3, AMZN 5.8→1.1, AVGO 3.4→3.0 (avg 11.9→3.6%). AAPL/TSLA/GOOGL unchanged (no $ guidance).
- `guidance.py` changes: `_GOV` accepts "we expect … to be in the range of" (META); `_PR_ATTACH_RE`
  accepts bare 99.1 exhibit names (AMD's `q2…991.htm`); an `earnings_only=True` mode (item-2.02 filter +
  160-8-K scan) that finds earnings diluted out of the latest-20 window (AMD/META had 0 before).
- **HARD LESSON (prod regression, caught + fixed):** making the item-2.02 + deep history the GLOBAL
  default wrecked NVDA Q1–Q3 (rev 1.2→6.8%, EPS 4.5→31%) because the guidance-beat is RECENCY-WEIGHTED
  and NVDA's beat regime flipped (2022 crypto crash → 2023+ AI boom); deep history pulls in the dead
  regime. So deep/earnings-filtered history is **Q4-only** (`earnings_only=True`); Q1–Q3 stays on the
  default recent latest-20 8-Ks. More history is NOT always better. Always re-check Q1–Q3 coverage after
  any guidance-parser/history change.

## Dead-ends (tested, rejected — don't re-attempt without a new method)

- **Segment-level revenue forecasting = NO-GO.** Intuition "analysts model segments, so sum per-segment
  forecasts" does not improve accuracy. Go/no-go with the same seasonal-YoY method both ways: on AMZN
  (clean segments reconciling to 100% of total), bottom-up = top-down (9.6 vs 9.4%, zero gain). Other
  payoff names (GOOGL, AMD) need heavy per-era member curation (renames vs merges vs splits from segment
  realignments) just to get inputs that reconcile; naive attempts gave 65–269% reconciliation and garbage
  MAPE. Why: a company's segments are correlated, so decomposing doesn't diversify away aggregate error,
  and segment data is noisier/structurally unstable. What analysts gain from segments is per-segment
  JUDGMENT (channel checks), not the arithmetic. Raw dimensioned segment facts DO exist in
  `silver.fct_financial_facts` (axis `us-gaap_StatementBusinessSegmentsAxis`) for 11/13 (not CRM; NFLX is
  single-segment); `gold.segment_revenue_quarterly` only materializes MSFT+NVDA via the
  `segment_members` seed.
- **Guidance-form expansion = NO-GO from SEC data.** TSLA's earnings 8-K EX-99.1 gives only narrative
  outlook (no delivery/revenue numbers); AAPL gives NO forward guidance in the filing at all (stopped in
  2020 — it's on the earnings call). Parsing these needs earnings-CALL TRANSCRIPTS, a non-SEC source that
  breaks the EDGAR-provenance thesis. The weak names' gap (AAPL/TSLA/GOOGL ~7–16%) is STRUCTURAL, not a
  fillable data gap. We've extracted all guidance that exists in SEC data; the system is at the SEC-data
  frontier. A pure-model improvement on the no-guidance names is the only remaining SEC-safe lever.

## Track record — the guidance-available cut (live)

The headline us-vs-consensus blends forecasts made WITH vs WITHOUT an extractable $ guidance signal. The
honest apples-to-apples is **row-level** (`model LIKE '%guid%'`): **3.1–3.2% vs consensus 2.5% WITH
guidance (n=33)** vs 7.6% vs 2.3% WITHOUT. Key insight: our entire gap to consensus is explained by
guidance availability on OUR side (consensus ~2.4% either way). A company-level guided/non-guided split
does NOT separate us (both buckets ~7%) — it must be row-level. `/api/track-record` returns
`guided_overall` + a per-row `guided` flag; the frontend shows the cut + a "guides" tag.

## 52/53-week filer quarter-labeling (bug → fix → guards)

**Symptom:** AAPL's track record was inflated ~3 points; FY2023 Q4 graded against a corrupt actual of
$171.3B (true $89.5B).

**Root cause:** AAPL/AVGO/NVDA/AMD run 52/53-week fiscal calendars; their quarter-ends drift into the
next month (AAPL fiscal-Q1 = 14 weeks, Q2 ends Apr 1, Q3 Jul 1) and the SEC filing's quarter tag is
sometimes blank. AAPL FY2023 Q1 dropped out, and the derived Q4 subtracted the wrong cumulative
(annual − 6-month-YTD = 171.3 instead of annual − 9-month-YTD = 89.5).

**Two labelers had to be fixed (they must stay in sync):**
1. The warehouse conforming layer (`dbt/models/silver/fct_financial_facts.sql`) — was blank-passthrough.
2. The forecaster's own point-in-time reader (`src/analysis/pit.py`, reads bronze directly for
   leakage-safety, can't use the warehouse) — was a month-bucket `ceil`, which mislabeled drifted
   quarters (AAPL Q2→Q3, Q3→Q4; same for AMD/NVDA in their drift years). Fixing only the warehouse left
   the ledger still wrong until pit.py was fixed too.

Both now DERIVE the quarter from quarter-end vs fiscal-year-end, rounded to absorb drift:
`4 − round(((fye_month − end_month + 12) % 12) / 3)`, clamped 1–4. Validated to reproduce every
correctly-labeled quarter (28,060 in the warehouse; all changes in pit were drift corrections).

**Guards added** (`dbt/tests/`, fail CI): `assert_quarter_facts_labeled.sql` (every quarter-grain fact
has a Q1–Q4 label) and `assert_complete_quarters_per_fy.sql` (every completed fiscal year exposes all 4
quarters, scoped past each company's first quarter-bearing year to skip boundary/annual-only filers).

**Root lesson:** validation was concentrated on raw-fact magnitudes + schema shape. The field that broke
(the quarter label) and the operation that manufactured the bad number (the Q4 derivation) had NO checks.
After any period/labeling change, re-check Q1–Q3 coverage AND that completed years reconcile to annual.
