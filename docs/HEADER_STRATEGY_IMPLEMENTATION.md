# XBRL-First Header Strategy Implementation Plan

## Overview

Refactor the financial statement header system to trust XBRL parent-child relationships and label roles as the primary source for headers, with intelligent fallbacks when XBRL data is missing or incomplete. This makes the system universal across companies and accounting standards while maintaining readability.

## Current State Analysis

### Current Header Handling

**Location:** `src/utils/populate_statement_items.py`

**Current Approach:**
1. **Synthetic Headers**: Manually created headers (e.g., "Transactions with owners", "Earnings per share")
2. **Hardcoded Detection**: Logic checks for specific items to decide if a header is needed
3. **Fixed Positioning**: Headers placed at hardcoded `display_order` positions
4. **Not Universal**: Only works for specific patterns (e.g., EPS after net income, transactions in equity)

**Examples:**
- "Transactions with owners" header created when transaction items detected (lines 1910-1989)
- "Earnings per share" header created when EPS items detected (lines 1290-1367)
- "Other comprehensive income" header created for comprehensive income (lines 1369-1450)

### Problems with Current Approach

1. **Ignores XBRL Structure**: XBRL already defines parent-child relationships that could serve as headers
2. **Not Universal**: Hardcoded logic only works for specific companies/patterns
3. **Maintenance Burden**: Requires manual updates for each new header pattern
4. **Inconsistent**: Some headers from XBRL, some synthetic - no clear priority

## Proposed Solution: XBRL-First Header Strategy

### Priority Hierarchy

1. **Primary: XBRL Parent-Child Relationships**
   - Parent concepts with children but no facts = headers
   - Use `rel_presentation_hierarchy.parent_concept_id` to identify
   - Most authoritative - reflects company's actual filing structure

2. **Secondary: XBRL Label Roles**
   - Concepts with "documentation" label role = headers
   - Extracted from XBRL label linkbase during parsing
   - Standard XBRL mechanism for headers

3. **Tertiary: Standard Templates**
   - Industry-standard header patterns (IFRS/US-GAAP)
   - Only used when XBRL doesn't provide headers
   - Configurable per accounting standard

4. **Fallback: Synthetic Headers**
   - Create headers only when absolutely necessary
   - Log when synthetic headers are created for monitoring

## Phase 1: Documentation Updates

### 1.1 Update PRD.md

**File:** `/Users/jonas/FinSight/prd.md`

**Changes:**
- Add section "Financial Statement Header Strategy" under Data Normalization
- Document XBRL-first approach with fallback hierarchy
- Document header detection from parent-child relationships
- Document label role support for headers

**Key points to add:**
- Primary: XBRL parent-child relationships (parent concepts with children but no facts)
- Secondary: XBRL label roles (documentation role indicates headers)
- Tertiary: Standard accounting templates (IFRS/US-GAAP header patterns)
- Fallback: Synthetic headers (only when XBRL unavailable)
- Headers are structural elements (no numeric values, NULL in fact tables)

### 1.2 Update ERD.md

**File:** `/Users/jonas/FinSight/docs/ERD.md`

**Changes:**
- Document `rel_statement_items.is_header` derivation logic
- Add note about header sources (xbrl_parent, xbrl_label_role, template, synthetic)
- Document parent-child relationship usage for headers
- Update `rel_presentation_hierarchy.parent_concept_id` description

## Phase 2: Database Schema Enhancement

### 2.1 Add `header_source` column to `rel_statement_items`

**File:** `/Users/jonas/FinSight/database/schema.sql`

**Change:**
```sql
ALTER TABLE rel_statement_items 
ADD COLUMN header_source VARCHAR(20) CHECK (header_source IN ('xbrl_parent', 'xbrl_label_role', 'template', 'synthetic', NULL));

COMMENT ON COLUMN rel_statement_items.header_source IS 
'Source of header: xbrl_parent (from parent-child relationship), xbrl_label_role (from label linkbase), template (standard template), synthetic (manually created), NULL (not a header)';
```

**Migration script:** Create `database/migrations/add_header_source.sql`

