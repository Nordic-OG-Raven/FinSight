# FinSight Data Integrity Upgrade Plan

## Executive Summary

This document outlines a comprehensive upgrade to FinSight's data validation and integrity framework. The upgrade addresses:
1. **Root cause fix**: Loader fact selection logic (selecting wrong equity facts when multiple exist)
2. **Validation architecture**: Modular validation system with single responsibility principle
3. **Universal testing**: UITest.py made universal and integrated into pipeline
4. **Data quality**: Enhanced validation at every pipeline stage

## Problem Statement

### Root Cause: Loader Fact Selection Bug & Data Loss

**Issue**: The loader loses data when multiple consolidated facts exist with different context_ids.

**Evidence**:
- Raw XBRL has multiple "Equity" facts: 2021: 930, 70,746, 72,004 (all scale=6, different context_ids)
- Loader loses 33.4% of facts (1,872 of 5,601) due to UNIQUE constraint conflicts
- Revenue: 219 consolidated facts per period → only 7 loaded (650 lost)
- Equity: 27 consolidated facts per period → only 1 loaded (26 lost per period)
- `fix_equity_values()` masks the equity issue by calculating correct value, but doesn't address data loss

**Root Cause**: 
- Multiple consolidated facts (dimension_id=NULL) with same business key but different context_ids conflict
- UNIQUE constraint: `(filing_id, normalized_label, fiscal_year, period_type, dimension_id)`
- Only one fact preserved, others dropped
- **Note**: Many consolidated facts legitimately lack dimensions by design (aggregated totals)

**Solution**: Synthetic `ContextAxis` dimensions preserve all facts:
- First fact keeps `dimension_id=NULL` (primary consolidated)
- Subsequent facts get `ContextAxis: Context_{context_id}` dimension
- All facts preserved and queryable

**Impact**: 
- **Before**: 33.4% data loss, wrong primary values selected
- **After**: 0% data loss, all facts preserved and usable
- All XBRL data available for analysis (not just SEC API subset)

### Current Validation Gaps

1. **No pre-load validation**: Facts dicts validated only after loading
2. **No concept mapping validation**: Wrong concepts can map to normalized labels
3. **No loader validation**: No checks on fact selection logic
4. **Hardcoded UITest**: Company-specific, not integrated
5. **Monolithic validator**: 3852 lines, mixed responsibilities

## Implementation Plan

### Phase 1: Fix Loader Fact Selection Logic

**Priority**: CRITICAL (fixes root cause, preserves and makes usable all data)

**Location**: `database/load_financial_data.py` (StarSchemaLoader)

**Current State**: 
- Multiple consolidated facts (dimension_id=NULL) with same business key but different context_ids conflict
- Only one fact is preserved, others are lost (33.4% data loss)
- Synthetic `ContextAxis` dimensions preserve all facts, but need to ensure they're usable

**Changes**:
1. **Preserve all facts using synthetic dimensions** (IMPLEMENTED):
   - When multiple consolidated facts exist with different context_ids, create synthetic `ContextAxis` dimensions
   - First fact keeps `dimension_id=NULL` (primary consolidated)
   - Subsequent facts get `ContextAxis: Context_{context_id}` dimension
   - **All facts are preserved and queryable** - no data loss

2. **Make synthetic dimensions usable for analysis**:
   - Update queries to treat `ContextAxis` dimensions as consolidated facts
   - Views (`v_facts_consolidated`) already include synthetic dimensions
   - Validators should prefer primary (dimension_id=NULL) but can use all
   - API can expose all context variants or aggregate them

3. **Enhance fact selection for primary consolidated**:
   - When selecting which fact gets `dimension_id=NULL` (primary), prefer:
     - Facts where `value_numeric ≈ Assets - Liabilities` (within 5% tolerance)
     - Facts from primary contexts (identify via context_id patterns or metadata)
     - Facts with `is_primary=TRUE` flag if available
   - Add validation: If primary equity doesn't match Assets - Liabilities, log warning

