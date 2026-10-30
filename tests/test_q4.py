"""Offline tests for the Q4 forecast models (the pure math; DB-backed series/backtest run live)."""
from datetime import date

from src.analysis import q4
from src.analysis.q4 import Q4Point


def _hist(vals):
    # vals: list of (fy, q4, ytd3); known_date ordered by fy
    return [Q4Point(fy, q4v, ytd, date(fy + 1, 2, 1)) for fy, q4v, ytd in vals]


def test_ytd_ratio_uses_stable_ratio():
    # Q4/YTD3 ratio is a stable 0.42; forecast = target YTD3 * 0.42
    hist = _hist([(2022, 170.0, 404.8), (2023, 187.8, 450.2), (2024, 213.4, 503.5)])
    out = q4._forecast_from(hist, 550.0, "ytd_ratio")
    ratios = [170.0 / 404.8, 187.8 / 450.2, 213.4 / 503.5]
    import numpy as np
    assert abs(out - 550.0 * float(np.median(ratios))) < 1e-6


def test_ytd_ratio_needs_two_priors():
    assert q4._forecast_from(_hist([(2023, 100.0, 250.0)]), 300.0, "ytd_ratio") is None


def test_seasonal_naive_grows_last_q4():
    hist = _hist([(2022, 100.0, 250.0), (2023, 110.0, 270.0), (2024, 121.0, 290.0)])  # +10%/yr
    out = q4._forecast_from(hist, 310.0, "seasonal_naive")
    assert 130.0 < out < 135.0   # 121 * ~1.10
