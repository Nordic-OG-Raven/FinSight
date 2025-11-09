# Financial Statement Structure Analysis

## 1. Structure of "Income Statement and Statement of Comprehensive Income"

### Overall Layout
- **Two-Table Side-by-Side Format**: The page presents two financial statements side-by-side:
  - **Left Table**: "Income statement"
  - **Right Table**: "Statement of comprehensive income"
- **Shared Column Headers**: Both tables share the same columns: "Note", "2024", "2023", "2022"
- **Unit Display**: "DKK million" is stated above both tables

### Income Statement Structure (Left Table)

**Flow of Items:**
1. **Revenue Section**
   - Net sales
   - Cost of goods sold (negative, in parentheses)
   - **→ Gross profit** (subtotal, bold)

2. **Operating Expenses Section**
   - Sales and distribution costs
   - Research and development costs
   - Administrative costs
   - Other operating income and expenses
   - **→ Operating profit** (subtotal, bold)

3. **Financial Items Section**
   - Financial income
   - Financial expenses
   - **→ Profit before income taxes** (subtotal, bold)

4. **Tax and Net Profit Section**
   - Income taxes (negative, in parentheses)
   - **→ Net profit** (subtotal, bold)

5. **Earnings Per Share Section** (separate sub-section, bold heading)
   - Basic earnings per share (DKK)
   - Diluted earnings per share (DKK)

### Statement of Comprehensive Income Structure (Right Table)

**Flow of Items:**
1. **Starting Point**
   - Net profit (matches Income Statement)

2. **Other Comprehensive Income (OCI) Section** (bold sub-heading)
   - **Items that will NOT be reclassified:**
     - Remeasurements of retirement benefit obligations
     - **→ Subtotal: "Items that will not be reclassified subsequently to the income statement"**
   
   - **Items that WILL be reclassified:**
     - Exchange rate adjustments of investments in subsidiaries
     - **Cash flow hedges:** (sub-category)
       - Realisation of previously deferred (gains)/losses
       - Deferred gains/(losses) related to acquisition of businesses
       - Deferred gains/(losses) on hedges open at year-end
     - Tax and other items
     - **→ Subtotal: "Items that will be reclassified subsequently to the income statement"**
   
   - **→ Other comprehensive income** (total, bold, double line)

3. **Final Total**
   - **→ Total comprehensive income** (bold, double line)

## 2. Commonality and Alternative Structures

### This Structure: Combined Statement Approach
- **Name**: "Statement of Profit or Loss and Other Comprehensive Income" (single statement approach)
- **Standards**: Common under **IFRS** (International Financial Reporting Standards)
- **Layout**: Income Statement and Comprehensive Income presented together in one document
- **Usage**: Very common for IFRS-compliant companies (e.g., Novo Nordisk, European companies)

### Alternative Structure 1: Two-Statement Approach
- **Name**: Separate "Income Statement" and "Statement of Comprehensive Income"
- **Layout**: 
  - First statement: Income Statement (ends with Net Profit)
  - Second statement: Statement of Comprehensive Income (starts with Net Profit from first statement)
- **Standards**: Also permitted under IFRS and US GAAP
- **Usage**: Common in US GAAP filings, some IFRS companies prefer this for clarity

### Alternative Structure 2: US GAAP Comprehensive Income Statement
- **Name**: "Comprehensive Income Statement" or "Statement of Comprehensive Income"
- **Layout**: Similar to IFRS but may have different OCI categorizations
- **Standards**: US GAAP
- **Usage**: Common for US companies

### Key Differences:
- **IFRS**: Often uses combined statement (as shown in image)
- **US GAAP**: More commonly uses two-statement approach
- **Both standards allow either approach** - it's a presentation choice

## 3. Visual Presentation: Lines Underneath Items

### Current FinSight Implementation
- **Problem**: Every row currently has a line underneath (using `divide-y` Tailwind class)
- **Desired**: Match professional financial statement presentation

### Professional Presentation Rules (Based on Image Analysis)

#### **NO Lines Underneath** (Most Individual Items)
Lines should **NOT** appear under:
- Individual revenue items (e.g., "Net sales")
- Individual expense items (e.g., "Sales and distribution costs", "Research and development costs", "Administrative costs")
- Individual financial items (e.g., "Financial income")
- Individual OCI items (e.g., "Exchange rate adjustments...", "Realisation of previously deferred...")
- Detail items within sub-categories

#### **Single Line Underneath** (Before Subtotals/Totals)
A **single horizontal line** should appear under items that are immediately followed by a subtotal or total:
- Under "Cost of goods sold" (before "Gross profit")
- Under "Other operating income and expenses" (before "Operating profit")
- Under "Financial expenses" (before "Profit before income taxes")
- Under "Income taxes" (before "Net profit")
- Under "Net profit" in Income Statement (before "Earnings per share" section)
- Under "Diluted earnings per share" (at bottom of Income Statement)
- Under "Remeasurements of retirement benefit obligations" (before OCI subtotal)
- Under "Items that will not be reclassified..." (before next OCI section)
- Under "Tax and other items" (before OCI reclassified subtotal)
- Under "Items that will be reclassified..." (before "Other comprehensive income" total)

#### **Double Line Underneath** (Before Final Totals)
A **double horizontal line** should appear under:
- "Other comprehensive income" (before "Total comprehensive income")
- "Total comprehensive income" (at the very bottom of the statement)

### Implementation Logic

**Rule**: Lines appear only when:
1. The item is a **subtotal or total** (hierarchy_level >= 3, or marked as `isTotal`)
2. OR the item is immediately **followed by** a subtotal/total in the next row

**CSS Classes Needed**:
- Default rows: No border-bottom
- Rows before subtotals: `border-b border-gray-300` (single line)
- Rows before final totals: `border-b-2 border-gray-400` (double line)
- Subtotal/total rows themselves: `border-b-2 border-gray-400` (double line for emphasis)

### Visual Hierarchy Summary

```
Individual Items (no line)
  - Net sales
  - Sales and distribution costs
  - Research and development costs
  ──────────────────────────────── (single line)
Subtotal (bold, gray background, has line)
  - Gross profit
  ──────────────────────────────── (single line)
Individual Items (no line)
  - Financial income
  ──────────────────────────────── (single line)
Subtotal (bold, gray background, has line)
  - Operating profit
  ════════════════════════════════ (double line)
Final Total (bold, gray background, double line)
  - Total comprehensive income
```

