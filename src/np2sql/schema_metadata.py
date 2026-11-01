"""
Semantic model for the NL->SQL "Ask" layer.

This is the curated description of the medallion **gold** serving layer that the LLM sees before it
writes SQL. The connection's search_path is `gold, public`, so bare table names resolve to gold.

It is deliberately a *semantic model*, not a raw schema dump: every table has a grain and join keys,
every ratio is a defined measure, the metric vocabulary is the slim canonical set (not the thousands
of raw XBRL concepts), and the real coverage (which companies and years actually exist) is fetched
live from the warehouse so the model never guesses an entity that isn't there.

Public entry points (unchanged for callers):
  - get_schema_metadata()                 -> dict (cached; the static model)
  - get_enumerations(database_url)         -> dict (cached; live companies + year range)
  - format_schema_for_llm(meta, enums)     -> str  (the prompt block)
  - COMPANIES                              -> entity dictionary (ticker -> name + aliases)
"""

import threading
import time
from functools import lru_cache
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.extraction.canonical_labels import CANONICAL


# ---------------------------------------------------------------------------
# Entity dictionary — the companies the warehouse actually covers.
# Grounded in live coverage (gold.companies). Clean display name + lowercase aliases used to
# detect a company in a free-text question. Ticker symbols are matched separately, so aliases
# only need the natural-language names a user would type.
# ---------------------------------------------------------------------------
COMPANIES: dict[str, dict] = {
    "AAPL": {"name": "Apple", "aliases": ["apple"]},
    "AMD":  {"name": "AMD", "aliases": ["amd", "advanced micro devices"]},
    "AMZN": {"name": "Amazon", "aliases": ["amazon"]},
    "AVGO": {"name": "Broadcom", "aliases": ["broadcom"]},
    "CRM":  {"name": "Salesforce", "aliases": ["salesforce"]},
    "GOOGL": {"name": "Alphabet", "aliases": ["alphabet", "google"]},
    "JPM":  {"name": "JPMorgan Chase", "aliases": ["jpmorgan", "jp morgan", "jpmorgan chase"]},
    "META": {"name": "Meta", "aliases": ["meta", "facebook", "meta platforms"]},
    "MSFT": {"name": "Microsoft", "aliases": ["microsoft"]},
    "NFLX": {"name": "Netflix", "aliases": ["netflix"]},
    "NVDA": {"name": "NVIDIA", "aliases": ["nvidia"]},
    "NVO":  {"name": "Novo Nordisk", "aliases": ["novo nordisk", "novo"]},
    "ORCL": {"name": "Oracle", "aliases": ["oracle"]},
    "TSLA": {"name": "Tesla", "aliases": ["tesla"]},
}


# ---------------------------------------------------------------------------
# Metric vocabulary — the slim canonical labels, grouped by statement. These are the names to
# filter normalized_label / canonical_label on; normalized_label also carries a long tail of
# thousands of raw per-concept labels, which we deliberately do NOT advertise.
# ---------------------------------------------------------------------------
METRIC_GROUPS: dict[str, list[str]] = {
    "Income statement": [
        "revenue", "cost_of_revenue", "gross_profit", "research_and_development_expense",
        "selling_general_and_administrative_expense", "operating_income",
        "income_before_income_taxes", "income_tax_expense", "net_income",
        "eps_basic", "eps_diluted", "weighted_average_shares_basic", "weighted_average_shares_diluted",
    ],
    "Balance sheet": [
        "total_assets", "current_assets", "cash_and_cash_equivalents",
        "total_liabilities", "current_liabilities", "total_equity", "total_liabilities_and_equity",
    ],
    "Cash flow": [
        "net_cash_from_operating_activities", "net_cash_from_investing_activities",
        "net_cash_from_financing_activities", "capital_expenditures", "depreciation_and_amortization",
    ],
}

