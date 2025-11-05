-- ============================================================================
-- Calculated Total Views for Missing Universal Metrics
-- ============================================================================
-- These views calculate totals from components when companies don't report
-- them as single line items (especially IFRS companies).

-- Drop existing views if recreating
DROP VIEW IF EXISTS v_calculated_totals CASCADE;

-- ============================================================================
-- VIEW: Calculated totals from components
-- ============================================================================
-- Purpose: Provide calculated totals for companies that only report components
-- Example: SNY revenue = RevenueFromSaleOfGoods + OtherRevenue
--          IFRS total_liabilities = current_liabilities + noncurrent_liabilities

CREATE VIEW v_calculated_totals AS
WITH calculated_revenue AS (
    -- SNY: RevenueFromSaleOfGoods + OtherRevenue = Total Revenue
    SELECT 
        f1.company_id,
        f1.filing_id,
        f1.period_id,
        f1.dimension_id,
        'revenue' as calculated_metric,
        (COALESCE(f1.value_numeric, 0) + COALESCE(f2.value_numeric, 0)) as calculated_value,
        f1.unit_measure,
        f1.fiscal_year,
        'RevenueFromSaleOfGoods + OtherRevenue' as calculation_formula
    FROM fact_financial_metrics f1
    JOIN dim_companies c ON f1.company_id = c.company_id
    JOIN dim_concepts dc1 ON f1.concept_id = dc1.concept_id
    JOIN fact_financial_metrics f2 ON f1.company_id = f2.company_id 
        AND f1.period_id = f2.period_id 
        AND f1.dimension_id IS NOT DISTINCT FROM f2.dimension_id
    JOIN dim_concepts dc2 ON f2.concept_id = dc2.concept_id
    JOIN dim_time_periods t ON f1.period_id = t.period_id
    WHERE c.ticker = 'SNY'
      AND dc1.concept_name = 'RevenueFromSaleOfGoods'
      AND dc2.concept_name = 'OtherRevenue'
      AND f1.dimension_id IS NULL
      AND f2.dimension_id IS NULL
      AND dc1.normalized_label != 'revenue'  -- Only if not already mapped
      AND dc2.normalized_label != 'revenue'
),

calculated_total_liabilities AS (
    -- IFRS companies: current_liabilities + noncurrent_liabilities
    SELECT 
        f1.company_id,
        f1.filing_id,
        f1.period_id,
        f1.dimension_id,
        'total_liabilities' as calculated_metric,
        (COALESCE(f1.value_numeric, 0) + COALESCE(f2.value_numeric, 0)) as calculated_value,
        f1.unit_measure,
        f1.fiscal_year,
        'current_liabilities + noncurrent_liabilities' as calculation_formula
    FROM fact_financial_metrics f1
    JOIN dim_companies c ON f1.company_id = c.company_id
    JOIN dim_concepts dc1 ON f1.concept_id = dc1.concept_id
    JOIN fact_financial_metrics f2 ON f1.company_id = f2.company_id 
        AND f1.period_id = f2.period_id 
        AND f1.dimension_id IS NOT DISTINCT FROM f2.dimension_id
    JOIN dim_concepts dc2 ON f2.concept_id = dc2.concept_id
    JOIN dim_time_periods t ON f1.period_id = t.period_id
    WHERE c.ticker IN ('KO', 'LLY', 'SNY')
      AND dc1.normalized_label = 'current_liabilities'
      AND dc2.normalized_label = 'noncurrent_liabilities'
      AND f1.dimension_id IS NULL
      AND f2.dimension_id IS NULL
      -- Only calculate if total_liabilities doesn't already exist
      AND NOT EXISTS (
          SELECT 1 
          FROM fact_financial_metrics f3
          JOIN dim_concepts dc3 ON f3.concept_id = dc3.concept_id
          WHERE f3.company_id = f1.company_id
            AND f3.period_id = f1.period_id
            AND dc3.normalized_label = 'total_liabilities'
            AND f3.dimension_id IS NULL
      )
),

calculated_gross_profit AS (
    -- Gross Profit = Revenue - Cost of Revenue
    SELECT 
        f1.company_id,
        f1.filing_id,
        f1.period_id,
        f1.dimension_id,
        'gross_profit' as calculated_metric,
        (COALESCE(f1.value_numeric, 0) - COALESCE(f2.value_numeric, 0)) as calculated_value,
        f1.unit_measure,
        f1.fiscal_year,
        'revenue - cost_of_revenue' as calculation_formula
    FROM fact_financial_metrics f1
    JOIN dim_companies c ON f1.company_id = c.company_id
    JOIN dim_concepts dc1 ON f1.concept_id = dc1.concept_id
    JOIN fact_financial_metrics f2 ON f1.company_id = f2.company_id 
        AND f1.period_id = f2.period_id 
        AND f1.dimension_id IS NOT DISTINCT FROM f2.dimension_id
    JOIN dim_concepts dc2 ON f2.concept_id = dc2.concept_id
    JOIN dim_time_periods t ON f1.period_id = t.period_id
    WHERE c.ticker IN ('GOOGL', 'LLY', 'MRNA', 'PFE')
      AND dc1.normalized_label = 'revenue'
      AND dc2.normalized_label = 'cost_of_revenue'
      AND f1.dimension_id IS NULL
      AND f2.dimension_id IS NULL
      -- Only calculate if gross_profit doesn't already exist
      AND NOT EXISTS (
          SELECT 1 
          FROM fact_financial_metrics f3
          JOIN dim_concepts dc3 ON f3.concept_id = dc3.concept_id
          WHERE f3.company_id = f1.company_id
            AND f3.period_id = f1.period_id
            AND dc3.normalized_label = 'gross_profit'
            AND f3.dimension_id IS NULL
      )
)

-- Union all calculated totals
SELECT * FROM calculated_revenue
UNION ALL
SELECT * FROM calculated_total_liabilities
UNION ALL
SELECT * FROM calculated_gross_profit;

-- ============================================================================
-- VIEW: Universal metrics with calculated totals (for UI queries)
-- ============================================================================
-- This view merges actual facts with calculated totals, providing
-- complete coverage for universal metrics.

CREATE VIEW v_universal_metrics_complete AS
SELECT 
    c.ticker as company,
    dc.normalized_label as metric,
    t.fiscal_year,
    f.value_numeric as value,
    f.unit_measure,
    f.dimension_id,
    'actual' as source_type
FROM fact_financial_metrics f
JOIN dim_companies c ON f.company_id = c.company_id
JOIN dim_concepts dc ON f.concept_id = dc.concept_id
JOIN dim_time_periods t ON f.period_id = t.period_id
WHERE dc.normalized_label IN (
    'revenue', 'net_income', 'operating_income', 'gross_profit',
    'total_assets', 'total_liabilities', 'stockholders_equity',
    'current_assets', 'current_liabilities', 'cash_and_equivalents',
    'accounts_receivable', 'accounts_payable', 'inventory',
    'property_plant_equipment', 'long_term_debt', 'operating_cash_flow'
)
AND f.dimension_id IS NULL

UNION ALL

-- Add calculated totals
SELECT 
    c.ticker as company,
    ct.calculated_metric as metric,
    ct.fiscal_year,
    ct.calculated_value as value,
    ct.unit_measure,
    ct.dimension_id,
    'calculated' as source_type
FROM v_calculated_totals ct
JOIN dim_companies c ON ct.company_id = c.company_id;

-- Grant access
GRANT SELECT ON v_calculated_totals TO superset;
GRANT SELECT ON v_universal_metrics_complete TO superset;

SELECT 'Calculated totals views created successfully' AS status;

