-- ============================================================================
-- Migration: Add rel_statement_items table (Approach 2)
-- Purpose: Pre-compute statement-level metadata to simplify API queries
-- ============================================================================

-- Create rel_statement_items table
CREATE TABLE IF NOT EXISTS rel_statement_items (
    statement_item_id SERIAL PRIMARY KEY,
    filing_id INTEGER NOT NULL REFERENCES dim_filings(filing_id) ON DELETE CASCADE,
    concept_id INTEGER NOT NULL REFERENCES dim_concepts(concept_id) ON DELETE CASCADE,
    statement_type VARCHAR(50) NOT NULL,  -- income_statement, balance_sheet, etc.
    display_order INTEGER NOT NULL,  -- Corrected order (handles EPS, headers, etc.)
    is_header BOOLEAN DEFAULT FALSE,
    is_main_item BOOLEAN DEFAULT TRUE,  -- Main statement item (not detail/disclosure)
    role_uri VARCHAR(500),  -- For reference (from presentation hierarchy)
    source VARCHAR(20),  -- 'xbrl' or 'standard'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(filing_id, concept_id, statement_type)
);

-- Create indexes for performance
CREATE INDEX idx_statement_items_filing ON rel_statement_items(filing_id);
CREATE INDEX idx_statement_items_concept ON rel_statement_items(concept_id);
CREATE INDEX idx_statement_items_type_order ON rel_statement_items(statement_type, display_order);
CREATE INDEX idx_statement_items_main ON rel_statement_items(filing_id, is_main_item, statement_type, display_order);

-- Add comment
COMMENT ON TABLE rel_statement_items IS 'Pre-computed statement-level metadata: which concepts belong to which statements, their display order, and whether they are main items or headers. Populated during ETL to simplify API queries.';

