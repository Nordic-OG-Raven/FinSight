{{ config(materialized='view') }}

-- Richer denormalized serving view (reproduces legacy public.v_facts_hierarchical + the columns
-- the API joined dim_xbrl_dimensions for). Includes BOTH consolidated and dimensional facts, with
-- the dimension axis/member embedded so the API needs no join. Consumed by /api/metrics,
-- /api/data, /api/analyze, /api/financials.

select
    f.ticker,
    f.concept                                         as concept_name,
    f.taxonomy,
    {{ normalized_label('f.concept', 'f.canonical_label') }} as normalized_label,
    f.standard_label,
    coalesce(f.label, f.concept)                      as preferred_label,
    f.statement_type,
    f.fiscal_year,
    f.fiscal_period,
    f.period_type,
    f.period_start                                    as start_date,
    f.period_end                                      as end_date,
    f.instant_date,
    (f.fiscal_year::text || ' ' || coalesce(f.fiscal_period, f.period_type)) as period_label,
    f.value_numeric,
    f.value_usd,
    f.value_text,
    f.unit                                            as unit_measure,
    f.form                                            as filing_type,
    f.period_of_report                                as fiscal_year_end,
    f.is_dimensioned,
    f.dimension_hash,
    f.dimensions                                      as dimension_json,
    -- axis/member derived from the dimensions jsonb (mirror of the legacy dim_xbrl_dimensions cols)
    (select string_agg(k, ', ' order by k) from jsonb_object_keys(f.dimensions) k) as axis_name,
    (select string_agg(v.value, ', ') from jsonb_each_text(f.dimensions) v)         as member_name,
    null::integer                                     as hierarchy_level
from {{ ref('fct_financial_facts') }} f
