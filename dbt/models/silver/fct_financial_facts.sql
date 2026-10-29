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
)

select
    ticker,
    accession,
    form,
    period_of_report,
    concept,
    taxonomy,
    label,
    standard_label,
    case when canon_rank = 1 and is_dimensioned = false then canonical_candidate end as canonical_label,
    value_numeric,
    value_text,
    currency,
    value_usd,
    fx_unconvertible,
    unit,
    period_type,
    period_start,
    period_end,
    instant_date,
    period_days,
    fiscal_year,
    fiscal_year_reported,
    fiscal_period,
    statement_type,
    dimensions,
    dimension_hash,
    is_dimensioned
from canonical_ranked
