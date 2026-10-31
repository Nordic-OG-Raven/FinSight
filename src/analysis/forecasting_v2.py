"""Forecasting v2 — regime-routed, segment-level, leakage-safe quarterly revenue forecasting.

Models are regression-based (trend + quarter seasonality, in level or log space) because the
filed series is Q1-Q3 only (no discrete Q4), so it's irregularly spaced — classical ETS/SARIMA
want a regular frequency, whereas a trend+seasonal regression over `quarter_index` (= fy*4+qnum,
which encodes the skipped-Q4 gap) handles it cleanly. Growth names use log space.

Routing:
  - hyper-growth series (e.g. NVDA Compute & Networking)  -> log_trend_seasonal
  - steady/seasonal series (MSFT consolidated, NVDA Graphics) -> trend_seasonal
  - seasonal_naive is always carried as the baseline to beat.

Everything is backtested walk-forward with a strict point-in-time cutoff (via src/analysis/pit):
each quarter is forecast using ONLY data filed before that quarter's own 10-Q. Prediction
intervals are empirical, from the walk-forward residuals.
"""
from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
from typing import Callable, Optional

import numpy as np

from src.analysis import pit


# yfinance reads, memoized per run: the same earnings table is otherwise re-fetched many times
# (once per quarter in the backfill, again in scoring/logging/grading) for identical data. yfinance
# is slow and throttles, so this is the dominant external cost. Static within a run → output-
# identical. Short-lived processes (scripts, weekly job) start cold, so grading sees fresh prints.
@lru_cache(maxsize=256)
def yf_earnings_dates(ticker: str, limit: int):
    import yfinance as yf
    return yf.Ticker(ticker).get_earnings_dates(limit=limit)


@lru_cache(maxsize=256)
def yf_revenue_estimate(ticker: str):
    import yfinance as yf
    return yf.Ticker(ticker).revenue_estimate

# --- series shape -----------------------------------------------------------

def _arrays(points):
    y = np.array([p.value for p in points], dtype=float)
    qidx = np.array([p.fiscal_year * 4 + p.quarter_num for p in points], dtype=float)
    qn = np.array([p.quarter_num for p in points], dtype=int)
    return y, qidx, qn


def _design(qidx, qn):
    # intercept + linear trend over quarter_index + quarter dummies (Q1,Q2; Q3 is the baseline)
    return np.column_stack([
        np.ones_like(qidx, dtype=float),
        qidx.astype(float),
        (qn == 1).astype(float),
        (qn == 2).astype(float),
    ])


# --- models: (points, target_fy, target_qnum) -> point forecast -------------

def seasonal_naive(points, t_fy, t_qn) -> Optional[float]:
    vals = {(p.fiscal_year, p.quarter_num): p.value for p in points}
    base = vals.get((t_fy - 1, t_qn))
    if base is None:
        return None
    yoy = [vals[(fy, qn)] / vals[(fy - 1, qn)] - 1
           for (fy, qn) in vals if (fy - 1, qn) in vals and vals[(fy - 1, qn)]]
    g = float(np.median(yoy[-4:])) if yoy else 0.0
    return base * (1.0 + g)


def _regress(points, t_fy, t_qn, log: bool) -> Optional[float]:
    y, qidx, qn = _arrays(points)
    if len(y) < 5 or (log and np.any(y <= 0)):
        return None
    # center the quarter index on the first observation: the absolute index is ~8100, which makes
    # the log-trend exponent huge and the fit ill-conditioned (exp(pred) overflows). Centering is
    # mathematically equivalent but numerically stable.
    base = qidx[0]
    Y = np.log(y) if log else y
    beta, *_ = np.linalg.lstsq(_design(qidx - base, qn), Y, rcond=None)
    xt = np.array([1.0, float(t_fy * 4 + t_qn) - base, float(t_qn == 1), float(t_qn == 2)])
    pred = float(xt @ beta)
    if log and pred > 50.0:          # guard: exp(50) ~ 5e21; a fit extrapolating past this is broken
        return None
    return float(np.exp(pred)) if log else pred


