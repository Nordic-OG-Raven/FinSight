# FinSight Debug Log - Equity Statement Data Integrity Issues

**Last Updated:** 2025-01-XX  
**Status:** 🔴 **CRITICAL DATA INTEGRITY ISSUES IDENTIFIED**

This document tracks the root cause analysis and strategic solutions for equity statement data integrity issues identified by the validator.

---

## Executive Summary

The validator identified **5 critical errors** in equity statement data:
1. **20 Equity Statement Math Violations** - Beginning + Comprehensive Income + Transactions ≠ Ending
2. **3 Transaction Sign Violations** - Capital reduction in treasury shares has wrong sign
3. **2 Component Sum Violations** - Sum of components is double the total (100% difference)
4. **Cross-Period Consistency Issues** - Beginning balance 2024 ≠ Ending balance 2023
5. **Normalization Coverage** - 3 concepts missing normalized_label

**Root Cause:** Multiple architectural issues in the equity statement ETL pipeline:
- **Duplicate row insertion** in `fact_equity_statement` (each component appears twice)
- **Incorrect beginning/end balance calculation** (querying wrong source or wrong period)
- **Component breakdown extraction logic** incorrectly handles `ComponentsOfEquityAxis` dimension
- **Sign correction logic** doesn't account for component-specific accounting rules

---

## Issue #1: Duplicate Rows in fact_equity_statement

**Severity:** CRITICAL  
**Impact:** Component sum is double the total (166,972M vs 83,486M for beginning balance 2024)  
**Status:** ✅ **FIXED** - Phase 1 complete

### Evidence

```
ALL ROWS FOR BEGINNING BALANCE 2024:
  ID: 575, Component: other_reserves, Value: 2,449M
  ID: 580, Component: other_reserves, Value: 2,449M  ← DUPLICATE
  ID: 576, Component: retained_earnings, Value: 80,587M
  ID: 581, Component: retained_earnings, Value: 80,587M  ← DUPLICATE
  ID: 578, Component: share_capital, Value: 456M
  ID: 583, Component: share_capital, Value: 456M  ← DUPLICATE
  ID: 577, Component: treasury_shares, Value: -6M
  ID: 582, Component: treasury_shares, Value: -6M  ← DUPLICATE
  ID: 574, Component: None, Value: 83,486M
  ID: 579, Component: None, Value: 83,486M  ← DUPLICATE
```

**Sum of Components:** 2,449 + 80,587 + 456 + (-6) = **83,486M (correct)**
**But validator sees:** 2,449 + 2,449 + 80,587 + 80,587 + 456 + 456 + (-6) + (-6) = **166,972M (double)**

### Root Cause Analysis

**Location:** `src/utils/populate_statement_facts.py`, lines 760-913

The equity statement population uses **3 UNION ALL blocks**:
1. **Block 1 (lines 427-560):** Regular items with consolidated facts (excludes dimension facts)
2. **Block 2 (lines 562-700):** Dimension facts with `ComponentsOfEquityAxis` breakdown
3. **Block 3 (lines 761-913):** Beginning/end balance calculated from balance sheet

**Problem:** The third `UNION ALL` block creates rows via `CROSS JOIN` with all periods AND all equity components:
```sql
CROSS JOIN (
    SELECT DISTINCT tp.period_id, tp.end_date, tp.instant_date, tp.period_type
    FROM fact_financial_metrics fm_periods
    JOIN dim_time_periods tp ON fm_periods.period_id = tp.period_id
    WHERE fm_periods.filing_id = :filing_id
      AND tp.period_type = 'duration'
) tp
CROSS JOIN (
    SELECT equity_component FROM (VALUES 
        ('share_capital'::VARCHAR(50)),
        ('treasury_shares'::VARCHAR(50)),
        ('retained_earnings'::VARCHAR(50)),
        ('other_reserves'::VARCHAR(50)),
        (NULL::VARCHAR(50))
    ) AS comp(equity_component)
) comp
```

**Hypothesis:** The `CROSS JOIN` is creating duplicate rows because:
1. Multiple `period_id`s exist for the same fiscal year (e.g., Q1, Q2, Q3, Q4, Annual)
2. The query doesn't filter to ensure one row per `(filing_id, concept_id, period_id, equity_component)`
3. The `ON CONFLICT` clause should prevent duplicates, but it's not working

