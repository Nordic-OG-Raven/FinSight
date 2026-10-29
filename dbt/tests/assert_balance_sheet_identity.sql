-- The reported balance-sheet identity (Assets = Liabilities + Equity) — the loader's hard gate
-- (src/validation/quality.py, BALANCE_TOL = 0.01) re-expressed as a dbt data test on the gold
-- layer. Fails (returns rows) for any company-year whose reported balance sheet doesn't balance
-- within 1%, using the same relative-error definition (|a-b| / max(|a|,|b|,1)).

with bs as (
    select
        ticker,
        fiscal_year,
        max(value_usd) filter (where canonical_label = 'total_assets')                   as assets,
        max(value_usd) filter (where canonical_label = 'total_liabilities_and_equity')   as liab_eq
    from {{ ref('company_financials') }}
    group by ticker, fiscal_year
)

select
    ticker,
    fiscal_year,
    assets,
    liab_eq,
    abs(assets - liab_eq) / greatest(abs(assets), abs(liab_eq), 1) as rel_error
from bs
where assets is not null
  and liab_eq is not null
  and abs(assets - liab_eq) / greatest(abs(assets), abs(liab_eq), 1) > 0.01
