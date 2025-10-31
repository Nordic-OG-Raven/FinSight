-- ============================================================================
-- FinSight Financial Data Warehouse Schema
-- Star Schema Design for XBRL Financial Data
-- ============================================================================

-- Drop existing tables (in correct order due to foreign keys)
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
DROP TABLE IF EXISTS taxonomy_mappings CASCADE;

-- ============================================================================
-- DIMENSION TABLES
-- ============================================================================

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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- XBRL concepts dimension table
CREATE TABLE dim_concepts (
    concept_id SERIAL PRIMARY KEY,
    concept_name TEXT NOT NULL,
    taxonomy VARCHAR(50) NOT NULL,
    normalized_label VARCHAR(200),
    concept_type VARCHAR(50),
    balance_type VARCHAR(20), -- debit, credit, NA
    period_type VARCHAR(20), -- instant, duration
    data_type VARCHAR(50),
    is_abstract BOOLEAN DEFAULT FALSE,
    statement_type VARCHAR(50), -- income_statement, balance_sheet, cash_flow, etc.
    UNIQUE(concept_name, taxonomy)
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
    
    -- Fact values
    value_numeric DOUBLE PRECISION,
    value_text TEXT,
    
    -- Units and scaling
    unit_measure VARCHAR(50),
    decimals VARCHAR(20),
    scale_int INTEGER, -- e.g., 6 for millions, 3 for thousands
    xbrl_format VARCHAR(100), -- e.g., 'ixt:num-dot-decimal'
    
    -- XBRL metadata
    context_id TEXT,
    fact_id_xbrl VARCHAR(100),
    source_line INTEGER,
    order_index INTEGER, -- Fact ordering within document sections
    is_primary BOOLEAN DEFAULT TRUE, -- TRUE if primary occurrence (not a duplicate reference)
    
    -- Provenance
    extraction_method VARCHAR(50) DEFAULT 'arelle',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Business key constraint: prevent duplicate facts and duplicate re-loads
    UNIQUE(filing_id, concept_id, period_id, dimension_id, fact_id_xbrl)
);

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

-- Taxonomy normalization mappings
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
    UNIQUE(filing_id, parent_concept_id, child_concept_id)
);

-- Presentation hierarchy (how concepts are organized in financial statements)
-- Example: Balance Sheet > Current Assets > Cash
CREATE TABLE rel_presentation_hierarchy (
    presentation_id SERIAL PRIMARY KEY,
    filing_id INTEGER NOT NULL REFERENCES dim_filings(filing_id),
    parent_concept_id INTEGER REFERENCES dim_concepts(concept_id), -- NULL for root nodes
    child_concept_id INTEGER NOT NULL REFERENCES dim_concepts(concept_id),
    order_index INTEGER NOT NULL, -- Order within statement section
    preferred_label VARCHAR(100), -- Label role (e.g., 'http://www.xbrl.org/2003/role/label')
    statement_type VARCHAR(50), -- balance_sheet, income_statement, cash_flow, etc.
    arcrole VARCHAR(200), -- XBRL arcrole URI (usually parent-child)
    priority INTEGER DEFAULT 0,
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
CREATE INDEX idx_concepts_statement ON dim_concepts(statement_type);
CREATE INDEX idx_periods_fiscal_year ON dim_time_periods(fiscal_year);
CREATE INDEX idx_periods_end_date ON dim_time_periods(end_date);
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

-- ============================================================================
-- VIEWS FOR COMMON QUERIES
-- ============================================================================

-- Consolidated facts only (no dimensional breakdowns)
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
    fi.fiscal_year_end
FROM fact_financial_metrics f
JOIN dim_companies c ON f.company_id = c.company_id
JOIN dim_concepts co ON f.concept_id = co.concept_id
JOIN dim_time_periods t ON f.period_id = t.period_id
JOIN dim_filings fi ON f.filing_id = fi.filing_id
WHERE f.dimension_id IS NULL; -- Only consolidated totals

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
-- GRANTS (for Superset and application access)
-- ============================================================================

GRANT SELECT ON ALL TABLES IN SCHEMA public TO superset;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO superset;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO superset;

-- ============================================================================
-- COMPLETION
-- ============================================================================

SELECT 'FinSight data warehouse schema created successfully' AS status;

