-- Every COMPLETED fiscal year (one that has an annual revenue figure filed) must expose all four
-- quarters in the quarterly series. A missing quarter means a labeling/derivation gap like the one
-- that dropped AAPL FY2023 Q1 (which left only 2 of 4 quarters and poisoned the derived Q4 +
-- the forecast base). This is a RECONCILIATION-by-completeness guard, complementing
-- assert_quarter_facts_labeled.
--
-- Scope: only years strictly after a company's first quarter-bearing year, so we don't flag the
-- earliest partially-ingested year or annual-only foreign filers (e.g. NVO, which reports no
-- quarters). In-progress years have no annual yet and are excluded by the `completed` join.
-- Fails (returns rows) for any in-scope completed year missing any of Q1-Q4.

with completed as (
    select distinct ticker, fiscal_year
    from {{ ref('fct_financial_facts') }}
    where period_grain = 'annual' and canonical_label = 'revenue'
),

qtr as (
    select ticker, fiscal_year, count(distinct fiscal_period) as n_q
    from {{ ref('company_quarterly') }}
    where canonical_label = 'revenue' and fiscal_period in ('Q1', 'Q2', 'Q3', 'Q4')
    group by ticker, fiscal_year
),

first_q as (  -- first fiscal year we actually have quarterly coverage for this company
    select ticker, min(fiscal_year) as first_q_year
    from qtr
    group by ticker
)

select c.ticker, c.fiscal_year, coalesce(q.n_q, 0) as n_quarters
from completed c
join first_q fq on fq.ticker = c.ticker
left join qtr q on q.ticker = c.ticker and q.fiscal_year = c.fiscal_year
where c.fiscal_year > fq.first_q_year
  and coalesce(q.n_q, 0) < 4
