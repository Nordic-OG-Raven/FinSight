-- Expose value_usd (USD-normalized amount) on v_facts_consolidated so NP2SQL / ad-hoc queries
-- can compare foreign filers (e.g. NVO in DKK) against USD filers. Appended to the existing
-- view definition; native value_numeric is unchanged.
CREATE OR REPLACE VIEW v_facts_consolidated AS
 SELECT f.fact_id, c.ticker, co.concept_name, co.normalized_label, t.fiscal_year,
    t.period_type, t.start_date, t.end_date, t.instant_date, f.value_numeric, f.value_text,
    f.unit_measure, fi.filing_type, fi.fiscal_year_end, f.context_id,
    CASE WHEN f.dimension_id IS NULL THEN 'true_consolidated'::text
         WHEN d.axis_name = 'ContextAxis'::text THEN 'synthetic_consolidated'::text
         ELSE 'dimensional'::text END AS consolidation_type,
    f.value_usd
   FROM fact_financial_metrics f
     JOIN dim_companies c ON f.company_id = c.company_id
     JOIN dim_concepts co ON f.concept_id = co.concept_id
     JOIN dim_time_periods t ON f.period_id = t.period_id
     JOIN dim_filings fi ON f.filing_id = fi.filing_id
     LEFT JOIN dim_xbrl_dimensions d ON f.dimension_id = d.dimension_id
  WHERE f.dimension_id IS NULL OR (f.dimension_id IS NOT NULL AND d.axis_name = 'ContextAxis'::text);
