"""Point-in-time (leakage-safe) quarterly series, read from BRONZE.

For backtesting we must reconstruct each series *as it was known* at a given `as_of` date —
otherwise the backtest leaks future information ("no bleed"). Silver/gold dedup every fact to its
latest filing vintage (great for "what's true now", useless for point-in-time), so we go back to
`bronze.raw_facts`, which keeps every vintage, join `bronze.raw_filings.filing_date`, and for each
fiscal quarter take the value from the **latest filing dated on/before `as_of`**.

Scope: discrete reported quarters (~80-100 day durations = Q1-Q3 as filed in 10-Qs; Q4 is only an
annual-minus-YTD derivation and is deferred). Metrics are canonical consolidated lines (reusing
`canonical_labels.CANONICAL`) or a segment revenue (`segment:<name>`, via the segment_members seed).
NVDA/MSFT file in USD, so value_numeric == value_usd.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from math import ceil
from pathlib import Path

from sqlalchemy import create_engine, text

from src.extraction.canonical_labels import CANONICAL

# One engine (connection pool) per database URL, reused across the thousands of point-in-time reads
# a backtest makes. Without this, every query called create_engine() afresh and opened a brand-new
# connection to the remote warehouse (full TCP+TLS+auth, ~100ms each) — the dominant cost of batch
# backtests. Pooling reuses the connection; it does not change any query or result.
_ENGINES: dict = {}


def _engine(database_url: str):
    eng = _ENGINES.get(database_url)
    if eng is None:
        eng = _ENGINES[database_url] = create_engine(database_url, pool_size=4, max_overflow=4,
                                                      pool_recycle=300)
    return eng


def clear_caches() -> None:
    """Drop the point-in-time read caches. Call after an ingest in a long-lived process so fresh
    filings are picked up (one-shot scripts and the per-run Modal job don't need this)."""
    series_asof.cache_clear()
    quarter_report_dates.cache_clear()

_SEED = Path(__file__).resolve().parent.parent.parent / "dbt" / "seeds" / "segment_members.csv"


def _segment_members() -> dict[tuple[str, str], list[str]]:
    """{(ticker, segment): [member, ...]} from the segment_members seed (the forecasting vocab)."""
    out: dict[tuple[str, str], list[str]] = defaultdict(list)
    with _SEED.open() as fh:
        for r in csv.DictReader(fh):
            out[(r["ticker"], r["segment"])].append(r["member"])
    return dict(out)


SEGMENT_MEMBERS = _segment_members()


@dataclass
class Point:
    period_end: date
    fiscal_year: int
    quarter_num: int          # 1-4 (fiscal quarter)
    value: float
    filing_date: date
    accession: str


def _fye_month(conn, ticker: str, as_of: date) -> int:
    """Modal month of the company's ~annual period-ends among filings known by `as_of`."""
    row = conn.execute(text("""
        SELECT mode() WITHIN GROUP (ORDER BY extract(month from f.period_end)::int) AS m
        FROM bronze.raw_facts f
        JOIN bronze.raw_filings rf USING (accession)
        WHERE f.ticker = :t AND rf.filing_date <= :asof
          AND f.period_type = 'duration'
          AND (f.period_end - f.period_start) BETWEEN 330 AND 380
    """), {"t": ticker, "asof": as_of}).fetchone()
    return int(row[0]) if row and row[0] is not None else 12


def _fy_and_quarter(period_end: date, fye_month: int) -> tuple[int, int]:
    """Fiscal year (named by the year it ends in) + fiscal quarter number (1-4)."""
    m = period_end.month
    fiscal_year = period_end.year + (1 if m > fye_month else 0)
    months_into_fy = ((m - (fye_month + 1)) % 12) + 1   # 1..12 since fiscal-year start
    quarter_num = ceil(months_into_fy / 3)
    return fiscal_year, quarter_num


@lru_cache(maxsize=8192)
def series_asof(database_url: str, ticker: str, metric: str, as_of: date) -> list[Point]:
    """Quarterly series for `metric` as it was known at `as_of`, newest-vintage-wins per quarter.

    metric: a canonical label (e.g. 'revenue', 'gross_profit') or 'segment:<name>'
            (e.g. 'segment:compute_and_networking').

    Cached: a backtest reconstructs the same (ticker, metric, as_of) series across several models and
    across the routing/forecast/scoring passes; the warehouse is static within a run, so caching
    returns the identical result without re-querying. Callers must treat the returned list as
    read-only (they do). Call `clear_caches()` after an ingest in a long-lived process.
    """
    eng = _engine(database_url)
    ticker = ticker.upper()

    if metric.startswith("segment:"):
        seg = metric.split(":", 1)[1]
        members = SEGMENT_MEMBERS.get((ticker, seg))
        if not members:
            return []
        sql = text("""
            SELECT DISTINCT ON (f.period_end)
                   f.period_end, f.value_numeric, rf.filing_date, f.accession
            FROM bronze.raw_facts f
            JOIN bronze.raw_filings rf USING (accession)
            WHERE f.ticker = :t AND rf.filing_date <= :asof
              AND f.is_dimensioned
              AND f.dimensions ->> 'us-gaap_StatementBusinessSegmentsAxis' = ANY(:members)
              AND split_part(f.concept, ':', 2) LIKE 'Revenue%'
              AND f.period_type = 'duration'
              AND (f.period_end - f.period_start) BETWEEN 80 AND 100
              AND f.value_numeric IS NOT NULL
              AND (SELECT count(*) FROM jsonb_object_keys(f.dimensions)) <= 2
            ORDER BY f.period_end, rf.filing_date DESC
        """)
        params = {"t": ticker, "asof": as_of, "members": members}
    else:
        concepts = CANONICAL.get(metric)
        if not concepts:
            raise ValueError(f"unknown canonical metric: {metric}")
        sql = text("""
            SELECT DISTINCT ON (f.period_end)
                   f.period_end, f.value_numeric, rf.filing_date, f.accession
            FROM bronze.raw_facts f
            JOIN bronze.raw_filings rf USING (accession)
            WHERE f.ticker = :t AND rf.filing_date <= :asof
              AND f.is_dimensioned = false
              AND f.concept = ANY(:concepts)
              AND f.period_type = 'duration'
              AND (f.period_end - f.period_start) BETWEEN 80 AND 100
              AND f.value_numeric IS NOT NULL
            -- newest vintage known by as_of; then canonical priority (earlier in list = preferred)
            ORDER BY f.period_end, rf.filing_date DESC, array_position(:concepts, f.concept)
        """)
        params = {"t": ticker, "asof": as_of, "concepts": concepts}

    with eng.connect() as conn:
        fye = _fye_month(conn, ticker, as_of)
        rows = conn.execute(sql, params).fetchall()

    out: list[Point] = []
    for period_end, value, filing_date, accession in rows:
        fy, qn = _fy_and_quarter(period_end, fye)
        out.append(Point(period_end, fy, qn, float(value), filing_date, accession))
    out.sort(key=lambda p: p.period_end)
    return out


# convenience: latest-known series (as of today-ish) == series_asof with a far-future as_of
def latest_series(database_url: str, ticker: str, metric: str) -> list[Point]:
    return series_asof(database_url, ticker, metric, date(2100, 1, 1))


@lru_cache(maxsize=256)
def quarter_report_dates(database_url: str, ticker: str) -> dict[date, date]:
    """{quarter_end: original 10-Q filing date} — when each quarter was first reported. Used to set
    the backtest cutoff (forecast a quarter using only what was filed before its own 10-Q).
    Cached (read-only result; static within a run)."""
    eng = _engine(database_url)
    with eng.connect() as conn:
        rows = conn.execute(text("""
            SELECT period_of_report, min(filing_date) AS first_filed
            FROM bronze.raw_filings
            WHERE ticker = :t AND form = '10-Q' AND period_of_report IS NOT NULL
            GROUP BY period_of_report
        """), {"t": ticker.upper()}).fetchall()
    return {r[0]: r[1] for r in rows}
