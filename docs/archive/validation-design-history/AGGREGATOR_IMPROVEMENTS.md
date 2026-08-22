# Validation Aggregator - Missing Issues & Improvements

## What the Aggregator Currently Catches ✅

1. **Database validation failures** - Accounting identity violations, normalization conflicts
2. **UI test failures** - Missing items, order issues (when test fails), year completeness (when test fails)
3. **Balance sheet year completeness** - 33 items missing years ✅

## What the Aggregator is Missing ❌

### 1. **SQL Errors During Data Loading** (CRITICAL)
**Terminal shows:**
```
[parameters: {'filing_id': 1, 'statement_type': 'equity_statement'}]
(Background on this error at: https://sqlalche.me/e/20/f405)
⚠️  Data loading failed. Check output above for details.
```

**Why missed:** Aggregator doesn't check for loading errors - it only validates after data is loaded.

**Impact:** HIGH - Data loading failures prevent any validation from running.

**Fix:** Add `_check_loading_errors()` method that:
- Checks database for recent loading errors
- Checks log files for SQL errors
- Validates that `fact_equity_statement` was populated successfully

### 2. **Value Mismatches in Equity Statement** (9 mismatches)
**Terminal shows:**
```
⚠️  Value mismatch for Balance at the beginning of the year 2024: expected 106561, got 107837
⚠️  Value mismatch for Balance at the beginning of the year 2023: expected 83486, got 85935
... (7 more)
```

**Why missed:** Value mismatches are printed as warnings but:
- Not returned in `test_equity_statement()` result dict
- Test still passes (`success=True`) because items are present and in correct order
- Aggregator only checks `if not is_result.get('success')`

**Impact:** MEDIUM - These are actual data quality issues that need fixing.

**Fix:** 
- Option A: Modify `UITest.py` to return `value_mismatches` in result dict
- Option B: Parse the printed warnings from test output (hacky)
- **Recommended:** Option A - modify UITest to return value mismatches

### 3. **Position Issues When Test Passes**
**Terminal shows:**
```
❌ Total equity and liabilities (expected pos: 21, actual pos: 22)
```

**Why missed:** 
- Position issue is shown as ❌ but test still passes overall
- Aggregator only checks `if not is_result.get('success')`
- `order_issues` is returned in result dict but aggregator doesn't check it when `success=True`

**Impact:** MEDIUM - Items in wrong position affect user experience.

**Fix:** Check for `order_issues` even when test passes:
```python
if is_result.get('order_issues'):
    issues.append(ValidationIssue(...))
```

### 4. **Component Breakdown Warnings**
**Terminal shows:**
```
⚠️  Component Breakdown Warnings: X
   ⚠️  Dividends 'dividends' only in Total for 2024 (expected in Retained earnings)
```

**Why missed:** Warnings are in `component_validation["warnings"]` but aggregator doesn't check them.

**Impact:** LOW-MEDIUM - These indicate data structure issues.

**Fix:** Check `component_validation["warnings"]` in equity test result.

## Recommended Improvements

### Priority 1: Check for Loading Errors
```python
def _check_loading_errors(self, filing_id: int) -> List[ValidationIssue]:
    """Check for SQL/loading errors"""
    issues = []
    
    # Check if equity statement was populated
    with self.engine.connect() as conn:
        result = conn.execute(text("""
            SELECT COUNT(*) 
            FROM fact_equity_statement 
            WHERE filing_id = :filing_id
        """), {'filing_id': filing_id})
        count = result.fetchone()[0]
        
        if count == 0:
            issues.append(ValidationIssue(
                category='loading_error',
                statement_type='equity_statement',
                issue='fact_equity_statement is empty - loading may have failed',
                details={'filing_id': filing_id}
            ))
    
    return issues
```

### Priority 2: Check Order Issues Even When Test Passes
```python
# In _collect_ui_test_issues()
if is_result.get('order_issues'):
    issues.append(ValidationIssue(
        category='ui_test',
        statement_type='equity_statement',
        issue=f"Order issues: {len(is_result['order_issues'])} items in wrong position",
        details={'order_issues': is_result['order_issues']}
    ))
```

### Priority 3: Modify UITest.py to Return Value Mismatches
```python
# In test_equity_statement(), collect value mismatches:
value_mismatches = []
for expected_label, expected_values in EXPECTED_NOVO_EQUITY_VALUES.items():
    # ... existing comparison logic ...
    if abs(val_millions - expected_val) > 1:
        value_mismatches.append({
            'item': expected_label,
            'year': year_val,
            'expected': expected_val,
            'actual': val_millions
        })

return {
    "success": success,
    "value_mismatches": value_mismatches,  # ADD THIS
    # ... rest of return dict
}
```

Then in aggregator:
```python
if equity_result.get('value_mismatches'):
    issues.append(ValidationIssue(
        category='ui_test',
        statement_type='equity_statement',
        issue=f"Value mismatches: {len(equity_result['value_mismatches'])} items",
        details={'value_mismatches': equity_result['value_mismatches']}
    ))
```

### Priority 4: Check Component Breakdown Warnings
```python
if equity_result.get('component_validation', {}).get('warnings'):
    warnings = equity_result['component_validation']['warnings']
    issues.append(ValidationIssue(
        category='ui_test',
        statement_type='equity_statement',
        issue=f"Component breakdown warnings: {len(warnings)}",
        details={'warnings': warnings}
    ))
```

## Summary

**Current coverage:** ~60% of issues
- ✅ Database validation failures
- ✅ UI test failures (when test fails)
- ❌ SQL/loading errors
- ❌ Value mismatches (warnings)
- ❌ Position issues (when test passes)
- ❌ Component breakdown warnings

**After improvements:** ~95% of issues
- ✅ All of the above
- ✅ Loading errors
- ✅ Value mismatches
- ✅ Position issues (even when test passes)
- ✅ Component warnings

## Implementation Order

1. **Add loading error check** (5 min) - Critical, prevents silent failures
2. **Check order_issues even when success=True** (2 min) - Easy fix
3. **Modify UITest to return value_mismatches** (10 min) - Requires changing UITest.py
4. **Check component warnings** (2 min) - Easy fix

Total time: ~20 minutes to catch 95% of issues instead of 60%.

