# Validation Aggregator - Quick Reference Guide

## What It Does

The validation aggregator solves the **"fix one thing, break another"** problem by:
1. Collecting ALL actual issues from existing validators (UITest.py, DatabaseValidator, etc.)
2. Listing what's broken - no arbitrary scores
3. Comparing before/after to detect NEW issues (regressions)

## Quick Start

### Command Line Usage

```bash
# Collect all issues for a filing
python src/validation/aggregator.py --ticker NVO --year 2024

# Save results to file
python src/validation/aggregator.py --ticker NVO --year 2024 > issues_before.txt
```

### Python Usage

```python
from src.validation.aggregator import ValidationAggregator

aggregator = ValidationAggregator()

# Collect all issues
result = aggregator.collect_all_issues(ticker='NVO', year=2024)

# Print issues
for issue in result['issues']:
    print(f"{issue['category']} [{issue.get('statement', 'N/A')}]: {issue['issue']}")

# Compare before/after
before = aggregator.collect_all_issues(ticker='NVO', year=2024)
# ... apply fix ...
after = aggregator.collect_all_issues(ticker='NVO', year=2024)
comparison = aggregator.compare_issues(before, after)

if comparison['new_issues']:
    print(f"⚠️ {len(comparison['new_issues'])} NEW issues detected!")
    for issue in comparison['new_issues']:
        print(f"   - {issue['category']}: {issue['issue']}")
```

## Issue Categories

Issues are collected from:

1. **DatabaseValidator** (`src/validation/validator.py`)
   - Accounting identity violations
   - Normalization conflicts
   - Data completeness issues
   - Calculation relationship errors

2. **UITest.py**
   - Missing items in statements
   - Order issues
   - Year completeness (missing data for some years)
   - Value mismatches

3. **CompletenessTracker** (`src/validation/completeness.py`)
   - Missing concepts
   - Missing periods

## Example Output

```
================================================================================
VALIDATION ISSUES: NVO 2024
================================================================================
Total Issues: 3

database_validation [balance_sheet]:
  Balance sheet equation: Assets (1000) ≠ Liabilities + Equity (995)

ui_test [balance_sheet]:
  33 items missing years [2022, 2023]

ui_test [equity_statement]:
  Balance at beginning 2024: expected 106561, got 107837
================================================================================
```

## Before/After Comparison

```
================================================================================
VALIDATION COMPARISON
================================================================================
Before: 3 issues
After: 2 issues

✅ Fixed Issues (1):
   - ui_test [equity_statement]: Balance at beginning 2024 mismatch

❌ New Issues (0):

➡️  Unchanged Issues (2):
   - database_validation [balance_sheet]: Balance sheet equation
   - ui_test [balance_sheet]: Missing years

✅ No regressions detected!
================================================================================
```

## Integration with Pipeline

Add to `run_pipeline.sh`:

```bash
# Before loading
echo "Collecting issues (before)..."
python src/validation/aggregator.py --ticker "$TICKER" --year "$YEAR" > issues_before.txt

# ... load data ...

# After loading
echo "Collecting issues (after)..."
python src/validation/aggregator.py --ticker "$TICKER" --year "$YEAR" > issues_after.txt

# Compare (optional)
python -c "
from src.validation.aggregator import ValidationAggregator
import json

aggregator = ValidationAggregator()
before = json.load(open('issues_before.txt'))
after = json.load(open('issues_after.txt'))
comparison = aggregator.compare_issues(before, after)

if comparison['new_issues']:
    print(f'⚠️ {len(comparison[\"new_issues\"])} NEW issues detected!')
    for issue in comparison['new_issues']:
        print(f'   - {issue[\"category\"]}: {issue[\"issue\"]}')
else:
    print('✅ No new issues detected!')
"
```

## Tips

1. **Always run before/after** - This is the whole point!
2. **Don't commit if new issues appear** - Investigate regressions first
3. **Focus on NEW issues** - Unchanged issues are known problems
4. **Save results** - Keep issue history to track progress

## Troubleshooting

**"Filing not found" error:**
- Make sure data is loaded first
- Check ticker/year are correct
- Verify filing exists in database

**Too many issues:**
- Focus on NEW issues first (regressions)
- Fix accounting identity violations (critical)
- Then fix UI test failures (user-facing)

**No issues but data looks wrong:**
- Check if validators are running correctly
- Verify API is returning data
- Check database directly
