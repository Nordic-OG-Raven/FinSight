# FinSight Validation Pipeline Evaluation

## Executive Summary

After 224+ hours of debugging, this evaluation assesses the current validation framework and proposes improvements to prevent future data quality issues.

## Current Validation Framework

### 1. **completeness.py** - Data Completeness Tracking
**Purpose**: Tracks coverage of critical financial concepts by statement type

**Strengths**:
- Uses normalized labels (taxonomy-agnostic, works for IFRS and US-GAAP)
- Calculates completeness scores per statement type
- Integrates SEC API gap filling
- Tracks dimensional coverage

**Weaknesses**:
- Only checks for presence, not correctness of values
- No validation of accounting identities
- No cross-statement consistency checks
- Completeness scores don't account for data quality issues

**Recommendation**: Keep as-is, but add data quality checks (not just presence)

### 2. **validator.py** - Database-Level Validation
**Purpose**: Validates data quality after loading into database

**Current Checks** (33 validation rules):
1. **Normalization Conflicts** - Checks for duplicate normalized labels
2. **User-Facing Duplicates** - Checks for duplicate display items
3. **Company Data** - Validates company metadata
4. **Data Completeness** - Checks for missing critical concepts
5. **Missing Data Matrix** - Company × metric × year coverage
6. **Universal Metrics** - Checks for critical normalized labels
7. **Accounting Identities**:
   - Balance sheet equation (Assets = Liabilities + Equity)
   - Retained earnings rollforward
   - Cash flow reconciliation
8. **Calculation Relationships**:
   - Gross profit margin
   - Operating income calculation
9. **Displayed Statement Math** (CRITICAL - validates what users see):
   - Income statement math
   - Comprehensive income math
   - Balance sheet displayed math
   - Cash flow displayed math
   - Equity statement math
10. **Data Quality**:
    - Normalization coverage
    - Numeric value ranges
    - Unit consistency

**Strengths**:
- Comprehensive coverage of accounting identities
- Validates both source (`fact_financial_metrics`) and display tables (`fact_income_statement`, etc.)
- Uses industry-standard tolerances (1% for rounding)
- BIG 4/Hedge Fund approach (prefer explicit over calculated, avoid double-counting)

**Weaknesses**:
- **CRITICAL GAP**: No validation of concept mappings (wrong concept → wrong normalized_label)
- **CRITICAL GAP**: No validation of unit scaling issues at source
- **CRITICAL GAP**: No validation of sign errors at source
- No validation of cross-period consistency (e.g., equity should be continuous)
- No validation of ratio reasonableness (e.g., gross margin 0-100%, equity 10-80% of assets)
- No validation of SEC API vs XBRL consistency
- Validator is large (3852 lines) - could benefit from modularization

**Recommendation**: Add source-level validation checks (see below)

### 3. **UITest.py** - End-to-End API Testing
**Purpose**: Validates the final API output (what users actually see)

**Strengths**:
- Tests actual user-facing output
- Checks item presence, order, and values
- Validates year completeness
- Catches transformation bugs

**Weaknesses**:
- Hardcoded for specific companies (NVO)
- Not integrated into pipeline (manual testing)
- Doesn't validate accounting identities
- Doesn't catch concept mapping errors

**Recommendation**: Generalize and integrate into pipeline

## Critical Gaps Identified

### 1. **Source Data Quality Validation** (MISSING)
**Problem**: Current validation checks `fact_financial_metrics` for accounting identities, but doesn't validate:
- Concept mappings (wrong concept → wrong normalized_label)
- Unit scaling issues (equity in millions when assets in base currency)
- Sign errors (XBRL/SEC_API reporting conventions)
- Value reasonableness (gross profit > revenue is impossible)

**Impact**: 
- Equity values were 930M/38M instead of 70.7B/83.5B (unit scaling)
- Gross profit was 245B when revenue was 167B (impossible - wrong concept)
- Operating income was 620M when it should be ~234B (wrong concept or value)
- Comprehensive income was 1.782B when it should be 102.331B (wrong concept)

**Solution**: Add source-level validation checks:
- **Unit Scaling Validation**: Check equity is 10-80% of assets (healthy companies)
- **Sign Validation**: Check transaction signs (e.g., expenses negative, income positive)
- **Ratio Reasonableness**: Gross margin 0-100%, operating margin reasonable, etc.
- **Concept Mapping Validation**: Cross-check concept names vs normalized labels for known issues

### 2. **Cross-Period Consistency** (MISSING)
**Problem**: No validation that values make sense across periods (e.g., equity should be continuous, retained earnings should roll forward)

**Solution**: Add cross-period consistency checks

### 3. **SEC API vs XBRL Consistency** (MISSING)
**Problem**: No validation that SEC API and XBRL values are consistent (within tolerance)

**Solution**: Add consistency checks when both sources exist

## Recommended Improvements

### Phase 1: Source-Level Validation (HIGH PRIORITY)
Create `src/validation/source_validator.py`:

```python
class SourceDataValidator:
    """Validates fact_financial_metrics before transformation"""
    
    def validate_unit_scaling(self):
        """Check equity is 10-80% of assets (catches unit scaling issues)"""
        
    def validate_concept_mappings(self):
        """Check for known concept mapping issues"""
        
    def validate_value_reasonableness(self):
        """Check ratios are within reasonable bounds"""
        
    def validate_signs(self):
        """Check transaction signs are correct"""
```

**Integration**: Run after data loading, before `populate_statement_facts()`

### Phase 2: Enhanced Database Validation (MEDIUM PRIORITY)
Add to `validator.py`:
- Cross-period consistency checks
- SEC API vs XBRL consistency
- Ratio reasonableness (gross margin, operating margin, etc.)

### Phase 3: Generalize UITest (LOW PRIORITY)
- Make UITest company-agnostic
- Integrate into pipeline
- Add accounting identity checks

## Validation Architecture Recommendation

### Current Flow:
```
XBRL/SEC_API → fact_financial_metrics → populate_statement_facts() → fact_income_statement, etc.
                                                      ↓
                                            validator.py (checks both)
```

### Recommended Flow:
```
XBRL/SEC_API → fact_financial_metrics → source_validator.py (NEW)
                                                      ↓
                                            populate_statement_facts()
                                                      ↓
                                            fact_income_statement, etc.
                                                      ↓
                                            validator.py (existing)
                                                      ↓
                                            UITest.py (generalized)
```

## Industry Standards Comparison

### Big 4 Accounting Firms:
- ✅ **Accounting Identities**: We have this
- ✅ **Calculation Relationships**: We have this
- ❌ **Source Data Quality**: We're missing this
- ❌ **Cross-Period Consistency**: We're missing this

### Hedge Funds / Financial Data Providers:
- ✅ **Displayed Statement Math**: We have this
- ✅ **Data Completeness**: We have this
- ❌ **Unit Scaling Validation**: We're missing this
- ❌ **Concept Mapping Validation**: We're missing this

## Conclusion

**Current State**: Good coverage of accounting identities and displayed statement math, but missing critical source-level validation.

**Priority**: Add source-level validation (unit scaling, concept mappings, value reasonableness) to catch issues before transformation.

**Impact**: Would have caught equity unit scaling issue (930M vs 70.7B) and gross profit concept mapping issue (245B vs 167B revenue) immediately.