def trend_seasonal(points, t_fy, t_qn):
    return _regress(points, t_fy, t_qn, log=False)


def log_trend_seasonal(points, t_fy, t_qn):
    return _regress(points, t_fy, t_qn, log=True)


def weighted_trend_seasonal(points, t_fy, t_qn, halflife=6.0):
    """Trend+seasonal fit with exponential RECENCY weights (recent quarters weigh more), so the
    slope reflects the CURRENT regime rather than the full-history average. Robust where growth has
    inflected — e.g. a company that grew fast then plateaued: blind linear extrapolation keeps
    projecting the old slope and overshoots for years (Apple 2023-24), this tracks the flattening.
    Reduces to the plain trend when growth is steady, so the backtest only adopts it where it wins."""
    y, qidx, qn = _arrays(points)
    if len(y) < 5:
        return None
    base = qidx[0]
    w = 0.5 ** ((qidx[-1] - qidx) / halflife)      # 1.0 at the most recent quarter, decaying back
    rw = np.sqrt(w)
    beta, *_ = np.linalg.lstsq(_design(qidx - base, qn) * rw[:, None], y * rw, rcond=None)
    xt = np.array([1.0, float(t_fy * 4 + t_qn) - base, float(t_qn == 1), float(t_qn == 2)])
    pred = float(xt @ beta)
    return pred if (np.isfinite(pred) and pred > 0) else None


def recent_mean(points, t_fy, t_qn, k=4):
    """Mean of the last k observations — right for sticky, mean-reverting series (margins)."""
    vals = [p.value for p in points[-k:]]
    return float(np.mean(vals)) if vals else None


def seasonal_hold(points, t_fy, t_qn):
    """Same fiscal quarter last year, held flat (no growth) — a seasonal margin baseline."""
    vals = {(p.fiscal_year, p.quarter_num): p.value for p in points}
    return vals.get((t_fy - 1, t_qn)) or (points[-1].value if points else None)


MODELS: dict[str, Callable] = {
    "seasonal_naive": seasonal_naive,
    "trend_seasonal": trend_seasonal,
    "log_trend_seasonal": log_trend_seasonal,
    "weighted_trend_seasonal": weighted_trend_seasonal,
}

# Margins are mean-reverting/sticky, not trending — a linear trend overshoots. Use conservative
# models and let the backtest pick.
MARGIN_MODELS: dict[str, Callable] = {
    "recent_mean": recent_mean,
    "seasonal_hold": seasonal_hold,
    "trend_seasonal": trend_seasonal,
}

# which model each series regime prefers (ensemble still computes all + a weighted blend)
REGIME_MODEL = {"growth": "log_trend_seasonal", "seasonal": "trend_seasonal"}


# --- a forecastable series = one or more pit metrics summed (segment roll-up) ---

def _series_asof(db, ticker, components, as_of):
    """Return {component: [Point]} for each component metric, as known at as_of."""
    return {c: pit.series_asof(db, ticker, c, as_of) for c in components}


def _forecast_components(comp_points: dict, t_fy, t_qn) -> dict:
    """Forecast each component with every model; sum components per model -> total forecast."""
    per_model_total: dict[str, Optional[float]] = {}
    for name, fn in MODELS.items():
        parts = [fn(pts, t_fy, t_qn) for pts in comp_points.values() if pts]
        per_model_total[name] = float(np.sum(parts)) if parts and all(p is not None for p in parts) else None
    return per_model_total


# --- leakage-safe walk-forward backtest -------------------------------------

