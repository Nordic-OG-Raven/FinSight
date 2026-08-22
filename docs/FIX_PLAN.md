# Fix Plan for Remaining UI Test Issues

## Principles (from STATEMENT_ORGANIZATION_STRATEGY.md)
1. **Use XBRL Standards, Not Company-Specific Logic** - All fixes must work universally
2. **Use Role URI Patterns for Filtering** - Pattern matching works across all companies
3. **Fix Data Extraction/Loading, Not Add Workarounds** - Fix root cause, not symptoms
4. **Use balance_type for Signs** - Not manual fixes

## Issues Identified

### 1. Balance Sheet: Disclosure Items (order_index=1020) ✅ FIXED
- **Problem**: Items with order_index >= 1000 are disclosure items but showing in main statement
- **Fix**: Added filter `order_index < 1000` in SQL query and `is_main_statement_item()` function
- **Status**: ✅ Implemented

### 2. Balance Sheet: Missing "Total equity and liabilities"
- **Problem**: Balance sheet missing total for liabilities + equity side
- **Fix**: Check if concept exists in database, if not, add synthetic total calculation
- **Approach**: Use standard template or calculate from existing data

### 3. Income Statement: Missing "Earnings per share" header
- **Problem**: Basic and Diluted EPS are present but no header
- **Fix**: Add header item with is_header=True before EPS items

### 4. Income Statement: EPS ordering
- **Problem**: Basic EPS at pos 14 (expected 15), Diluted at pos 15 (expected 16)
- **Fix**: Adjust display_order computation for EPS items

### 5. Cash Flow: Missing "Cash and cash equivalents at the end of the year"
- **Problem**: Has "Cash at bank" but missing standard label
- **Fix**: Map "Cash at bank" to "Cash and cash equivalents at the end of the year" via taxonomy mapping

### 6. Comprehensive Income: Sign errors
- **Problem**: Many items have wrong signs (positive vs negative)
- **Fix**: Use balance_type from concept metadata, not manual fixes

### 7. Comprehensive Income: Missing Net profit for 2023
- **Problem**: Net profit missing for 2023 year
- **Fix**: Ensure Net profit is linked from income statement for all years

### 8. Equity Statement: Missing beginning/ending balances
- **Problem**: Missing "Balance at the beginning of the year" and "Balance at the end of the year"
- **Fix**: Add synthetic items or ensure they're extracted from XBRL

### 9. Missing Years: Many items missing 2022 data
- **Problem**: Items present for 2023-2024 but missing 2022
- **Fix**: Post-load gap filling should catch this, but may need to ensure it runs for all years

## Implementation Order

1. ✅ Filter disclosure items (order_index >= 1000)
2. Fix missing items (Total equity and liabilities, EPS header, Cash equivalents, Equity balances)
3. Fix sign errors (use balance_type)
4. Fix ordering issues (EPS, comprehensive income)
5. Fix missing years (ensure gap filling covers all years)

