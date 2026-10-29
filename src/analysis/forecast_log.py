"""Live forecast track-record ledger — the pitch asset.

A backtest can hide leakage; a timestamped, out-of-sample live log cannot. Each run upserts the
current next-quarter forecast (revenue + EPS) for the tracked tickers; `grade()` fills in the actual
+ consensus + errors once a quarter reports. Over time this accumulates an auditable record of
"our forecast vs what actually happened vs what the analysts said" — made before each print.

Table `forecasts.forecast_log` is Python-managed (operational, append/upsert) using the same
psycopg2 pattern as `src/ingestion/bronze.py`. Run weekly from `deploy/modal_ingest.py`:
grade() (reported quarters) then log_forecasts() (the new current forecast).
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import DATABASE_URL  # noqa: E402
from src.analysis import forecasting_v2 as fv  # noqa: E402
from src.analysis import pit  # noqa: E402
from src.analysis import regime as rg  # noqa: E402
from src.ingestion.bronze import direct_dsn  # noqa: E402

# Ledger universe. REVENUE is logged for every ticker here — it is our strongest, best-generalizing
# output (leakage-safe backtest MAPE < 8% for all; see scripts/forecast_coverage.py). EPS is logged
# ONLY where the revenue->margin->EPS chain is competitive with analyst consensus: AVGO/GOOGL/JPM
# have reliable revenue forecasts but their EPS is distorted by acquisition amortization, other
# income/FX, and bank accounting respectively, so we do not log an EPS number we know is weak.
# Routes (guidance vs seasonal) are auto-detected per ticker by regime.classify; components are
# overridden only where segment roll-up has been validated to help (NVDA).
LEDGER = {
    "NVDA":  {"eps": True},    # revenue 1.2%, EPS 4.5% vs consensus 4.8% (we edge it)
    "AMZN":  {"eps": False},   # revenue 3.9%, but EPS chain broken by lumpy one-time items (83% vs 52%)
    "MSFT":  {"eps": True},    # revenue 3.6%, EPS 8.9% vs consensus 5.7% (we trail but it's close+honest)
    "AVGO":  {"eps": False},   # revenue 0.6%, EPS chain broken by acquisition amortization
    "GOOGL": {"eps": False},   # revenue 6.1%, EPS chain weak (other income / FX swings)
    "JPM":   {"eps": False},   # revenue 8.0%, bank P&L does not fit revenue->margin->EPS
    "AAPL":  {"eps": False},   # revenue weaker historically (trend-inflection lag); report it honestly
}
_COMPONENTS = {"NVDA": ["segment:compute_and_networking", "segment:graphics"]}


def build_specs(db=DATABASE_URL):
    """Auto-route each ledger ticker into (ticker, components, regime, method, log_eps)."""
    specs = []
    for tk, cfg in LEDGER.items():
        # regex covers the whole current universe deterministically; the LLM net is insurance for
        # future odd-phrasing tickers, so we don't pay for it on every routine routing pass.
        r = rg.classify(db, tk, use_llm=False)
        specs.append((tk, _COMPONENTS.get(tk, r.components), r.regime, r.method, cfg["eps"]))
    return specs

DDL = """
CREATE SCHEMA IF NOT EXISTS forecasts;
CREATE TABLE IF NOT EXISTS forecasts.forecast_log (
    ticker               TEXT NOT NULL,
    target_fiscal_year   INTEGER NOT NULL,
    target_quarter       INTEGER NOT NULL,
    metric               TEXT NOT NULL,          -- 'revenue' | 'eps'
    forecast             DOUBLE PRECISION,
    interval_lo          DOUBLE PRECISION,
    interval_hi          DOUBLE PRECISION,
    model                TEXT,
    consensus            DOUBLE PRECISION,
    actual               DOUBLE PRECISION,
    actual_reported_at   DATE,
    our_ape              DOUBLE PRECISION,        -- |forecast-actual|/|actual|
    consensus_ape        DOUBLE PRECISION,
    run_ts               TIMESTAMPTZ NOT NULL DEFAULT now(),
    graded_at            TIMESTAMPTZ,
    PRIMARY KEY (ticker, target_fiscal_year, target_quarter, metric)
);
"""


def _conn():
    conn = psycopg2.connect(direct_dsn())
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()
    return conn


def _revenue_consensus(ticker):
    try:
        re = fv.yf_revenue_estimate(ticker)
        if re is not None and "0q" in re.index:
            return float(re.loc["0q", "avg"])
    except Exception:  # noqa: BLE001
        pass
    return None


def log_forecasts(db=DATABASE_URL, specs=None) -> None:
    """Compute + upsert the current next-quarter revenue & EPS forecast for each tracked ticker.
    Only rows not yet graded are overwritten (a frozen, graded row is never changed)."""
    specs = specs or build_specs(db)
    conn = _conn()
    try:
        for tk, comps, regime, method, log_eps in specs:
            r = fv.forecast_eps(db, tk, comps, regime)
            fy_s, q_s = r["target"].replace("FY", "").split(" Q")
            fy, q = int(fy_s), int(q_s)
            rev, iv = r["revenue"], r["revenue"].get("interval_80")
            rows = [
                (tk, fy, q, "revenue", rev["forecast"], iv[0] if iv else None, iv[1] if iv else None,
                 rev["best_model"], _revenue_consensus(tk)),
            ]
            if log_eps and r.get("eps_forecast") is not None:
                rows.append((tk, fy, q, "eps", r["eps_forecast"], None, None,
                             "revenue->margin->eps", r["consensus_eps"]))
            with conn.cursor() as cur:
                execute_values(cur, """
                    INSERT INTO forecasts.forecast_log
                      (ticker, target_fiscal_year, target_quarter, metric, forecast,
                       interval_lo, interval_hi, model, consensus)
                    VALUES %s
                    ON CONFLICT (ticker, target_fiscal_year, target_quarter, metric)
                    DO UPDATE SET forecast=EXCLUDED.forecast, interval_lo=EXCLUDED.interval_lo,
                       interval_hi=EXCLUDED.interval_hi, model=EXCLUDED.model,
                       consensus=EXCLUDED.consensus, run_ts=now()
                    WHERE forecasts.forecast_log.graded_at IS NULL
                """, rows)
            conn.commit()
            eps_s = f", EPS {r['eps_forecast']:.2f}" if (log_eps and r.get("eps_forecast") is not None) else ""
            print(f"  logged {tk} FY{fy} Q{q}: revenue {rev['forecast']/1e9:.1f}B{eps_s}")
    finally:
        conn.close()


def _reported_eps(ticker, quarter_end):
    """yfinance Reported EPS for the quarter ending `quarter_end` (report lands within ~70 days)."""
    try:
        ed = fv.yf_earnings_dates(ticker, 16)
        if ed is None:
            return None, None
        for dt, row in ed.iterrows():
            d = dt.date()
            rep = row.get("Reported EPS")
            if quarter_end < d <= quarter_end + timedelta(days=75) and rep is not None and not np.isnan(rep):
                return float(rep), d
    except Exception:  # noqa: BLE001
        pass
    return None, None


def grade(db=DATABASE_URL) -> None:
    """Fill actual + errors for logged quarters that have since reported."""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT ticker, target_fiscal_year, target_quarter, metric, forecast, consensus
                           FROM forecasts.forecast_log WHERE graded_at IS NULL""")
            pending = cur.fetchall()
        reports_cache: dict = {}
        for tk, fy, q, metric, forecast, consensus in pending:
            # the quarter's actual revenue + end date, from gold.earnings (present once it reports)
            with conn.cursor() as cur:
                cur.execute("""SELECT quarter_end, revenue_usd FROM gold.earnings
                               WHERE ticker=%s AND fiscal_year=%s AND fiscal_period=%s""",
                            (tk, fy, f"Q{q}"))
                row = cur.fetchone()
            if not row or row[1] is None:
                continue
            quarter_end, rev_actual = row[0], float(row[1])
            if hasattr(quarter_end, "date"):
                quarter_end = quarter_end.date()

            if metric == "revenue":
                actual = rev_actual
                if tk not in reports_cache:
                    reports_cache[tk] = pit.quarter_report_dates(db, tk)
                reported_at = reports_cache[tk].get(quarter_end)
            else:  # eps
                actual, reported_at = _reported_eps(tk, quarter_end)
                if actual is None:
                    continue

            our_ape = abs(forecast - actual) / abs(actual) if (forecast and actual) else None
            cons_ape = abs(consensus - actual) / abs(actual) if (consensus and actual) else None
            with conn.cursor() as cur:
                cur.execute("""UPDATE forecasts.forecast_log
                               SET actual=%s, actual_reported_at=%s, our_ape=%s, consensus_ape=%s, graded_at=now()
                               WHERE ticker=%s AND target_fiscal_year=%s AND target_quarter=%s AND metric=%s""",
                            (actual, reported_at, our_ape, cons_ape, tk, fy, q, metric))
            conn.commit()
            print(f"  graded {tk} FY{fy} Q{q} {metric}: actual {actual:.3g}, our_ape "
                  f"{our_ape*100 if our_ape else None:.1f}%, cons_ape {cons_ape*100 if cons_ape else None:.1f}%")
    finally:
        conn.close()