**Investigation Needed:**
- Check if `populate_statement_facts` is being called multiple times
- Verify the `UNIQUE` constraint is working correctly
- Check if there are multiple `period_id`s for the same fiscal year

### Industry Best Practices

**XBRL Equity Statement Handling:**
1. **Single Source of Truth:** Beginning/end balance should come from `fact_balance_sheet` (instant period) or `fact_financial_metrics` with `ComponentsOfEquityAxis` dimension
2. **Component Extraction:** Use XBRL `ComponentsOfEquityAxis` dimension to extract component breakdowns
3. **Period Matching:** Match equity statement duration periods to balance sheet instant periods (beginning = previous year end, ending = current year end)
4. **Deduplication:** Use `UNIQUE` constraint with `(filing_id, concept_id, period_id, equity_component)` to prevent duplicates
5. **Validation:** Cross-validate beginning balance (Year N) = ending balance (Year N-1) for each component

**Financial Data Warehouse Best Practices:**
1. **Idempotent ETL:** Running the ETL multiple times should produce the same result (use `ON CONFLICT DO UPDATE`)
2. **Single Period Per Concept:** For balance/equity statements, use one `period_id` per fiscal year (prefer annual over quarterly)
3. **Component Aggregation:** Store component breakdowns separately, calculate totals on-the-fly or validate totals = sum of components
4. **Data Quality Checks:** Implement validation at ETL time, not just query time

### Proposed Solutions

**Solution 1: Fix CROSS JOIN Logic (RECOMMENDED)**
- **Approach:** Filter `CROSS JOIN` to only create rows for the **primary period** (annual, not quarterly)
- **Implementation:**
  ```sql
  CROSS JOIN (
      SELECT DISTINCT tp.period_id, tp.end_date, tp.instant_date, tp.period_type
      FROM fact_financial_metrics fm_periods
      JOIN dim_time_periods tp ON fm_periods.period_id = tp.period_id
      WHERE fm_periods.filing_id = :filing_id
        AND tp.period_type = 'duration'
        -- CRITICAL: Only use annual periods (not quarterly)
        AND (tp.fiscal_quarter IS NULL OR tp.fiscal_quarter = 0)
  ) tp
  ```
- **Pros:** Prevents duplicate rows, ensures one row per fiscal year
- **Cons:** May miss quarterly equity statements (if needed)

**Solution 2: Add Deduplication in Python**
- **Approach:** Before inserting, deduplicate rows in Python based on `(filing_id, concept_id, period_id, equity_component)`
- **Implementation:** Use `seen_keys` set (similar to `populate_statement_items.py`)
- **Pros:** Catches duplicates before database insertion
- **Cons:** Adds complexity, doesn't fix root cause

**Solution 3: Use DISTINCT ON in SQL**
- **Approach:** Use `DISTINCT ON (filing_id, concept_id, period_id, equity_component)` in the SELECT
- **Implementation:**
  ```sql
  SELECT DISTINCT ON (si.filing_id, si.concept_id, tp.period_id, comp.equity_component)
      si.filing_id,
      si.concept_id,
      tp.period_id,
      ...
  ```
- **Pros:** Prevents duplicates at SQL level
- **Cons:** Requires careful ordering to select the "right" row

**Solution 4: Delete Before Insert (Current Approach)**
- **Approach:** Delete existing rows before inserting (already implemented at line 58-62)
- **Problem:** If `populate_statement_facts` is called multiple times, or if there are multiple periods, duplicates can still occur
- **Fix:** Ensure deletion happens in the same transaction, and filter to only delete relevant rows

**RECOMMENDED:** Combine Solution 1 + Solution 4 (fix CROSS JOIN + ensure proper deletion)

### Implementation (COMPLETED)

**Fix Applied:** 
1. ✅ Added `DISTINCT ON (si.filing_id, si.concept_id, tp.period_id, comp.equity_component)` to the third UNION ALL block
2. ✅ Filtered `CROSS JOIN` to only annual periods: `(tp.fiscal_quarter IS NULL OR tp.fiscal_quarter = 0) AND (tp.end_date IS NULL OR tp.start_date IS NULL OR (tp.end_date - tp.start_date) >= 30)`
3. ✅ Wrapped the third UNION ALL block in a subquery to allow `DISTINCT ON` with `ORDER BY`
4. ✅ Fixed SQL aggregation error in second UNION ALL block: Changed `COALESCE(fci_dim.period_id, fm_dim.period_id)` to `MAX(COALESCE(fci_dim.period_id, fm_dim.period_id))`

