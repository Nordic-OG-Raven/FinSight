"""
Tests for NP2SQL after the re-architecture. The LLM call itself needs OPENAI_API_KEY and is
not exercised here; everything it depends on IS: the schema context only names live objects,
its sample SQL runs against the warehouse, and the SQL safety layer behaves.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.np2sql.schema_metadata import get_schema_metadata  # noqa: E402
from src.np2sql.np2sql_service import validate_sql, execute_query  # noqa: E402

DROPPED = {"fact_income_statement", "fact_balance_sheet", "fact_cash_flow",
           "fact_comprehensive_income", "fact_equity_statement", "staging_facts",
           "dim_statement_templates"}
META = get_schema_metadata()


def _db_url():
    return os.getenv("DATABASE_URL", "postgresql://superset:superset@localhost:5432/finsight")


def test_schema_context_has_no_dropped_tables():
    named = set(META["tables"]) | set(META["views"])
    assert named.isdisjoint(DROPPED), named & DROPPED
    # every sample query must avoid the dropped tables too
    for q in META["sample_queries"]:
        assert not any(t in q["sql"] for t in DROPPED), q["sql"]


def test_canonical_labels_exposed():
    for label in ("revenue", "net_income", "total_assets", "total_equity",
                  "total_liabilities_and_equity"):
        assert label in META["normalized_labels"], label


def test_value_usd_documented():
    assert "value_usd" in META["tables"]["fact_financial_metrics"]["columns"]
    assert "value_usd" in META["views"]["v_facts_consolidated"]["columns"]


def test_validate_sql_safety():
    ok, _ = validate_sql("SELECT ticker, value_usd FROM v_facts_consolidated WHERE normalized_label='revenue'")
    assert ok
    assert not validate_sql("UPDATE fact_financial_metrics SET value_numeric=0")[0]
    assert not validate_sql("SELECT * FROM pg_catalog.pg_tables")[0]       # table not allow-listed
    assert not validate_sql("DROP TABLE dim_companies")[0]


@pytest.mark.skipif("CI" in os.environ, reason="needs local warehouse")
def test_sample_queries_execute():
    """Every sample SQL in the schema context runs read-only against the warehouse."""
    for q in META["sample_queries"]:
        ok, msg = validate_sql(q["sql"])
        assert ok, f"validate rejected sample: {msg}: {q['sql']}"
        res = execute_query(q["sql"], _db_url())   # raises on SQL error
        assert isinstance(res["row_count"], int)


@pytest.mark.skipif("CI" in os.environ, reason="needs local warehouse")
def test_usd_comparison_query_returns_both_filers():
    sql = ("SELECT ticker, value_usd FROM v_facts_consolidated WHERE ticker IN ('NVO','AAPL') "
           "AND normalized_label='revenue' AND fiscal_year=2025 AND period_type='duration' "
           "ORDER BY value_usd DESC")
    res = execute_query(sql, _db_url())
    tickers = {r["ticker"] for r in res["data"]}
    assert {"NVO", "AAPL"} <= tickers, res


if __name__ == "__main__":
    import traceback
    fails = 0
    for n, fn in sorted(globals().items()):
        if n.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS {n}")
            except Exception:
                fails += 1; print(f"FAIL {n}"); traceback.print_exc()
    sys.exit(1 if fails else 0)
