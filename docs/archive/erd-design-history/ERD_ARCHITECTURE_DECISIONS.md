# ERD Architecture Decisions: Template Tables, Views, and Data Lake

**Date:** 2025-01-XX  
**Context:** Architectural decisions for long-term viability and maintainability

---

## 1. Template Table Organization

### Recommended Structure: Hierarchical Template System

**Core Principle:** Templates should be **canonical** (standard structure) with **filing-specific overrides** (custom items).

```sql
-- ============================================================================
-- CANONICAL STATEMENT TEMPLATES (Standard Structure)
-- ============================================================================
-- These define the standard structure for each statement type and format
-- Populated once per (statement_type, format_type) combination
-- Used as the default structure for all companies

CREATE TABLE dim_statement_templates (
    template_id SERIAL PRIMARY KEY,
    
    -- Template Identity
    statement_type VARCHAR(50) NOT NULL, -- 'income_statement', 'balance_sheet', 'cash_flow', 'comprehensive_income', 'equity_statement'
    format_type VARCHAR(20) NOT NULL DEFAULT 'standard', -- 'ifrs', 'us_gaap', 'ifrs_eu', 'custom'
    
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
    
    -- Metadata
    description TEXT, -- Description of what this item represents
    accounting_standard_notes TEXT, -- Notes on IFRS vs US-GAAP differences
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(statement_type, format_type, item_order)
);

-- Indexes for fast lookups
CREATE INDEX idx_templates_statement_format ON dim_statement_templates(statement_type, format_type, item_order);
CREATE INDEX idx_templates_normalized_label ON dim_statement_templates(normalized_label) WHERE normalized_label IS NOT NULL;

-- ============================================================================
-- FILING-SPECIFIC OVERRIDES (Custom Items)
-- ============================================================================
-- These allow companies to have custom items not in the canonical template
-- Example: NVO has "Reduction of the B share capital" which is not standard

CREATE TABLE rel_statement_items (
    statement_item_id SERIAL PRIMARY KEY,
    
    -- Link to Filing
    filing_id INTEGER NOT NULL REFERENCES dim_filings(filing_id) ON DELETE CASCADE,
    
    -- Link to Template (if item exists in template)
    template_id INTEGER REFERENCES dim_statement_templates(template_id) ON DELETE SET NULL,
    
    -- Item Definition (overrides template if template_id is set)
    concept_id INTEGER REFERENCES dim_concepts(concept_id) ON DELETE CASCADE,
    statement_type VARCHAR(50) NOT NULL,
    item_order INTEGER NOT NULL, -- Override: custom order
    item_label VARCHAR(200), -- Override: custom label
    normalized_label VARCHAR(200), -- Links to dim_concepts.normalized_label
    
    -- Item Type (overrides template)
    item_type VARCHAR(20) DEFAULT 'fact',
    is_header BOOLEAN DEFAULT FALSE,
    is_spacer BOOLEAN DEFAULT FALSE,
    is_calculated BOOLEAN DEFAULT FALSE,
    
    -- Hierarchy (overrides template)
    hierarchy_level INTEGER DEFAULT 0,
    parent_item_order INTEGER,
    section_name VARCHAR(100),
    
    -- Display Rules (overrides template)
    side VARCHAR(20),
    is_required BOOLEAN DEFAULT TRUE,
    display_condition TEXT,
    
    -- Metadata
    is_custom BOOLEAN DEFAULT FALSE, -- TRUE if not in canonical template
    source VARCHAR(20) DEFAULT 'xbrl', -- 'xbrl', 'standard', 'manual'
    role_uri VARCHAR(500), -- XBRL role URI for reference
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(filing_id, concept_id, statement_type),
    UNIQUE(filing_id, statement_type, item_order) -- Prevent duplicate orders
);

-- Indexes
CREATE INDEX idx_statement_items_filing ON rel_statement_items(filing_id, statement_type, item_order);
CREATE INDEX idx_statement_items_template ON rel_statement_items(template_id) WHERE template_id IS NOT NULL;
CREATE INDEX idx_statement_items_custom ON rel_statement_items(filing_id, is_custom) WHERE is_custom = TRUE;
```

### Template Organization Strategy

**Level 1: Canonical Templates (Standard Structure)**
- **IFRS Income Statement Template** - Standard IFRS income statement structure
- **US-GAAP Income Statement Template** - Standard US-GAAP income statement structure
- **IFRS Balance Sheet Template** - Standard IFRS balance sheet structure
- **US-GAAP Balance Sheet Template** - Standard US-GAAP balance sheet structure
- **Cash Flow Template** - Standard cash flow structure (similar across standards)
- **Comprehensive Income Template** - Standard comprehensive income structure
- **Equity Statement Template** - Standard equity statement structure

