"""Coverage scorecard — auto-route every ingested ticker and measure forecast accuracy.

For each ticker this:
  1. auto-routes it with `regime.classify` (guides? growth vs seasonal),
  2. backtests the next-quarter REVENUE forecast (leakage-safe walk-forward MAPE), and
  3. scores OUR EPS vs analyst-CONSENSUS EPS over the same quarters.

It prints a table and writes docs/forecasting/COVERAGE.md. EVERY company is reported honestly; the
Ledger column reflects the curated live set (`forecast_log.LEDGER`) — revenue for all members, EPS
only where the margin->EPS chain is competitive with consensus — so the scorecard and the live
ledger never disagree.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy import text  # noqa: E402

from config import DATABASE_URL  # noqa: E402
from src.analysis import forecast_log  # noqa: E402
from src.analysis import pit  # noqa: E402
from src.analysis import regime  # noqa: E402


def score(db, ticker: str) -> dict:
    r = regime.classify(db, ticker)
    row = {"route": r, "rev_mape": None, "rev_n": 0, "rev_cons_mape": None, "rev_cons_n": 0,
           "our_eps_mape": None, "cons_eps_mape": None, "eps_n": 0}
    # Accuracy is READ FROM THE LEDGER (the single source of truth, populated by the backfill), so
    # the scorecard and the track record report identical numbers. The scorecard adds the route and
    # the consensus comparison; it does not recompute the backtest.
    try:
        with pit._engine(db).connect() as conn:
            rev = conn.execute(text(
                "SELECT avg(our_ape), count(*), "
                "avg(consensus_ape) FILTER (WHERE consensus_ape IS NOT NULL), "
                "count(*) FILTER (WHERE consensus_ape IS NOT NULL) "
                "FROM forecasts.forecast_log WHERE ticker=:t "
                "AND metric='revenue' AND model LIKE 'backtest:%' AND our_ape IS NOT NULL"),
                {"t": ticker}).fetchone()
            eps = conn.execute(text(
                "SELECT avg(our_ape), avg(consensus_ape), count(*) FROM forecasts.forecast_log "
                "WHERE ticker=:t AND metric='eps' AND model LIKE 'backtest:%' AND our_ape IS NOT NULL"),
                {"t": ticker}).fetchone()
        if rev and rev[0] is not None:
            row.update(rev_mape=float(rev[0] * 100), rev_n=int(rev[1]),
                       rev_cons_mape=float(rev[2] * 100) if rev[2] is not None else None,
                       rev_cons_n=int(rev[3]))
        if eps and eps[0] is not None:
            row.update(our_eps_mape=float(eps[0] * 100),
                       cons_eps_mape=float(eps[1] * 100) if eps[1] is not None else None,
                       eps_n=int(eps[2]))
    except Exception as e:  # noqa: BLE001
        row["rev_error"] = str(e)[:120]
    # the ledger universe is the explicit, curated set (forecast_log.LEDGER), not a bare MAPE gate:
    # revenue is logged for every member; EPS only where the margin->EPS chain is competitive.
    cfg = forecast_log.LEDGER.get(ticker)
    row["in_ledger"] = cfg is not None
    row["logs_eps"] = bool(cfg and cfg.get("eps"))
    return row


def _fmt(x, suffix="%"):
    return f"{x:.1f}{suffix}" if isinstance(x, (int, float)) else "  n/a"


def render(rows: dict) -> str:
    lines = [
        "# FinSight — Forecasting Coverage Scorecard",
        "",
        "Auto-routed with `regime.classify`; revenue MAPE is a leakage-safe walk-forward backtest. "
        "The vs-consensus columns compare OUR error to the analyst CONSENSUS error over the same "
        "quarters (revenue consensus via MarketBeat ~2yr; EPS consensus via yfinance).",
        "",
        "| Ticker | Route | Rev MAPE | us vs Rev cons | Our EPS | EPS cons | Ledger |",
        "|--------|-------|---------:|:--------------:|--------:|---------:|:------:|",
    ]
    for tk, row in rows.items():
        r = row["route"]
        ew = " ✅" if (isinstance(row["our_eps_mape"], (int, float)) and isinstance(row["cons_eps_mape"], (int, float))
                       and row["our_eps_mape"] <= row["cons_eps_mape"]) else ""
        rw = " ✅" if (isinstance(row["rev_mape"], (int, float)) and isinstance(row["rev_cons_mape"], (int, float))
                       and row["rev_mape"] <= row["rev_cons_mape"]) else ""
        rev_cons = (f"{_fmt(row['rev_mape'])} vs {_fmt(row['rev_cons_mape'])}{rw} (n={row['rev_cons_n']})"
                    if row["rev_cons_mape"] is not None else "—")
        ledger = ("revenue+EPS" if row["logs_eps"] else "revenue") if row["in_ledger"] else "—"
        lines.append(
            f"| {tk} | {r.method} | {_fmt(row['rev_mape'])} ({row['rev_n']}) | {rev_cons} | "
            f"{_fmt(row['our_eps_mape'])}{ew} | {_fmt(row['cons_eps_mape'])} | {ledger} |")
    rev = [tk for tk, row in rows.items() if row["in_ledger"]]
    eps = [tk for tk, row in rows.items() if row["logs_eps"]]
    lines += ["",
              f"**Logged live — revenue ({len(rev)}):** {', '.join(rev) or 'none'}. "
              f"**EPS ({len(eps)}):** {', '.join(eps) or 'none'} (logged where the margin→EPS chain is "
              f"credible; we beat consensus on NVDA and trail it on MSFT, shown either way; elsewhere "
              f"EPS is distorted by one-time items, acquisition amortization, FX, or bank accounting).",
              "", "Every company is reported here honestly; the Ledger column shows what we commit to "
              "live. ✅ marks quarters where our EPS matched or beat consensus.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    tickers = sys.argv[1:] or ["NVDA", "AMZN", "AVGO", "MSFT", "GOOGL", "AAPL", "JPM",
                               "META", "TSLA", "NFLX", "AMD", "ORCL", "CRM"]
    rows = {}
    for tk in tickers:
        print(f"scoring {tk} ...", flush=True)
        rows[tk] = score(DATABASE_URL, tk)
    out = Path(__file__).resolve().parent.parent / "docs" / "forecasting" / "COVERAGE.md"
    out.write_text(render(rows))
    print("\n" + render(rows))
    print(f"\nwrote {out}")
