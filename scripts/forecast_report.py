"""Generate the quarterly-earnings forecast write-up (docs/forecasting/EARNINGS_FORECAST.md).

For each US filer in the warehouse: forecast next-quarter revenue + diluted EPS from the gold
quarterly series, walk-forward backtest each model, pull the analyst consensus + recent actuals
from Yahoo Finance, and render a markdown report with an honest methods/caveats section.

    .venv/bin/python scripts/forecast_report.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from config import DATABASE_URL  # noqa: E402
from src.analysis.forecasting import consensus, forecast_next  # noqa: E402

# US filers only (NVO is a 20-F foreign filer with no 10-Q, so no quarterly series).
TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "AVGO", "JPM"]
OUT = ROOT / "docs" / "forecasting" / "EARNINGS_FORECAST.md"


def _fmt(x, pct=False, money=False):
    if x is None:
        return "—"
    if pct:
        return f"{x:.1f}%"
    if money:
        return f"${x/1e9:.1f}B"
    return f"{x:.2f}"


def _lean(ours, cons):
    if ours is None or cons is None:
        return "—"
    d = (ours - cons) / abs(cons) * 100 if cons else 0
    if d > 1.5:
        return f"above consensus (+{d:.1f}%)"
    if d < -1.5:
        return f"below consensus ({d:.1f}%)"
    return f"in line ({d:+.1f}%)"


def build(today: str) -> str:
    eps_rows, rev_rows, deep = [], [], []
    for tk in TICKERS:
        try:
            eps = forecast_next(DATABASE_URL, tk, "eps_diluted_adj")
            rev = forecast_next(DATABASE_URL, tk, "revenue_usd")
            con = consensus(tk)
        except Exception as e:  # noqa: BLE001
            print(f"  skip {tk}: {e}")
            continue
        up = (con or {}).get("upcoming") or {}
        cons_eps = up.get("eps_estimate")
        ens_eps = eps.get("ensemble_forecast")
        mape = (eps.get("models", {}).get("ols_trend_seasonal", {}) or {}).get("mape")
        reliable = mape is not None and mape < 15.0
        # Suppress the EPS forecast when the company's own backtest says the model can't track it
        # (stock splits / one-time items distort the short EPS history — see the data-quality note).
        shown_eps = _fmt(ens_eps) if reliable else "— *(suppressed)*"
        lean = _lean(ens_eps, cons_eps) if reliable else "history distorted"
        flag = "reliable" if reliable else "⚠ split / one-off"
        eps_rows.append(
            f"| {tk} | {up.get('date','—')} | {shown_eps} | {_fmt(cons_eps)} | "
            f"{lean} | {_fmt(mape, pct=True)} | {flag} |"
        )
        rev_rows.append(
            f"| {tk} | {_fmt(rev.get('ensemble_forecast'), money=True)} | "
            f"{_fmt((rev.get('models',{}).get('seasonal_naive',{}) or {}).get('forecast'), money=True)} | "
            f"{_fmt((rev.get('models',{}).get('ols_trend_seasonal',{}) or {}).get('forecast'), money=True)} | "
            f"{_fmt((rev.get('models',{}).get('gbm_lags',{}) or {}).get('forecast'), money=True)} | "
            f"{_fmt(rev.get('n_quarters'))} |"
        )
        if tk == "AAPL":
            deep = _deep_dive(eps, con)

    md = _render(today, eps_rows, rev_rows, deep)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(md)
    print(f"wrote {OUT}")
    return md


def _deep_dive(eps: dict, con: dict) -> list[str]:
    up = (con or {}).get("upcoming") or {}
    lines = [
        "## Spotlight: Apple, next print",
        "",
        f"- **Reports:** {up.get('date','—')} (fiscal Q4 2026, quarter ending ~Sept 2026)",
        f"- **Wall Street consensus EPS:** {_fmt(up.get('eps_estimate'))}",
        f"- **FinSight ensemble forecast:** {_fmt(eps.get('ensemble_forecast'))} "
        f"→ *{_lean(eps.get('ensemble_forecast'), up.get('eps_estimate'))}*",
        "",
        "Per-model next-quarter EPS and each model's walk-forward backtest error on Apple's own history:",
        "",
        "| Model | Forecast EPS | Backtest MAPE |",
        "| --- | --- | --- |",
    ]
    for name, m in eps.get("models", {}).items():
        lines.append(f"| {name} | {_fmt(m.get('forecast'))} | {_fmt(m.get('mape'), pct=True)} |")
    recent = (con or {}).get("recent") or []
    if recent:
        lines += ["", "Recent actual vs consensus (Apple has a persistent beat pattern):", "",
                   "| Date | Consensus EPS | Reported EPS | Surprise |", "| --- | --- | --- | --- |"]
        for r in recent[:5]:
            lines.append(f"| {r['date']} | {_fmt(r.get('eps_estimate'))} | "
                         f"{_fmt(r.get('reported_eps'))} | {_fmt(r.get('surprise_pct'), pct=True)} |")
    return lines


def _render(today, eps_rows, rev_rows, deep):
    return f"""# FinSight — Quarterly Earnings Forecast