### 2.2 Store label roles during XBRL parsing

**File:** `/Users/jonas/FinSight/src/parsing/parse_xbrl.py`

**Changes:**
- Extract label roles from XBRL label linkbase
- Store in `dim_concepts.label_role` column (add if missing)
- Identify "documentation" role as header indicator

## Phase 3: XBRL Parent-Child Header Detection

### 3.1 Implement `detect_xbrl_parent_headers()` function

**File:** `/Users/jonas/FinSight/src/utils/populate_statement_items.py`

**New function:**
```python
def detect_xbrl_parent_headers(
    conn,
    filing_id: int,
    statement_type: str
) -> List[Dict]:
    """
    Detect headers from XBRL parent-child relationships.
    
    A parent concept is a header if:
    1. It has children in rel_presentation_hierarchy
    2. It has no facts in fact_financial_metrics (or all facts are NULL)
    3. It's marked as abstract in dim_concepts (optional check)
    
    Returns:
        List of header items with concept_id, display_order, header_source='xbrl_parent'
    """
```

**Logic:**
- Query `rel_presentation_hierarchy` for parent concepts
- Check if parent has children: `EXISTS (SELECT 1 FROM rel_presentation_hierarchy WHERE parent_concept_id = parent.concept_id)`
- Check if parent has no facts: `NOT EXISTS (SELECT 1 FROM fact_financial_metrics WHERE concept_id = parent.concept_id AND value_numeric IS NOT NULL)`
- Use parent's `order_index` as `display_order`
- Set `is_header=TRUE`, `header_source='xbrl_parent'`

### 3.2 Integrate into `populate_statement_items()`

**File:** `/Users/jonas/FinSight/src/utils/populate_statement_items.py`

**Changes:**
- After processing XBRL items, call `detect_xbrl_parent_headers()`
- Add detected headers to `items_to_insert` with `header_source='xbrl_parent'`
- Avoid duplicates (check if header already in `items_to_insert`)

**Location:** After first pass (XBRL items), before synthetic header creation

## Phase 4: XBRL Label Role Header Detection

### 4.1 Extract label roles during parsing

**File:** `/Users/jonas/FinSight/src/parsing/parse_xbrl.py`

**Changes:**
- In `extract_concept_labels()`, also extract label roles
- Store in `dim_concepts.label_role` column
- Identify "documentation" role as header indicator

**Example:**
```python
# In extract_concept_labels()
for concept in model_xbrl.qnameConcepts.values():
    for label in concept.label(preferredLabel=True):
        label_role = label.role
        if label_role and 'documentation' in label_role.lower():
            # Mark as header
            label_roles[concept.qname.localName] = 'documentation'
```

### 4.2 Implement `detect_xbrl_label_role_headers()` function

**File:** `/Users/jonas/FinSight/src/utils/populate_statement_items.py`

**New function:**
```python
def detect_xbrl_label_role_headers(
    conn,
    filing_id: int,
    statement_type: str
) -> List[Dict]:
    """
    Detect headers from XBRL label roles.
    
    A concept is a header if:
    1. It has label_role='documentation' in dim_concepts
    2. It's in rel_presentation_hierarchy for this statement
    3. It has no facts (or all facts are NULL)
    
    Returns:
        List of header items with concept_id, display_order, header_source='xbrl_label_role'
    """
```

**Logic:**
- Query `dim_concepts` for concepts with `label_role='documentation'`
- Join with `rel_presentation_hierarchy` to get `order_index`
- Check if concept has no facts
- Set `is_header=TRUE`, `header_source='xbrl_label_role'`

### 4.3 Integrate into `populate_statement_items()`

**File:** `/Users/jonas/FinSight/src/utils/populate_statement_items.py`

**Changes:**
- After XBRL parent headers, call `detect_xbrl_label_role_headers()`
- Add detected headers to `items_to_insert` with `header_source='xbrl_label_role'`
- Avoid duplicates (check if header already exists)

## Phase 5: Standard Template Headers (Fallback)

### 5.1 Define standard header templates

**File:** `/Users/jonas/FinSight/src/utils/header_templates.py` (new file)