**Level 2: Filing-Specific Overrides**
- Custom items not in template (e.g., "Reduction of the B share capital")
- Custom ordering (e.g., EPS placement)
- Custom headers (e.g., company-specific section names)

**Benefits:**
- **Standard structure** for most companies (80-90% of items)
- **Custom overrides** for special cases (10-20% of items)
- **Easy to maintain** - update template once, affects all companies
- **Easy to compare** - standard structure enables cross-company comparison

---

## 2. Views vs. Materialized Views: Industry Standard Explanation

### What Are Views?

**Views** are **virtual tables** - they don't store data, they're just saved SQL queries.

```sql
-- Example: View (no data stored)
CREATE VIEW v_income_statement AS
SELECT 
    st.item_order,
    st.item_label,
    st.is_header,
    fm.value_numeric,
    ...
FROM dim_statement_templates st
LEFT JOIN fact_financial_metrics fm ON ...
WHERE st.statement_type = 'income_statement'
ORDER BY st.item_order;

-- When you query the view, it runs the SQL query
SELECT * FROM v_income_statement WHERE filing_id = 5;
-- This executes the underlying query every time
```

**Pros:**
- ✅ Always up-to-date (queries underlying tables directly)
- ✅ No data duplication
- ✅ No maintenance (no need to refresh)
- ✅ Simple to create

**Cons:**
- ❌ Slower (runs query every time)
- ❌ Can't index views directly (PostgreSQL can create indexes on underlying tables)

### What Are Materialized Views?

**Materialized Views** are **physical tables** - they store the results of a query.

```sql
-- Example: Materialized View (data is stored)
CREATE MATERIALIZED VIEW mv_income_statement AS
SELECT 
    st.item_order,
    st.item_label,
    st.is_header,
    fm.value_numeric,
    ...
FROM dim_statement_templates st
LEFT JOIN fact_financial_metrics fm ON ...
WHERE st.statement_type = 'income_statement'
ORDER BY st.item_order;

-- Create index on materialized view (faster queries)
CREATE INDEX idx_mv_income_statement_filing ON mv_income_statement(filing_id, item_order);

-- When you query the materialized view, it reads from stored data
SELECT * FROM mv_income_statement WHERE filing_id = 5;
-- This reads from the stored table (fast!)

-- But you need to refresh when underlying data changes
REFRESH MATERIALIZED VIEW mv_income_statement;
```

**Pros:**
- ✅ Fast (reads from stored table)
- ✅ Can be indexed (faster queries)
- ✅ No data duplication (still queries from fact_financial_metrics)

**Cons:**
- ❌ Needs refresh when data changes
- ❌ Takes up storage space (but minimal - just the query results)

### Why Are Views Industry Standard?

**1. Separation of Concerns**
- **Data Layer:** `fact_financial_metrics` (raw data)
- **Presentation Layer:** Views (how data is presented)
- **Benefit:** Can change presentation without touching data

**2. Single Source of Truth**
- All data comes from `fact_financial_metrics`
- No data duplication
- **Benefit:** No sync issues, no inconsistencies

**3. Flexibility**
- Easy to create new views for different use cases
- Easy to modify views without changing data
- **Benefit:** Can support multiple statement formats

**4. Performance (Materialized Views)**
- Pre-computed results for fast queries
- Can be indexed for even faster queries
- **Benefit:** Fast queries without data duplication

### Would Views Add Value Here?

**YES, ABSOLUTELY** - Here's why:

**Current Problem:**
- `fact_income_statement`, `fact_balance_sheet`, etc. duplicate data from `fact_financial_metrics`
- Complex ETL to populate them (`populate_statement_facts.py`)
- Need to keep them in sync
- Headers stored as facts (mixing data with presentation)

**With Views:**
- **Single source of truth:** `fact_financial_metrics`
- **No data duplication:** Views query from fact table
- **No sync issues:** Always up-to-date (or refresh materialized views)
- **Simpler ETL:** No need to populate statement-specific tables
- **Headers in templates:** Not in fact tables

**Example Implementation:**

```sql
-- View for Income Statement (always up-to-date)
CREATE VIEW v_income_statement AS
SELECT 
    f.filing_id,
    f.period_id,
    st.item_order as display_order,
    st.item_label,
    st.is_header,
    st.is_spacer,
    st.hierarchy_level,
    st.parent_item_order,
    co.concept_id,
    fm.value_numeric,
    fm.unit_measure,
    co.parent_concept_id
FROM dim_statement_templates st
LEFT JOIN dim_concepts co ON st.normalized_label = co.normalized_label
LEFT JOIN fact_financial_metrics fm ON 
    fm.normalized_label = st.normalized_label
    AND fm.filing_id = :filing_id
    AND fm.period_id = :period_id
    AND fm.dimension_id IS NULL
LEFT JOIN dim_filings f ON fm.filing_id = f.filing_id
LEFT JOIN dim_companies c ON f.company_id = c.company_id
WHERE st.statement_type = 'income_statement'
  AND st.format_type = COALESCE(
      CASE c.accounting_standard
          WHEN 'IFRS' THEN 'ifrs'
          WHEN 'US-GAAP' THEN 'us_gaap'
          ELSE 'standard'
      END,
      'standard'
  )
ORDER BY st.item_order;

-- Materialized View for Performance (refresh after data load)
CREATE MATERIALIZED VIEW mv_income_statement AS
SELECT * FROM v_income_statement;

-- Index for fast queries
CREATE INDEX idx_mv_income_statement_filing_period 
    ON mv_income_statement(filing_id, period_id, display_order);

-- Refresh after data load
REFRESH MATERIALIZED VIEW mv_income_statement;
```

