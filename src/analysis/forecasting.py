"""Quarterly earnings forecasting on the gold warehouse (Phase 3 / ML content).

Reads gold.earnings (quarterly revenue / EPS series, Q1-Q3 reported + Q4 derived), forecasts the
NEXT fiscal quarter with three deliberately-transparent models, walk-forward backtests each on the
company's own history, and benchmarks against the Wall-Street analyst consensus + actual outcome
pulled from Yahoo Finance (yfinance). The point is an honest apples-to-apples: *can a model built
only on SEC filing history get near the consensus / the real number?*

Caveat (stated, not hidden): with ~12-14 quarters per filer the series is short, so these are
illustrative nowcasts, not a trading signal. Seasonality (e.g. Apple's December quarter) is the
dominant structure and every model here is built to respect it.

Models:
  - seasonal_naive        : same quarter last year, grown by the median recent YoY rate
  - ols_trend_seasonal    : least-squares linear trend + quarter-of-year dummies
  - gbm_lags              : gradient-boosted trees on [lag1, lag4, quarter, trend] features
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
from sqlalchemy import create_engine, text

NEXT_Q = {1: 2, 2: 3, 3: 4, 4: 1}


@dataclass
class Series:
    ticker: str
    metric: str
    values: np.ndarray          # chronological
    quarters: np.ndarray        # fiscal quarter number (1-4) aligned to values
    labels: list[str] = field(default_factory=list)  # e.g. "FY2026 Q3"

    def __len__(self) -> int:
        return len(self.values)


# ---- data access ------------------------------------------------------------

def load_series(database_url: str, ticker: str, metric: str = "revenue_usd") -> Series:
    """Load one company's chronological quarterly series from gold.earnings."""
    if metric not in {"revenue_usd", "net_income_usd", "operating_income_usd",
                      "eps_diluted", "eps_diluted_adj"}:
        raise ValueError(f"unsupported metric: {metric}")
    sql = text(f"""
        SELECT fiscal_year, fiscal_period, quarter_num, {metric} AS val
        FROM gold.earnings
        WHERE ticker = :tk AND {metric} IS NOT NULL
        ORDER BY quarter_index
    """)
    eng = create_engine(database_url)
    with eng.connect() as conn:
        rows = conn.execute(sql, {"tk": ticker.upper()}).fetchall()
    vals = np.array([float(r.val) for r in rows])
    qs = np.array([int(r.quarter_num) for r in rows])
    labels = [f"FY{r.fiscal_year} {r.fiscal_period}" for r in rows]
    return Series(ticker.upper(), metric, vals, qs, labels)


# ---- models (each: (y, q, target_q) -> next-quarter prediction) -------------

def seasonal_naive(y: np.ndarray, q: np.ndarray, target_q: int) -> Optional[float]:
    """Same-quarter-last-year value, scaled by the median YoY growth of recent quarters."""
    same = np.where(q == target_q)[0]
    if len(same) == 0:
        return None
    base = y[same[-1]]
    yoy = [y[i] / y[i - 4] - 1.0 for i in range(4, len(y)) if y[i - 4] != 0]
    g = float(np.median(yoy[-4:])) if yoy else 0.0
    return base * (1.0 + g)


def _design(idx: np.ndarray, qs: np.ndarray) -> np.ndarray:
    # intercept, trend, and quarter dummies for Q1..Q3 (Q4 is the baseline)
    cols = [np.ones_like(idx, dtype=float), idx.astype(float)]
    for qq in (1, 2, 3):
        cols.append((qs == qq).astype(float))
    return np.column_stack(cols)


def ols_trend_seasonal(y: np.ndarray, q: np.ndarray, target_q: int) -> Optional[float]:
    """Least-squares linear trend + quarter-of-year seasonal dummies."""
    n = len(y)
    if n < 5:
        return None
    idx = np.arange(n)
    X = _design(idx, q)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    x_next = _design(np.array([n]), np.array([target_q]))[0]
    return float(x_next @ beta)


def gbm_lags(y: np.ndarray, q: np.ndarray, target_q: int) -> Optional[float]:
    """Gradient-boosted trees on [lag1, lag4, quarter one-hot, trend]."""
    n = len(y)
    if n < 8:  # need a few lag-4 samples to train on
        return None
    from sklearn.ensemble import GradientBoostingRegressor

    def feats(i: int, qq: int) -> list[float]:
        return [y[i - 1], y[i - 4], float(qq == 1), float(qq == 2), float(qq == 3),
                float(qq == 4), float(i)]

    X = np.array([feats(i, int(q[i])) for i in range(4, n)])
    ytrain = y[4:n]
    model = GradientBoostingRegressor(n_estimators=200, max_depth=2, learning_rate=0.05,
                                      random_state=0)
    model.fit(X, ytrain)
    x_next = np.array([feats(n, target_q)])  # uses y[n-1], y[n-4]
    return float(model.predict(x_next)[0])


