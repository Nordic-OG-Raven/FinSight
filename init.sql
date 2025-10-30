-- Database initialization for local development
-- This script creates the necessary tables for FinSight

-- Financial facts table (mirrors your existing structure)
CREATE TABLE IF NOT EXISTS financial_facts (
    id SERIAL PRIMARY KEY,
    company VARCHAR(10) NOT NULL,
    concept VARCHAR(500) NOT NULL,
    normalized_label VARCHAR(500),
    value NUMERIC,
    unit VARCHAR(50),
    period_start DATE,
    period_end DATE,
    fiscal_year_end DATE,
    instant_date DATE,
    context_id VARCHAR(500),
    decimals INTEGER,
    taxonomy VARCHAR(100),
    filing_type VARCHAR(10),
    filing_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_fact UNIQUE (company, concept, context_id, period_end)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_company ON financial_facts(company);
CREATE INDEX IF NOT EXISTS idx_fiscal_year ON financial_facts(fiscal_year_end);
CREATE INDEX IF NOT EXISTS idx_normalized_label ON financial_facts(normalized_label);
CREATE INDEX IF NOT EXISTS idx_company_year ON financial_facts(company, fiscal_year_end);

-- Request tracking table (for quota management)
CREATE TABLE IF NOT EXISTS request_log (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    year INTEGER NOT NULL,
    request_type VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL,
    processing_time_seconds NUMERIC,
    fact_count INTEGER,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_request_log_created ON request_log(created_at);

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO superset;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO superset;

