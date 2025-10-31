# Conflict Resolution Strategy: Path to 100% No Conflicts

## Current State
- **58 normalization conflicts** (backend: multiple concepts → same label)
- **106 user-facing duplicates** (multiple values shown for same metric)

## Goal
- **0 normalization conflicts** where concepts are semantically different
- **Intentional merges only** for cross-taxonomy comparability (IFRS ↔ US-GAAP)

---

## Classification Framework

### ✅ KEEP MERGED (Intentional Cross-Taxonomy Equivalents)
These concepts represent the SAME financial item across different accounting standards.  
**Rationale**: Enable cross-company comparability

| Normalized Label | Concepts | Taxonomy | Action |
|------------------|----------|----------|--------|
| `revenue` | Revenue, Revenues, RevenueFromContractWithCustomerExcludingAssessedTax | US-GAAP variants | **KEEP MERGED** |
| `net_income` | NetIncomeLoss (US-GAAP), ProfitLoss (IFRS), ProfitLossAttributableToOwnersOfParent (IFRS) | US-GAAP ↔ IFRS | **KEEP MERGED** (but separate NetIncomeLossAvailableToCommonStockholdersBasic) |
| `stockholders_equity` | StockholdersEquity (US-GAAP), EquityAttributableToOwnersOfParent (IFRS) | US-GAAP ↔ IFRS | **KEEP MERGED** |
| `income_before_tax` | IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest, ProfitLossBeforeTax (IFRS) | US-GAAP ↔ IFRS | **KEEP MERGED** |
| `oci_total` | OtherComprehensiveIncome, OtherComprehensiveIncomeLossNetOfTax | US-GAAP variants | **KEEP MERGED** |

### 🔄 MUST SEPARATE (Semantically Different)
These look similar but represent DIFFERENT financial items.

| Current Label | Problem | Concepts | Resolution |
|---------------|---------|----------|------------|
| `noncurrent_assets` | AssetsNoncurrent ($212B) vs NoncurrentAssets ($45B different item!) | AssetsNoncurrent = TOTAL noncurrent assets<br>NoncurrentAssets = Specific line item in US-GAAP, OR total in IFRS | **SEPARATE**:<br>- `noncurrent_assets` (total) ← AssetsNoncurrent (US-GAAP), NoncurrentAssets (IFRS-only companies)<br>- `other_noncurrent_assets_ifrs` ← NoncurrentAssets (when used by US-GAAP companies) |
| `total_equity` | Equity (IFRS total) vs StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest (includes minorities) | Equity = Simple IFRS equity<br>StockholdersEquity...Noncontrolling = includes minorities | **ALREADY SEPARATED** (good) |
| `stock_based_compensation` | AllocatedShareBasedCompensationExpense vs ShareBasedCompensation | Allocated = expense allocated to products/segments<br>ShareBasedCompensation = total expense | **SEPARATE**:<br>- `stock_based_compensation` ← ShareBasedCompensation<br>- `allocated_stock_based_compensation` ← AllocatedShareBasedCompensationExpense |
| `selling_general_admin` | SellingGeneralAndAdministrativeExpense appears twice | Duplicate in mappings? | **FIX MAPPING** (check if actually different) |

### ⚠️ UNCLEAR - NEED INVESTIGATION
These require checking actual XBRL definitions.

| Label | Concepts | Question |
|-------|----------|----------|
| `derivative_financial_instruments` | DerivativeFinancialInstruments, DerivativeFinancialInstrumentsToManageFinancialExposure | Is second a subset? Or same with more specificity? |
| `goodwill` | Goodwill (appears twice) | Why is this showing as conflict? Check data |
| `noncurrent_assets` | NoncurrentAssets (used by both IFRS and US-GAAP companies) | Context-dependent meaning - need smarter handling |

---

## Resolution Rules

### Rule 1: Cross-Taxonomy Equivalents (MERGE)
**When to merge:**
- US-GAAP concept and IFRS concept represent the SAME financial item
- Different names due to taxonomy conventions, not semantic difference
- Necessary for cross-company analysis

**Examples:**
- ✅ `ProfitLoss` (IFRS) = `NetIncomeLoss` (US-GAAP) → **MERGE to `net_income`**
- ✅ `EquityAttributableToOwnersOfParent` (IFRS) = `StockholdersEquity` (US-GAAP) → **MERGE to `stockholders_equity`**

### Rule 2: Semantic Differences (SEPARATE)
**When to separate:**
- Concepts represent DIFFERENT things
- Different values in same filing for same period
- One is subset/detail of the other

**Examples:**
- ❌ `Depreciation` ($8.5B) ≠ `DepreciationDepletionAndAmortization` ($11.5B) → **SEPARATE**
- ❌ `IncomeTaxExpenseBenefit` (total) ≠ `IncomeTaxesPaid` (cash) → **SEPARATE**
- ❌ `AssetsNoncurrent` ($212B) ≠ `NoncurrentAssets` ($45B when used by US-GAAP company) → **SEPARATE**

### Rule 3: Context-Dependent Concepts (SMART HANDLING)
**When context matters:**
- Same concept name used differently by IFRS vs US-GAAP companies
- Need to check company's primary taxonomy

**Example:**
- `NoncurrentAssets`:
  - When used by IFRS company (NVO, SNY): Means TOTAL noncurrent assets → map to `noncurrent_assets`
  - When used by US-GAAP company (AAPL): Means a specific line item → map to `other_noncurrent_assets`