# Defined measures — the ratios are precomputed once in the warehouse so the model prefers the
# mart over re-deriving them from raw facts (and gets the exact same definition every time).
METRICS: dict[str, str] = {
    "gross_margin": "gross_profit / revenue",
    "operating_margin": "operating_income / revenue",
    "net_margin": "net_income / revenue",
    "return_on_equity": "net_income / total_equity",
    "return_on_assets": "net_income / total_assets",
    "current_ratio": "current_assets / current_liabilities",
    "debt_to_equity": "total_liabilities / total_equity",
    "asset_turnover": "revenue / total_assets",
    "effective_tax_rate": "income_tax_expense / income_before_income_taxes",
    "free_cash_flow_usd": "operating_cash_flow - abs(capital_expenditures)",
    "fcf_margin": "free_cash_flow_usd / revenue",
    "revenue_growth": "revenue / prior_year_revenue - 1 (fraction, year-over-year)",
}

# How the serving objects relate — one grain, consistent keys.
RELATIONSHIPS: list[str] = [
    "Annual marts (company_financials, ratios, peers) share the grain (ticker, fiscal_year) and join on it.",
    "Quarterly marts (company_quarterly, earnings) share the grain (ticker, fiscal_year, fiscal_period) and join on it.",
    "v_facts_consolidated and v_facts_hierarchical hold the raw facts; the marts are built from them, so for a precomputed figure prefer a mart over the raw views.",
    "company_financials and company_quarterly are LONG (one row per canonical_label); ratios, peers and earnings are WIDE (one column per metric).",
]


