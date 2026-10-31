"""Analyst REVENUE consensus by quarter, from MarketBeat's free earnings pages.

Revenue consensus is a licensed/premium field in every structured API's free tier. MarketBeat's
public earnings page is the one free source exposing a per-quarter table of the PRE-RELEASE consensus
revenue estimate alongside the actual, ~2 years back, correctly dated. We use it only to benchmark
our own revenue forecasts (low volume, attributed to MarketBeat on the site).

Leakage-safe: the "Revenue Estimate" column is the consensus going INTO the report (shown next to the
actual that followed), so pairing it to a past quarter uses no post-quarter information. We align by
report date (a quarter reports within ~75 days of its end) — the same alignment used for EPS.
"""
from __future__ import annotations

import io
import re
import time
import urllib.request
from datetime import date, timedelta
from functools import lru_cache

import pandas as pd

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
# MarketBeat URLs are /stocks/<EXCHANGE>/<TICKER>/earnings/. Our set is NASDAQ except where noted.
_EXCHANGE = {"JPM": "NYSE", "ORCL": "NYSE", "CRM": "NYSE"}


def _money(s) -> float | None:
    m = re.search(r"([\d.]+)\s*([BMT])", str(s))
    return float(m.group(1)) * {"B": 1e9, "M": 1e6, "T": 1e12}[m.group(2)] if m else None


@lru_cache(maxsize=64)
def _rows(ticker: str) -> tuple:
    """(report_date, revenue_estimate) per quarter from the earnings-history table, forward row
    included (it carries a date too). () on any fetch/parse failure."""
    ex = _EXCHANGE.get(ticker.upper(), "NASDAQ")
    url = f"https://www.marketbeat.com/stocks/{ex}/{ticker.upper()}/earnings/"
    # MarketBeat intermittently serves a table-stripped page to throttle scrapers. This isn't
    # latency-sensitive (weekly job / one-off backfill), so retry patiently until the real table
    # appears, then give up gracefully (consensus stays None for that ticker this run).
    tbl = None
    for attempt in range(8):
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                html = r.read().decode("utf-8", "ignore")
            tables = pd.read_html(io.StringIO(html))
            tbl = next((t for t in tables
                        if any("Revenue Estimate" == str(c) for c in t.columns)
                        and any("Date" == str(c) for c in t.columns)), None)
        except Exception:  # noqa: BLE001
            tbl = None
        if tbl is not None:
            break
        time.sleep(3 + 1.5 * attempt)
    if tbl is None:
        return ()
    out = []
    for _, row in tbl.iterrows():
        est = _money(row.get("Revenue Estimate"))
        m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(row.get("Date", "")))
        if est is not None and m:
            out.append((date(int(m.group(3)), int(m.group(1)), int(m.group(2))), est))
    return tuple(out)


def revenue_consensus_for_quarter(ticker: str, quarter_end: date) -> float | None:
    """Consensus revenue estimate for the quarter ending `quarter_end` (matched by report date).
    Works for both past quarters and the upcoming one (its forward row carries an estimated date)."""
    for rd, est in _rows(ticker):
        if quarter_end < rd <= quarter_end + timedelta(days=75):
            return est
    return None
