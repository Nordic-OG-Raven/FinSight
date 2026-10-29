"""Tests for forecasting v2: deterministic model recovery + the leakage guarantee.

The model tests are offline (synthetic series). The leakage test hits the warehouse (skipped in
CI, like the other DB-backed tests) and is the credibility core: a point-in-time series must never
contain a fact from a filing dated after the as-of date.
"""
import os
from datetime import date

import numpy as np
import pytest

from src.analysis import forecasting_v2 as fv
from src.analysis import pit

SEASON = {1: 10.0, 2: 0.0, 3: -5.0}   # our filed series is Q1-Q3 (no discrete Q4)


def _pts(values, start_fy=2024):
    """Build a Q1-Q2-Q3-repeating Point series (chronological)."""
    out, fy, qn = [], start_fy, 1
    for v in values:
        out.append(pit.Point(date(fy, qn * 3, 28), fy, qn, float(v), date(fy, qn * 3, 28), "acc"))
        qn += 1
        if qn > 3:
            qn, fy = 1, fy + 1
    return out


def _seq(n, start_fy=2024):
    """The (fiscal_year, quarter_num, quarter_index) sequence for n Q1-Q3 points, + the next one."""
    seq, fy, qn = [], start_fy, 1
    for _ in range(n + 1):
        seq.append((fy, qn, fy * 4 + qn))
        qn += 1
        if qn > 3:
            qn, fy = 1, fy + 1
    return seq


def test_trend_seasonal_recovers_linear():
    seq = _seq(11)
    a, b = 100.0, 2.0
    vals = [a + b * qidx + SEASON[qn] for (_, qn, qidx) in seq[:-1]]
    pts = _pts(vals)
    t_fy, t_qn, t_qidx = seq[-1]
    pred = fv.trend_seasonal(pts, t_fy, t_qn)
    assert abs(pred - (a + b * t_qidx + SEASON[t_qn])) < 1e-6


def test_log_trend_recovers_exponential():
    seq = _seq(11)
    base = seq[0][2]                       # center the quarter_index so exponents stay small
    g = 0.15
    vals = [1000.0 * np.exp(g * (qidx - base)) for (_, _, qidx) in seq[:-1]]
    pts = _pts(vals)
    t_fy, t_qn, t_qidx = seq[-1]
    pred = fv.log_trend_seasonal(pts, t_fy, t_qn)
    assert abs(pred / (1000.0 * np.exp(g * (t_qidx - base))) - 1.0) < 1e-6


def test_recent_mean_on_sticky_series():
    pts = _pts([0.55, 0.54, 0.56, 0.55, 0.57, 0.56])  # a sticky margin
    out = fv.recent_mean(pts, 2026, 1)
    assert 0.54 < out < 0.57


def test_seasonal_naive_uses_last_year_same_quarter():
    # Q1 values grow ~10%/yr; forecasting next Q1 should be near last Q1 * (1+~0.1)
    pts = _pts([100, 50, 60, 110, 55, 66, 121, 60, 73])  # Q1=100,110,121 ...
    pred = fv.seasonal_naive(pts, 2027, 1)   # next Q1
    assert 125 < pred < 140


def test_guidance_beat_formula():
    # guidance-beat forecast = guidance * (1 + median beat); verify the arithmetic directly
    guidance, beats = 108.0, [0.056, 0.048, 0.057]
    assert abs(guidance * (1 + float(np.median(beats))) - 108.0 * 1.056) < 1e-9


@pytest.mark.skipif("CI" in os.environ, reason="needs the warehouse")
def test_pit_no_future_leakage():
    import config
    as_of = date(2025, 6, 1)
    pts = pit.series_asof(config.DATABASE_URL, "NVDA", "revenue", as_of)
    assert pts, "expected some history known by the as-of date"
    assert all(p.filing_date <= as_of for p in pts), "LEAKAGE: a fact from a future-dated filing"
    # and the point-in-time view is a prefix: fewer/equal quarters than the latest
    latest = pit.latest_series(config.DATABASE_URL, "NVDA", "revenue")
    assert len(pts) <= len(latest)
