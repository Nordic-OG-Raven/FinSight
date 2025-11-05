-- Migration: Add hierarchy columns to dim_concepts if they don't exist
-- Safe to run multiple times (IF NOT EXISTS checks)

-- Add hierarchy_level column
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'dim_concepts' 
        AND column_name = 'hierarchy_level'
    ) THEN
        ALTER TABLE dim_concepts ADD COLUMN hierarchy_level INTEGER;
    END IF;
END $$;

-- Add parent_concept_id column
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'dim_concepts' 
        AND column_name = 'parent_concept_id'
    ) THEN
        ALTER TABLE dim_concepts ADD COLUMN parent_concept_id INTEGER REFERENCES dim_concepts(concept_id) ON DELETE SET NULL;
    END IF;
END $$;

-- Add is_calculated column
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'dim_concepts' 
        AND column_name = 'is_calculated'
    ) THEN
        ALTER TABLE dim_concepts ADD COLUMN is_calculated BOOLEAN DEFAULT FALSE;
    END IF;
END $$;

-- Add calculation_weight column
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'dim_concepts' 
        AND column_name = 'calculation_weight'
    ) THEN
        ALTER TABLE dim_concepts ADD COLUMN calculation_weight DECIMAL(10,4) DEFAULT 1.0;
    END IF;
END $$;

-- Add statement_type column if missing
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'dim_concepts' 
        AND column_name = 'statement_type'
    ) THEN
        ALTER TABLE dim_concepts ADD COLUMN statement_type VARCHAR(50);
    END IF;
END $$;

-- Create index on hierarchy_level for performance
CREATE INDEX IF NOT EXISTS idx_concepts_hierarchy_level ON dim_concepts(hierarchy_level);
CREATE INDEX IF NOT EXISTS idx_concepts_parent ON dim_concepts(parent_concept_id);
CREATE INDEX IF NOT EXISTS idx_concepts_statement ON dim_concepts(statement_type);

