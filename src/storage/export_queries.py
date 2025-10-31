"""
SQL export queries for FinSight data warehouse.

Provides pre-built queries for common export scenarios.
"""

# Export all facts for a single company
EXPORT_COMPANY = """
SELECT 
    company,
    filing_type,
    fiscal_year_end,
    concept,
    normalized_label,
    taxonomy,
    value_text,
    value_numeric,
    period_type,
    period_end,
    unit_measure
FROM financial_facts
WHERE company = %s
ORDER BY period_end DESC, concept;
"""

# Export specific concepts across all companies
EXPORT_CONCEPTS_CROSS_COMPANY = """
SELECT 
    company,
    fiscal_year_end,
    concept,
    normalized_label,
    value_numeric,
    unit_measure,
    period_end
FROM financial_facts
WHERE normalized_label = ANY(%s)
  AND value_numeric IS NOT NULL
ORDER BY normalized_label, company, period_end DESC;
"""

# Export by statement type (requires taxonomy mapping)
EXPORT_BY_STATEMENT_TYPE = """
SELECT 
    company,
    fiscal_year_end,
    concept,
    normalized_label,
    value_numeric,
    unit_measure,
    period_type,
    period_end
FROM financial_facts
WHERE normalized_label = ANY(%s)
  AND value_numeric IS NOT NULL
ORDER BY company, period_end DESC;
"""

# Export time series for specific metric
EXPORT_TIME_SERIES = """
SELECT 
    company,
    period_end,
    value_numeric,
    unit_measure
FROM financial_facts
WHERE normalized_label = %s
  AND value_numeric IS NOT NULL
  AND period_end >= %s
  AND period_end <= %s
ORDER BY company, period_end;
"""

# Export latest period comparison across companies
EXPORT_LATEST_COMPARISON = """
WITH ranked AS (
    SELECT 
        company,
        normalized_label,
        value_numeric,
        unit_measure,
        period_end,
        ROW_NUMBER() OVER (PARTITION BY company, normalized_label ORDER BY period_end DESC) as rn
    FROM financial_facts
    WHERE normalized_label = ANY(%s)
      AND value_numeric IS NOT NULL
)
SELECT 
    company,
    normalized_label,
    value_numeric,
    unit_measure,
    period_end
FROM ranked
WHERE rn = 1
ORDER BY normalized_label, company;
"""

# Export key metrics dashboard data
EXPORT_KEY_METRICS = """
WITH latest_periods AS (
    SELECT 
        company,
        fiscal_year_end,
        normalized_label,
        value_numeric,
        period_end,
        ROW_NUMBER() OVER (PARTITION BY company, normalized_label ORDER BY period_end DESC) as rn
    FROM financial_facts
    WHERE normalized_label IN (
        'revenue', 'net_income', 'total_assets', 'stockholders_equity',
        'operating_income', 'operating_cash_flow', 'eps_basic', 'eps_diluted'
    )
    AND value_numeric IS NOT NULL
)
SELECT 
    company,
    fiscal_year_end,
    MAX(CASE WHEN normalized_label = 'revenue' THEN value_numeric END) as revenue,
    MAX(CASE WHEN normalized_label = 'net_income' THEN value_numeric END) as net_income,
    MAX(CASE WHEN normalized_label = 'total_assets' THEN value_numeric END) as total_assets,
    MAX(CASE WHEN normalized_label = 'stockholders_equity' THEN value_numeric END) as equity,
    MAX(CASE WHEN normalized_label = 'operating_income' THEN value_numeric END) as operating_income,
    MAX(CASE WHEN normalized_label = 'operating_cash_flow' THEN value_numeric END) as operating_cash_flow,
    MAX(CASE WHEN normalized_label = 'eps_basic' THEN value_numeric END) as eps_basic,
    MAX(CASE WHEN normalized_label = 'eps_diluted' THEN value_numeric END) as eps_diluted
FROM latest_periods
WHERE rn = 1
GROUP BY company, fiscal_year_end
ORDER BY revenue DESC NULLS LAST;
"""

# Export data quality summary
EXPORT_DATA_QUALITY = """
SELECT 
    company,
    COUNT(*) as total_facts,
    COUNT(DISTINCT concept) as unique_concepts,
    COUNT(CASE WHEN normalized_label IS NOT NULL THEN 1 END) as normalized_facts,
    ROUND(100.0 * COUNT(CASE WHEN normalized_label IS NOT NULL THEN 1 END) / COUNT(*), 2) as normalization_pct,
    COUNT(CASE WHEN value_numeric IS NOT NULL THEN 1 END) as numeric_facts,
    MAX(fiscal_year_end) as latest_period,
    STRING_AGG(DISTINCT filing_type, ', ') as filing_types
FROM financial_facts
GROUP BY company
ORDER BY company;
"""


def get_query(query_name):
    """
    Get a pre-built query by name.
    
    Args:
        query_name: Name of the query (e.g., 'company', 'concepts', 'time_series')
    
    Returns:
        SQL query string
    """
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

