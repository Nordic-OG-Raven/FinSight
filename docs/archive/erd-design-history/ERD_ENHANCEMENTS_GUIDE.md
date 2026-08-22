# ERD Enhancements Usage Guide

This guide documents the new ERD enhancements and provides example queries for each feature.

## Table of Contents

1. [Foundation Dimensions](#foundation-dimensions)
2. [Analysis Dimensions](#analysis-dimensions)
3. [Advanced Features](#advanced-features)
4. [Example Queries](#example-queries)

## Foundation Dimensions

### dim_reporting_frameworks

**Purpose**: Store framework metadata (IFRS, US-GAAP, UK-GAAP, etc.)

**Example Query**: Get all companies using IFRS
```sql
SELECT c.ticker, c.company_name, rf.framework_name, rf.standard_setter
FROM dim_companies c
JOIN dim_reporting_frameworks rf ON c.framework_id = rf.framework_id
WHERE rf.framework_name = 'IFRS';
```

### dim_taxonomies

**Purpose**: Store taxonomy metadata with versioning support

**Example Query**: Get all taxonomies for IFRS framework
```sql
SELECT taxonomy_name, taxonomy_version, effective_date, superseded_date
FROM dim_taxonomies
WHERE reporting_framework_id = (SELECT framework_id FROM dim_reporting_frameworks WHERE framework_name = 'IFRS')
ORDER BY taxonomy_version DESC;
```

### rel_concept_mappings

**Purpose**: Map concepts across taxonomies for cross-standard analysis

**Example Query**: Find equivalent revenue concepts across standards
```sql
SELECT 
    sc.normalized_label as source_label,
    tc.normalized_label as target_label,
    cm.mapping_type,
    cm.confidence_score
FROM rel_concept_mappings cm
JOIN dim_concepts sc ON cm.source_concept_id = sc.concept_id
JOIN dim_concepts tc ON cm.target_concept_id = tc.concept_id
WHERE sc.normalized_label = 'revenue'
  AND cm.mapping_type = 'equivalent';
```

## Analysis Dimensions

### dim_fiscal_periods

**Purpose**: Enable period normalization for cross-company analysis

**Example Query**: Get all companies with December fiscal year end
```sql
SELECT c.ticker, fp.fiscal_year, fp.fiscal_year_end_month, fp.fiscal_year_end_day
FROM dim_fiscal_periods fp
JOIN dim_companies c ON fp.company_id = c.company_id
WHERE fp.fiscal_year_end_month = 12
  AND fp.fiscal_year_end_day = 31;
```

### dim_currencies & fact_exchange_rates

**Purpose**: Multi-currency support and conversion

**Example Query**: Convert all revenue to USD
```sql
SELECT 
    c.ticker,
    fm.fiscal_year,
    fm.value_numeric as original_value,
    dc.currency_code as original_currency,
    CASE 
        WHEN dc.currency_code = 'USD' THEN fm.value_numeric
        ELSE fm.value_numeric * er.exchange_rate
    END as usd_value
FROM fact_financial_metrics fm
JOIN dim_companies c ON fm.company_id = c.company_id
JOIN dim_currencies dc ON fm.currency_id = dc.currency_id
LEFT JOIN fact_exchange_rates er ON 
    er.from_currency_id = fm.currency_id
    AND er.to_currency_id = (SELECT currency_id FROM dim_currencies WHERE currency_code = 'USD')
    AND er.rate_date = (
        SELECT MAX(rate_date) 
        FROM fact_exchange_rates 
        WHERE from_currency_id = fm.currency_id 
          AND to_currency_id = (SELECT currency_id FROM dim_currencies WHERE currency_code = 'USD')
          AND rate_date <= CURRENT_DATE
    )
WHERE fm.normalized_label = 'revenue';
```

### fact_ratios

**Purpose**: Pre-calculated financial ratios for performance

**Example Query**: Compare ROE across companies
```sql
SELECT 
    c.ticker,
    tp.fiscal_year,
    fr.ratio_value as roe,
    num.normalized_label as numerator,
    den.normalized_label as denominator
FROM fact_ratios fr
JOIN dim_companies c ON fr.company_id = c.company_id
JOIN dim_time_periods tp ON fr.period_id = tp.period_id
LEFT JOIN dim_concepts num ON fr.numerator_concept_id = num.concept_id
LEFT JOIN dim_concepts den ON fr.denominator_concept_id = den.concept_id
WHERE fr.ratio_type = 'roe'
  AND tp.fiscal_year = 2024
ORDER BY fr.ratio_value DESC;
```

### dim_segments

**Purpose**: Segment reporting (geographic, business, product)

**Example Query**: Get all segments for a company
```sql
SELECT segment_name, segment_type, parent_segment_id
FROM dim_segments
WHERE company_id = (SELECT company_id FROM dim_companies WHERE ticker = 'NVO')
ORDER BY segment_type, segment_name;
```

## Advanced Features

### fact_financial_notes & rel_fact_notes

**Purpose**: Structured notes to financial statements

**Example Query**: Get all notes related to revenue
```sql
SELECT 
    fn.note_number,
    fn.note_type,
    fn.title,
    fn.content,
    rfn.relationship_type
FROM fact_financial_notes fn
JOIN rel_fact_notes rfn ON fn.note_id = rfn.note_id
JOIN fact_financial_metrics fm ON rfn.fact_id = fm.fact_id
WHERE fm.normalized_label = 'revenue'
ORDER BY fn.order_index;
```

### fact_gaap_reconciliation

**Purpose**: Track GAAP → non-GAAP adjustments

**Example Query**: Get all non-GAAP revenue with reconciliations
```sql
SELECT 
    c.ticker,
    fm.value_numeric as non_gaap_value,
    gaap_fm.value_numeric as gaap_value,
    fgr.adjustment_type,
    fgr.adjustment_amount,
    fgr.adjustment_description
FROM fact_financial_metrics fm
JOIN dim_companies c ON fm.company_id = c.company_id
LEFT JOIN fact_gaap_reconciliation fgr ON fm.fact_id = fgr.non_gaap_fact_id
LEFT JOIN fact_financial_metrics gaap_fm ON fgr.gaap_fact_id = gaap_fm.fact_id
WHERE fm.normalized_label = 'revenue'
  AND fm.is_gaap = FALSE;
```

### audit_fact_changes

**Purpose**: Audit trail for fact changes

**Example Query**: Get all restatements for a company
```sql
SELECT 
    afc.fact_id,
    afc.old_value_numeric,
    afc.new_value_numeric,
    afc.change_type,
    afc.reason,
    afc.changed_at,
    afc.changed_by
FROM audit_fact_changes afc
JOIN fact_financial_metrics fm ON afc.fact_id = fm.fact_id
WHERE fm.company_id = (SELECT company_id FROM dim_companies WHERE ticker = 'NVO')
  AND afc.change_type = 'restatement'
ORDER BY afc.changed_at DESC;
```

### fact_restatements

**Purpose**: Track restatement events

**Example Query**: Get all restatements with impact
```sql
SELECT 
    c.ticker,
    fr.restatement_date,
    fr.restatement_type,
    fr.reason,
    fr.impact_amount,
    fr.affected_periods
FROM fact_restatements fr
JOIN dim_companies c ON fr.company_id = c.company_id
ORDER BY fr.restatement_date DESC;
```

## Example Queries

### Cross-Standard Analysis

**Query**: Compare revenue for all companies regardless of standard
```sql
SELECT 
    c.ticker,
    rf.framework_name,
    fm.fiscal_year,
    fm.value_numeric as revenue
FROM fact_financial_metrics fm
JOIN dim_companies c ON fm.company_id = c.company_id
JOIN dim_reporting_frameworks rf ON c.framework_id = rf.framework_id
WHERE fm.normalized_label = 'revenue'
  AND fm.fiscal_year = 2024
ORDER BY rf.framework_name, fm.value_numeric DESC;
```

### Period Normalization

**Query**: Compare Q1 revenue across companies (regardless of fiscal year end)
```sql
SELECT 
    c.ticker,
    fp.fiscal_year_end_month,
    fp.fiscal_year_end_day,
    fm.fiscal_year,
    fm.value_numeric as revenue
FROM fact_financial_metrics fm
JOIN dim_companies c ON fm.company_id = c.company_id
JOIN dim_fiscal_periods fp ON c.company_id = fp.company_id AND fm.fiscal_year = fp.fiscal_year
JOIN dim_time_periods tp ON fm.period_id = tp.period_id
WHERE fm.normalized_label = 'revenue'
  AND EXTRACT(QUARTER FROM tp.end_date) = 1
  AND fm.fiscal_year = 2024
ORDER BY fm.value_numeric DESC;
```

### Multi-Currency Analysis

**Query**: Show revenue in original currency and USD equivalent
```sql
SELECT 
    c.ticker,
    dc.currency_code,
    fm.value_numeric as original_value,
    CASE 
        WHEN dc.currency_code = 'USD' THEN fm.value_numeric
        ELSE fm.value_numeric * COALESCE(er.exchange_rate, 1)
    END as usd_equivalent
FROM fact_financial_metrics fm
JOIN dim_companies c ON fm.company_id = c.company_id
JOIN dim_currencies dc ON fm.currency_id = dc.currency_id
LEFT JOIN fact_exchange_rates er ON 
    er.from_currency_id = fm.currency_id
    AND er.to_currency_id = (SELECT currency_id FROM dim_currencies WHERE currency_code = 'USD')
WHERE fm.normalized_label = 'revenue'
  AND fm.fiscal_year = 2024;
```

### Ratio Analysis

**Query**: Compare financial ratios across companies
```sql
SELECT 
    c.ticker,
    fr.ratio_type,
    fr.ratio_value,
    tp.fiscal_year
FROM fact_ratios fr
JOIN dim_companies c ON fr.company_id = c.company_id
JOIN dim_time_periods tp ON fr.period_id = tp.period_id
WHERE fr.ratio_type IN ('roe', 'roa', 'current_ratio')
  AND tp.fiscal_year = 2024
ORDER BY c.ticker, fr.ratio_type;
```

### Segment Analysis

**Query**: Get segment breakdown for a company
```sql
SELECT 
    ds.segment_name,
    ds.segment_type,
    fm.normalized_label,
    fm.value_numeric,
    tp.fiscal_year
FROM fact_financial_metrics fm
JOIN dim_xbrl_dimensions dx ON fm.dimension_id = dx.dimension_id
JOIN dim_segments ds ON dx.dimension_json->>'segment' = ds.segment_name
JOIN dim_time_periods tp ON fm.period_id = tp.period_id
WHERE fm.company_id = (SELECT company_id FROM dim_companies WHERE ticker = 'NVO')
  AND fm.normalized_label = 'revenue'
  AND tp.fiscal_year = 2024;
```

### Notes Analysis

**Query**: Get all accounting policy notes
```sql
SELECT 
    c.ticker,
    fn.note_number,
    fn.title,
    fn.content
FROM fact_financial_notes fn
JOIN dim_filings f ON fn.filing_id = f.filing_id
JOIN dim_companies c ON f.company_id = c.company_id
WHERE fn.note_type = 'accounting_policy'
ORDER BY c.ticker, fn.order_index;
```

### Restatement Analysis

**Query**: Find companies with frequent restatements
```sql
SELECT 
    c.ticker,
    COUNT(*) as restatement_count,
    SUM(fr.impact_amount) as total_impact
FROM fact_restatements fr
JOIN dim_companies c ON fr.company_id = c.company_id
WHERE fr.restatement_date >= CURRENT_DATE - INTERVAL '5 years'
GROUP BY c.ticker
HAVING COUNT(*) > 2
ORDER BY restatement_count DESC;
```

## Migration Notes

After running the migration script (`migrate_erd_enhancements.py`):

1. **Verify frameworks populated**: `SELECT * FROM dim_reporting_frameworks;`
2. **Verify taxonomies populated**: `SELECT * FROM dim_taxonomies;`
3. **Verify companies linked**: `SELECT COUNT(*) FROM dim_companies WHERE framework_id IS NOT NULL;`
4. **Verify concepts linked**: `SELECT COUNT(*) FROM dim_concepts WHERE taxonomy_id IS NOT NULL;`
5. **Verify currencies populated**: `SELECT * FROM dim_currencies;`
6. **Verify facts linked**: `SELECT COUNT(*) FROM fact_financial_metrics WHERE currency_id IS NOT NULL;`

## Next Steps

1. Populate concept mappings manually or via automated matching
2. Load exchange rates from external sources (FRED, SEC, etc.)
3. Calculate ratios for existing data: `python src/utils/calculate_ratios.py`
4. Extract notes from filings (future enhancement)
5. Track restatements as they occur (future enhancement)

