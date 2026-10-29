"""Bronze landing: raw edgartools facts -> bronze.raw_filings / bronze.raw_facts.

The first layer of the medallion warehouse. Bronze is the *as-ingested truth*: XBRL facts
exactly as edgartools yields them (raw concept, native value, native currency, exact period
dates, dimensions as JSON), for both annual (10-K / 20-F / 40-F) and quarterly (10-Q) filings.
No conformance, no USD normalization, no canonical labels -- that is silver's job (dbt).

Idempotent per accession: an accession is an immutable SEC artifact, so re-landing it replaces
its facts in place rather than duplicating them.

Run:
    .venv/bin/python -m src.ingestion.bronze --tickers AAPL --quarters 8
    .venv/bin/python -m src.ingestion.bronze                      # all reference filers
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import DATABASE_URL  # noqa: E402
from src.extraction.edgartools_adapter import EdgarToolsExtractor, ExtractionResult  # noqa: E402

# The reference filers (match the loaded set). NVO is a foreign filer (20-F, no 10-Q).
REFERENCE_TICKERS = ["AAPL", "AVGO", "AMZN", "GOOGL", "MSFT", "NVDA", "JPM", "NVO"]

DDL = """
CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.raw_filings (
    accession                TEXT PRIMARY KEY,
    ticker                   TEXT NOT NULL,
    cik                      TEXT,
    company_name             TEXT,
    form                     TEXT NOT NULL,
    filing_date              DATE,
    period_of_report         DATE,
    source_currency          TEXT,
    is_financial_institution BOOLEAN,
    source                   TEXT NOT NULL DEFAULT 'edgartools',
    loaded_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bronze.raw_facts (
    fact_id        BIGSERIAL PRIMARY KEY,
    accession      TEXT NOT NULL REFERENCES bronze.raw_filings(accession) ON DELETE CASCADE,
    ticker         TEXT NOT NULL,
    concept        TEXT,
    label          TEXT,
    standard_label TEXT,
    value_numeric  DOUBLE PRECISION,
    value_text     TEXT,
    unit           TEXT,
    period_type    TEXT,
    period_start   DATE,
    period_end     DATE,
    instant_date   DATE,
    fiscal_year    INTEGER,
    fiscal_period  TEXT,
    statement_type TEXT,
    dimensions     JSONB,
    dimension_hash TEXT,
    is_dimensioned BOOLEAN,
    loaded_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_raw_facts_accession     ON bronze.raw_facts(accession);
CREATE INDEX IF NOT EXISTS ix_raw_facts_ticker_concept ON bronze.raw_facts(ticker, concept);
CREATE INDEX IF NOT EXISTS ix_raw_facts_std            ON bronze.raw_facts(standard_label);
"""


def direct_dsn(dsn: str = DATABASE_URL) -> str:
    """DDL + bulk writes should hit the Neon DIRECT endpoint, not the transaction pooler."""
    return dsn.replace("-pooler", "")


def _dim_hash(dims: dict | None) -> str | None:
    if not dims:
        return None
    return hashlib.sha1(json.dumps(dims, sort_keys=True, default=str).encode()).hexdigest()


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()


def land(conn, r: ExtractionResult) -> int:
    """Upsert one filing + replace its raw facts. Returns the number of facts landed."""
    acc = r.filing.accession
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bronze.raw_filings
              (accession, ticker, cik, company_name, form, filing_date, period_of_report,
               source_currency, is_financial_institution, source)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (accession) DO UPDATE SET loaded_at = now()
            """,
            (acc, r.company.ticker, r.company.cik, r.company.name, r.filing.form,
             r.filing.filing_date, r.filing.period_end, r.company.currency,
             r.company.is_financial_institution, r.source),
        )
        # idempotent: an accession is immutable -> replace its facts in place
        cur.execute("DELETE FROM bronze.raw_facts WHERE accession = %s", (acc,))
        rows = [(
            acc, r.company.ticker, f.concept, f.label, f.standard_label,
            f.value_numeric, f.value_text, f.unit, f.period_type,
            f.period_start, f.period_end, f.instant_date, f.fiscal_year, f.fiscal_period,
            f.statement_type, json.dumps(f.dimensions) if f.dimensions else None,
            _dim_hash(f.dimensions), f.is_dimensioned,
        ) for f in r.facts]
        if rows:
            execute_values(
                cur,
                """
                INSERT INTO bronze.raw_facts
                  (accession, ticker, concept, label, standard_label, value_numeric, value_text,
                   unit, period_type, period_start, period_end, instant_date, fiscal_year,
                   fiscal_period, statement_type, dimensions, dimension_hash, is_dimensioned)
                VALUES %s
                """,
                rows,
            )
    conn.commit()
    return len(rows)


def _existing_accessions(conn, ticker: str) -> set:
    with conn.cursor() as cur:
        cur.execute("SELECT accession FROM bronze.raw_filings WHERE ticker = %s", (ticker,))
        return {r[0] for r in cur.fetchall()}


def ingest(tickers, annual: bool = True, quarters: int = 8, only_new: bool = False,
           dsn: str | None = None) -> None:
    dsn = dsn or direct_dsn()
    ex = EdgarToolsExtractor()
    conn = psycopg2.connect(dsn)
    try:
        ensure_schema(conn)
        total_filings = total_facts = 0
        for tk in tickers:
            # Incremental: skip accessions already landed (so weekly runs only fetch new filings).
            skip = _existing_accessions(conn, tk) if only_new else frozenset()
            results: list[ExtractionResult] = []
            if annual:
                results.extend(ex.extract_filings(
                    tk, forms=EdgarToolsExtractor._ANNUAL_FORMS, limit=1, skip_accessions=skip))
            if quarters:
                results.extend(ex.extract_filings(
                    tk, forms=("10-Q",), limit=quarters, skip_accessions=skip))
            if not results:
                print(f"  {tk}: nothing new to land" if only_new else f"  {tk}: no filings found")
            for r in results:
                n = land(conn, r)
                total_filings += 1
                total_facts += n
                print(f"  landed {tk} {r.filing.form} {r.filing.accession} "
                      f"period_end={r.filing.period_end} facts={n}")
        print(f"DONE: {total_filings} filings, {total_facts} facts into bronze")
    finally:
        conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Land raw XBRL facts into the bronze layer.")
    ap.add_argument("--tickers", default=",".join(REFERENCE_TICKERS),
                    help="comma-separated tickers (default: the reference filers)")
    ap.add_argument("--quarters", type=int, default=8,
                    help="number of recent 10-Q filings to land per filer (0 to skip)")
    ap.add_argument("--no-annual", action="store_true", help="skip the latest annual filing")
    ap.add_argument("--only-new", action="store_true",
                    help="incremental: skip filings already landed in bronze")
    args = ap.parse_args()
    ingest(
        [t.strip().upper() for t in args.tickers.split(",") if t.strip()],
        annual=not args.no_annual,
        quarters=args.quarters,
        only_new=args.only_new,
    )
