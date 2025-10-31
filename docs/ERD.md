# FinSight Data Warehouse - Entity Relationship Diagram

## Star Schema ERD

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FINSIGHT DATA WAREHOUSE                              │
│                            Star Schema Design                                │
└─────────────────────────────────────────────────────────────────────────────┘


┌──────────────────────────┐
│    dim_companies         │
├──────────────────────────┤
│ PK company_id (SERIAL)   │◄────┐
│    ticker (UNIQUE)       │     │
│    company_name          │     │
│    cik                   │     │
│    sector                │     │
│    industry              │     │
│    country               │     │
│    accounting_standard   │     │
│    created_at            │     │
│    updated_at            │     │
└──────────────────────────┘     │
                                 │
                                 │
┌──────────────────────────┐     │
│    dim_concepts          │     │
├──────────────────────────┤     │
│ PK concept_id (SERIAL)   │◄────┤
│    concept_name          │     │
│    taxonomy              │     │
│    normalized_label      │     │
│    concept_type          │     │
│    balance_type          │     │
│    period_type           │     │
│    data_type             │     │
│    is_abstract           │     │
│    statement_type        │     │  -- inferred: balance_sheet, income_statement, cash_flow, equity_statement, notes, other
│ UK (concept_name,        │     │
│     taxonomy)            │     │
└──────────────────────────┘     │
                                 │
                                 │
┌──────────────────────────┐     │
│    dim_time_periods      │     │
├──────────────────────────┤     │
│ PK period_id (SERIAL)    │◄────┤
│    period_type           │     │
│    start_date            │     │
│    end_date              │     │
│    instant_date          │     │
│    fiscal_year           │     │         ┌────────────────────────────┐
│    fiscal_quarter        │     │         │  fact_financial_metrics    │
│    period_label          │     │         ├────────────────────────────┤
│ UK (period_type,         │     │         │ PK fact_id (SERIAL)        │
│     start_date,          │     ├────────►│ FK company_id (NOT NULL)   │
│     end_date,            │     │         │ FK concept_id (NOT NULL)   │
│     instant_date)        │     ├────────►│ FK period_id (NOT NULL)    │
└──────────────────────────┘     │         │ FK filing_id (NOT NULL)    │
                                 ├────────►│ FK dimension_id (NULL OK)  │
                                 │         │                            │
┌──────────────────────────┐     │         │    value_numeric (DOUBLE)  │
│    dim_filings           │     │         │    value_text              │
├──────────────────────────┤     │         │    unit_measure            │
│ PK filing_id (SERIAL)    │◄────┤         │    decimals                │
│ FK company_id            │─────┘         │    scale_int               │
│    filing_type           │               │    xbrl_format             │
│    fiscal_year_end       │               │    context_id              │
│    filing_date           │               │    fact_id_xbrl            │
│    source_url            │               │    source_line             │
│    accession_number      │               │    order_index             │
│    extraction_timestamp  │               │    is_primary (BOOL)       │
│    validation_score      │               │    extraction_method       │
│    completeness_score    │               │    created_at              │
│ UK (company_id,          │               │                            │
│     filing_type,         │               │ UK (filing_id, concept_id, │
│     fiscal_year_end)     │               │     period_id,             │
└──────────────────────────┘               │     dimension_id,          │
                                           │     fact_id_xbrl)          │
                                           └────────────────────────────┘
                                                        │
                                                        ▼
┌──────────────────────────┐                            │
│  dim_xbrl_dimensions     │                            │
├──────────────────────────┤                            │
│ PK dimension_id (SERIAL) │◄───────────────────────────┘
│    dimension_json (JSONB)│
│    dimension_hash (UNIQUE)│
│    axis_name             │
│    member_name           │
│    dimension_description │
└──────────────────────────┘


┌──────────────────────────┐              ┌────────────────────────────┐
│  data_quality_scores     │              │   taxonomy_mappings        │
├──────────────────────────┤              ├────────────────────────────┤
│ PK quality_id (SERIAL)   │              │ PK mapping_id (SERIAL)     │
│ FK filing_id             │──────┐       │    source_concept          │
│    check_name            │      │       │    source_taxonomy         │
│    check_passed          │      │       │    normalized_label        │
│    expected_value        │      │       │    confidence              │
│    actual_value          │      │       │    mapping_type            │
│    difference            │      │       │    notes                   │
│    difference_pct        │      │       │ UK (source_concept,        │
│    severity              │      │       │     source_taxonomy)       │
│    details (JSONB)       │      │       └────────────────────────────┘
│    checked_at            │      │
│ UK (filing_id,           │      │
│     check_name)          │      │
└──────────────────────────┘      │
                                  │
                                  │
                    ┌─────────────┘
                    │
                    ▼
          (References dim_filings)
