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
    assert "value_usd" in META["tables"]["v_facts_consolidated"]["columns"]
    assert "value_usd" in META["tables"]["ratios"]["columns"] or \
        "revenue_usd" in META["tables"]["ratios"]["columns"]


def test_validate_sql_safety():
    ok, _ = validate_sql("SELECT ticker, value_usd FROM v_facts_consolidated WHERE normalized_label='revenue'")
    assert ok
    assert not validate_sql("UPDATE fact_financial_metrics SET value_numeric=0")[0]
    assert not validate_sql("SELECT * FROM pg_catalog.pg_tables")[0]       # table not allow-listed
    assert not validate_sql("DROP TABLE dim_companies")[0]


def test_company_coverage_grounded():
    """The entity dictionary tracks the warehouse's real 14-company coverage, not the retired list."""
    from src.np2sql.np2sql_service import detect_companies_in_query
    from src.np2sql.schema_metadata import COMPANIES, get_enumerations
    assert {"TSLA", "META", "AMD", "NFLX", "ORCL"} <= set(COMPANIES)   # really covered now
    assert not ({"PFE", "WMT", "KO", "LLY"} & set(COMPANIES))          # retired, had no data
    assert detect_companies_in_query("How did Tesla do?") == ["TSLA"]
    assert detect_companies_in_query("tell me about Pfizer") == []
    assert detect_companies_in_query("show metadata for amazon") == ["AMZN"]  # 'meta' must not fire
    fb = get_enumerations(None)   # no-DB fallback must be safe and complete
    assert fb["source"] == "fallback" and len(fb["tickers"]) == len(COMPANIES)


def test_execution_sql_handles_trailing_semicolon():
    """A model-emitted trailing ';' must not break the appended row cap."""
    from src.np2sql.np2sql_service import _prepare_execution_sql
    assert _prepare_execution_sql("SELECT 1;", 100) == "SELECT 1 LIMIT 101"
    assert _prepare_execution_sql("SELECT 1 ;  ", 100) == "SELECT 1 LIMIT 101"
    assert _prepare_execution_sql("SELECT 1 LIMIT 5;", 100) == "SELECT 1 LIMIT 5"
    assert _prepare_execution_sql("SELECT 1", 100) == "SELECT 1 LIMIT 101"


def test_prompt_block_grounded_and_clean():
    """The LLM prompt advertises live coverage and no longer names the dropped star schema."""
    from src.np2sql.schema_metadata import format_schema_for_llm, COMPANIES
    enums = {"tickers": sorted(COMPANIES), "year_min": 2014, "year_max": 2027, "source": "live"}
    s = format_schema_for_llm(META, enums)
    assert "AVAILABLE COVERAGE" in s and "TSLA" in s
    assert "fact_financial_metrics" not in s and "dimension_id" not in s


def test_lexical_selection_relevant_and_diverse():
    """Fallback retrieval keys on masked intent (not the company named) and stays diverse.
    Backend is pinned off so this is deterministic and never makes a network call in CI."""
    from src.np2sql import example_queries as eq
    orig = eq._get_backend
    eq._get_backend = lambda: None
    try:
        picks = eq.select_examples("What was Oracle's operating margin in 2022?")
        assert 1 <= len(picks) <= 3 and all("question" in p and "sql" in p for p in picks)
        assert any(p["intent"] == "ratio" for p in picks)             # company masked -> still a margin example
        assert any(p["intent"] == "quarterly"
                   for p in eq.select_examples("show me the quarterly revenue for some company"))
        # synonym layer: "over the years" must now reach the trend example (the gap embeddings would fix)
        assert any(p["intent"] == "trend"
                   for p in eq.select_examples("how did some company's revenue do over the years"))
        broad = eq.select_examples("compare and rank the companies by their growth")
        assert len({p["intent"] for p in broad}) >= 2                 # not 3 near-duplicates
    finally:
        eq._get_backend = orig


def test_embedding_scores_drive_selection_with_diversity():
    """When an embedding backend is available, its scores rank selection, still kept diverse."""
    from src.np2sql import example_queries as eq
    orig = eq._score_embedding
    priority = {"rank": 0.95, "ratio": 0.90, "quarterly": 0.85}
    eq._score_embedding = lambda q: [(priority.get(eq.EXAMPLES[i]["intent"], 0.1), i) for i in range(eq._N)]
    try:
        intents = [p["intent"] for p in eq.select_examples("anything", k=3)]
        assert intents[0] == "rank" and len(set(intents)) == 3
    finally:
        eq._score_embedding = orig


def _ok_result():
    return {"data": [{"n": 1}], "columns": ["n"], "row_count": 1, "execution_time": 0.0, "warning": None}


def test_answer_query_self_corrects_on_execution_error():
    """A first SQL that errors on execution is repaired on the second attempt."""
    from src.np2sql.np2sql_service import answer_query
    def gen(q, meta, db, prior_attempt=None):
        return "SELECT nope FROM ratios" if prior_attempt is None else "SELECT 1"
    def ex(sql, db, timeout=30, max_rows=10000):
        if "nope" in sql:
            raise Exception('column "nope" does not exist')
        return _ok_result()
    out = answer_query("q", {}, "db://x", _generate=gen, _execute=ex)
    assert out["success"] and out["attempts"] == 2 and len(out["repairs"]) == 1


def test_answer_query_repairs_safety_rejection():
    """A first SQL rejected by the safety check is repaired, not returned as an error."""
    from src.np2sql.np2sql_service import answer_query
    seq = iter(["DROP TABLE x", "SELECT 1"])
    def gen(q, meta, db, prior_attempt=None):
        return next(seq)
    out = answer_query("q", {}, "db", _generate=gen, _execute=lambda *a, **k: _ok_result())
    assert out["success"] and out["attempts"] == 2
    assert "safety" in out["repairs"][0]["error"].lower()


def test_answer_query_gives_up_after_max_attempts():
    from src.np2sql.np2sql_service import answer_query
    def ex(sql, db, timeout=30, max_rows=10000):
        raise Exception("boom")
    out = answer_query("q", {}, "db", max_attempts=3,
                       _generate=lambda *a, **k: "SELECT bad FROM ratios", _execute=ex)
    assert not out["success"] and out["attempts"] == 3 and len(out["repairs"]) == 3 and out["error"]


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
           "AND normalized_label='revenue' AND fiscal_year=2025 AND period_grain='annual' "
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
