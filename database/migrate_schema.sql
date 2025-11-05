-- Safe migration: Add missing columns to dim_concepts
-- This script checks if columns exist before adding them
-- Run this via Railway dashboard SQL editor or psql connection

-- Add hierarchy_level if missing
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'dim_concepts' 
        AND column_name = 'hierarchy_level'
    ) THEN
        ALTER TABLE dim_concepts ADD COLUMN hierarchy_level INTEGER;
        RAISE NOTICE 'Added hierarchy_level column';
    ELSE
        RAISE NOTICE 'hierarchy_level column already exists';
    END IF;
END $$;

-- Add parent_concept_id if missing
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'dim_concepts' 
        AND column_name = 'parent_concept_id'
    ) THEN
        ALTER TABLE dim_concepts ADD COLUMN parent_concept_id INTEGER REFERENCES dim_concepts(concept_id) ON DELETE SET NULL;
        RAISE NOTICE 'Added parent_concept_id column';
    ELSE
        RAISE NOTICE 'parent_concept_id column already exists';
    END IF;
END $$;

-- Add is_calculated if missing
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'dim_concepts' 
        AND column_name = 'is_calculated'
    ) THEN
        ALTER TABLE dim_concepts ADD COLUMN is_calculated BOOLEAN DEFAULT FALSE;
        RAISE NOTICE 'Added is_calculated column';
    ELSE
        RAISE NOTICE 'is_calculated column already exists';
    END IF;
END $$;

-- Add calculation_weight if missing
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'dim_concepts' 
        AND column_name = 'calculation_weight'
    ) THEN
        ALTER TABLE dim_concepts ADD COLUMN calculation_weight DECIMAL(10,4) DEFAULT 1.0;
        RAISE NOTICE 'Added calculation_weight column';
    ELSE
        RAISE NOTICE 'calculation_weight column already exists';
    END IF;
END $$;

-- Add statement_type if missing (some older schemas might not have it)
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'dim_concepts' 
        AND column_name = 'statement_type'
    ) THEN
        ALTER TABLE dim_concepts ADD COLUMN statement_type VARCHAR(50);
        RAISE NOTICE 'Added statement_type column';
    ELSE
        RAISE NOTICE 'statement_type column already exists';
    END IF;
END $$;

-- Create indexes if they don't exist
CREATE INDEX IF NOT EXISTS idx_concepts_hierarchy_level ON dim_concepts(hierarchy_level);
CREATE INDEX IF NOT EXISTS idx_concepts_parent ON dim_concepts(parent_concept_id);
CREATE INDEX IF NOT EXISTS idx_concepts_statement ON dim_concepts(statement_type);

-- Verify: Show current columns
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'dim_concepts'
ORDER BY ordinal_position;