```

## Relationships

### Star Schema (1 Fact, 5 Dimensions)

**Fact Table: `fact_financial_metrics`**
- **Many-to-One** → `dim_companies` (via `company_id`)
- **Many-to-One** → `dim_concepts` (via `concept_id`)
- **Many-to-One** → `dim_time_periods` (via `period_id`)
- **Many-to-One** → `dim_filings` (via `filing_id`)
- **Many-to-One** → `dim_xbrl_dimensions` (via `dimension_id`, **nullable**)

### Supporting Relationships

**dim_filings**
- **Many-to-One** → `dim_companies` (via `company_id`)

**data_quality_scores**
- **Many-to-One** → `dim_filings` (via `filing_id`)

## Key Constraints

### Primary Keys (Auto-increment SERIAL)
- All dimension tables have `{table}_id SERIAL PRIMARY KEY`
- Fact table has `fact_id SERIAL PRIMARY KEY`

### Foreign Keys
- `fact_financial_metrics.company_id` → `dim_companies.company_id`
- `fact_financial_metrics.concept_id` → `dim_concepts.concept_id`
- `fact_financial_metrics.period_id` → `dim_time_periods.period_id`
- `fact_financial_metrics.filing_id` → `dim_filings.filing_id`
- `fact_financial_metrics.dimension_id` → `dim_xbrl_dimensions.dimension_id` (nullable)
- `dim_filings.company_id` → `dim_companies.company_id`
- `data_quality_scores.filing_id` → `dim_filings.filing_id`

### Unique Constraints (Business Keys)

**dim_companies:**
- `UNIQUE(ticker)` - One row per ticker

**dim_concepts:**
- `UNIQUE(concept_name, taxonomy)` - One row per concept+taxonomy combo

**dim_time_periods:**
- `UNIQUE(period_type, start_date, end_date, instant_date)` - One row per unique period

**dim_filings:**
- `UNIQUE(company_id, filing_type, fiscal_year_end)` - One filing per company/type/year

**dim_xbrl_dimensions:**
- `UNIQUE(dimension_hash)` - One row per unique dimensional breakdown

**fact_financial_metrics:**
- `UNIQUE(filing_id, concept_id, period_id, dimension_id)` - **Critical constraint**
  - Prevents duplicate facts within same filing
  - Handles NULL dimension_id for consolidated facts
  - Allows multiple dimensional breakdowns of same concept

**data_quality_scores:**
- `UNIQUE(filing_id, check_name)` - One score per check per filing

**taxonomy_mappings:**
- `UNIQUE(source_concept, source_taxonomy)` - One mapping per source concept

## Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  1. EXTRACTION (Arelle XBRL Parser)                             │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. VALIDATION (Accounting Checks)                              │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. LOADING (load_financial_data.py)                            │
│     ├─ Get or create company_id                                 │
│     ├─ Get or create concept_id                                 │
│     ├─ Get or create period_id                                  │
│     ├─ Get or create filing_id                                  │
│     ├─ Get or create dimension_id (if dimensional)              │
│     └─ Insert fact (ON CONFLICT DO UPDATE)                      │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. QUERY (Streamlit / Superset)                                │
│     ├─ Consolidated: WHERE dimension_id IS NULL                 │
│     ├─ Dimensional: JOIN dim_xbrl_dimensions                    │
│     └─ Cross-company: JOIN all dimensions                       │
└─────────────────────────────────────────────────────────────────┘
```

## Cardinality

```
Companies:      11 rows
Concepts:       3,383 rows (276 with normalized_label, 8.2%)
Time Periods:   336 rows
Filings:        14 rows
Dimensions:     3,731 rows

Facts:          30,909 rows
  ├─ Consolidated (dimension_id IS NULL):     11,648 (37.7%)
  └─ Dimensional (dimension_id IS NOT NULL):  19,261 (62.3%)

Quality Scores: 0 rows (to be populated)
Mappings:       0 rows (normalization applied directly to dim_concepts)
```

## Indexes

