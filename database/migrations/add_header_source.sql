-- Migration: Add header_source column to rel_statement_items
-- Purpose: Track the source of headers (XBRL parent-child, label role, template, or synthetic)
-- Date: 2025-01-XX

-- Add header_source column if it doesn't exist
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'rel_statement_items' 
        AND column_name = 'header_source'
    ) THEN
        ALTER TABLE rel_statement_items 
        ADD COLUMN header_source VARCHAR(20) CHECK (header_source IN ('xbrl_parent', 'xbrl_label_role', 'template', 'synthetic'));
        
        COMMENT ON COLUMN rel_statement_items.header_source IS 
        'Source of header: xbrl_parent (from parent-child relationship), xbrl_label_role (from label linkbase), template (standard template), synthetic (manually created), NULL (not a header)';
    END IF;
END $$;

