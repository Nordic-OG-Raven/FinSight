# Taxonomy Normalization Documentation

## Overview

The FinSight pipeline extracts financial data from SEC filings using different accounting standards (US-GAAP, IFRS). Each standard uses different concept names for the same financial metrics. Taxonomy normalization solves this problem by mapping all concepts to standardized labels.

## Problem Statement

**Without normalization:**
```sql
-- US-GAAP companies
SELECT value_numeric FROM financial_facts 
WHERE concept = 'RevenueFromContractWithCustomerExcludingAssessedTax'

-- IFRS companies
SELECT value_numeric FROM financial_facts 
WHERE concept = 'Revenue'
```

These are **the same metric** but with different names, making cross-company analysis impossible.

**With normalization:**
```sql
-- Works for ALL companies
SELECT company, value_numeric FROM financial_facts
WHERE normalized_label = 'revenue'
```

## Architecture

### 1. Concept Mappings (`src/utils/taxonomy_mappings.py`)

The core mapping dictionary maps normalized labels to lists of possible concept names:

```python
CONCEPT_MAPPINGS = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",  # US-GAAP
        "RevenueFromContractWithCustomerIncludingAssessedTax",  # US-GAAP
        "Revenues",                                              # US-GAAP (older)
        "Revenue",                                               # IFRS
        "SalesRevenueNet",                                       # IFRS variations
    ],
    "net_income": [
        "NetIncomeLoss",                                         # US-GAAP
        "NetIncomeLossAvailableToCommonStockholdersBasic",       # US-GAAP
        "ProfitLossAttributableToOwnersOfParent",                # IFRS
        "ProfitLoss",                                            # IFRS
    ],
    # ... 80+ more mappings
}
```

### 2. Database Schema

The `financial_facts` table includes:
- `concept`: Original XBRL concept name
- `normalized_label`: Standardized label for cross-company queries
- Index on `normalized_label` for fast lookups

### 3. Application Script (`apply_normalization.sh`)

Batch process that:
1. Reads all unique concepts from database
2. Maps each to normalized label using `taxonomy_mappings.py`
3. Updates `normalized_label` column
4. Reports coverage statistics

## Coverage Statistics

**Current Coverage:**
- **Total facts:** 28,471
- **Mapped facts:** 5,363 (18.84%)
- **Unmapped facts:** 23,108 (81.16%)

**Why is coverage only 18.84%?**

The low coverage is **expected and correct** because:

1. **Core financial metrics are covered:** The 97 mapped concepts include all critical KPIs (revenue, expenses, assets, liabilities, equity, cash flow). These represent the most **important** 18.84% of facts.

2. **Most facts are granular details:** The unmapped 81.16% consists of:
   - Footnote disclosures
   - Segment breakdowns (already have dimensions)
   - Policy text blocks
   - Detailed sub-line items
   - Entity information
   - Industry-specific metrics
   - Uncommonly used concepts

3. **Granular facts are intentionally not normalized:** These are useful for deep analysis but don't need cross-company standardization.

## Top Normalized Labels

| Label | Fact Count | Description |
|-------|-----------|-------------|
| `revenue` | 1,991 | Total revenues |
| `stockholders_equity` | 478 | Total equity |
| `net_income` | 254 | Net income/profit |
| `operating_income` | 195 | Operating profit |
| `goodwill` | 142 | Goodwill asset |
| `long_term_debt` | 139 | Long-term borrowings |
| `cost_of_revenue` | 133 | Cost of goods/services sold |
| `cash_and_equivalents` | 126 | Cash and cash equivalents |
| `short_term_investments` | 124 | Marketable securities |
| `depreciation_amortization` | 107 | D&A expense |

## Example Queries

### 1. Revenue Comparison Across Companies

```sql
-- Get consolidated revenue for each company (no segment breakdowns)
WITH ranked_revenue AS (
    SELECT 
        company, 
        fiscal_year_end,
        value_numeric,
        ROW_NUMBER() OVER (
            PARTITION BY company, fiscal_year_end 
            ORDER BY value_numeric DESC
        ) as rn
    FROM financial_facts
    WHERE normalized_label = 'revenue' 
      AND period_type = 'duration'
      AND value_numeric IS NOT NULL
      AND dimensions IS NULL  -- Consolidated only
)
SELECT 
    company, 
    fiscal_year_end,
    value_numeric / 1e9 as revenue_billions
FROM ranked_revenue
WHERE rn = 1
ORDER BY revenue_billions DESC;
```

