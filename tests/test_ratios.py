"""Tests for src/analysis/ratios.py — pure ratio math (offline) + warehouse-backed checks."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analysis.ratios import compute_ratios, company_ratios, peer_comparison  # noqa: E402


def _db():
    return os.getenv("DATABASE_URL", "postgresql://superset:superset@localhost:5432/finsight")


M = {
    "revenue": 1000, "gross_profit": 600, "operating_income": 300, "net_income": 200,
    "total_equity": 1000, "total_assets": 4000, "current_assets": 500,
    "current_liabilities": 250, "total_liabilities": 2000,
    "income_before_income_taxes": 250, "income_tax_expense": 50,
    "net_cash_from_operating_activities": 400, "capital_expenditures": 100,
}


def test_margins_and_returns():
    r = compute_ratios(M)
    assert r["gross_margin"] == 0.6
    assert r["operating_margin"] == 0.3
    assert r["net_margin"] == 0.2
    assert r["return_on_equity"] == 0.2
    assert r["return_on_assets"] == 0.05


def test_leverage_liquidity_efficiency_tax():
    r = compute_ratios(M)
    assert r["debt_to_equity"] == 2.0
    assert r["current_ratio"] == 2.0
    assert r["asset_turnover"] == 0.25
    assert r["effective_tax_rate"] == 0.2


def test_free_cash_flow_subtracts_capex_magnitude():
    assert compute_ratios(M)["free_cash_flow"] == 300        # 400 - |100|
    assert compute_ratios(M)["fcf_margin"] == 0.3
    # capex reported as a negative outflow must still subtract its magnitude
    m2 = dict(M, capital_expenditures=-100)
    assert compute_ratios(m2)["free_cash_flow"] == 300


def test_missing_or_zero_inputs_yield_none():
    assert compute_ratios({"net_income": 5})["net_margin"] is None          # no revenue
    assert compute_ratios({"net_income": 5, "total_equity": 0})["return_on_equity"] is None  # /0


@pytest.mark.skipif("CI" in os.environ, reason="needs local warehouse")
def test_peer_comparison_is_usd_normalized():
    rows = {r["ticker"]: r for r in peer_comparison(_db())}
    assert len(rows) >= 8
    # NVO files in DKK (~309B revenue); in the peer table it must be USD (~$45-52B)
    assert 45e9 < rows["NVO"]["revenue_usd"] < 52e9
    # revenue-sorted descending
    revs = [r["revenue_usd"] for r in peer_comparison(_db()) if r["revenue_usd"]]
    assert revs == sorted(revs, reverse=True)


@pytest.mark.skipif("CI" in os.environ, reason="needs local warehouse")
def test_company_ratios_nvda_margins_sane():
    d = company_ratios(_db(), "NVDA")
    latest = max(d["years"])
    assert 0.4 < d["ratios"]["net_margin"][latest] < 0.7     # NVDA ~55%
