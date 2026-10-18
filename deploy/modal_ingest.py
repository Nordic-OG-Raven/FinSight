"""
Scheduled SEC ingestion on Modal (free alternative to GitHub Actions).

Runs the edgartools loader on a weekly cron against the hosted warehouse (e.g. Neon). The
loader is idempotent, so a re-run that finds no new annual filing simply refreshes/ no-ops.

One-time setup
--------------
    pip install modal
    modal token new                                   # authenticate (opens browser)
    modal secret create finsight DATABASE_URL="postgresql://USER:PASS@HOST/neondb?sslmode=require"
    modal deploy deploy/modal_ingest.py               # deploy + schedule

Config
------
    DATABASE_URL        (required, via the `finsight` secret) — the hosted Postgres.
    FINSIGHT_TICKERS    (optional) — space-separated tickers; defaults to the reference set.

Run once on demand (no waiting for the cron):
    modal run deploy/modal_ingest.py
"""
import modal

DEFAULT_TICKERS = "AAPL AVGO JPM NVO GOOGL MSFT AMZN NVDA"

# Slim image: only what the extract→validate→load path needs (edgartools pulls pandas etc.).
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("edgartools>=5.62.0", "sqlalchemy>=2.0.0",
                 "psycopg2-binary>=2.9.0", "python-dotenv>=1.0.0")
    # ship the repo code (adapter, loader, validation, config) into the image
    .add_local_dir(
        ".", remote_path="/app",
        ignore=["*.pyc", "__pycache__", ".git", ".venv", "data", "docs", "tests",
                "Website", "node_modules", "*.md"],
    )
)

app = modal.App("finsight-ingest")


def _load(tickers: list[str]) -> None:
    import os
    import sys

    os.chdir("/app")
    sys.path.insert(0, "/app")
    from config import DATABASE_URL  # reads DATABASE_URL from the Modal secret's env
    from src.extraction.edgartools_adapter import EdgarToolsExtractor
    from database.load_from_edgartools import StarSchemaLoader

    ex = EdgarToolsExtractor()
    loader = StarSchemaLoader(DATABASE_URL)
    print(f"{'TICKER':6} {'FACTS':>7} {'GATE':5} {'QUAL':>5}")
    for tk in tickers:
        try:
            r = ex.extract(tk)
            n, rep = loader.load(r)
            print(f"{tk:6} {n:>7} {'PASS' if rep.passed else 'FAIL':5} {rep.scores.get('overall', 0):>5.2f}")
        except Exception as e:  # isolate failures so one filer can't abort the batch
            loader.conn.rollback()
            print(f"{tk:6}   ERROR: {type(e).__name__}: {str(e)[:70]}")
    loader.close()


@app.function(image=image, secrets=[modal.Secret.from_name("finsight")],
              schedule=modal.Cron("0 6 * * 1"), timeout=1800)
def scheduled_ingest() -> None:
    """Weekly (Mondays 06:00 UTC) — pull the latest annual filings into the warehouse."""
    import os
    _load(os.environ.get("FINSIGHT_TICKERS", DEFAULT_TICKERS).split())


@app.local_entrypoint()
def main() -> None:
    """`modal run deploy/modal_ingest.py` — trigger one ingestion immediately."""
    scheduled_ingest.remote()
