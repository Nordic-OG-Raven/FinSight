# Star Schema Migration - October 29, 2025

## Problem

The initial database implementation used a single denormalized `financial_facts` table that:
- Had NO unique constraints (allowed duplicate rows)
- Did NOT store dimensional breakdowns (segments, products, geographies)
- Mixed consolidated totals with dimensional facts
- Made cross-company analysis difficult
- Violated data warehouse best practices

**Critical Issues:**
1. Duplicate rows being inserted on every load
2. No way to distinguish between total values and segment breakdowns
3. Missing dimensions meant "duplicate" facts were actually legitimate breakdowns
4. No proper primary/foreign key relationships
5. Not suitable for a portfolio project demonstrating real-world data engineering

## Solution: Star Schema Data Warehouse

### Architecture

Implemented industry-standard **star schema** design:

```
Dimension Tables:
├── dim_companies (11 companies)
├── dim_concepts (3,383 financial concepts)
├── dim_time_periods (336 fiscal periods)
├── dim_filings (14 filings)
└── dim_xbrl_dimensions (3,731 dimensional breakdowns)

Fact Table:
└── fact_financial_metrics (30,908 facts)
    ├── 11,647 consolidated facts (37.7%)
    └── 19,261 dimensional facts (62.3%)

Metadata Tables:
├── data_quality_scores
└── taxonomy_mappings
```

### Benefits

1. **Data Integrity**
   - Proper PRIMARY KEY and FOREIGN KEY constraints
   - UNIQUE constraint prevents duplicates: `(filing_id, concept_id, period_id, dimension_id)`
   - NOT NULL constraints on critical fields
   - Referential integrity enforced

2. **Dimensional Modeling**
   - Consolidated facts: `dimension_id IS NULL`
   - Segment breakdowns: `dimension_id` references specific breakdown
   - JSONB storage for flexible dimensional structures
   - Can distinguish between total revenue vs product-specific revenue

3. **Query Performance**
   - 20+ indexes on common query patterns
   - Materialized views for consolidated facts
   - Star schema optimized for OLAP queries
   - Efficient joins on dimension tables

4. **Scalability**
   - Can add new companies without schema changes
   - New concepts automatically added to dim_concepts
   - Supports incremental loading
   - Idempotent loads (ON CONFLICT DO UPDATE)

5. **Professional Standards**
   - Industry-standard data warehouse pattern
   - Proper normalization (dimensions) + denormalization (fact table)
   - Audit trail with timestamps
   - Data quality tracking

### Implementation

**Files Created:**
- `database/schema.sql` - Complete DDL for star schema
- `database/init_db.sh` - Database initialization script
- `database/load_financial_data.py` - Python loader for star schema
- `database/load_financial_data.sh` - Shell wrapper
- `docs/DATABASE.md` - Comprehensive documentation
- `src/ui/data_viewer_v2.py` - Updated Streamlit viewer

**Migration Steps:**
1. Backed up existing table
2. Dropped old denormalized table
3. Created star schema with proper constraints
4. Loaded all 11 companies (30,908 facts)
5. Verified data integrity
6. Updated Streamlit viewer to query star schema

### Data Verification

**Before (Broken):**
- Single table: `financial_facts`
- Duplicate rows allowed
- No dimensional tracking
- 28,471 facts (many duplicates)
- 0 dimensional facts

**After (Fixed):**
- 8 tables (5 dimensions, 1 fact, 2 metadata)
- 30,908 unique facts
- 19,261 (62.3%) dimensional facts properly tracked
- 11,647 (37.7%) consolidated facts
- All companies loaded successfully
- Proper constraints prevent duplicates

### Example: Apple Cost of Revenue

**Before:**
```
company | concept                    | value       | dimensions
AAPL    | CostOfGoodsAndServicesSold | 210000000000| NULL
AAPL    | CostOfGoodsAndServicesSold | 185000000000| NULL  <- "duplicate"
AAPL    | CostOfGoodsAndServicesSold | 25000000000 | NULL  <- "duplicate"
```
These appeared as duplicates but were actually:
- Total: $210B
- Products: $185B
- Services: $25B

**After:**
```
company_id | concept_id | value        | dimension_id
1          | 245        | 210000000000 | NULL         <- Total
1          | 245        | 185000000000 | 1523         <- Products (ProductMember)
1          | 245        | 25000000000  | 1524         <- Services (ServiceMember)
```

The `dimension_id` properly distinguishes between total and breakdowns.

### Query Examples

**Consolidated Revenue Comparison:**
```sql
SELECT 
    c.ticker,
    t.fiscal_year,
    f.value_numeric / 1e9 as revenue_billions
FROM fact_financial_metrics f
JOIN dim_companies c ON f.company_id = c.company_id
JOIN dim_concepts co ON f.concept_id = co.concept_id
JOIN dim_time_periods t ON f.period_id = t.period_id
WHERE co.normalized_label = 'revenue'
  AND f.dimension_id IS NULL  -- Consolidated only
ORDER BY t.fiscal_year, f.value_numeric DESC;
```

**Segment Analysis:**
```sql
SELECT 
    c.ticker,
    d.member_name as segment,
    co.concept_name,
    f.value_numeric
FROM fact_financial_metrics f
JOIN dim_companies c ON f.company_id = c.company_id
JOIN dim_concepts co ON f.concept_id = co.concept_id
JOIN dim_xbrl_dimensions d ON f.dimension_id = d.dimension_id
WHERE c.ticker = 'GOOGL'
  AND d.axis_name LIKE '%Segment%';
```

### Best Practices Followed

1. ✅ Star schema design (dimensional modeling)
2. ✅ Proper primary and foreign keys
3. ✅ Unique constraints on business logic
4. ✅ Indexes on query patterns
5. ✅ Materialized views for performance
6. ✅ Audit timestamps
7. ✅ Data quality tracking
8. ✅ Idempotent loading
9. ✅ Comprehensive documentation
10. ✅ Version-controlled DDL

### Lessons Learned

1. **Always start with proper schema design** - Fixing it later is painful
2. **Dimensional data is critical for XBRL** - 62% of facts have dimensions
3. **UNIQUE constraints must consider all distinguishing factors** - Not just (company, concept, period)
4. **Star schema is worth the complexity** - Much better for analysis
5. **Document everything** - Future you will thank present you

### Next Steps

- [x] Initialize star schema
- [x] Load all financial data
- [x] Update Streamlit viewer
- [ ] Add data quality dashboard
- [ ] Create Superset dashboards
- [ ] Implement incremental loading
- [ ] Add automated testing
- [ ] Set up GitHub Actions

## Summary

This migration transformed FinSight from a broken denormalized table into a production-quality data warehouse following industry best practices. The star schema properly models the dimensional nature of XBRL financial data and enables sophisticated cross-company analysis.

**Portfolio Impact:**
- Demonstrates understanding of data warehousing
- Shows best practices in database design
- Proves ability to handle complex dimensional data
- Documents problem-solving and migration process