MODELS: dict[str, Callable] = {
    "seasonal_naive": seasonal_naive,
    "ols_trend_seasonal": ols_trend_seasonal,
    "gbm_lags": gbm_lags,
}


# ---- backtest + forecast ----------------------------------------------------

def backtest(s: Series, model: Callable, min_train: int = 8) -> dict:
    """Walk-forward one-step-ahead. Returns MAPE / MAE over the held-out tail."""
    errs, apes = [], []
    for t in range(min_train, len(s)):
        pred = model(s.values[:t], s.quarters[:t], int(s.quarters[t]))
        if pred is None:
            continue
        actual = s.values[t]
        errs.append(abs(actual - pred))
        if actual != 0:
            apes.append(abs(actual - pred) / abs(actual))
    if not errs:
        return {"n": 0, "mape": None, "mae": None}
    return {"n": len(errs), "mape": float(np.mean(apes) * 100) if apes else None,
            "mae": float(np.mean(errs))}


def forecast_next(database_url: str, ticker: str, metric: str = "revenue_usd",
                  min_train: int = 8) -> dict:
    """Forecast the next fiscal quarter per model + an inverse-MAPE-weighted ensemble."""
    s = load_series(database_url, ticker, metric)
    if len(s) < 6:
        return {"ticker": s.ticker, "metric": metric, "error": "series too short",
                "n_quarters": len(s)}
    target_q = NEXT_Q[int(s.quarters[-1])]
    out: dict = {}
    for name, fn in MODELS.items():
        pred = fn(s.values, s.quarters, target_q)
        bt = backtest(s, fn, min_train=min_train)
        out[name] = {"forecast": pred, **bt}
    # ensemble: weight models with a backtest by 1/MAPE (more accurate -> more weight)
    weighted, wsum = 0.0, 0.0
    for m in out.values():
        if m["forecast"] is not None and m.get("mape"):
            w = 1.0 / m["mape"]
            weighted += w * m["forecast"]
            wsum += w
    ensemble = (weighted / wsum) if wsum else None
    return {
        "ticker": s.ticker,
        "metric": metric,
        "n_quarters": len(s),
        "history_tail": list(zip(s.labels[-6:], [round(v, 4) for v in s.values[-6:]])),
        "target_quarter_num": target_q,
        "models": out,
        "ensemble_forecast": ensemble,
    }


# ---- external consensus / actual (yfinance) ---------------------------------

def consensus(ticker: str) -> dict:
    """Upcoming earnings date + analyst EPS consensus and recent surprises, from Yahoo Finance.

    Degrades gracefully (returns {'error': ...}) if yfinance or the network is unavailable, so
    the SEC-only forecast still stands on its own."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker.upper())
        ed = t.get_earnings_dates(limit=12)
        upcoming = None
        recent = []
        if ed is not None and len(ed):
            for dt, row in ed.iterrows():
                est = row.get("EPS Estimate")
                rep = row.get("Reported EPS")
                sup = row.get("Surprise(%)")
                rec = {"date": str(dt.date()), "eps_estimate": _nan(est),
                       "reported_eps": _nan(rep), "surprise_pct": _nan(sup)}
                if rep is None or (isinstance(rep, float) and np.isnan(rep)):
                    if upcoming is None:
                        upcoming = rec           # nearest not-yet-reported
                else:
                    recent.append(rec)
        return {"ticker": ticker.upper(), "upcoming": upcoming, "recent": recent[:6]}
    except Exception as e:  # noqa: BLE001
        return {"ticker": ticker.upper(), "error": repr(e)[:200]}


def _nan(v):
    if v is None:
        return None
    try:
        f = float(v)
        return None if np.isnan(f) else f
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    import json
    import sys
    from config import DATABASE_URL

    tk = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    met = sys.argv[2] if len(sys.argv) > 2 else "revenue_usd"
    res = forecast_next(DATABASE_URL, tk, met)
    res["consensus"] = consensus(tk)
    print(json.dumps(res, indent=2, default=str))
