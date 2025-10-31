# FinSight Data Warehouse Documentation

## Overview

FinSight uses a **star schema** data warehouse design optimized for OLAP queries and financial analysis. The schema follows data warehousing best practices with proper dimension tables, a central fact table, and supporting metadata tables.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     STAR SCHEMA DESIGN                      │
└─────────────────────────────────────────────────────────────┘

         ┌──────────────────┐
         │  dim_companies   │───┐
         └──────────────────┘   │
                                │
         ┌──────────────────┐   │
         │   dim_concepts   │───┤
         └──────────────────┘   │
                                │
         ┌──────────────────┐   │      ┌──────────────────────┐
         │ dim_time_periods │───┼─────>│ fact_financial_      │
         └──────────────────┘   │      │    metrics           │
                                │      └──────────────────────┘
         ┌──────────────────┐   │               │
         │   dim_filings    │───┤               │
         └──────────────────┘   │               v
                                │      ┌──────────────────────┐
         ┌──────────────────┐   │      │ data_quality_scores  │
         │ dim_xbrl_        │───┘      └──────────────────────┘
         │  dimensions      │
         └──────────────────┘
```

## Schema Tables

### Dimension Tables

#### 1. `dim_companies`
Master list of all companies in the warehouse.

| Column | Type | Description |
|--------|------|-------------|
| `company_id` | SERIAL PK | Unique company identifier |
| `ticker` | VARCHAR(20) UNIQUE | Stock ticker symbol |
| `company_name` | VARCHAR(200) | Full company name |
| `cik` | VARCHAR(20) | SEC Central Index Key |
| `sector` | VARCHAR(100) | Business sector |
| `industry` | VARCHAR(100) | Industry classification |
| `country` | VARCHAR(3) | ISO country code |
| `accounting_standard` | VARCHAR(20) | 'US-GAAP' or 'IFRS' |

**Business Rules:**
- One row per company
- Ticker is business key (unique, not null)
- Updated when company metadata changes

#### 2. `dim_concepts`
XBRL concept definitions (financial metrics like Revenue, Assets, etc.)

| Column | Type | Description |
|--------|------|-------------|
| `concept_id` | SERIAL PK | Unique concept identifier |
| `concept_name` | TEXT | XBRL tag name (e.g., 'us-gaap:Revenues') |
| `taxonomy` | VARCHAR(50) | Taxonomy namespace |
| `normalized_label` | VARCHAR(200) | Standardized label for cross-company comparison |
| `concept_type` | VARCHAR(50) | Data type (monetary, shares, pure, etc.) |
| `balance_type` | VARCHAR(20) | 'debit', 'credit', or NULL |
| `period_type` | VARCHAR(20) | 'instant' or 'duration' |
| `statement_type` | VARCHAR(50) | Which financial statement |

**Business Rules:**
- One row per unique (concept_name, taxonomy) combination
- Normalized labels enable cross-taxonomy comparisons
- US-GAAP and IFRS concepts mapped to same normalized_label where equivalent

#### 3. `dim_time_periods`
Fiscal time periods for financial data.

| Column | Type | Description |
|--------|------|-------------|
| `period_id` | SERIAL PK | Unique period identifier |
| `period_type` | VARCHAR(20) | 'instant' or 'duration' |
| `start_date` | DATE | Period start (for duration) |
| `end_date` | DATE | Period end (for duration) |
| `instant_date` | DATE | Point-in-time date (for instant) |
| `fiscal_year` | INTEGER | Fiscal year |
| `fiscal_quarter` | INTEGER | Fiscal quarter (1-4) |
| `period_label` | VARCHAR(100) | Human-readable label |

**Business Rules:**
- One row per unique time period
- Either (start_date, end_date) OR instant_date is populated
- Enables time-series analysis and YoY comparisons

#### 4. `dim_filings`
SEC filing metadata.

| Column | Type | Description |
|--------|------|-------------|
| `filing_id` | SERIAL PK | Unique filing identifier |
| `company_id` | INTEGER FK | References dim_companies |
| `filing_type` | VARCHAR(20) | '10-K', '20-F', '10-Q' |
| `fiscal_year_end` | DATE | Fiscal year end date |
| `filing_date` | DATE | SEC acceptance date |
| `source_url` | TEXT | URL to XBRL filing |
| `accession_number` | VARCHAR(50) | SEC accession number |
| `validation_score` | NUMERIC(5,2) | Data quality score (0-100) |
| `completeness_score` | NUMERIC(5,2) | Extraction completeness (0-100) |

**Business Rules:**
- One row per filing
- Unique constraint on (company_id, filing_type, fiscal_year_end)
- Prevents duplicate filing extractions

#### 5. `dim_xbrl_dimensions`
XBRL dimensional breakdowns (segments, products, geographies).

| Column | Type | Description |
|--------|------|-------------|
| `dimension_id` | SERIAL PK | Unique dimension identifier |
| `dimension_json` | JSONB | Full dimension structure |
| `dimension_hash` | VARCHAR(64) | MD5 hash for deduplication |
| `axis_name` | TEXT | Dimension axis |
| `member_name` | TEXT | Dimension member |
| `dimension_description` | TEXT | Human-readable description |

**Business Rules:**
- One row per unique dimensional breakdown
- NULL dimension_id in fact table = consolidated total
- JSONB allows flexible dimensional structures

### Fact Table

#### `fact_financial_metrics`
Core financial data points (the heart of the warehouse).

| Column | Type | Description |
|--------|------|-------------|
| `fact_id` | SERIAL PK | Unique fact identifier |
| `company_id` | INTEGER FK | References dim_companies |
| `concept_id` | INTEGER FK | References dim_concepts |
| `period_id` | INTEGER FK | References dim_time_periods |
| `filing_id` | INTEGER FK | References dim_filings |
| `dimension_id` | INTEGER FK | References dim_xbrl_dimensions (NULL for consolidated) |
| `value_numeric` | DOUBLE PRECISION | Numeric value |
| `value_text` | TEXT | Text value (for non-numeric facts) |
| `unit_measure` | VARCHAR(50) | Currency or unit |
| `decimals` | VARCHAR(20) | XBRL decimals attribute |
| `scale_factor` | INTEGER | Scale (e.g., -6 for millions) |
| `context_id` | TEXT | XBRL context ID |

**Business Rules:**
- One row per unique financial fact
- UNIQUE constraint on (filing_id, concept_id, period_id, dimension_id)
- Prevents duplicate facts within same filing
- NULL dimension_id = consolidated (total) value
- Non-NULL dimension_id = segment/breakdown value

### Metadata Tables

#### `data_quality_scores`
Validation results for each filing.

| Column | Type | Description |
|--------|------|-------------|
| `quality_id` | SERIAL PK | Unique check identifier |
| `filing_id` | INTEGER FK | References dim_filings |
| `check_name` | VARCHAR(100) | Name of validation check |
| `check_passed` | BOOLEAN | TRUE if passed |
| `expected_value` | NUMERIC | Expected value |
| `actual_value` | NUMERIC | Actual value |
| `difference` | NUMERIC | Absolute difference |
| `difference_pct` | NUMERIC | Percentage difference |
| `severity` | VARCHAR(20) | 'critical', 'warning', 'info' |

**Business Rules:**
- Multiple rows per filing (one per check)
- Enables data quality tracking over time
- Used for filing validation score calculation

#### `taxonomy_mappings`
Cross-taxonomy concept mappings.

| Column | Type | Description |
|--------|------|-------------|
| `mapping_id` | SERIAL PK | Unique mapping identifier |
| `source_concept` | TEXT | Original XBRL concept |
| `source_taxonomy` | VARCHAR(50) | Source taxonomy |
| `normalized_label` | VARCHAR(200) | Standardized label |
| `confidence` | NUMERIC(3,2) | Mapping confidence (0-1) |
| `mapping_type` | VARCHAR(50) | 'exact', 'sum', 'derived' |

**Business Rules:**
- Enables cross-company comparisons across US-GAAP and IFRS
- Updated as new concepts are encountered
- Confidence score tracks mapping quality

## Views

### `v_facts_consolidated`
Pre-filtered view of only consolidated (non-dimensional) facts.

```sql
SELECT 
    c.ticker,
    co.normalized_label,
    t.fiscal_year,
    f.value_numeric,
    f.unit_measure
