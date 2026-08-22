-- Migration: Add label_role column to dim_concepts
-- Purpose: Store XBRL label roles (documentation role indicates headers)
-- Date: 2025-01-XX

-- Add label_role column if it doesn't exist
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'dim_concepts' 
        AND column_name = 'label_role'
    ) THEN
        ALTER TABLE dim_concepts 
        ADD COLUMN label_role VARCHAR(200);
        
        COMMENT ON COLUMN dim_concepts.label_role IS 
        'XBRL label role (e.g., documentation role indicates headers)';
    END IF;
END $$;

