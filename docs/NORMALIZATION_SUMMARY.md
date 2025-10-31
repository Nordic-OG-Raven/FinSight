# Taxonomy Normalization Summary

## Coverage Statistics

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Concepts Mapped | 97 | 265 | **+168 (+173%)** |
| Facts Mapped | 5,363 | 13,645 | **+8,282 (+154%)** |
| Coverage % | 18.84% | 47.93% | **+29.09pp** |

## What Was Added

### Investment Securities (230+ facts)
- Available-for-sale securities (current/noncurrent)
- Unrealized gains/losses
- Amortized cost basis
- Equity securities (FVNI, no fair value)
- Equity method investments

### Debt & Borrowings (550+ facts)
- Carrying amount, face amount, fair value
- Interest rates (stated, effective, weighted average)
- Borrowings (bank, long-term, short-term)
- Bonds issued
- Debt net of cash

### Derivatives & Hedging (650+ facts)
- Derivative assets/liabilities (current/noncurrent)
- Fair values
- Notional amounts
- Gains/losses

### Pension & Benefits (1,000+ facts)
- Plan assets (672 facts alone!)
- Benefit obligations
- Funded status
- Service cost, interest cost
- Expected return
- Actuarial assumptions (discount rate, return rate)

### Property, Plant & Equipment (300+ facts)
- Gross PPE
- Useful life
- Additions, disposals
- Impairment
- FX changes
- Depreciation

### Intangible Assets (350+ facts)
- Gross amounts
- Accumulated amortization
- Indefinite-lived
- Useful life
- Additions, disposals, impairment
- FX changes

### Tax Details (900+ facts)
- Current tax (federal, foreign, state/local)
- Deferred tax (federal, foreign)
- Unrecognized tax benefits (increases, decreases, settlements)
- Deferred tax assets/liabilities
- Valuation allowance
- Effective tax rate
- Statutory tax rate

### Stock-Based Compensation (400+ facts)
- Options granted
- Grant date fair value
- Vested fair value
- Nonvested shares
- Vesting period
- Unrecognized compensation
- Dividend rate assumptions

### Other Comprehensive Income (400+ facts)
- OCI before reclassifications
- Reclassifications
- Cash flow hedge components
- Net investment hedge
- Pension adjustments
- Comprehensive income

### Leases (100+ facts)
- Operating lease cost
- Lease payments
- Right-of-use assets
- Lease liabilities

### Other
- Goodwill changes (acquired, other)
- Restructuring (charges, reserves)
- Business combinations (purchase price, contingent consideration)
- Segment data (revenue, capex, growth %)
- Working capital changes (receivables, inventory)
- Cash components (restricted, marketable securities)
- Other assets/liabilities

## Examples of New Queries

### Pension Funded Status Analysis
```sql
SELECT 
    company,
    MAX(CASE WHEN normalized_label = 'pension_plan_assets' THEN value_numeric END) / 1e9 as assets_B,
    MAX(CASE WHEN normalized_label = 'pension_benefit_obligation' THEN value_numeric END) / 1e9 as obligation_B
FROM financial_facts
WHERE normalized_label IN ('pension_plan_assets', 'pension_benefit_obligation')
GROUP BY company;
```

### Debt Interest Rate Comparison
```sql
SELECT 
    company,
    AVG(CASE WHEN normalized_label = 'debt_interest_rate_stated' THEN value_numeric END) as avg_stated_rate,
    AVG(CASE WHEN normalized_label = 'debt_interest_rate_effective' THEN value_numeric END) as avg_effective_rate
FROM financial_facts
WHERE normalized_label IN ('debt_interest_rate_stated', 'debt_interest_rate_effective')
GROUP BY company;
```

### Tax Efficiency Analysis
```sql
SELECT 
    company,
    MAX(CASE WHEN normalized_label = 'effective_tax_rate' THEN value_numeric END) as effective_rate,
    MAX(CASE WHEN normalized_label = 'statutory_tax_rate' THEN value_numeric END) as statutory_rate
FROM financial_facts
WHERE normalized_label IN ('effective_tax_rate', 'statutory_tax_rate')
GROUP BY company;
```

## What's Still Unmapped (52%)

The remaining 52% consists of:
- **Policy text blocks** (e.g., `RevenueRecognitionPolicyTextBlock`)
- **Document metadata** (e.g., `DocumentType`, `EntityRegistrantName`)
- **Table references** (e.g., `ScheduleOfDevelopmentInNumberOfSharesTableTextBlock`)
- **Highly specific items** (e.g., actuarial assumptions for specific years)
- **Narrative descriptions** (e.g., `DescriptionOfAccountingPolicyForRestructuringCostsAndSimilarItemsPolicyTextBlock`)

These are intentionally left unmapped as they don't require cross-company standardization.

## Impact

With 47.93% coverage, you can now:
- ✅ Compare **all major financial metrics** across companies
- ✅ Analyze **detailed footnote items** (pensions, taxes, debt)
- ✅ Track **OCI components** and hedging activities
- ✅ Examine **segment performance**
- ✅ Review **stock-based compensation** programs
- ✅ Assess **lease obligations**
- ✅ Evaluate **business combinations**

The normalization enables sophisticated financial analysis while maintaining data integrity across US-GAAP, IFRS, and custom taxonomies.