**Content:**
```python
STANDARD_HEADERS = {
    'income_statement': {
        'ifrs': [
            {'normalized_label': 'earnings_per_share_header', 'display_order': 14, 'preferred_label': 'Earnings per share'},
        ],
        'us_gaap': [
            {'normalized_label': 'earnings_per_share_header', 'display_order': 14, 'preferred_label': 'Earnings per share'},
        ],
    },
    'equity_statement': {
        'ifrs': [
            {'normalized_label': 'transactions_with_owners_header', 'display_order': 8, 'preferred_label': 'Transactions with owners'},
        ],
        'us_gaap': [
            {'normalized_label': 'transactions_with_owners_header', 'display_order': 8, 'preferred_label': 'Transactions with owners'},
        ],
    },
    'comprehensive_income': {
        'ifrs': [
            {'normalized_label': 'other_comprehensive_income_header', 'display_order': 1, 'preferred_label': 'Other comprehensive income'},
        ],
        'us_gaap': [
            {'normalized_label': 'other_comprehensive_income_header', 'display_order': 1, 'preferred_label': 'Other comprehensive income'},
        ],
    },
}
```

### 5.2 Implement `apply_template_headers()` function

**File:** `/Users/jonas/FinSight/src/utils/populate_statement_items.py`

**New function:**
```python
def apply_template_headers(
    conn,
    filing_id: int,
    statement_type: str,
    accounting_standard: str,
    existing_items: List[Dict]
) -> List[Dict]:
    """
    Apply standard template headers as fallback.
    
    Only creates headers if:
    1. XBRL didn't provide a header for this position
    2. Template header is appropriate for this statement type
    3. Related items exist (e.g., EPS header only if EPS items exist)
    
    Returns:
        List of template header items with header_source='template'
    """
```

**Logic:**
- Get template headers for `statement_type` and `accounting_standard`
- Check if header already exists (from XBRL)
- Check if related items exist (e.g., EPS items for EPS header)
- Create header concept if doesn't exist
- Add to `items_to_insert` with `header_source='template'`

### 5.3 Integrate into `populate_statement_items()`

**File:** `/Users/jonas/FinSight/src/utils/populate_statement_items.py`

**Changes:**
- After XBRL label role headers, call `apply_template_headers()`
- Only apply templates when XBRL headers are missing
- Log when template headers are used (for monitoring)

## Phase 6: Remove Hardcoded Synthetic Header Logic

### 6.1 Remove hardcoded header creation

**File:** `/Users/jonas/FinSight/src/utils/populate_statement_items.py`

**Remove:**
- "Earnings per share" header creation (lines 1290-1367)
- "Transactions with owners" header creation (lines 1910-1989)
- "Other comprehensive income" header creation (lines 1369-1450)

**Replace with:**
- Calls to `detect_xbrl_parent_headers()`, `detect_xbrl_label_role_headers()`, `apply_template_headers()`

### 6.2 Keep synthetic headers as last resort

**File:** `/Users/jonas/FinSight/src/utils/populate_statement_items.py`

**New function:**
```python
def create_synthetic_headers(
    conn,
    filing_id: int,
    statement_type: str,
    existing_items: List[Dict]
) -> List[Dict]:
    """
    Create synthetic headers only as last resort.
    
    Only creates headers if:
    1. XBRL didn't provide headers
    2. Templates didn't provide headers
    3. Structure clearly requires a header (e.g., EPS items without header)
    
    Logs all synthetic header creation for monitoring.
    
    Returns:
        List of synthetic header items with header_source='synthetic'
    """
```

**Logic:**
- Check if critical headers are missing (e.g., EPS header when EPS items exist)
- Create only if absolutely necessary
- Log with `logger.warning()` for monitoring
- Set `header_source='synthetic'`

## Phase 7: Update Fact Table Population

### 7.1 Ensure headers are included in fact tables

**File:** `/Users/jonas/FinSight/src/utils/populate_statement_facts.py`

**Current state:** Already handles headers correctly (lines 805-812 in equity statement)