**Migration Path:**
1. Create views (test with current data)
2. Update API to use views
3. Remove `populate_statement_facts.py` logic
4. Drop statement-specific fact tables
5. Use materialized views for performance if needed

---

## 3. Separate Templates (Already Addressed)

See Section 1 above - the template structure supports separate templates per `(statement_type, format_type)`.

---

## 4. Single Normalized Fact Table: Speed vs. Storage

### Why Hedge Funds Use Single Normalized Fact Tables

**Hedge Funds (Trading/Real-time Analysis):**
- **Speed is critical:** Need to analyze data in milliseconds
- **Storage is cheap:** Can afford to denormalize for speed
- **Single use case:** Trading algorithms, not general-purpose platform
- **Approach:** Denormalize everything, materialize everything, index everything

**Your Use Case (Analysis Platform):**
- **Speed is important but not critical:** Users can wait 1-2 seconds
- **Storage matters:** Need to scale to many companies
- **Multiple use cases:** Different users, different queries
- **Approach:** Normalize for flexibility, materialize for performance where needed

### Recommended Approach for Your Platform

**Hybrid Approach:**
1. **Normalized Fact Table** (`fact_financial_metrics`) - Single source of truth
2. **Materialized Views** - Pre-computed for common queries (statements)
3. **Indexes** - Fast lookups on fact table and materialized views
4. **Views** - Flexible queries for ad-hoc analysis

**Why This Works:**
- **Flexibility:** Can support any query pattern
- **Performance:** Materialized views for common queries (statements)
- **Storage:** Minimal duplication (just query results, not full data)
- **Maintainability:** Single source of truth, easy to maintain

**Example:**
```sql
-- Normalized fact table (single source of truth)
CREATE TABLE fact_financial_metrics (
    -- All financial data here
);

-- Materialized view for common queries (income statement)
CREATE MATERIALIZED VIEW mv_income_statement AS
SELECT ... FROM fact_financial_metrics
JOIN dim_statement_templates ON ...
WHERE statement_type = 'income_statement';

-- Index for fast queries
CREATE INDEX idx_mv_income_statement_filing 
    ON mv_income_statement(filing_id, period_id);

-- View for ad-hoc analysis (flexible)
CREATE VIEW v_financial_analysis AS
SELECT ... FROM fact_financial_metrics
-- Can join any way needed for analysis
```

**Refresh Strategy:**
- **After data load:** Refresh materialized views
- **For ad-hoc analysis:** Use views (always up-to-date)
- **For API queries:** Use materialized views (fast)

---

## 5. Data Lake: Should We Add One?

### What Is a Data Lake?

**Data Lake** = Raw data storage (files, JSON, CSV, etc.) before processing
**Data Warehouse** = Processed, structured data (tables, SQL queries)

**Typical Architecture:**
```
Raw Data (XBRL files, SEC API JSON)
    ↓
Data Lake (S3, HDFS, etc.) - Store raw files
    ↓
ETL Process (Extract, Transform, Load)
    ↓
Data Warehouse (PostgreSQL) - Structured tables
    ↓
API / Analysis Tools
```

### Should You Add a Data Lake?

**Short Answer: NO, not yet** - But here's why and when you should:

**Current Architecture:**
- Raw data → ETL → Data Warehouse → API
- **Problem:** If ETL fails or data is wrong, need to re-extract from source
- **Problem:** Can't easily reprocess historical data
- **Problem:** Debugging is hard (can't see raw data)

**With Data Lake:**
- Raw data → Data Lake → ETL → Data Warehouse → API
- **Benefit:** Can reprocess data without re-extracting
- **Benefit:** Can debug by looking at raw data
- **Benefit:** Can store multiple versions of data

**When to Add Data Lake:**

**Add Now If:**
- ✅ You're processing many companies (100+)
- ✅ You need to reprocess historical data often
- ✅ You want to store raw XBRL files for debugging
- ✅ You want to support multiple data sources

**Don't Add Now If:**
- ❌ You're processing few companies (< 10)
- ❌ You can re-extract from source easily
- ❌ Storage costs are a concern
- ❌ You don't need historical reprocessing

### Recommended: Lightweight Data Lake

**Instead of full data lake, use a "data archive" approach:**

```python
# Store raw JSON files in a structured directory
data/
  raw/
    xbrl/
      NVO/
        2024/
          NVO_2024_20F_facts.json
          NVO_2024_20F_metadata.json
    sec_api/
      NVO/
        2024/
          NVO_2024_10K_facts.json
  processed/
    NVO/
      2024/
        NVO_2024_20F_facts.json  # After normalization
```

**Benefits:**
- ✅ Can reprocess without re-extracting
- ✅ Can debug by looking at raw files
- ✅ Minimal infrastructure (just file system)
- ✅ Can migrate to S3/Data Lake later if needed

**Implementation:**
```python
# In load_financial_data.py
def load_json_file(filepath: Path, show_completeness_check: bool = True):
    # 1. Load raw JSON
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    # 2. Archive raw file (lightweight data lake)
    archive_path = Path(f"data/raw/xbrl/{company_ticker}/{fiscal_year}/{filepath.name}")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(filepath, archive_path)
    
    # 3. Process and load to warehouse
    # ... existing logic ...
```

---

## Addressing the "Hundreds of Hours" Problem

### Root Cause Analysis

**Why has debugging taken so long?**

1. **Mixed Concerns:** Headers in fact tables, data in presentation layer
2. **Data Duplication:** Multiple fact tables need to stay in sync
3. **Complex Queries:** Cross-filing matching, period deduplication, etc.
4. **No Clear Separation:** Can't easily see what's data vs. what's presentation

### How Template Tables + Views Would Help

**Before (Current):**
- Headers in `fact_equity_statement` with `is_header = TRUE`, `value_numeric = NULL`
- Complex queries to populate statement tables
- Need to debug why headers aren't appearing
- Need to debug why values are wrong
- **Problem:** Can't separate data issues from presentation issues

**After (With Templates + Views):**
- Headers in `dim_statement_templates` (metadata only)
- Values in `fact_financial_metrics` (data only)
- Views combine them (presentation)
- **Benefit:** Can debug data issues separately from presentation issues
- **Benefit:** Can test templates independently
- **Benefit:** Can test data independently

**Example Debugging:**

```sql
-- Debug data issues (check if values exist)
SELECT 
    normalized_label,
    fiscal_year,
    value_numeric
FROM fact_financial_metrics
WHERE filing_id = 5
  AND normalized_label = 'oci_total'
ORDER BY fiscal_year;

-- Debug presentation issues (check if template is correct)
SELECT 
    item_order,
    item_label,
    is_header,
    normalized_label
FROM dim_statement_templates
WHERE statement_type = 'equity_statement'
  AND format_type = 'ifrs'
ORDER BY item_order;

-- Debug combined (check if view works)
SELECT * FROM v_equity_statement WHERE filing_id = 5;
```

**This separation makes debugging 10x easier.**

---

## Recommended Implementation Order

### Phase 1: Template Tables (1-2 weeks)
1. Create `dim_statement_templates` table
2. Migrate headers from `rel_statement_items` to templates
3. Update ETL to populate templates
4. **Benefit:** Headers are now metadata, not data

### Phase 2: Views (1 week)
1. Create views for each statement type
2. Test views with current data
3. Update API to use views
4. **Benefit:** Single source of truth, no data duplication

### Phase 3: Remove Denormalized Tables (1 week)
1. Remove `populate_statement_facts.py` logic
2. Drop statement-specific fact tables
3. Use views instead
4. **Benefit:** Simpler ETL, easier maintenance

### Phase 4: Materialized Views (Optional, 1 week)
1. Create materialized views for performance
2. Add refresh logic after data load
3. **Benefit:** Fast queries without data duplication

### Phase 5: Data Archive (Optional, 1 week)
1. Add raw file archiving to ETL
2. Store raw JSON files in structured directory
3. **Benefit:** Can reprocess without re-extracting

---

## Conclusion

**Template Tables:** ✅ **YES** - Separate presentation from data
**Views:** ✅ **YES** - Industry standard, eliminates data duplication
**Materialized Views:** ✅ **YES** - For performance on common queries
**Single Normalized Fact Table:** ✅ **YES** - Flexibility + performance via materialized views
**Data Lake:** ⚠️ **NOT YET** - Use lightweight data archive instead

**Expected Impact:**
- **Debugging time:** 10x reduction (can separate data vs. presentation issues)
- **Maintenance:** 5x reduction (single source of truth, no sync issues)
- **Flexibility:** 10x increase (easy to add new statement formats)
- **Performance:** Same or better (materialized views are fast)

**Migration Risk:** **LOW** - Can be done incrementally, views can coexist with current tables during migration