FROM fact_financial_metrics f
JOIN dim_companies c ON f.company_id = c.company_id
JOIN dim_concepts co ON f.concept_id = co.concept_id
JOIN dim_time_periods t ON f.period_id = t.period_id
WHERE f.dimension_id IS NULL;
```

**Use Case:** Quick cross-company comparisons without dimensional complexity.

### `v_facts_with_dimensions`
All facts including dimensional breakdowns.

**Use Case:** Segment analysis, geographic breakdowns, product-level data.

### `v_data_quality_summary`
Summary of validation results per filing.

**Use Case:** Data quality monitoring dashboard.

## Indexes

### Fact Table Indexes
- `idx_fact_company` - Filter by company
- `idx_fact_concept` - Filter by concept
- `idx_fact_period` - Time-series queries
- `idx_fact_company_concept` - Cross-sectional analysis
- `idx_fact_company_period` - Company time series

### Dimension Table Indexes
- `idx_companies_ticker` - Ticker lookup
- `idx_concepts_normalized` - Normalized label queries
- `idx_periods_fiscal_year` - Year-based filtering
- `idx_dimensions_json` - GIN index for JSONB queries

## Common Query Patterns

### 1. Get revenue for all companies in latest fiscal year

```sql
SELECT 
    c.ticker,
    t.fiscal_year,
    f.value_numeric / 1000000 as revenue_millions