### 2. Multi-Metric Dashboard Query

```sql
-- Compare key metrics across companies
SELECT 
    company,
    fiscal_year_end,
    MAX(CASE WHEN normalized_label = 'revenue' THEN value_numeric END) / 1e9 as revenue_B,
    MAX(CASE WHEN normalized_label = 'net_income' THEN value_numeric END) / 1e9 as net_income_B,
    MAX(CASE WHEN normalized_label = 'total_assets' THEN value_numeric END) / 1e9 as assets_B,
    MAX(CASE WHEN normalized_label = 'stockholders_equity' THEN value_numeric END) / 1e9 as equity_B
FROM financial_facts
WHERE normalized_label IN ('revenue', 'net_income', 'total_assets', 'stockholders_equity')
  AND value_numeric IS NOT NULL
  AND dimensions IS NULL
GROUP BY company, fiscal_year_end
ORDER BY revenue_B DESC;
```

### 3. Time-Series Analysis

```sql
-- Revenue growth over time
SELECT 
    company,
    fiscal_year_end,
    value_numeric / 1e9 as revenue_B,
    LAG(value_numeric) OVER (PARTITION BY company ORDER BY fiscal_year_end) as prev_revenue,
    ROUND(100.0 * (value_numeric - LAG(value_numeric) OVER (PARTITION BY company ORDER BY fiscal_year_end)) 
          / LAG(value_numeric) OVER (PARTITION BY company ORDER BY fiscal_year_end), 2) as yoy_growth_pct
FROM financial_facts
WHERE normalized_label = 'revenue'
  AND period_type = 'duration'
  AND dimensions IS NULL
ORDER BY company, fiscal_year_end;
```

## Statement Classification

Each normalized label is assigned to a statement type:

- **Income Statement:** `revenue`, `cost_of_revenue`, `net_income`, `eps_basic`, etc.
- **Balance Sheet:** `total_assets`, `total_liabilities`, `stockholders_equity`, etc.
- **Cash Flow:** `operating_cash_flow`, `investing_cash_flow`, `capex`, etc.
- **Other:** `depreciation_amortization`, `stock_based_compensation`, etc.

Query by statement type:
```python
from src.utils.taxonomy_mappings import get_statement_type

statement = get_statement_type('revenue')  # Returns 'income_statement'
```

## Adding New Mappings

To add support for new concepts:

1. **Identify the concept:** Check unmapped concepts in database
2. **Add to mapping:** Edit `CONCEPT_MAPPINGS` in `taxonomy_mappings.py`
3. **Re-run normalization:** Execute `./apply_normalization.sh`
4. **Verify:** Query database to confirm mapping

Example:
```python
# In taxonomy_mappings.py
CONCEPT_MAPPINGS = {
    # ... existing mappings ...
    
    "new_metric": [
        "USGAAPConceptName",
        "IFRSConceptName",
        "AlternativeConceptName",
    ],
}
```

## Handling Dimensional Data

**Important:** When querying normalized labels, filter by `dimensions IS NULL` to get consolidated figures.

**Why?** Many facts have dimensional breakdowns (e.g., revenue by segment, equity by component). Without filtering, you'll get duplicate values.

```sql
-- ❌ WRONG: Returns segment revenue + consolidated revenue
SELECT * FROM financial_facts WHERE normalized_label = 'revenue';

-- ✅ RIGHT: Returns only consolidated revenue
SELECT * FROM financial_facts 
WHERE normalized_label = 'revenue' AND dimensions IS NULL;
```

## Future Enhancements

1. **Expand coverage:** Add more concept mappings for industry-specific metrics
2. **Segment normalization:** Normalize dimensional concepts (e.g., 'revenue_north_america')
3. **Automatic mapping:** Use LLM to suggest mappings for unmapped concepts
4. **Validation:** Cross-check mapped concepts against actual filing to ensure accuracy

## References

- US-GAAP Taxonomy: https://www.fasb.org/xbrl
- IFRS Taxonomy: https://www.ifrs.org/issued-standards/ifrs-taxonomy/
- SEC EDGAR: https://www.sec.gov/edgar

