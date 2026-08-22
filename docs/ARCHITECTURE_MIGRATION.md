# Template Tables + Views + ELT Architecture - Migration Guide

## Overview

This document describes the migration from the old ETL architecture (denormalized fact tables) to the new hybrid ETL/ELT architecture with template-based presentation.

## Architecture Changes

### Old Architecture (ETL)
```
Extract → Transform (Python) → Load (denormalized fact tables)
```

**Problems:**
- Data duplication (same data in `fact_financial_metrics` AND `fact_income_statement`, etc.)
- Sync issues (need to keep multiple tables in sync)
- Headers stored as facts (mixing data with presentation)
- Hard to debug (no raw data preserved)
- Hard to reprocess (need to re-extract to change transformations)

### New Architecture (Hybrid ETL/ELT)
```
Extract → Load (staging_facts) → Transform (SQL) → Query (functions)
```

**Benefits:**
- No data duplication (single source of truth: `fact_financial_metrics`)
- No sync issues (functions always query latest data)
- Headers in templates (clean separation of data vs. presentation)
- Easy debugging (query `staging_facts` to see raw data)
- Easy reprocessing (`UPDATE staging_facts SET is_processed = FALSE`)

## New Components

### 1. ELT Staging Layer

**Table**: `staging_facts`
- Stores raw extracted facts (minimal transformation)
- Preserves original extraction method and metadata
- Enables debugging and reprocessing

**View**: `v_staging_to_facts`
- Shows transformation logic from staging to facts
- Useful for understanding how raw data is transformed

### 2. Template Tables

**Table**: `dim_statement_templates`
- Canonical templates for standard statement structures
- 80-90% of items are standard (IFRS Income Statement, US-GAAP Balance Sheet, etc.)
- Headers and spacers stored here, NOT in fact tables

**Table**: `rel_statement_overrides`
- Filing-specific custom items (10-20%)
- Overrides to templates for company-specific items
- Example: "Reduction of the B share capital" (NVO-specific)

### 3. Statement Functions

**Functions**: 
- `get_income_statement(filing_id, period_id)`
- `get_balance_sheet(filing_id, period_id)`
- `get_cash_flow(filing_id, period_id)`
- `get_comprehensive_income(filing_id, period_id)`
- `get_equity_statement(filing_id, period_id)`

**Usage**:
```sql
SELECT * FROM get_income_statement(5, 123) ORDER BY display_order;
```

These functions replace queries to denormalized fact tables.

## Migration Steps

### Step 1: Run Schema Migration

```bash
# Apply new schema (creates staging tables, template tables, functions)
psql -U superset -d finsight -f database/schema.sql
```

### Step 2: Run Data Migration

```bash
# Populate templates from existing rel_statement_items
python database/migrations/migrate_to_templates_views.py
```

This script:
- Analyzes existing `rel_statement_items` to identify common patterns
- Creates canonical templates for standard items
- Validates the setup

### Step 3: Validate Functions

```bash
# Compare functions vs denormalized tables
python scripts/validate_templates_views.py
```

This ensures functions return the same data as denormalized tables.

### Step 4: Update API (Incremental)

Update `api/main.py` to use functions instead of denormalized tables:

**Old**:
```python
query = text("""
    SELECT * FROM fact_income_statement
    WHERE filing_id = :filing_id AND period_id = :period_id
""")
```

**New**:
```python
query = text("""
    SELECT * FROM get_income_statement(:filing_id, :period_id)
""")
```

**Migration Strategy**:
- Start with one statement type (e.g., income_statement)
- Test thoroughly
- Migrate other statement types incrementally
- Keep denormalized tables until all are migrated

### Step 5: Deprecate Old Tables (After Validation)

Once all statement types are migrated and validated:
1. Mark denormalized fact tables as deprecated in `schema.sql`
2. Remove `populate_statement_facts.py` dependency
3. Update documentation

## Testing

### Test Staging Layer

```sql
-- View raw extracted data
SELECT * FROM staging_facts WHERE filing_id = 5 LIMIT 10;

-- View transformation logic
SELECT * FROM v_staging_to_facts WHERE filing_id = 5 LIMIT 10;
```

### Test Functions

```sql
-- Test income statement function
SELECT * FROM get_income_statement(5, 123) ORDER BY display_order;

-- Compare with denormalized table
SELECT * FROM fact_income_statement 
WHERE filing_id = 5 AND period_id = 123 
ORDER BY display_order;
```

### Test Template Population

```sql
-- View templates
SELECT * FROM dim_statement_templates 
WHERE statement_type = 'income_statement' AND format_type = 'ifrs'
ORDER BY item_order;

-- View overrides for a filing
SELECT * FROM rel_statement_overrides 
WHERE filing_id = 5
ORDER BY item_order;
```

## Rollback Plan

If issues arise:

1. **Keep denormalized tables**: They remain functional during migration
2. **Revert API changes**: Switch back to denormalized table queries
3. **Keep `populate_statement_facts.py`**: Can still populate denormalized tables if needed

## Benefits Realized

1. **Debugging**: Query `staging_facts` to see raw data, compare with `fact_financial_metrics`
2. **Reprocessing**: `UPDATE staging_facts SET is_processed = FALSE WHERE filing_id = X` and re-run transformation
3. **No Data Duplication**: Single source of truth (`fact_financial_metrics`)
4. **No Sync Issues**: Functions always query latest data
5. **Headers in Templates**: Cleaner separation of data vs. presentation
6. **Performance**: SQL functions are efficient and can be optimized further

## Files Modified

- `database/schema.sql` - Added staging tables, template tables, functions
- `database/load_financial_data.py` - Added staging layer
- `src/utils/populate_statement_items.py` - Added template population
- `database/migrations/migrate_to_templates_views.py` - Migration script
- `scripts/validate_templates_views.py` - Validation script
- `docs/ERD.md` - Updated architecture documentation
- `prd.md` - Updated data flow and architecture sections

## Next Steps

1. Run migration script
2. Validate functions
3. Update API incrementally
4. Test thoroughly
5. Deprecate old tables after validation