**Implementation:** Check company taxonomy or use calculation linkbase to determine if it's a total or subset.

---

## Action Plan to Reach 100%

### Phase 1: Fix Obviously Wrong Separations (MY MISTAKES) ✅ DO THIS NOW
1. **Re-merge cost concepts** (these ARE cross-taxonomy equivalents):
   ```
   cost_of_revenue ← CostOfRevenue, CostOfGoodsAndServicesSold, CostOfSales, CostOfGoodsSold
   ```
   - CostOfSales = IFRS
   - CostOfRevenue = US-GAAP (service companies)
   - CostOfGoodsAndServicesSold = US-GAAP (product companies)
   - **All mean the same thing!**

2. **Fix noncurrent_assets naming confusion**:
   - Currently: `noncurrent_assets_total` (confusing)
   - Should be: Check context - if it's the total, use `noncurrent_assets`, if it's a line item, use `other_noncurrent_assets`

3. **Re-merge dividends_paid**:
   ```
   dividends_paid ← PaymentsOfDividends, PaymentsOfDividendsCommonStock, DividendsPaid
   ```
   - These are the same (common stock dividends), just different naming

4. **Check interest_income**:
   ```
   interest_income ← InterestIncome, InvestmentIncomeInterest, FinanceIncome
   ```
   - FinanceIncome = IFRS
   - InterestIncome = US-GAAP
   - InvestmentIncomeInterest = US-GAAP (specific source)
   - **Consider merging FinanceIncome + InterestIncome, keep InvestmentIncomeInterest separate**

### Phase 2: Separate Net Income Variants
1. **Keep merged**: NetIncomeLoss, ProfitLoss, ProfitLossAttributableToOwnersOfParent (cross-taxonomy equivalents)
2. **Separate**: NetIncomeLossAvailableToCommonStockholdersBasic → `net_income_to_common_shareholders`
   - This is net income AFTER preferred dividends, different number!

### Phase 3: Handle Context-Dependent Concepts
This is the hard part - requires checking:
1. Company's primary taxonomy (US-GAAP vs IFRS)
2. Calculation linkbase (is it a parent or child in calc tree?)
3. Value magnitude (sanity check)

**Concepts needing smart handling:**
- NoncurrentAssets
- NoncontrollingInterest (can mean equity account OR income statement allocation)
- Various "Other" line items

### Phase 4: Document Intentional Merges
Create a whitelist of intentional cross-taxonomy merges:
```python
INTENTIONAL_CROSS_TAXONOMY_MERGES = {
    'revenue': ['Revenue', 'Revenues', 'RevenueFromContractWithCustomer...'],
    'net_income': ['NetIncomeLoss', 'ProfitLoss', 'ProfitLossAttributable...'],
    'stockholders_equity': ['StockholdersEquity', 'EquityAttributableToOwnersOfParent'],
    'cost_of_revenue': ['CostOfRevenue', 'CostOfSales', 'CostOfGoodsAndServicesSold'],
    # ... etc
}
```

Update validator to allow these conflicts (they're intentional).

---

## Expected Outcome

**After Phase 1 (fixes):**
- ~45 conflicts (down from 58)
- ~85 user-facing duplicates (down from 106)

**After Phases 1-2:**
- ~40 conflicts
- ~70 user-facing duplicates

**After Phases 1-4:**
- **15-20 intentional cross-taxonomy merges** (documented, whitelisted)
- **0 unintentional conflicts**
- **~20-30 user-facing "duplicates"** that are actually different concepts correctly separated

**Validation criteria for "done":**
- Every remaining conflict is documented as intentional
- Every user-facing duplicate represents genuinely different financial items
- Cross-company revenue/net income/equity comparisons work correctly

---

## Validation Queries

### Check if separation is correct:
```sql
-- If these show DIFFERENT values for same company/period, separation was correct
SELECT c.ticker, dc.concept_name, dt.fiscal_year, f.value_numeric
FROM fact_financial_metrics f
JOIN dim_concepts dc ON f.concept_id = dc.concept_id
JOIN dim_companies c ON f.company_id = c.company_id
JOIN dim_time_periods dt ON f.period_id = dt.period_id
WHERE dc.normalized_label = '<label_in_question>'
  AND f.dimension_id IS NULL
ORDER BY c.ticker, dt.fiscal_year, f.value_numeric;
```

### Check if merge is needed:
```sql
-- If NO company uses both concepts for same period, merge is safe
SELECT c.ticker, dt.fiscal_year, COUNT(DISTINCT dc.concept_id) as concept_count
FROM fact_financial_metrics f
JOIN dim_concepts dc ON f.concept_id = dc.concept_id
JOIN dim_companies c ON f.company_id = c.company_id
JOIN dim_time_periods dt ON f.period_id = dt.period_id
WHERE dc.normalized_label = '<label_in_question>'
  AND f.dimension_id IS NULL
GROUP BY c.ticker, dt.fiscal_year
HAVING COUNT(DISTINCT dc.concept_id) > 1;
```

---

## Next Steps

1. ✅ **IMMEDIATE**: Fix Phase 1 items (cost_of_revenue, interest_income, dividends_paid)
2. Separate NetIncomeLossAvailableToCommonStockholdersBasic
3. Investigate top 10 remaining conflicts by impact
4. Implement smart context handling for ambiguous concepts
5. Document all intentional merges
6. Update validator to whitelist intentional merges