def backtest(db, ticker, components, min_train=6) -> dict:
    """Walk-forward one-step-ahead revenue backtest with a strict point-in-time cutoff.

    `components`: list of pit metrics whose sum is the target (e.g. the two NVDA segments, or just
    ['revenue'] for consolidated). For each target quarter, forecast using only filings dated
    before that quarter's own 10-Q, compare to the actual reported total.
    """
    ticker = ticker.upper()
    report_dates = pit.quarter_report_dates(db, ticker)
    # ground-truth target = latest-vintage consolidated revenue (the real reported total)
    actuals = pit.latest_series(db, ticker, "revenue")
    errs = {m: [] for m in MODELS}          # signed % errors (for residual intervals)
    apes = {m: [] for m in MODELS}
    n_eval = 0
    for tp in actuals:
        cutoff = report_dates.get(tp.period_end)
        if cutoff is None:
            continue
        as_of = cutoff - timedelta(days=1)       # strictly before this quarter's own filing
        comp_points = _series_asof(db, ticker, components, as_of)
        # need enough history known at as_of
        hist_len = max((len(p) for p in comp_points.values()), default=0)
        if hist_len < min_train:
            continue
        preds = _forecast_components(comp_points, tp.fiscal_year, tp.quarter_num)
        actual = tp.value
        if not actual:
            continue
        n_eval += 1
        for m, pred in preds.items():
            if pred is None:
                continue
            errs[m].append((actual - pred) / pred)   # signed rel. error: actual = pred*(1+err)
            apes[m].append(abs(pred - actual) / abs(actual))
    out = {}
    for m in MODELS:
        if apes[m]:
            resid = np.array(errs[m])
            out[m] = {
                "n": len(apes[m]),
                "mape": float(np.mean(apes[m]) * 100),
                "resid_std_pct": float(np.std(resid) * 100),
                "resid": resid,     # kept for empirical intervals
            }
        else:
            out[m] = {"n": 0, "mape": None, "resid_std_pct": None, "resid": np.array([])}
    out["_n_eval"] = n_eval
    return out


def guidance_model(db, ticker) -> Optional[dict]:
    """Guidance-beat model: forecast = company's forward guidance x (1 + median historical beat).

    Leakage-safe: guidance for quarter T is issued at T-1's earnings (before T); the beat rate uses
    only quarters already reported. The single strongest signal for hyper-growth names, where
    filings-only models lag. Actuals come from gold.earnings (includes the derived Q4 so every
    guided quarter can be paired). Returns None if the company doesn't give parseable guidance.
    """
    from sqlalchemy import text

    from src.analysis import guidance as gd

    hist = gd.guidance_history(ticker)
    if len(hist) < 3:
        return None
    eng = pit._engine(db)
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT quarter_end, revenue_usd FROM gold.earnings "
            "WHERE ticker = :t AND revenue_usd IS NOT NULL ORDER BY quarter_end"
        ), {"t": ticker.upper()}).fetchall()
    acts = [(r[0].date() if hasattr(r[0], "date") else r[0], float(r[1])) for r in rows]

    def actual_after(d):
        nxt = [v for qe, v in acts if qe > d]
        return min(nxt) if nxt else None   # first quarter to END after the guidance date

    pairs = [(g.given_date, g.guided_revenue, actual_after(g.given_date)) for g in hist]
    pairs = [(d, gv, a, a / gv - 1.0) for d, gv, a in pairs if a]
    if len(pairs) < 3:
        return None
    apes, resid = [], []
    for i in range(2, len(pairs)):           # walk-forward: beat from prior pairs only
        beat = float(np.median([p[3] for p in pairs[:i]]))
        pred, act = pairs[i][1] * (1 + beat), pairs[i][2]
        apes.append(abs(pred - act) / act)
        resid.append((act - pred) / pred)   # signed rel. error: actual = pred*(1+err)
    beat = float(np.median([p[3] for p in pairs]))
    return {
        "n": len(apes),
        "mape": float(np.mean(apes) * 100) if apes else None,
        "resid": np.array(resid),
        "forecast": hist[-1].guided_revenue * (1 + beat),
        "guidance": hist[-1].guided_revenue,
        "median_beat_pct": beat * 100,
    }


