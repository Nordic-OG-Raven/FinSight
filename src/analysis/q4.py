"""Q4 (fourth-fiscal-quarter) revenue forecasting — the quarter the Q1-Q3 pipeline defers.

Companies file 10-Qs for Q1-Q3 only; Q4 is reported in the annual 10-K as the full-year figure, so
the discrete Q4 = annual - (Q1+Q2+Q3 YTD). For December-fiscal-year names (AMZN, GOOGL, JPM) that
missing quarter is the Oct-Dec HOLIDAY quarter — their biggest — so it is worth forecasting.

Leakage-safe: Q4[fy] becomes knowable only when the fy annual 10-K is filed (~weeks after Q4 ends),
so each Q4 point is dated to its ORIGINAL 10-K filing date (not the latest restated vintage), and a
forecast for Q4[fy] uses only the fy's already-filed Q1-Q3 plus prior years' Q4s.

Two models, backtest-selected per ticker (like revenue):
  - ytd_ratio:     Q4[fy] = YTD3[fy] x median(prior Q4/YTD3 ratios) — anchors on the filed 9 months
                   x a stable seasonal ratio. Best for most names (AMZN 5.8%, JPM 4.2%, MSFT 3.2%).
  - seasonal_naive: Q4[fy] = Q4[fy-1] x (1 + median YoY) — better where Q4 is lumpy (GOOGL).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
from sqlalchemy import text

from src.analysis import pit
from src.extraction.canonical_labels import CANONICAL

MIN_PRIOR = 2   # need at least this many prior Q4s to form a ratio/seasonal estimate


@dataclass
class Q4Point:
    fiscal_year: int
    q4: float            # annual - YTD3
    ytd3: float          # Q1+Q2+Q3
    known_date: date     # original annual 10-K filing date (when Q4 became knowable)


def annual_report_dates(db, ticker: str) -> dict:
    """{annual period_of_report: original (earliest) annual filing date} — the Q4 leakage cutoff."""
    with pit._engine(db).connect() as conn:
        rows = conn.execute(text(
            "SELECT period_of_report, min(filing_date) FROM bronze.raw_filings "
            "WHERE ticker=:t AND form IN ('10-K','20-F','40-F') AND period_of_report IS NOT NULL "
            "GROUP BY period_of_report"), {"t": ticker.upper()}).fetchall()
    return {r[0]: (r[1] if isinstance(r[1], date) else date.fromisoformat(str(r[1])[:10])) for r in rows}


def _annual_revenue(db, ticker: str) -> list[tuple[date, float, date]]:
    """(period_end, original annual revenue value, original filing date), earliest vintage per year."""
    cc = CANONICAL["revenue"]
    with pit._engine(db).connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT ON (f.period_end) f.period_end, f.value_numeric, rf.filing_date
            FROM bronze.raw_facts f JOIN bronze.raw_filings rf USING (accession)
            WHERE f.ticker=:t AND f.is_dimensioned=false AND f.concept=ANY(:cc)
              AND f.period_type='duration' AND (f.period_end - f.period_start) BETWEEN 330 AND 380
              AND f.value_numeric IS NOT NULL
            ORDER BY f.period_end, rf.filing_date ASC, array_position(:cc, f.concept)"""),
            {"t": ticker.upper(), "cc": cc}).fetchall()
    out = []
    for pe, val, fd in rows:
        fd = fd if isinstance(fd, date) else date.fromisoformat(str(fd)[:10])
        out.append((pe, float(val), fd))
    return out


def q4_history(db, ticker: str, as_of: date, fye_month: int | None = None) -> list[Q4Point]:
    """Point-in-time Q4 revenue history known at `as_of`, oldest-first."""
    ticker = ticker.upper()
    if fye_month is None:
        with pit._engine(db).connect() as conn:
            fye_month = pit._fye_month(conn, ticker, date(2100, 1, 1))
    # YTD3[fy] = sum of the fy's Q1+Q2+Q3 (consolidated, latest known)
    ytd3: dict[int, float] = {}
    for p in pit.series_asof(db, ticker, "revenue", as_of):
        if p.quarter_num in (1, 2, 3):
            ytd3[p.fiscal_year] = ytd3.get(p.fiscal_year, 0.0) + p.value
    out: list[Q4Point] = []
    for pe, annual, fd in _annual_revenue(db, ticker):
        if fd > as_of:
            continue
        fy, _ = pit._fy_and_quarter(pe, fye_month)
        if fy in ytd3 and ytd3[fy] > 0:
            out.append(Q4Point(fy, annual - ytd3[fy], ytd3[fy], fd))
    out.sort(key=lambda p: p.fiscal_year)
    return out


