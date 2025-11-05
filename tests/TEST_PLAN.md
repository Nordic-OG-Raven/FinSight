# FinSight Comprehensive Test Plan

## Overview
This document outlines all beneficial unit tests and validation tests for the FinSight financial data pipeline.

## Status Update (2025-11-03)
**✅ VALIDATOR INTEGRATION COMPLETE:**
The following validation checks have been integrated into the pipeline validator (`src/validation/validator.py`):
- ✅ Accounting Identity Checks (Category 6)
- ✅ Calculation Relationship Validation (Category 7)
- ✅ Data Quality Checks (Category 5 - partial)

**📋 VALIDATOR = Pipeline Integration (Runs Automatically)**
- These checks run automatically in the pipeline after data loading
- Ensures data quality before data persists
- Part of the 100% validation score goal
- All fixes are lasting (work for any company, any data load)

**🔧 UNIT TESTS = Separate (CI/CD)**
- Function-level tests (test individual functions)
- Can run with mock data (no DB needed)
- Tests code logic, not data correctness

## Test Categories

### 1. XBRL Parsing Tests (`test_parse_xbrl.py`)

#### Unit Tests
- **test_parse_valid_filing()**
  - Test parsing a valid 10-K filing
  - Verify all facts extracted
  - Check concept names, values, periods, dimensions

- **test_parse_inline_xbrl()**
  - Test parsing iXBRL (HTML) vs traditional XBRL packages
  - Verify same data extracted from both formats

- **test_extract_relationships()**
  - Test calculation linkbase extraction
  - Test presentation linkbase extraction
  - Test footnote linkbase extraction
  - Verify parent-child relationships
  - Verify weights/order indices

- **test_handle_malformed_xbrl()**
  - Test handling of missing required elements
  - Test handling of invalid XML
  - Verify graceful error handling

- **test_extract_dimensions()**
  - Test dimensional data extraction (segments, axes, members)
  - Verify dimension hierarchies
  - Test explicit vs typed dimensions

- **test_deduplication_logic()**
  - Test fact deduplication during parsing
  - Verify `is_primary` flag assignment
  - Test `order_index` prioritization

- **test_scale_and_decimals()**
  - Test scale factor handling (-3 for thousands, -6 for millions)
  - Test decimal precision
  - Verify numeric value accuracy

- **test_period_extraction()**
  - Test instant vs duration period types
  - Test fiscal year/quarter extraction
  - Test period boundary alignment

---

### 2. Taxonomy Normalization Tests (`test_taxonomy_mappings.py`)

#### Unit Tests
- **test_explicit_mappings()**
  - Test all explicit concept mappings
  - Verify priority ordering (most specific first)
  - Test cross-taxonomy mappings (US-GAAP ↔ IFRS)

- **test_auto_normalization()**
  - Test CamelCase → snake_case conversion
  - Test hash suffix for long labels
  - Verify uniqueness guarantee

- **test_text_field_marking()**
  - Test `_note` suffix for text blocks
  - Test `_disclosure_note` for disclosures
  - Test `_section_header` for abstracts

- **test_normalization_conflicts()**
  - Test that no semantic conflicts exist
  - Verify distinct concepts → distinct labels
  - Test intentional cross-taxonomy merges

- **test_statement_type_inference()**
  - Test balance_sheet concept classification
  - Test income_statement concept classification
  - Test cash_flow concept classification

- **test_label_length_limits()**
  - Test labels don't exceed maximum length
  - Test hash suffix generation for long labels
  - Verify collision resistance

---

### 3. Database Loading Tests (`test_load_financial_data.py`)

#### Unit Tests
- **test_star_schema_creation()**
  - Test dim_companies table creation
  - Test dim_concepts table creation
  - Test dim_time_periods table creation
  - Test dim_filings table creation
  - Test dim_xbrl_dimensions table creation
  - Test fact_financial_metrics table creation
  - Test relationship tables creation

- **test_get_or_create_company()**
  - Test inserting new company
  - Test retrieving existing company
  - Verify idempotency

- **test_get_or_create_concept()**
  - Test inserting new concept with normalization
  - Test retrieving existing concept
  - Test statement_type assignment

