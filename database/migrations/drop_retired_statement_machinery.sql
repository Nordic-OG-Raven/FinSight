-- Drop the retired statement-reconstruction / ELT-staging machinery.
--
-- These tables belonged to the custom Arelle pipeline's presentation layer and ELT staging.
-- The edgartools re-architecture (docs/REARCHITECTURE.md) serves statements warehouse-direct
-- from fact_financial_metrics (GET /api/financials/<ticker>), so they are unused and empty.
-- The endpoints that read them (/api/statements, /api/populate-statements) are deprecated to
-- HTTP 410 in the same change.
--
-- Safe to drop: all eight are empty and nothing in the live path references them. CASCADE
-- covers any leftover dependent object.

DROP TABLE IF EXISTS fact_income_statement       CASCADE;
DROP TABLE IF EXISTS fact_balance_sheet          CASCADE;
DROP TABLE IF EXISTS fact_cash_flow              CASCADE;
DROP TABLE IF EXISTS fact_comprehensive_income   CASCADE;
DROP TABLE IF EXISTS fact_equity_statement       CASCADE;
DROP TABLE IF EXISTS rel_statement_overrides     CASCADE;
DROP TABLE IF EXISTS dim_statement_templates     CASCADE;
DROP TABLE IF EXISTS staging_facts               CASCADE;
