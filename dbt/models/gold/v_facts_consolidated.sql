{{ config(materialized='view') }}

-- Consolidated (non-dimensioned) facts: the canonical "one row per consolidated fact" surface,
-- consumed by the NP2SQL endpoint. This used to be a materialized TABLE duplicating ~95 MB of
-- fct_financial_facts; it is now a lightweight VIEW over the already-materialized
-- gold.v_facts_hierarchical, filtered to non-dimensioned rows. Row-for-row and value identical to
-- the old table (verified). It stays fast because v_facts_hierarchical carries a partial index
-- idx_vfh_ticker_year (ticker, fiscal_year) WHERE NOT is_dimensioned, which the NP2SQL lookups hit.
-- (This is a filtered projection over an indexed table, NOT the per-row jsonb pattern that forced
-- v_facts_hierarchical itself to be a table.)

select
    ticker,
    concept_name,
    taxonomy,
    normalized_label,
    standard_label,
    statement_type,
    fiscal_year,
    fiscal_period,
    period_type,
    period_grain,
    start_date,
    end_date,
    instant_date,
    value_numeric,
    value_usd,
    value_text,
    unit_measure,
    filing_type,
    fiscal_year_end
from {{ ref('v_facts_hierarchical') }}
where is_dimensioned = false
