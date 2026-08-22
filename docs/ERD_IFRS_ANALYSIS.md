# ERD Analysis: IFRS Considerations & Industry Standards

## Executive Summary

**IFRS was partially considered** in the ERD revision, but there are **gaps and opportunities for improvement** to make this a true "Swiss Army knife" for financial data analysis.

## Current IFRS Support

### ✅ What's Working

1. **Accounting Standard Tracking**
   - `dim_companies.accounting_standard` stores 'US-GAAP' or 'IFRS'
   - Automatically detected from filing type (20-F = IFRS, 10-K = US-GAAP)

2. **Template-Based Presentation**
   - `dim_statement_templates.format_type` supports 'ifrs', 'us_gaap', 'ifrs_eu', 'custom'
   - Functions correctly map `accounting_standard` → `format_type`

3. **Concept Normalization**
   - `normalized_label` allows cross-taxonomy queries
   - `taxonomy_mappings` table exists (but underutilized)

4. **Single Normalized Fact Table**
   - ✅ Industry standard: One fact table for all standards
   - Facts are facts, regardless of reporting framework

### ⚠️ Gaps & Issues

1. **No Taxonomy Dimension**
   - Taxonomy is just a VARCHAR in `dim_concepts`
   - No metadata about taxonomies (version, jurisdiction, etc.)
   - Can't query "all IFRS concepts" efficiently

2. **No Reporting Framework Dimension**
   - `accounting_standard` is just a VARCHAR
   - No framework metadata (effective dates, jurisdictions, etc.)
   - Can't track framework changes over time

3. **Concept Mapping Table Underutilized**
   - `taxonomy_mappings` exists but isn't actively used
   - No cross-taxonomy equivalence mapping (IFRS Revenue → US-GAAP Revenue)
   - Can't do "show me revenue for all companies regardless of standard"

4. **Template Population Logic**
   - Templates created from `rel_statement_items` without checking `accounting_standard`
   - Format type inferred, but not always correctly
   - No validation that templates match company's standard

5. **No Multi-Standard Support**
   - Can't handle companies that report in multiple standards
   - Can't track restatements from one standard to another
   - No support for dual-listed companies (IFRS + US-GAAP)

## Industry Standards Analysis

### How Big 4 / Hedge Funds Handle This

**Single Normalized Fact Table** ✅ (We have this)
- All facts in one table, regardless of standard
- Standard is a dimension attribute, not a table separator

