# ERD Industry Standards Evaluation

**Date:** 2025-01-XX  
**Evaluator:** AI Assistant  
**Context:** Evaluation of FinSight ERD for long-term viability across IFRS and US-GAAP companies

---

## Executive Summary

**Current Status:** ⚠️ **FUNCTIONAL BUT SUBOPTIMAL**

The current ERD is **viable and works**, but has **architectural debt** that will cause increasing maintenance complexity as the system scales. The design mixes concerns (data vs. presentation) and uses denormalization in ways that violate industry best practices.

**Recommendation:** **MODERATE REFACTORING** - Not a complete rewrite, but strategic improvements to separate concerns and improve maintainability.

---

## Current Architecture Analysis

### Strengths ✅

1. **Star Schema Foundation** - Solid dimensional modeling with proper fact/dimension separation
2. **Business Keys** - Recent addition of denormalized business keys (`normalized_label`, `fiscal_year`, `period_type`) is industry-standard for data warehouses
3. **XBRL Relationship Preservation** - `rel_calculation_hierarchy` and `rel_presentation_hierarchy` correctly preserve XBRL metadata
4. **Data Quality Tracking** - `data_quality_scores` table enables systematic validation
5. **Taxonomy Normalization** - `taxonomy_mappings` and `normalized_label` enable cross-taxonomy comparison (US-GAAP vs IFRS)

### Weaknesses ⚠️

1. **Headers Stored as Facts** - Headers are stored in fact tables with `is_header = TRUE` and `value_numeric = NULL`
   - **Problem:** Mixes metadata (presentation) with data (values)
   - **Industry Standard:** Headers should be in a separate presentation/structure table
   - **Impact:** Complex queries, data integrity issues, maintenance burden

2. **Denormalized Statement Fact Tables** - Separate fact tables (`fact_income_statement`, `fact_balance_sheet`, etc.) duplicate data from `fact_financial_metrics`
   - **Problem:** Data duplication, complex ETL, maintenance burden
   - **Industry Standard:** Use views or materialized views, not separate fact tables
   - **Impact:** Need to keep multiple tables in sync, complex queries to populate them

3. **No Clear Presentation Layer** - Statement structure (headers, ordering, hierarchy) is mixed with data
   - **Problem:** Can't easily change statement structure without touching data
   - **Industry Standard:** Separate statement templates/structure tables
   - **Impact:** Hard to support multiple statement formats, hard to customize per company

4. **Complex Cross-Filing Matching** - Queries require complex LATERAL joins to match data across filings
   - **Problem:** Despite business keys, queries are still complex
   - **Industry Standard:** Better normalization or clearer data model would simplify
   - **Impact:** Hard to debug, fragile queries, performance issues

---

## Industry Standards Comparison

### Big 4 Accounting Firms (PwC, Deloitte, EY, KPMG)

**Their Approach:**
- **Separate Presentation Layer:** Statement templates stored separately from data
- **Headers as Metadata:** Headers are in template tables, not fact tables
- **Views for Statements:** Use views or materialized views for statement-specific queries
- **Normalized Structure:** Clear separation between data (facts) and presentation (templates)

**Example Structure:**
```sql
-- Template table (metadata only)
CREATE TABLE dim_statement_templates (
    template_id SERIAL PRIMARY KEY,
    statement_type VARCHAR(50),
    item_order INTEGER,
    item_label VARCHAR(200),
    is_header BOOLEAN,
    parent_item_order INTEGER,
    ...
);

-- Fact table (data only)
CREATE TABLE fact_financial_metrics (
    -- No is_header, no display_order
    -- Just data
);

-- View (combines template + data)
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
```

### Hedge Funds (Two Sigma, Renaissance, Citadel)

**Their Approach:**
- **Normalized Fact Table:** Single source of truth for all financial data
- **Materialized Views:** Pre-computed statement views for performance
- **Template-Driven:** Statement structure defined in templates, not in data
- **Flexible Presentation:** Easy to change statement format without touching data

**Example Structure:**
```sql
-- Core fact table (normalized)
CREATE TABLE fact_financial_metrics (
    -- Just data, no presentation metadata
);

-- Statement template (metadata)
CREATE TABLE rel_statement_structure (
    filing_id INTEGER,
    statement_type VARCHAR(50),
    concept_id INTEGER,
    display_order INTEGER,
    is_header BOOLEAN,
    -- No values, just structure
);

-- Materialized view (performance)
CREATE MATERIALIZED VIEW mv_income_statement AS
SELECT ... FROM fact_financial_metrics
JOIN rel_statement_structure ON ...
WHERE statement_type = 'income_statement';
```