- **test_get_or_create_period()**
  - Test inserting new period
  - Test fiscal year/quarter extraction
  - Test period type (instant/duration)

- **test_get_or_create_dimension()**
  - Test inserting new dimension
  - Test axis-member pair creation
  - Test dimension value storage

- **test_load_fact()**
  - Test fact insertion with all fields
  - Test unique constraint (filing_id, concept_id, period_id, dimension_id)
  - Test `NULLS NOT DISTINCT` handling

- **test_load_fact_update()**
  - Test `ON CONFLICT DO UPDATE` behavior
  - Verify existing facts are updated, not duplicated

- **test_load_relationships()**
  - Test calculation hierarchy loading
  - Test presentation hierarchy loading
  - Test footnote references loading
  - Verify source, is_synthetic, confidence fields

- **test_transaction_rollback()**
  - Test transaction rollback on error
  - Verify atomicity of loading

---

### 4. Data Completeness Tests (`test_completeness.py`)

#### Validation Tests
- **test_fact_count_per_filing()**
  - Verify minimum fact count per filing
  - Flag filings with suspiciously low fact counts
  - Compare against expected ranges (SEC: 3-5k, ESEF: 5-10k)

- **test_critical_metrics_present()**
  - Test revenue present in all companies
  - Test net_income present in all companies
  - Test total_assets present in all companies
  - Test stockholders_equity present in all companies
  - Test operating_cash_flow present in all companies

- **test_time_series_continuity()**
  - Test no gaps in fiscal years
  - Test consistent fiscal year-end dates
  - Verify quarterly data completeness (if applicable)

- **test_relationship_completeness()**
  - Test calculation relationships exist for major line items
  - Test presentation hierarchy exists for statements
  - Verify linkbase coverage

---

### 5. Data Quality Tests (`test_data_quality.py`)

#### ✅ INTEGRATED INTO VALIDATOR (Pipeline)
- ✅ **test_no_user_facing_duplicates()** → `_check_user_facing_duplicates()`
- ✅ **test_normalization_coverage()** → `_check_normalization_coverage()`
- ✅ **test_numeric_value_range()** → `_check_numeric_value_ranges()`
- ✅ **test_unit_consistency()** → `_check_unit_consistency()`
- ✅ **test_normalization_quality()** → `_check_normalization_conflicts()`

#### 🔧 REMAIN AS SEPARATE UNIT TESTS
- **test_no_database_duplicates()**
  - Test unique constraint enforcement
  - Verify no identical facts (same fact_id tuple)

- **test_dimensional_data_quality()**
  - Test dimensional facts have valid dimension_id
  - Test axis-member pairs are valid
  - Verify segment names are populated

---

### 6. Accounting Identity Tests (`test_accounting_identities.py`)

#### ✅ INTEGRATED INTO VALIDATOR (Pipeline)
- ✅ **test_balance_sheet_equation()** → `_check_balance_sheet_equation()`
- ✅ **test_retained_earnings_rollforward()** → `_check_retained_earnings_rollforward()`
- ✅ **test_cash_flow_to_balance_sheet()** → `_check_cash_flow_reconciliation()`
- ✅ **test_gross_profit_margin()** → `_check_gross_profit_margin()`
- ✅ **test_operating_income_calculation()** → `_check_operating_income_calculation()`

#### 🔧 REMAIN AS SEPARATE UNIT TESTS
- **test_eps_calculation()**
  - Test `EPS = Net Income / Weighted Average Shares`
  - Test both basic and diluted EPS
  - Tolerance: 3% (rounding in large numbers)

- **test_revenue_to_accounts_receivable()**
  - Test Days Sales Outstanding (DSO) is reasonable
  - Flag extreme values (< 0 days, > 365 days)

---

### 7. Relationship Tests (`test_relationships.py`)

#### ✅ INTEGRATED INTO VALIDATOR (Pipeline)
- ✅ **test_calculation_relationships()** → `_check_calculation_relationships()`
  - Checks parent = sum(children) for all calc relationships
  - Tolerance: 0.1% (XBRL precision)
  - Only checks relationships with confidence >= 0.995

