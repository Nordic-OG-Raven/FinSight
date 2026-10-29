{{ config(materialized='view') }}

-- The conformed fact grain. Two conformance steps:
--  1. Dedup across filings. The same period's facts recur in multiple filings (a 10-K carries
--     prior-year comparatives; each 10-Q carries the prior-year comparative quarter). Keep one
--     row per economic fact, from the most-recently-filed source.
--  2. Resolve the canonical label. A core economic line (e.g. "revenue") can be tagged with
--     several synonymous concepts; assign the canonical label to the single highest-priority
--     UNDIMENSIONED concept per (company, period) so the line reconciles 1:1. Everyone else
--     keeps raw (canonical_label = NULL) — nothing is dropped.

with staged as (
    select * from {{ ref('stg_facts') }}
),

deduped as (
    select *,
        row_number() over (
            partition by ticker, concept, period_type, period_start, period_end, instant_date,
                         coalesce(dimension_hash, '')
            order by period_of_report desc nulls last, accession desc
        ) as rn
    from staged
),

one_per_fact as (
    select * from deduped where rn = 1
),

canonical_ranked as (
    select *,
        -- is_dimensioned is in the partition key so undimensioned facts rank only against each
        -- other; dimensioned (segment) facts never claim a canonical line.
        case when canonical_candidate is not null then
            row_number() over (
                partition by ticker, canonical_candidate, is_dimensioned,
                             period_type, period_start, period_end, instant_date
                order by canonical_priority asc, concept
            )
        end as canon_rank
    from one_per_fact
),

-- fiscal-year-end date per (company, year) from the annual income/cash-flow durations, so an
-- instant can be tagged as the YEAR-END balance vs a quarter-end balance (10-Qs contribute the
-- latter, and all of a year's quarter-end instants share that fiscal_year).
fye as (
    -- a TRUE annual period is ~1y AND ends in the company's fiscal-year-end month; this excludes
    -- trailing-twelve-month (TTM/LTM) durations 10-Qs report (e.g. AMZN's 364-day period ending
    -- in June), which are ~1y but aren't the fiscal year.
    select ticker, fiscal_year, max(period_end) as fye_date
    from canonical_ranked
    where period_type = 'duration' and period_days between 330 and 380
      and extract(month from period_end)::int = fye_month
    group by ticker, fiscal_year
)

select
    cr.ticker,
    cr.accession,
    cr.form,
    cr.period_of_report,
    cr.concept,
    cr.taxonomy,
    cr.label,
    cr.standard_label,
    case when cr.canon_rank = 1 and cr.is_dimensioned = false then cr.canonical_candidate end as canonical_label,
    cr.value_numeric,
    cr.value_text,
    cr.currency,
    cr.value_usd,
    cr.fx_unconvertible,
    cr.unit,
    cr.period_type,
    cr.period_start,
    cr.period_end,
    cr.instant_date,
    cr.period_days,
    cr.fiscal_year,
    cr.fiscal_year_reported,
    cr.fiscal_period,
    cr.statement_type,
    -- period grain: annual flows, single quarters, YTD rollups, fiscal-year-end vs quarter-end instants
    case
        when cr.period_type = 'duration' and cr.period_days between 330 and 380
             and extract(month from cr.period_end)::int = cr.fye_month then 'annual'
        when cr.period_type = 'duration' and cr.period_days between 80 and 100 then 'quarter'
        when cr.period_type = 'duration' then 'ytd_or_other'  -- incl. TTM/LTM and YTD rollups
        when cr.period_type = 'instant' and cr.instant_date = fye.fye_date then 'instant'
        when cr.period_type = 'instant' then 'quarter_instant'
    end as period_grain,
    cr.dimensions,
    cr.dimension_hash,
    cr.is_dimensioned
from canonical_ranked cr
left join fye on fye.ticker = cr.ticker and fye.fiscal_year = cr.fiscal_year
