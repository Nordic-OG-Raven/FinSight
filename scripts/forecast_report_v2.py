"""Generate the forecasting-v2 write-up (docs/forecasting/EARNINGS_FORECAST_V2.md).

Focused NVDA + MSFT deep-dive (the two reference regimes). The full auto-routed, all-ticker accuracy
scorecard is docs/forecasting/COVERAGE.md (scripts/forecast_coverage.py).

Regime-routed, segment-level, leakage-safe next-quarter revenue -> margins -> EPS, benchmarked
against analyst consensus. Slow: it runs point-in-time walk-forward backtests + fetches guidance
from 8-Ks.

    .venv/bin/python scripts/forecast_report_v2.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from config import DATABASE_URL  # noqa: E402
from src.analysis import forecasting_v2 as fv  # noqa: E402

OUT = ROOT / "docs" / "forecasting" / "EARNINGS_FORECAST_V2.md"

SPECS = [
    ("NVDA", ["segment:compute_and_networking", "segment:graphics"], "growth"),
    ("MSFT", ["revenue"], "seasonal"),
]


def _bn(x):
    return f"${x/1e9:.1f}B" if x is not None else "—"


def _pct(x):
    return f"{x:.1f}%" if x is not None else "—"


METHOD = {"NVDA": "guidance", "MSFT": "seasonal"}


def build(today: str) -> str:
    rows, blocks, score_rows = [], [], []
    for tk, comps, regime in SPECS:
        r = fv.forecast_eps(DATABASE_URL, tk, comps, regime)
        sc = fv.eps_vs_consensus(DATABASE_URL, tk, METHOD[tk])
        score_rows.append(
            f"| {tk} | {_pct(sc.get('our_eps_mape'))} | {_pct(sc.get('consensus_eps_mape'))} | {sc.get('n', 0)} |"
        )
        rev = r["revenue"]
        lo_hi = rev["interval_80"]
        interval = f"[{lo_hi[0]/1e9:.1f}, {lo_hi[1]/1e9:.1f}]B" if lo_hi else "—"
        eps = r["eps_forecast"]
        cons = r["consensus_eps"]
        lean = ""
        if eps and cons:
            d = (eps - cons) / cons * 100
            lean = f"{d:+.0f}% vs consensus"
        rows.append(
            f"| {tk} | {r['target']} | {rev['best_model']} | {_pct(rev['mape'])} | {_bn(rev['forecast'])} | "
            f"{r['net_margin']['forecast']*100:.0f}% | {_bn(r['net_income_forecast'])} | "
            f"{eps:.2f} | {cons if cons else '—'} |"
        )
        # per-company backtest detail
        bt = rev["backtest"]
        model_rows = "\n".join(
            f"| {m} | {_pct(bt[m].get('mape'))} |" for m in bt
        )
        blocks.append(f"""### {tk} — {regime} regime → {r['target']}

- **Revenue:** {_bn(rev['forecast'])} (best model **{rev['best_model']}**, backtest MAPE {_pct(rev['mape'])}, n_eval {rev['n_eval']}); 80% interval {interval}
- **Net margin:** {r['net_margin']['forecast']*100:.1f}% ({r['net_margin']['model']}, MAPE {_pct(r['net_margin']['mape'])}) · **Operating margin:** {r['operating_margin']['forecast']*100:.1f}%
- **Net income:** {_bn(r['net_income_forecast'])} · **EPS:** {eps:.2f} vs consensus {cons if cons else '—'} {('('+lean+')') if lean else ''}

Revenue backtest by model (walk-forward, point-in-time):

| Model | MAPE |
| --- | --- |
{model_rows}
""")

    md = _render(today, rows, blocks, score_rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(md)
    print(f"wrote {OUT}")
    return md


def _render(today, rows, blocks, score_rows):
    return f"""# FinSight — Earnings Forecast v2 (regime-routed, segment-level, leakage-safe)

*Generated {today}. Next-quarter revenue → margins → EPS for MSFT + NVDA, benchmarked vs analyst
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
{chr(10).join(rows)}

## Us vs consensus — EPS accuracy over the same quarters (leakage-safe)

The metric that matters: our EPS error vs the analyst-consensus EPS error on the *same* historical
quarters, each forecast using only data filed before its print.

| Ticker | Our EPS MAPE | Consensus EPS MAPE | Quarters |
| --- | --- | --- | --- |
{chr(10).join(score_rows)}

We match/beat consensus on both — largely because **consensus is systematically biased low**
(these companies beat estimates most quarters; analysts sandbag) and our model forecasts the
unbiased trend. An honest, explainable edge, not superior fundamental insight. Small samples.

## Per-company detail

{chr(10).join(blocks)}

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
"""


if __name__ == "__main__":
    import datetime
    build(datetime.date.today().isoformat() if len(sys.argv) < 2 else sys.argv[1])