def _tables() -> dict:
    """The authored table/view definitions (grain, columns, join keys)."""
    return {
        "v_facts_consolidated": {
            "name": "v_facts_consolidated",
            "grain": "one row per consolidated (non-segment) fact: (ticker, metric, period)",
            "description": "PRIMARY raw-fact surface. Consolidated financial facts for every company, "
                           "annual and quarterly. Use this for any metric not already served by a mart.",
            "join_keys": ["ticker", "fiscal_year", "fiscal_period"],
            "columns": {
                "ticker": {"type": "TEXT", "description": "Company ticker (filter by company)"},
                "concept_name": {"type": "TEXT", "description": "Raw XBRL concept, e.g. 'us-gaap:Revenues'"},
                "normalized_label": {"type": "TEXT", "description": "Canonical cross-company metric, e.g. 'revenue','net_income','total_assets' — filter metrics on this"},
                "standard_label": {"type": "TEXT", "description": "edgartools standard concept where available"},
                "statement_type": {"type": "TEXT", "description": "'income_statement','balance_sheet','cash_flow'"},
                "fiscal_year": {"type": "INTEGER", "description": "Fiscal year label (filter by year)"},
                "fiscal_period": {"type": "TEXT", "description": "'FY','Q1'..'Q4'"},
                "period_type": {"type": "TEXT", "description": "'duration' (income/cash-flow) or 'instant' (balance sheet)"},
                "period_grain": {"type": "TEXT", "description": "'annual','quarter','instant','ytd_or_other' — see rules"},
                "value_numeric": {"type": "DOUBLE PRECISION", "description": "Value in the filing's NATIVE currency"},
                "value_usd": {"type": "NUMERIC", "description": "Value in USD — use for cross-company/cross-currency comparison"},
                "unit_measure": {"type": "TEXT", "description": "Native unit ('USD','DKK','shares','USD/share')"},
                "fiscal_year_end": {"type": "DATE", "description": "Fiscal-year-end date of the source filing"},
            },
        },
        "v_facts_hierarchical": {
            "name": "v_facts_hierarchical",
            "grain": "one row per fact, INCLUDING segment/dimensional rows",
            "description": "Richer raw surface: everything in v_facts_consolidated PLUS segment rows and "
                           "the source filing id. Use ONLY when the question needs segments or a filing reference; "
                           "otherwise use v_facts_consolidated to avoid double-counting segments.",
            "join_keys": ["ticker", "fiscal_year", "fiscal_period"],
            "columns": {
                "ticker": {"type": "TEXT", "description": "Company ticker"},
                "accession": {"type": "TEXT", "description": "Source SEC filing id (provenance; traces a number to its filing)"},
                "normalized_label": {"type": "TEXT", "description": "Canonical cross-company metric"},
                "statement_type": {"type": "TEXT", "description": "'income_statement','balance_sheet','cash_flow'"},
                "fiscal_year": {"type": "INTEGER", "description": "Fiscal year label"},
                "fiscal_period": {"type": "TEXT", "description": "'FY','Q1'..'Q4'"},
                "period_grain": {"type": "TEXT", "description": "'annual','quarter','instant','ytd_or_other'"},
                "value_usd": {"type": "NUMERIC", "description": "Value in USD"},
                "is_dimensioned": {"type": "BOOLEAN", "description": "TRUE for a segment/dimensional row, FALSE for consolidated — filter is_dimensioned=false for company totals"},
                "axis_name": {"type": "TEXT", "description": "Segment axis, e.g. 'BusinessSegmentAxis' (only when is_dimensioned)"},
                "member_name": {"type": "TEXT", "description": "Segment member, e.g. the segment name (only when is_dimensioned)"},
            },
        },
        "companies": {
            "name": "companies",
            "grain": "one row per annual filing",
            "description": "Company/filing metadata.",
            "join_keys": ["ticker", "fiscal_year"],
            "columns": {
                "ticker": {"type": "TEXT", "description": "Company ticker"},
                "company_name": {"type": "TEXT", "description": "Company name as filed"},
                "filing_type": {"type": "TEXT", "description": "'10-K','20-F','40-F'"},
                "fiscal_year": {"type": "INTEGER", "description": "Fiscal year"},
                "reporting_frequency": {"type": "TEXT", "description": "'annual' or 'quarterly'"},
            },
        },
        "company_financials": {
            "name": "company_financials",
            "grain": "one row per (ticker, fiscal_year, canonical_label) — LONG",
            "description": "Annual canonical lines per company/year, USD + native currency.",
            "join_keys": ["ticker", "fiscal_year"],
            "columns": {
                "ticker": {"type": "TEXT", "description": "Company ticker"},
                "fiscal_year": {"type": "INTEGER", "description": "Fiscal year"},
                "canonical_label": {"type": "TEXT", "description": "Canonical metric name, e.g. 'revenue' — filter on this"},
                "value_usd": {"type": "NUMERIC", "description": "USD value"},
                "value_native": {"type": "DOUBLE PRECISION", "description": "Native-currency value"},
                "currency": {"type": "TEXT", "description": "Native currency"},
                "statement_type": {"type": "TEXT", "description": "'income_statement','balance_sheet','cash_flow'"},
                "period_end": {"type": "DATE", "description": "Period-end date (flows)"},
                "instant_date": {"type": "DATE", "description": "Balance-sheet instant date"},
            },
        },
        "ratios": {
            "name": "ratios",
            "grain": "one row per (ticker, fiscal_year) — WIDE",
            "description": "Annual financial ratios + headline figures per company/year, in USD. Precomputed.",
            "join_keys": ["ticker", "fiscal_year"],
            "columns": {
                "ticker": {"type": "TEXT", "description": "Company ticker"},
                "fiscal_year": {"type": "INTEGER", "description": "Fiscal year"},
                "revenue_usd": {"type": "NUMERIC", "description": "Revenue (USD)"},
                "net_income_usd": {"type": "NUMERIC", "description": "Net income (USD)"},
                "total_assets_usd": {"type": "NUMERIC", "description": "Total assets (USD)"},
                "total_equity_usd": {"type": "NUMERIC", "description": "Total equity (USD)"},
                "gross_margin": {"type": "NUMERIC", "description": "Gross margin (fraction)"},
                "operating_margin": {"type": "NUMERIC", "description": "Operating margin (fraction)"},
                "net_margin": {"type": "NUMERIC", "description": "Net margin (fraction)"},
                "return_on_equity": {"type": "NUMERIC", "description": "ROE (fraction)"},
                "return_on_assets": {"type": "NUMERIC", "description": "ROA (fraction)"},
                "current_ratio": {"type": "NUMERIC", "description": "Current ratio"},
                "debt_to_equity": {"type": "NUMERIC", "description": "Debt / equity"},
                "asset_turnover": {"type": "NUMERIC", "description": "Revenue / total assets"},
                "effective_tax_rate": {"type": "NUMERIC", "description": "Income tax / pretax income (fraction)"},
                "free_cash_flow_usd": {"type": "NUMERIC", "description": "Free cash flow (USD)"},
                "fcf_margin": {"type": "NUMERIC", "description": "FCF / revenue (fraction)"},
                "revenue_growth": {"type": "NUMERIC", "description": "Year-over-year revenue growth (fraction)"},
            },
        },
        "peers": {
            "name": "peers",
            "grain": "one row per company, LATEST year only — WIDE",
            "description": "Latest-year cross-company snapshot (identical columns to ratios), revenue-sorted. "
                           "Use for 'which company has the highest/lowest X' in the most recent year.",
            "join_keys": ["ticker"],
            "columns": None,  # same as ratios; filled in below
        },
        "company_quarterly": {
            "name": "company_quarterly",
            "grain": "one row per (ticker, fiscal_year, fiscal_period, canonical_label) — LONG",
            "description": "Quarterly series per company (USD), one metric per row. Q4 is DERIVED (annual minus Q1-Q3).",
            "join_keys": ["ticker", "fiscal_year", "fiscal_period"],
            "columns": {
                "ticker": {"type": "TEXT", "description": "Company ticker"},
                "fiscal_year": {"type": "INTEGER", "description": "Fiscal year"},
                "fiscal_period": {"type": "TEXT", "description": "'Q1'..'Q4'"},
                "quarter_num": {"type": "INTEGER", "description": "1..4"},
                "canonical_label": {"type": "TEXT", "description": "Metric name, e.g. 'revenue' — filter on this"},
                "quarter_end": {"type": "DATE", "description": "Quarter-end date"},
                "value_usd": {"type": "NUMERIC", "description": "Quarterly value (USD)"},
                "is_derived": {"type": "BOOLEAN", "description": "TRUE when Q4 was derived rather than directly filed"},
            },
        },
        "earnings": {
            "name": "earnings",
            "grain": "one row per (ticker, fiscal_year, fiscal_period) — WIDE",
            "description": "Quarterly earnings per company: headline figures in USD with split-adjusted EPS. "
                           "Use for quarterly revenue/net income/EPS questions and quarterly time series.",
            "join_keys": ["ticker", "fiscal_year", "fiscal_period"],
            "columns": {
                "ticker": {"type": "TEXT", "description": "Company ticker"},
                "fiscal_year": {"type": "INTEGER", "description": "Fiscal year"},
                "fiscal_period": {"type": "TEXT", "description": "'Q1'..'Q4'"},
                "quarter_end": {"type": "DATE", "description": "Quarter-end date"},
                "revenue_usd": {"type": "NUMERIC", "description": "Quarterly revenue (USD)"},
                "net_income_usd": {"type": "NUMERIC", "description": "Quarterly net income (USD)"},
                "operating_income_usd": {"type": "NUMERIC", "description": "Quarterly operating income (USD)"},
                "eps_diluted": {"type": "NUMERIC", "description": "Diluted EPS as reported"},
                "eps_diluted_adj": {"type": "NUMERIC", "description": "Split-adjusted diluted EPS (current-share basis)"},
                "quarter_index": {"type": "INTEGER", "description": "Monotonic quarter index for ordering a time series (fiscal_year*4 + quarter_num)"},
            },
        },
    }


