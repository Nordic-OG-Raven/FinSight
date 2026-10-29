"""
Financial ratios + peer comparison derived from the warehouse (PRD §10 / Phase 3).

Ratios are computed from the canonical normalized labels (so they work across us-gaap and
ifrs filers) using USD-normalized values (`value_usd`), which means cross-company comparison
is currency-agnostic. Ratios are themselves unit-free, so margins/ROE are identical whether
computed in native currency or USD; the absolute figures (revenue, net income) are reported in
USD so peers line up.

Valuation ratios that need market data (P/E, P/B, dividend yield) are intentionally NOT here —
SEC filings don't carry share price / market cap, so those belong to a future market-data
integration, not this module.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import create_engine, text

# canonical labels this module consumes (must match src/extraction/canonical_labels.py)
METRIC_LABELS = [
    "revenue", "cost_of_revenue", "gross_profit", "operating_income",
    "income_before_income_taxes", "income_tax_expense", "net_income",
    "eps_diluted", "total_assets", "current_assets", "cash_and_cash_equivalents",
    "total_liabilities", "current_liabilities", "total_equity",
    "net_cash_from_operating_activities", "capital_expenditures",
]


def _safe_div(num: Optional[float], den: Optional[float]) -> Optional[float]:
    if num is None or den in (None, 0):
        return None
    return num / den


def compute_ratios(m: dict) -> dict:
    """Single-period ratios from a {canonical_label: value} dict. Missing inputs -> None.
    Values should be in one consistent currency (we pass USD)."""
    rev = m.get("revenue")
    ocf = m.get("net_cash_from_operating_activities")
    capex = m.get("capital_expenditures")
    # capex is reported as a positive outflow in us-gaap (PaymentsToAcquire…); subtract it
    fcf = (ocf - abs(capex)) if (ocf is not None and capex is not None) else None
    return {
        "gross_margin": _safe_div(m.get("gross_profit"), rev),
        "operating_margin": _safe_div(m.get("operating_income"), rev),
        "net_margin": _safe_div(m.get("net_income"), rev),
        "return_on_equity": _safe_div(m.get("net_income"), m.get("total_equity")),
        "return_on_assets": _safe_div(m.get("net_income"), m.get("total_assets")),
        "current_ratio": _safe_div(m.get("current_assets"), m.get("current_liabilities")),
        "debt_to_equity": _safe_div(m.get("total_liabilities"), m.get("total_equity")),
        "asset_turnover": _safe_div(rev, m.get("total_assets")),
        "effective_tax_rate": _safe_div(m.get("income_tax_expense"), m.get("income_before_income_taxes")),
        "free_cash_flow": fcf,
        "fcf_margin": _safe_div(fcf, rev),
    }


def load_metrics(database_url: str, ticker: Optional[str] = None) -> dict:
    """{ticker: {fiscal_year: {canonical_label: value_usd}}} for the core metrics.

    Uses value_usd so figures are comparable across currencies; falls back to value_numeric if
    value_usd is null. Undimensioned facts only; annual durations and instants."""
    engine = create_engine(database_url)
    # Gold serving mart (medallion): one USD value per (ticker, fiscal_year, canonical line).
    sql = """
        SELECT ticker, fiscal_year, canonical_label AS normalized_label,
               COALESCE(value_usd, value_native) AS val
        FROM gold.company_financials
        WHERE canonical_label = ANY(:labels)
    """ + (" AND ticker = :ticker" if ticker else "")
    params = {"labels": METRIC_LABELS}
    if ticker:
        params["ticker"] = ticker.upper()
    out: dict = {}
    with engine.connect() as conn:
        for tk, fy, label, val in conn.execute(text(sql), params):
            if fy is None:
                continue
            # keep the largest-magnitude value if a (ticker, year, label) ever collides
            cur = out.setdefault(tk, {}).setdefault(fy, {})
            if label not in cur or abs(float(val)) > abs(cur[label]):
                cur[label] = float(val)
    return out


def company_ratios(database_url: str, ticker: str, years: int = 3) -> dict:
    """Multi-year metrics + ratios for one company, USD."""
    by_year = load_metrics(database_url, ticker).get(ticker.upper(), {})
    yrs = sorted(by_year, reverse=True)[:years]
    metrics = {label: {y: by_year[y][label] for y in yrs if label in by_year[y]} for label in METRIC_LABELS}
    ratios: dict = {}
    for y in yrs:
        r = compute_ratios(by_year[y])
        prior = by_year.get(y - 1)
        r["revenue_growth"] = _safe_div(by_year[y].get("revenue"), prior.get("revenue") if prior else None)
        if r["revenue_growth"] is not None:
            r["revenue_growth"] -= 1.0
        for name, val in r.items():
            ratios.setdefault(name, {})[y] = val
    return {"ticker": ticker.upper(), "currency": "USD", "years": yrs,
            "metrics": {k: v for k, v in metrics.items() if v}, "ratios": ratios}


def peer_comparison(database_url: str) -> list:
    """Latest-year snapshot per company: headline USD figures + key ratios, revenue-sorted."""
    allm = load_metrics(database_url)
    rows = []
    for tk, by_year in allm.items():
        if not by_year:
            continue
        y = max(by_year)
        m = by_year[y]
        r = compute_ratios(m)
        prior = by_year.get(y - 1)
        growth = _safe_div(m.get("revenue"), prior.get("revenue") if prior else None)
        rows.append({
            "ticker": tk, "fiscal_year": y,
            "revenue_usd": m.get("revenue"), "net_income_usd": m.get("net_income"),
            "total_assets_usd": m.get("total_assets"), "total_equity_usd": m.get("total_equity"),
            "revenue_growth": (growth - 1.0) if growth is not None else None,
            "gross_margin": r["gross_margin"], "operating_margin": r["operating_margin"],
            "net_margin": r["net_margin"], "return_on_equity": r["return_on_equity"],
            "return_on_assets": r["return_on_assets"], "debt_to_equity": r["debt_to_equity"],
            "current_ratio": r["current_ratio"], "free_cash_flow_usd": r["free_cash_flow"],
        })
    rows.sort(key=lambda x: (x["revenue_usd"] is None, -(x["revenue_usd"] or 0)))
    return rows


if __name__ == "__main__":
    import json
    import sys
    from config import DATABASE_URL
    if len(sys.argv) > 1:
        print(json.dumps(company_ratios(DATABASE_URL, sys.argv[1]), indent=2, default=str))
    else:
        print(json.dumps(peer_comparison(DATABASE_URL), indent=2, default=str))
