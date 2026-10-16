"""
SQL export queries for the FinSight data warehouse (star schema).

Pre-built, parameterized queries for common export scenarios, over
`fact_financial_metrics` joined to its dimensions. Fetch one by name with `get_query(name)`
and run it with psycopg2 (`%s` placeholders). Consolidated (undimensioned) facts only, so
segment breakdowns don't double-count totals.

`period_end` is COALESCE(end_date, instant_date) — instant (balance-sheet) facts carry their
date in `instant_date`. Metric names are the canonical labels from
`src/extraction/canonical_labels.py`.
"""

# Export all facts for a single company (by ticker)
EXPORT_COMPANY = """
SELECT
    c.ticker AS company,
    fi.filing_type,
    fi.fiscal_year_end,
    co.concept_name AS concept,
    f.normalized_label,
    co.taxonomy,
    f.value_text,
    f.value_numeric,
    f.period_type,
    COALESCE(t.end_date, t.instant_date) AS period_end,
    f.unit_measure
FROM fact_financial_metrics f
JOIN dim_companies c ON f.company_id = c.company_id
JOIN dim_concepts co ON f.concept_id = co.concept_id
JOIN dim_time_periods t ON f.period_id = t.period_id
JOIN dim_filings fi ON f.filing_id = fi.filing_id
WHERE c.ticker = %s
  AND f.dimension_id IS NULL
ORDER BY period_end DESC, co.concept_name;
"""

# Export specific normalized metrics across all companies
EXPORT_CONCEPTS_CROSS_COMPANY = """
SELECT
    c.ticker AS company,
    fi.fiscal_year_end,
    co.concept_name AS concept,
    f.normalized_label,
    f.value_numeric,
    f.unit_measure,
    COALESCE(t.end_date, t.instant_date) AS period_end
FROM fact_financial_metrics f
JOIN dim_companies c ON f.company_id = c.company_id
JOIN dim_concepts co ON f.concept_id = co.concept_id
JOIN dim_time_periods t ON f.period_id = t.period_id
JOIN dim_filings fi ON f.filing_id = fi.filing_id
WHERE f.normalized_label = ANY(%s)
  AND f.value_numeric IS NOT NULL
  AND f.dimension_id IS NULL
ORDER BY f.normalized_label, c.ticker, period_end DESC;
"""

# Export a set of normalized metrics (same as cross-company; kept for the named API)
EXPORT_BY_STATEMENT_TYPE = EXPORT_CONCEPTS_CROSS_COMPANY

# Export a time series for one metric between two dates
EXPORT_TIME_SERIES = """
SELECT
    c.ticker AS company,
    COALESCE(t.end_date, t.instant_date) AS period_end,
    f.value_numeric,
    f.unit_measure
FROM fact_financial_metrics f
JOIN dim_companies c ON f.company_id = c.company_id
JOIN dim_time_periods t ON f.period_id = t.period_id
WHERE f.normalized_label = %s
  AND f.value_numeric IS NOT NULL
  AND f.dimension_id IS NULL
  AND COALESCE(t.end_date, t.instant_date) >= %s
  AND COALESCE(t.end_date, t.instant_date) <= %s
ORDER BY c.ticker, period_end;
"""

# Latest value of each requested metric, per company
EXPORT_LATEST_COMPARISON = """
WITH ranked AS (
    SELECT
        c.ticker AS company,
        f.normalized_label,
        f.value_numeric,
        f.unit_measure,
        COALESCE(t.end_date, t.instant_date) AS period_end,
        ROW_NUMBER() OVER (
            PARTITION BY c.ticker, f.normalized_label
            ORDER BY COALESCE(t.end_date, t.instant_date) DESC
        ) AS rn
    FROM fact_financial_metrics f
    JOIN dim_companies c ON f.company_id = c.company_id
    JOIN dim_time_periods t ON f.period_id = t.period_id
    WHERE f.normalized_label = ANY(%s)
      AND f.value_numeric IS NOT NULL
      AND f.dimension_id IS NULL
)
SELECT company, normalized_label, value_numeric, unit_measure, period_end
FROM ranked
WHERE rn = 1
ORDER BY normalized_label, company;
"""

# Key-metrics dashboard: latest value of each core line, one row per company
EXPORT_KEY_METRICS = """
WITH latest AS (
    SELECT
        c.ticker AS company,
        fi.fiscal_year_end,
        f.normalized_label,
        f.value_numeric,
        ROW_NUMBER() OVER (
            PARTITION BY c.ticker, f.normalized_label
            ORDER BY COALESCE(t.end_date, t.instant_date) DESC
        ) AS rn
    FROM fact_financial_metrics f
    JOIN dim_companies c ON f.company_id = c.company_id
    JOIN dim_time_periods t ON f.period_id = t.period_id
    JOIN dim_filings fi ON f.filing_id = fi.filing_id
    WHERE f.normalized_label IN (
        'revenue', 'net_income', 'total_assets', 'total_equity',
        'operating_income', 'net_cash_from_operating_activities', 'eps_basic', 'eps_diluted'
    )
    AND f.value_numeric IS NOT NULL
    AND f.dimension_id IS NULL
)
SELECT
    company,
    fiscal_year_end,
    MAX(CASE WHEN normalized_label = 'revenue' THEN value_numeric END) AS revenue,
    MAX(CASE WHEN normalized_label = 'net_income' THEN value_numeric END) AS net_income,
    MAX(CASE WHEN normalized_label = 'total_assets' THEN value_numeric END) AS total_assets,
    MAX(CASE WHEN normalized_label = 'total_equity' THEN value_numeric END) AS total_equity,
    MAX(CASE WHEN normalized_label = 'operating_income' THEN value_numeric END) AS operating_income,
    MAX(CASE WHEN normalized_label = 'net_cash_from_operating_activities' THEN value_numeric END) AS operating_cash_flow,
    MAX(CASE WHEN normalized_label = 'eps_basic' THEN value_numeric END) AS eps_basic,
    MAX(CASE WHEN normalized_label = 'eps_diluted' THEN value_numeric END) AS eps_diluted
FROM latest
WHERE rn = 1
GROUP BY company, fiscal_year_end
ORDER BY revenue DESC NULLS LAST;
"""

# Per-company data-quality summary
EXPORT_DATA_QUALITY = """
SELECT
    c.ticker AS company,
    COUNT(*) AS total_facts,
    COUNT(DISTINCT co.concept_name) AS unique_concepts,
    COUNT(CASE WHEN f.value_numeric IS NOT NULL THEN 1 END) AS numeric_facts,
    MAX(fi.fiscal_year_end) AS latest_period,
    STRING_AGG(DISTINCT fi.filing_type, ', ') AS filing_types
FROM fact_financial_metrics f
JOIN dim_companies c ON f.company_id = c.company_id
JOIN dim_concepts co ON f.concept_id = co.concept_id
JOIN dim_filings fi ON f.filing_id = fi.filing_id
GROUP BY c.ticker
ORDER BY c.ticker;
"""


def get_query(query_name):
    """Get a pre-built query by name ('company', 'concepts', 'statement', 'time_series',
    'comparison', 'key_metrics', 'quality')."""
    queries = {
        'company': EXPORT_COMPANY,
        'concepts': EXPORT_CONCEPTS_CROSS_COMPANY,
        'statement': EXPORT_BY_STATEMENT_TYPE,
        'time_series': EXPORT_TIME_SERIES,
        'comparison': EXPORT_LATEST_COMPARISON,
        'key_metrics': EXPORT_KEY_METRICS,
        'quality': EXPORT_DATA_QUALITY,
    }
    return queries.get(query_name)