# Student-t upper-tail critical values by degrees of freedom, for the two interval levels we serve
# (80% -> 0.90 per-tail, 90% -> 0.95 per-tail). A small table keeps this dependency-free (scipy is not
# in the API/Modal images) while giving the fat small-sample tails an empirical quantile lacks.
_T_CRIT = {
    0.90: {1: 3.078, 2: 1.886, 3: 1.638, 4: 1.533, 5: 1.476, 6: 1.440, 7: 1.415, 8: 1.397,
           9: 1.383, 10: 1.372, 11: 1.363, 12: 1.356, 13: 1.350, 14: 1.345, 15: 1.341, 16: 1.337,
           17: 1.333, 18: 1.330, 19: 1.328, 20: 1.325},
    0.95: {1: 6.314, 2: 2.920, 3: 2.353, 4: 2.132, 5: 2.015, 6: 1.943, 7: 1.895, 8: 1.860,
           9: 1.833, 10: 1.812, 11: 1.796, 12: 1.782, 13: 1.771, 14: 1.761, 15: 1.753, 16: 1.746,
           17: 1.740, 18: 1.734, 19: 1.729, 20: 1.725},
}
_Z = {0.90: 1.282, 0.95: 1.645}   # normal limit (df > 20)


def _t_crit(df: int, level: float) -> float:
    tail = 0.90 if level <= 0.80 else 0.95
    if df <= 0:
        return _Z[tail]
    return _T_CRIT[tail].get(df, _Z[tail])


def _empirical_interval(point: float, resid: np.ndarray, level=0.80):
    """Bias-corrected Student-t prediction interval on the walk-forward % residuals.

    point x (1 + mean(resid) +/- t_{df} * std(resid)). The t multiplier gives the fat tails a tiny
    empirical sample lacks, and centering on the mean residual folds in any systematic bias — so the
    band covers its nominal rate. Calibration check (n=70, seasonal tickers): nominal 80% -> 82.9%,
    90% -> 91.4% actual coverage (the prior median-centered empirical quantiles covered only ~61/67%)."""
    if point is None or len(resid) < 3:
        return None
    r = np.asarray(resid, dtype=float)
    m, sd = float(np.mean(r)), float(np.std(r, ddof=1))
    t = _t_crit(len(r) - 1, level)
    lo = point * (1 + m - t * sd)
    hi = point * (1 + m + t * sd)
    return (float(min(lo, hi)), float(max(lo, hi)))


