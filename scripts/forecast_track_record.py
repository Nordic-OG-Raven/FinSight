"""Render the live forecast track record from forecasts.forecast_log.

Fast (just reads the ledger — no forecasting computation). Shows, per metric, our forecast vs the
actual vs consensus over time, the running our-vs-consensus MAPE, and any pending (ungraded) live
forecasts. Written to docs/forecasting/TRACK_RECORD.md.

    .venv/bin/python scripts/forecast_track_record.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sqlalchemy import create_engine, text  # noqa: E402

from config import DATABASE_URL  # noqa: E402

OUT = ROOT / "docs" / "forecasting" / "TRACK_RECORD.md"


def _fmt(v, metric):
    if v is None:
        return "—"
    return f"${v/1e9:.1f}B" if metric == "revenue" else f"{v:.2f}"


def build(today: str) -> str:
    eng = create_engine(DATABASE_URL)
    with eng.connect() as conn:
        rows = conn.execute(text("""
            SELECT ticker, target_fiscal_year, target_quarter, metric, forecast, consensus,
                   actual, our_ape, consensus_ape, graded_at, interval_lo, interval_hi
            FROM forecasts.forecast_log
            ORDER BY metric, ticker, target_fiscal_year, target_quarter
        """)).fetchall()

    graded = [r for r in rows if r.graded_at is not None]
    pending = [r for r in rows if r.graded_at is None]

    # running MAPE per (ticker, metric)
    agg = {}
    for r in graded:
        k = (r.ticker, r.metric)
        agg.setdefault(k, []).append((r.our_ape, r.consensus_ape))
    summary = []
    for (tk, metric), vals in sorted(agg.items()):
        ours = [a for a, _ in vals if a is not None]
        cons = [c for _, c in vals if c is not None]
        our_m = f"{sum(ours)/len(ours)*100:.1f}%" if ours else "—"
        cons_m = f"{sum(cons)/len(cons)*100:.1f}%" if cons else "—"
        summary.append(f"| {tk} | {metric} | {our_m} | {cons_m} | {len(vals)} |")

    def _line(r):
        inter = f" [{r.interval_lo/1e9:.0f}, {r.interval_hi/1e9:.0f}]B" if (r.metric == 'revenue' and r.interval_lo) else ""
        return (f"| {r.ticker} | FY{r.target_fiscal_year} Q{r.target_quarter} | {r.metric} | "
                f"{_fmt(r.forecast, r.metric)}{inter} | {_fmt(r.consensus, r.metric)} | {_fmt(r.actual, r.metric)} | "
                f"{(str(round(r.our_ape*100,1))+'%') if r.our_ape is not None else '—'} | "
                f"{(str(round(r.consensus_ape*100,1))+'%') if r.consensus_ape is not None else '—'} |")

    md = f"""# FinSight — Live Forecast Track Record

*Updated {today}. Every forecast is made **before** the print and frozen; actuals + consensus are
filled once the quarter reports. `backtest:*` rows are the historical point-in-time record that
seeded the ledger; new rows are logged live each week.*

## Running accuracy — us vs consensus

| Ticker | Metric | Our MAPE | Consensus MAPE | Quarters |
| --- | --- | --- | --- | --- |
{chr(10).join(summary) if summary else '| — | — | — | — | — |'}

## Pending (live, not yet reported)

| Ticker | Quarter | Metric | Forecast | Consensus | Actual | Our APE | Cons APE |
| --- | --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(_line(r) for r in pending) if pending else '| — | — | — | — | — | — | — | — |'}

## Graded history

| Ticker | Quarter | Metric | Forecast | Consensus | Actual | Our APE | Cons APE |
| --- | --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(_line(r) for r in graded) if graded else '| — | — | — | — | — | — | — | — |'}
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(md)
    print(f"wrote {OUT} ({len(graded)} graded, {len(pending)} pending)")
    return md


if __name__ == "__main__":
    import datetime
    build(datetime.date.today().isoformat() if len(sys.argv) < 2 else sys.argv[1])