**Taxonomy Dimension** ❌ (We're missing this)
- Separate `dim_taxonomies` table with:
  - Taxonomy name, version, jurisdiction
  - Effective dates, superseded dates
  - Framework relationships (IFRS → IFRS-EU → IFRS-UK)

**Concept Mapping Tables** ❌ (We have structure, but not used)
- `rel_concept_mappings` table:
  - Maps IFRS concepts to US-GAAP equivalents
  - Maps old taxonomy versions to new
  - Enables cross-standard analysis

**Reporting Framework Dimension** ❌ (We're missing this)
- `dim_reporting_frameworks` table:
  - Framework name (IFRS, US-GAAP, etc.)
  - Jurisdiction, effective dates
  - Relationships (IFRS is parent of IFRS-EU)

**Template Tables Per Framework** ✅ (We have this)
- Separate templates per `format_type`
- But should be linked to `dim_reporting_frameworks`

## Recommendations

### Priority 1: Critical for Multi-Standard Analysis

1. **Add `dim_taxonomies` Table**
   ```sql
   CREATE TABLE dim_taxonomies (
       taxonomy_id SERIAL PRIMARY KEY,
       taxonomy_name VARCHAR(50) NOT NULL UNIQUE, -- 'us-gaap', 'ifrs-full', 'ifrs-eu'
       taxonomy_version VARCHAR(20), -- '2024', '2023', etc.
       reporting_framework VARCHAR(20), -- 'US-GAAP', 'IFRS', etc.
       jurisdiction VARCHAR(3), -- 'US', 'EU', 'GB', etc.
       effective_date DATE,
       superseded_date DATE,
       parent_taxonomy_id INTEGER REFERENCES dim_taxonomies(taxonomy_id),
       is_active BOOLEAN DEFAULT TRUE
   );
   ```

2. **Add `dim_reporting_frameworks` Table**
   ```sql
   CREATE TABLE dim_reporting_frameworks (
       framework_id SERIAL PRIMARY KEY,
       framework_name VARCHAR(50) NOT NULL UNIQUE, -- 'IFRS', 'US-GAAP', 'UK-GAAP'
       framework_code VARCHAR(20) NOT NULL UNIQUE, -- 'IFRS', 'USGAAP', 'UKGAAP'
       jurisdiction VARCHAR(3),
       standard_setter VARCHAR(100), -- 'IASB', 'FASB', 'FRC'
       effective_date DATE,
       is_active BOOLEAN DEFAULT TRUE
   );
   ```

3. **Enhance `taxonomy_mappings` → `rel_concept_mappings`**
   ```sql
   CREATE TABLE rel_concept_mappings (
       mapping_id SERIAL PRIMARY KEY,
       source_concept_id INTEGER NOT NULL REFERENCES dim_concepts(concept_id),
       target_concept_id INTEGER NOT NULL REFERENCES dim_concepts(concept_id),
       mapping_type VARCHAR(20) NOT NULL, -- 'equivalent', 'similar', 'approximate'
       confidence_score NUMERIC(3,2), -- 0.00 to 1.00
       mapping_source VARCHAR(50), -- 'manual', 'automated', 'industry_standard'
       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
       UNIQUE(source_concept_id, target_concept_id)
   );
   ```

4. **Link Templates to Frameworks**
   ```sql
   ALTER TABLE dim_statement_templates 
   ADD COLUMN framework_id INTEGER REFERENCES dim_reporting_frameworks(framework_id);
   
   -- Replace format_type with framework_id for better normalization
   ```

### Priority 2: Enhanced Analysis Capabilities

5. **Add `dim_fiscal_periods` for Period Normalization**
   ```sql
   CREATE TABLE dim_fiscal_periods (
       fiscal_period_id SERIAL PRIMARY KEY,
       company_id INTEGER REFERENCES dim_companies(company_id),
       fiscal_year INTEGER NOT NULL,
       fiscal_year_end_month INTEGER NOT NULL, -- 1-12
       fiscal_year_end_day INTEGER NOT NULL, -- Usually 31
       calendar_year INTEGER, -- For calendar-year companies, same as fiscal_year
       is_calendar_year BOOLEAN DEFAULT FALSE,
       UNIQUE(company_id, fiscal_year)
   );
   ```
   - Enables "Q1 2024" comparisons across companies with different fiscal year ends
   - Critical for cross-company analysis

6. **Add `rel_standard_restatements` for Tracking Changes**
   ```sql
   CREATE TABLE rel_standard_restatements (
       restatement_id SERIAL PRIMARY KEY,
       company_id INTEGER REFERENCES dim_companies(company_id),
       from_framework_id INTEGER REFERENCES dim_reporting_frameworks(framework_id),
       to_framework_id INTEGER REFERENCES dim_reporting_frameworks(framework_id),
       restatement_date DATE,
       reason TEXT,
       impact_amount NUMERIC(20,2)
   );
   ```

### Priority 3: Swiss Army Knife Features

7. **Add `dim_currencies` for Multi-Currency Analysis**
   ```sql
   CREATE TABLE dim_currencies (
       currency_id SERIAL PRIMARY KEY,
       currency_code VARCHAR(3) NOT NULL UNIQUE, -- 'USD', 'EUR', 'DKK'
       currency_name VARCHAR(100),
       is_base_currency BOOLEAN DEFAULT FALSE
   );
   ```
   - Link to `fact_financial_metrics` for currency conversion
   - Enable "show all values in USD" queries

8. **Add `fact_ratios` for Pre-Calculated Metrics**
   ```sql
   CREATE TABLE fact_ratios (
       ratio_id SERIAL PRIMARY KEY,
       company_id INTEGER REFERENCES dim_companies(company_id),
       period_id INTEGER REFERENCES dim_time_periods(period_id),
       ratio_type VARCHAR(50), -- 'roe', 'roa', 'current_ratio', etc.
       ratio_value NUMERIC(20,4),
       numerator_concept_id INTEGER REFERENCES dim_concepts(concept_id),
       denominator_concept_id INTEGER REFERENCES dim_concepts(concept_id),
       UNIQUE(company_id, period_id, ratio_type)
   );
   ```
   - Pre-calculated ratios for performance
   - Can be materialized view instead

9. **Add `dim_segments` for Segment Reporting**
   ```sql
   CREATE TABLE dim_segments (
       segment_id SERIAL PRIMARY KEY,
       company_id INTEGER REFERENCES dim_companies(company_id),
       segment_name VARCHAR(200) NOT NULL,
       segment_type VARCHAR(50), -- 'operating', 'geographic', 'product'
       parent_segment_id INTEGER REFERENCES dim_segments(segment_id),
       UNIQUE(company_id, segment_name)
   );
   ```
   - Link to `fact_financial_metrics` via dimensions
   - Enable segment-level analysis

## Should We Have Different Tables Per Standard?

### ❌ NO - Keep Single Normalized Fact Table

**Reasons:**
1. **Industry Standard**: All major data warehouses use single fact table
2. **Query Simplicity**: One query works for all standards
3. **Normalization Works**: `normalized_label` + `accounting_standard` = sufficient
4. **Performance**: Single table is faster than multiple tables
5. **Maintenance**: One table is easier to maintain

**What We SHOULD Have:**
- ✅ Single fact table (we have this)
- ✅ Framework as dimension attribute (we have this via `accounting_standard`)
- ❌ Framework dimension table (we're missing this)
- ❌ Concept mapping table (we have structure but not used)
- ❌ Taxonomy dimension (we're missing this)

## Implementation Priority

### Phase 1: Foundation (Critical)
1. `dim_taxonomies` - Enable taxonomy queries
2. `dim_reporting_frameworks` - Framework metadata
3. Enhance `taxonomy_mappings` → `rel_concept_mappings` - Cross-standard analysis

### Phase 2: Analysis (High Value)
4. `dim_fiscal_periods` - Period normalization
5. Link templates to frameworks - Better template management

### Phase 3: Advanced (Nice to Have)
6. `dim_currencies` - Multi-currency support
7. `fact_ratios` - Pre-calculated metrics
8. `dim_segments` - Segment reporting

## Conclusion

**IFRS was considered**, but the implementation is **incomplete**. The current ERD is good for single-standard analysis but needs enhancement for true multi-standard, cross-company analysis.

**Key Missing Pieces:**
1. Taxonomy dimension (critical)
2. Reporting framework dimension (critical)
3. Concept mapping table (high value)
4. Fiscal period normalization (high value)

**Recommendation:** Implement Phase 1 (taxonomy + framework dimensions) to enable proper multi-standard support, then Phase 2 for enhanced analysis capabilities.

