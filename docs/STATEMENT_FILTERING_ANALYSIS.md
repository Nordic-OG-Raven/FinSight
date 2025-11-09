# Financial Statement Filtering and Organization

## Current Implementation (Star Schema + Statement-Specific Fact Tables)

The system uses a **star schema** data warehouse with **statement-specific fact tables** for optimal performance:

### Database Architecture
- **Dimension Tables**: `dim_companies`, `dim_concepts`, `dim_time_periods`, `dim_filings`, `dim_xbrl_dimensions`
- **Fact Tables**: 
  - `fact_financial_metrics` (all facts, including dimensional breakdowns)
  - `fact_income_statement` (pre-filtered, pre-ordered income statement items)
  - `fact_balance_sheet` (pre-filtered, pre-ordered balance sheet items)
  - `fact_cash_flow` (pre-filtered, pre-ordered cash flow items)
  - `fact_comprehensive_income` (pre-filtered, pre-ordered comprehensive income items)
- **Metadata Tables**: `rel_statement_items` (statement type, display order, is_header, is_main_item)

### ETL Pipeline Integration
- **`populate_statement_items.py`**: Identifies main statement items using XBRL `role_uri` patterns and presentation hierarchy
- **`populate_statement_facts.py`**: Populates statement-specific fact tables with pre-filtered, pre-ordered facts
- **`concept_label_mapping.py`**: Provides universal label humanization based on IFRS/US-GAAP terminology
- **`preferred_label` column**: Stores human-readable labels in `dim_concepts` (populated during ETL, lasting solution)

### Key Features
- ✅ **Universal filtering**: Uses XBRL `role_uri` patterns (not company-specific)
- ✅ **Universal ordering**: Based on IFRS/US-GAAP standard structure
- ✅ **Universal labels**: Standard accounting terminology via `preferred_label`
- ✅ **Lasting fixes**: All processing integrated into ETL pipeline
- ✅ **Sign corrections**: Universal IFRS/US-GAAP rules for comprehensive income items

## Problem Statement (Historical Context)

Previously, we were displaying **ALL** income statement items from the database, including:
- Main statement items (what companies actually show in their primary income statement)
- Tax reconciliation details (typically in tax notes)
- Detailed breakdowns (employee benefits, interest details, etc. - typically in footnotes)
- Various adjustments and reconciliations

**Example: Novo Nordisk**
- **Actual Income Statement**: ~15 main line items
- **What We Were Showing**: 100+ items including all detailed breakdowns

## What Should Be Displayed

Based on professional financial statement presentation, the main income statement should include:

### Core Income Statement Items:
1. **Revenue Section**
   - Net sales / Revenue
   - Cost of goods sold / Cost of sales
   - **→ Gross profit** (subtotal)

2. **Operating Expenses Section**
   - Sales and distribution costs
   - Research and development costs
   - Administrative costs
   - Other operating income and expenses
   - **→ Operating profit** (subtotal)

3. **Financial Items Section**
   - Financial income
   - Financial expenses
   - **→ Profit before income taxes** (subtotal)

4. **Tax and Net Profit Section**
   - Income taxes
   - **→ Net profit** (subtotal)

5. **Earnings Per Share Section**
   - Basic earnings per share
   - Diluted earnings per share

### What Should Be FILTERED OUT:

1. **Tax Reconciliation Items** (typically in tax note):
   - `Adjustments For Current Tax Of Prior Period`
   - `Adjustments For Deferred Tax Of Prior Periods`
   - `Current And Deferred Tax Expense Income Before Adjustments`
   - `Other Tax Rate Effects For Reconciliation...`
   - `Tax Rate Effect Of Foreign Tax Rates`
   - `Tax Rate Effect Of Revenues Exempt From Taxation...`
   - `Effective Tax Rate Reconciliation...`
   - `Income Tax Reconciliation...`

