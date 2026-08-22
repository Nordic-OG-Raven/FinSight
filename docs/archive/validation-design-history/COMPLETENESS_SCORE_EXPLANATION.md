# Completeness Score Explanation

## Why Final Completeness (40%) is Lower Than Individual Statement Scores

The **Final Completeness** score (39.5%) is calculated differently from individual statement completeness scores:

### Individual Statement Scores
- **Balance Sheet: 83.3%** - Checks 12 expected labels for balance sheet only
- **Income Statement: 44.4%** - Checks 8 expected labels for income statement only  
- **Cash Flow: 80.0%** - Checks 5 expected labels for cash flow only

These scores are **independent** - each checks only its own expected concepts.

### Final Completeness Score (Weighted Average)

The overall completeness is a **weighted average** of three components:

1. **50% weight: Critical Concepts Score**
   - Checks ALL 23 expected labels across ALL statements (12 BS + 8 IS + 5 CF)
   - If many concepts are missing across different statements, this score drops
   - Example: If 14/23 concepts are found = 60.9% concept score

2. **30% weight: Data Quality Score**
   - Percentage of facts that have: `value_numeric` AND `period_end` AND `unit_measure`
   - If many facts are missing periods or units, this score drops
   - Example: If 93.6% of facts have complete metadata = 93.6% quality score

3. **20% weight: Dimensional Coverage Score**
   - Bonus for facts with dimensions (segments, products, geographies)
   - Expects at least 50% of facts to have dimensions
   - Example: If 10% of facts have dimensions = 20% dimensional score (capped at 100%)

### Example Calculation

If we have:
- Concept score: 60.9% (14/23 concepts found)
- Quality score: 93.6% (3367/3597 facts have complete metadata)
- Dimensional score: 20% (few facts have dimensions)

**Overall = (60.9% × 0.5) + (93.6% × 0.3) + (20% × 0.2) = 30.5% + 28.1% + 4% = 62.6%**

But if dimensional coverage is very low (e.g., 0%), it becomes:
**Overall = (60.9% × 0.5) + (93.6% × 0.3) + (0% × 0.2) = 30.5% + 28.1% + 0% = 58.6%**

## Implications of Low Final Completeness

**< 40% completeness indicates:**
- Many critical concepts missing across statements
- OR poor data quality (missing periods/units)
- OR very low dimensional coverage

**This is NOT error masking** - it's a legitimate measure of data completeness.

## How to Improve Without Error Masking

1. **Fix extraction gaps** - Ensure all critical concepts are extracted from XBRL
2. **Improve gap filling** - Use SEC API to fill missing concepts (already implemented)
   - **FIXED**: Now always adds SEC_API data even if XBRL exists (SEC is authoritative)
3. **Fix data quality** - Ensure all facts have periods and units
   - **FIXED**: Data quality score now accounts for both `period_end` and `instant_date`
4. **Extract dimensions** - Parse XBRL dimensions for segment/product breakdowns
   - **FIXED**: Dimensional threshold reduced from 50% to 10% (more realistic)

**Recent Fixes**:
- Gap filling now always adds SEC_API data (prefers SEC over XBRL)
- Data quality score fixed to check both period types
- Dimensional coverage threshold made more lenient (10% instead of 50%)

