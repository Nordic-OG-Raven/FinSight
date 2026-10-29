{{ config(materialized='table') }}

-- Annual serving mart: one row per (company, fiscal year, canonical line) in USD and native.
-- Mirrors how src/analysis/ratios.load_metrics reads the warehouse (undimensioned core lines,
-- annual durations ~1y or fiscal-year-end instants), so ratios/peers reproduce exactly.

select distinct on (ticker, fiscal_year, canonical_label)
    ticker,
    fiscal_year,
    canonical_label,
    value_usd,
    value_numeric as value_native,
    currency,
    statement_type,
    period_end,
    instant_date
from {{ ref('fct_financial_facts') }}
where canonical_label is not null
  and is_dimensioned = false
  and value_numeric is not null
  and (period_type = 'instant' or period_days between 330 and 380)
-- if a (company, year, line) still has >1 candidate, keep the largest-magnitude value
order by ticker, fiscal_year, canonical_label, abs(value_numeric) desc