# ---------------------------------------------------------------------------
# Live enumerations — which companies and years actually exist. Fetched once and cached so the
# model is grounded in real coverage instead of a hardcoded list that drifts out of date.
# ---------------------------------------------------------------------------
_ENUM_TTL_SECONDS = 3600
_enum_cache: dict[str, tuple[float, dict]] = {}
_enum_lock = threading.Lock()


def get_enumerations(database_url: str | None = None) -> dict:
    """Return {'tickers', 'year_min', 'year_max', 'source'} from the live warehouse (cached).

    Falls back to the curated COMPANIES keys (and no year range) if no DB url is given or the
    probe fails, so the Ask feature never breaks on a metadata hiccup.
    """
    fallback = {"tickers": sorted(COMPANIES.keys()), "year_min": None, "year_max": None, "source": "fallback"}
    if not database_url:
        return fallback

    now = time.time()
    with _enum_lock:
        hit = _enum_cache.get(database_url)
        if hit and hit[0] > now:
            return hit[1]

    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(
            database_url.replace("-pooler", ""),
            connect_args={"connect_timeout": 10, "options": "-c search_path=gold,public"},
        )
        try:
            with engine.connect() as conn:
                row = conn.execute(text(
                    "SELECT array_agg(DISTINCT ticker ORDER BY ticker) AS tickers, "
                    "min(fiscal_year) FILTER (WHERE fiscal_year > 1990) AS ymin, "
                    "max(fiscal_year) AS ymax FROM v_facts_consolidated"
                )).one()
        finally:
            engine.dispose()
        enums = {
            "tickers": list(row[0] or []) or fallback["tickers"],
            "year_min": row[1],
            "year_max": row[2],
            "source": "live",
        }
        with _enum_lock:
            _enum_cache[database_url] = (now + _ENUM_TTL_SECONDS, enums)
        return enums
    except Exception:
        return fallback