FROM fact_financial_metrics f
JOIN dim_companies c ON f.company_id = c.company_id
JOIN dim_concepts co ON f.concept_id = co.concept_id
JOIN dim_time_periods t ON f.period_id = t.period_id
WHERE co.normalized_label = 'revenue'
  AND f.dimension_id IS NULL
  AND t.fiscal_year = (SELECT MAX(fiscal_year) FROM dim_time_periods)
ORDER BY f.value_numeric DESC;
```

### 2. Compare US-GAAP vs IFRS company metrics

```sql
SELECT 
    c.ticker,
    c.accounting_standard,
    co.normalized_label,
    AVG(f.value_numeric) as avg_value
FROM fact_financial_metrics f
JOIN dim_companies c ON f.company_id = c.company_id
JOIN dim_concepts co ON f.concept_id = co.concept_id
WHERE co.normalized_label IN ('revenue', 'net_income', 'total_assets')
  AND f.dimension_id IS NULL
GROUP BY c.ticker, c.accounting_standard, co.normalized_label;
```

### 3. Segment analysis with dimensions

```sql
SELECT 
    c.ticker,
    d.axis_name,
    d.member_name,
    f.value_numeric
FROM fact_financial_metrics f
JOIN dim_companies c ON f.company_id = c.company_id
JOIN dim_xbrl_dimensions d ON f.dimension_id = d.dimension_id
WHERE c.ticker = 'AAPL'
  AND d.axis_name = 'ProductOrServiceAxis';
```

### 4. Data quality overview

```sql
SELECT 
    c.ticker,
    fi.filing_type,
    fi.fiscal_year_end,
    fi.validation_score,
    fi.completeness_score,
    COUNT(dq.quality_id) as total_checks,
    SUM(CASE WHEN dq.check_passed THEN 1 ELSE 0 END) as checks_passed
FROM dim_filings fi
JOIN dim_companies c ON fi.company_id = c.company_id
LEFT JOIN data_quality_scores dq ON fi.filing_id = dq.filing_id
GROUP BY c.ticker, fi.filing_type, fi.fiscal_year_end, fi.validation_score, fi.completeness_score
ORDER BY fi.validation_score ASC;
```

## Data Loading Process

### Complete Setup (First Time)

```bash
# 1. Initialize the star schema
./database/init_db.sh

# 2. Extract and load financial data (includes taxonomy normalization)
./database/load_financial_data.sh

# 3. Apply taxonomy normalization to concepts (if not already done)
/Users/jonas/FinSight/.venv/bin/python -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from src.utils.taxonomy_mappings import get_normalized_label
from config import *
import psycopg2

conn = psycopg2.connect(host=POSTGRES_HOST, port=POSTGRES_PORT, user=POSTGRES_USER, password=POSTGRES_PASSWORD, database=POSTGRES_DB)
cur = conn.cursor()
cur.execute('SELECT concept_id, concept_name FROM dim_concepts')
for concept_id, concept_name in cur.fetchall():
    label = get_normalized_label(concept_name)
    if label:
        cur.execute('UPDATE dim_concepts SET normalized_label = %s WHERE concept_id = %s', (label, concept_id))
conn.commit()
print('✅ Taxonomy normalization applied')
"

# 4. Validate data quality (optional)
/Users/jonas/FinSight/.venv/bin/python -m src.validation.checks
```

### Quick Re-load (After Schema Exists)

```bash
# Just reload financial data (idempotent)
./database/load_financial_data.sh

# Or use the legacy wrapper
./bulk_load_to_db.sh
```

## Maintenance

### Backup
```bash
docker exec superset_db pg_dump -U superset finsight > backup_$(date +%Y%m%d).sql
```

### Restore
```bash
docker exec -i superset_db psql -U superset finsight < backup_20241029.sql
```

### Vacuum and Analyze
```bash
docker exec superset_db psql -U superset -d finsight -c "VACUUM ANALYZE;"
```

## Performance Considerations

1. **Fact Table Size**: Expect ~2,000-5,000 facts per company per filing
2. **Query Optimization**: Always filter by company_id or concept_id first
3. **Dimensional Queries**: Use `dimension_id IS NULL` for consolidated views
4. **Time Series**: Index on period_id enables fast temporal queries
5. **Normalization**: Use normalized_label for cross-company comparisons

## Future Enhancements

- [ ] Partition fact table by fiscal_year for very large datasets
- [ ] Add materialized views for common aggregations
- [ ] Implement slowly changing dimensions (SCD Type 2) for company changes
- [ ] Add data lineage tracking table
- [ ] Implement incremental loading with CDC

