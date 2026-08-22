# ERD Improvements: Business Keys Implementation

## Overview

This document describes the three ERD improvements implemented to make queries less complex and fragile during debugging. These changes follow industry-standard data warehouse design principles.

## Improvements Implemented

### 1. Business Keys in Dimension Tables

#### `dim_time_periods`
- **Added**: `business_key` computed column (`fiscal_year || '-' || period_type`, e.g., '2024-duration')
- **Added**: Index on `(fiscal_year, period_type)` for fast lookups
- **Benefit**: Enables matching periods by business attributes without complex date comparisons

#### `dim_concepts`
- **Added**: `UNIQUE(normalized_label)` constraint
- **Changed**: `normalized_label` is now `NOT NULL`
- **Benefit**: `normalized_label` is the true business key for cross-taxonomy matching (US-GAAP vs IFRS)

### 2. Business Keys in Fact Table (Denormalized)

#### `fact_financial_metrics`
- **Added**: Denormalized columns:
  - `normalized_label VARCHAR(200) NOT NULL` (from `dim_concepts`)
  - `fiscal_year INTEGER NOT NULL` (from `dim_time_periods`)
  - `period_type VARCHAR(20) NOT NULL` (from `dim_time_periods`)
- **Changed**: Unique constraint now uses business keys:
  - `UNIQUE(filing_id, normalized_label, fiscal_year, period_type, dimension_id)`
- **Added**: Indexes on business keys for fast lookups
- **Benefit**: 
  - Queries can match facts by `normalized_label` + `fiscal_year` + `period_type` without joins
  - Enables simpler ON CONFLICT clauses in data loading
  - Reduces query complexity when matching SEC_API vs XBRL data

### 3. Automatic Maintenance via Triggers

- **Added**: `populate_fact_business_keys()` trigger function
  - Automatically populates denormalized columns when facts are inserted/updated
- **Added**: `update_fact_normalized_label()` trigger function
  - Updates all facts when a concept's `normalized_label` changes
- **Added**: `update_fact_period_info()` trigger function
  - Updates all facts when a period's `fiscal_year` or `period_type` changes
- **Benefit**: Ensures data consistency without manual maintenance

## Migration

For existing databases, run:
```bash
psql -d finsight -f database/migrations/add_business_keys.sql
```

This migration:
1. Adds business key columns to dimension tables
2. Populates denormalized columns in fact table
3. Adds unique constraints and indexes
4. Creates maintenance triggers

## Impact on Queries

### Before (Complex)
```sql
-- Match SEC_API vs XBRL data required complex joins
SELECT fm1.value_numeric as xbrl_value, fm2.value_numeric as sec_api_value
FROM fact_financial_metrics fm1
JOIN dim_concepts dc1 ON fm1.concept_id = dc1.concept_id
JOIN dim_time_periods dt1 ON fm1.period_id = dt1.period_id
JOIN fact_financial_metrics fm2 ON fm2.filing_id = fm1.filing_id
JOIN dim_concepts dc2 ON fm2.concept_id = dc2.concept_id
JOIN dim_time_periods dt2 ON fm2.period_id = dt2.period_id
WHERE dc1.normalized_label = dc2.normalized_label
  AND EXTRACT(YEAR FROM COALESCE(dt1.end_date, dt1.instant_date)) = 
      EXTRACT(YEAR FROM COALESCE(dt2.end_date, dt2.instant_date))
  AND dt1.period_type = dt2.period_type
  AND fm1.source = 'XBRL' AND fm2.source = 'SEC_API'
```

### After (Simple)
```sql
-- Match SEC_API vs XBRL data using business keys (no joins needed)
SELECT fm1.value_numeric as xbrl_value, fm2.value_numeric as sec_api_value
FROM fact_financial_metrics fm1
JOIN fact_financial_metrics fm2 ON 
    fm2.filing_id = fm1.filing_id
    AND fm2.normalized_label = fm1.normalized_label
    AND fm2.fiscal_year = fm1.fiscal_year
    AND fm2.period_type = fm1.period_type
WHERE fm1.source = 'XBRL' AND fm2.source = 'SEC_API'
```

## Benefits

1. **Simpler Queries**: No need to join to dimension tables for matching
2. **Better Performance**: Indexes on business keys enable fast lookups
3. **Easier Debugging**: Can directly query facts by business attributes
4. **Industry Standard**: Denormalization of business keys is a common data warehouse pattern
5. **Data Integrity**: Unique constraints prevent duplicate facts at the business key level

## Backward Compatibility

- Legacy unique constraint `(filing_id, concept_id, period_id, dimension_id)` is maintained for backward compatibility
- All existing queries continue to work
- New queries can use business keys for simpler logic

## Files Modified

1. `/Users/jonas/FinSight/database/schema.sql` - Updated schema with business keys
2. `/Users/jonas/FinSight/database/migrations/add_business_keys.sql` - Migration script
3. `/Users/jonas/FinSight/database/load_financial_data.py` - Updated loader to populate business keys