@lru_cache(maxsize=1)
def get_schema_metadata() -> dict:
    """The static semantic model (cached). Live coverage is layered on via get_enumerations()."""
    tables = _tables()
    tables["peers"]["columns"] = tables["ratios"]["columns"]  # peers mirrors ratios

    # Canonical labels (back-compat shape: label -> {description, concept_examples, usage}).
    normalized_labels = {}
    for label, concept_names in CANONICAL.items():
        normalized_labels[label] = {
            "description": f"Canonical cross-company label '{label}'",
            "concept_examples": concept_names[:3],
            "usage": f"normalized_label = '{label}'",
        }

    sample_queries = [
        {"question": "Show me Apple's revenue in 2024",
         "sql": "SELECT value_usd FROM v_facts_consolidated WHERE ticker = 'AAPL' AND normalized_label = 'revenue' AND fiscal_year = 2024 AND period_grain = 'annual'"},
        {"question": "Compare net income across all companies in 2024",
         "sql": "SELECT ticker, value_usd FROM v_facts_consolidated WHERE normalized_label = 'net_income' AND fiscal_year = 2024 AND period_grain = 'annual' ORDER BY value_usd DESC"},
        {"question": "What were Microsoft's total assets in 2024?",
         "sql": "SELECT value_usd FROM v_facts_consolidated WHERE ticker = 'MSFT' AND normalized_label = 'total_assets' AND fiscal_year = 2024 AND period_grain = 'instant'"},
        {"question": "Which company had the highest net margin in the latest year?",
         "sql": "SELECT ticker, net_margin FROM peers ORDER BY net_margin DESC NULLS LAST LIMIT 1"},
        {"question": "Show NVIDIA's quarterly revenue over time",
         "sql": "SELECT fiscal_year, fiscal_period, revenue_usd FROM earnings WHERE ticker = 'NVDA' ORDER BY quarter_index"},
        {"question": "Rank companies by revenue growth in 2024",
         "sql": "SELECT ticker, revenue_growth FROM ratios WHERE fiscal_year = 2024 ORDER BY revenue_growth DESC NULLS LAST"},
    ]

    company_mappings = {t: [info["name"], *[(a.title()) for a in info["aliases"]], t] for t, info in COMPANIES.items()}

    return {
        "tables": tables,
        "views": {},
        "metrics": METRICS,
        "metric_groups": METRIC_GROUPS,
        "relationships": RELATIONSHIPS,
        "normalized_labels": normalized_labels,
        "sample_queries": sample_queries,
        "company_mappings": company_mappings,
        "business_rules": [
            "v_facts_consolidated is the primary surface for raw financial facts; prefer a mart when one already serves the figure.",
            "For a FULL-YEAR figure filter period_grain = 'annual' (balance-sheet lines use period_grain = 'instant').",
            "For a single quarter use the earnings or company_quarterly mart, or v_facts_consolidated with period_grain = 'quarter'.",
            "Use value_usd for cross-company / cross-currency comparison; value_numeric is native currency (e.g. NVO in DKK).",
            "Filter metrics with the canonical normalized_label / canonical_label names; do not invent metric names.",
            "Only reference companies (tickers) and years listed under AVAILABLE COVERAGE; if the question names one that is not listed, return SELECT 1 WHERE 1=0.",
            "For ready-made ratios use ratios (per year) or peers (latest year); for quarterly earnings use earnings.",
        ],
    }


