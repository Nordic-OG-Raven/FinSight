-- Test queries demonstrating taxonomy normalization

-- 1. Revenue comparison across ALL companies (US-GAAP + IFRS)
SELECT 
    company, 
    MAX(value_numeric) / 1e9 as revenue_billions,
    COUNT(*) as revenue_facts
FROM financial_facts
WHERE normalized_label = 'revenue' 
  AND period_type = 'duration'
  AND value_numeric IS NOT NULL
GROUP BY company
ORDER BY revenue_billions DESC;

-- 2. Key metrics for all companies
WITH metrics AS (
    SELECT 
        company,
        fiscal_year_end,
        normalized_label,
        MAX(value_numeric) as value_numeric
    FROM financial_facts
    WHERE normalized_label IN ('revenue', 'net_income', 'total_assets', 'stockholders_equity')
      AND value_numeric IS NOT NULL
    GROUP BY company, fiscal_year_end, normalized_label
)
SELECT 
    company,
    fiscal_year_end,
    MAX(CASE WHEN normalized_label = 'revenue' THEN value_numeric END) / 1e9 as revenue_B,
    MAX(CASE WHEN normalized_label = 'net_income' THEN value_numeric END) / 1e9 as net_income_B,
    MAX(CASE WHEN normalized_label = 'total_assets' THEN value_numeric END) / 1e9 as assets_B,
    MAX(CASE WHEN normalized_label = 'stockholders_equity' THEN value_numeric END) / 1e9 as equity_B
FROM metrics
GROUP BY company, fiscal_year_end
HAVING MAX(CASE WHEN normalized_label = 'revenue' THEN value_numeric END) IS NOT NULL
ORDER BY revenue_B DESC;

-- 3. Profit margin comparison
WITH metrics AS (
    SELECT 
        company,
        fiscal_year_end,
        normalized_label,
        MAX(value_numeric) as value
    FROM financial_facts
    WHERE normalized_label IN ('revenue', 'net_income')
      AND value_numeric IS NOT NULL
    GROUP BY company, fiscal_year_end, normalized_label
)
SELECT 
    company,
    fiscal_year_end,
    MAX(CASE WHEN normalized_label = 'revenue' THEN value END) / 1e9 as revenue_B,
    MAX(CASE WHEN normalized_label = 'net_income' THEN value END) / 1e9 as net_income_B,
    100.0 * MAX(CASE WHEN normalized_label = 'net_income' THEN value END) 
        / NULLIF(MAX(CASE WHEN normalized_label = 'revenue' THEN value END), 0) as profit_margin_pct
FROM metrics
GROUP BY company, fiscal_year_end
HAVING MAX(CASE WHEN normalized_label = 'revenue' THEN value END) IS NOT NULL
  AND MAX(CASE WHEN normalized_label = 'net_income' THEN value END) IS NOT NULL
ORDER BY profit_margin_pct DESC;