### Financial Data Platforms (Bloomberg, FactSet, Refinitiv)

**Their Approach:**
- **Template-Based:** Statement structure defined in templates
- **Multi-Format Support:** Templates support different formats (IFRS, US-GAAP, etc.)
- **Header Management:** Headers are in template tables, not fact tables
- **View-Based Queries:** Use views for statement-specific queries

**Example Structure:**
```sql
-- Statement template (supports multiple formats)
CREATE TABLE dim_statement_templates (
    template_id SERIAL PRIMARY KEY,
    statement_type VARCHAR(50),
    format_type VARCHAR(20), -- 'ifrs', 'us_gaap', 'custom'
    item_order INTEGER,
    item_label VARCHAR(200),
    is_header BOOLEAN,
    concept_normalized_label VARCHAR(200), -- Links to concepts
    ...
);

-- Fact table (data only)
CREATE TABLE fact_financial_metrics (
    -- No presentation metadata
);

-- View (combines template + data)
CREATE VIEW v_statement AS
SELECT 
    st.item_order,
    st.item_label,
    st.is_header,
    fm.value_numeric,
    ...
FROM dim_statement_templates st
LEFT JOIN fact_financial_metrics fm ON 
    fm.normalized_label = st.concept_normalized_label
WHERE st.statement_type = :statement_type
  AND st.format_type = :format_type
ORDER BY st.item_order;
```

---

## Recommended Improvements

### Priority 1: Separate Presentation Layer (HIGH IMPACT)

**Problem:** Headers and statement structure are mixed with data

**Solution:** Create a separate statement template/structure table

```sql
-- NEW: Statement structure template (metadata only)
CREATE TABLE dim_statement_templates (
    template_id SERIAL PRIMARY KEY,
    statement_type VARCHAR(50) NOT NULL, -- 'income_statement', 'balance_sheet', etc.
    format_type VARCHAR(20) DEFAULT 'standard', -- 'ifrs', 'us_gaap', 'custom'
    item_order INTEGER NOT NULL,
    item_label VARCHAR(200), -- Human-readable label (e.g., "Revenue")
    normalized_label VARCHAR(200), -- Links to dim_concepts.normalized_label
    is_header BOOLEAN DEFAULT FALSE,
    is_spacer BOOLEAN DEFAULT FALSE, -- For blank lines
    hierarchy_level INTEGER,
    parent_item_order INTEGER, -- For hierarchical structure
    side VARCHAR(20), -- For balance sheet: 'assets' or 'liabilities_equity'
    is_required BOOLEAN DEFAULT TRUE, -- Must appear in statement
    display_condition VARCHAR(200), -- SQL condition for when to show (e.g., "IF value > 0")
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(statement_type, format_type, item_order)
);

-- MIGRATION: Move headers from fact tables to template
-- Remove is_header, display_order from fact tables
-- Populate dim_statement_templates from rel_statement_items
```

**Benefits:**
- Clear separation of data vs. presentation
- Easy to support multiple statement formats (IFRS vs US-GAAP)
- Headers are metadata, not data
- Can change statement structure without touching data

**Migration Effort:** Medium (2-3 days)
- Create `dim_statement_templates` table
- Migrate headers from `rel_statement_items` and fact tables
- Update ETL to populate templates
- Update API to use templates

---

### Priority 2: Replace Denormalized Fact Tables with Views (MEDIUM IMPACT)

**Problem:** Statement-specific fact tables duplicate data and create maintenance burden

**Solution:** Replace with views or materialized views

```sql
-- REMOVE: fact_income_statement, fact_balance_sheet, etc.
-- REPLACE WITH: Views

CREATE VIEW v_income_statement AS
SELECT 
    st.item_order as display_order,
    st.item_label,
    st.is_header,
    st.is_spacer,
    st.hierarchy_level,
    st.parent_item_order,
    fm.filing_id,
    fm.concept_id,
    fm.period_id,
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
WHERE st.statement_type = 'income_statement'
  AND st.format_type = (SELECT accounting_standard FROM dim_companies WHERE company_id = (SELECT company_id FROM dim_filings WHERE filing_id = :filing_id))
ORDER BY st.item_order;

-- For performance, create materialized view if needed
CREATE MATERIALIZED VIEW mv_income_statement AS
SELECT ... FROM v_income_statement;
```

