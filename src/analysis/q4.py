"""Q4 (fourth-fiscal-quarter) revenue forecasting — the quarter the Q1-Q3 pipeline defers.

Companies file 10-Qs for Q1-Q3 only; Q4 is reported in the annual 10-K as the full-year figure, so
the discrete Q4 = annual - (Q1+Q2+Q3 YTD). For December-fiscal-year names (AMZN, GOOGL, JPM) that
missing quarter is the Oct-Dec HOLIDAY quarter — their biggest — so it is worth forecasting.

Leakage-safe: Q4[fy] becomes knowable only when the fy annual 10-K is filed (~weeks after Q4 ends),
so each Q4 point is dated to its ORIGINAL 10-K filing date (not the latest restated vintage), and a
forecast for Q4[fy] uses only the fy's already-filed Q1-Q3 plus prior years' Q4s.

Q4 is just another quarter to the companies that guide it: their Q3 earnings release guides the
next quarter, which IS Q4, so the same guidance-beat model we use for Q1-Q3 applies. Three models,
backtest-selected per ticker:
  - guide_quarter: Q4[fy] = (the Q3-release guidance that targets Q4) x (1 + median historical beat).
                   The strongest signal where the company guides (AAPL, NVDA, AMZN, AVGO); this is
                   why Q4 should be EASY, not hard (9 months known + the company's own guide).
  - ytd_ratio:     Q4[fy] = YTD3[fy] x median(prior Q4/YTD3 ratios) — filed 9 months x a seasonal
                   ratio. Fallback where there is no parseable guidance.
  - seasonal_naive: Q4[fy] = Q4[fy-1] x (1 + median YoY) — fallback where Q4 is lumpy (GOOGL).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
from sqlalchemy import text

from src.analysis import pit
from src.analysis import guidance as gd
from src.extraction.canonical_labels import CANONICAL

MIN_PRIOR = 2         # need at least this many prior Q4s to form a ratio/seasonal estimate
MIN_GUIDE_PAIRS = 6   # min total guidance-beat pairs (ALL quarters) before guidance is "reliable" —
                      # Q4 history is only ~5 years, so eligibility rests on the company's overall
                      # guidance-beat track record, not on Q4-specific points.
GUIDE_Q4_CAP = 12.0   # reject garbage-parsed Q4 guidance (e.g. a mis-grabbed number) by a MAPE cap
GUIDE_LIMIT = 40      # earnings releases of guidance history to scan (~10yr; covers all our Q4s)


def _guidance_overall_mape(beats: list) -> float | None:
    """Walk-forward MAPE of the guidance-beat model over ALL guided quarters — the reliability signal
    that justifies trusting guidance for Q4 (which has too few points to judge on its own)."""
    if len(beats) < MIN_GUIDE_PAIRS:
        return None
    ap = []
    for i in range(2, len(beats)):
        b = float(np.median([p[3] for p in beats[:i]]))
        ap.append(abs(beats[i][1] * (1 + b) - beats[i][2]) / beats[i][2])
    return float(np.mean(ap) * 100) if ap else None


@dataclass
class Q4Point:
    fiscal_year: int
    q4: float            # annual - YTD3
    ytd3: float          # Q1+Q2+Q3
    known_date: date     # original annual 10-K filing date (when Q4 became knowable)
    quarter_end: date | None = None   # the fiscal-year-end date (Q4's period end)


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
            out.append(Q4Point(fy, annual - ytd3[fy], ytd3[fy], fd, quarter_end=pe))
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


def _beat_pairs(db, ticker: str, guid: list) -> list:
    """(given_date, guided_revenue, next-quarter actual, beat). Pairs each guidance to the first
    quarter to END after it; gold.earnings includes the derived Q4, so Q4 guidance pairs too."""
    with pit._engine(db).connect() as conn:
        rows = conn.execute(text(
            "SELECT quarter_end, revenue_usd FROM gold.earnings "
            "WHERE ticker=:t AND revenue_usd IS NOT NULL ORDER BY quarter_end"
        ), {"t": ticker.upper()}).fetchall()
    acts = [(r[0].date() if hasattr(r[0], "date") else r[0], float(r[1])) for r in rows]
    out = []
    for g in guid:
        nxt = [v for qe, v in acts if qe > g.given_date]
        if nxt:
            a = min(nxt)
            out.append((g.given_date, g.guided_revenue, a, a / g.guided_revenue - 1.0))
    return out


def _q3_asof(db, ticker: str, fye_month: int, fy: int) -> date | None:
    """When we'd forecast Q4[fy]: the latest Q1-Q3[fy] 10-Q filing date (YTD3 complete, Q4 is next)."""
    cands = []
    for qend, fdate in pit.quarter_report_dates(db, ticker).items():
        f, q = pit._fy_and_quarter(qend, fye_month)
        if f == fy and q in (1, 2, 3):
            cands.append(fdate if isinstance(fdate, date) else date.fromisoformat(str(fdate)[:10]))
    return max(cands) if cands else None