### Fact Table
- `idx_fact_company` ON company_id
- `idx_fact_concept` ON concept_id
- `idx_fact_period` ON period_id
- `idx_fact_filing` ON filing_id
- `idx_fact_dimension` ON dimension_id
- `idx_fact_value_numeric` ON value_numeric (WHERE value_numeric IS NOT NULL)
- `idx_fact_company_concept` ON (company_id, concept_id)
- `idx_fact_company_period` ON (company_id, period_id)
- `idx_fact_concept_period` ON (concept_id, period_id)

### Dimension Tables
- `idx_companies_ticker` ON ticker
- `idx_companies_sector` ON sector
- `idx_concepts_normalized` ON normalized_label
- `idx_concepts_statement` ON statement_type
- `idx_periods_fiscal_year` ON fiscal_year
- `idx_periods_end_date` ON end_date
- `idx_filings_company_year` ON (company_id, fiscal_year_end)
- `idx_dimensions_json` ON dimension_json (GIN index for JSONB)

## Design Rationale

### Why Star Schema?

1. **Simplicity**: Single fact table with denormalized dimensions
2. **Query Performance**: Minimal joins required for most queries
3. **OLAP Optimized**: Perfect for analytical queries and aggregations
4. **Dimensional Flexibility**: Easy to add new dimensions without schema changes
5. **Industry Standard**: Widely understood by data analysts and BI tools

### Why NULL dimension_id?

NULL dimension_id distinguishes:
- **Consolidated facts**: Total values (e.g., total revenue = $100B)
- **Dimensional facts**: Breakdowns (e.g., product A revenue = $60B, product B = $40B)

This prevents double-counting when aggregating and allows queries to choose:
- Totals only: `WHERE dimension_id IS NULL`
- All breakdowns: `WHERE dimension_id IS NOT NULL`
- Specific dimension: `JOIN dim_xbrl_dimensions WHERE axis_name = 'ProductAxis'`

### Why JSONB for dimensions?

XBRL dimensions have varying structures:
- Simple: `{"ProductAxis": "ProductAMember"}`
- Complex: `{"StatementAxis": "SegmentMember", "GeographyAxis": "USMember"}`

JSONB provides:
- Flexible schema for any dimensional structure
- Indexable with GIN indexes
- Queryable with JSON operators
- Human-readable for debugging

### Duplicate Fact Handling

XBRL inline documents often contain the same fact multiple times (e.g., in main statement + footnote reference). 

**Deduplication Strategy:**
- Facts are deduplicated during extraction by (concept, context, value)
- Primary occurrence is determined by `order_index` (lowest = primary statement location)
- Duplicates are logged for audit but not stored
- `is_primary` flag marks the kept occurrence
- Unique constraint includes `fact_id_xbrl` to prevent accidental re-loading

**Why This Matters:**
- Prevents double-counting in aggregations
- Ensures statement-level queries return correct facts
- Maintains data quality for cross-company comparisons
- Preserves ability to trace fact to primary financial statement

## Example Queries

### 1. Get consolidated revenue for all companies
```sql
SELECT 
    c.ticker,
    t.fiscal_year,
    f.value_numeric / 1e9 as revenue_billions
FROM fact_financial_metrics f
JOIN dim_companies c ON f.company_id = c.company_id
JOIN dim_concepts co ON f.concept_id = co.concept_id
JOIN dim_time_periods t ON f.period_id = t.period_id
WHERE co.normalized_label = 'revenue'
  AND f.dimension_id IS NULL;  -- Consolidated only
```

### 2. Get segment breakdown for Google
```sql
SELECT 
    d.member_name as segment,
    co.normalized_label as metric,
    f.value_numeric
FROM fact_financial_metrics f
JOIN dim_companies c ON f.company_id = c.company_id
JOIN dim_concepts co ON f.concept_id = co.concept_id
JOIN dim_xbrl_dimensions d ON f.dimension_id = d.dimension_id
WHERE c.ticker = 'GOOGL'
  AND d.axis_name = 'StatementBusinessSegmentsAxis';
```

### 3. Compare pharma companies (US-GAAP vs IFRS)
```sql
SELECT 
    c.ticker,
    c.accounting_standard,
    co.normalized_label,
    AVG(f.value_numeric) as avg_value
FROM fact_financial_metrics f
JOIN dim_companies c ON f.company_id = c.company_id
JOIN dim_concepts co ON f.concept_id = co.concept_id
WHERE c.ticker IN ('PFE', 'LLY', 'NVO')  -- US-GAAP vs IFRS
  AND co.normalized_label IN ('revenue', 'net_income')
  AND f.dimension_id IS NULL
GROUP BY c.ticker, c.accounting_standard, co.normalized_label;
```

