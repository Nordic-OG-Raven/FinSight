"""
Schema metadata generation for NP2SQL.

This module generates comprehensive database schema documentation
for use in LLM prompts to convert natural language to SQL.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.utils.taxonomy_mappings import CONCEPT_MAPPINGS


def get_schema_metadata() -> dict:
    """
    Generate comprehensive schema metadata for LLM context.
    
    Returns:
        Dictionary containing tables, columns, relationships, mappings, and examples
    """
    
    # Core fact table
    fact_financial_metrics = {
        "name": "fact_financial_metrics",
        "description": "Core fact table containing all financial metrics with full dimensional context. This is the primary table for querying financial data.",
        "columns": {
            "fact_id": {"type": "SERIAL PRIMARY KEY", "description": "Unique fact identifier"},
            "company_id": {"type": "INTEGER FK", "description": "References dim_companies - identifies which company"},
            "concept_id": {"type": "INTEGER FK", "description": "References dim_concepts - identifies the financial concept/metric"},
            "period_id": {"type": "INTEGER FK", "description": "References dim_time_periods - identifies the time period"},
            "filing_id": {"type": "INTEGER FK", "description": "References dim_filings - identifies the source filing"},
            "dimension_id": {"type": "INTEGER FK", "description": "References dim_xbrl_dimensions - NULL for consolidated totals, non-NULL for segment/breakdown data"},
            "normalized_label": {"type": "VARCHAR(200)", "description": "Standardized label for cross-company queries (e.g., 'revenue', 'net_income', 'total_assets'). Use this for filtering by metric type."},
            "fiscal_year": {"type": "INTEGER", "description": "Fiscal year (denormalized for performance)"},
            "period_type": {"type": "VARCHAR(20)", "description": "Period type: 'instant' (point in time) or 'duration' (period of time)"},
            "value_numeric": {"type": "DOUBLE PRECISION", "description": "Numeric value of the financial metric"},
            "value_text": {"type": "TEXT", "description": "Text value for non-numeric facts"},
            "unit_measure": {"type": "VARCHAR(50)", "description": "Unit of measure (e.g., 'USD', 'shares', 'pure')"},
            "currency_id": {"type": "INTEGER FK", "description": "References dim_currencies"},
            "scale_int": {"type": "INTEGER", "description": "Scale factor (e.g., 6 for millions, 3 for thousands)"},
            "is_gaap": {"type": "BOOLEAN", "description": "Whether this is GAAP or non-GAAP metric"},
            "is_calculated": {"type": "BOOLEAN", "description": "Whether value was calculated from children (not in original filing)"},
        },
        "business_rules": [
            "dimension_id IS NULL means consolidated (total) value for the company",
            "dimension_id IS NOT NULL means segment/breakdown value",
            "For most queries, filter by dimension_id IS NULL to get consolidated figures",
            "normalized_label is the key field for querying specific metrics across companies",
            "fiscal_year and period_type are denormalized for easier filtering",
        ],
        "common_joins": [
            "JOIN dim_companies c ON fact_financial_metrics.company_id = c.company_id",
            "JOIN dim_concepts co ON fact_financial_metrics.concept_id = co.concept_id",
            "JOIN dim_time_periods t ON fact_financial_metrics.period_id = t.period_id",
            "JOIN dim_filings f ON fact_financial_metrics.filing_id = f.filing_id",
        ],
    }
    
    # Denormalized fact tables (easier for specific statement queries)
    fact_income_statement = {
        "name": "fact_income_statement",
        "description": "Pre-filtered income statement items with display order. Use for income statement-specific queries.",
        "columns": {
            "income_statement_id": {"type": "SERIAL PRIMARY KEY", "description": "Unique identifier"},
            "filing_id": {"type": "INTEGER FK", "description": "References dim_filings"},
            "concept_id": {"type": "INTEGER FK", "description": "References dim_concepts"},
            "period_id": {"type": "INTEGER FK", "description": "References dim_time_periods"},
            "value_numeric": {"type": "NUMERIC(20,2)", "description": "Numeric value"},
            "unit_measure": {"type": "VARCHAR(20)", "description": "Unit of measure"},
            "display_order": {"type": "INTEGER", "description": "Order in which item appears in statement"},
            "is_header": {"type": "BOOLEAN", "description": "Whether this is a section header"},
            "hierarchy_level": {"type": "INTEGER", "description": "Hierarchy level (1=detail, 2=subtotal, etc.)"},
        },
    }
    
    fact_balance_sheet = {
        "name": "fact_balance_sheet",
        "description": "Pre-filtered balance sheet items with display order and side (assets vs liabilities_equity).",
        "columns": {
            "balance_sheet_id": {"type": "SERIAL PRIMARY KEY", "description": "Unique identifier"},
            "filing_id": {"type": "INTEGER FK", "description": "References dim_filings"},
            "concept_id": {"type": "INTEGER FK", "description": "References dim_concepts"},
            "period_id": {"type": "INTEGER FK", "description": "References dim_time_periods"},
            "value_numeric": {"type": "NUMERIC(20,2)", "description": "Numeric value"},
            "unit_measure": {"type": "VARCHAR(20)", "description": "Unit of measure"},
            "display_order": {"type": "INTEGER", "description": "Order in which item appears"},
            "side": {"type": "VARCHAR(20)", "description": "'assets' or 'liabilities_equity'"},
            "is_header": {"type": "BOOLEAN", "description": "Whether this is a section header"},
        },
    }
    
    fact_cash_flow = {
        "name": "fact_cash_flow",
        "description": "Pre-filtered cash flow statement items with display order.",
        "columns": {
            "cash_flow_id": {"type": "SERIAL PRIMARY KEY", "description": "Unique identifier"},
            "filing_id": {"type": "INTEGER FK", "description": "References dim_filings"},
            "concept_id": {"type": "INTEGER FK", "description": "References dim_concepts"},
            "period_id": {"type": "INTEGER FK", "description": "References dim_time_periods"},
            "value_numeric": {"type": "NUMERIC(20,2)", "description": "Numeric value"},
            "unit_measure": {"type": "VARCHAR(20)", "description": "Unit of measure"},
            "display_order": {"type": "INTEGER", "description": "Order in which item appears"},
        },
    }
    
    # Dimension tables
    dim_companies = {
        "name": "dim_companies",
        "description": "Company dimension table. Contains company identifiers and metadata.",
        "columns": {
            "company_id": {"type": "SERIAL PRIMARY KEY", "description": "Unique company identifier"},
            "ticker": {"type": "VARCHAR(20)", "description": "Stock ticker symbol (e.g., 'AAPL', 'MSFT', 'NVO') - use this for filtering by company"},
            "company_name": {"type": "VARCHAR(200)", "description": "Full company name"},
            "cik": {"type": "VARCHAR(20)", "description": "SEC CIK number"},
            "sector": {"type": "VARCHAR(100)", "description": "Company sector"},
            "industry": {"type": "VARCHAR(100)", "description": "Company industry"},
            "country": {"type": "VARCHAR(3)", "description": "Country code"},
            "accounting_standard": {"type": "VARCHAR(20)", "description": "Accounting standard (US-GAAP or IFRS)"},
        },
    }
    
    dim_concepts = {
        "name": "dim_concepts",
        "description": "XBRL concepts dimension. Maps concept names to normalized labels.",
        "columns": {
            "concept_id": {"type": "SERIAL PRIMARY KEY", "description": "Unique concept identifier"},
            "concept_name": {"type": "TEXT", "description": "Original XBRL concept name (e.g., 'RevenueFromContractWithCustomerExcludingAssessedTax')"},
            "taxonomy": {"type": "VARCHAR(50)", "description": "Taxonomy name (e.g., 'us-gaap', 'ifrs-full')"},
            "normalized_label": {"type": "VARCHAR(200)", "description": "Standardized label (e.g., 'revenue') - use this for cross-company queries"},
            "statement_type": {"type": "VARCHAR(50)", "description": "Statement type: 'income_statement', 'balance_sheet', 'cash_flow', etc."},
            "preferred_label": {"type": "VARCHAR(500)", "description": "Human-readable label"},
        },
    }
    
    dim_time_periods = {
        "name": "dim_time_periods",
        "description": "Time periods dimension. Contains fiscal year, quarter, and date information.",
        "columns": {
            "period_id": {"type": "SERIAL PRIMARY KEY", "description": "Unique period identifier"},
            "period_type": {"type": "VARCHAR(20)", "description": "'instant' (point in time) or 'duration' (period)"},
            "start_date": {"type": "DATE", "description": "Period start date"},
            "end_date": {"type": "DATE", "description": "Period end date"},
            "instant_date": {"type": "DATE", "description": "Instant date (for balance sheet items)"},
            "fiscal_year": {"type": "INTEGER", "description": "Fiscal year (e.g., 2024) - use this for filtering by year"},
            "fiscal_quarter": {"type": "INTEGER", "description": "Fiscal quarter (1-4)"},
            "period_label": {"type": "VARCHAR(100)", "description": "Human-readable period label"},
        },
    }
    
    dim_filings = {
        "name": "dim_filings",
        "description": "SEC filings dimension. Contains filing metadata.",
        "columns": {
            "filing_id": {"type": "SERIAL PRIMARY KEY", "description": "Unique filing identifier"},
            "company_id": {"type": "INTEGER FK", "description": "References dim_companies"},
            "filing_type": {"type": "VARCHAR(20)", "description": "Filing type: '10-K', '20-F', '10-Q'"},
            "fiscal_year_end": {"type": "DATE", "description": "Fiscal year end date"},
            "filing_date": {"type": "DATE", "description": "Date filing was submitted"},
        },
    }
    
    # Views
    v_facts_consolidated = {
        "name": "v_facts_consolidated",
        "description": "View of consolidated facts only (dimension_id IS NULL). Use this view for most queries to avoid duplicate segment data.",
        "columns": {
            "fact_id": {"type": "INTEGER", "description": "Fact identifier"},
            "ticker": {"type": "VARCHAR(20)", "description": "Company ticker"},
            "concept_name": {"type": "TEXT", "description": "XBRL concept name"},
            "normalized_label": {"type": "VARCHAR(200)", "description": "Normalized label"},
            "fiscal_year": {"type": "INTEGER", "description": "Fiscal year"},
            "period_type": {"type": "VARCHAR(20)", "description": "Period type"},
            "value_numeric": {"type": "DOUBLE PRECISION", "description": "Numeric value"},
            "unit_measure": {"type": "VARCHAR(50)", "description": "Unit of measure"},
        },
    }
    
    # Normalized label mappings (for LLM to understand metric names)
    normalized_labels = {}
    for normalized_label, concept_names in CONCEPT_MAPPINGS.items():
        normalized_labels[normalized_label] = {
            "description": f"Standardized label for {normalized_label}",
            "concept_examples": concept_names[:3],  # First 3 examples
            "usage": f"Use normalized_label = '{normalized_label}' to query this metric across all companies",
        }
    
    # Sample queries
    sample_queries = [
        {
            "question": "Show me Apple's revenue in 2024",
            "sql": "SELECT value_numeric, unit_measure FROM v_facts_consolidated WHERE ticker = 'AAPL' AND normalized_label = 'revenue' AND fiscal_year = 2024 AND period_type = 'duration'",
        },
        {
            "question": "Compare net income across all companies in 2024",
            "sql": "SELECT ticker, value_numeric FROM v_facts_consolidated WHERE normalized_label = 'net_income' AND fiscal_year = 2024 AND period_type = 'duration' ORDER BY value_numeric DESC",
        },
        {
            "question": "What is Microsoft's total assets in 2023?",
            "sql": "SELECT value_numeric, unit_measure FROM v_facts_consolidated WHERE ticker = 'MSFT' AND normalized_label = 'total_assets' AND fiscal_year = 2023 AND period_type = 'instant'",
        },
        {
            "question": "Show revenue trend for NVIDIA over the last 3 years",
            "sql": "SELECT fiscal_year, value_numeric FROM v_facts_consolidated WHERE ticker = 'NVDA' AND normalized_label = 'revenue' AND period_type = 'duration' AND fiscal_year >= 2022 ORDER BY fiscal_year",
        },
        {
            "question": "Which company has the highest revenue in 2024?",
            "sql": "SELECT ticker, value_numeric FROM v_facts_consolidated WHERE normalized_label = 'revenue' AND fiscal_year = 2024 AND period_type = 'duration' ORDER BY value_numeric DESC LIMIT 1",
        },
    ]
    
    # Company name mappings (for detecting company mentions)
    company_mappings = {
        "AAPL": ["Apple", "Apple Inc", "AAPL"],
        "MSFT": ["Microsoft", "MSFT"],
        "GOOGL": ["Alphabet", "Google", "GOOGL"],
        "NVDA": ["NVIDIA", "NVDA"],
        "NVO": ["Novo Nordisk", "Novo", "NVO"],
        "JNJ": ["Johnson & Johnson", "J&J", "JNJ"],
        "PFE": ["Pfizer", "PFE"],
        "LLY": ["Eli Lilly", "LLY"],
        "MRNA": ["Moderna", "MRNA"],
        "SNY": ["Sanofi", "SNY"],
        "KO": ["Coca-Cola", "Coke", "KO"],
        "AMZN": ["Amazon", "AMZN"],
        "ASML": ["ASML"],
        "BAC": ["Bank of America", "BAC"],
        "CAT": ["Caterpillar", "CAT"],
        "JPM": ["JPMorgan", "JPMorgan Chase", "JPM"],
        "WMT": ["Walmart", "WMT"],
    }
    
    return {
        "tables": {
            "fact_financial_metrics": fact_financial_metrics,
            "fact_income_statement": fact_income_statement,
            "fact_balance_sheet": fact_balance_sheet,
            "fact_cash_flow": fact_cash_flow,
            "dim_companies": dim_companies,
            "dim_concepts": dim_concepts,
            "dim_time_periods": dim_time_periods,
            "dim_filings": dim_filings,
        },
        "views": {
            "v_facts_consolidated": v_facts_consolidated,
        },
        "normalized_labels": normalized_labels,
        "sample_queries": sample_queries,
        "company_mappings": company_mappings,
        "business_rules": [
            "Always use v_facts_consolidated for consolidated queries (avoids duplicate segment data)",
            "Filter by dimension_id IS NULL when querying fact_financial_metrics directly",
            "Use normalized_label for cross-company metric queries",
            "Use ticker from dim_companies for company filtering",
            "Use fiscal_year from dim_time_periods or denormalized fiscal_year for year filtering",
            "period_type = 'duration' for income statement and cash flow (periods of time)",
            "period_type = 'instant' for balance sheet (point in time)",
            "Join dim_companies to get ticker: JOIN dim_companies c ON f.company_id = c.company_id",
        ],
    }


def format_schema_for_llm(metadata: dict) -> str:
    """
    Format schema metadata as a string for LLM prompt.
    
    Args:
        metadata: Schema metadata dictionary
        
    Returns:
        Formatted string for LLM context
    """
    lines = []
    
    lines.append("=== FINANCIAL DATA WAREHOUSE SCHEMA ===\n")
    
    # Tables
    lines.append("## TABLES\n")
    for table_name, table_info in metadata["tables"].items():
        lines.append(f"### {table_name}")
        lines.append(f"Description: {table_info['description']}")
        lines.append("Columns:")
        for col_name, col_info in table_info["columns"].items():
            lines.append(f"  - {col_name} ({col_info['type']}): {col_info['description']}")
        if "business_rules" in table_info:
            lines.append("Business Rules:")
            for rule in table_info["business_rules"]:
                lines.append(f"  - {rule}")
        if "common_joins" in table_info:
            lines.append("Common Joins:")
            for join in table_info["common_joins"]:
                lines.append(f"  - {join}")
        lines.append("")
    
    # Views
    lines.append("## VIEWS\n")
    for view_name, view_info in metadata["views"].items():
        lines.append(f"### {view_name}")
        lines.append(f"Description: {view_info['description']}")
        lines.append("Columns:")
        for col_name, col_info in view_info["columns"].items():
            lines.append(f"  - {col_name} ({col_info['type']}): {col_info['description']}")
        lines.append("")
    
    # Normalized labels (top 20 most common)
    lines.append("## COMMON NORMALIZED LABELS\n")
    common_labels = ["revenue", "net_income", "total_assets", "total_liabilities", "stockholders_equity",
                     "operating_cash_flow", "investing_cash_flow", "financing_cash_flow", "gross_profit",
                     "operating_income", "cost_of_revenue", "research_development", "depreciation_amortization",
                     "earnings_per_share", "shares_outstanding", "total_debt", "cash_and_equivalents"]
    
    for label in common_labels:
        if label in metadata["normalized_labels"]:
            label_info = metadata["normalized_labels"][label]
            lines.append(f"- {label}: {label_info['description']}")
            if label_info.get("concept_examples"):
                lines.append(f"  Examples: {', '.join(label_info['concept_examples'][:2])}")
    lines.append("")
    
    # Business rules
    lines.append("## BUSINESS RULES\n")
    for rule in metadata["business_rules"]:
        lines.append(f"- {rule}")
    lines.append("")
    
    # Sample queries
    lines.append("## SAMPLE QUERIES\n")
    for i, sample in enumerate(metadata["sample_queries"][:5], 1):
        lines.append(f"{i}. Question: {sample['question']}")
        lines.append(f"   SQL: {sample['sql']}")
        lines.append("")
    
    return "\n".join(lines)

