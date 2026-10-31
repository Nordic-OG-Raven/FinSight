-- Every quarter-grain fact must carry a real quarter label (Q1-Q4). The raw filing's fiscal_period
-- tag is BLANK for 52/53-week filers' 14-week quarters (e.g. AAPL / AVGO fiscal-Q1 of a 53-week
-- year). An unlabeled quarter silently drops out of the quarterly marts — which is exactly what
-- dropped AAPL FY2023 Q1 and corrupted its derived Q4. fct_financial_facts now DERIVES the label
-- (quarter-end vs fiscal-year-end month); this test is the standing guard so the class can't recur.
-- Fails (returns rows) for any quarter-grain fact without a Q1-Q4 label.

select ticker, fiscal_year, period_end, period_days, fiscal_period
from {{ ref('fct_financial_facts') }}
where period_grain = 'quarter'
  and (fiscal_period is null or fiscal_period not in ('Q1', 'Q2', 'Q3', 'Q4'))