#### 🔧 REMAIN AS SEPARATE UNIT TESTS
- **test_relationship_confidence()**
  - Test all relationships have confidence >= 0.995
  - Verify no low-confidence synthetic relationships

- **test_presentation_hierarchy()**
  - Test all statement line items have presentation order
  - Verify parent-child relationships are valid
  - Test no circular references

- **test_footnote_linkages()**
  - Test footnote references point to valid facts
  - Verify bidirectional linkage (fact ↔ footnote)

---

### 8. Cross-Company Comparability Tests (`test_comparability.py`)

#### Validation Tests
- **test_same_metric_across_companies()**
  - Test `revenue` is comparable across all companies
  - Test `net_income` is comparable
  - Test `total_assets` is comparable

- **test_ifrs_vs_usgaap_mapping()**
  - Test IFRS concepts map to equivalent US-GAAP concepts
  - Verify intentional cross-taxonomy merges
  - Test no loss of semantic meaning

- **test_industry_specific_metrics()**
  - Test pharma companies have R&D expense
  - Test banks have interest income
  - Test tech companies have stock-based compensation

---

### 9. Pipeline Integration Tests (`test_pipeline.py`)

#### Integration Tests
- **test_full_etl_pipeline()**
  - Test complete pipeline: fetch → parse → load → normalize → validate
  - Verify end-to-end for a single company
  - Check data integrity at each stage

- **test_incremental_loading()**
  - Test loading new filing for existing company
  - Verify no duplication of old data
  - Test update of changed facts

- **test_multi_company_loading()**
  - Test loading 10+ companies in sequence
  - Verify no cross-contamination
  - Test performance (< 5 min per company)

- **test_error_recovery()**
  - Test handling of parsing errors (skip filing, continue)
  - Test handling of database errors (rollback transaction)
  - Verify logging of errors

---

### 10. API Tests (`test_api.py`)

#### Integration Tests
- **test_analyze_endpoint()**
  - Test `/api/analyze` with valid company ticker
  - Verify response structure
  - Test filtering by fiscal year, metric

- **test_api_error_handling()**
  - Test invalid ticker returns 404
  - Test invalid parameters return 400
  - Test database errors return 500

- **test_api_cors()**
  - Test CORS headers are set correctly
  - Verify frontend can access API

- **test_api_rate_limiting()**
  - Test rate limits are enforced (if applicable)
  - Verify appropriate error messages

---

### 11. UI Tests (`test_data_viewer.py`)

#### UI/UX Tests
- **test_viewer_loads()**
  - Test Streamlit app starts without errors
  - Test database connection established
  - Verify filters are populated

- **test_company_filter()**
  - Test selecting different companies
  - Verify data updates correctly

- **test_metric_filter()**
  - Test filtering by normalized labels
  - Verify partial matching works

- **test_fiscal_year_range()**
  - Test year range slider
  - Verify data filtered correctly

- **test_segment_breakdown_toggle()**
  - Test "Show segment breakdowns" checkbox
  - Verify dimensional data appears/disappears
  - Test column visibility logic

- **test_visualization_rendering()**
  - Test time series chart renders
  - Verify discrete fiscal year axis (no interpolation)
  - Test multiple metrics on same chart

- **test_export_data()**
  - Test CSV export functionality
  - Verify exported data matches displayed data

---

### 12. Performance Tests (`test_performance.py`)

#### Performance Tests
- **test_parsing_speed()**
  - Test parsing 10-K in < 30 seconds
  - Test parsing 20-F in < 45 seconds
  - Benchmark against target (3-5k facts/sec)

- **test_loading_speed()**
  - Test loading parsed JSON to database in < 10 seconds
  - Verify bulk insert performance

- **test_normalization_speed()**
  - Test normalizing 3k concepts in < 5 seconds
  - Verify caching improves subsequent runs

- **test_query_performance()**
  - Test viewer queries return in < 2 seconds
  - Test API queries return in < 1 second
  - Verify indexes are used

- **test_memory_usage()**
  - Test parsing doesn't exceed 1GB RAM
  - Test database loading doesn't cause memory leaks

---

### 13. Security Tests (`test_security.py`)