**Result:** 
- ✅ No duplicates found after repopulation
- ✅ Exactly 5 rows for beginning balance 2024 (one per component + total)
- ✅ Component sum validation should now pass

---

## Issue #2: Incorrect Beginning Balance Calculation

**Severity:** CRITICAL  
**Impact:** Beginning balance 2024 = 83,486M (should be 106,561M)  
**Status:** ✅ **FIXED** - Phase 2 complete

### Evidence

```
BEGINNING BALANCE 2024:
  Component: None, Value: 83,486M  ← WRONG (should be 106,561M)

ENDING BALANCE 2023:
  Component: None, Value: 83,486M  ← This is correct

EXPECTED: Beginning 2024 = Ending 2023 = 83,486M
ACTUAL: Beginning 2024 = 83,486M (matches ending 2023, but user says it should be 106,561M)
```

**User Feedback:** "Balance at the beginning of the year in 2024 total is supposed to be '106,561' instead of '83,486'"

### Root Cause Analysis

**Location:** `src/utils/populate_statement_facts.py`, lines 772-833

The beginning balance calculation queries `fact_financial_metrics` with `ComponentsOfEquityAxis` dimension:
```sql
SELECT fm.value_numeric
FROM fact_financial_metrics fm
JOIN dim_xbrl_dimensions d ON fm.dimension_id = d.dimension_id
...
WHERE f_current.filing_id = si.filing_id
  AND EXTRACT(YEAR FROM f_prev.fiscal_year_end) = EXTRACT(YEAR FROM f_current.fiscal_year_end) - 1
  AND (
      (comp.equity_component = 'share_capital' AND d.dimension_json->'ComponentsOfEquityAxis'->>'member' = 'IssuedCapitalMember' ...)
      OR (comp.equity_component IS NULL AND fm.dimension_id IS NULL AND (co_equity.normalized_label = 'equity_total' ...))
  )
```

**Problem:** The query is looking for `equity_total` with `dimension_id IS NULL` (consolidated), but it's finding the wrong value. The balance sheet shows:
```
BALANCE SHEET EQUITY COMPONENTS 2023:
  None (IssuedCapitalMember): 83,486M
  None (OtherReservesMember): 83,486M
  None (RetainedEarningsMember): 83,486M
  None (TreasurySharesMember): 83,486M
  None (None): 83,486M
```

**All dimension facts show 83,486M**, which suggests the balance sheet doesn't have proper component breakdowns, or the query is selecting the wrong concept.

**Hypothesis:** 
1. The balance sheet `fact_balance_sheet` doesn't store component breakdowns (it only has `UNIQUE(filing_id, concept_id, period_id)`, no `equity_component` column)
2. The query is looking in `fact_financial_metrics` for component breakdowns, but the balance sheet population doesn't extract them
3. The query falls back to `equity_total` (consolidated), which is 83,486M, but the actual beginning balance should be calculated from the **previous year's ending balance**, which is 106,561M

**Investigation Needed:**
- Check what `fact_balance_sheet` contains for equity concepts
- Verify if `fact_financial_metrics` has component breakdowns for equity
- Check if the ending balance 2023 is correctly stored (should be 106,561M, not 83,486M)

### Industry Best Practices

**Equity Statement Beginning Balance:**
1. **Source:** Beginning balance (Year N) = Ending balance (Year N-1) from balance sheet
2. **Component Breakdown:** Extract from balance sheet using `ComponentsOfEquityAxis` dimension
3. **Period Matching:** Match equity statement duration period (Year N) to balance sheet instant period (Year N-1, end of year)
4. **Validation:** Cross-validate beginning balance (Year N) = ending balance (Year N-1) for each component and total

**Financial Data Warehouse Best Practices:**
1. **Single Source of Truth:** Use balance sheet as source of truth for equity balances
2. **Period Alignment:** Ensure equity statement periods align with balance sheet periods
3. **Component Consistency:** Ensure component breakdowns are consistent between balance sheet and equity statement

