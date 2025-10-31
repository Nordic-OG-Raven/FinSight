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

┌──────────────────────────────────┐
│  rel_calculation_hierarchy       │
├──────────────────────────────────┤
│ PK calculation_id (SERIAL)       │
│ FK filing_id → dim_filings       │
│ FK parent_concept_id →           │
│    dim_concepts                  │
│ FK child_concept_id →            │
│    dim_concepts                  │
│    weight (NUMERIC)              │  -- Usually 1.0 (add) or -1.0 (subtract)
│    order_index                   │
│    arcrole                       │
│    priority                      │
│ UK (filing_id, parent_concept_id,│
│     child_concept_id)            │
└──────────────────────────────────┘

┌──────────────────────────────────┐
│  rel_presentation_hierarchy      │
├──────────────────────────────────┤
│ PK presentation_id (SERIAL)      │
│ FK filing_id → dim_filings       │
│ FK parent_concept_id →           │
│    dim_concepts (NULL OK)        │  -- NULL for root nodes
│ FK child_concept_id →            │
│    dim_concepts                  │
│    order_index                   │
│    preferred_label               │
│    statement_type                │  -- balance_sheet, income_statement, etc.
│    arcrole                       │
│    priority                      │
│ UK (filing_id, parent_concept_id,│
│     child_concept_id, order_index)│
└──────────────────────────────────┘

┌──────────────────────────────────┐
│  rel_footnote_references         │
├──────────────────────────────────┤
│ PK footnote_id (SERIAL)         │
│ FK filing_id → dim_filings       │
│ FK fact_id →                     │
│    fact_financial_metrics        │
│    (NULL OK)                     │
│ FK concept_id →                  │
│    dim_concepts (NULL OK)        │
│    footnote_text (TEXT)          │
│    footnote_label                │  -- e.g., 'F1', 'Note 8'
│    footnote_role                 │
│    footnote_lang                 │
│    created_at                    │
│ UK (filing_id, fact_id,          │
│     concept_id, footnote_label)  │
└──────────────────────────────────┘
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

**rel_calculation_hierarchy**
- **Many-to-One** → `dim_filings` (via `filing_id`)
- **Many-to-One** → `dim_concepts` (via `parent_concept_id`)
- **Many-to-One** → `dim_concepts` (via `child_concept_id`)

**rel_presentation_hierarchy**
- **Many-to-One** → `dim_filings` (via `filing_id`)
- **Many-to-One** → `dim_concepts` (via `parent_concept_id`, nullable)
- **Many-to-One** → `dim_concepts` (via `child_concept_id`)

**rel_footnote_references**
- **Many-to-One** → `dim_filings` (via `filing_id`)
- **Many-to-One** → `fact_financial_metrics` (via `fact_id`, nullable)
- **Many-to-One** → `dim_concepts` (via `concept_id`, nullable)

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
- `rel_calculation_hierarchy.filing_id` → `dim_filings.filing_id`
- `rel_calculation_hierarchy.parent_concept_id` → `dim_concepts.concept_id`
- `rel_calculation_hierarchy.child_concept_id` → `dim_concepts.concept_id`
- `rel_presentation_hierarchy.filing_id` → `dim_filings.filing_id`
- `rel_presentation_hierarchy.parent_concept_id` → `dim_concepts.concept_id` (nullable)
- `rel_presentation_hierarchy.child_concept_id` → `dim_concepts.concept_id`
- `rel_footnote_references.filing_id` → `dim_filings.filing_id`
- `rel_footnote_references.fact_id` → `fact_financial_metrics.fact_id` (nullable)
- `rel_footnote_references.concept_id` → `dim_concepts.concept_id` (nullable)

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

**rel_calculation_hierarchy:**
- `UNIQUE(filing_id, parent_concept_id, child_concept_id)` - One calculation relationship per parent-child pair per filing

**rel_presentation_hierarchy:**
- `UNIQUE(filing_id, parent_concept_id, child_concept_id, order_index)` - One presentation relationship per parent-child-order combo per filing

**rel_footnote_references:**
- `UNIQUE(filing_id, fact_id, concept_id, footnote_label)` - One footnote reference per fact/concept-label combo per filing

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

### XBRL Relationship Tables (Hybrid System)

