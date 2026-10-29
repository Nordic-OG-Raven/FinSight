{{ config(materialized='table') }}

-- Forecasting-ready quarterly earnings: one wide row per (company, fiscal quarter) with the
-- headline figures in USD and a monotonic quarter_index for time-series models. This is the
-- table the forecasting notebook/models read.

with p as (
    select
        ticker,
        fiscal_year,
        fiscal_period,
        quarter_num,
        quarter_end,
        max(value_usd) filter (where canonical_label = 'revenue')          as revenue_usd,
        max(value_usd) filter (where canonical_label = 'net_income')       as net_income_usd,
        max(value_usd) filter (where canonical_label = 'operating_income') as operating_income_usd,
        max(value_usd) filter (where canonical_label = 'eps_diluted')      as eps_diluted,
        bool_or(is_derived)                                                as is_derived
    from {{ ref('company_quarterly') }}
    group by ticker, fiscal_year, fiscal_period, quarter_num, quarter_end
),

-- Split-adjust EPS to a current-share basis: divide by the product of every split ratio that
-- occurred AFTER the quarter ended (those splits retroactively shrank per-share values). Dollar
-- metrics (revenue, net income) are split-immune and left untouched. Postgres has no product
-- aggregate, so product = exp(sum(ln(ratio))).
with_split_factor as (
    select
        p.*,
        (
            select coalesce(exp(sum(ln(ca.split_ratio))), 1.0)
            from {{ source('bronze', 'corporate_actions') }} ca
            where ca.ticker = p.ticker
              and ca.action_type = 'split'
              and ca.action_date > p.quarter_end
        ) as split_factor
    from p
)

select
    ticker,
    fiscal_year,
    fiscal_period,
    quarter_num,
    quarter_end,
    revenue_usd,
    net_income_usd,
    operating_income_usd,
    eps_diluted,                                 -- as originally reported
    eps_diluted / nullif(split_factor, 0) as eps_diluted_adj,  -- on current-share basis
    split_factor,
    is_derived,
    (fiscal_year * 4 + quarter_num) as quarter_index,
    row_number() over (partition by ticker order by fiscal_year, quarter_num) as seq
from with_split_factor
