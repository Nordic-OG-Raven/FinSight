{{ config(materialized='table') }}

-- Annual financial ratios in USD, a SQL port of src/analysis/ratios.compute_ratios so the
-- serving layer is self-contained in the warehouse (the Python module can read this mart
-- instead of recomputing). Margins/ratios are unit-free; absolute figures are USD.

with w as (
    select
        ticker,
        fiscal_year,
        max(value_usd) filter (where canonical_label = 'revenue')                            as revenue,
        max(value_usd) filter (where canonical_label = 'gross_profit')                       as gross_profit,
        max(value_usd) filter (where canonical_label = 'operating_income')                   as operating_income,
        max(value_usd) filter (where canonical_label = 'income_before_income_taxes')         as pretax_income,
        max(value_usd) filter (where canonical_label = 'income_tax_expense')                 as income_tax,
        max(value_usd) filter (where canonical_label = 'net_income')                         as net_income,
        max(value_usd) filter (where canonical_label = 'total_assets')                       as total_assets,
        max(value_usd) filter (where canonical_label = 'current_assets')                     as current_assets,
        max(value_usd) filter (where canonical_label = 'total_liabilities')                  as total_liabilities,
        max(value_usd) filter (where canonical_label = 'current_liabilities')                as current_liabilities,
        max(value_usd) filter (where canonical_label = 'total_equity')                       as total_equity,
        max(value_usd) filter (where canonical_label = 'net_cash_from_operating_activities') as operating_cash_flow,
        max(value_usd) filter (where canonical_label = 'capital_expenditures')               as capex
    from {{ ref('company_financials') }}
    group by ticker, fiscal_year
),

growth as (
    select *,
        case when lag(fiscal_year) over (partition by ticker order by fiscal_year) = fiscal_year - 1
             then lag(revenue) over (partition by ticker order by fiscal_year) end as prior_revenue
    from w
)

select
    ticker,
    fiscal_year,
    revenue                                         as revenue_usd,
    net_income                                      as net_income_usd,
    total_assets                                    as total_assets_usd,
    total_equity                                    as total_equity_usd,
    gross_profit        / nullif(revenue, 0)        as gross_margin,
    operating_income    / nullif(revenue, 0)        as operating_margin,
    net_income          / nullif(revenue, 0)        as net_margin,
    net_income          / nullif(total_equity, 0)   as return_on_equity,
    net_income          / nullif(total_assets, 0)   as return_on_assets,
    current_assets      / nullif(current_liabilities, 0) as current_ratio,
    total_liabilities   / nullif(total_equity, 0)   as debt_to_equity,
    revenue             / nullif(total_assets, 0)   as asset_turnover,
    income_tax          / nullif(pretax_income, 0)  as effective_tax_rate,
    (operating_cash_flow - abs(capex))              as free_cash_flow_usd,
    (operating_cash_flow - abs(capex)) / nullif(revenue, 0) as fcf_margin,
    revenue / nullif(prior_revenue, 0) - 1          as revenue_growth
from growth
