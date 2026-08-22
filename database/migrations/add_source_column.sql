-- Migration: Add source column to fact_financial_metrics
-- Purpose: Track data provenance (XBRL vs SEC_API) to enable smart deduplication
-- Date: 2025-11-10

-- Add source column with default 'XBRL' for existing data
ALTER TABLE fact_financial_metrics 
ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'XBRL';

-- Add index for faster filtering by source
CREATE INDEX IF NOT EXISTS idx_fact_financial_metrics_source 
ON fact_financial_metrics(source);

-- Add comment explaining the column
COMMENT ON COLUMN fact_financial_metrics.source IS 
'Data source: XBRL (parsed from filing) or SEC_API (gap-filled from SEC Company Facts API). SEC_API is preferred when both exist.';