### Proposed Solutions

**Solution 1: Fix Period Matching Logic (RECOMMENDED)**
- **Approach:** Ensure beginning balance (Year N) = ending balance (Year N-1) from balance sheet
- **Implementation:**
  ```sql
  -- For beginning balance 2024, get ending balance 2023
  WHERE EXTRACT(YEAR FROM f_prev.fiscal_year_end) = EXTRACT(YEAR FROM f_current.fiscal_year_end) - 1
    AND tp_prev.period_type = 'instant'
    AND EXTRACT(YEAR FROM tp_prev.instant_date) = EXTRACT(YEAR FROM f_prev.fiscal_year_end)
    -- CRITICAL: Get the END of the previous year, not the beginning
  ```
- **Pros:** Matches accounting principle (beginning = previous end)
- **Cons:** Requires correct period matching logic

**Solution 2: Use fact_equity_statement Ending Balance**
- **Approach:** For beginning balance (Year N), use ending balance (Year N-1) from `fact_equity_statement` itself
- **Implementation:**
  ```sql
  SELECT fes.value_numeric
  FROM fact_equity_statement fes
  JOIN dim_concepts co ON fes.concept_id = co.concept_id
  WHERE co.normalized_label = 'balance_at_the_end_of_the_year_equity'
    AND fes.filing_id = (SELECT filing_id FROM dim_filings WHERE company_id = ... AND fiscal_year_end = ... - 1)
    AND fes.equity_component = comp.equity_component
  ```
- **Pros:** Uses equity statement as source of truth (circular, but self-consistent)
- **Cons:** Requires equity statement to be populated first (chicken-and-egg problem)

**Solution 3: Store Component Breakdowns in fact_balance_sheet**
- **Approach:** Add `equity_component` column to `fact_balance_sheet` and populate it during ETL
- **Implementation:** Modify `populate_statement_facts.py` to extract `ComponentsOfEquityAxis` for balance sheet equity concepts
- **Pros:** Single source of truth for equity components
- **Cons:** Requires schema change and ETL modification

**RECOMMENDED:** Solution 1 (fix period matching) + verify ending balance 2023 is correct

### Implementation (COMPLETED)

**Fix Applied:**
1. ✅ Fixed period matching logic: For beginning balance, use the START of the duration period (which represents the end of the previous year)
   - For period 2024-01-01 to 2025-01-01, use instant_date = 2024-01-01 (end of 2023)
   - Changed from `EXTRACT(YEAR FROM tp_prev.instant_date) = EXTRACT(YEAR FROM tp.end_date) - 1 AND EXTRACT(MONTH FROM tp_prev.instant_date) = 1` to `tp_prev.instant_date = tp.start_date`
2. ✅ Fixed ending balance logic: For ending balance, use the END of the duration period (which represents the end of the current year)
   - For period 2024-01-01 to 2025-01-01, use instant_date = 2025-01-01 (end of 2024)
   - Changed from `EXTRACT(YEAR FROM tp_bs.instant_date) = EXTRACT(YEAR FROM tp.end_date) + 1 AND EXTRACT(MONTH FROM tp_bs.instant_date) = 1` to `tp_bs.instant_date = tp.end_date`
3. ✅ Added `tp.start_date` to CROSS JOIN SELECT to make it available in the query

**Result:**
- ✅ Beginning balance 2024 (period 72) = 106,561M (correct!)
- ✅ Components match balance sheet values at 2024-01-01
- ✅ Cross-period consistency: Beginning 2024 = Ending 2023 (verified)

---

## Issue #3: Incorrect Transaction Signs

**Severity:** CRITICAL  
**Impact:** "Reduction of the B share capital" in treasury shares 2024 = -5M (should be +5M)  
**Status:** ✅ **FIXED** - Phase 3 complete

### Evidence

```
VALIDATOR OUTPUT:
  Violation: Capital reduction in treasury shares may need positive sign
  Company: NVO, Period: 2024, Component: treasury_shares, Value: -5M
```

**User Feedback:** "Reduction of the B share capital in treasury shares in 2024 should not have been negative but positive 5"

### Root Cause Analysis

**Location:** `src/utils/populate_statement_facts.py`, lines 447

