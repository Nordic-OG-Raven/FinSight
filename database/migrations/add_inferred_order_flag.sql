-- Migration: Add inferred_order flag to rel_statement_items
-- Purpose: Track when display_order was inferred from other years (XBRL extraction failed)
-- Date: 2025-01-XX

-- Add inferred_order column if it doesn't exist
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'rel_statement_items' 
        AND column_name = 'inferred_order'
    ) THEN
        ALTER TABLE rel_statement_items 
        ADD COLUMN inferred_order BOOLEAN DEFAULT FALSE;
        
        COMMENT ON COLUMN rel_statement_items.inferred_order IS 
        'TRUE if display_order was inferred from other years (XBRL extraction failed for this filing)';
    END IF;
END $$;

