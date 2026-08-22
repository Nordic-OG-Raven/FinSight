-- ============================================================================
-- Migration: Add Business Keys to ERD
-- Purpose: Make queries less complex and fragile by adding business keys
-- Date: 2024
-- ============================================================================

-- ============================================================================
-- IMPROVEMENT 1: Add Business Keys to Dimension Tables
-- ============================================================================

-- 1.1: dim_time_periods - Add business_key column and index
ALTER TABLE dim_time_periods 
ADD COLUMN IF NOT EXISTS business_key VARCHAR(50) GENERATED ALWAYS AS (
    CASE 
        WHEN fiscal_year IS NOT NULL AND period_type IS NOT NULL 
        THEN fiscal_year::TEXT || '-' || period_type
        ELSE NULL
    END
) STORED;

-- Index for fast lookups by business key
CREATE INDEX IF NOT EXISTS idx_periods_business_key ON dim_time_periods(business_key);
CREATE INDEX IF NOT EXISTS idx_periods_fiscal_year_type ON dim_time_periods(fiscal_year, period_type);

-- 1.2: dim_concepts - Add unique constraint on normalized_label (business key)
-- First, handle any NULL normalized_labels (they should be rare)
-- Use a temporary unique value to avoid conflicts
DO $$
DECLARE
    null_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO null_count FROM dim_concepts WHERE normalized_label IS NULL;
    IF null_count > 0 THEN
        -- Generate unique temporary labels for NULL values
        UPDATE dim_concepts 
        SET normalized_label = 'UNMAPPED_' || concept_id::TEXT 
        WHERE normalized_label IS NULL;
        RAISE NOTICE 'Updated % concepts with NULL normalized_label', null_count;
    END IF;
END $$;

-- Now add NOT NULL constraint (if column doesn't already have it)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'dim_concepts' 
        AND column_name = 'normalized_label' 
        AND is_nullable = 'YES'
    ) THEN
        ALTER TABLE dim_concepts ALTER COLUMN normalized_label SET NOT NULL;
    END IF;
END $$;

-- Add unique constraint on normalized_label (business key)
-- Drop existing index if it exists (non-unique)
DROP INDEX IF EXISTS idx_concepts_normalized_label;
CREATE UNIQUE INDEX IF NOT EXISTS idx_concepts_normalized_label_unique 
ON dim_concepts(normalized_label);

-- ============================================================================
-- IMPROVEMENT 2: Add Business Keys to Fact Table (Denormalized)
-- ============================================================================

-- 2.1: Add denormalized business key columns to fact_financial_metrics
ALTER TABLE fact_financial_metrics 
ADD COLUMN IF NOT EXISTS normalized_label VARCHAR(200),
ADD COLUMN IF NOT EXISTS fiscal_year INTEGER,
ADD COLUMN IF NOT EXISTS period_type VARCHAR(20);

-- 2.2: Populate denormalized columns from dimension tables
UPDATE fact_financial_metrics fm
SET 
    normalized_label = dc.normalized_label,
    fiscal_year = dt.fiscal_year,
    period_type = dt.period_type
FROM dim_concepts dc, dim_time_periods dt
WHERE fm.concept_id = dc.concept_id
  AND fm.period_id = dt.period_id
  AND (fm.normalized_label IS NULL OR fm.fiscal_year IS NULL OR fm.period_type IS NULL);

-- 2.3: Add NOT NULL constraints after population
ALTER TABLE fact_financial_metrics 
ALTER COLUMN normalized_label SET NOT NULL,
ALTER COLUMN fiscal_year SET NOT NULL,
ALTER COLUMN period_type SET NOT NULL;

