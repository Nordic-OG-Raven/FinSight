"""Offline tests for auto-regime routing — the YoY growth computation that splits growth vs seasonal.
(The full `classify` is DB- + network-backed and exercised by scripts/forecast_coverage.py, not CI.)
"""
from datetime import date

from src.analysis import regime
from src.analysis.pit import Point


def _pts(vals_by_fy_q):
    return [Point(date(fy, qn * 3, 28), fy, qn, v, date(fy, qn * 3, 28), "acc")
            for (fy, qn), v in vals_by_fy_q.items()]


def test_median_yoy_hypergrowth():
    # Q1 doubles each year -> YoY ~100%
    pts = _pts({(2024, 1): 100.0, (2025, 1): 200.0, (2026, 1): 400.0})
    assert abs(regime._median_yoy(pts) - 1.0) < 1e-9


def test_median_yoy_flat():
    pts = _pts({(2024, 2): 50.0, (2025, 2): 50.0, (2026, 2): 50.0})
    assert abs(regime._median_yoy(pts)) < 1e-9


def test_median_yoy_none_without_prior_year():
    pts = _pts({(2024, 1): 100.0, (2024, 2): 110.0})   # no same-quarter prior year
    assert regime._median_yoy(pts) is None
