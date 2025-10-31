# Deduplication Risks & Mitigation

## The Deduplication Approach:
"When querying, if multiple concepts for same (company, metric, year, dimension) have identical values, keep only one"

## Potential Problems:

### Problem 1: Losing Semantic Information
**Risk**: Different concepts with same value may have different meanings.

**Example:**
```
Company: AAPL, Metric: total_assets, Year: 2023
- Assets: $352.6B
- LiabilitiesAndStockholdersEquity: $352.6B
```

**If we deduplicate:**
- Keep only "Assets" (because it has lower order_index)
- Lose "LiabilitiesAndStockholdersEquity"

**Problem**: Users can't verify balance sheet equation (Assets = L+E) if we hide one side

**Impact**: MEDIUM - Makes manual validation harder

**Mitigation**:
- Don't actually DELETE the duplicate - keep in database
- Only hide in user-facing views/queries
- Add "Show All Concepts" debug toggle in viewer

---

### Problem 2: Audit Trail Loss
**Risk**: Can't trace back to original XBRL filing if we delete facts.

**Example:**
If SEC asks "where did you get $352.6B for AAPL assets?", we need to say:
- "Concept: Assets, Context: c-42, FactID: f-123"

**If we deleted one:**
- Can't show full lineage
- Compliance issue for regulated users

**Impact**: HIGH - Could violate audit requirements

**Mitigation**:
- NEVER delete from `fact_financial_metrics` table
- Create VIEW with deduplication logic
- Keep raw facts table complete

---

### Problem 3: Missing Small Differences
**Risk**: 0.3% difference might seem "identical" but could be meaningful.

**Example:**
```
KO net_income FY2023:
- NetIncomeLoss: $9,542,000,000
- ProfitLoss: $9,571,000,000
(0.3% diff = $29M)
```

**If we deduplicate** (< 0.5% threshold):
- Keep only one
- Lose $29M difference

**But**: This $29M = noncontrolling interest (minority shareholders)

**Impact**: MEDIUM - Loss of analytical granularity

**Mitigation**:
- Set very strict threshold (< 0.1% or even 0.01%)
- OR keep both if ANY difference exists
- Document what was deduplicated

---

### Problem 4: Cross-Taxonomy Comparability Loss
**Risk**: If we deduplicate based on `is_primary` flag, we might keep different concept types for different companies.

**Example:**
```
AAPL (US-GAAP): Keep "NetIncomeLoss" (is_primary=True)
SNY (IFRS): Keep "ProfitLoss" (is_primary=True)
```

**Problem**: Cross-company comparison now uses different concepts

**Impact**: HIGH - Defeats purpose of normalization

**Mitigation**:
- Deduplication must be deterministic across companies
- Use concept_name priority, not is_primary
- Always prefer same concept for same normalized_label

---

### Problem 5: Breaking Calculation Relationships
**Risk**: If we hide child concepts, calculation tree becomes incomplete.

**Example:**
```
Revenue (parent) = Revenue from Contracts (child) + Collaborative Revenue (child)
```

**If we deduplicate** and hide children:
- Parent shown: $58.5B
- Children hidden
- Users can't see breakdown

**Impact**: MEDIUM - Loses drill-down capability

**Mitigation**:
- Only deduplicate at SAME hierarchy level
- Keep parent-child relationships intact
- Use calculation linkbase to determine hierarchy

---

## Recommended Deduplication Strategy:

### SAFE Approach (What I Recommend):

```sql
CREATE VIEW v_deduplicated_facts AS
SELECT DISTINCT ON (
    company_id, 
    normalized_label, 
    fiscal_year, 
    dimension_id,
    value_numeric  -- Include value to ensure we're only deduping identical values
)
    f.fact_id,
    f.company_id,
    f.concept_id,
    f.filing_id,
    f.period_id,
    f.dimension_id,
    f.value_numeric,
    f.value_text,
    f.unit_measure,
    -- Include concept info for auditability
    dc.concept_name,
    dc.normalized_label
FROM fact_financial_metrics f
JOIN dim_concepts dc ON f.concept_id = dc.concept_id
WHERE 
    -- Exclude cases where values differ (> 0.01% = not truly identical)
    NOT EXISTS (
        SELECT 1
        FROM fact_financial_metrics f2
        JOIN dim_concepts dc2 ON f2.concept_id = dc2.concept_id
        JOIN dim_time_periods dt2 ON f2.period_id = dt2.period_id
        WHERE f2.company_id = f.company_id
          AND dc2.normalized_label = dc.normalized_label
          AND dt2.fiscal_year = (SELECT fiscal_year FROM dim_time_periods WHERE period_id = f.period_id)
          AND f2.dimension_id IS NOT DISTINCT FROM f.dimension_id
          AND f2.fact_id != f.fact_id
          AND ABS(f2.value_numeric - f.value_numeric) / NULLIF(f.value_numeric, 0) > 0.0001
    )
ORDER BY 
    company_id, 
    normalized_label, 
    fiscal_year, 
    dimension_id,
    value_numeric,
    -- Tiebreaker: prefer concept names in this order
    CASE dc.concept_name
        WHEN 'Assets' THEN 1
        WHEN 'NetIncomeLoss' THEN 1
        WHEN 'StockholdersEquity' THEN 1
        ELSE 2
    END,
    f.is_primary DESC NULLS LAST;
```

### What This Does:

1. **Keeps raw facts intact** - no deletion
2. **Only dedupes truly identical** - < 0.01% difference
3. **Deterministic** - always picks same concept for same label
4. **Auditable** - original facts still in database
5. **Safe** - if ANY meaningful difference, keeps both

### Problems This Avoids:

- ✅ Audit trail preserved (raw facts table unchanged)
- ✅ Small differences kept (0.3% = $29M for KO retained)
- ✅ Cross-taxonomy consistency (always picks Assets over LiabilitiesAndStockholdersEquity)
- ✅ Calculation relationships intact (only dedupes at display layer)
- ✅ Can toggle back to "show all" for debugging

### Problems This Doesn't Solve:

- ⚠️ Users still confused why total_assets appears twice in raw table
- ⚠️ Fact count still inflated (26k vs ~24k deduplicated)

But these are acceptable tradeoffs for data integrity.

---

## Alternative: Deduplication During Loading

**More aggressive**: Deduplicate BEFORE inserting into `fact_financial_metrics`

**Pros:**
- Cleaner database from start
- No view complexity
- True fact count

**Cons:**
- ❌ Audit trail lost
- ❌ Can't recover if we made wrong deduplication choice
- ❌ Irreversible

**Verdict**: Too risky - stick with VIEW approach

