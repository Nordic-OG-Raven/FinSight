-- ============================================================================
-- FinSight Financial Data Warehouse Schema
-- Star Schema Design for XBRL Financial Data
-- ============================================================================

-- Drop existing tables (in correct order due to foreign keys)
DROP TABLE IF EXISTS fact_comprehensive_income CASCADE;
DROP TABLE IF EXISTS fact_cash_flow CASCADE;
DROP TABLE IF EXISTS fact_balance_sheet CASCADE;
DROP TABLE IF EXISTS fact_income_statement CASCADE;
DROP TABLE IF EXISTS rel_statement_items CASCADE;
DROP TABLE IF EXISTS rel_footnote_references CASCADE;
DROP TABLE IF EXISTS rel_presentation_hierarchy CASCADE;
DROP TABLE IF EXISTS rel_calculation_hierarchy CASCADE;
DROP TABLE IF EXISTS fact_financial_metrics CASCADE;
DROP TABLE IF EXISTS data_quality_scores CASCADE;
DROP TABLE IF EXISTS dim_xbrl_dimensions CASCADE;
DROP TABLE IF EXISTS dim_filings CASCADE;
DROP TABLE IF EXISTS dim_time_periods CASCADE;
DROP TABLE IF EXISTS dim_concepts CASCADE;
DROP TABLE IF EXISTS dim_companies CASCADE;
DROP TABLE IF EXISTS rel_fact_notes CASCADE;
DROP TABLE IF EXISTS fact_financial_notes CASCADE;
DROP TABLE IF EXISTS fact_restatements CASCADE;
DROP TABLE IF EXISTS audit_fact_changes CASCADE;
DROP TABLE IF EXISTS fact_gaap_reconciliation CASCADE;
DROP TABLE IF EXISTS fact_ratios CASCADE;
DROP TABLE IF EXISTS fact_exchange_rates CASCADE;
DROP TABLE IF EXISTS dim_segments CASCADE;
DROP TABLE IF EXISTS dim_consolidation_levels CASCADE;
DROP TABLE IF EXISTS dim_currencies CASCADE;
DROP TABLE IF EXISTS dim_fiscal_periods CASCADE;
DROP TABLE IF EXISTS rel_concept_mappings CASCADE;
DROP TABLE IF EXISTS dim_reporting_frameworks CASCADE;
DROP TABLE IF EXISTS dim_taxonomies CASCADE;
DROP TABLE IF EXISTS taxonomy_mappings CASCADE;

-- ============================================================================
-- DIMENSION TABLES
-- ============================================================================