**Verify:**
- Headers have `value_numeric=NULL` (already implemented)
- Headers have `period_id` (use default period, already implemented)
- Headers are included in queries (already implemented)

**No changes needed** - current implementation is correct

## Phase 8: API Header Handling

### 8.1 Remove hardcoded header insertion

**File:** `/Users/jonas/FinSight/api/main.py`

**Current state:** May have hardcoded header insertion logic

**Changes:**
- Remove any hardcoded header insertion in API
- Headers should come from database (`rel_statement_items` with `is_header=TRUE`)
- API should just query and return headers as-is

### 8.2 Verify header display

**File:** `/Users/jonas/FinSight/api/main.py`

**Verify:**
- Headers are returned with `value=NULL` or `value="—"`
- Headers are sorted correctly (by `display_order`)
- Headers appear before their children (if parent-child relationship exists)

## Phase 9: Data Quality Monitoring

### 9.1 Add logging for header detection

**File:** `/Users/jonas/FinSight/src/utils/populate_statement_items.py`

**Add logging:**
- Log when XBRL parent headers are detected
- Log when XBRL label role headers are detected
- Log when template headers are applied
- Log when synthetic headers are created (WARNING level)
- Include: `filing_id`, `statement_type`, `header_source`, `concept_id`

### 9.2 Add validation warnings

**File:** `/Users/jonas/FinSight/src/validation/validator.py` (or new validation module)

**Add check:**
- Flag when many headers are synthetic (indicates XBRL extraction issues)
- Flag when template headers are used frequently (indicates missing XBRL data)
- Compare XBRL headers vs. templates; warn on large discrepancies
- Validate header positioning (headers should come before their children)

## Phase 10: Testing & Validation

### 10.1 Test with Novo Nordisk (NVO 2024)

- Verify XBRL parent headers are detected correctly
- Verify "Transactions with owners" header comes from XBRL (if available)
- Verify "Earnings per share" header comes from XBRL (if available)
- Verify headers appear in correct positions

### 10.2 Test with other companies

- Test IFRS companies (different header patterns)
- Test US-GAAP companies (different structure)
- Verify system works universally without hardcoding
- Verify headers match company's actual filing structure

### 10.3 Validate UITest.py still works

- Keep UITest.py as company-specific validation layer
- UniversalUITest should validate header presence and positioning
- Both should pass after changes

## Implementation Order

1. **Phase 1** (Documentation): Update PRD.md and ERD.md
2. **Phase 2** (Schema): Add `header_source` column, extract label roles
3. **Phase 3** (XBRL Parent): Implement parent-child header detection
4. **Phase 4** (XBRL Label Role): Implement label role header detection
5. **Phase 5** (Templates): Implement standard template headers
6. **Phase 6** (Remove Hardcoded): Remove hardcoded synthetic header logic
7. **Phase 7** (Fact Tables): Verify headers in fact tables (already correct)
8. **Phase 8** (API): Remove hardcoded API header insertion
9. **Phase 9** (Monitoring): Add logging and validation
10. **Phase 10** (Testing): Test with multiple companies

## Rollback Plan

- Keep `header_source` column for tracking
- Can revert to hardcoded headers if XBRL data quality is too poor
- Monitor `header_source` distribution to assess XBRL extraction quality
- Synthetic headers remain as fallback option

## Success Criteria

- Headers detected from XBRL parent-child relationships (primary)
- Headers detected from XBRL label roles (secondary)
- Standard templates used only when XBRL unavailable (tertiary)
- Synthetic headers created only as last resort (fallback)
- System works for multiple companies without hardcoding
- Headers appear in correct positions (before their children)
- UITest.py and UniversalUITest both pass
- Data quality monitoring flags issues appropriately
- No hardcoded header logic remains

## Key Principles

1. **Trust XBRL First**: Use XBRL parent-child relationships and label roles as primary source
2. **Universal by Default**: System should work for all companies automatically
3. **Fallback Gracefully**: Templates and synthetic headers only when XBRL unavailable
4. **Monitor Quality**: Log header sources to assess XBRL extraction quality
5. **Respect Company Intent**: Show headers as company filed them in XBRL

