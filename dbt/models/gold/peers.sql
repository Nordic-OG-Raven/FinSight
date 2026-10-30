{{ config(materialized='table') }}

-- Latest-year cross-company snapshot, revenue-sorted (USD) — reproduces /api/peers.

with latest as (
    select ticker, max(fiscal_year) as fiscal_year
    from {{ ref('ratios') }}
    where revenue_usd is not null
    group by ticker
)

select r.*
from {{ ref('ratios') }} r
join latest l on l.ticker = r.ticker and l.fiscal_year = r.fiscal_year
order by r.revenue_usd desc nulls last
