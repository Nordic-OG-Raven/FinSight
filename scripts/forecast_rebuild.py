"""One-process full rebuild of the forecasting artifacts, sharing in-memory caches across stages.

Runs, in a single warm process: the coverage scorecard -> clear + backfill the ledger -> log the
current live forecasts -> render the track record. Because it is one process, the point-in-time
read caches (`pit`), the guidance cache, and the yfinance earnings cache persist across all stages,
instead of being thrown away between four separate script invocations (which re-fetched the same
EDGAR filings and yfinance tables many times over).

Pure orchestration: the outputs are identical to running the stages separately — only the redundant
cross-stage refetching is removed. Verify with a diff against a snapshot if changing the pipeline.

    .venv/bin/python scripts/forecast_rebuild.py [YYYY-MM-DD]
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from config import DATABASE_URL  # noqa: E402
from src.analysis import forecast_log  # noqa: E402

import forecast_coverage  # noqa: E402
import forecast_track_record  # noqa: E402

TICKERS = ["NVDA", "AMZN", "AVGO", "MSFT", "GOOGL", "AAPL", "JPM",
           "META", "TSLA", "NFLX", "AMD", "ORCL", "CRM"]


def _clear_backtest_rows() -> int:
    conn = forecast_log._conn()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM forecasts.forecast_log WHERE model LIKE 'backtest:%'")
        n = cur.rowcount
    conn.commit()
    conn.close()
    return n


def main(today: str | None = None, tickers: list | None = None) -> None:
    today = today or date.today().isoformat()
    tickers = tickers or TICKERS

    # backfill FIRST — it populates the ledger (the single source of truth); the scorecard then
    # reads realized accuracy from it, so the scorecard and track record always agree.
    print("== clear + backfill ledger ==", flush=True)
    print(f"  cleared {_clear_backtest_rows()} backtest rows", flush=True)
    forecast_log.backfill()

    print("== log live forecasts ==", flush=True)
    forecast_log.log_forecasts()

    print("== coverage scorecard (reads the ledger) ==", flush=True)
    rows = {tk: forecast_coverage.score(DATABASE_URL, tk) for tk in tickers}
    (ROOT / "docs" / "forecasting" / "COVERAGE.md").write_text(forecast_coverage.render(rows))

    print("== render track record ==", flush=True)
    forecast_track_record.build(today)


if __name__ == "__main__":
    main(today=sys.argv[1] if len(sys.argv) > 1 else None)