def forecast_next(db, ticker, components, regime="seasonal", min_train=6, use_guidance=True) -> dict:
    """Live next-quarter revenue forecast: best-backtested model (incl. the guidance-beat model
    where guidance exists) + inverse-MAPE ensemble + empirical interval."""
    ticker = ticker.upper()
    bt = backtest(db, ticker, components, min_train=min_train)
    # Fold in the guidance-beat model (strongest signal for hyper-growth names) as another model.
    all_models = list(MODELS)
    if use_guidance:
        gm = guidance_model(db, ticker)
        if gm and gm["mape"] is not None:
            bt["guidance_beat"] = gm
            all_models = all_models + ["guidance_beat"]
    # next target quarter = one after the latest known consolidated Q1-Q3 quarter (discrete Q4 is a
    # deferred annual derivation; drop any mislabeled Q4 so the Q1->Q2->Q3->(next year)Q1 map holds)
    latest = [p for p in pit.latest_series(db, ticker, "revenue") if p.quarter_num in (1, 2, 3)]
    if not latest:
        return {"ticker": ticker, "error": "no data"}
    last = latest[-1]
    t_qn = {1: 2, 2: 3, 3: 1}[last.quarter_num]           # Q1->Q2->Q3->(next year)Q1
    t_fy = last.fiscal_year + (1 if last.quarter_num == 3 else 0)

    comp_points = _series_asof(db, ticker, components, pit.date(2100, 1, 1))
    preds = _forecast_components(comp_points, t_fy, t_qn)
    if "guidance_beat" in all_models:
        preds["guidance_beat"] = bt["guidance_beat"]["forecast"]

    # ensemble: inverse-MAPE weight over models that have a backtest + a prediction
    wsum = num = 0.0
    for m in all_models:
        pred, mape = preds.get(m), bt[m]["mape"]
        if pred is not None and mape:
            w = 1.0 / mape
            num += w * pred
            wsum += w
    ensemble = (num / wsum) if wsum else None

    # Let the BACKTEST pick the model (it is the regime detector): lowest-MAPE model that also
    # produced a forecast. Intervals come from that model's empirical residuals, around its point.
    scored = [(bt[m]["mape"], m) for m in all_models if bt[m]["mape"] and preds.get(m) is not None]
    best_model = min(scored)[1] if scored else None
    resid = bt[best_model]["resid"] if best_model else np.array([])
    return {
        "ticker": ticker,
        "target": f"FY{t_fy} Q{t_qn}",
        "components": components,
        "regime_hint": regime,
        "backtest": {m: {k: v for k, v in bt[m].items() if k != "resid"} for m in all_models},
        "n_eval": bt["_n_eval"],
        "forecast_by_model": preds,
        "best_model": best_model,
        "best_model_mape": bt[best_model]["mape"] if best_model else None,
        "best_model_forecast": preds.get(best_model),
        "ensemble": ensemble,
        # center the interval on the point we actually report (best model, else ensemble) using that
        # model's residuals, so the interval always brackets the headline forecast
        "interval_80": _empirical_interval(preds.get(best_model) or ensemble, resid, 0.80),
        "interval_90": _empirical_interval(preds.get(best_model) or ensemble, resid, 0.90),
    }


def _beat_pairs(db, ticker, guid):
    """[(given_date, guided_revenue, next_quarter_actual, beat)] — for the guidance-beat model."""
    from sqlalchemy import text
    eng = pit._engine(db)
    with eng.connect() as conn:
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
            out.append((g.given_date, g.guided_revenue, a, a / g.guided_revenue - 1))
    return out


def realized_backtest(db, ticker, components, method, guid=None, beats=None) -> list:
    """The SINGLE SOURCE OF TRUTH for "what we forecast vs what happened" — the point-in-time
    forecasts we would actually have logged and graded, per reported quarter.

    For each reported quarter (gold.earnings, non-derived, Q1-Q3), forecast it as-of the day before
    its 10-Q using the ticker's routed method, and pair to the reported actual. Both the coverage
    scorecard and the live-ledger backfill read this, so the two can never disagree. Leakage-safe:
    the as-of is strictly before the quarter's own filing; the guidance/beat inputs are resolved
    point-in-time inside `_revenue_asof`.

    Returns [{fy, q, quarter_end, report_date, forecast, actual, ape}], oldest-first.
    """
    from sqlalchemy import text

    ticker = ticker.upper()
    if method == "guidance" and guid is None:
        from src.analysis import guidance as gd
        guid = gd.guidance_history(ticker)
        beats = _beat_pairs(db, ticker, guid)
    model = best_seasonal_model(db, ticker, components) if method != "guidance" else None
    reports = pit.quarter_report_dates(db, ticker)
    with pit._engine(db).connect() as conn:
        qrows = conn.execute(text(
            "SELECT fiscal_year, fiscal_period, quarter_end, revenue_usd FROM gold.earnings "
            "WHERE ticker=:t AND revenue_usd IS NOT NULL AND NOT is_derived ORDER BY quarter_end"
        ), {"t": ticker}).fetchall()
    out = []
    for fy, fp, qe, act in qrows:
        if not str(fp).startswith("Q"):
            continue
        q = int(str(fp)[1])
        qe_d = qe.date() if hasattr(qe, "date") else qe
        rd = reports.get(qe_d)
        if not rd:
            continue
        rev = _revenue_asof(db, ticker, rd - timedelta(days=1), method, guid, beats,
                            target_qend=qe_d, model=model, target_fy=fy, target_qn=q)
        if rev is None:
            continue
        act = float(act)
        out.append({"fy": fy, "q": q, "quarter_end": qe_d, "report_date": rd,
                    "forecast": rev, "actual": act, "ape": abs(rev - act) / abs(act)})
    return out