-- 2.4: Add unique constraint on business key
-- Drop existing unique constraint first (we'll replace it)
ALTER TABLE fact_financial_metrics 
DROP CONSTRAINT IF EXISTS fact_financial_metrics_filing_id_concept_id_period_id_dimension_id_key;

-- Add new unique constraint using business keys
ALTER TABLE fact_financial_metrics 
ADD CONSTRAINT fact_financial_metrics_business_key_unique 
UNIQUE NULLS NOT DISTINCT (filing_id, normalized_label, fiscal_year, period_type, dimension_id);

-- 2.5: Add indexes on business keys for fast lookups
CREATE INDEX IF NOT EXISTS idx_fact_normalized_label ON fact_financial_metrics(normalized_label);
CREATE INDEX IF NOT EXISTS idx_fact_fiscal_year ON fact_financial_metrics(fiscal_year);
CREATE INDEX IF NOT EXISTS idx_fact_period_type ON fact_financial_metrics(period_type);
CREATE INDEX IF NOT EXISTS idx_fact_business_key ON fact_financial_metrics(filing_id, normalized_label, fiscal_year, period_type, dimension_id);

-- ============================================================================
-- IMPROVEMENT 3: Add Triggers to Maintain Denormalized Columns
-- ============================================================================

-- 3.1: Function to update denormalized columns when concept changes
CREATE OR REPLACE FUNCTION update_fact_normalized_label()
RETURNS TRIGGER AS $$
BEGIN
    -- Update all facts that reference this concept
    UPDATE fact_financial_metrics fm
    SET normalized_label = NEW.normalized_label
    WHERE fm.concept_id = NEW.concept_id
      AND (fm.normalized_label IS NULL OR fm.normalized_label != NEW.normalized_label);
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 3.2: Function to update denormalized columns when period changes
CREATE OR REPLACE FUNCTION update_fact_period_info()
RETURNS TRIGGER AS $$
BEGIN
    -- Update all facts that reference this period
    UPDATE fact_financial_metrics fm
    SET 
        fiscal_year = NEW.fiscal_year,
        period_type = NEW.period_type
    WHERE fm.period_id = NEW.period_id
      AND (fm.fiscal_year IS NULL OR fm.fiscal_year != NEW.fiscal_year 
           OR fm.period_type IS NULL OR fm.period_type != NEW.period_type);
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 3.3: Function to populate denormalized columns when fact is inserted/updated
CREATE OR REPLACE FUNCTION populate_fact_business_keys()
RETURNS TRIGGER AS $$
BEGIN
    -- Populate from dimension tables if not already set
    IF NEW.normalized_label IS NULL THEN
        SELECT normalized_label INTO NEW.normalized_label
        FROM dim_concepts
        WHERE concept_id = NEW.concept_id;
    END IF;
    
    IF NEW.fiscal_year IS NULL OR NEW.period_type IS NULL THEN
        SELECT fiscal_year, period_type INTO NEW.fiscal_year, NEW.period_type
        FROM dim_time_periods
        WHERE period_id = NEW.period_id;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 3.4: Create triggers
DROP TRIGGER IF EXISTS trigger_update_fact_normalized_label ON dim_concepts;
CREATE TRIGGER trigger_update_fact_normalized_label
    AFTER UPDATE OF normalized_label ON dim_concepts
    FOR EACH ROW
    WHEN (OLD.normalized_label IS DISTINCT FROM NEW.normalized_label)
    EXECUTE FUNCTION update_fact_normalized_label();

DROP TRIGGER IF EXISTS trigger_update_fact_period_info ON dim_time_periods;
CREATE TRIGGER trigger_update_fact_period_info
    AFTER UPDATE OF fiscal_year, period_type ON dim_time_periods
    FOR EACH ROW
    WHEN (OLD.fiscal_year IS DISTINCT FROM NEW.fiscal_year 
          OR OLD.period_type IS DISTINCT FROM NEW.period_type)
    EXECUTE FUNCTION update_fact_period_info();

DROP TRIGGER IF EXISTS trigger_populate_fact_business_keys ON fact_financial_metrics;
CREATE TRIGGER trigger_populate_fact_business_keys
    BEFORE INSERT OR UPDATE ON fact_financial_metrics
    FOR EACH ROW
    WHEN (NEW.normalized_label IS NULL OR NEW.fiscal_year IS NULL OR NEW.period_type IS NULL)
    EXECUTE FUNCTION populate_fact_business_keys();

-- ============================================================================
-- VERIFICATION
-- ============================================================================

-- Check that all facts have business keys populated
DO $$
DECLARE
    missing_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO missing_count
    FROM fact_financial_metrics fm
    LEFT JOIN dim_concepts dc ON fm.concept_id = dc.concept_id
    LEFT JOIN dim_time_periods dt ON fm.period_id = dt.period_id
    WHERE fm.normalized_label IS NULL 
       OR fm.fiscal_year IS NULL 
       OR fm.period_type IS NULL;
    
    IF missing_count > 0 THEN
        RAISE WARNING 'Found % facts with missing business keys. Please run UPDATE statement again.', missing_count;
    ELSE
        RAISE NOTICE 'All facts have business keys populated successfully.';
    END IF;
END $$;

-- ============================================================================
-- COMPLETION
-- ============================================================================

SELECT 'Business keys migration completed successfully' AS status;

