{{ config(materialized='view') }}

-- Company/filing metadata for /api/companies. One row per annual filing (matches the legacy
-- annual-only behaviour; quarterly coverage is surfaced by the data/financials endpoints). For
-- an annual filing the fiscal-year label equals the calendar year of its period-of-report date.

select distinct
    rf.ticker,
    rf.company_name,
    rf.form                                       as filing_type,
    extract(year from rf.period_of_report)::int   as fiscal_year,
    null::integer                                 as fiscal_quarter,
    case when rf.form = '10-Q' then 'quarterly' else 'annual' end as reporting_frequency
from {{ source('bronze', 'raw_filings') }} rf
where rf.form in ('10-K', '20-F', '40-F')
  and rf.period_of_report is not null