def best_seasonal_model(db, ticker, components) -> Optional[str]:
    """The lowest-MAPE filings-only model from the walk-forward backtest (what forecast_next would
    pick for a seasonal ticker). Used to make the point-in-time backfill faithful to the live method."""
    bt = backtest(db, ticker, components)
    scored = [(bt[m]["mape"], m) for m in MODELS if bt[m].get("mape")]
    return min(scored)[1] if scored else None


def _revenue_asof(db, ticker, as_of, method, guid=None, beat_pairs=None, target_qend=None, model=None,
                  target_fy=None, target_qn=None):
    """Point-in-time next-quarter revenue forecast by the ticker's method.

    `target_qend` (when known) pins guidance pairing to the quarter it guides: a quarter's forward
    guidance is issued at the PRIOR earnings release, so the guidance for a quarter ending `target_qend`
    is the latest one given strictly before `target_qend`. This is unambiguous and leakage-safe, and
    avoids the trap that the earnings 8-K (carrying the NEXT quarter's guidance) is filed days before
    the 10-Q — so an as-of cutoff on the 10-Q date would grab the wrong quarter's guidance. Without
    `target_qend`, callers that cut off on the earnings date (e.g. eps_vs_consensus) use `as_of`.
    """
    from src.analysis import guidance as gd
    if method == "guidance":
        if target_qend is not None:
            cand = [g for g in guid if g.given_date < target_qend]
            g = cand[-1] if cand else None
        else:
            g = gd.guidance_asof(guid, as_of)
        # walk-forward: beat rate from guidance->actual pairs resolved before this guidance was issued
        prior = [b for (d, _gv, _a, b) in beat_pairs if g and d < g.given_date]
        if g is None or len(prior) < 2:
            return None
        return g.guided_revenue * (1 + float(np.median(prior)))
    # scope is the Q1-Q3 10-Q quarters (discrete Q4 is the annual-minus-YTD derivation, deferred); a
    # rare mislabeled Q4 (from a point-in-time FYE-month resolution) is dropped so the progression holds
    pts = [p for p in pit.series_asof(db, ticker, "revenue", as_of) if p.quarter_num in (1, 2, 3)]
    if len(pts) < 6:
        return None
    # forecast the SPECIFIC target quarter when the caller knows it (the backfill does); otherwise
    # the next quarter after the latest known point. Deriving the target from `last` is wrong when a
    # point-in-time FYE quirk mislabels a quarter, so an explicit target is preferred.
    if target_fy is not None and target_qn is not None:
        t_fy, t_qn = target_fy, target_qn
    else:
        last = pts[-1]
        t_qn = {1: 2, 2: 3, 3: 1}[last.quarter_num]
        t_fy = last.fiscal_year + (1 if last.quarter_num == 3 else 0)
    # faithful to the live method: use the model the backtest selected for this ticker (`model`).
    # Without one, fall back to the median of the non-degenerate models (robust to any single model
    # collapsing or over-extrapolating at a given as-of).
    if model and model in MODELS:
        out = MODELS[model](pts, t_fy, t_qn)
        return out if (out is not None and np.isfinite(out) and out > 0) else None
    cands = [m(pts, t_fy, t_qn) for m in (seasonal_naive, trend_seasonal, log_trend_seasonal)]
    cands = [c for c in cands if c is not None and np.isfinite(c) and c > 0]
    return float(np.median(cands)) if cands else None


