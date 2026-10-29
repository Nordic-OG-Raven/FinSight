"""Deterministic tests for the forecasting models (no DB / network).

The models are exercised on synthetic series with a known trend + seasonality so we can assert
they recover the structure, plus the backtest/ensemble plumbing.
"""
import numpy as np

from src.analysis.forecasting import (
    NEXT_Q,
    Series,
    backtest,
    gbm_lags,
    ols_trend_seasonal,
    seasonal_naive,
)

SEASON = {1: 10.0, 2: 0.0, 3: -5.0, 4: 5.0}


def _synthetic(n=16):
    q = np.array([(i % 4) + 1 for i in range(n)])
    y = np.array([100.0 + 2.0 * i + SEASON[int(q[i])] for i in range(n)])
    return y, q


def test_next_quarter_cycle():
    assert [NEXT_Q[i] for i in (1, 2, 3, 4)] == [2, 3, 4, 1]


def test_ols_recovers_trend_and_seasonality():
    y, q = _synthetic(16)              # last index 15 -> q4, next is q1
    pred = ols_trend_seasonal(y, q, target_q=1)
    expected = 100.0 + 2.0 * 16 + SEASON[1]   # 142
    assert pred is not None
    assert abs(pred - expected) < 1e-6


def test_seasonal_naive_is_in_sane_band():
    y, q = _synthetic(16)
    pred = seasonal_naive(y, q, target_q=1)
    # same-quarter-last-year (index 12, q1) grown by the steady YoY rate -> near the true next
    assert pred is not None
    assert 135.0 < pred < 150.0


def test_gbm_returns_float_when_enough_history():
    y, q = _synthetic(16)
    pred = gbm_lags(y, q, target_q=1)
    assert pred is not None and pred > 0


def test_gbm_declines_on_short_series():
    y, q = _synthetic(6)
    assert gbm_lags(y, q, target_q=(q[-1] % 4) + 1) is None


def test_backtest_zero_error_for_perfect_model():
    y, q = _synthetic(16)
    s = Series("TEST", "revenue_usd", y, q)
    # an oracle model that returns the true next value -> zero error
    def oracle(yy, qq, tq):
        t = len(yy)
        return 100.0 + 2.0 * t + SEASON[tq]
    bt = backtest(s, oracle, min_train=8)
    assert bt["n"] > 0
    assert bt["mape"] is not None and bt["mape"] < 1e-6


def test_backtest_reports_error_for_biased_model():
    y, q = _synthetic(16)
    s = Series("TEST", "revenue_usd", y, q)
    bt = backtest(s, lambda yy, qq, tq: yy[-1], min_train=8)  # naive last-value: biased
    assert bt["n"] > 0 and bt["mape"] > 0
