"""Land stock splits into bronze.corporate_actions (from Yahoo Finance).

Corporate actions aren't in the SEC XBRL facts, but they're needed to put a per-share series
(EPS) on a consistent basis: a filer's EPS reported before a split is on pre-split shares and
isn't comparable to post-split quarters. We land the raw split history here (bronze) and let gold
compute a split-adjusted EPS from it — so the warehouse stays the single source of truth and the
adjustment is just another SQL transform.

    .venv/bin/python -m src.ingestion.corporate_actions
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from src.ingestion.bronze import REFERENCE_TICKERS, direct_dsn  # noqa: E402

DDL = """
CREATE TABLE IF NOT EXISTS bronze.corporate_actions (
    ticker       TEXT NOT NULL,
    action_type  TEXT NOT NULL DEFAULT 'split',
    action_date  DATE NOT NULL,
    split_ratio  DOUBLE PRECISION NOT NULL,
    source       TEXT NOT NULL DEFAULT 'yfinance',
    loaded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, action_type, action_date)
);
"""


def fetch_splits(ticker: str) -> list[tuple]:
    import yfinance as yf
    s = yf.Ticker(ticker).splits
    rows = []
    for d, ratio in s.items():
        r = float(ratio)
        if r and r != 1.0:
            rows.append((ticker, "split", d.date(), r))
    return rows


def ingest(tickers=REFERENCE_TICKERS, dsn: str | None = None) -> None:
    dsn = dsn or direct_dsn()
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS bronze;")
            cur.execute(DDL)
        conn.commit()
        total = 0
        for tk in tickers:
            try:
                rows = fetch_splits(tk)
            except Exception as e:  # noqa: BLE001
                print(f"  {tk}: splits fetch failed ({e})")
                continue
            if not rows:
                continue
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    """INSERT INTO bronze.corporate_actions (ticker, action_type, action_date, split_ratio)
                       VALUES %s
                       ON CONFLICT (ticker, action_type, action_date)
                       DO UPDATE SET split_ratio = EXCLUDED.split_ratio, loaded_at = now()""",
                    rows,
                )
            conn.commit()
            total += len(rows)
            print(f"  {tk}: {len(rows)} split(s) -> {rows}")
        print(f"DONE: {total} corporate actions into bronze.corporate_actions")
    finally:
        conn.close()


if __name__ == "__main__":
    ingest()