def eps_vs_consensus(db, ticker, method, min_prior_beats=2) -> dict:
    """Backtest OUR EPS error vs the analyst-consensus EPS error over the same quarters.

    Our EPS = point-in-time revenue x net-margin / current diluted shares (net income is
    split-immune; using current shares keeps us on the same split-adjusted basis as the
    consensus/reported EPS). Leakage-safe: each quarter forecast as-of the day before its print.
    """
    from datetime import timedelta

    from src.analysis import guidance as gd

    ed = yf_earnings_dates(ticker, 14)
    if ed is None:
        return {"n": 0}
    guid = gd.guidance_history(ticker) if method == "guidance" else None
    beat_pairs = _beat_pairs(db, ticker, guid) if method == "guidance" else None
    model = best_seasonal_model(db, ticker, ["revenue"]) if method != "guidance" else None

    sh = pit.latest_series(db, ticker, "weighted_average_shares_diluted")
    cur_shares = sh[-1].value if sh else None
    if not cur_shares:
        return {"n": 0}

    ours, cons, detail = [], [], []
    for dt, row in ed.iterrows():
        reported, est = row.get("Reported EPS"), row.get("EPS Estimate")
        if reported is None or est is None or np.isnan(reported) or np.isnan(est):
            continue
        as_of = dt.date() - timedelta(days=1)
        rev = _revenue_asof(db, ticker, as_of, method, guid, beat_pairs, model=model)
        if rev is None:
            continue
        nm_pts = _ratio_points(db, ticker, "net_income", as_of)
        if len(nm_pts) < 4:
            continue
        eps_ours = rev * recent_mean(nm_pts, None, None) / cur_shares
        a_ours, a_cons = abs(eps_ours - reported) / abs(reported), abs(est - reported) / abs(reported)
        ours.append(a_ours)
        cons.append(a_cons)
        detail.append((str(dt.date()), round(eps_ours, 2), float(est), float(reported)))
    return {
        "n": len(ours),
        "our_eps_mape": float(np.mean(ours) * 100) if ours else None,
        "consensus_eps_mape": float(np.mean(cons) * 100) if cons else None,
        "detail": detail,
    }


_FAR = None  # set lazily to pit.date(2100,1,1)


def _ratio_points(db, ticker, num_metric, as_of):
    """Quarterly ratio series num_metric/revenue, as known at as_of (for margins)."""
    rev = {p.period_end: p for p in pit.series_asof(db, ticker, "revenue", as_of)}
    num = {p.period_end: p.value for p in pit.series_asof(db, ticker, num_metric, as_of)}
    pts = []
    for pe, rp in sorted(rev.items()):
        if pe in num and rp.value:
            pts.append(pit.Point(pe, rp.fiscal_year, rp.quarter_num, num[pe] / rp.value, rp.filing_date, rp.accession))
    return pts


def _margin_forecast(db, ticker, num_metric, t_fy, t_qn, min_train=6) -> dict:
    """Backtest the margin (num/revenue) across MARGIN_MODELS point-in-time, pick the best, and
    forecast the target quarter's margin with it."""
    reports = pit.quarter_report_dates(db, ticker)
    truth = _ratio_points(db, ticker, num_metric, pit.date(2100, 1, 1))
    apes = {m: [] for m in MARGIN_MODELS}
    for tp in truth:
        cutoff = reports.get(tp.period_end)
        if cutoff is None:
            continue
        hist = _ratio_points(db, ticker, num_metric, cutoff - timedelta(days=1))
        if len(hist) < min_train:
            continue
        for name, fn in MARGIN_MODELS.items():
            pred = fn(hist, tp.fiscal_year, tp.quarter_num)
            if pred is not None and tp.value:
                apes[name].append(abs(pred - tp.value) / abs(tp.value))
    mapes = {m: (float(np.mean(a) * 100) if a else None) for m, a in apes.items()}
    scored = [(v, m) for m, v in mapes.items() if v is not None]
    best = min(scored)[1] if scored else "recent_mean"
    latest = _ratio_points(db, ticker, num_metric, pit.date(2100, 1, 1))
    forecast = MARGIN_MODELS[best](latest, t_fy, t_qn)
    return {"forecast": forecast, "best_model": best, "mape": mapes.get(best), "mapes": mapes}