def _forecast_from(hist: list[Q4Point], ytd3_target: float, model: str) -> float | None:
    """Forecast a Q4 given prior Q4 history and the target year's YTD3, by the chosen model."""
    if model == "ytd_ratio":
        ratios = [h.q4 / h.ytd3 for h in hist if h.ytd3]
        return ytd3_target * float(np.median(ratios)) if len(ratios) >= MIN_PRIOR and ytd3_target else None
    # seasonal_naive: last year's Q4 grown by the median YoY of consecutive Q4s
    if not hist:
        return None
    last = hist[-1]
    yoys = [hist[i].q4 / hist[i - 1].q4 - 1 for i in range(1, len(hist))
            if hist[i].fiscal_year == hist[i - 1].fiscal_year + 1 and hist[i - 1].q4]
    return last.q4 * (1 + (float(np.median(yoys)) if yoys else 0.0))


def q4_backtest(db, ticker: str) -> dict:
    """Walk-forward Q4 backtest; returns per-model MAPE + the per-year forecasts of the best model.

    For each historical Q4[fy], forecast it using only Q4s whose annual report predates fy's annual
    report (strict point-in-time), then compare to the realized Q4. Picks the lower-MAPE model.
    """
    ticker = ticker.upper()
    full = q4_history(db, ticker, date(2100, 1, 1))
    models = ("ytd_ratio", "seasonal_naive")
    apes = {m: [] for m in models}
    per_year = {m: [] for m in models}
    for i, tp in enumerate(full):
        prior = [h for h in full[:i] if h.known_date < tp.known_date]
        if len(prior) < MIN_PRIOR:
            continue
        for m in models:
            pred = _forecast_from(prior, tp.ytd3, m)
            if pred is not None and pred > 0 and tp.q4:
                apes[m].append(abs(pred - tp.q4) / abs(tp.q4))
                per_year[m].append({"fy": tp.fiscal_year, "q4": 4, "forecast": pred,
                                    "actual": tp.q4, "ape": abs(pred - tp.q4) / abs(tp.q4),
                                    "report_date": tp.known_date})
    mapes = {m: (float(np.mean(apes[m]) * 100) if apes[m] else None) for m in models}
    scored = [(v, m) for m, v in mapes.items() if v is not None]
    best = min(scored)[1] if scored else None
    return {"ticker": ticker, "mapes": mapes, "best_model": best,
            "best_mape": mapes.get(best), "history": per_year.get(best, [])}


def forecast_next_q4(db, ticker: str) -> dict | None:
    """Live next-Q4 forecast, IF the latest filed quarter is Q3 (so Q4 is the next report). Uses the
    backtest-selected model + all Q4 history known today. Returns None when Q4 isn't the next quarter
    or there isn't enough history."""
    ticker = ticker.upper()
    rev = [p for p in pit.latest_series(db, ticker, "revenue") if p.quarter_num in (1, 2, 3)]
    if not rev or rev[-1].quarter_num != 3:
        return None                       # Q4 is only the "next" quarter right after Q3
    target_fy = rev[-1].fiscal_year
    ytd3 = sum(p.value for p in rev if p.fiscal_year == target_fy and p.quarter_num in (1, 2, 3))
    bt = q4_backtest(db, ticker)
    if not bt["best_model"]:
        return None
    hist = q4_history(db, ticker, date(2100, 1, 1))
    pred = _forecast_from(hist, ytd3, bt["best_model"])
    if pred is None or pred <= 0:
        return None
    resid = np.array([h["ape"] for h in bt["history"]])
    lo = pred * (1 - float(np.quantile(resid, 0.8))) if len(resid) >= 3 else None
    hi = pred * (1 + float(np.quantile(resid, 0.8))) if len(resid) >= 3 else None
    return {"ticker": ticker, "target_fy": target_fy, "quarter": 4, "forecast": pred,
            "model": "q4_" + bt["best_model"], "mape": bt["best_mape"],
            "interval_80": [lo, hi] if lo else None}