def format_schema_for_llm(metadata: dict, enumerations: dict | None = None) -> str:
    """Render the semantic model as the prompt block the LLM sees."""
    lines = ["=== FINANCIAL DATA WAREHOUSE (gold layer) ===\n"]

    # Live coverage first — the entities the model is allowed to reference.
    if enumerations:
        companies = metadata.get("company_mappings", {})
        tickers = enumerations.get("tickers") or sorted(companies.keys())
        lines.append("## AVAILABLE COVERAGE")
        name_for = {t: (companies.get(t, [t])[0]) for t in tickers}
        lines.append(f"Companies ({len(tickers)}) — query only these tickers:")
        lines.append("  " + ", ".join(f"{t} ({name_for.get(t, t)})" for t in tickers))
        if enumerations.get("year_min") and enumerations.get("year_max"):
            lines.append(f"Fiscal years available: {enumerations['year_min']}-{enumerations['year_max']} (fiscal-year labels, e.g. NVDA's FY2027).")
        lines.append("")

    # Metric vocabulary.
    lines.append("## METRIC LABELS (filter normalized_label / canonical_label on these)")
    for group, labels in metadata.get("metric_groups", {}).items():
        lines.append(f"  {group}: {', '.join(labels)}")
    lines.append("  (normalized_label also holds a long tail of thousands of raw concept labels; "
                 "prefer the canonical names above for reliable cross-company queries.)")
    lines.append("")

    # Tables.
    lines.append("## TABLES & VIEWS")
    for table_name, table_info in {**metadata["tables"], **metadata["views"]}.items():
        lines.append(f"### {table_name}  —  grain: {table_info.get('grain', 'n/a')}")
        lines.append(table_info["description"])
        if table_info.get("join_keys"):
            lines.append(f"Join keys: {', '.join(table_info['join_keys'])}")
        lines.append("Columns:")
        for col_name, col_info in (table_info["columns"] or {}).items():
            lines.append(f"  - {col_name} ({col_info['type']}): {col_info['description']}")
        lines.append("")

    # Defined measures.
    lines.append("## DEFINED MEASURES (precomputed in ratios / peers — use the column, don't recompute)")
    for name, formula in metadata.get("metrics", {}).items():
        lines.append(f"  - {name} = {formula}")
    lines.append("")

    # Relationships.
    lines.append("## RELATIONSHIPS")
    for rel in metadata.get("relationships", []):
        lines.append(f"  - {rel}")
    lines.append("")

    # Rules.
    lines.append("## RULES")
    for rule in metadata["business_rules"]:
        lines.append(f"  - {rule}")
    lines.append("")

    # Example queries (teaching few-shot — the model still generates fresh SQL).
    lines.append("## EXAMPLE QUERIES")
    for i, sample in enumerate(metadata["sample_queries"], 1):
        lines.append(f"{i}. Q: {sample['question']}")
        lines.append(f"   SQL: {sample['sql']}")
    lines.append("")

    return "\n".join(lines)
