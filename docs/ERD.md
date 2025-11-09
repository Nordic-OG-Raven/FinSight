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
│                          │     │
│    -- HIERARCHICAL STRUCTURE (NEW):
│    hierarchy_level (INT) │     │  -- 1=detail, 2=subtotal, 3=section_total, 4=statement_total
│ FK parent_concept_id     │─────┤  -- Self-referencing FK to concept_id (NULL for top-level)
│    calculation_weight    │     │  -- Multiplier for summation (1.0 for addition, -1.0 for subtraction)
│                          │     │
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
│    validation_score      │               │    is_calculated (BOOL)    │
│    completeness_score    │               │    extraction_method       │
│ UK (company_id,          │               │    created_at              │
│     filing_type,         │               │                            │
│     fiscal_year_end)     │               │ UK (filing_id, concept_id, │
└──────────────────────────┘               │     period_id,             │
                                           │     dimension_id,          │
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

┌──────────────────────────────────┐
│  rel_statement_items             │
├──────────────────────────────────┤
│ PK statement_item_id (SERIAL)   │
│ FK filing_id → dim_filings       │
│ FK concept_id → dim_concepts      │
│    statement_type VARCHAR(50)     │  -- income_statement, balance_sheet, etc.
│    display_order INTEGER          │  -- Corrected order (handles EPS, headers)
│    is_header BOOLEAN              │  -- TRUE for header items (e.g., "Earnings per share")
│    is_main_item BOOLEAN           │  -- TRUE for main statement items (not detail/disclosure)
│    role_uri VARCHAR(500)          │  -- For reference (from presentation hierarchy)
│    source VARCHAR(20)             │  -- 'xbrl' or 'standard'
│    created_at TIMESTAMP           │
│ UK (filing_id, concept_id,        │
│     statement_type)               │
└──────────────────────────────────┘

┌──────────────────────────────────┐
│  fact_income_statement            │
├──────────────────────────────────┤
│ PK income_statement_id (SERIAL)  │
│ FK filing_id → dim_filings       │
│ FK concept_id → dim_concepts      │
│ FK period_id → dim_time_periods   │
│    value_numeric NUMERIC(20,2)    │
│    unit_measure VARCHAR(20)       │
│    display_order INTEGER          │  -- Pre-computed order from XBRL
│    is_header BOOLEAN              │
│    hierarchy_level INTEGER        │
│ FK parent_concept_id →           │
│    dim_concepts (NULL OK)         │
│    created_at TIMESTAMP           │
│ UK (filing_id, concept_id,        │
│     period_id)                    │
└──────────────────────────────────┘

┌──────────────────────────────────┐
│  fact_balance_sheet               │
├──────────────────────────────────┤
│ PK balance_sheet_id (SERIAL)     │
│ (Same structure as               │
│  fact_income_statement)          │
└──────────────────────────────────┘

┌──────────────────────────────────┐
│  fact_cash_flow                   │
├──────────────────────────────────┤
│ PK cash_flow_id (SERIAL)         │
│ (Same structure as               │
│  fact_income_statement)          │
└──────────────────────────────────┘

┌──────────────────────────────────┐
│  fact_comprehensive_income       │
├──────────────────────────────────┤
│ PK comprehensive_income_id       │
│   (SERIAL)                       │
│ (Same structure as               │
│  fact_income_statement)          │
└──────────────────────────────────┘

┌──────────────────────────────────┐
│  fact_equity_statement           │
├──────────────────────────────────┤
│ PK equity_statement_id (SERIAL) │
│ (Same structure as               │
│  fact_income_statement)          │
│ NOTE: Not yet implemented in    │
│       schema.sql (future)        │
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

**rel_statement_items**
- **Many-to-One** → `dim_filings` (via `filing_id`)
- **Many-to-One** → `dim_concepts` (via `concept_id`)

**fact_income_statement**
- **Many-to-One** → `dim_filings` (via `filing_id`)
- **Many-to-One** → `dim_concepts` (via `concept_id`)
- **Many-to-One** → `dim_time_periods` (via `period_id`)
- **Many-to-One** → `dim_concepts` (via `parent_concept_id`, nullable)

**fact_balance_sheet**
- **Many-to-One** → `dim_filings` (via `filing_id`)
- **Many-to-One** → `dim_concepts` (via `concept_id`)
- **Many-to-One** → `dim_time_periods` (via `period_id`)
- **Many-to-One** → `dim_concepts` (via `parent_concept_id`, nullable)

**fact_cash_flow**
- **Many-to-One** → `dim_filings` (via `filing_id`)
- **Many-to-One** → `dim_concepts` (via `concept_id`)
- **Many-to-One** → `dim_time_periods` (via `period_id`)
- **Many-to-One** → `dim_concepts` (via `parent_concept_id`, nullable)

**fact_comprehensive_income**
- **Many-to-One** → `dim_filings` (via `filing_id`)
- **Many-to-One** → `dim_concepts` (via `concept_id`)
- **Many-to-One** → `dim_time_periods` (via `period_id`)
- **Many-to-One** → `dim_concepts` (via `parent_concept_id`, nullable)

**fact_equity_statement** (Future Implementation)
- **Many-to-One** → `dim_filings` (via `filing_id`)
- **Many-to-One** → `dim_concepts` (via `concept_id`)
- **Many-to-One** → `dim_time_periods` (via `period_id`)
- **Many-to-One** → `dim_concepts` (via `parent_concept_id`, nullable)
- **Note**: Statement of Changes in Equity - not yet implemented in schema.sql

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
- `rel_statement_items.filing_id` → `dim_filings.filing_id`
- `rel_statement_items.concept_id` → `dim_concepts.concept_id`
- `fact_income_statement.filing_id` → `dim_filings.filing_id`
- `fact_income_statement.concept_id` → `dim_concepts.concept_id`
- `fact_income_statement.period_id` → `dim_time_periods.period_id`
- `fact_income_statement.parent_concept_id` → `dim_concepts.concept_id` (nullable)
- `fact_balance_sheet.filing_id` → `dim_filings.filing_id`
- `fact_balance_sheet.concept_id` → `dim_concepts.concept_id`
- `fact_balance_sheet.period_id` → `dim_time_periods.period_id`
- `fact_balance_sheet.parent_concept_id` → `dim_concepts.concept_id` (nullable)
- `fact_cash_flow.filing_id` → `dim_filings.filing_id`
- `fact_cash_flow.concept_id` → `dim_concepts.concept_id`
- `fact_cash_flow.period_id` → `dim_time_periods.period_id`
- `fact_cash_flow.parent_concept_id` → `dim_concepts.concept_id` (nullable)
- `fact_comprehensive_income.filing_id` → `dim_filings.filing_id`
- `fact_comprehensive_income.concept_id` → `dim_concepts.concept_id`
- `fact_comprehensive_income.period_id` → `dim_time_periods.period_id`
- `fact_comprehensive_income.parent_concept_id` → `dim_concepts.concept_id` (nullable)

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

**rel_statement_items:**
- `UNIQUE(filing_id, concept_id, statement_type)` - One statement item per concept per statement type per filing

**fact_income_statement:**
- `UNIQUE(filing_id, concept_id, period_id)` - One fact per concept per period per filing

**fact_balance_sheet:**
- `UNIQUE(filing_id, concept_id, period_id)` - One fact per concept per period per filing

**fact_cash_flow:**
- `UNIQUE(filing_id, concept_id, period_id)` - One fact per concept per period per filing

**fact_comprehensive_income:**
- `UNIQUE(filing_id, concept_id, period_id)` - One fact per concept per period per filing

**fact_equity_statement:** (Future Implementation)
- `UNIQUE(filing_id, concept_id, period_id)` - One fact per concept per period per filing
- **Note**: Not yet implemented in schema.sql

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

---

## Hierarchical Normalization Strategy (Parent-Child Relationships)

### The Core Problem

Companies report the **same business item** at **different levels of granularity**:

**Example: Accrued Liabilities**
- **GOOGL**: Reports 3 separate components ($15B + $22B + $46B = $83B total)
  - `AccruedLiabilitiesCurrent`: $15B
  - `EmployeeRelatedLiabilitiesCurrent`: $22B  
  - `OtherAccruedLiabilitiesCurrent`: $46B
  
- **KO**: Reports 1 combined total ($21B)
  - `AccountsPayableAndAccruedLiabilitiesCurrent`: $21B
  
- **LLY**: Reports 2 components ($1.7B + $3.3B = $5B total)
  - `EmployeeRelatedLiabilitiesCurrent`: $1.7B
  - `OtherLiabilitiesCurrent`: $3.3B

**Cross-Company Comparison Problem:**
- User asks: "Compare accrued liabilities across GOOGL, KO, LLY"
- Naive normalization shows: GOOGL=$46B, KO=$21B, LLY=$3.3B (WRONG - incomplete)
- Correct totals: GOOGL=$83B, KO=$21B, LLY=$5B

### Solution: Hierarchical Concept Storage

**New `dim_concepts` Fields:**

1. **`hierarchy_level` (INT)**:
   - `1` = Detail (leaf node): `EmployeeRelatedLiabilitiesCurrent`
   - `2` = Subtotal: `TotalAccruedLiabilitiesCurrent`  
   - `3` = Section Total: `CurrentLiabilities`
   - `4` = Statement Total: `TotalLiabilities`

2. **`parent_concept_id` (FK to dim_concepts)**:
   - Self-referencing foreign key
   - Links child concept to parent concept
   - `NULL` for top-level concepts (statement totals)
   
3. **`calculation_weight` (DECIMAL)**:
   - `1.0` = Add to parent (assets, revenues, expenses)
   - `-1.0` = Subtract from parent (contra-accounts, deductions)
   - Used for: `parent_value = SUM(child_value * weight)`

**Additional Fields:**

- **`is_calculated` (on `fact_financial_metrics`, not `dim_concepts`)**:
  - `FALSE` = Reported directly in XBRL filing
  - `TRUE` = Calculated by summing children (synthesized at ETL)
  - Reason: Same concept can be calculated for one company but reported by another

### Hierarchy Construction Process

**Step 1: Extract XBRL Calculation Relationships**
```
From filing linkbase:
  CurrentLiabilities (parent)
    ├─ AccountsPayable (child, weight=1.0)
    ├─ AccruedLiabilities (child, weight=1.0)  
    └─ ShortTermDebt (child, weight=1.0)
```

**Step 2: Populate Hierarchy Metadata**
```sql
-- Set parent-child links
UPDATE dim_concepts 
SET parent_concept_id = (
    SELECT parent_concept_id 
    FROM rel_calculation_hierarchy 
    WHERE child_concept_id = concept_id
)

-- Infer hierarchy levels
UPDATE dim_concepts SET hierarchy_level = 1 WHERE parent_concept_id IS NOT NULL AND concept_id NOT IN (SELECT parent_concept_id FROM rel_calculation_hierarchy);
UPDATE dim_concepts SET hierarchy_level = 4 WHERE parent_concept_id IS NULL AND concept_name LIKE '%Total%';
```

**Step 3: Calculate Missing Parent Facts**

If company reports children but not parent:
```python
def calculate_parent_facts(filing_id):
    """Calculate aggregated facts for parents when children exist but parent is missing."""
    
    # Find parent concepts that have children but no reported value
    missing_parents = get_missing_parent_concepts(filing_id)
    
    for parent in missing_parents:
        children = get_child_concepts(parent)
        
        for period in get_periods(filing_id):
            child_values = []
            for child in children:
                child_fact = get_fact(child.concept_id, period)
                if child_fact:
                    weighted_value = child_fact.value_numeric * child.calculation_weight
                    child_values.append(weighted_value)
            
            if child_values:
                calculated_value = sum(child_values)
                
                # Insert calculated fact
                insert_fact(
                    concept_id=parent.concept_id,
                    period_id=period,
                    value_numeric=calculated_value,
                    is_calculated=TRUE,
                    extraction_method='calculated_from_children'
                )
```

**Step 4: Validate Aggregations**

Hard-fail if reported parent ≠ calculated parent (> 1% diff):
```python
if reported_parent and calculated_parent:
    diff_pct = abs(reported_parent - calculated_parent) / reported_parent * 100
    if diff_pct > 1.0:
        raise ValidationError(
            f"{parent.name}: Reported=${reported_parent:,.0f}, "
            f"Calculated=${calculated_parent:,.0f} ({diff_pct:.2f}% diff)"
        )
```

### Cross-Company Querying with Hierarchy

**User Query**: "Compare accrued liabilities across GOOGL, KO, LLY"

**Query Logic**:
```sql
WITH concept_hierarchy AS (
    -- Find the normalized label user requested
    SELECT concept_id, normalized_label, hierarchy_level
    FROM dim_concepts
    WHERE normalized_label = 'accrued_liabilities_current'
),
aggregated_values AS (
    SELECT 
        f.company_id,
        f.period_id,
        -- If company reports at this level, use it
        -- Otherwise, sum children or use parent
        COALESCE(
            -- Direct value
            (SELECT value_numeric FROM fact_financial_metrics 
             WHERE company_id = f.company_id AND concept_id IN (SELECT concept_id FROM concept_hierarchy)),
            
            -- Or sum children
            (SELECT SUM(fc.value_numeric * dc.calculation_weight)
             FROM fact_financial_metrics fc
             JOIN dim_concepts dc ON fc.concept_id = dc.concept_id
             WHERE fc.company_id = f.company_id 
               AND dc.parent_concept_id IN (SELECT concept_id FROM concept_hierarchy)),
            
            -- Or use calculated parent fact
            (SELECT value_numeric FROM fact_financial_metrics 
             WHERE company_id = f.company_id AND is_calculated = TRUE 
               AND concept_id IN (SELECT parent_concept_id FROM dim_concepts WHERE concept_id IN (SELECT concept_id FROM concept_hierarchy)))
        ) as comparable_value
    FROM fact_financial_metrics f
    GROUP BY f.company_id, f.period_id
)
SELECT company, fiscal_year, comparable_value
FROM aggregated_values
```

**Result**: All companies now comparable at same hierarchy level, regardless of reporting granularity.

### UI Integration: Drill-Down/Roll-Up

**Sidebar Filter:**
```
Metric Granularity:
  ○ Detail Level (all line items)
  ○ Subtotals (section summaries)
  ● Statement Totals (balance sheet, income statement) [DEFAULT]
```

**Interactive Drill-Down:**
```
User clicks: "Current Liabilities: $83B" (GOOGL FY2024)
  → Shows children:
    - Accounts Payable: $15B
    - Accrued Liabilities: $46B
    - Employee Liabilities: $22B
    - Short-term Debt: $0
```

**Benefits:**
- ✅ Cross-company comparison at ANY level
- ✅ Drill-down for detail, roll-up for summary
- ✅ Data quality validated at ETL (not query time)
- ✅ Fast queries (pre-calculated aggregations)
- ✅ Flexible analysis (user chooses granularity)

---

### XBRL Relationship Tables (Hybrid System)

**Relationship System: XBRL Only + Dimensional Filtering**

Modern inline XBRL filings (SEC, ESEF) often don't include linkbases. We use a **conservative, accuracy-first approach**:

1. **XBRL calc relationships** (`source='xbrl'`, `is_synthetic=FALSE`, `confidence=1.0`): From filing linkbases when available
2. **NO synthetic calc relationships**: We do NOT generate calc relationships from dimensional data

**Why No Dimensional Calc Relationships?**

Dimensional breakdowns are **same concept, different dimensions** - NOT a calculation relationship:
```
❌ WRONG: Revenue (parent) = Revenue+ProductA (child) + Revenue+ProductB (child)
           ^^^^ Same concept (Revenue), different dimensions

✅ CORRECT: Use dimension filtering for drill-down
           Parent: SELECT * WHERE dimension_id IS NULL
           Children: SELECT * WHERE concept_id = X AND dimension_id IS NOT NULL
```

**Dimensional Drill-Down Without Calc Relationships:**
- Query consolidated: `WHERE dimension_id IS NULL`
- Query breakdowns: `WHERE concept_id = X AND dimension_id IS NOT NULL`
- Join `dim_xbrl_dimensions` to show dimension labels (Geography, Product, etc.)
- No calc relationships needed - it's just data filtering!

**Result**: ALL companies with dimensional data (60%+ of facts) support drill-down, without needing calc relationships.

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


---

## Hierarchical Normalization - IMPLEMENTED ✅

The system now implements Option 1 (Hierarchical Normalization) to solve the semantic conflation problem.

### Implementation Status

1. ✅ **Taxonomy Download**: Downloaded US-GAAP 2023 with 6,279 calculation relationships
   - Script: `src/ingestion/download_taxonomy.py`
   - Output: `data/taxonomies/us-gaap-2023-calc.json`

2. ✅ **Hierarchy Population**: Built concept parent-child links
   - Script: `src/utils/populate_hierarchy.py`
   - Updated: 5,160 concepts with parent links
   - Inferred: 4 hierarchy levels (detail → statement total)

3. ✅ **Database Views**: Created hierarchical query views
   - `v_facts_hierarchical`: Facts with hierarchy metadata
   - Includes: parent_concept_id, hierarchy_level, parent_normalized_label

4. ✅ **UI Integration**: Added granularity control to data viewer
   - Filter: "Comparable totals (Level 3+)" - DEFAULT
   - Filter: "Include subtotals (Level 2+)"
   - Filter: "All detail (Level 1+)"

### Hierarchy Levels

- **Level 4 (Statement Total)**: 386 concepts (e.g., `Assets`, `Revenue`)
- **Level 3 (Section Total)**: 221 concepts (e.g., `LiabilitiesCurrent`) ← **DEFAULT COMPARISON LEVEL**
- **Level 2 (Subtotal)**: 240 concepts (e.g., `AccruedLiabilitiesCurrent`)
- **Level 1 (Detail)**: 4,149 concepts (e.g., `AccruedSalariesCurrent`)

### Solution to "Missing Data" Problem

**Problem**: User saw "missing data" for metrics like `accrued_liabilities_current`

**Root Cause**: Companies report at different granularities:
- GOOGL: 3 components (AccruedLiabilities + Employee + Other)
- KO: 1 combined (AccountsPayableAndAccruedLiabilities)
- User was comparing Level 2 metrics (not all companies report)

**Solution**: Default to Level 3 (section totals)
- ALL companies report `LiabilitiesCurrent` (Level 3)
- Users can drill down to Level 2/1 where available
- Cross-company comparison mathematically sound

### Validation Results

✅ All parent-child summations validated (< 1% difference)
✅ 746 company concepts matched to taxonomy hierarchy
✅ 4,046/10,088 facts have hierarchy metadata (40%)
✅ All companies report Level 3+ metrics

### Validation Pipeline Integration

**Integrated into ETL Pipeline (`database/load_financial_data.py`):**

1. **Taxonomy Download** (if missing):
   - Downloads US-GAAP, IFRS, ESEF taxonomies with calculation and label linkbases
   - Extracts calculation relationships and concept labels

2. **Taxonomy Hierarchy Loading**:
   - Loads taxonomy calculation relationships into `rel_calculation_hierarchy`
   - Infers hierarchy levels from taxonomy structure

3. **Hierarchy Population**:
   - Populates `hierarchy_level` for all concepts
   - Uses taxonomy relationships + pattern matching fallback

4. **Normalization Application**:
   - Applies taxonomy mappings from `taxonomy_mappings.py`
   - Updates `normalized_label` in `dim_concepts`

5. **Taxonomy Synonym Application**:
   - Applies taxonomy-driven synonyms (concepts with identical labels)
   - Uses downloaded taxonomy label linkbases

6. **Calculated Totals** (if needed):
   - Calculates missing universal metric totals from components
   - Uses taxonomy-defined calculation relationships (standard XBRL approach)

7. **Comprehensive Validation**:
   - Runs `DatabaseValidator.validate_all()` automatically
   - Flags missing universal metrics for manual review
   - Detects user-facing duplicates
   - Generates data quality report

8. **Mapping Suggestions** (development tool):
   - `suggest_mappings_from_taxonomy_labels.py` flags potential missing mappings
   - NOT auto-applied - requires manual curation and accounting standards verification
   - Integrated to run after validation to suggest improvements

**Key Principle:** All fixes are **lasting** - integrated into pipeline, not one-off scripts.
When data is cleared/reloaded or new companies added, pipeline automatically handles:
- Taxonomy normalization
- Hierarchy population
- Synonym application
- Calculated totals
- Validation checks

### Testing

Visit http://localhost:8502/ and try:
1. Select all companies
2. Choose "Comparable totals (Level 3+)" (default)
3. Pick a metric like "Liabilities Current"
4. All companies show data ✅
5. Switch to "All detail" → see granular variations
