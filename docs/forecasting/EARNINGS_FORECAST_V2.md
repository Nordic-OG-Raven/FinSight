# FinSight — Earnings Forecast v2 (regime-routed, segment-level, leakage-safe)

*Generated 2026-10-29. Next-quarter revenue → margins → EPS for MSFT + NVDA, benchmarked vs analyst
consensus.*

This is a **pitch-grade** forecaster. Each company is routed to the model that fits its regime, the
**backtest picks the winner**, and everything is **leakage-safe**: every quarter is forecast using
only data filed before that quarter's own report (point-in-time reconstruction from the bronze
layer, which retains every filing vintage), guidance is taken from the *prior* 8-K, and beat rates
use only already-reported quarters.

**Success criterion is not 100% accuracy** (earnings surprise is irreducible, and a backtest
claiming ~100% signals leakage). It's: beat the seasonal-naive baseline, match/approach consensus
with less information, and be honestly calibrated.

## Next-quarter forecast

| Ticker | Quarter | Revenue model | Rev MAPE | Revenue | Net margin | Net income | EPS | Consensus EPS |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NVDA | FY2027 Q3 | guidance_beat | 0.7% | $113.6B | 61% | $69.9B | 2.88 | 2.47 |
| MSFT | FY2027 Q2 | log_trend_seasonal | 2.1% | $95.7B | 40% | $38.5B | 5.17 | 4.82 |

## Per-company detail

### NVDA — growth regime → FY2027 Q3

- **Revenue:** $113.6B (best model **guidance_beat**, backtest MAPE 0.7%, n_eval 5); 80% interval —
- **Net margin:** 61.5% (recent_mean, MAPE 15.4%) · **Operating margin:** 64.0%
- **Net income:** $69.9B · **EPS:** 2.88 vs consensus 2.47 (+16% vs consensus)

Revenue backtest by model (walk-forward, point-in-time):

| Model | MAPE |
| --- | --- |
| seasonal_naive | 24.8% |
| trend_seasonal | 12.5% |
| log_trend_seasonal | 34.6% |
| guidance_beat | 0.7% |

### MSFT — seasonal regime → FY2027 Q2

- **Revenue:** $95.7B (best model **log_trend_seasonal**, backtest MAPE 2.1%, n_eval 5); 80% interval [91.4, 95.7]B
- **Net margin:** 40.3% (recent_mean, MAPE 5.8%) · **Operating margin:** 47.8%
- **Net income:** $38.5B · **EPS:** 5.17 vs consensus 4.82 (+7% vs consensus)

Revenue backtest by model (walk-forward, point-in-time):

| Model | MAPE |
| --- | --- |
| seasonal_naive | 2.3% |
| trend_seasonal | 3.1% |
| log_trend_seasonal | 2.1% |


## Method

- **Point-in-time, leakage-safe** (`src/analysis/pit.py`): series reconstructed as known at each
  as-of date from `bronze.raw_facts` + `raw_filings.filing_date`. Silver/gold dedup to the latest
  vintage and would leak, so the backtest never uses them.
- **Regime-routed models** (`src/analysis/forecasting_v2.py`): level/log trend+seasonal and
  seasonal-naive over `quarter_index` (handles the filed-Q1–Q3 gap); the backtest selects the best.
- **Guidance-beat** (`src/analysis/guidance.py`): for hyper-growth names, forecast =
  company guidance × (1 + median historical beat). Guidance is parsed point-in-time from the
  earnings-release 8-K (not in XBRL). This is the signal filings-only models lack.
- **Margins → EPS**: net/operating margins (sticky → recent-mean usually wins over a trend),
  applied to the revenue forecast → net income (split-immune) → EPS = net income / current diluted
  shares, vs analyst consensus (yfinance).

## Findings & honest caveats

- **Stable names (MSFT) are forecastable from filings alone** — ~2% revenue MAPE, matching
  consensus with no external data.
- **Hyper-growth names (NVDA) are not** — filings-only models lag the acceleration and sit below
  consensus (~12% MAPE). Capturing the company's own **guidance** closes the gap (NVDA beats its
  guidance by a near-constant ~5%/qtr → ~1% MAPE). This is *the* result: the method a fund cares
  about is knowing *which* companies need guidance and quantifying it.
- **Segment decomposition** didn't improve NVDA's 1-step revenue accuracy (one segment is ~90% of
  revenue) — it buys explainability, not accuracy, here.
- **Margins are the weaker link** (~6–15% MAPE) and are mean-reverting; EPS inherits revenue +
  margin error. Net income (dollars) is the clean, split-immune earnings metric.
- **Short history** (~11 filed quarters; ~4 guidance points) → small backtest samples; NVDA's
  interval needs more 8-Ks to firm up. More history is the top improvement lever.