4. **Generalize for all concepts**:
   - Apply synthetic dimension logic to all concepts with multiple consolidated facts
   - Preserve all facts, mark one as primary
   - All facts remain queryable and usable for analysis

5. **Add loader validation**:
   - After loading, check if primary facts satisfy accounting identities
   - Log warnings for mismatches
   - Optionally auto-correct primary fact (with `is_calculated=True` flag)
   - Verify all facts are preserved (count before/after loading)

**Files to modify**:
- `database/load_financial_data.py`: Synthetic dimension logic (already implemented, verify usability)
- `src/utils/fix_equity_values.py`: Keep as fallback, but should rarely trigger
- Update queries/views to ensure synthetic dimensions are queryable

**Data Usability**:
- All facts are queryable: `WHERE dimension_id IS NULL OR axis_name = 'ContextAxis'`
- Primary fact: `WHERE dimension_id IS NULL` (for standard queries)
- All variants: `WHERE normalized_label = 'revenue'` (gets all context variants)
- Aggregation: Can aggregate across contexts or pick primary
- Analysis: All XBRL data available, not just SEC API subset

**Testing**:
- Verify all facts are preserved (count matches JSON input)
- Verify primary equity values are correct after loader runs
- Verify synthetic dimensions are queryable and usable
- Verify `fix_equity_values()` rarely needs to run
- Test with multiple companies (NVO, AAPL, etc.)

---

### Phase 2: Create Pre-Load Validation (`input_check.py`)

**Priority**: HIGH (catches issues before loading)

**Location**: `src/validation/input_check.py`

**Purpose**: Validate facts dicts before database loading

