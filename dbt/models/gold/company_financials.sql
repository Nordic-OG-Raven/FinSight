{{ config(
    materialized='table',
    post_hook="create index if not exists idx_cf_ticker_year on {{ this }} (ticker, fiscal_year)"
) }}

-- Annual serving mart: one row per (company, fiscal year, canonical line) in USD and native.
-- Mirrors how src/analysis/ratios.load_metrics reads the warehouse (undimensioned core lines,
-- annual durations ~1y or fiscal-year-end instants), so ratios/peers reproduce exactly.

select distinct on (f.ticker, f.fiscal_year, f.canonical_label)
    f.ticker,
    f.fiscal_year,
    f.canonical_label,
    f.value_usd,
    f.value_numeric as value_native,
    f.currency,
    f.statement_type,
    f.period_end,
    f.instant_date
from {{ ref('fct_financial_facts') }} f
where f.canonical_label is not null
  and f.is_dimensioned = false
  and f.value_numeric is not null
  -- annual flows (~1y durations) + ONLY the fiscal-year-end balance-sheet instant
  -- (period_grain already excludes the quarter-end instants that 10-Qs contribute)
  and f.period_grain in ('annual', 'instant')
-- if a (company, year, line) still has >1 candidate, keep the largest-magnitude value
order by f.ticker, f.fiscal_year, f.canonical_label, abs(f.value_numeric) desc