**Hybrid Approach: XBRL + Data-Verified Only**

Modern inline XBRL filings (SEC, ESEF) often don't include linkbases. To ensure consistent user experience while maintaining **100% data accuracy**, we use a **two-tier conservative system**:

1. **XBRL relationships** (`source='xbrl'`, `is_synthetic=FALSE`, `confidence=1.0`): From filing linkbases when available
2. **Dimensional relationships** (`source='dimensional'`, `is_synthetic=TRUE`, `confidence≥0.995`): Generated ONLY when dimensional facts mathematically sum to consolidated (within 0.5%)

**NO TEMPLATE GUESSING**: We do NOT generate relationships based on assumptions or templates. Every synthetic relationship is mathematically verified against actual reported data.

**Priority**: XBRL > Verified Dimensional (deduplicates by parent-child pair)

**1. Calculation Relationships (`rel_calculation_hierarchy`)**

Tracks parent-child summation relationships.

**Example:**
```
Revenue (parent) = Product Revenue (child, weight=1.0) + Service Revenue (child, weight=1.0)
Net Income (parent) = Revenue (child, weight=1.0) - Expenses (child, weight=-1.0)
```

**New Fields:**
- `source`: 'xbrl' or 'dimensional' (NO 'standard' - we don't guess)
- `is_synthetic`: TRUE if generated from data, FALSE if from filing
- `confidence`: 0.995-1.0 for synthetic (≥99.5% required), 1.0 for XBRL

**Generation Strategy (Data-Verified Only):**
- **Dimensional**: If Revenue (consolidated) = $100M and dimensional breakdowns sum to $99.95M-$100.05M (within 0.5%), create relationship
- **Verification**: `confidence = 1.0 - |difference|/parent_value`
- **Minimum threshold**: 99.5% confidence required
- **NO template guessing**: If data doesn't verify, no relationship created

**Use Cases:**
- **Drill-down navigation**: Click "Revenue" → show Product/Service breakdown (works for ALL companies)
- **Validation**: Verify children sum to parent
- **Cross-company comparison**: Consistent drill-down experience

**2. Presentation Hierarchy (`rel_presentation_hierarchy`)**

Tracks how concepts are organized in financial statements.

**Example:**
```
Balance Sheet (root)
  ├─ Current Assets (parent, NULL)
  │    ├─ Cash (child, order_index=1)
  │    └─ Accounts Receivable (child, order_index=2)
  └─ Non-Current Assets (parent)
       └─ Property, Plant & Equipment (child, order_index=1)
```

**New Fields:**
- `source`: 'xbrl' or 'dimensional' (NO 'standard')
- `is_synthetic`: TRUE if generated from data, FALSE if from filing

**Generation Strategy (Data-Verified Only):**
- **Dimensional**: Generated from hierarchical dimensional data (when available)
- **NO templates**: Presentation relationships are XBRL-only or data-verified dimensional

**Use Cases:**
- **Statement reconstruction**: Rebuild financial statements (when XBRL provided) or standard view (generated)
- **Section filtering**: Show only specific sections
- **Visualization**: Display statements in hierarchical order
- **Consistent UX**: All companies get hierarchical views

**3. Footnote References (`rel_footnote_references`)**

Links facts or concepts to detailed footnote disclosures (XBRL only, not synthesized).

**Example:**
```
DebtInstrument fact → footnote_label='F1', footnote_text='Long-term debt consists of...'
Revenue concept → footnote_label='Note 2', footnote_text='Revenue recognition policy...'
```

**Note:** Footnotes are XBRL-only. When not available, UI shows: "❌ Not made available in filing"

**Use Cases:**
- **Detailed disclosure access**: Click metric → see explanation (when available)
- **Compliance tracking**: Verify facts have disclosures
- **Audit trail**: Trace fact origins

**Availability by Source:**
- **SEC inline XBRL**: Rarely includes footnote linkbases
- **ESEF (EU)**: May include footnote linkbases
- **Older XBRL packages**: More likely to have footnotes

**UX Guidance:**
- Show availability badge: ✅ From filing / ⚠️ Generated / ❌ Not available in filing
- Don't blame regulator ("Not available in filing" not "Not provided by SEC/ESMA")

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