-- Reporting frameworks dimension table (must be created first - referenced by dim_companies)
CREATE TABLE dim_reporting_frameworks (
    framework_id SERIAL PRIMARY KEY,
    framework_name VARCHAR(50) NOT NULL UNIQUE, -- 'IFRS', 'US-GAAP', 'UK-GAAP'
    framework_code VARCHAR(20) NOT NULL UNIQUE, -- 'IFRS', 'USGAAP', 'UKGAAP'
    jurisdiction VARCHAR(3),
    standard_setter VARCHAR(100), -- 'IASB', 'FASB', 'FRC'
    effective_date DATE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Companies dimension table
CREATE TABLE dim_companies (
    company_id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL UNIQUE,
    company_name VARCHAR(200),
    cik VARCHAR(20),
    sector VARCHAR(100),
    industry VARCHAR(100),
    country VARCHAR(3),
    accounting_standard VARCHAR(20), -- 'US-GAAP' or 'IFRS'
    framework_id INTEGER REFERENCES dim_reporting_frameworks(framework_id),
    default_reporting_frequency VARCHAR(20), -- 'annual', 'quarterly', 'semi-annual'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Taxonomies dimension table
CREATE TABLE dim_taxonomies (
    taxonomy_id SERIAL PRIMARY KEY,
    taxonomy_name VARCHAR(50) NOT NULL UNIQUE, -- 'us-gaap', 'ifrs-full', 'ifrs-eu'
    taxonomy_version VARCHAR(20), -- '2024', '2023', etc.
    reporting_framework_id INTEGER REFERENCES dim_reporting_frameworks(framework_id),
    jurisdiction VARCHAR(3), -- 'US', 'EU', 'GB', etc.
    effective_date DATE,
    superseded_date DATE,
    parent_taxonomy_id INTEGER REFERENCES dim_taxonomies(taxonomy_id),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- XBRL concepts dimension table
CREATE TABLE dim_concepts (
    concept_id SERIAL PRIMARY KEY,
    concept_name TEXT NOT NULL,
    taxonomy VARCHAR(50) NOT NULL,
    taxonomy_id INTEGER REFERENCES dim_taxonomies(taxonomy_id),
    normalized_label VARCHAR(200) NOT NULL, -- BUSINESS KEY: Unique across taxonomies
    concept_type VARCHAR(50),
    balance_type VARCHAR(20), -- debit, credit, NA
    period_type VARCHAR(20), -- instant, duration
    data_type VARCHAR(50),
    is_abstract BOOLEAN DEFAULT FALSE,
    statement_type VARCHAR(50), -- income_statement, balance_sheet, cash_flow, etc.
    
    -- HIERARCHICAL STRUCTURE (parent-child relationships)
    hierarchy_level INTEGER, -- 1=detail, 2=subtotal, 3=section_total, 4=statement_total
    parent_concept_id INTEGER REFERENCES dim_concepts(concept_id) ON DELETE SET NULL,
    is_calculated BOOLEAN DEFAULT FALSE, -- TRUE if value derived from children
    calculation_weight DECIMAL(10,4) DEFAULT 1.0, -- 1.0 for addition, -1.0 for subtraction
    preferred_label VARCHAR(500), -- Human-readable label from taxonomy or generic mapping (populated during ETL)
    original_label VARCHAR(500), -- Original XBRL label text from label linkbase (company-specific, extracted during parsing)
    label_role VARCHAR(200), -- XBRL label role (e.g., 'http://www.xbrl.org/2003/role/documentation' indicates headers)
    
    UNIQUE(concept_name, taxonomy)
    -- NOTE: normalized_label is NOT unique - multiple concepts can map to same normalized_label
    -- This is intentional: e.g., 'Assets' and 'LiabilitiesAndStockholdersEquity' both map to 'total_assets'
);

-- Time periods dimension table
CREATE TABLE dim_time_periods (
    period_id SERIAL PRIMARY KEY,
    period_type VARCHAR(20) NOT NULL, -- instant, duration
    start_date DATE,
    end_date DATE,
    instant_date DATE,
    fiscal_year INTEGER,
    fiscal_quarter INTEGER,
    period_label VARCHAR(100), -- e.g., 'FY2024 Q1', 'FY2024'
    -- BUSINESS KEY: Computed column for easier matching (e.g., '2024-duration')
    business_key VARCHAR(50) GENERATED ALWAYS AS (
        CASE 
            WHEN fiscal_year IS NOT NULL AND period_type IS NOT NULL 
            THEN fiscal_year::TEXT || '-' || period_type
            ELSE NULL
        END
    ) STORED,
    UNIQUE(period_type, start_date, end_date, instant_date)
);

-- SEC filings dimension table
CREATE TABLE dim_filings (
    filing_id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES dim_companies(company_id),
    filing_type VARCHAR(20) NOT NULL, -- 10-K, 20-F, 10-Q
    fiscal_year_end DATE NOT NULL,
    filing_date DATE,
    source_url TEXT,
    accession_number VARCHAR(50),
    reporting_frequency VARCHAR(20), -- 'annual', 'quarterly', 'semi-annual'
    extraction_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    validation_score NUMERIC(5,2),
    completeness_score NUMERIC(5,2),
    UNIQUE(company_id, filing_type, fiscal_year_end)
);

-- XBRL dimensions (segments, products, geographies, etc.)
CREATE TABLE dim_xbrl_dimensions (
    dimension_id SERIAL PRIMARY KEY,
    dimension_json JSONB NOT NULL,
    dimension_hash VARCHAR(64) NOT NULL UNIQUE, -- MD5 hash for quick lookup
    axis_name TEXT,
    member_name TEXT,
    dimension_description TEXT
);

-- ============================================================================
-- ELT STAGING LAYER (Raw Extracted Data)
-- ============================================================================

-- Raw extracted facts (before normalization/transformation)
-- This table stores raw data from XBRL/SEC_API extraction for debugging and reprocessing
CREATE TABLE staging_facts (
    staging_id SERIAL PRIMARY KEY,
    filing_id INTEGER NOT NULL REFERENCES dim_filings(filing_id) ON DELETE CASCADE,
    
    -- Raw extracted data (minimal transformation)
    concept_name TEXT NOT NULL,
    concept_namespace TEXT,
    taxonomy VARCHAR(50),
    value_text TEXT,
    value_numeric DOUBLE PRECISION,
    
    -- Period info (raw from XBRL)
    period_type VARCHAR(20),
    period_start DATE,
    period_end DATE,
    instant_date DATE,
    context_id TEXT,
    
    -- Dimensions (raw JSON)
    dimensions_json JSONB,
    
    -- Unit info (raw)
    unit_measure VARCHAR(50),
    unit_type VARCHAR(20), -- 'currency', 'shares', 'pure'
    scale_int INTEGER, -- e.g., 6 for millions, 3 for thousands
    
    -- Source metadata
    source VARCHAR(20) NOT NULL, -- 'XBRL', 'SEC_API'
    extraction_method VARCHAR(50), -- 'lxml', 'modelxbrl', 'sec_api'
    extraction_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Provenance
    fact_id_xbrl VARCHAR(100),
    source_line INTEGER,
    order_index INTEGER,
    
    -- Processing status
    is_processed BOOLEAN DEFAULT FALSE,
    processing_error TEXT,
    
    UNIQUE(filing_id, concept_name, context_id, fact_id_xbrl)
);

CREATE INDEX idx_staging_facts_filing ON staging_facts(filing_id, is_processed);
CREATE INDEX idx_staging_facts_concept ON staging_facts(concept_name, taxonomy);
CREATE INDEX idx_staging_facts_processed ON staging_facts(is_processed) WHERE is_processed = FALSE;

-- View showing transformation logic from staging to facts
CREATE VIEW v_staging_to_facts AS
SELECT 
    sf.staging_id,
    sf.filing_id,
    sf.concept_name,
    sf.value_numeric as raw_value,
    sf.unit_measure as raw_unit_measure,
    sf.unit_type as raw_unit_type,
    sf.scale_int as raw_scale_int,
    -- Transformation logic (unit scaling, normalization, etc.)
    CASE 
        WHEN sf.unit_type = 'currency' AND sf.unit_measure IN ('DKK', 'EUR', 'USD', 'GBP', 'JPY', 'CNY') 
        THEN sf.value_numeric * POWER(10, COALESCE(sf.scale_int, 0))
        WHEN sf.unit_type = 'shares'
        THEN sf.value_numeric * POWER(10, COALESCE(sf.scale_int, 0))
        ELSE sf.value_numeric
    END as transformed_value,
    sf.dimensions_json,
    sf.period_type,
    sf.period_start,
    sf.period_end,
    sf.instant_date,
    sf.source,
    sf.extraction_method,
    sf.is_processed,
    sf.processing_error
FROM staging_facts sf
WHERE sf.is_processed = FALSE;

-- ============================================================================
-- FACT TABLE
-- ============================================================================

-- Core financial metrics fact table
CREATE TABLE fact_financial_metrics (
    fact_id SERIAL PRIMARY KEY,
    
    -- Foreign keys to dimensions
    company_id INTEGER NOT NULL REFERENCES dim_companies(company_id),
    concept_id INTEGER NOT NULL REFERENCES dim_concepts(concept_id),
    period_id INTEGER NOT NULL REFERENCES dim_time_periods(period_id),
    filing_id INTEGER NOT NULL REFERENCES dim_filings(filing_id),
    dimension_id INTEGER REFERENCES dim_xbrl_dimensions(dimension_id), -- NULL for consolidated totals
    
    -- BUSINESS KEYS (denormalized for performance and simpler queries)
    normalized_label VARCHAR(200) NOT NULL, -- Denormalized from dim_concepts
    fiscal_year INTEGER NOT NULL, -- Denormalized from dim_time_periods
    period_type VARCHAR(20) NOT NULL, -- Denormalized from dim_time_periods
    
    -- Fact values
    value_numeric DOUBLE PRECISION,
    value_text TEXT,
    
    -- Units and scaling
    unit_measure VARCHAR(50),
    currency_id INTEGER, -- Will be set via ALTER TABLE after dim_currencies is created
    decimals VARCHAR(20),
    scale_int INTEGER, -- e.g., 6 for millions, 3 for thousands
    xbrl_format VARCHAR(100), -- e.g., 'ixt:num-dot-decimal'
    
    -- GAAP/Non-GAAP classification
    is_gaap BOOLEAN DEFAULT TRUE,
    
    -- XBRL metadata
    context_id TEXT,
    fact_id_xbrl VARCHAR(100),
    source_line INTEGER,
    order_index INTEGER, -- Fact ordering within document sections
    is_primary BOOLEAN DEFAULT TRUE, -- TRUE if primary occurrence (not a duplicate reference)
    
    -- Hierarchical aggregation
    is_calculated BOOLEAN DEFAULT FALSE, -- TRUE if value calculated from children (not in XBRL filing)
    
    -- Provenance
    extraction_method VARCHAR(50) DEFAULT 'arelle',
    source VARCHAR(50) DEFAULT 'XBRL', -- 'XBRL' (parsed from filing) or 'SEC_API' (gap-filled). SEC_API preferred when both exist.
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- BUSINESS KEY constraint: prevent duplicate facts using business keys
    -- This enables matching by normalized_label + fiscal_year + period_type
    -- instead of requiring joins to dimension tables
    -- NULLS NOT DISTINCT treats NULL values as equal (PostgreSQL 15+)
    UNIQUE NULLS NOT DISTINCT (filing_id, normalized_label, fiscal_year, period_type, dimension_id),
    
    -- Legacy constraint for backward compatibility (can be removed after migration)
    UNIQUE NULLS NOT DISTINCT (filing_id, concept_id, period_id, dimension_id)
);

-- Index for source filtering (enables fast queries by data provenance)
CREATE INDEX idx_fact_financial_metrics_source ON fact_financial_metrics(source);

-- BUSINESS KEY indexes for fast lookups without joins
CREATE INDEX idx_fact_normalized_label ON fact_financial_metrics(normalized_label);
CREATE INDEX idx_fact_fiscal_year ON fact_financial_metrics(fiscal_year);
CREATE INDEX idx_fact_period_type ON fact_financial_metrics(period_type);
CREATE INDEX idx_fact_business_key ON fact_financial_metrics(filing_id, normalized_label, fiscal_year, period_type, dimension_id);

-- ============================================================================
-- METADATA & QUALITY TABLES
-- ============================================================================

-- Data quality scores per filing
CREATE TABLE data_quality_scores (
    quality_id SERIAL PRIMARY KEY,
    filing_id INTEGER NOT NULL REFERENCES dim_filings(filing_id),
    check_name VARCHAR(100) NOT NULL,
    check_passed BOOLEAN,
    expected_value NUMERIC,
    actual_value NUMERIC,
    difference NUMERIC,
    difference_pct NUMERIC,
    severity VARCHAR(20), -- 'critical', 'warning', 'info'
    details JSONB,
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(filing_id, check_name)
);

-- Taxonomy normalization mappings (legacy - kept for backward compatibility)
CREATE TABLE taxonomy_mappings (
    mapping_id SERIAL PRIMARY KEY,
    source_concept TEXT NOT NULL,
    source_taxonomy VARCHAR(50) NOT NULL,
    normalized_label VARCHAR(200) NOT NULL,
    confidence NUMERIC(3,2) DEFAULT 1.0,
    mapping_type VARCHAR(50), -- 'exact', 'sum', 'derived'
    notes TEXT,
    UNIQUE(source_concept, source_taxonomy)
);

-- Concept mappings (enhanced version linking concepts via concept_id)
CREATE TABLE rel_concept_mappings (
    mapping_id SERIAL PRIMARY KEY,
    source_concept_id INTEGER NOT NULL REFERENCES dim_concepts(concept_id),
    target_concept_id INTEGER NOT NULL REFERENCES dim_concepts(concept_id),
    mapping_type VARCHAR(20) NOT NULL, -- 'equivalent', 'similar', 'approximate'
    confidence_score NUMERIC(3,2), -- 0.00 to 1.00
    mapping_source VARCHAR(50), -- 'manual', 'automated', 'industry_standard'
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_concept_id, target_concept_id)
);

-- Fiscal periods dimension table
CREATE TABLE dim_fiscal_periods (
    fiscal_period_id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES dim_companies(company_id),
    fiscal_year INTEGER NOT NULL,
    fiscal_year_end_month INTEGER NOT NULL, -- 1-12
    fiscal_year_end_day INTEGER NOT NULL, -- Usually 31
    calendar_year INTEGER, -- For calendar-year companies, same as fiscal_year
    is_calendar_year BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, fiscal_year)
);

-- Currencies dimension table
CREATE TABLE dim_currencies (
    currency_id SERIAL PRIMARY KEY,
    currency_code VARCHAR(3) NOT NULL UNIQUE, -- 'USD', 'EUR', 'DKK'
    currency_name VARCHAR(100),
    is_base_currency BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add foreign key constraint for currency_id in fact_financial_metrics
ALTER TABLE fact_financial_metrics 
    ADD CONSTRAINT fact_financial_metrics_currency_id_fkey 
    FOREIGN KEY (currency_id) REFERENCES dim_currencies(currency_id);

-- Exchange rates fact table
CREATE TABLE fact_exchange_rates (
    exchange_rate_id SERIAL PRIMARY KEY,
    from_currency_id INTEGER NOT NULL REFERENCES dim_currencies(currency_id),
    to_currency_id INTEGER NOT NULL REFERENCES dim_currencies(currency_id),
    period_id INTEGER REFERENCES dim_time_periods(period_id),
    rate_date DATE NOT NULL,
    exchange_rate NUMERIC(20,6) NOT NULL,
    source VARCHAR(50), -- 'SEC', 'FRED', 'manual'
    UNIQUE(from_currency_id, to_currency_id, rate_date)
);

-- Financial ratios fact table
CREATE TABLE fact_ratios (
    ratio_id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES dim_companies(company_id),
    period_id INTEGER NOT NULL REFERENCES dim_time_periods(period_id),
    ratio_type VARCHAR(50) NOT NULL, -- 'roe', 'roa', 'current_ratio', etc.
    ratio_value NUMERIC(20,4),
    numerator_concept_id INTEGER REFERENCES dim_concepts(concept_id),
    denominator_concept_id INTEGER REFERENCES dim_concepts(concept_id),
    calculation_method TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, period_id, ratio_type)
);

-- Segments dimension table
CREATE TABLE dim_segments (
    segment_id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES dim_companies(company_id),
    segment_name VARCHAR(200) NOT NULL,
    segment_type VARCHAR(50), -- 'operating', 'geographic', 'product'
    parent_segment_id INTEGER REFERENCES dim_segments(segment_id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, segment_name)
);

-- Financial notes fact table
CREATE TABLE fact_financial_notes (
    note_id SERIAL PRIMARY KEY,
    filing_id INTEGER NOT NULL REFERENCES dim_filings(filing_id),
    note_number VARCHAR(20),
    note_type VARCHAR(50), -- 'accounting_policy', 'contingency', 'related_party', etc.
    section VARCHAR(100),
    title VARCHAR(500),
    content TEXT,
    order_index INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Fact-notes relationship table
CREATE TABLE rel_fact_notes (
    fact_note_id SERIAL PRIMARY KEY,
    fact_id INTEGER NOT NULL REFERENCES fact_financial_metrics(fact_id),
    note_id INTEGER NOT NULL REFERENCES fact_financial_notes(note_id),
    relationship_type VARCHAR(50), -- 'explains', 'references', 'discloses'
    UNIQUE(fact_id, note_id)
);

-- GAAP reconciliation table
CREATE TABLE fact_gaap_reconciliation (
    reconciliation_id SERIAL PRIMARY KEY,
    non_gaap_fact_id INTEGER NOT NULL REFERENCES fact_financial_metrics(fact_id),
    gaap_fact_id INTEGER REFERENCES fact_financial_metrics(fact_id),
    adjustment_type VARCHAR(50), -- 'add_back', 'exclude', 'adjust'
    adjustment_amount NUMERIC(20,2),
    adjustment_description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Audit trail for fact changes
CREATE TABLE audit_fact_changes (
    audit_id SERIAL PRIMARY KEY,
    fact_id INTEGER NOT NULL REFERENCES fact_financial_metrics(fact_id),
    old_value_numeric DOUBLE PRECISION,
    new_value_numeric DOUBLE PRECISION,
    old_value_text TEXT,
    new_value_text TEXT,
    change_type VARCHAR(50), -- 'restatement', 'correction', 'update'
    reason TEXT,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    changed_by VARCHAR(100) -- 'system', 'user', 'pipeline'
);

-- Restatements fact table
CREATE TABLE fact_restatements (
    restatement_id SERIAL PRIMARY KEY,
    filing_id INTEGER NOT NULL REFERENCES dim_filings(filing_id),
    company_id INTEGER NOT NULL REFERENCES dim_companies(company_id),
    restatement_date DATE NOT NULL,
    reason TEXT,
    impact_amount NUMERIC(20,2),
    affected_periods TEXT, -- JSON array of period_ids
    restatement_type VARCHAR(50), -- 'correction', 'reclassification', 'adoption'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Consolidation levels dimension table
CREATE TABLE dim_consolidation_levels (
    level_id SERIAL PRIMARY KEY,
    level_name VARCHAR(100) NOT NULL, -- 'consolidated', 'standalone', 'segment'
    level_type VARCHAR(50), -- 'consolidated', 'standalone', 'segment', 'subsidiary'
    parent_level_id INTEGER REFERENCES dim_consolidation_levels(level_id),
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- INDEXES FOR NEW TABLES
-- ============================================================================

-- Indexes for dim_taxonomies
CREATE INDEX idx_taxonomies_framework ON dim_taxonomies(reporting_framework_id);
CREATE INDEX idx_taxonomies_name_version ON dim_taxonomies(taxonomy_name, taxonomy_version);
CREATE INDEX idx_taxonomies_active ON dim_taxonomies(is_active) WHERE is_active = TRUE;

-- Indexes for dim_reporting_frameworks
CREATE INDEX idx_frameworks_code ON dim_reporting_frameworks(framework_code);
CREATE INDEX idx_frameworks_active ON dim_reporting_frameworks(is_active) WHERE is_active = TRUE;

-- Indexes for rel_concept_mappings
CREATE INDEX idx_concept_mappings_source ON rel_concept_mappings(source_concept_id);
CREATE INDEX idx_concept_mappings_target ON rel_concept_mappings(target_concept_id);
CREATE INDEX idx_concept_mappings_type ON rel_concept_mappings(mapping_type);

-- Indexes for dim_fiscal_periods
CREATE INDEX idx_fiscal_periods_company_year ON dim_fiscal_periods(company_id, fiscal_year);
CREATE INDEX idx_fiscal_periods_calendar ON dim_fiscal_periods(is_calendar_year) WHERE is_calendar_year = TRUE;

-- Indexes for dim_currencies
CREATE INDEX idx_currencies_code ON dim_currencies(currency_code);
CREATE INDEX idx_currencies_base ON dim_currencies(is_base_currency) WHERE is_base_currency = TRUE;

-- Indexes for fact_exchange_rates
CREATE INDEX idx_exchange_rates_currencies ON fact_exchange_rates(from_currency_id, to_currency_id);
CREATE INDEX idx_exchange_rates_date ON fact_exchange_rates(rate_date);
CREATE INDEX idx_exchange_rates_period ON fact_exchange_rates(period_id);

-- Indexes for fact_ratios
CREATE INDEX idx_ratios_company_period ON fact_ratios(company_id, period_id);
CREATE INDEX idx_ratios_type ON fact_ratios(ratio_type);
CREATE INDEX idx_ratios_concepts ON fact_ratios(numerator_concept_id, denominator_concept_id);

-- Indexes for dim_segments
CREATE INDEX idx_segments_company ON dim_segments(company_id);
CREATE INDEX idx_segments_type ON dim_segments(segment_type);
CREATE INDEX idx_segments_parent ON dim_segments(parent_segment_id);

-- Indexes for fact_financial_notes
CREATE INDEX idx_notes_filing ON fact_financial_notes(filing_id);
CREATE INDEX idx_notes_type ON fact_financial_notes(note_type);
CREATE INDEX idx_notes_number ON fact_financial_notes(note_number);

-- Indexes for rel_fact_notes
CREATE INDEX idx_fact_notes_fact ON rel_fact_notes(fact_id);
CREATE INDEX idx_fact_notes_note ON rel_fact_notes(note_id);

-- Indexes for fact_gaap_reconciliation
CREATE INDEX idx_gaap_recon_non_gaap ON fact_gaap_reconciliation(non_gaap_fact_id);
CREATE INDEX idx_gaap_recon_gaap ON fact_gaap_reconciliation(gaap_fact_id);

-- Indexes for audit_fact_changes
CREATE INDEX idx_audit_fact ON audit_fact_changes(fact_id);
CREATE INDEX idx_audit_type ON audit_fact_changes(change_type);
CREATE INDEX idx_audit_date ON audit_fact_changes(changed_at);

-- Indexes for fact_restatements
CREATE INDEX idx_restatements_filing ON fact_restatements(filing_id);
CREATE INDEX idx_restatements_company ON fact_restatements(company_id);
CREATE INDEX idx_restatements_date ON fact_restatements(restatement_date);
CREATE INDEX idx_restatements_type ON fact_restatements(restatement_type);

-- Indexes for dim_consolidation_levels
CREATE INDEX idx_consolidation_parent ON dim_consolidation_levels(parent_level_id);
CREATE INDEX idx_consolidation_type ON dim_consolidation_levels(level_type);

-- Indexes for fact_financial_metrics (new columns)
CREATE INDEX idx_facts_currency ON fact_financial_metrics(currency_id) WHERE currency_id IS NOT NULL;
CREATE INDEX idx_facts_gaap ON fact_financial_metrics(is_gaap) WHERE is_gaap = FALSE;
CREATE INDEX idx_facts_taxonomy ON dim_concepts(taxonomy_id) WHERE taxonomy_id IS NOT NULL;

-- ============================================================================
-- XBRL RELATIONSHIP TABLES
-- ============================================================================

-- Calculation relationships (parent-child summation relationships)
-- Example: Revenue = Product Revenue + Service Revenue
CREATE TABLE rel_calculation_hierarchy (
    calculation_id SERIAL PRIMARY KEY,
    filing_id INTEGER NOT NULL REFERENCES dim_filings(filing_id),
    parent_concept_id INTEGER NOT NULL REFERENCES dim_concepts(concept_id),
    child_concept_id INTEGER NOT NULL REFERENCES dim_concepts(concept_id),
    weight NUMERIC(5,2) DEFAULT 1.0, -- Usually 1.0 for addition, -1.0 for subtraction
    order_index INTEGER, -- Order within calculation tree
    arcrole VARCHAR(200), -- XBRL arcrole URI
    priority INTEGER DEFAULT 0,
    source VARCHAR(20) DEFAULT 'xbrl', -- 'xbrl', 'dimensional', 'standard'
    is_synthetic BOOLEAN DEFAULT FALSE, -- TRUE if generated, FALSE if from filing
    confidence NUMERIC(3,2) DEFAULT 1.0, -- Confidence score for synthetic relationships
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(filing_id, parent_concept_id, child_concept_id)
);

-- Presentation hierarchy (how concepts are organized in financial statements)
-- Example: Balance Sheet > Current Assets > Cash
-- NOTE: SEC_API facts (source='SEC_API' in fact_financial_metrics) do NOT have presentation hierarchy metadata.
-- Metadata is populated via populate_sec_api_metadata() which:
-- 1. Infers order_index/role_uri from other years (same company, same concept) if available
-- 2. Falls back to standard templates (source='standard' in rel_presentation_hierarchy)
-- This ensures SEC_API facts can be displayed even when XBRL data is missing for specific years.
CREATE TABLE rel_presentation_hierarchy (
    presentation_id SERIAL PRIMARY KEY,
    filing_id INTEGER NOT NULL REFERENCES dim_filings(filing_id),
    parent_concept_id INTEGER REFERENCES dim_concepts(concept_id), -- NULL for root nodes
    child_concept_id INTEGER NOT NULL REFERENCES dim_concepts(concept_id),
    order_index INTEGER NOT NULL, -- Order within statement section
    preferred_label VARCHAR(100), -- Label role (e.g., 'http://www.xbrl.org/2003/role/label')
    statement_type VARCHAR(50), -- balance_sheet, income_statement, cash_flow, etc.
    role_uri VARCHAR(500), -- CRITICAL: XBRL role URI from presentationLink (e.g., 'http://www.xbrl.org/role/statement/IncomeStatement')
                          -- Used to distinguish main statement items from detailed breakdowns
                          -- NULL for SEC_API facts (SEC API doesn't provide presentation hierarchy)
    arcrole VARCHAR(200), -- XBRL arcrole URI (usually parent-child)
    priority INTEGER DEFAULT 0,
    source VARCHAR(20) DEFAULT 'xbrl', -- 'xbrl' (from XBRL filing), 'standard' (from templates), 'dimensional' (from dimension relationships)
    is_synthetic BOOLEAN DEFAULT FALSE, -- TRUE if generated, FALSE if from filing
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(filing_id, parent_concept_id, child_concept_id, order_index)
);

-- Footnote references (links facts to footnote disclosures)
-- Example: DebtInstrument fact → links to Note 8: Long-term Debt
CREATE TABLE rel_footnote_references (
    footnote_id SERIAL PRIMARY KEY,
    filing_id INTEGER NOT NULL REFERENCES dim_filings(filing_id),
    fact_id INTEGER REFERENCES fact_financial_metrics(fact_id), -- Can be NULL if footnote references a concept
    concept_id INTEGER REFERENCES dim_concepts(concept_id), -- Concept the footnote explains
    footnote_text TEXT, -- The actual footnote text content
    footnote_label VARCHAR(100), -- Footnote identifier (e.g., 'F1', 'Note 8')
    footnote_role VARCHAR(200), -- XBRL role URI
    footnote_lang VARCHAR(10) DEFAULT 'en',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(filing_id, fact_id, concept_id, footnote_label)
);

-- ============================================================================
-- TEMPLATE TABLES (Presentation Layer - Separates Structure from Data)
-- ============================================================================

-- Canonical statement templates (standard structure)
-- Defines the standard structure for each statement type and format
-- Populated once per (statement_type, format_type) combination
-- Used as the default structure for all companies
CREATE TABLE dim_statement_templates (
    template_id SERIAL PRIMARY KEY,
    
    -- Template Identity
    statement_type VARCHAR(50) NOT NULL, -- 'income_statement', 'balance_sheet', 'cash_flow', 'comprehensive_income', 'equity_statement'
    format_type VARCHAR(20) NOT NULL DEFAULT 'standard', -- 'ifrs', 'us_gaap', 'ifrs_eu', 'custom' (legacy - use framework_id)
    framework_id INTEGER REFERENCES dim_reporting_frameworks(framework_id),
    
    -- Item Definition
    item_order INTEGER NOT NULL, -- Display order (1, 2, 3, ...)
    item_label VARCHAR(200) NOT NULL, -- Human-readable label (e.g., "Revenue", "Assets")
    normalized_label VARCHAR(200), -- Links to dim_concepts.normalized_label (NULL for headers/spacers)
    
    -- Item Type
    item_type VARCHAR(20) NOT NULL DEFAULT 'fact', -- 'fact', 'header', 'spacer', 'calculated', 'section_total'
    is_header BOOLEAN DEFAULT FALSE,
    is_spacer BOOLEAN DEFAULT FALSE, -- For blank lines (e.g., equity statement spaces)
    is_calculated BOOLEAN DEFAULT FALSE, -- TRUE if value is calculated from children (e.g., "Total Assets")
    
    -- Hierarchy
    hierarchy_level INTEGER DEFAULT 0, -- 0=detail, 1=subtotal, 2=section_total, 3=statement_total
    parent_item_order INTEGER, -- Parent item's order (for hierarchical structure)
    section_name VARCHAR(100), -- Section name (e.g., "Current Assets", "Operating Activities")
    
    -- Display Rules
    side VARCHAR(20), -- For balance sheet: 'assets' or 'liabilities_equity'
    is_required BOOLEAN DEFAULT TRUE, -- Must appear in statement (FALSE = optional, show if value exists)
    display_condition TEXT, -- SQL condition for when to show (e.g., "value > 0 OR is_required = TRUE")
    format_string VARCHAR(50), -- Format for display (e.g., "currency", "percentage", "shares")
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(statement_type, format_type, item_order)
);

-- Partial uniqueness (framework_id IS NOT NULL) can't be expressed as an inline UNIQUE(...)
-- constraint in PostgreSQL — that requires a separate partial unique index instead. This
-- was previously written as an inline constraint, which is invalid syntax; it caused this
-- table's CREATE TABLE statement to fail silently whenever schema.sql was applied, which is
-- very likely why the table was never actually deployed (see docs/NVO_GOLDEN_PATH_2026-08.md
-- item 6).
CREATE UNIQUE INDEX idx_templates_statement_framework_order ON dim_statement_templates(statement_type, framework_id, item_order) WHERE framework_id IS NOT NULL;

-- Filing-specific statement overrides (Custom Items)
-- These allow for custom items or overrides to the canonical templates
-- Populated per filing, only for items that deviate from the standard template
CREATE TABLE rel_statement_overrides (
    override_id SERIAL PRIMARY KEY,
    filing_id INTEGER NOT NULL REFERENCES dim_filings(filing_id) ON DELETE CASCADE,
    
    -- Reference to template (if overriding an existing item)
    template_id INTEGER REFERENCES dim_statement_templates(template_id) ON DELETE SET NULL,
    
    -- Overridden/Custom Item Definition
    item_order INTEGER NOT NULL, -- Display order (can override template)
    item_label VARCHAR(200) NOT NULL, -- Human-readable label (can override template)
    normalized_label VARCHAR(200), -- Links to dim_concepts.normalized_label (can override template)
    
    -- Item Type
    item_type VARCHAR(20) NOT NULL DEFAULT 'fact', -- 'fact', 'header', 'spacer', 'calculated', 'section_total'
    is_header BOOLEAN DEFAULT FALSE,
    is_spacer BOOLEAN DEFAULT FALSE,
    is_calculated BOOLEAN DEFAULT FALSE,
    
    -- Hierarchy
    hierarchy_level INTEGER DEFAULT 0,
    parent_item_order INTEGER,
    section_name VARCHAR(100),
    
    -- Display Rules
    side VARCHAR(20),
    is_required BOOLEAN DEFAULT TRUE,
    display_condition TEXT,
    format_string VARCHAR(50),
    
    is_custom BOOLEAN DEFAULT TRUE, -- TRUE if this is a custom item not in the template
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(filing_id, item_order) -- Ensure unique order per filing
);

-- Indexes for template tables
CREATE INDEX idx_templates_statement_format ON dim_statement_templates(statement_type, format_type);
CREATE INDEX idx_templates_statement_framework ON dim_statement_templates(statement_type, framework_id) WHERE framework_id IS NOT NULL;
CREATE INDEX idx_templates_normalized_label ON dim_statement_templates(normalized_label) WHERE normalized_label IS NOT NULL;
CREATE INDEX idx_overrides_filing ON rel_statement_overrides(filing_id);
CREATE INDEX idx_overrides_template ON rel_statement_overrides(template_id);

-- ============================================================================
-- STATEMENT ITEMS (Legacy - Kept for backward compatibility during migration)
-- ============================================================================

-- Statement items metadata (Approach 2: Statement Metadata Table)
-- Pre-computed statement-level metadata: which concepts belong to which statements,
-- their display order, and whether they are main items or headers.
-- Populated during ETL to simplify API queries.
-- NOTE: This table is DEPRECATED in favor of dim_statement_templates + rel_statement_overrides
-- Kept for backward compatibility during migration
CREATE TABLE rel_statement_items (
    statement_item_id SERIAL PRIMARY KEY,
    filing_id INTEGER NOT NULL REFERENCES dim_filings(filing_id) ON DELETE CASCADE,
    concept_id INTEGER NOT NULL REFERENCES dim_concepts(concept_id) ON DELETE CASCADE,
    statement_type VARCHAR(50) NOT NULL,  -- income_statement, balance_sheet, etc.
    display_order NUMERIC(10,2) NOT NULL,  -- Corrected order (handles EPS, headers, etc.) - NUMERIC to support decimal values (e.g., 0.5 for headers)
    is_header BOOLEAN DEFAULT FALSE,
    is_main_item BOOLEAN DEFAULT TRUE,  -- Main statement item (not detail/disclosure)
    role_uri VARCHAR(500),  -- For reference (from presentation hierarchy)
    source VARCHAR(20),  -- 'xbrl' or 'standard'
    side VARCHAR(20) CHECK (side IN ('assets', 'liabilities_equity')),  -- For balance sheet: left side (assets) or right side (liabilities_equity)
    inferred_order BOOLEAN DEFAULT FALSE,  -- TRUE if display_order was inferred from other years (XBRL extraction failed for this filing)
    header_source VARCHAR(20) CHECK (header_source IN ('xbrl_parent', 'xbrl_label_role', 'template', 'synthetic')),  -- Source of header: xbrl_parent (from parent-child relationship), xbrl_label_role (from label linkbase), template (standard template), synthetic (manually created), NULL (not a header)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(filing_id, concept_id, statement_type)
);

-- Statement-specific fact tables (Approach 2: Denormalized for Performance)
-- Pre-filtered and pre-ordered facts for each statement type.
-- Only main statement items are stored here (detail items stay in fact_financial_metrics).
-- Populated during ETL to enable simple, fast API queries.
CREATE TABLE fact_income_statement (
    income_statement_id SERIAL PRIMARY KEY,
    filing_id INTEGER NOT NULL REFERENCES dim_filings(filing_id) ON DELETE CASCADE,
    concept_id INTEGER NOT NULL REFERENCES dim_concepts(concept_id) ON DELETE CASCADE,
    period_id INTEGER NOT NULL REFERENCES dim_time_periods(period_id) ON DELETE CASCADE,
    value_numeric NUMERIC(20, 2),
    unit_measure VARCHAR(20),
    display_order INTEGER NOT NULL,  -- Pre-computed order from XBRL
    is_header BOOLEAN DEFAULT FALSE,
    hierarchy_level INTEGER,
    parent_concept_id INTEGER REFERENCES dim_concepts(concept_id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(filing_id, concept_id, period_id)
);

CREATE TABLE fact_balance_sheet (
    balance_sheet_id SERIAL PRIMARY KEY,
    filing_id INTEGER NOT NULL REFERENCES dim_filings(filing_id) ON DELETE CASCADE,
    concept_id INTEGER NOT NULL REFERENCES dim_concepts(concept_id) ON DELETE CASCADE,
    period_id INTEGER NOT NULL REFERENCES dim_time_periods(period_id) ON DELETE CASCADE,
    value_numeric NUMERIC(20, 2),
    unit_measure VARCHAR(20),
    display_order INTEGER NOT NULL,
    is_header BOOLEAN DEFAULT FALSE,
    hierarchy_level INTEGER,
    parent_concept_id INTEGER REFERENCES dim_concepts(concept_id) ON DELETE SET NULL,
    side VARCHAR(20) CHECK (side IN ('assets', 'liabilities_equity')),  -- Left side (assets) or right side (liabilities_equity)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(filing_id, concept_id, period_id)
);

CREATE TABLE fact_cash_flow (
    cash_flow_id SERIAL PRIMARY KEY,
    filing_id INTEGER NOT NULL REFERENCES dim_filings(filing_id) ON DELETE CASCADE,
    concept_id INTEGER NOT NULL REFERENCES dim_concepts(concept_id) ON DELETE CASCADE,
    period_id INTEGER NOT NULL REFERENCES dim_time_periods(period_id) ON DELETE CASCADE,
    value_numeric NUMERIC(20, 2),
    unit_measure VARCHAR(20),
    display_order INTEGER NOT NULL,
    is_header BOOLEAN DEFAULT FALSE,
    hierarchy_level INTEGER,
    parent_concept_id INTEGER REFERENCES dim_concepts(concept_id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(filing_id, concept_id, period_id)
);

CREATE TABLE fact_comprehensive_income (
    comprehensive_income_id SERIAL PRIMARY KEY,
    filing_id INTEGER NOT NULL REFERENCES dim_filings(filing_id) ON DELETE CASCADE,
    concept_id INTEGER NOT NULL REFERENCES dim_concepts(concept_id) ON DELETE CASCADE,
    period_id INTEGER NOT NULL REFERENCES dim_time_periods(period_id) ON DELETE CASCADE,
    value_numeric NUMERIC(20, 2),
    unit_measure VARCHAR(20),
    display_order INTEGER NOT NULL,
    is_header BOOLEAN DEFAULT FALSE,
    hierarchy_level INTEGER,
    parent_concept_id INTEGER REFERENCES dim_concepts(concept_id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(filing_id, concept_id, period_id)
);

CREATE TABLE fact_equity_statement (
    equity_statement_id SERIAL PRIMARY KEY,
    filing_id INTEGER NOT NULL REFERENCES dim_filings(filing_id) ON DELETE CASCADE,
    concept_id INTEGER NOT NULL REFERENCES dim_concepts(concept_id) ON DELETE CASCADE,
    period_id INTEGER NOT NULL REFERENCES dim_time_periods(period_id) ON DELETE CASCADE,
    value_numeric NUMERIC(20, 2),
    unit_measure VARCHAR(20),
    display_order INTEGER NOT NULL,
    is_header BOOLEAN DEFAULT FALSE,
    hierarchy_level INTEGER,
    parent_concept_id INTEGER REFERENCES dim_concepts(concept_id) ON DELETE SET NULL,
    equity_component VARCHAR(50),  -- 'share_capital', 'treasury_shares', 'retained_earnings', 'other_reserves', NULL for totals
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(filing_id, concept_id, period_id, equity_component)
);

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Performance indexes on fact table
CREATE INDEX idx_fact_company ON fact_financial_metrics(company_id);
CREATE INDEX idx_fact_concept ON fact_financial_metrics(concept_id);
CREATE INDEX idx_fact_period ON fact_financial_metrics(period_id);
CREATE INDEX idx_fact_filing ON fact_financial_metrics(filing_id);
CREATE INDEX idx_fact_dimension ON fact_financial_metrics(dimension_id);
CREATE INDEX idx_fact_value_numeric ON fact_financial_metrics(value_numeric) WHERE value_numeric IS NOT NULL;

-- Compound indexes for common queries
CREATE INDEX idx_fact_company_concept ON fact_financial_metrics(company_id, concept_id);
CREATE INDEX idx_fact_company_period ON fact_financial_metrics(company_id, period_id);
CREATE INDEX idx_fact_concept_period ON fact_financial_metrics(concept_id, period_id);

-- Dimension table indexes
CREATE INDEX idx_companies_ticker ON dim_companies(ticker);
CREATE INDEX idx_companies_sector ON dim_companies(sector);
CREATE INDEX idx_concepts_normalized ON dim_concepts(normalized_label);
CREATE INDEX idx_concepts_preferred_label ON dim_concepts(preferred_label);
CREATE INDEX idx_concepts_statement ON dim_concepts(statement_type);
CREATE INDEX idx_periods_fiscal_year ON dim_time_periods(fiscal_year);
CREATE INDEX idx_periods_end_date ON dim_time_periods(end_date);
CREATE INDEX idx_periods_business_key ON dim_time_periods(business_key);
CREATE INDEX idx_periods_fiscal_year_type ON dim_time_periods(fiscal_year, period_type);
CREATE INDEX idx_filings_company_year ON dim_filings(company_id, fiscal_year_end);
CREATE INDEX idx_dimensions_json ON dim_xbrl_dimensions USING GIN(dimension_json);

-- Quality table indexes
CREATE INDEX idx_quality_filing ON data_quality_scores(filing_id);
CREATE INDEX idx_quality_check ON data_quality_scores(check_name);
CREATE INDEX idx_quality_passed ON data_quality_scores(check_passed);

-- Relationship table indexes
CREATE INDEX idx_calc_filing ON rel_calculation_hierarchy(filing_id);
CREATE INDEX idx_calc_parent ON rel_calculation_hierarchy(parent_concept_id);
CREATE INDEX idx_calc_child ON rel_calculation_hierarchy(child_concept_id);
CREATE INDEX idx_pres_filing ON rel_presentation_hierarchy(filing_id);
CREATE INDEX idx_pres_parent ON rel_presentation_hierarchy(parent_concept_id);
CREATE INDEX idx_pres_child ON rel_presentation_hierarchy(child_concept_id);
CREATE INDEX idx_pres_statement ON rel_presentation_hierarchy(statement_type);
CREATE INDEX idx_footnote_filing ON rel_footnote_references(filing_id);
CREATE INDEX idx_footnote_fact ON rel_footnote_references(fact_id);
CREATE INDEX idx_footnote_concept ON rel_footnote_references(concept_id);

-- Statement items indexes
CREATE INDEX idx_statement_items_filing ON rel_statement_items(filing_id);
CREATE INDEX idx_statement_items_concept ON rel_statement_items(concept_id);
CREATE INDEX idx_statement_items_type_order ON rel_statement_items(statement_type, display_order);
CREATE INDEX idx_statement_items_main ON rel_statement_items(filing_id, is_main_item, statement_type, display_order);

-- Statement-specific fact table indexes
CREATE INDEX idx_income_statement_filing ON fact_income_statement(filing_id);
CREATE INDEX idx_income_statement_concept ON fact_income_statement(concept_id);
CREATE INDEX idx_income_statement_period ON fact_income_statement(period_id);
CREATE INDEX idx_income_statement_order ON fact_income_statement(filing_id, display_order);

CREATE INDEX idx_balance_sheet_filing ON fact_balance_sheet(filing_id);
CREATE INDEX idx_balance_sheet_concept ON fact_balance_sheet(concept_id);
CREATE INDEX idx_balance_sheet_period ON fact_balance_sheet(period_id);
CREATE INDEX idx_balance_sheet_order ON fact_balance_sheet(filing_id, display_order);

CREATE INDEX idx_cash_flow_filing ON fact_cash_flow(filing_id);
CREATE INDEX idx_cash_flow_concept ON fact_cash_flow(concept_id);
CREATE INDEX idx_cash_flow_period ON fact_cash_flow(period_id);
CREATE INDEX idx_cash_flow_order ON fact_cash_flow(filing_id, display_order);

CREATE INDEX idx_comprehensive_income_filing ON fact_comprehensive_income(filing_id);
CREATE INDEX idx_comprehensive_income_concept ON fact_comprehensive_income(concept_id);
CREATE INDEX idx_comprehensive_income_period ON fact_comprehensive_income(period_id);
CREATE INDEX idx_comprehensive_income_order ON fact_comprehensive_income(filing_id, display_order);

CREATE INDEX idx_equity_statement_filing ON fact_equity_statement(filing_id);
CREATE INDEX idx_equity_statement_concept ON fact_equity_statement(concept_id);
CREATE INDEX idx_equity_statement_period ON fact_equity_statement(period_id);
CREATE INDEX idx_equity_statement_order ON fact_equity_statement(filing_id, display_order);

-- ============================================================================
-- VIEWS FOR COMMON QUERIES
-- ============================================================================

-- Consolidated facts only (no dimensional breakdowns)
-- NOTE: Includes synthetic ContextAxis dimensions (created from context_id to preserve multiple consolidated facts)
CREATE VIEW v_facts_consolidated AS
SELECT 
    f.fact_id,
    c.ticker,
    co.concept_name,
    co.normalized_label,
    t.fiscal_year,
    t.period_type,
    t.start_date,
    t.end_date,
    t.instant_date,
    f.value_numeric,
    f.value_text,
    f.unit_measure,
    fi.filing_type,
    fi.fiscal_year_end,
    f.context_id,
    CASE 
        WHEN f.dimension_id IS NULL THEN 'true_consolidated'
        WHEN d.axis_name = 'ContextAxis' THEN 'synthetic_consolidated'
        ELSE 'dimensional'
    END as consolidation_type
FROM fact_financial_metrics f
JOIN dim_companies c ON f.company_id = c.company_id
JOIN dim_concepts co ON f.concept_id = co.concept_id
JOIN dim_time_periods t ON f.period_id = t.period_id
JOIN dim_filings fi ON f.filing_id = fi.filing_id
LEFT JOIN dim_xbrl_dimensions d ON f.dimension_id = d.dimension_id
WHERE f.dimension_id IS NULL 
   OR (f.dimension_id IS NOT NULL AND d.axis_name = 'ContextAxis'); -- Includes synthetic consolidated facts

-- All facts with dimensional breakdowns
CREATE VIEW v_facts_with_dimensions AS
SELECT 
    f.fact_id,
    c.ticker,
    co.concept_name,
    co.normalized_label,
    t.fiscal_year,
    t.period_type,
    t.start_date,
    t.end_date,
    f.value_numeric,
    f.value_text,
    f.unit_measure,
    d.dimension_json,
    d.axis_name,
    d.member_name,
    fi.filing_type
FROM fact_financial_metrics f
JOIN dim_companies c ON f.company_id = c.company_id
JOIN dim_concepts co ON f.concept_id = co.concept_id
JOIN dim_time_periods t ON f.period_id = t.period_id
JOIN dim_filings fi ON f.filing_id = fi.filing_id
JOIN dim_xbrl_dimensions d ON f.dimension_id = d.dimension_id
WHERE f.dimension_id IS NOT NULL; -- Only dimensional facts

-- Data quality summary
CREATE VIEW v_data_quality_summary AS
SELECT 
    c.ticker,
    fi.filing_type,
    fi.fiscal_year_end,
    COUNT(*) as total_checks,
    SUM(CASE WHEN dq.check_passed THEN 1 ELSE 0 END) as checks_passed,
    ROUND(100.0 * SUM(CASE WHEN dq.check_passed THEN 1 ELSE 0 END) / COUNT(*), 1) as pass_rate
FROM data_quality_scores dq
JOIN dim_filings fi ON dq.filing_id = fi.filing_id
JOIN dim_companies c ON fi.company_id = c.company_id
GROUP BY c.ticker, fi.filing_type, fi.fiscal_year_end;

-- ============================================================================
-- DEDUPLICATED VIEW (PRIMARY VIEW FOR BUSINESS INTELLIGENCE)
-- ============================================================================
-- 
-- Purpose: Eliminate duplicate facts where multiple XBRL concepts map to the same 
--          normalized_label with identical values.
--
-- Example: Assets and LiabilitiesAndStockholdersEquity both map to 'total_assets' 
--          with identical value ($352.6B) - this view shows only one.
--
-- Design Decisions:
-- 1. ONLY deduplicates when values are TRULY IDENTICAL (< 0.01% difference)
-- 2. Uses deterministic priority (always picks same concept for consistency)
-- 3. Preserves all distinct values (0.3% diff = kept as separate rows)
-- 4. Raw facts table unchanged (validation can still see all source concepts)
--
-- Priority Order for Tiebreaking:
-- 1. Balance sheet totals: prefer 'Assets' over 'LiabilitiesAndStockholdersEquity'
-- 2. Income statement: prefer 'NetIncomeLoss' over alternatives
-- 3. Equity: prefer 'StockholdersEquity' over 'TotalEquity'
-- 4. General: prefer concept marked is_primary=TRUE
-- 5. Fallback: lowest concept_id (stable across reloads)

CREATE VIEW v_facts_deduplicated AS
WITH fact_groups AS (
    -- Group facts by the business key + value
    SELECT 
        f.fact_id,
        f.company_id,
        f.concept_id,
        f.filing_id,
        f.period_id,
        f.dimension_id,
        f.value_numeric,
        f.value_text,
        f.unit_measure,
        f.decimals,
        f.scale_int,
        f.xbrl_format,
        f.context_id,
        f.fact_id_xbrl,
        f.source_line,
        f.order_index,
        f.is_primary,
        co.concept_name,
        co.normalized_label,
        co.taxonomy,
        co.statement_type,
        t.fiscal_year,
        -- Concept priority (lower = higher priority)
        CASE co.concept_name
            -- Balance sheet equality pairs - prefer left side
            WHEN 'Assets' THEN 1
            WHEN 'LiabilitiesAndStockholdersEquity' THEN 2
            -- Net income variants - prefer core concept
            WHEN 'NetIncomeLoss' THEN 1
            WHEN 'ProfitLoss' THEN 2
            WHEN 'NetIncomeLossAvailableToCommonStockholdersBasic' THEN 3
            -- Equity variants - prefer standard term
            WHEN 'StockholdersEquity' THEN 1
            WHEN 'TotalEquity' THEN 2
            WHEN 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest' THEN 3
            -- Cash variants - prefer most comprehensive
            WHEN 'CashAndCashEquivalentsAtCarryingValue' THEN 1
            WHEN 'Cash' THEN 2
            -- Default: use is_primary flag and concept_id
            ELSE 99
        END as concept_priority,
        -- Generate group key for identical facts
        ROW_NUMBER() OVER (
            PARTITION BY 
                f.company_id,
                co.normalized_label,
                t.fiscal_year,
                f.dimension_id,
                -- Group by rounded value (handles rounding differences < 0.01%)
                ROUND(f.value_numeric::numeric, 2)
            ORDER BY 
                -- Prioritize based on concept name
                CASE co.concept_name
                    WHEN 'Assets' THEN 1
                    WHEN 'LiabilitiesAndStockholdersEquity' THEN 2
                    WHEN 'NetIncomeLoss' THEN 1
                    WHEN 'ProfitLoss' THEN 2
                    WHEN 'StockholdersEquity' THEN 1
                    WHEN 'TotalEquity' THEN 2
                    WHEN 'CashAndCashEquivalentsAtCarryingValue' THEN 1
                    WHEN 'Cash' THEN 2
                    ELSE 99
                END,
                -- Then by is_primary flag
                f.is_primary DESC NULLS LAST,
                -- Then by order_index (lower = more prominent in statement)
                f.order_index ASC NULLS LAST,
                -- Stable tiebreaker
                f.fact_id
        ) as row_num
    FROM fact_financial_metrics f
    JOIN dim_concepts co ON f.concept_id = co.concept_id
    JOIN dim_time_periods t ON f.period_id = t.period_id
    WHERE 
        -- Exclude text notes (already filtered in viewer, but good practice)
        co.normalized_label NOT LIKE '%_note'
        AND co.normalized_label NOT LIKE '%_disclosure%'
)
SELECT 
    fg.fact_id,
    fg.company_id,
    fg.concept_id,
    fg.filing_id,
    fg.period_id,
    fg.dimension_id,
    fg.value_numeric,
    fg.value_text,
    fg.unit_measure,
    fg.decimals,
    fg.scale_int,
    fg.xbrl_format,
    fg.context_id,
    fg.fact_id_xbrl,
    fg.source_line,
    fg.order_index,
    fg.is_primary,
    fg.concept_name,
    fg.normalized_label,
    fg.taxonomy,
    fg.statement_type,
    fg.fiscal_year
FROM fact_groups fg
WHERE fg.row_num = 1;  -- Keep only the highest-priority fact from each group

-- Create index on the view for performance (materialized-like behavior)
CREATE INDEX IF NOT EXISTS idx_dedup_company_label 
    ON fact_financial_metrics(company_id, concept_id) 
    WHERE is_primary = TRUE;

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function to get or create dimension_id from JSONB
CREATE OR REPLACE FUNCTION get_or_create_dimension(p_dimension_json JSONB)
RETURNS INTEGER AS $$
DECLARE
    v_dimension_id INTEGER;
    v_hash VARCHAR(64);
BEGIN
    -- If NULL or empty, return NULL (for consolidated facts)
    IF p_dimension_json IS NULL OR p_dimension_json = 'null'::jsonb OR p_dimension_json = '{}'::jsonb THEN
        RETURN NULL;
    END IF;
    
    -- Generate hash
    v_hash := md5(p_dimension_json::text);
    
    -- Try to find existing
    SELECT dimension_id INTO v_dimension_id
    FROM dim_xbrl_dimensions
    WHERE dimension_hash = v_hash;
    
    -- Create if not exists
    IF v_dimension_id IS NULL THEN
        INSERT INTO dim_xbrl_dimensions (dimension_json, dimension_hash)
        VALUES (p_dimension_json, v_hash)
        RETURNING dimension_id INTO v_dimension_id;
    END IF;
    
    RETURN v_dimension_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- BUSINESS KEY MAINTENANCE FUNCTIONS & TRIGGERS
-- ============================================================================

-- Function to populate denormalized business keys when fact is inserted/updated
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

-- Function to update denormalized columns when concept changes
CREATE OR REPLACE FUNCTION update_fact_normalized_label()
RETURNS TRIGGER AS $$
BEGIN
    -- Update all facts that reference this concept
    -- CRITICAL: Handle potential duplicates when updating normalized_label
    -- If updating would create a duplicate (same filing_id, normalized_label, fiscal_year, period_type, dimension_id),
    -- we need to merge or skip the update
    
    -- Strategy: Only update facts where the new normalized_label doesn't already exist
    -- for the same (filing_id, fiscal_year, period_type, dimension_id) combination
    UPDATE fact_financial_metrics fm
    SET normalized_label = NEW.normalized_label
    WHERE fm.concept_id = NEW.concept_id
      AND (fm.normalized_label IS NULL OR fm.normalized_label != NEW.normalized_label)
      -- CRITICAL: Only update if the new normalized_label doesn't already exist for this fact's context
      AND NOT EXISTS (
          SELECT 1
          FROM fact_financial_metrics existing
          WHERE existing.filing_id = fm.filing_id
            AND existing.normalized_label = NEW.normalized_label
            AND existing.fiscal_year = fm.fiscal_year
            AND existing.period_type = fm.period_type
            AND (existing.dimension_id = fm.dimension_id OR (existing.dimension_id IS NULL AND fm.dimension_id IS NULL))
            AND existing.fact_id != fm.fact_id  -- Exclude the fact being updated
      );
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Function to update denormalized columns when period changes
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

-- Triggers to maintain denormalized business keys
CREATE TRIGGER trigger_populate_fact_business_keys
    BEFORE INSERT OR UPDATE ON fact_financial_metrics
    FOR EACH ROW
    WHEN (NEW.normalized_label IS NULL OR NEW.fiscal_year IS NULL OR NEW.period_type IS NULL)
    EXECUTE FUNCTION populate_fact_business_keys();

CREATE TRIGGER trigger_update_fact_normalized_label
    AFTER UPDATE OF normalized_label ON dim_concepts
    FOR EACH ROW
    WHEN (OLD.normalized_label IS DISTINCT FROM NEW.normalized_label)
    EXECUTE FUNCTION update_fact_normalized_label();

CREATE TRIGGER trigger_update_fact_period_info
    AFTER UPDATE OF fiscal_year, period_type ON dim_time_periods
    FOR EACH ROW
    WHEN (OLD.fiscal_year IS DISTINCT FROM NEW.fiscal_year 
          OR OLD.period_type IS DISTINCT FROM NEW.period_type)
    EXECUTE FUNCTION update_fact_period_info();

-- ============================================================================
-- CALCULATED TOTALS VIEWS (for Missing Universal Metrics)
-- ============================================================================
-- These views calculate totals from components when companies don't report
-- them as single line items (especially IFRS companies).
-- Example: SNY revenue = RevenueFromSaleOfGoods + OtherRevenue

-- Note: This view is created here to ensure it exists after database initialization.
-- For now, we keep the logic simple - actual calculated totals should be handled
-- at query time or via materialized views if performance becomes an issue.

-- The calculated totals logic is handled in the UI/data viewer queries
-- by UNIONing actual facts with calculated values when needed.
-- This keeps the schema clean and avoids redundant data storage.

-- If performance requires it, we can create materialized views later:
-- CREATE MATERIALIZED VIEW v_calculated_totals AS ...
-- REFRESH MATERIALIZED VIEW v_calculated_totals;

-- ============================================================================
-- STATEMENT VIEWS (Template-Based Presentation Layer)
-- ============================================================================
-- These views combine templates + facts to replace denormalized fact tables
-- They provide a clean separation: templates define structure, facts provide data

-- Income Statement View
-- Combines dim_statement_templates with fact_financial_metrics
-- Uses rel_statement_overrides for filing-specific custom items
-- Usage: SELECT * FROM v_income_statement WHERE filing_id = X AND period_id = Y
CREATE VIEW v_income_statement AS
SELECT 
    f.filing_id,
    tp.period_id,
    COALESCE(so.item_order, st.item_order) as display_order,
    COALESCE(so.item_label, st.item_label) as item_label,
    COALESCE(so.normalized_label, st.normalized_label) as normalized_label,
    COALESCE(so.is_header, st.is_header) as is_header,
    COALESCE(so.is_spacer, st.is_spacer) as is_spacer,
    COALESCE(so.is_calculated, st.is_calculated) as is_calculated,
    COALESCE(so.hierarchy_level, st.hierarchy_level) as hierarchy_level,
    COALESCE(so.parent_item_order, st.parent_item_order) as parent_item_order,
    COALESCE(so.section_name, st.section_name) as section_name,
    co.concept_id,
    fm.value_numeric,
    fm.unit_measure,
    co.parent_concept_id,
    st.template_id,
    so.override_id,
    c.accounting_standard,
    st.format_type
FROM dim_statement_templates st
CROSS JOIN dim_filings f
JOIN dim_companies c ON f.company_id = c.company_id
LEFT JOIN rel_statement_overrides so ON 
    so.filing_id = f.filing_id 
    AND so.template_id = st.template_id
LEFT JOIN dim_concepts co ON 
    COALESCE(so.normalized_label, st.normalized_label) = co.normalized_label
CROSS JOIN dim_time_periods tp
LEFT JOIN fact_financial_metrics fm ON 
    fm.normalized_label = COALESCE(so.normalized_label, st.normalized_label)
    AND fm.filing_id = f.filing_id
    AND fm.period_id = tp.period_id
    AND fm.dimension_id IS NULL
WHERE st.statement_type = 'income_statement'
  AND st.format_type = COALESCE(
      CASE c.accounting_standard
          WHEN 'IFRS' THEN 'ifrs'
          WHEN 'US-GAAP' THEN 'us_gaap'
          ELSE 'standard'
      END,
      'standard'
  );

-- Balance Sheet View
-- Usage: SELECT * FROM v_balance_sheet WHERE filing_id = X AND period_id = Y ORDER BY side, display_order
CREATE VIEW v_balance_sheet AS
SELECT 
    f.filing_id,
    tp.period_id,
    COALESCE(so.item_order, st.item_order) as display_order,
    COALESCE(so.item_label, st.item_label) as item_label,
    COALESCE(so.normalized_label, st.normalized_label) as normalized_label,
    COALESCE(so.is_header, st.is_header) as is_header,
    COALESCE(so.is_spacer, st.is_spacer) as is_spacer,
    COALESCE(so.is_calculated, st.is_calculated) as is_calculated,
    COALESCE(so.hierarchy_level, st.hierarchy_level) as hierarchy_level,
    COALESCE(so.parent_item_order, st.parent_item_order) as parent_item_order,
    COALESCE(so.section_name, st.section_name) as section_name,
    COALESCE(so.side, st.side) as side,
    co.concept_id,
    fm.value_numeric,
    fm.unit_measure,
    co.parent_concept_id,
    st.template_id,
    so.override_id,
    c.accounting_standard,
    st.format_type
FROM dim_statement_templates st
CROSS JOIN dim_filings f
JOIN dim_companies c ON f.company_id = c.company_id
LEFT JOIN rel_statement_overrides so ON 
    so.filing_id = f.filing_id 
    AND so.template_id = st.template_id
LEFT JOIN dim_concepts co ON 
    COALESCE(so.normalized_label, st.normalized_label) = co.normalized_label
CROSS JOIN dim_time_periods tp
LEFT JOIN fact_financial_metrics fm ON 
    fm.normalized_label = COALESCE(so.normalized_label, st.normalized_label)
    AND fm.filing_id = f.filing_id
    AND fm.period_id = tp.period_id
    AND fm.dimension_id IS NULL
WHERE st.statement_type = 'balance_sheet'
  AND st.format_type = COALESCE(
      CASE c.accounting_standard
          WHEN 'IFRS' THEN 'ifrs'
          WHEN 'US-GAAP' THEN 'us_gaap'
          ELSE 'standard'
      END,
      'standard'
  );

-- Cash Flow Statement View
-- Usage: SELECT * FROM v_cash_flow WHERE filing_id = X AND period_id = Y ORDER BY display_order
CREATE VIEW v_cash_flow AS
SELECT 
    f.filing_id,
    tp.period_id,
    COALESCE(so.item_order, st.item_order) as display_order,
    COALESCE(so.item_label, st.item_label) as item_label,
    COALESCE(so.normalized_label, st.normalized_label) as normalized_label,
    COALESCE(so.is_header, st.is_header) as is_header,
    COALESCE(so.is_spacer, st.is_spacer) as is_spacer,
    COALESCE(so.is_calculated, st.is_calculated) as is_calculated,
    COALESCE(so.hierarchy_level, st.hierarchy_level) as hierarchy_level,
    COALESCE(so.parent_item_order, st.parent_item_order) as parent_item_order,
    COALESCE(so.section_name, st.section_name) as section_name,
    co.concept_id,
    fm.value_numeric,
    fm.unit_measure,
    co.parent_concept_id,
    st.template_id,
    so.override_id,
    c.accounting_standard,
    st.format_type
FROM dim_statement_templates st
CROSS JOIN dim_filings f
JOIN dim_companies c ON f.company_id = c.company_id
LEFT JOIN rel_statement_overrides so ON 
    so.filing_id = f.filing_id 
    AND so.template_id = st.template_id
LEFT JOIN dim_concepts co ON 
    COALESCE(so.normalized_label, st.normalized_label) = co.normalized_label
CROSS JOIN dim_time_periods tp
LEFT JOIN fact_financial_metrics fm ON 
    fm.normalized_label = COALESCE(so.normalized_label, st.normalized_label)
    AND fm.filing_id = f.filing_id
    AND fm.period_id = tp.period_id
    AND fm.dimension_id IS NULL
WHERE st.statement_type = 'cash_flow'
  AND st.format_type = COALESCE(
      CASE c.accounting_standard
          WHEN 'IFRS' THEN 'ifrs'
          WHEN 'US-GAAP' THEN 'us_gaap'
          ELSE 'standard'
      END,
      'standard'
  );

-- Comprehensive Income View
-- Usage: SELECT * FROM v_comprehensive_income WHERE filing_id = X AND period_id = Y ORDER BY display_order
CREATE VIEW v_comprehensive_income AS
SELECT 
    f.filing_id,
    tp.period_id,
    COALESCE(so.item_order, st.item_order) as display_order,
    COALESCE(so.item_label, st.item_label) as item_label,
    COALESCE(so.normalized_label, st.normalized_label) as normalized_label,
    COALESCE(so.is_header, st.is_header) as is_header,
    COALESCE(so.is_spacer, st.is_spacer) as is_spacer,
    COALESCE(so.is_calculated, st.is_calculated) as is_calculated,
    COALESCE(so.hierarchy_level, st.hierarchy_level) as hierarchy_level,
    COALESCE(so.parent_item_order, st.parent_item_order) as parent_item_order,
    COALESCE(so.section_name, st.section_name) as section_name,
    co.concept_id,
    fm.value_numeric,
    fm.unit_measure,
    co.parent_concept_id,
    st.template_id,
    so.override_id,
    c.accounting_standard,
    st.format_type
FROM dim_statement_templates st
CROSS JOIN dim_filings f
JOIN dim_companies c ON f.company_id = c.company_id
LEFT JOIN rel_statement_overrides so ON 
    so.filing_id = f.filing_id 
    AND so.template_id = st.template_id
LEFT JOIN dim_concepts co ON 
    COALESCE(so.normalized_label, st.normalized_label) = co.normalized_label
CROSS JOIN dim_time_periods tp
LEFT JOIN fact_financial_metrics fm ON 
    fm.normalized_label = COALESCE(so.normalized_label, st.normalized_label)
    AND fm.filing_id = f.filing_id
    AND fm.period_id = tp.period_id
    AND fm.dimension_id IS NULL
WHERE st.statement_type = 'comprehensive_income'
  AND st.format_type = COALESCE(
      CASE c.accounting_standard
          WHEN 'IFRS' THEN 'ifrs'
          WHEN 'US-GAAP' THEN 'us_gaap'
          ELSE 'standard'
      END,
      'standard'
  );

-- Equity Statement View
-- Usage: SELECT * FROM v_equity_statement WHERE filing_id = X AND period_id = Y ORDER BY display_order
CREATE VIEW v_equity_statement AS
SELECT 
    f.filing_id,
    tp.period_id,
    COALESCE(so.item_order, st.item_order) as display_order,
    COALESCE(so.item_label, st.item_label) as item_label,
    COALESCE(so.normalized_label, st.normalized_label) as normalized_label,
    COALESCE(so.is_header, st.is_header) as is_header,
    COALESCE(so.is_spacer, st.is_spacer) as is_spacer,
    COALESCE(so.is_calculated, st.is_calculated) as is_calculated,
    COALESCE(so.hierarchy_level, st.hierarchy_level) as hierarchy_level,
    COALESCE(so.parent_item_order, st.parent_item_order) as parent_item_order,
    COALESCE(so.section_name, st.section_name) as section_name,
    co.concept_id,
    fm.value_numeric,
    fm.unit_measure,
    co.parent_concept_id,
    st.template_id,
    so.override_id,
    c.accounting_standard,
    st.format_type
FROM dim_statement_templates st
CROSS JOIN dim_filings f
JOIN dim_companies c ON f.company_id = c.company_id
LEFT JOIN rel_statement_overrides so ON 
    so.filing_id = f.filing_id 
    AND so.template_id = st.template_id
LEFT JOIN dim_concepts co ON 
    COALESCE(so.normalized_label, st.normalized_label) = co.normalized_label
CROSS JOIN dim_time_periods tp
LEFT JOIN fact_financial_metrics fm ON 
    fm.normalized_label = COALESCE(so.normalized_label, st.normalized_label)
    AND fm.filing_id = f.filing_id
    AND fm.period_id = tp.period_id
    AND fm.dimension_id IS NULL
WHERE st.statement_type = 'equity_statement'
  AND st.format_type = COALESCE(
      CASE c.accounting_standard
          WHEN 'IFRS' THEN 'ifrs'
          WHEN 'US-GAAP' THEN 'us_gaap'
          ELSE 'standard'
      END,
      'standard'
  );

-- ============================================================================
-- STATEMENT FUNCTIONS (Parameterized Views)
-- ============================================================================
-- SQL functions that return statement data for a specific filing and period
-- These replace the CROSS JOIN views with efficient parameterized queries

-- Income Statement Function
CREATE OR REPLACE FUNCTION get_income_statement(p_filing_id INTEGER, p_period_id INTEGER)
RETURNS TABLE (
    filing_id INTEGER,
    period_id INTEGER,
    display_order INTEGER,
    item_label VARCHAR,
    normalized_label VARCHAR,
    is_header BOOLEAN,
    is_spacer BOOLEAN,
    is_calculated BOOLEAN,
    hierarchy_level INTEGER,
    parent_item_order INTEGER,
    section_name VARCHAR,
    concept_id INTEGER,
    value_numeric DOUBLE PRECISION,
    unit_measure VARCHAR,
    parent_concept_id INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        p_filing_id::INTEGER as filing_id,
        p_period_id::INTEGER as period_id,
        COALESCE(so.item_order, st.item_order) as display_order,
        COALESCE(so.item_label, st.item_label) as item_label,
        COALESCE(so.normalized_label, st.normalized_label) as normalized_label,
        COALESCE(so.is_header, st.is_header) as is_header,
        COALESCE(so.is_spacer, st.is_spacer) as is_spacer,
        COALESCE(so.is_calculated, st.is_calculated) as is_calculated,
        COALESCE(so.hierarchy_level, st.hierarchy_level) as hierarchy_level,
        COALESCE(so.parent_item_order, st.parent_item_order) as parent_item_order,
        COALESCE(so.section_name, st.section_name) as section_name,
        co.concept_id,
        fm.value_numeric,
        fm.unit_measure,
        co.parent_concept_id
    FROM dim_statement_templates st
    JOIN dim_filings f ON f.filing_id = p_filing_id
    JOIN dim_companies c ON f.company_id = c.company_id
    LEFT JOIN rel_statement_overrides so ON 
        so.filing_id = p_filing_id 
        AND so.template_id = st.template_id
    LEFT JOIN dim_concepts co ON 
        COALESCE(so.normalized_label, st.normalized_label) = co.normalized_label
    LEFT JOIN fact_financial_metrics fm ON 
        fm.normalized_label = COALESCE(so.normalized_label, st.normalized_label)
        AND fm.filing_id = p_filing_id
        AND fm.period_id = p_period_id
        AND fm.dimension_id IS NULL
    WHERE st.statement_type = 'income_statement'
      AND st.format_type = COALESCE(
          CASE c.accounting_standard
              WHEN 'IFRS' THEN 'ifrs'
              WHEN 'US-GAAP' THEN 'us_gaap'
              ELSE 'standard'
          END,
          'standard'
      )
    ORDER BY COALESCE(so.item_order, st.item_order);
END;
$$ LANGUAGE plpgsql;

-- Balance Sheet Function
CREATE OR REPLACE FUNCTION get_balance_sheet(p_filing_id INTEGER, p_period_id INTEGER)
RETURNS TABLE (
    filing_id INTEGER,
    period_id INTEGER,
    display_order INTEGER,
    item_label VARCHAR,
    normalized_label VARCHAR,
    is_header BOOLEAN,
    is_spacer BOOLEAN,
    is_calculated BOOLEAN,
    hierarchy_level INTEGER,
    parent_item_order INTEGER,
    section_name VARCHAR,
    side VARCHAR,
    concept_id INTEGER,
    value_numeric DOUBLE PRECISION,
    unit_measure VARCHAR,
    parent_concept_id INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        p_filing_id::INTEGER as filing_id,
        p_period_id::INTEGER as period_id,
        COALESCE(so.item_order, st.item_order) as display_order,
        COALESCE(so.item_label, st.item_label) as item_label,
        COALESCE(so.normalized_label, st.normalized_label) as normalized_label,
        COALESCE(so.is_header, st.is_header) as is_header,
        COALESCE(so.is_spacer, st.is_spacer) as is_spacer,
        COALESCE(so.is_calculated, st.is_calculated) as is_calculated,
        COALESCE(so.hierarchy_level, st.hierarchy_level) as hierarchy_level,
        COALESCE(so.parent_item_order, st.parent_item_order) as parent_item_order,
        COALESCE(so.section_name, st.section_name) as section_name,
        COALESCE(so.side, st.side) as side,
        co.concept_id,
        fm.value_numeric,
        fm.unit_measure,
        co.parent_concept_id
    FROM dim_statement_templates st
    JOIN dim_filings f ON f.filing_id = p_filing_id
    JOIN dim_companies c ON f.company_id = c.company_id
    LEFT JOIN rel_statement_overrides so ON 
        so.filing_id = p_filing_id 
        AND so.template_id = st.template_id
    LEFT JOIN dim_concepts co ON 
        COALESCE(so.normalized_label, st.normalized_label) = co.normalized_label
    LEFT JOIN fact_financial_metrics fm ON 
        fm.normalized_label = COALESCE(so.normalized_label, st.normalized_label)
        AND fm.filing_id = p_filing_id
        AND fm.period_id = p_period_id
        AND fm.dimension_id IS NULL
    WHERE st.statement_type = 'balance_sheet'
      AND st.format_type = COALESCE(
          CASE c.accounting_standard
              WHEN 'IFRS' THEN 'ifrs'
              WHEN 'US-GAAP' THEN 'us_gaap'
              ELSE 'standard'
          END,
          'standard'
      )
    ORDER BY COALESCE(so.side, st.side), COALESCE(so.item_order, st.item_order);
END;
$$ LANGUAGE plpgsql;

-- Cash Flow Function
CREATE OR REPLACE FUNCTION get_cash_flow(p_filing_id INTEGER, p_period_id INTEGER)
RETURNS TABLE (
    filing_id INTEGER,
    period_id INTEGER,
    display_order INTEGER,
    item_label VARCHAR,
    normalized_label VARCHAR,
    is_header BOOLEAN,
    is_spacer BOOLEAN,
    is_calculated BOOLEAN,
    hierarchy_level INTEGER,
    parent_item_order INTEGER,
    section_name VARCHAR,
    concept_id INTEGER,
    value_numeric DOUBLE PRECISION,
    unit_measure VARCHAR,
    parent_concept_id INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        p_filing_id::INTEGER as filing_id,
        p_period_id::INTEGER as period_id,
        COALESCE(so.item_order, st.item_order) as display_order,
        COALESCE(so.item_label, st.item_label) as item_label,
        COALESCE(so.normalized_label, st.normalized_label) as normalized_label,
        COALESCE(so.is_header, st.is_header) as is_header,
        COALESCE(so.is_spacer, st.is_spacer) as is_spacer,
        COALESCE(so.is_calculated, st.is_calculated) as is_calculated,
        COALESCE(so.hierarchy_level, st.hierarchy_level) as hierarchy_level,
        COALESCE(so.parent_item_order, st.parent_item_order) as parent_item_order,
        COALESCE(so.section_name, st.section_name) as section_name,
        co.concept_id,
        fm.value_numeric,
        fm.unit_measure,
        co.parent_concept_id
    FROM dim_statement_templates st
    JOIN dim_filings f ON f.filing_id = p_filing_id
    JOIN dim_companies c ON f.company_id = c.company_id
    LEFT JOIN rel_statement_overrides so ON 
        so.filing_id = p_filing_id 
        AND so.template_id = st.template_id
    LEFT JOIN dim_concepts co ON 
        COALESCE(so.normalized_label, st.normalized_label) = co.normalized_label
    LEFT JOIN fact_financial_metrics fm ON 
        fm.normalized_label = COALESCE(so.normalized_label, st.normalized_label)
        AND fm.filing_id = p_filing_id
        AND fm.period_id = p_period_id
        AND fm.dimension_id IS NULL
    WHERE st.statement_type = 'cash_flow'
      AND st.format_type = COALESCE(
          CASE c.accounting_standard
              WHEN 'IFRS' THEN 'ifrs'
              WHEN 'US-GAAP' THEN 'us_gaap'
              ELSE 'standard'
          END,
          'standard'
      )
    ORDER BY COALESCE(so.item_order, st.item_order);
END;
$$ LANGUAGE plpgsql;

-- Comprehensive Income Function
CREATE OR REPLACE FUNCTION get_comprehensive_income(p_filing_id INTEGER, p_period_id INTEGER)
RETURNS TABLE (
    filing_id INTEGER,
    period_id INTEGER,
    display_order INTEGER,
    item_label VARCHAR,
    normalized_label VARCHAR,
    is_header BOOLEAN,
    is_spacer BOOLEAN,
    is_calculated BOOLEAN,
    hierarchy_level INTEGER,
    parent_item_order INTEGER,
    section_name VARCHAR,
    concept_id INTEGER,
    value_numeric DOUBLE PRECISION,
    unit_measure VARCHAR,
    parent_concept_id INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        p_filing_id::INTEGER as filing_id,
        p_period_id::INTEGER as period_id,
        COALESCE(so.item_order, st.item_order) as display_order,
        COALESCE(so.item_label, st.item_label) as item_label,
        COALESCE(so.normalized_label, st.normalized_label) as normalized_label,
        COALESCE(so.is_header, st.is_header) as is_header,
        COALESCE(so.is_spacer, st.is_spacer) as is_spacer,
        COALESCE(so.is_calculated, st.is_calculated) as is_calculated,
        COALESCE(so.hierarchy_level, st.hierarchy_level) as hierarchy_level,
        COALESCE(so.parent_item_order, st.parent_item_order) as parent_item_order,
        COALESCE(so.section_name, st.section_name) as section_name,
        co.concept_id,
        fm.value_numeric,
        fm.unit_measure,
        co.parent_concept_id
    FROM dim_statement_templates st
    JOIN dim_filings f ON f.filing_id = p_filing_id
    JOIN dim_companies c ON f.company_id = c.company_id
    LEFT JOIN rel_statement_overrides so ON 
        so.filing_id = p_filing_id 
        AND so.template_id = st.template_id
    LEFT JOIN dim_concepts co ON 
        COALESCE(so.normalized_label, st.normalized_label) = co.normalized_label
    LEFT JOIN fact_financial_metrics fm ON 
        fm.normalized_label = COALESCE(so.normalized_label, st.normalized_label)
        AND fm.filing_id = p_filing_id
        AND fm.period_id = p_period_id
        AND fm.dimension_id IS NULL
    WHERE st.statement_type = 'comprehensive_income'
      AND st.format_type = COALESCE(
          CASE c.accounting_standard
              WHEN 'IFRS' THEN 'ifrs'
              WHEN 'US-GAAP' THEN 'us_gaap'
              ELSE 'standard'
          END,
          'standard'
      )
    ORDER BY COALESCE(so.item_order, st.item_order);
END;
$$ LANGUAGE plpgsql;

-- Equity Statement Function
CREATE OR REPLACE FUNCTION get_equity_statement(p_filing_id INTEGER, p_period_id INTEGER)
RETURNS TABLE (
    filing_id INTEGER,
    period_id INTEGER,
    display_order INTEGER,
    item_label VARCHAR,
    normalized_label VARCHAR,
    is_header BOOLEAN,
    is_spacer BOOLEAN,
    is_calculated BOOLEAN,
    hierarchy_level INTEGER,
    parent_item_order INTEGER,
    section_name VARCHAR,
    concept_id INTEGER,
    value_numeric DOUBLE PRECISION,
    unit_measure VARCHAR,
    parent_concept_id INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        p_filing_id::INTEGER as filing_id,
        p_period_id::INTEGER as period_id,
        COALESCE(so.item_order, st.item_order) as display_order,
        COALESCE(so.item_label, st.item_label) as item_label,
        COALESCE(so.normalized_label, st.normalized_label) as normalized_label,
        COALESCE(so.is_header, st.is_header) as is_header,
        COALESCE(so.is_spacer, st.is_spacer) as is_spacer,
        COALESCE(so.is_calculated, st.is_calculated) as is_calculated,
        COALESCE(so.hierarchy_level, st.hierarchy_level) as hierarchy_level,
        COALESCE(so.parent_item_order, st.parent_item_order) as parent_item_order,
        COALESCE(so.section_name, st.section_name) as section_name,
        co.concept_id,
        fm.value_numeric,
        fm.unit_measure,
        co.parent_concept_id
    FROM dim_statement_templates st
    JOIN dim_filings f ON f.filing_id = p_filing_id
    JOIN dim_companies c ON f.company_id = c.company_id
    LEFT JOIN rel_statement_overrides so ON 
        so.filing_id = p_filing_id 
        AND so.template_id = st.template_id
    LEFT JOIN dim_concepts co ON 
        COALESCE(so.normalized_label, st.normalized_label) = co.normalized_label
    LEFT JOIN fact_financial_metrics fm ON 
        fm.normalized_label = COALESCE(so.normalized_label, st.normalized_label)
        AND fm.filing_id = p_filing_id
        AND fm.period_id = p_period_id
        AND fm.dimension_id IS NULL
    WHERE st.statement_type = 'equity_statement'
      AND st.format_type = COALESCE(
          CASE c.accounting_standard
              WHEN 'IFRS' THEN 'ifrs'
              WHEN 'US-GAAP' THEN 'us_gaap'
              ELSE 'standard'
          END,
          'standard'
      )
    ORDER BY COALESCE(so.item_order, st.item_order);
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- GRANTS (for Superset and application access)
-- ============================================================================

GRANT SELECT ON ALL TABLES IN SCHEMA public TO superset;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO superset;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO superset;

-- ============================================================================
-- COMPLETION
-- ============================================================================

SELECT 'FinSight data warehouse schema created successfully' AS status;

