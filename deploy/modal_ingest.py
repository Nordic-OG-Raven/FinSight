"""Scheduled medallion ingestion + transform on Modal (weekly cron).

Runs the full pipeline against the hosted Neon warehouse:
    1. bronze — land NEW SEC filings (10-K + 10-Q), incremental (only-new), + stock splits
    2. dbt build — rebuild silver/gold + run all data tests

Bronze landing is idempotent and incremental, so a run that finds no new filing is a no-op for
bronze and just refreshes the gold marts.

One-time setup
--------------
    pip install modal
    modal token new                                   # authenticate (opens browser)
    modal secret create finsight DATABASE_URL="postgresql://USER:PASS@HOST/neondb?sslmode=require&channel_binding=require"
    modal deploy deploy/modal_ingest.py               # deploy + schedule

Config
------
    DATABASE_URL        (required, via the `finsight` secret) — the hosted Postgres (pooled URL
                        is fine; the job parses the DIRECT endpoint for writes + dbt DDL).
    FINSIGHT_TICKERS    (optional) — space-separated tickers; defaults to the reference set.

Run once on demand:
    modal run deploy/modal_ingest.py
"""
import modal

DEFAULT_TICKERS = "AAPL AVGO JPM NVO GOOGL MSFT AMZN NVDA"

# Image: ingestion deps (edgartools/yfinance) + dbt for the silver/gold transforms.
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "edgartools>=5.62.0", "yfinance>=0.2.40", "sqlalchemy>=2.0.0,<2.1",
        "psycopg2-binary>=2.9.0", "python-dotenv>=1.0.0", "dbt-postgres>=1.8,<1.10",
    )
    # ship the repo code (ingestion, adapter, config, dbt project) into the image
    .add_local_dir(
        ".", remote_path="/app",
        ignore=["*.pyc", "__pycache__", ".git", ".venv", "data", "docs", "tests",
                "Website", "node_modules", "*.md", "dbt/target", "dbt/dbt_packages", "dbt/logs"],
    )
)

app = modal.App("finsight-ingest")


def _dbt_env() -> dict:
    """Env for dbt: DBT_PG_* parsed from DATABASE_URL (DIRECT endpoint), + profiles dir."""
    import os
    from urllib.parse import urlparse
    u = urlparse(os.environ["DATABASE_URL"].replace("-pooler", ""))  # DIRECT endpoint for DDL
    return {
        **os.environ,
        "DBT_PG_HOST": u.hostname or "",
        "DBT_PG_PORT": str(u.port or 5432),
        "DBT_PG_USER": u.username or "",
        "DBT_PG_PASSWORD": u.password or "",
        "DBT_PG_DBNAME": (u.path or "/neondb").lstrip("/"),
        "DBT_PROFILES_DIR": "/app/dbt",
    }


def _run(tickers: list[str]) -> None:
    import os
    import subprocess
    import sys

    os.chdir("/app")
    sys.path.insert(0, "/app")
    from src.ingestion.bronze import ingest as bronze_ingest
    from src.ingestion.corporate_actions import ingest as ca_ingest

    print("== BRONZE: land new filings (incremental) ==")
    bronze_ingest(tickers, only_new=True)
    print("== BRONZE: stock splits ==")
    try:
        ca_ingest(tickers)
    except Exception as e:  # noqa: BLE001 — splits best-effort
        print(f"corporate-actions skip: {e}")

    print("== dbt: deps + build (silver/gold + tests) ==")
    env = _dbt_env()
    subprocess.run(["dbt", "deps"], cwd="/app/dbt", env=env, check=True)
    subprocess.run(["dbt", "build"], cwd="/app/dbt", env=env, check=True)

    print("== forecast ledger: grade reported quarters, log the new forecast ==")
    try:
        from src.analysis import forecast_log
        forecast_log.grade()
        forecast_log.log_forecasts()
    except Exception as e:  # noqa: BLE001 — forecasting shouldn't fail the ingestion run
        print(f"forecast ledger step skipped: {e}")
    print("== DONE ==")


@app.function(image=image, secrets=[modal.Secret.from_name("finsight")],
              schedule=modal.Cron("0 6 * * 1"), timeout=3600)
def scheduled_ingest() -> None:
    """Weekly (Mondays 06:00 UTC) — land new filings + rebuild the medallion."""
    import os
    _run(os.environ.get("FINSIGHT_TICKERS", DEFAULT_TICKERS).split())


@app.local_entrypoint()
def main() -> None:
    """`modal run deploy/modal_ingest.py` — trigger one run immediately."""
    scheduled_ingest.remote()