**Checks**:
1. **Accounting identities** (what's possible with facts dicts):
   - Balance sheet equation: `Assets ≈ Liabilities + Equity` (within tolerance)
     - **Note**: If multiple equity facts exist, check primary one (first context_id or largest value)
   - Gross profit logic: `gross_profit ≤ revenue` (not health-based)
   - Basic income statement flow: `revenue - costs = gross_profit`

2. **Value reasonableness**:
   - Gross margin logic: `0% ≤ gross_margin ≤ 100%` (not health ranges)
   - Unit scaling: Equity 10-80% of assets (catches loader selection bugs)
     - **Note**: Check primary equity fact if multiple exist
   - Transaction signs: Expenses negative, income positive

3. **Cross-statement consistency** (limited at this stage):
   - Net income matches between income statement and comprehensive income
   - Retained earnings changes match net income (if both present)

4. **Multiple consolidated facts detection**:
   - Warn if multiple consolidated facts exist for same concept/period
   - Verify all will be preserved (not lost due to conflicts)
   - Check if values are significantly different (might indicate data quality issue)

**Integration Point**: After gap filling, before `StarSchemaLoader.load_json_file()`

**Output**: `ValidationReport` with warnings/errors (doesn't block pipeline, but logs issues)

**Handling Missing Data**:
- If required concepts are missing (e.g., Assets for equity check), skip that check
- Log warnings for missing required concepts
- Don't fail validation if optional concepts are missing

**Example**:
```python
# In src/main.py, after gap filling:
from src.validation.input_check import InputValidator

input_validator = InputValidator()
input_report = input_validator.validate_facts(facts)
if not input_report.passed:
    logger.warning(f"Input validation issues: {input_report.overall_score:.1%}")
    # Log specific issues for debugging
```

---

### Phase 3: Create Concept Mapping Validator (`concept_checker.py`)

**Priority**: HIGH (catches concept mapping errors)

**Location**: `src/validation/concept_checker.py`

**Purpose**: Validate concept mappings after normalization

**Checks**:
1. **Wrong concepts mapped to normalized labels**:
   - Check if mapped concept makes sense (e.g., equity concept actually represents equity)
   - Compare concept values to expected ranges
   - Flag concepts that don't match their normalized label's expected behavior
   - **Note**: Check primary facts (dimension_id=NULL) for standard validation
   - **Note**: Can optionally check all context variants if values differ significantly

2. **Concept mapping conflicts**:
   - Multiple different concepts → same normalized label (when not expected)
   - Same concept → multiple normalized labels (when not expected)

3. **Taxonomy consistency**:
   - IFRS vs US-GAAP mappings are correct
   - Cross-taxonomy merges are valid

4. **Synthetic dimension validation**:
   - Verify synthetic `ContextAxis` dimensions are correctly created
   - Check that all context variants are preserved
   - Validate that primary fact (dimension_id=NULL) is reasonable

**Integration Point**: After loading to `fact_financial_metrics`, before `populate_statement_facts()`

**Output**: `ValidationReport` with concept mapping issues

**Example**:
```python
# In database/load_financial_data.py, after loading:
from src.validation.concept_checker import ConceptMappingValidator

concept_validator = ConceptMappingValidator()
concept_report = concept_validator.validate_mappings(ticker, year)
if not concept_report.passed:
    logger.warning(f"Concept mapping issues: {concept_report.overall_score:.1%}")
```

---

### Phase 4: Create Consistency Validator (`consistency_check.py`)

**Priority**: MEDIUM (catches cross-period/source issues)

**Location**: `src/validation/consistency_check.py`

**Purpose**: Cross-period and cross-source consistency

**Checks**:
1. **Cross-period consistency**:
   - Equity continuity: Ending equity ≈ Beginning equity + Net income + OCI - Dividends
     - **Note**: Use primary facts (dimension_id=NULL) for standard checks
   - Retained earnings rollforward: Ending RE ≈ Beginning RE + Net income - Dividends
   - Balance sheet equation holds across all periods

2. **Ratio reasonableness** (logic, not health):
   - Gross margin: 0% ≤ gross_margin ≤ 100%
   - Operating margin: Reasonable range (not health-based)
   - Equity ratio: 10-80% of assets (catches unit scaling)
     - **Note**: Use primary facts for ratio calculations

3. **XBRL vs SEC API consistency**:
   - When both sources exist for same concept/period, values should match (within 1% tolerance)
   - Flag significant discrepancies
   - Prefer SEC_API when both exist (already done in loader, but validate)
   - **Note**: Compare primary XBRL fact (dimension_id=NULL) with SEC API value

4. **Context variant consistency** (optional):
   - If multiple context variants exist, check if values are consistent
   - Flag if values differ significantly (might indicate data quality issue)
   - Can aggregate or pick primary for analysis

**Integration Point**: After `populate_statement_facts()`, before `validator.py`

**Output**: `ValidationReport` with consistency issues

**Example**:
```python
# In src/main.py or after populate_statement_facts:
from src.validation.consistency_check import ConsistencyValidator

consistency_validator = ConsistencyValidator()
consistency_report = consistency_validator.validate_consistency(ticker)
if not consistency_report.passed:
    logger.warning(f"Consistency issues: {consistency_report.overall_score:.1%}")
```

---

### Phase 5: Modularize `validator.py`

**Priority**: MEDIUM (improves maintainability)

**Current State**: 3852 lines, mixed responsibilities

**New Structure**:
```
src/validation/
├── validator.py              # Core DatabaseValidator (coordinator)
├── accounting_identities.py  # Balance sheet equation, retained earnings, cash flow reconciliation
├── displayed_math.py         # Statement math validation (fact_income_statement, etc.)
└── data_quality.py          # Normalization coverage, numeric ranges, unit consistency
```

**Migration Plan**:

1. **Create `accounting_identities.py`**:
   - Move `_check_balance_sheet_equation()`
   - Move `_check_retained_earnings_rollforward()`
   - Move `_check_cash_flow_reconciliation()`
   - Move `_check_gross_profit_margin()` (accounting identity)
   - Move `_check_operating_income_calculation()` (accounting identity)

2. **Create `displayed_math.py`**:
   - Move `_check_displayed_statement_math()`
   - Move `_check_income_statement_math()`
   - Move `_check_comprehensive_income_math()`
   - Move `_check_balance_sheet_displayed_math()`
   - Move `_check_cash_flow_displayed_math()`
   - Move `_check_equity_statement_math()`

3. **Create `data_quality.py`**:
   - Move `_check_data_quality()`
   - Move `_check_normalization_coverage()`
   - Move `_check_numeric_value_ranges()`
   - Move `_check_unit_consistency()`

4. **Update `validator.py`**:
   - Keep `_check_normalization_conflicts()` → Move to `concept_checker.py`
   - Keep `_check_user_facing_duplicates()` → Move to `concept_checker.py`
   - Keep `_check_company_data()` → Move to `input_check.py`
   - Keep `_check_data_completeness()` → Enhance `completeness.py`
   - Keep `_check_missing_data_matrix()` → Enhance `completeness.py`
   - Keep `_check_universal_metrics()` → Enhance `completeness.py`
   - Keep `_check_calculation_relationships()` → Move to `consistency_check.py`
   - Keep `_check_transaction_signs()` → Move to `input_check.py`
   - Keep `_check_equity_cross_period_consistency()` → Move to `consistency_check.py`
   - Keep `_check_equity_component_sums()` → Move to `consistency_check.py`
   - Import and call modules: `accounting_identities.py`, `displayed_math.py`, `data_quality.py`

**Result**: `validator.py` becomes a coordinator that calls specialized modules

---

### Phase 6: Universal UITest.py

**Priority**: HIGH (removes manual work, makes testing universal)

**Current Issues**:
- Hardcoded for NVO (`EXPECTED_NOVO_INCOME_STATEMENT`)
- Not integrated into pipeline
- Company-specific expected items
- Requires manual work to pull up reports

**Solution**: Query `rel_statement_items` instead of hardcoding

**Implementation**:

1. **Move file**: `UITest.py` → `src/validation/ui_test.py`

2. **Create `UniversalUITest` class**:
   ```python
   class UniversalUITest:
       """Universal UI test - works for any company"""
       
       def test_company(self, ticker: str, year: int) -> ValidationReport:
           """Test API output for any company"""
           
           # 1. Get expected items from rel_statement_items
           expected_items = self._get_expected_items(ticker, year)
           
           # 2. Call API
           api_data = self._call_api(ticker, year)
           
           # 3. Compare: items present, order, values
           return self._validate_output(expected_items, api_data)
       
       def _get_expected_items(self, ticker: str, year: int):
           """Query rel_statement_items - no hardcoding needed"""
           query = text("""
               SELECT 
                   co.preferred_label,
                   co.normalized_label,
                   si.display_order,
                   si.is_header,
                   si.statement_type
               FROM rel_statement_items si
               JOIN dim_concepts co ON si.concept_id = co.concept_id
               JOIN dim_filings f ON si.filing_id = f.filing_id
               JOIN dim_companies c ON f.company_id = c.company_id
               WHERE c.ticker = :ticker
                 AND EXTRACT(YEAR FROM f.fiscal_year_end) = :year
                 AND si.is_main_item = TRUE
               ORDER BY si.statement_type, si.display_order
           """)
           # Returns expected items in correct order for ANY company
   ```

3. **Remove hardcoded lists**:
   - Delete `EXPECTED_NOVO_INCOME_STATEMENT`
   - Delete `EXPECTED_NOVO_COMPREHENSIVE_INCOME`
   - Delete `EXPECTED_NOVO_BALANCE_SHEET_*`
   - Generate dynamically from database

4. **Integrate into pipeline**:
   ```python
   # In src/main.py, after populate_statement_facts:
   from src.validation.ui_test import UniversalUITest
   
   ui_test = UniversalUITest()
   ui_report = ui_test.test_company(ticker, year)
   if not ui_report.passed:
       logger.warning(f"UI test issues: {ui_report.overall_score:.1%}")
   ```

**Benefits**:
- Universal: Works for any company (NVO, AAPL, etc.)
- Accurate: Uses company's XBRL structure
- No manual work: No need to pull up reports
- Dynamic: Updates automatically when new filings are loaded

---

## Single Responsibility Principle

Each module has one clear purpose:

| Module | Purpose | Stage |
|--------|---------|-------|
| `completeness.py` | Data completeness tracking | After parsing |
| `input_check.py` | Pre-load validation of facts dicts | After gap filling |
| `concept_checker.py` | Concept mapping validation | After loading |
| `consistency_check.py` | Cross-period/source consistency | After populate_statement_facts |
| `validator.py` | Accounting identities (coordinator) | After populate_statement_facts |
| `accounting_identities.py` | Balance sheet equation, etc. | After populate_statement_facts |
| `displayed_math.py` | Statement math validation | After populate_statement_facts |
| `data_quality.py` | Data quality metrics | After populate_statement_facts |
| `ui_test.py` | API output validation | After populate_statement_facts |

**No overlap**: Each checks a different aspect at a different stage.

---

## Complete Pipeline Flow

```
1. Parse XBRL → facts (dicts)
2. Completeness check (completeness.py)
3. Gap filling (SEC API)
4. input_check.py ← NEW: Validates facts dicts before loading
5. Load to fact_financial_metrics (StarSchemaLoader) ← FIX: Preserve all facts via synthetic dimensions
   - Primary fact: dimension_id=NULL
   - Additional facts: ContextAxis dimensions
   - All facts preserved and queryable
6. concept_checker.py ← NEW: Validates concept mappings
7. Post-load gap filling
8. populate_statement_facts
   - Uses primary facts (dimension_id=NULL) for standard queries
   - Can aggregate or use all context variants if needed
9. consistency_check.py ← NEW: Cross-period, ratios, XBRL vs SEC API
10. validator.py (modularized) - Accounting identities only
    - Prefers primary facts but can validate all variants
11. ui_test.py (universal, integrated) - API output validation
```

**Data Usability**:
- Primary facts: Standard queries use `dimension_id IS NULL` (primary consolidated)
- All variants: Queries can include `ContextAxis` to get all context variants
- Analysis: All XBRL data available (not just SEC API subset)
- Aggregation: Can aggregate across contexts or pick primary

---

## Implementation Order

1. **Phase 1** (CRITICAL): Fix loader fact selection logic
   - Prevents wrong data from being loaded
   - Reduces need for post-load fixes

2. **Phase 2** (HIGH): Create `input_check.py`
   - Catches issues before loading
   - Validates facts dicts

3. **Phase 3** (HIGH): Create `concept_checker.py`
   - Catches concept mapping errors
   - Validates normalization

4. **Phase 6** (HIGH): Universal UITest.py
   - Removes manual work
   - Makes testing universal

5. **Phase 4** (MEDIUM): Create `consistency_check.py`
   - Cross-period/source validation
   - Ratio reasonableness

6. **Phase 5** (MEDIUM): Modularize `validator.py`
   - Improves maintainability
   - Single responsibility principle

---

## Testing Strategy

### Unit Tests
- Each new module has unit tests
- Test with mock data
- Test edge cases (missing data, wrong values, etc.)

### Integration Tests
- Test full pipeline with real data (NVO, AAPL, etc.)
- Verify validation catches known issues
- Verify no false positives

### Regression Tests
- Run existing validation on historical data
- Ensure no regressions
- Compare validation scores before/after

---

## Success Criteria

1. **Loader fix**: 
   - All facts preserved (0% data loss, not 33.4%)
   - Primary equity values correct after loader runs (no need for `fix_equity_values()`)
   - Synthetic dimensions created and queryable
   - All XBRL data usable for analysis (not just SEC API subset)

2. **Data usability**:
   - All facts queryable via standard SQL
   - Primary facts used for standard analysis
   - Context variants available when needed
   - No data loss - all facts preserved and usable

3. **Validation coverage**: All validation gaps addressed
4. **Universal testing**: UITest works for any company without hardcoding
5. **Modularity**: Each module has single responsibility
6. **Integration**: All validators integrated into pipeline
7. **Data quality**: Validation catches issues at appropriate stages

---

## Notes

### Synthetic Dimension Handling

**All validators should**:
- Prefer primary facts (`dimension_id IS NULL`) for standard validation
- Include synthetic `ContextAxis` dimensions when querying "all consolidated facts"
- Treat synthetic dimensions as consolidated facts (not dimensional breakdowns)
- Can aggregate or pick primary when multiple context variants exist

**Query patterns**:
- Primary consolidated: `WHERE dimension_id IS NULL`
- All consolidated (including synthetic): `WHERE dimension_id IS NULL OR (dimension_id IS NOT NULL AND EXISTS (SELECT 1 FROM dim_xbrl_dimensions d WHERE d.dimension_id = f.dimension_id AND d.axis_name = 'ContextAxis'))`
- True dimensional: `WHERE dimension_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dim_xbrl_dimensions d WHERE d.dimension_id = f.dimension_id AND d.axis_name = 'ContextAxis')`

**Data Usability**:
- All XBRL facts are preserved and queryable (not just SEC API subset)
- Primary facts used for standard analysis
- Context variants available for advanced analysis or when primary is questionable
- No data loss - all facts usable for analysis

### What NOT to do:
- ❌ Add accounting identity checks at UI level
- ❌ Use arbitrary "healthy equity" ranges (use logic: 10-80% of assets)
- ❌ Spam terminal logs with verbosity
- ❌ Hardcode company-specific expected items
- ❌ Filter out synthetic dimensions without considering their value
- ❌ Assume all consolidated facts should have dimensions (many legitimately don't)

### What TO do:
- ✅ Check transaction signs (expenses negative, income positive)
- ✅ Check gross margin ranges (logic: 0-100%, not health-based)
- ✅ Validate concept mappings
- ✅ Check cross-period consistency
- ✅ Check XBRL vs SEC API consistency
- ✅ Use `rel_statement_items` for expected items (not hardcoding)
- ✅ Preserve and make usable all XBRL facts (not just SEC API subset)
- ✅ Prefer primary facts for standard validation, but keep all variants available

---

## Timeline Estimate

- **Phase 1** (Loader fix): 2-3 days
- **Phase 2** (input_check.py): 2-3 days
- **Phase 3** (concept_checker.py): 2-3 days
- **Phase 4** (consistency_check.py): 2-3 days
- **Phase 5** (Modularize validator.py): 3-4 days
- **Phase 6** (Universal UITest.py): 2-3 days

**Total**: ~15-20 days

---

## Dependencies

- `rel_statement_items` table must be populated (already done)
- Database schema must support validation queries (already done)
- Pipeline must support validation integration points (already done)

---

## Risk Mitigation

1. **Backward compatibility**: Keep existing validators until new ones are tested
2. **Gradual rollout**: Implement one phase at a time, test thoroughly
3. **Fallback mechanisms**: Keep `fix_equity_values()` as fallback until loader is fixed
4. **Monitoring**: Log validation results for analysis

---

## Performance Considerations

### Validation Performance
- Batch validation queries where possible (don't query per-fact)
- Cache results for repeated checks (e.g., concept mappings)
- Use database indexes (already exist for common queries)
- Consider async validation for non-blocking checks (optional)

### Synthetic Dimension Performance
- Synthetic dimensions add minimal overhead (one dimension per context variant)
- Queries with `ContextAxis` filter are efficient (indexed dimension_id)
- Primary fact queries (`dimension_id IS NULL`) remain fast
- No performance degradation from preserving all facts

### Load Performance
- Synthetic dimension creation is O(1) per fact (hash lookup)
- No significant performance impact from preserving all facts
- Load time increase: <5% (negligible)

## Conclusion

This upgrade plan addresses:
- Root cause (loader fact selection & data loss)
- Data preservation (all facts preserved via synthetic dimensions)
- Data usability (all facts queryable and usable for analysis)
- Validation gaps (pre-load, concept mapping, consistency)
- Maintainability (modularization)
- Usability (universal UITest)

**Key Improvement**: All XBRL data is preserved and usable, not just SEC API subset. This provides richer data for analysis while maintaining data quality through validation.

Implementation should proceed in phases, with Phase 1 (loader fix) as highest priority.

