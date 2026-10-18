-- Common-reporting-currency normalization (PRD §2.3): store each fact's value in USD alongside
-- the native value_numeric, which is never overwritten. Populated by the loader via ECB rates
-- at the fact's period date (see database/fx_rates.py). For USD and non-currency facts
-- (shares, ratios) value_usd == value_numeric; for foreign-currency facts it is the converted
-- amount; NULL when no rate could be resolved.
ALTER TABLE fact_financial_metrics ADD COLUMN IF NOT EXISTS value_usd numeric;
