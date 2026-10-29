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
from typing import Callable, Optional

import numpy as np

from src.analysis import pit

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
    Y = np.log(y) if log else y
    beta, *_ = np.linalg.lstsq(_design(qidx, qn), Y, rcond=None)
    xt = np.array([1.0, float(t_fy * 4 + t_qn), float(t_qn == 1), float(t_qn == 2)])
    pred = float(xt @ beta)
    return float(np.exp(pred)) if log else pred


def trend_seasonal(points, t_fy, t_qn):
    return _regress(points, t_fy, t_qn, log=False)


def log_trend_seasonal(points, t_fy, t_qn):
    return _regress(points, t_fy, t_qn, log=True)


MODELS: dict[str, Callable] = {
    "seasonal_naive": seasonal_naive,
    "trend_seasonal": trend_seasonal,
    "log_trend_seasonal": log_trend_seasonal,
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
            errs[m].append((pred - actual) / actual)
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


def _empirical_interval(point: float, resid: np.ndarray, level=0.80):
    """Prediction interval from the empirical distribution of walk-forward % residuals."""
    if point is None or len(resid) < 3:
        return None
    lo_q, hi_q = (1 - level) / 2, 1 - (1 - level) / 2
    lo = point * (1 + np.quantile(resid, lo_q))
    hi = point * (1 + np.quantile(resid, hi_q))
    return (float(min(lo, hi)), float(max(lo, hi)))


def forecast_next(db, ticker, components, regime="seasonal", min_train=6) -> dict:
    """Live next-quarter revenue forecast: regime model + inverse-MAPE ensemble + interval,
    with the backtest accuracy attached (so we only trust what the backtest earns)."""
    ticker = ticker.upper()
    bt = backtest(db, ticker, components, min_train=min_train)
    # next target quarter = one after the latest known consolidated quarter
    latest = pit.latest_series(db, ticker, "revenue")
    if not latest:
        return {"ticker": ticker, "error": "no data"}
    last = latest[-1]
    t_qn = {1: 2, 2: 3, 3: 1}[last.quarter_num]           # Q1->Q2->Q3->(next year)Q1
    t_fy = last.fiscal_year + (1 if last.quarter_num == 3 else 0)

    comp_points = _series_asof(db, ticker, components, pit.date(2100, 1, 1))
    preds = _forecast_components(comp_points, t_fy, t_qn)

    # ensemble: inverse-MAPE weight over models that have a backtest + a prediction
    wsum = num = 0.0
    for m, pred in preds.items():
        mape = bt[m]["mape"]
        if pred is not None and mape:
            w = 1.0 / mape
            num += w * pred
            wsum += w
    ensemble = (num / wsum) if wsum else None

    # Let the BACKTEST pick the model (it is the regime detector): lowest-MAPE model that also
    # produced a forecast. Intervals come from that model's empirical residuals, around the
    # ensemble point (robust blend as the primary number).
    scored = [(bt[m]["mape"], m) for m in MODELS if bt[m]["mape"] and preds.get(m) is not None]
    best_model = min(scored)[1] if scored else None
    resid = bt[best_model]["resid"] if best_model else np.array([])
    return {
        "ticker": ticker,
        "target": f"FY{t_fy} Q{t_qn}",
        "components": components,
        "regime_hint": regime,
        "backtest": {m: {k: v for k, v in bt[m].items() if k != "resid"} for m in MODELS},
        "n_eval": bt["_n_eval"],
        "forecast_by_model": preds,
        "best_model": best_model,
        "best_model_mape": bt[best_model]["mape"] if best_model else None,
        "best_model_forecast": preds.get(best_model),
        "ensemble": ensemble,
        "interval_80": _empirical_interval(ensemble, resid, 0.80),
        "interval_90": _empirical_interval(ensemble, resid, 0.90),
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
        print("  backtest MAPE:", {m: (round(r['backtest'][m]['mape'], 1) if r['backtest'][m]['mape'] else None) for m in MODELS})
        fb = r["forecast_by_model"]
        print("  model forecasts ($B):", {m: (round(v / 1e9, 1) if v else None) for m, v in fb.items()})
        print(f"  best model: {r['best_model']} (MAPE {r['best_model_mape']:.1f}%) -> {r['best_model_forecast']/1e9:.1f}B")
        print(f"  ensemble: {r['ensemble']/1e9:.1f}B" if r["ensemble"] else "  ensemble: None")
        if r["interval_80"]:
            print(f"  80% interval: [{r['interval_80'][0]/1e9:.1f}, {r['interval_80'][1]/1e9:.1f}]B")