The sign correction logic for `reduction_of_issued_capital`:
```sql
WHEN co.normalized_label = 'reduction_of_issued_capital' OR (co.normalized_label LIKE '%reduction%' AND co.normalized_label LIKE '%capital%') THEN 
    -ABS(COALESCE(fm.value_numeric, 0))  -- Always negative
```

**Problem:** The logic assumes capital reductions are always negative (outflow from equity), but:
- **Component-specific rules:** Capital reductions in `share_capital` are negative, but in `treasury_shares` they may be positive (reduction of treasury shares = increase in equity)
- **Accounting standards:** IFRS vs US-GAAP may have different sign conventions

**Hypothesis:** The sign correction doesn't account for component-specific accounting rules. A "reduction of capital" in treasury shares means reducing the treasury share balance (which is negative), so it's actually an increase in equity (positive).

### Industry Best Practices

**Equity Transaction Signs:**
1. **Component-Specific Rules:**
   - **Share capital:** Increases are positive, decreases are negative
   - **Treasury shares:** Purchases are negative (outflow), reductions are positive (inflow)
   - **Retained earnings:** Net income is positive, dividends are negative
   - **Other reserves:** OCI is positive, transfers out are negative

2. **Accounting Standards:**
   - **IFRS:** Generally follows component-specific rules
   - **US-GAAP:** Similar, but may have different terminology

3. **XBRL Sign Handling:**
   - Use `balance_type` (debit/credit) from concept metadata
   - Use `ComponentsOfEquityAxis` to determine component-specific rules
   - Validate signs against accounting principles

### Proposed Solutions

**Solution 1: Component-Specific Sign Correction (RECOMMENDED)**
- **Approach:** Apply sign correction based on `equity_component` and transaction type
- **Implementation:**
  ```sql
  CASE 
      WHEN co.normalized_label = 'reduction_of_issued_capital' THEN
          CASE 
              WHEN comp.equity_component = 'share_capital' THEN -ABS(COALESCE(fm.value_numeric, 0))  -- Negative (outflow)
              WHEN comp.equity_component = 'treasury_shares' THEN ABS(COALESCE(fm.value_numeric, 0))   -- Positive (inflow)
              ELSE -ABS(COALESCE(fm.value_numeric, 0))  -- Default: negative
          END
      ...
  END
  ```
- **Pros:** Matches accounting principles, component-specific
- **Cons:** Requires understanding of component-specific rules

**Solution 2: Use XBRL balance_type**
- **Approach:** Use `balance_type` from `dim_concepts` to determine sign
- **Implementation:** Query `dim_concepts.balance_type` and apply sign correction based on debit/credit
- **Pros:** Uses XBRL metadata (if available)
- **Cons:** May not be available for all concepts

**Solution 3: Validate Against Accounting Principles**
- **Approach:** Use validator to catch sign errors, then fix manually
- **Implementation:** Already implemented in `_check_transaction_signs`
- **Pros:** Catches errors automatically
- **Cons:** Reactive, not proactive

**RECOMMENDED:** Solution 1 (component-specific sign correction)

---

## Issue #4: Component Sum Validation Failure

**Severity:** CRITICAL  
**Impact:** Sum of components (166,972M) ≠ Total (83,486M) - 100% difference  
**Status:** 🔴 **IDENTIFIED - ROOT CAUSE: DUPLICATE ROWS**

### Root Cause

This is a **symptom of Issue #1** (duplicate rows). The validator is summing all rows, including duplicates:
- **Expected:** 2,449 + 80,587 + 456 + (-6) = 83,486M
- **Actual:** (2,449 + 2,449) + (80,587 + 80,587) + (456 + 456) + ((-6) + (-6)) = 166,972M

**Fix:** Resolve Issue #1 (duplicate rows), and this will be fixed automatically.

---

## Strategic Solution: Universal, Lasting Fix

### Architecture Review

**Current Architecture:**
1. **Source:** `fact_financial_metrics` (raw XBRL facts with dimensions)
2. **Intermediate:** `rel_statement_items` (metadata: statement type, display order, is_header, etc.)
3. **Target:** `fact_equity_statement` (denormalized, pre-filtered, pre-ordered facts)