#### Security Tests
- **test_sql_injection_prevention()**
  - Test parameterized queries prevent SQL injection
  - Verify user input sanitization

- **test_xss_prevention()**
  - Test HTML escaping in viewer
  - Verify no script injection through data

- **test_environment_variable_protection()**
  - Test sensitive env vars (DATABASE_URL) not exposed
  - Verify logging doesn't leak credentials

- **test_api_authentication()**
  - Test API requires authentication (if applicable)
  - Verify token validation

---

### 14. Edge Case Tests (`test_edge_cases.py`)

#### Edge Case Tests
- **test_zero_values()**
  - Test handling of zero values (not NULL)
  - Verify $0 revenue is valid
  - Test zero shares outstanding

- **test_negative_values()**
  - Test handling of negative net income (losses)
  - Test negative cash flow
  - Verify negative equity (bankruptcy)

- **test_missing_periods()**
  - Test handling of missing fiscal years
  - Test quarterly vs annual data mismatches

- **test_extreme_scales()**
  - Test very large numbers (> $1T for big companies)
  - Test very small numbers (< $1M for startups)
  - Verify scale factors applied correctly

- **test_null_dimensions()**
  - Test facts with NULL dimension_id (consolidated)
  - Test `NULLS NOT DISTINCT` constraint

- **test_foreign_characters()**
  - Test handling of non-ASCII characters in company names
  - Test Unicode in concept labels

- **test_date_boundaries()**
  - Test fiscal year-end on different dates (not 12/31)
  - Test leap years
  - Test period transitions

---

### 15. Regression Tests (`test_regression.py`)

#### Regression Tests
- **test_apple_fy2023_revenue()**
  - Test specific known values don't change
  - AAPL FY2023 revenue should be $383.3B

- **test_google_fy2024_net_income()**
  - Test GOOGL FY2024 net income
  - Verify no rounding errors introduced

- **test_novo_nordisk_fact_count()**
  - Test NVO has >= 2,500 facts per filing
  - Verify no data loss in re-processing

- **test_depreciation_separation()**
  - Test AAPL FY2023 has both:
    - `depreciation`: $8.5B
    - `depreciation_depletion_and_amortization`: $11.5B
  - Verify no conflation

---

## Test Execution Strategy

### Priority Levels
1. **P0 (Critical)**: Run before every commit
   - test_balance_sheet_equation
   - test_no_user_facing_duplicates
   - test_normalization_coverage
   - test_full_etl_pipeline

2. **P1 (High)**: Run before every PR merge
   - All accounting identity tests
   - All data quality tests
   - API tests

3. **P2 (Medium)**: Run nightly
   - All unit tests
   - Performance tests
   - Cross-company comparability tests

4. **P3 (Low)**: Run weekly
   - Security tests
   - Edge case tests
   - Regression tests

### Test Framework
- **Unit Tests**: pytest
- **Integration Tests**: pytest with fixtures
- **Performance Tests**: pytest-benchmark
- **UI Tests**: pytest + Streamlit testing library

### Coverage Goals
- **Line Coverage**: > 80%
- **Branch Coverage**: > 70%
- **Critical Path Coverage**: 100%

### CI/CD Integration
```bash
# Pre-commit hooks
pytest tests/test_normalization.py
pytest tests/test_data_quality.py

# PR checks
pytest tests/ --cov=src --cov-report=html

# Nightly builds
pytest tests/ --benchmark-only --benchmark-autosave

# Weekly full regression
pytest tests/ --slow --run-regression
```

---

## Test Data
- **Mock Data**: Small synthetic datasets for unit tests
- **Fixture Filings**: Real 10-K/20-F samples (3-4 companies)
- **Production Sample**: 11 companies currently loaded (AAPL, GOOGL, etc.)

---

## Test Metrics to Track
1. **Test Execution Time**: < 5 minutes for full suite
2. **Flakiness Rate**: < 1% (re-run failed tests)
3. **Coverage Trend**: Track over time, aim for upward trend
4. **Bug Detection Rate**: % of bugs caught by tests vs production
5. **Regression Prevention**: % of regressions caught before deployment