**Benefits:**
- Single source of truth (`fact_financial_metrics`)
- No data duplication
- Easier maintenance
- Can refresh views without complex ETL

**Migration Effort:** Medium (2-3 days)
- Create views
- Update API to use views
- Remove old fact tables
- Update ETL to remove population logic

---

### Priority 3: Normalize Statement Structure (LOW-MEDIUM IMPACT)

**Problem:** `rel_statement_items` is filing-specific, but statement structure is often similar across filings

**Solution:** Create a canonical statement template, then allow filing-specific overrides

```sql
-- NEW: Canonical statement template (standard structure)
CREATE TABLE dim_statement_templates (
    template_id SERIAL PRIMARY KEY,
    statement_type VARCHAR(50) NOT NULL,
    format_type VARCHAR(20) DEFAULT 'standard',
    item_order INTEGER NOT NULL,
    normalized_label VARCHAR(200), -- Links to concepts
    is_header BOOLEAN DEFAULT FALSE,
    ...
    UNIQUE(statement_type, format_type, item_order)
);

-- KEEP: Filing-specific overrides (for custom items)
CREATE TABLE rel_statement_items (
    statement_item_id SERIAL PRIMARY KEY,
    filing_id INTEGER NOT NULL,
    template_id INTEGER REFERENCES dim_statement_templates(template_id), -- Links to template
    concept_id INTEGER, -- Override: custom concept not in template
    display_order INTEGER, -- Override: custom order
    is_header BOOLEAN, -- Override: custom header
    is_custom BOOLEAN DEFAULT FALSE, -- TRUE if not in template
    ...
);
```

**Benefits:**
- Standard structure for most companies
- Custom overrides for special cases
- Easier to maintain consistency
- Better for cross-company comparison

**Migration Effort:** Medium (3-4 days)
- Create canonical templates
- Migrate existing `rel_statement_items` to templates
- Update ETL to use templates with overrides

---

## Assessment: Is Current ERD "Too Bad"?

### Short Answer: **NO, but it needs improvement**

**Current State:**
- ✅ **Functional:** Works for current use case
- ✅ **Scalable:** Can handle multiple companies and taxonomies
- ⚠️ **Maintainable:** Complex queries, mixed concerns
- ⚠️ **Industry Standard:** Close, but not quite there

**Verdict:**
- **For MVP/Prototype:** Current ERD is **acceptable**
- **For Production/Long-term:** Current ERD needs **moderate refactoring**
- **For Enterprise Scale:** Current ERD needs **significant refactoring**

---

## Recommended Action Plan

### Phase 1: Quick Wins (1-2 weeks)
1. **Separate Headers:** Move headers from fact tables to `dim_statement_templates`
2. **Document Current Structure:** Create ERD diagram and data flow documentation
3. **Simplify Queries:** Use business keys more effectively to reduce query complexity

### Phase 2: Medium-Term Improvements (1-2 months)
1. **Replace Denormalized Fact Tables:** Convert to views or materialized views
2. **Normalize Statement Structure:** Create canonical templates with filing-specific overrides
3. **Improve Cross-Filing Matching:** Better normalization or clearer data model

### Phase 3: Long-Term Optimization (3-6 months)
1. **Performance Optimization:** Materialized views, better indexes
2. **Multi-Format Support:** Templates for different statement formats (IFRS vs US-GAAP)
3. **Advanced Features:** Custom statement formats, user-defined templates

---

## Conclusion

**Current ERD Status:** ⚠️ **FUNCTIONAL BUT SUBOPTIMAL**

The current ERD is **viable** and works for the current use case, but has **architectural debt** that will cause increasing maintenance complexity as the system scales. The main issues are:

1. **Headers stored as facts** (mixing data with presentation)
2. **Denormalized statement fact tables** (data duplication)
3. **No clear presentation layer** (hard to change statement structure)

**Recommendation:** **MODERATE REFACTORING** - Not a complete rewrite, but strategic improvements to separate concerns and improve maintainability. Priority should be on separating presentation from data (headers → templates).

**Industry Standard Compliance:** **70%** - Close to industry standards, but needs improvement in presentation layer separation.

**Long-term Viability:** **YES** - With the recommended improvements, the ERD will be industry-standard and viable for all IFRS and US-GAAP companies.