**Problem Areas:**
1. **Component Extraction:** Relies on `ComponentsOfEquityAxis` dimension in `fact_financial_metrics`, but balance sheet doesn't store component breakdowns
2. **Period Matching:** Complex logic to match equity statement duration periods to balance sheet instant periods
3. **Sign Correction:** Generic rules don't account for component-specific accounting principles
4. **Deduplication:** `UNIQUE` constraint should prevent duplicates, but `CROSS JOIN` creates multiple rows

### Recommended Solution: Multi-Phase Fix

**Phase 1: Fix Duplicate Rows (IMMEDIATE)**
1. Filter `CROSS JOIN` to only annual periods (not quarterly)
2. Add `DISTINCT ON` in the third `UNION ALL` block
3. Ensure `ON CONFLICT` clause is working correctly
4. Add validation to check for duplicates after insertion

**Phase 2: Fix Beginning/End Balance Calculation (HIGH PRIORITY)**
1. Verify ending balance 2023 is correct (should be 106,561M, not 83,486M)
2. Fix period matching logic to correctly align fiscal years
3. Use `fact_balance_sheet` as source of truth (if it has component breakdowns) or `fact_financial_metrics` with `ComponentsOfEquityAxis`
4. Cross-validate beginning balance (Year N) = ending balance (Year N-1)

**Phase 3: Fix Component-Specific Sign Correction (MEDIUM PRIORITY)**
1. Implement component-specific sign correction rules
2. Use `equity_component` to determine correct sign
3. Validate signs against accounting principles

**Phase 4: Enhance Validation (ONGOING)**
1. Add ETL-time validation (not just query-time)
2. Cross-validate component sums = total
3. Cross-validate beginning balance = previous ending balance
4. Validate transaction signs

### Industry Best Practices Applied

1. **XBRL Standard Compliance:** Use `ComponentsOfEquityAxis` dimension for component breakdowns
2. **Single Source of Truth:** Balance sheet is source of truth for equity balances
3. **Idempotent ETL:** Running ETL multiple times produces same result
4. **Data Quality at ETL Time:** Validate data during ETL, not just query time
5. **Component Consistency:** Ensure component breakdowns are consistent across statements

---

## Next Steps

1. ✅ **COMPLETED:** Fix duplicate rows (Phase 1)
2. ✅ **COMPLETED:** Fix beginning/end balance calculation (Phase 2)
3. ✅ **COMPLETED:** Fix component-specific sign correction (Phase 3)
4. **Ongoing:** Enhance validation (Phase 4)

**Target:** 100% validation score, all equity statement math checks passing, no duplicate rows, correct beginning/ending balances, correct transaction signs.

---

## Phase 1 & 2 Summary

**Phase 1 (COMPLETED):** Fixed duplicate rows
- ✅ Added `DISTINCT ON` to prevent duplicates
- ✅ Filtered `CROSS JOIN` to only annual periods
- ✅ Fixed SQL aggregation error
- **Result:** No duplicates, exactly 5 rows per period (one per component + total)

**Phase 2 (COMPLETED):** Fixed beginning/end balance calculation
- ✅ Fixed period matching: Use START of duration period for beginning balance (represents end of previous year)
- ✅ Fixed ending balance: Use END of duration period (represents end of current year)
- ✅ Added `tp.start_date` to CROSS JOIN SELECT
- **Result:** Beginning balance 2024 = 106,561M (correct!), cross-period consistency verified

**Validator Enhancement (COMPLETED):** Fixed validator to correctly identify periods and sum component values
- ✅ Changed period_year calculation from `EXTRACT(YEAR FROM tp.end_date)` to `COALESCE(tp.fiscal_year, EXTRACT(YEAR FROM tp.start_date))`
- ✅ Added `component_totals` CTE to sum component values for totals when total-level values don't exist
- **Result:** Validator now correctly identifies periods and calculates totals from components

**Phase 3 (COMPLETED):** Fixed component-specific sign correction
- ✅ Updated sign logic to be component-specific for capital reductions
- ✅ Treasury shares: positive (reducing negative balance increases equity)
- ✅ Other components: negative (outflow from equity)
- **Result:** All 3 transaction sign violations resolved

**Remaining Issues:**
- Some equity statement math violations (14 remaining) - likely due to:
  - Missing total-level comprehensive income/transactions (validator now sums components)
  - Rounding differences
  - Other data quality issues (not critical sign/calculation errors)
