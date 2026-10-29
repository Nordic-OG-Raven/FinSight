{{ config(materialized='table') }}

-- Quarterly series per company (USD) for the forecasting marts.
--
-- 10-Qs report Q1-Q3 as discrete ~90-day periods; Q4 is never filed on its own (it lives in
-- the 10-K). So we take the reported quarters and DERIVE Q4 = annual - (Q1+Q2+Q3) for additive
-- flow metrics, only when exactly the three quarters are present. EPS Q4 is the same subtraction
-- (an approximation — EPS isn't strictly additive — hence is_derived flags it).

{% set flow_metrics = "('revenue','net_income','operating_income','net_cash_from_operating_activities','eps_diluted')" %}

with reported as (
    select
        ticker,
        fiscal_year,
        fiscal_period,
        canonical_label,
        period_end                           as quarter_end,
        value_usd,
        case fiscal_period when 'Q1' then 1 when 'Q2' then 2 when 'Q3' then 3 when 'Q4' then 4 end as quarter_num
    from {{ ref('fct_financial_facts') }}
    where canonical_label in {{ flow_metrics }}
      and is_dimensioned = false
      and period_type = 'duration'
      and period_days between 80 and 100
      and value_numeric is not null
      and fiscal_period in ('Q1', 'Q2', 'Q3', 'Q4')
),

fy_end as (  -- fiscal-year-end date per (company, fiscal year), for dating a derived Q4
    select ticker, fiscal_year, max(period_end) as fy_end_date
    from {{ ref('fct_financial_facts') }}
    where is_dimensioned = false and period_type = 'duration' and period_days between 330 and 380
    group by ticker, fiscal_year
),

annual as (
    select ticker, fiscal_year, canonical_label, value_usd as fy_value
    from {{ ref('company_financials') }}
    where canonical_label in {{ flow_metrics }}
),

three_q as (
    select ticker, fiscal_year, canonical_label, sum(value_usd) as sum_q, count(*) as n_q
    from reported
    where quarter_num in (1, 2, 3)
    group by ticker, fiscal_year, canonical_label
),

derived_q4 as (
    select
        a.ticker,
        a.fiscal_year,
        'Q4'                      as fiscal_period,
        a.canonical_label,
        fe.fy_end_date            as quarter_end,
        a.fy_value - t.sum_q      as value_usd,
        4                         as quarter_num
    from annual a
    join three_q t on t.ticker = a.ticker and t.fiscal_year = a.fiscal_year
                   and t.canonical_label = a.canonical_label and t.n_q = 3
    left join fy_end fe on fe.ticker = a.ticker and fe.fiscal_year = a.fiscal_year
    -- don't double-count a quarter the filer happened to report directly as Q4
    where not exists (
        select 1 from reported r
        where r.ticker = a.ticker and r.fiscal_year = a.fiscal_year
          and r.canonical_label = a.canonical_label and r.quarter_num = 4
    )
)

select ticker, fiscal_year, fiscal_period, quarter_num, canonical_label, quarter_end,
       value_usd, false as is_derived
from reported
union all
select ticker, fiscal_year, fiscal_period, quarter_num, canonical_label, quarter_end,
       value_usd, true as is_derived
from derived_q4