def _guide_quarter_pred(guid: list, beats: list, as_of: date, target_qend: date | None,
                        walk_forward: bool = True) -> float | None:
    """Q4 = (latest guidance issued on/before as_of) x (1 + median beat) — the same guidance-beat
    model used for Q1-Q3, applied to the Q3-release guidance that targets Q4. Guarded so the guidance
    actually targets Q4 (issued during the Q4 period), and leakage-safe (beats from before as_of)."""
    if target_qend is None:
        return None
    g = gd.guidance_asof(guid, as_of)
    if g is None:
        return None
    # Q4 guidance is issued at the Q3 earnings release, i.e. during the Q4 period (after Q3 ended,
    # before the fiscal year ends). Reject an older guide that targets some other quarter.
    if not (target_qend - timedelta(days=150) < g.given_date < target_qend):
        return None
    bt = [b[3] for b in beats if (b[0] < as_of if walk_forward else True)]
    if len(bt) < 2:
        return None
    return g.guided_revenue * (1 + float(np.median(bt)))


def q4_backtest(db, ticker: str) -> dict:
    """Walk-forward Q4 backtest; returns per-model MAPE + the per-year forecasts of the best model.

    For each historical Q4[fy], forecast it point-in-time (only data filed before) by three models
    and compare to the realized Q4; pick the lower-MAPE model. guide_quarter (the company's own
    Q3-release guidance x the historical beat) is the strongest where the company guides; ytd_ratio /
    seasonal_naive are the filings-only fallback where it does not.
    """
    ticker = ticker.upper()
    with pit._engine(db).connect() as conn:
        fye_month = pit._fye_month(conn, ticker, date(2100, 1, 1))
    full = q4_history(db, ticker, date(2100, 1, 1), fye_month)
    guid = gd.guidance_history(ticker, limit=GUIDE_LIMIT)
    beats = _beat_pairs(db, ticker, guid) if guid else []
    models = ("ytd_ratio", "seasonal_naive", "guide_quarter")
    apes = {m: [] for m in models}
    per_year = {m: [] for m in models}
    for i, tp in enumerate(full):
        preds: dict = {}
        prior = [h for h in full[:i] if h.known_date < tp.known_date]
        if len(prior) >= MIN_PRIOR:
            preds["ytd_ratio"] = _forecast_from(prior, tp.ytd3, "ytd_ratio")
            preds["seasonal_naive"] = _forecast_from(prior, tp.ytd3, "seasonal_naive")
        if guid:
            as_of = _q3_asof(db, ticker, fye_month, tp.fiscal_year)
            if as_of:
                preds["guide_quarter"] = _guide_quarter_pred(guid, beats, as_of, tp.quarter_end)
        for m in models:
            pred = preds.get(m)
            if pred is not None and pred > 0 and tp.q4:
                ape = abs(pred - tp.q4) / abs(tp.q4)
                apes[m].append(ape)
                per_year[m].append({"fy": tp.fiscal_year, "q4": 4, "forecast": pred,
                                    "actual": tp.q4, "ape": ape,
                                    "report_date": tp.known_date, "quarter_end": tp.quarter_end})
    mapes = {m: (float(np.mean(apes[m]) * 100) if apes[m] else None) for m in models}
    counts = {m: len(apes[m]) for m in models}
    # guide_quarter is eligible when the company's guidance-beat is reliable OVERALL (many guided
    # quarters) and its Q4 points are sane (reject mis-parsed guidance via the cap). Q4-specific
    # count stays small forever (only ~5 Q4s exist), so it can't be the gate.
    gm_mape = _guidance_overall_mape(beats)
    guide_eligible = (gm_mape is not None and counts["guide_quarter"] >= 1
                      and mapes["guide_quarter"] is not None and mapes["guide_quarter"] < GUIDE_Q4_CAP)
    scored = [(v, m) for m, v in mapes.items()
              if v is not None and (m != "guide_quarter" or guide_eligible)]
    best = min(scored)[1] if scored else None
    return {"ticker": ticker, "mapes": mapes, "counts": counts, "guide_overall_mape": gm_mape,
            "best_model": best, "best_mape": mapes.get(best), "history": per_year.get(best, [])}


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
    best = bt["best_model"]
    if not best:
        return None
    with pit._engine(db).connect() as conn:
        fye_month = pit._fye_month(conn, ticker, date(2100, 1, 1))
    hist = q4_history(db, ticker, date(2100, 1, 1), fye_month)
    tqe = (hist[-1].quarter_end + timedelta(days=364)) if (hist and hist[-1].quarter_end) else None
    if best == "guide_quarter":
        guid = gd.guidance_history(ticker, limit=GUIDE_LIMIT)
        beats = _beat_pairs(db, ticker, guid)
        pred = _guide_quarter_pred(guid, beats, date.today(), tqe, walk_forward=False)
    else:
        pred = _forecast_from(hist, ytd3, best)
    if pred is None or pred <= 0:
        return None
    resid = np.array([h["ape"] for h in bt["history"]])
    lo = pred * (1 - float(np.quantile(resid, 0.8))) if len(resid) >= 3 else None
    hi = pred * (1 + float(np.quantile(resid, 0.8))) if len(resid) >= 3 else None
    return {"ticker": ticker, "target_fy": target_fy, "quarter": 4, "forecast": pred,
            "model": "q4_" + best, "mape": bt["best_mape"],
            "interval_80": [lo, hi] if lo else None, "target_qend": tqe}
