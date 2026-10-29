"""
Schema metadata generation for NP2SQL.

Describes the medallion **gold** serving layer (the connection's search_path is set to
`gold, public`, so bare names resolve to gold). The retired legacy star schema is no longer
advertised.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.extraction.canonical_labels import CANONICAL


def get_schema_metadata() -> dict:
    """Generate comprehensive schema metadata (gold layer) for LLM context."""

    # Primary serving view: one row per consolidated fact, across annual + quarterly grains.
    v_facts_consolidated = {
        "name": "v_facts_consolidated",
        "description": "PRIMARY VIEW. Consolidated (non-segment) financial facts, all companies, "
                       "annual and quarterly. Use this for most queries.",
        "columns": {
            "ticker": {"type": "TEXT", "description": "Company ticker (e.g. 'AAPL','NVO') — filter by company"},
            "concept_name": {"type": "TEXT", "description": "Raw XBRL concept (e.g. 'us-gaap:Revenues')"},
            "normalized_label": {"type": "TEXT", "description": "Canonical cross-company metric (e.g. 'revenue','net_income','total_assets') — filter metrics on this"},
            "standard_label": {"type": "TEXT", "description": "edgartools standard concept where available"},
            "statement_type": {"type": "TEXT", "description": "'income_statement','balance_sheet','cash_flow',..."},
            "fiscal_year": {"type": "INTEGER", "description": "Fiscal year (reliably derived) — filter by year"},
            "fiscal_period": {"type": "TEXT", "description": "'FY','Q1'..'Q4' — the reporting period"},
            "period_type": {"type": "TEXT", "description": "'duration' (income/cash-flow) or 'instant' (balance sheet)"},
            "period_grain": {"type": "TEXT", "description": "'annual','quarter','instant','ytd_or_other' — FILTER period_grain='annual' for full-year figures, 'quarter' for a single quarter"},
            "value_numeric": {"type": "DOUBLE PRECISION", "description": "Value in the filing's NATIVE currency"},
            "value_usd": {"type": "NUMERIC", "description": "Value in USD — use for cross-currency comparison (e.g. NVO in DKK)"},
            "unit_measure": {"type": "TEXT", "description": "Native unit ('USD','DKK','shares','USD/share')"},
            "fiscal_year_end": {"type": "DATE", "description": "Fiscal-year-end date of the source filing"},
        },
        "business_rules": [
            "For a FULL-YEAR figure, filter period_grain = 'annual' (balance-sheet lines use period_grain='instant').",
            "For a single quarter, filter period_grain = 'quarter' and fiscal_period in ('Q1','Q2','Q3','Q4').",
            "Use value_usd for cross-company comparison; value_numeric is native currency.",
            "Filter metrics with normalized_label (canonical names below).",
        ],
    }

    company_financials = {
        "name": "company_financials",
        "description": "Annual canonical lines per company/year in USD + native. One row per (ticker, fiscal_year, canonical_label).",
        "columns": {
            "ticker": {"type": "TEXT", "description": "Company ticker"},
            "fiscal_year": {"type": "INTEGER", "description": "Fiscal year"},
            "canonical_label": {"type": "TEXT", "description": "Canonical metric name (e.g. 'revenue')"},
            "value_usd": {"type": "NUMERIC", "description": "USD value"},
            "value_native": {"type": "DOUBLE PRECISION", "description": "Native-currency value"},
            "currency": {"type": "TEXT", "description": "Native currency"},
        },
    }

    ratios = {
        "name": "ratios",
        "description": "Annual financial ratios per company/year in USD (margins, ROE/ROA, leverage, FCF, revenue growth).",
        "columns": {
            "ticker": {"type": "TEXT", "description": "Company ticker"},
            "fiscal_year": {"type": "INTEGER", "description": "Fiscal year"},
            "revenue_usd": {"type": "NUMERIC", "description": "Revenue (USD)"},
            "net_income_usd": {"type": "NUMERIC", "description": "Net income (USD)"},
            "gross_margin": {"type": "NUMERIC", "description": "Gross margin (fraction)"},
            "operating_margin": {"type": "NUMERIC", "description": "Operating margin"},
            "net_margin": {"type": "NUMERIC", "description": "Net margin"},
            "return_on_equity": {"type": "NUMERIC", "description": "ROE"},
            "return_on_assets": {"type": "NUMERIC", "description": "ROA"},
            "debt_to_equity": {"type": "NUMERIC", "description": "Debt / equity"},
            "current_ratio": {"type": "NUMERIC", "description": "Current ratio"},
            "free_cash_flow_usd": {"type": "NUMERIC", "description": "Free cash flow (USD)"},
            "revenue_growth": {"type": "NUMERIC", "description": "YoY revenue growth (fraction)"},
        },
    }

    peers = {
        "name": "peers",
        "description": "Latest-year cross-company snapshot (same columns as ratios), revenue-sorted.",
        "columns": ratios["columns"],
    }

    earnings = {
        "name": "earnings",
        "description": "Quarterly earnings per company (revenue/net income/EPS, USD), with derived Q4 and split-adjusted EPS.",
        "columns": {
            "ticker": {"type": "TEXT", "description": "Company ticker"},
            "fiscal_year": {"type": "INTEGER", "description": "Fiscal year"},
            "fiscal_period": {"type": "TEXT", "description": "'Q1'..'Q4'"},
            "quarter_end": {"type": "DATE", "description": "Quarter-end date"},
            "revenue_usd": {"type": "NUMERIC", "description": "Quarterly revenue (USD)"},
            "net_income_usd": {"type": "NUMERIC", "description": "Quarterly net income (USD)"},
            "eps_diluted": {"type": "NUMERIC", "description": "Diluted EPS as reported"},
            "eps_diluted_adj": {"type": "NUMERIC", "description": "Split-adjusted diluted EPS (current-share basis)"},
        },
    }

    # Canonical normalized labels (the cross-company metric names to filter normalized_label on).
    normalized_labels = {}
    for label, concept_names in CANONICAL.items():
        normalized_labels[label] = {
            "description": f"Canonical cross-company label '{label}'",
            "concept_examples": concept_names[:3],
            "usage": f"Use normalized_label = '{label}' to query this metric across all companies",
        }

    sample_queries = [
        {
            "question": "Show me Apple's revenue in 2024",
            "sql": "SELECT value_usd FROM v_facts_consolidated WHERE ticker = 'AAPL' AND normalized_label = 'revenue' AND fiscal_year = 2024 AND period_grain = 'annual'",
        },
        {
            "question": "Compare net income across all companies in 2025",
            "sql": "SELECT ticker, value_usd FROM v_facts_consolidated WHERE normalized_label = 'net_income' AND fiscal_year = 2025 AND period_grain = 'annual' ORDER BY value_usd DESC",
        },
        {
            "question": "What is Microsoft's total assets in 2025?",
            "sql": "SELECT value_usd FROM v_facts_consolidated WHERE ticker = 'MSFT' AND normalized_label = 'total_assets' AND fiscal_year = 2025 AND period_grain = 'instant'",
        },
        {
            "question": "Compare Novo Nordisk and Apple revenue in USD (NVO reports in DKK)",
            "sql": "SELECT ticker, value_usd FROM v_facts_consolidated WHERE ticker IN ('NVO','AAPL') AND normalized_label = 'revenue' AND fiscal_year = 2025 AND period_grain = 'annual' ORDER BY value_usd DESC",
        },
        {
            "question": "Which company has the highest net margin in the latest year?",
            "sql": "SELECT ticker, net_margin FROM peers ORDER BY net_margin DESC NULLS LAST LIMIT 1",
        },
        {
            "question": "Show NVIDIA's quarterly revenue",
            "sql": "SELECT fiscal_year, fiscal_period, revenue_usd FROM earnings WHERE ticker = 'NVDA' ORDER BY quarter_index",
        },
    ]

    company_mappings = {
        "AAPL": ["Apple", "Apple Inc", "AAPL"],
        "MSFT": ["Microsoft", "MSFT"],
        "GOOGL": ["Alphabet", "Google", "GOOGL"],
        "NVDA": ["NVIDIA", "NVDA"],
        "NVO": ["Novo Nordisk", "Novo", "NVO"],
        "AMZN": ["Amazon", "AMZN"],
        "AVGO": ["Broadcom", "AVGO"],
        "JPM": ["JPMorgan", "JPMorgan Chase", "JPM"],
    }

    return {
        "tables": {
            "v_facts_consolidated": v_facts_consolidated,
            "company_financials": company_financials,
            "ratios": ratios,
            "peers": peers,
            "earnings": earnings,
        },
        "views": {},
        "normalized_labels": normalized_labels,
        "sample_queries": sample_queries,
        "company_mappings": company_mappings,
        "business_rules": [
            "v_facts_consolidated is the primary surface for raw financial facts.",
            "For full-year figures filter period_grain='annual' (balance-sheet lines use 'instant'); for a quarter use period_grain='quarter'.",
            "Use value_usd for cross-company/cross-currency comparison.",
            "Use normalized_label (canonical names) for metric filtering.",
            "For ready-made ratios use the ratios / peers marts; for quarterly earnings use the earnings mart.",
            "Filter by ticker for a specific company.",
        ],
    }


def format_schema_for_llm(metadata: dict) -> str:
    """Format schema metadata as a string for the LLM prompt."""
    lines = []
    lines.append("=== FINANCIAL DATA WAREHOUSE SCHEMA (gold layer) ===\n")

    lines.append("## TABLES & VIEWS\n")
    for table_name, table_info in {**metadata["tables"], **metadata["views"]}.items():
        lines.append(f"### {table_name}")
        lines.append(f"Description: {table_info['description']}")
        lines.append("Columns:")
        for col_name, col_info in table_info["columns"].items():
            lines.append(f"  - {col_name} ({col_info['type']}): {col_info['description']}")
        if "business_rules" in table_info:
            lines.append("Rules:")
            for rule in table_info["business_rules"]:
                lines.append(f"  - {rule}")
        lines.append("")

    lines.append("## COMMON NORMALIZED LABELS\n")
    common_labels = ["revenue", "cost_of_revenue", "gross_profit", "operating_income", "net_income",
                     "income_tax_expense", "total_assets", "current_assets", "cash_and_cash_equivalents",
                     "total_liabilities", "current_liabilities", "total_equity",
                     "net_cash_from_operating_activities", "capital_expenditures", "eps_diluted"]
    for label in common_labels:
        if label in metadata["normalized_labels"]:
            info = metadata["normalized_labels"][label]
            lines.append(f"- {label}: {info['description']}")
            if info.get("concept_examples"):
                lines.append(f"  Examples: {', '.join(info['concept_examples'][:2])}")
    lines.append("")

    lines.append("## BUSINESS RULES\n")
    for rule in metadata["business_rules"]:
        lines.append(f"- {rule}")
    lines.append("")

    lines.append("## SAMPLE QUERIES\n")
    for i, sample in enumerate(metadata["sample_queries"][:6], 1):
        lines.append(f"{i}. Question: {sample['question']}")
        lines.append(f"   SQL: {sample['sql']}")
        lines.append("")

    return "\n".join(lines)