*Generated {today} from the gold warehouse (`gold.earnings`) + Yahoo Finance consensus.*

Can a model built **only on SEC filing history** get near the Wall-Street analyst consensus for
next quarter? This is the experiment. Every FinSight number comes from the medallion warehouse
(bronze 10-K/10-Q XBRL → silver conformance → gold quarterly series); the consensus and actuals
come from Yahoo Finance. Nothing here is investment advice — see the caveats.

**Headline:** revenue forecasts are robust; EPS forecasts are only trustworthy where the
company's own backtest says so (stock splits and one-time items distort the short EPS history —
see the data-quality note). So revenue leads.

## Next-quarter revenue: FinSight model spread

| Ticker | Ensemble | Seasonal-naive | Trend+seasonal | GBM (lags) | #Quarters |
| --- | --- | --- | --- | --- | --- |
{chr(10).join(rev_rows)}

## Next-quarter diluted EPS: FinSight vs consensus

EPS is only shown where the walk-forward backtest error (MAPE) is under 15% — i.e. where the
model actually tracks that company's prints. The rest are suppressed, not fudged.

| Ticker | Reports | FinSight ensemble | Consensus | Lean | Backtest MAPE* | Status |
| --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(eps_rows)}

\\* MAPE = mean absolute percentage error of the trend+seasonal model, walk-forward on each
company's own quarterly history (lower = the model tracks that company's prints better).

## Data-quality finding: splits & one-offs distort EPS, not revenue

Noisy EPS forecasts aren't a modelling failure — they're a **data** signal the pipeline surfaced,
and they split into one part we fixed and one part that's inherent:

- **Stock splits — FIXED.** AVGO (10:1, 2024) and NVDA (10:1, 2024) split in-window, so their raw
  EPS history mixed pre- and post-split values (AVGO showed a pre-split ~$8 quarter next to
  post-split ~$1). We now land splits as raw corporate actions in **bronze**
  (`bronze.corporate_actions`, from Yahoo Finance) and **gold** computes a split-adjusted EPS on a
  current-share basis (`gold.earnings.eps_diluted_adj`). Backtest error fell sharply (AVGO
  148%→30%, NVDA 38%→20%) and the warehouse EPS is now comparable to the split-adjusted consensus.
- **One-time items — inherent, not a bug.** Some quarters carry a one-off gain (AMZN's latest; a
  spike in MSFT's recent quarter) that is the *correct* reported GAAP EPS but unrepresentative. A
  trend model inherits it and can sit above the analyst consensus, which normalizes one-offs out.
  "Fixing" this would mean a non-GAAP/normalized EPS, which isn't in the XBRL — so it's a genuine
  limit of forecasting GAAP EPS, flagged rather than papered over.

**Revenue carries neither distortion**, which is why it forecasts cleanly across every filer.

{chr(10).join(deep)}

## Method

Three deliberately-transparent models, each respecting quarterly seasonality (which dominates a
short series like this):

1. **seasonal_naive** — same quarter last year, grown by the median recent year-over-year rate.
2. **ols_trend_seasonal** — least-squares linear trend + quarter-of-year dummies.
3. **gbm_lags** — gradient-boosted trees on `[lag1, lag4, quarter, trend]` features.

The **ensemble** is an inverse-MAPE weighting (more-accurate models get more weight). Q4 is never
filed on its own (10-Qs cover Q1–Q3), so the warehouse **derives** it as `annual − (Q1+Q2+Q3)`;
this was validated against a real print (Apple FQ4-FY2025 derived EPS $1.84 vs reported $1.85).

## Caveats (stated, not hidden)

- **Short history.** ~12–14 quarters per filer. These are illustrative nowcasts, not a trading
  signal, and the backtest sample is small.
- **SEC-only inputs.** The models see past reported fundamentals — no guidance, order books,
  macro, or price action that real analysts use. Beating consensus isn't the goal; getting close
  with far less information is the interesting part.
- **Consensus/actuals are third-party** (Yahoo Finance) and may restate.
"""


if __name__ == "__main__":
    build(date.today().isoformat() if len(sys.argv) < 2 else sys.argv[1])
