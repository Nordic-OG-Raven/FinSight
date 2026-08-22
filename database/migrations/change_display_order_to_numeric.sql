-- Migration: Change display_order from INTEGER to NUMERIC to support decimal values
-- This allows headers to use display_order = min_order_index - 0.5 to appear before their children

-- Update rel_statement_items
ALTER TABLE rel_statement_items 
ALTER COLUMN display_order TYPE NUMERIC(10,2) USING display_order::NUMERIC(10,2);

COMMENT ON COLUMN rel_statement_items.display_order IS 
'Corrected order (handles EPS, headers, etc.) - NUMERIC to support decimal values (e.g., 0.5 for headers)';

-- Update fact_income_statement
ALTER TABLE fact_income_statement 
ALTER COLUMN display_order TYPE NUMERIC(10,2) USING display_order::NUMERIC(10,2);

-- Update fact_balance_sheet
ALTER TABLE fact_balance_sheet 
ALTER COLUMN display_order TYPE NUMERIC(10,2) USING display_order::NUMERIC(10,2);

-- Update fact_cash_flow
ALTER TABLE fact_cash_flow 
ALTER COLUMN display_order TYPE NUMERIC(10,2) USING display_order::NUMERIC(10,2);

-- Update fact_comprehensive_income
ALTER TABLE fact_comprehensive_income 
ALTER COLUMN display_order TYPE NUMERIC(10,2) USING display_order::NUMERIC(10,2);

-- Update fact_equity_statement
ALTER TABLE fact_equity_statement 
ALTER COLUMN display_order TYPE NUMERIC(10,2) USING display_order::NUMERIC(10,2);

