{{ config(materialized='view') }}

-- Conform bronze.raw_facts: type-cast, attach the filing's form + as-of date, derive the
-- reporting currency and a USD value (ECB rates via the fx_rates seed, "latest rate on or
-- before the fact's period date"), tag core lines with a canonical-label candidate, and derive
-- a RELIABLE fiscal year.
--
-- Why derive fiscal year: edgartools' per-filing `fiscal_year` tag is unreliable for the annual
-- comparatives inside a 10-K for off-December filers (e.g. NVDA's Jan year-end 10-K tagged two
-- different year-ends as "2026"). We instead derive it from the period-end date relative to the
-- company's fiscal-year-end month: FY = year(end) + (1 if month(end) > FYE_month else 0). That
-- is correct for annual periods AND quarters across Sep (AAPL), Jun (MSFT), Jan (NVDA) and Dec
-- filers alike.

with f as (
    select
        rf.ticker,
        rf.accession,
        fl.form,
        fl.period_of_report,
        rf.concept,
        split_part(rf.concept, ':', 1)                          as taxonomy,
        rf.label,
        rf.standard_label,
        rf.value_numeric,
        rf.value_text,
        rf.unit,
        rf.period_type,
        rf.period_start,
        rf.period_end,
        rf.instant_date,
        rf.fiscal_year                                          as fiscal_year_reported,
        rf.fiscal_period,
        rf.statement_type,
        rf.dimensions,
        rf.dimension_hash,
        rf.is_dimensioned,
        case when rf.period_type = 'duration'
             then (rf.period_end - rf.period_start) end         as period_days,
        case when rf.unit ~ '^[A-Z]{3}$' then rf.unit end       as currency,
        coalesce(rf.period_end, rf.instant_date)                as fx_date,
        coalesce(rf.period_end, rf.instant_date)                as fy_anchor_date
    from {{ source('bronze', 'raw_facts') }} rf
    join {{ source('bronze', 'raw_filings') }} fl using (accession)
),

-- fiscal-year-end month per company = the modal month of its full-year period ends
fye as (
    select ticker,
           mode() within group (order by extract(month from period_end)::int) as fye_month
    from f
    where period_type = 'duration' and period_days between 330 and 380
    group by ticker
),

with_fx as (
    select
        f.*,
        case
            when f.value_numeric is null then null
            when f.currency is null or f.currency = 'USD' then f.value_numeric
            else f.value_numeric * fx.rate_to_usd
        end as value_usd,
        (f.currency is not null and f.currency <> 'USD' and fx.rate_to_usd is null) as fx_unconvertible
    from f
    left join lateral (
        select r.rate_to_usd
        from {{ ref('fx_rates') }} r
        where r.currency = f.currency
          and r.rate_date <= f.fx_date
        order by r.rate_date desc
        limit 1
    ) fx on (f.currency is not null and f.currency <> 'USD')
)

select
    wf.*,
    fye.fye_month,
    case when wf.fy_anchor_date is not null then
        extract(year from wf.fy_anchor_date)::int
        + case when extract(month from wf.fy_anchor_date) > fye.fye_month then 1 else 0 end
    end as fiscal_year,
    cl.canonical_label as canonical_candidate,
    cl.priority        as canonical_priority
from with_fx wf
left join fye on fye.ticker = wf.ticker
left join {{ ref('canonical_labels') }} cl on cl.concept = wf.concept