def forecast_eps(db, ticker, components, regime="seasonal", use_guidance=True) -> dict:
    """Revenue -> margins -> net income -> EPS. Net income (split-immune $) is the backtested
    earnings metric; EPS = net_income / current diluted shares, compared to analyst consensus."""
    far = pit.date(2100, 1, 1)
    rev = forecast_next(db, ticker, components, regime=regime, use_guidance=use_guidance)
    rev_hat = rev.get("best_model_forecast") or rev.get("ensemble")
    fy_s, q_s = rev["target"].replace("FY", "").split(" Q")
    t_fy, t_qn = int(fy_s), int(q_s)

    nm = _margin_forecast(db, ticker, "net_income", t_fy, t_qn)
    om = _margin_forecast(db, ticker, "operating_income", t_fy, t_qn)
    net_income_hat = rev_hat * nm["forecast"] if (rev_hat and nm["forecast"]) else None
    op_income_hat = rev_hat * om["forecast"] if (rev_hat and om["forecast"]) else None

    shares = pit.latest_series(db, ticker, "weighted_average_shares_diluted")
    cur_shares = shares[-1].value if shares else None
    eps_hat = (net_income_hat / cur_shares) if (net_income_hat and cur_shares) else None

    # consensus EPS for the upcoming print (yfinance)
    cons_eps = None
    try:
        import yfinance as yf
        ed = yf.Ticker(ticker).get_earnings_dates(limit=8)
        if ed is not None:
            for _, r in ed.iterrows():
                rep = r.get("Reported EPS")
                if rep is None or (isinstance(rep, float) and np.isnan(rep)):
                    est = r.get("EPS Estimate")
                    cons_eps = float(est) if est is not None and not np.isnan(est) else None
                    break
    except Exception:  # noqa: BLE001
        pass

    return {
        "ticker": ticker, "target": rev["target"],
        "revenue": {"forecast": rev_hat, "best_model": rev["best_model"], "mape": rev["best_model_mape"],
                    "interval_80": rev["interval_80"], "backtest": rev["backtest"], "n_eval": rev["n_eval"]},
        "net_margin": {"forecast": nm["forecast"], "mape": nm["mape"], "model": nm["best_model"]},
        "operating_margin": {"forecast": om["forecast"], "mape": om["mape"], "model": om["best_model"]},
        "net_income_forecast": net_income_hat,
        "operating_income_forecast": op_income_hat,
        "eps_forecast": eps_hat, "consensus_eps": cons_eps,
    }


if __name__ == "__main__":
    import json
    from config import DATABASE_URL

    # NVDA: segment roll-up, growth regime; MSFT: consolidated, seasonal regime
    specs = [
        ("NVDA", ["segment:compute_and_networking", "segment:graphics"], "growth"),
        ("MSFT", ["revenue"], "seasonal"),
    ]
    for tk, comps, regime in specs:
        r = forecast_next(DATABASE_URL, tk, comps, regime=regime)
        print(f"\n=== {tk} revenue -> {r['target']} (n_eval={r['n_eval']}) ===")
        print("  backtest MAPE:", {m: (round(r['backtest'][m]['mape'], 1) if r['backtest'][m]['mape'] else None) for m in r['backtest']})
        fb = r["forecast_by_model"]
        print("  model forecasts ($B):", {m: (round(v / 1e9, 1) if v else None) for m, v in fb.items()})
        print(f"  best model: {r['best_model']} (MAPE {r['best_model_mape']:.1f}%) -> {r['best_model_forecast']/1e9:.1f}B")
        print(f"  ensemble: {r['ensemble']/1e9:.1f}B" if r["ensemble"] else "  ensemble: None")
        if r["interval_80"]:
            print(f"  80% interval: [{r['interval_80'][0]/1e9:.1f}, {r['interval_80'][1]/1e9:.1f}]B")
