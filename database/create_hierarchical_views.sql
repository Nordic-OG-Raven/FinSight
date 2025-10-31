-- ============================================================================
-- Hierarchical Views for Cross-Company Comparable Metrics
-- ============================================================================
--
-- Purpose: Enable cross-company comparison at ANY hierarchy level
-- Solution: Aggregate child concepts when parent not directly reported
--
-- Example: Accrued Liabilities
--   - GOOGL reports 3 components: AccruedLiabilities + Employee + Other
--   - KO reports 1 combined: AccountsPayableAndAccruedLiabilities  
--   - For comparison: Both roll up to LiabilitiesCurrent (section total)
--

-- Drop existing views
DROP VIEW IF EXISTS v_facts_hierarchical CASCADE;
DROP VIEW IF EXISTS v_facts_comparable CASCADE;

-- ============================================================================
-- v_facts_hierarchical: Facts with hierarchy metadata + deduplication
-- ============================================================================
-- Uses v_facts_deduplicated as base to eliminate duplicate facts
-- Adds hierarchy metadata for granularity filtering
CREATE OR REPLACE VIEW v_facts_hierarchical AS
SELECT 
    dedup.fact_id,
    dedup.company_id,
    dedup.concept_id,
    dedup.period_id,
    dedup.filing_id,
    dedup.dimension_id,  -- REQUIRED for segment filtering
    dedup.value_numeric,
    dedup.value_text,
    dedup.unit_measure,
    dedup.decimals,
    dedup.scale_int,
    dedup.xbrl_format,
    dedup.context_id,
    dedup.fact_id_xbrl,
    dedup.source_line,
    dedup.order_index,
    dedup.is_primary,
    
    -- Concept info (from deduplicated view)
    dedup.concept_name,
    dedup.normalized_label,
    dedup.taxonomy,
    dedup.statement_type,
    
    -- Hierarchy info (join to get parent metadata)
    dc.hierarchy_level,
    dc.parent_concept_id,
    dc.calculation_weight,
    
    -- Parent concept info (for drill-up)
    dc_parent.concept_name as parent_concept_name,
    dc_parent.normalized_label as parent_normalized_label,
    dc_parent.hierarchy_level as parent_hierarchy_level,
    
    -- Time period info (from deduplicated view)
    dedup.fiscal_year,
    
    -- Company info
    c.ticker,
    c.company_name,
    c.accounting_standard

FROM v_facts_deduplicated dedup
JOIN dim_concepts dc ON dedup.concept_id = dc.concept_id
LEFT JOIN dim_concepts dc_parent ON dc.parent_concept_id = dc_parent.concept_id
JOIN dim_companies c ON dedup.company_id = c.company_id;

-- Index for performance
CREATE INDEX IF NOT EXISTS idx_facts_hier_level ON fact_financial_metrics(concept_id) 
    WHERE NOT is_calculated;

-- ============================================================================
-- v_facts_comparable: Aggregated to comparable levels
-- ============================================================================
--
-- This view automatically aggregates child concepts to parent when needed.
-- Ensures all companies are comparable at same hierarchy level.
--
CREATE VIEW v_facts_comparable AS
WITH RECURSIVE concept_rollup AS (
    -- Base case: Facts that exist at this level
    SELECT 
        f.company_id,
        f.period_id,
        f.concept_id,
        dc.normalized_label,
        dc.hierarchy_level,
        f.value_numeric,
        f.is_calculated,
        dc.parent_concept_id,
        1 as aggregation_hops  -- How many levels we aggregated
    FROM fact_financial_metrics f
    JOIN dim_concepts dc ON f.concept_id = dc.concept_id
    WHERE f.dimension_id IS NULL
      AND f.value_numeric IS NOT NULL
    
    UNION ALL
    
    -- Recursive case: Aggregate children to parent
    SELECT 
        cr.company_id,
        cr.period_id,
        dc_parent.concept_id,
        dc_parent.normalized_label,
        dc_parent.hierarchy_level,
        SUM(cr.value_numeric * dc.calculation_weight) as value_numeric,
        TRUE as is_calculated,
        dc_parent.parent_concept_id,
        cr.aggregation_hops + 1
    FROM concept_rollup cr
    JOIN dim_concepts dc ON cr.concept_id = dc.concept_id
    JOIN dim_concepts dc_parent ON dc.parent_concept_id = dc_parent.concept_id
    WHERE cr.aggregation_hops < 3  -- Prevent infinite recursion
    GROUP BY cr.company_id, cr.period_id, dc_parent.concept_id, 
             dc_parent.normalized_label, dc_parent.hierarchy_level, dc_parent.parent_concept_id
)
SELECT DISTINCT ON (company_id, period_id, concept_id)
    company_id,
    period_id,
    concept_id,
    normalized_label,
    hierarchy_level,
    value_numeric,
    is_calculated,
    aggregation_hops
FROM concept_rollup
ORDER BY company_id, period_id, concept_id, aggregation_hops ASC;  -- Prefer direct reports over calculated

COMMENT ON VIEW v_facts_comparable IS 
'Cross-company comparable facts with automatic child aggregation. 
Uses hierarchy to ensure all companies report at same level.
Calculated values marked with is_calculated=TRUE.';