def _eps_actual_and_consensus(ticker, quarter_end):
    """(reported_eps, consensus_eps, report_date) for the quarter ending quarter_end, from yfinance."""
    try:
        ed = fv.yf_earnings_dates(ticker, 16)
        if ed is None:
            return None, None, None
        for dt, row in ed.iterrows():
            d = dt.date()
            rep, est = row.get("Reported EPS"), row.get("EPS Estimate")
            if quarter_end < d <= quarter_end + timedelta(days=75) and rep is not None and not np.isnan(rep):
                return float(rep), (float(est) if est is not None and not np.isnan(est) else None), d
    except Exception:  # noqa: BLE001
        pass
    return None, None, None


def backfill(db=DATABASE_URL, specs=None) -> None:
    """Seed the ledger with the HISTORICAL point-in-time record (forecasts made as-of before each
    past print), so the track record is populated from day one. Rows are tagged model='backtest:*'
    to distinguish them from going-forward live forecasts.

    Revenue comes from `forecasting_v2.realized_backtest` — the SAME walk-forward the coverage
    scorecard reports — so the ledger and the scorecard always agree. EPS (where logged) applies the
    point-in-time net margin to that realized revenue forecast."""
    specs = specs or build_specs(db)
    conn = _conn()
    try:
        for tk, comps, regime, method, log_eps in specs:
            rb = fv.realized_backtest(db, tk, comps, method)
            sh = pit.latest_series(db, tk, "weighted_average_shares_diluted")
            cur_shares = sh[-1].value if sh else None
            n = 0
            for item in rb:
                fy, q, qe_d, report_date = item["fy"], item["q"], item["quarter_end"], item["report_date"]
                rev_hat, rev_actual = item["forecast"], item["actual"]
                writes = [("revenue", "backtest:" + method, rev_hat, None, rev_actual, item["ape"], None)]
                if log_eps and cur_shares:
                    nm_pts = fv._ratio_points(db, tk, "net_income", report_date - timedelta(days=1))
                    if len(nm_pts) >= 4:
                        eps_our = rev_hat * fv.recent_mean(nm_pts, None, None) / cur_shares
                        eps_act, eps_cons, _ = _eps_actual_and_consensus(tk, qe_d)
                        if eps_act:
                            writes.append(("eps", "backtest:chain", eps_our, eps_cons, eps_act,
                                           abs(eps_our - eps_act) / abs(eps_act),
                                           (abs(eps_cons - eps_act) / abs(eps_act)) if eps_cons else None))
                with conn.cursor() as cur:
                    for metric, mdl, fcast, cons, act, ape, cape in writes:
                        cur.execute("""INSERT INTO forecasts.forecast_log
                            (ticker,target_fiscal_year,target_quarter,metric,forecast,model,consensus,
                             actual,actual_reported_at,our_ape,consensus_ape,graded_at)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                            ON CONFLICT (ticker,target_fiscal_year,target_quarter,metric) DO UPDATE SET
                             forecast=EXCLUDED.forecast, consensus=EXCLUDED.consensus, actual=EXCLUDED.actual,
                             actual_reported_at=EXCLUDED.actual_reported_at, our_ape=EXCLUDED.our_ape,
                             consensus_ape=EXCLUDED.consensus_ape, model=EXCLUDED.model, graded_at=now()""",
                            (tk, fy, q, metric, fcast, mdl, cons, act, report_date, ape, cape))
                conn.commit()
                n += 1
            print(f"  backfilled {tk}: {n} quarters")
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["log", "grade", "backfill", "both"], nargs="?", default="both")
    args = ap.parse_args()
    if args.action == "backfill":
        print("== backfill ==")
        backfill()
    if args.action in ("grade", "both"):
        print("== grade ==")
        grade()
    if args.action in ("log", "both"):
        print("== log ==")
        log_forecasts()
