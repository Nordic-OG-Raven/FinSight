-- ============================================================================
-- Production Database Migration Script
-- Run this on Railway PostgreSQL to update schema for latest changes
-- Safe to run multiple times (uses IF NOT EXISTS checks)
-- ============================================================================

-- 1. Add preferred_label column to dim_concepts (if missing)
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'dim_concepts' 
        AND column_name = 'preferred_label'
    ) THEN
        ALTER TABLE dim_concepts ADD COLUMN preferred_label VARCHAR(500);
        CREATE INDEX IF NOT EXISTS idx_concepts_preferred_label ON dim_concepts(preferred_label);
        RAISE NOTICE 'Added preferred_label column to dim_concepts';
    ELSE
        RAISE NOTICE 'preferred_label column already exists';
    END IF;
END $$;

-- 2. Add side column to rel_statement_items (if missing)
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'rel_statement_items' 
        AND column_name = 'side'
    ) THEN
        ALTER TABLE rel_statement_items ADD COLUMN side VARCHAR(20) CHECK (side IN ('assets', 'liabilities_equity'));
        RAISE NOTICE 'Added side column to rel_statement_items';
    ELSE
        RAISE NOTICE 'side column already exists in rel_statement_items';
    END IF;
END $$;

-- 3. Add side column to fact_balance_sheet (if missing)
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'fact_balance_sheet' 
        AND column_name = 'side'
    ) THEN
        ALTER TABLE fact_balance_sheet ADD COLUMN side VARCHAR(20) CHECK (side IN ('assets', 'liabilities_equity'));
        RAISE NOTICE 'Added side column to fact_balance_sheet';
    ELSE
        RAISE NOTICE 'side column already exists in fact_balance_sheet';
    END IF;
END $$;

-- 4. Create fact_equity_statement table (if missing)
CREATE TABLE IF NOT EXISTS fact_equity_statement (
    equity_statement_id SERIAL PRIMARY KEY,
    filing_id INTEGER NOT NULL REFERENCES dim_filings(filing_id) ON DELETE CASCADE,
    concept_id INTEGER NOT NULL REFERENCES dim_concepts(concept_id) ON DELETE CASCADE,
    period_id INTEGER NOT NULL REFERENCES dim_time_periods(period_id) ON DELETE CASCADE,
    value_numeric NUMERIC(20, 2),
    unit_measure VARCHAR(20),
    display_order INTEGER NOT NULL,
    is_header BOOLEAN DEFAULT FALSE,
    hierarchy_level INTEGER,
    parent_concept_id INTEGER REFERENCES dim_concepts(concept_id) ON DELETE SET NULL,
    equity_component VARCHAR(50),  -- 'share_capital', 'treasury_shares', 'retained_earnings', 'other_reserves', NULL for totals
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(filing_id, concept_id, period_id, equity_component)
);

-- Create indexes for fact_equity_statement
CREATE INDEX IF NOT EXISTS idx_equity_statement_filing ON fact_equity_statement(filing_id);
CREATE INDEX IF NOT EXISTS idx_equity_statement_concept ON fact_equity_statement(concept_id);
CREATE INDEX IF NOT EXISTS idx_equity_statement_period ON fact_equity_statement(period_id);
CREATE INDEX IF NOT EXISTS idx_equity_statement_component ON fact_equity_statement(equity_component);
CREATE INDEX IF NOT EXISTS idx_equity_statement_order ON fact_equity_statement(filing_id, display_order);

-- 5. Verify fiscal_year_end exists in dim_filings (should already exist, but check)
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'dim_filings' 
        AND column_name = 'fiscal_year_end'
    ) THEN
        ALTER TABLE dim_filings ADD COLUMN fiscal_year_end DATE NOT NULL DEFAULT CURRENT_DATE;
        RAISE NOTICE 'Added fiscal_year_end column to dim_filings';
    ELSE
        RAISE NOTICE 'fiscal_year_end column already exists in dim_filings';
    END IF;
END $$;

-- 6. Summary: Show what was migrated
SELECT 
    'Migration complete. Verify tables and columns:' as status,
    (SELECT COUNT(*) FROM information_schema.columns WHERE table_name = 'dim_concepts' AND column_name = 'preferred_label') as has_preferred_label,
    (SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'fact_equity_statement') as has_equity_table,
    (SELECT COUNT(*) FROM information_schema.columns WHERE table_name = 'rel_statement_items' AND column_name = 'side') as has_side_column;

