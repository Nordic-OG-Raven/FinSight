-- Migration: Add preferred_label column to dim_concepts
-- This stores human-readable labels from XBRL taxonomy or generic mappings
-- Safe to run multiple times (IF NOT EXISTS checks)

DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'dim_concepts' 
        AND column_name = 'preferred_label'
    ) THEN
        ALTER TABLE dim_concepts ADD COLUMN preferred_label VARCHAR(500);
        CREATE INDEX IF NOT EXISTS idx_concepts_preferred_label ON dim_concepts(preferred_label);
    END IF;
END $$;

