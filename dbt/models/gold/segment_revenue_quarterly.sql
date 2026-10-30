{{ config(
    materialized='table',
    post_hook="create index if not exists idx_srq_ticker on {{ this }} (ticker, fiscal_year)"
) }}

-- Clean quarterly segment REVENUE (latest-vintage) for the forecasting layer.
--
-- Dimensioned revenue facts on the business-segments axis, with member synonyms canonicalized
-- via the segment_members seed (e.g. NVDA renamed ComputeAndNetworkingMember ->
-- ComputeAndNetworkingSegmentMember across filings — both map to one segment). Only the
-- operating-segment total per quarter is kept (exactly the ConsolidationItems + BusinessSegments
-- dims, no finer product/geography sub-breakdown), and synonyms are deduped so a segment-quarter
-- appears once.
--
-- This is the "best current view" (silver dedup = latest filing). The LEAKAGE-SAFE backtest does
-- NOT use this — it reads bronze with filing_date, because silver's latest-vintage dedup discards
-- the as-originally-reported value needed for point-in-time.

with seg_facts as (
    select
        f.ticker,
        sm.segment,
        sm.segment_label,
        sm.structure,
        f.fiscal_year,
        f.fiscal_period,
        f.period_end                                  as quarter_end,
        f.value_usd                                   as revenue_usd,
        f.value_numeric                               as revenue_native,
        f.accession
    from {{ ref('fct_financial_facts') }} f
    join {{ ref('segment_members') }} sm
      on sm.ticker = f.ticker
     and sm.member = f.dimensions ->> 'us-gaap_StatementBusinessSegmentsAxis'
    where f.is_dimensioned
      and split_part(f.concept, ':', 2) like 'Revenue%'
      and f.period_type = 'duration'
      and f.period_days between 80 and 100                      -- discrete quarters
      and f.value_numeric is not null
      -- operating-segment total only: just the segment (+ consolidation-items) dims,
      -- not a finer segment x product/geography sub-breakdown
      and (select count(*) from jsonb_object_keys(f.dimensions)) <= 2
)

-- dedup synonym members (same segment+quarter via two member names) to one row
select distinct on (ticker, segment, fiscal_year, fiscal_period)
    ticker, segment, segment_label, structure,
    fiscal_year, fiscal_period, quarter_end,
    revenue_usd, revenue_native, accession
from seg_facts
order by ticker, segment, fiscal_year, fiscal_period, abs(revenue_native) desc
