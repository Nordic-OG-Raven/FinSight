{{ config(materialized='view') }}

-- Serving view reproducing the legacy public.v_facts_consolidated shape (consolidated facts
-- only), sourced from the medallion. Consumed by the NP2SQL endpoint and as the canonical
-- "one row per consolidated fact" surface.

select
    f.ticker,
    f.concept                                         as concept_name,
    f.taxonomy,
    {{ normalized_label('f.concept', 'f.canonical_label') }} as normalized_label,
    f.standard_label,
    f.statement_type,
    f.fiscal_year,
    f.fiscal_period,
    f.period_type,
    f.period_grain,  -- 'annual'|'quarter'|'ytd_or_other'|'instant'(year-end)|'quarter_instant'
    f.period_start                                    as start_date,
    f.period_end                                      as end_date,
    f.instant_date,
    f.value_numeric,
    f.value_usd,
    f.value_text,
    f.unit                                            as unit_measure,
    f.form                                            as filing_type,
    f.period_of_report                                as fiscal_year_end
from {{ ref('fct_financial_facts') }} f
where f.is_dimensioned = false