2. **Detailed Breakdowns** (typically in footnotes/schedules):
   - `Employee Benefits Expense Gross`
   - `Employee Benefits Expense Research And Development Expense`
   - `Other Employee Expense`
   - `Postemployment Benefit Expense Defined Benefit Plans`
   - `Postemployment Benefit Expense Defined Contribution Plans`
   - `Depreciation Amortisation And Impairment Loss...`
   - `Adjustments For Depreciation And Amortisation Expense...`
   - `Interest Paid Classified As Operating Activities`
   - `Interest Received Classified As Operating Activities`
   - `Income Taxes Paid Refund Current Period Domestic`
   - `Income Taxes Paid Refund Current Period Foreign`

3. **Cash Flow Classifications** (belong in cash flow statement):
   - `Income Taxes Paid Refund Classified As Operating Activities`
   - `Interest Paid Classified As Operating Activities`
   - `Interest Received Classified As Operating Activities`

4. **Derivative/Financial Instrument Details** (typically in notes):
   - `Income Losses On Change In Fair Value Of Derivatives...`
   - `Gains Losses On Change In Value Of Forward Elements...`

5. **Percentage/Ratio Metrics** (not line items):
   - `Profit Loss From Operating Activities Operating Margin Percent`
   - `Research And Development Expense Percentage Of Revenue`
   - `Revenue Growth Percent`
   - `Applicable Tax Rate`
   - `Average Effective Tax Rate`
   - `Statutory Tax Rate`
   - `Effective Tax Rate`

6. **Adjustment/Reconciliation Items**:
   - `Adjustments For Interest Income Expense Net`
   - `Other Adjustments To Reconcile Profit Loss`
   - `Adjustments For Income Tax Expense`

7. **Balance Sheet Items** (wrong statement type):
   - `Deferred Tax Liabilities`
   - `Current Tax Liabilities Current`
   - `Retained Earnings`
   - `Current Inventories Indirect Production Costs...`

8. **Other Detailed Items**:
   - `Auditors Remuneration For Tax Services`
   - `Professional Fees Expense`
   - `Expense From Sharebased Payment Transactions With Employees`
   - `Decrease Increase Through Tax On Sharebased Payment Transactions`
   - `Provisions For Sales Rebates`
   - `Discount Rate Applied To Cash Flow Projections Pre Tax`

## Filtering Strategy

### Approach 1: Pattern-Based Exclusion (Recommended)
Filter out items based on keywords that indicate they belong in footnotes/notes rather than the main statement:

**Exclude patterns:**
- Contains: `adjustment`, `reconciliation`, `reconcile` (unless it's a main subtotal)
- Contains: `tax_rate`, `effective_tax_rate`, `statutory_tax_rate`, `applicable_tax_rate`
- Contains: `paid`, `received`, `classified_as` (cash flow classifications)
- Contains: `percentage`, `percent`, `ratio`, `growth_percent`
- Contains: `breakdown`, `detail`, `component`
- Contains: `employee_benefit` (unless it's a main expense category)
- Contains: `depreciation`, `amortisation`, `impairment` (unless it's a main expense category)
- Contains: `interest_paid`, `interest_received` (detailed breakdowns)
- Contains: `prior_period`, `prior_year`
- Contains: `provision`, `allowance`, `reserve`
- Contains: `discount_rate`, `rate_applied`
- Contains: `remuneration`, `fee` (detailed expense breakdowns)

**Keep patterns:**
- Main revenue items: `revenue`, `net_sales`, `sales_revenue`
- Main cost items: `cost_of_sales`, `cost_of_goods`
- Main profit items: `gross_profit`, `operating_profit`, `profit_before_tax`, `net_profit`, `net_income`
- Main expense categories: `selling_expense`, `distribution`, `research_and_development`, `administrative`
- Main financial items: `finance_income`, `finance_costs`, `financial_income`, `financial_expenses`
- Main tax items: `income_tax`, `tax_expense` (but NOT tax reconciliation items)
- EPS items: `basic_earnings_per_share`, `diluted_earnings_per_share`, `eps_basic`, `eps_diluted`

### Approach 2: Hierarchy Level Filtering
- Main statement items typically have `hierarchy_level` 1-3
- Detailed breakdowns often have `hierarchy_level` 4+
- **Issue**: Not all items have hierarchy_level populated

### Approach 3: Presentation Order Filtering
- Items with `presentation_order_index` from XBRL are more likely to be main statement items
- Items without presentation order might be detailed breakdowns
- **Issue**: Not all items have presentation_order_index

### Recommended: Hybrid Approach
1. **Primary**: Pattern-based exclusion (most reliable)
2. **Secondary**: Hierarchy level check (if hierarchy_level > 3, likely a detail)
3. **Tertiary**: Presentation order check (if no presentation_order_index AND no hierarchy_level, might be a detail)

## Current Implementation

### Filtering Strategy (Implemented)

**Approach: XBRL Role URI Pattern Matching (Universal)**
- Uses XBRL `role_uri` patterns to identify main statement items
- Filters out `detail`, `disclosure`, `reconciliation`, `segment`, `tax`, `cover` roles
- Prioritizes main statement roles (e.g., `Incomestatement`, `Balancesheet`, `Statementofcashflows`)
- Works for all companies (not company-specific)

**Implementation Location:**
- `src/utils/populate_statement_items.py`: `is_main_statement_item()` function
- Filters items during ETL, stores only main items in `rel_statement_items`
- Statement-specific fact tables (`fact_income_statement`, etc.) contain only main items

### Ordering Strategy (Implemented)

**Approach: Standard IFRS/US-GAAP Structure (Universal)**
- Income Statement: Uses XBRL `presentation_order_index` with special handling for EPS items
- Comprehensive Income: Uses `compute_comprehensive_income_order()` function with standard IFRS structure
- Balance Sheet: Uses XBRL `presentation_order_index` (to be enhanced for left/right side separation)
- Works for all companies (not company-specific)

**Implementation Location:**
- `src/utils/populate_statement_items.py`: `compute_display_order()` and `compute_comprehensive_income_order()` functions
- Stores `display_order` in `rel_statement_items` and statement-specific fact tables

### Label Humanization (Implemented)

**Approach: Generic Concept-to-Label Mapping (Universal)**
- Uses `concept_label_mapping.py` with IFRS/US-GAAP standard terminology
- Stores `preferred_label` in `dim_concepts` during ETL (lasting solution)
- API returns `preferred_label` from database
- Frontend uses `preferred_label` with fallback to runtime humanization

**Implementation Location:**
- `src/utils/concept_label_mapping.py`: `get_humanized_label()` function
- `database/load_financial_data.py`: Populates `preferred_label` in `get_or_create_concept()`
- `api/main.py`: Returns `preferred_label` in API response
- `Website/portfolio/app/finsight/FinancialStatements.tsx`: Uses `preferred_label` from API

### Sign Corrections (Implemented)

**Approach: Universal IFRS/US-GAAP Rules**
- Reclassification adjustments: reverse sign (universal IFRS/US-GAAP rule)
- Tax items in OCI: reverse sign (universal IFRS/US-GAAP rule)
- Applied during ETL in `populate_statement_facts.py`

**Implementation Location:**
- `src/utils/populate_statement_facts.py`: Sign correction logic in comprehensive income INSERT query

## Results

### Income Statement (✅ Complete)
- All main items present (16 items for Novo)
- Correct ordering
- Standard accounting terminology
- No extra detail items

### Comprehensive Income (✅ Complete)
- All main items present (13 items for Novo, including headers)
- Correct ordering (standard IFRS structure)
- Standard accounting terminology
- Correct signs (universal IFRS/US-GAAP rules applied)

### Balance Sheet (⚠️ In Progress)
- Need to implement left/right side separation
- Need to ensure main items only (not more, not less)
- Universal solution required (not company-specific)

## Next Steps

1. **Balance Sheet Organization**
   - Separate left side (Assets) and right side (Equity and Liabilities)
   - Ensure main items only (not more, not less)
   - Universal solution based on XBRL role_uri and presentation hierarchy

2. **Cash Flow Statement**
   - Verify main items only
   - Ensure correct ordering
   - Standard accounting terminology
