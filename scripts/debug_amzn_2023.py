#!/usr/bin/env python3
"""
Debug script for Amazon 2023 Retained Earnings discrepancy
Analyzes the actual SEC filing data from our database
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from config import DATABASE_URI
from datetime import datetime

engine = create_engine(DATABASE_URI)

print("=" * 100)
print("AMAZON 2023 RETAINED EARNINGS - COMPLETE ANALYSIS")
print("Analyzing actual SEC filing data from database")
print("=" * 100)

# 1. Get beginning and ending retained earnings
print("\n" + "=" * 100)
print("1. RETAINED EARNINGS VALUES")
print("=" * 100)

query1 = text("""
    SELECT 
        t.fiscal_year,
        t.period_type,
        dc.normalized_label,
        dc.concept_name,
        f.value_numeric,
        fl.filing_type,
        fl.filing_date
    FROM fact_financial_metrics f
    JOIN dim_companies c ON f.company_id = c.company_id
    JOIN dim_concepts dc ON f.concept_id = dc.concept_id
    JOIN dim_time_periods t ON f.period_id = t.period_id
    JOIN dim_filings fl ON f.filing_id = fl.filing_id
    WHERE f.dimension_id IS NULL
      AND f.value_numeric IS NOT NULL
      AND c.ticker = 'AMZN'
      AND t.fiscal_year IN (2022, 2023)
      AND t.period_type = 'instant'
      AND dc.normalized_label = 'retained_earnings'
    ORDER BY t.fiscal_year, fl.filing_date DESC;
""")

result1 = engine.connect().execute(query1)
re_data = {}
for row in result1:
    year = row[0]
    label = row[2]
    concept = row[3]
    value = row[4]
    filing_type = row[5]
    filing_date = row[6]
    
    if year not in re_data:
        re_data[year] = []
    re_data[year].append({
        'value': value,
        'concept': concept,
        'filing_type': filing_type,
        'filing_date': filing_date
    })

for year in sorted(re_data.keys()):
    print(f"\n{year} Retained Earnings:")
    for item in re_data[year]:
        print(f"  ${item['value']:>15,.0f} | {item['concept']:<60} | {item['filing_type']} | {item['filing_date']}")

beg_re = re_data[2022][0]['value'] if 2022 in re_data else None
end_re = re_data[2023][0]['value'] if 2023 in re_data else None

if beg_re and end_re:
    change = end_re - beg_re
    print(f"\n  Beginning RE (2022): ${beg_re:,.0f}")
    print(f"  Ending RE (2023): ${end_re:,.0f}")
    print(f"  Change: ${change:,.0f}")

# 2. Get ALL net income concepts for 2023
print("\n" + "=" * 100)
print("2. ALL NET INCOME CONCEPTS FOR 2023")
print("=" * 100)

query2 = text("""
    SELECT 
        dc.normalized_label,
        dc.concept_name,
        f.value_numeric,
        f.dimension_id,
        t.period_type
    FROM fact_financial_metrics f
    JOIN dim_companies c ON f.company_id = c.company_id
    JOIN dim_concepts dc ON f.concept_id = dc.concept_id
    JOIN dim_time_periods t ON f.period_id = t.period_id
    WHERE f.value_numeric IS NOT NULL
      AND c.ticker = 'AMZN'
      AND t.fiscal_year = 2023
      AND t.period_type = 'duration'
      AND (
          dc.concept_name LIKE '%NetIncome%'
          OR dc.concept_name LIKE '%ProfitLoss%'
          OR dc.concept_name LIKE '%IncomeLoss%'
          OR dc.normalized_label LIKE '%net_income%'
          OR dc.normalized_label LIKE '%profit_loss%'
      )
    ORDER BY ABS(f.value_numeric) DESC;
""")

result2 = engine.connect().execute(query2)
print("\nAll Income/Profit/Loss Concepts (2023, duration):")
print("-" * 100)
for row in result2:
    dim_str = f"Dim: {row[3]}" if row[3] else "No Dim"
    print(f"  {row[0]:<40} | {row[1]:<50} | ${row[2]:>15,.0f} | {dim_str}")

# 3. Get Statement of Changes in Equity components
print("\n" + "=" * 100)
print("3. STATEMENT OF CHANGES IN EQUITY COMPONENTS")
print("=" * 100)

query3 = text("""
    SELECT 
        dc.normalized_label,
        dc.concept_name,
        f.value_numeric,
        f.dimension_id
    FROM fact_financial_metrics f
    JOIN dim_companies c ON f.company_id = c.company_id
    JOIN dim_concepts dc ON f.concept_id = dc.concept_id
    JOIN dim_time_periods t ON f.period_id = t.period_id
    WHERE f.value_numeric IS NOT NULL
      AND c.ticker = 'AMZN'
      AND t.fiscal_year = 2023
      AND t.period_type = 'duration'
      AND (
          -- Statement of Changes in Equity concepts
          dc.concept_name LIKE '%RetainedEarnings%'
          OR dc.concept_name LIKE '%BeginningBalance%'
          OR dc.concept_name LIKE '%EndingBalance%'
          OR dc.concept_name LIKE '%NetIncomeLoss%'
          OR dc.concept_name LIKE '%Dividends%'
          OR dc.concept_name LIKE '%Stock%'
          OR dc.concept_name LIKE '%Equity%'
          OR dc.concept_name LIKE '%Adjustment%'
          OR dc.concept_name LIKE '%Translation%'
          OR dc.concept_name LIKE '%ComprehensiveIncome%'
          OR dc.concept_name LIKE '%OCI%'
          OR dc.concept_name LIKE '%AOCI%'
          OR dc.normalized_label LIKE '%retained%'
          OR dc.normalized_label LIKE '%dividend%'
          OR dc.normalized_label LIKE '%stock%'
          OR dc.normalized_label LIKE '%equity%'
          OR dc.normalized_label LIKE '%adjustment%'
          OR dc.normalized_label LIKE '%translation%'
          OR dc.normalized_label LIKE '%comprehensive%income%'
          OR dc.normalized_label LIKE '%oci%'
      )
      AND ABS(f.value_numeric) > 1000000  -- > $1M
    ORDER BY ABS(f.value_numeric) DESC
    LIMIT 50;
""")

result3 = engine.connect().execute(query3)
print("\nStatement of Changes in Equity Components (>$1M):")
print("-" * 100)
equity_components = {}
for row in result3:
    label = row[0]
    concept = row[1]
    value = row[2]
    dim_id = row[3]
    
    dim_str = f"Dim: {dim_id}" if dim_id else "No Dim"
    print(f"  {label:<50} | {concept:<60} | ${value:>15,.0f} | {dim_str}")
    
    # Group by category
    if 'net_income' in label.lower() or 'NetIncome' in concept:
        if 'net_income' not in equity_components:
            equity_components['net_income'] = []
        equity_components['net_income'].append(value)
    elif 'dividend' in label.lower() or 'Dividend' in concept:
        if 'dividends' not in equity_components:
            equity_components['dividends'] = []
        equity_components['dividends'].append(value)
    elif 'stock' in label.lower() and ('repurchas' in label.lower() or 'repurchas' in concept.lower()):
        if 'stock_repurchased' not in equity_components:
            equity_components['stock_repurchased'] = []
        equity_components['stock_repurchased'].append(value)
    elif 'stock' in label.lower() and ('issued' in label.lower() or 'issued' in concept.lower()):
        if 'stock_issued' not in equity_components:
            equity_components['stock_issued'] = []
        equity_components['stock_issued'].append(value)
    elif 'comprehensive' in label.lower() or 'OCI' in concept or 'AOCI' in concept:
        if 'oci' not in equity_components:
            equity_components['oci'] = []
        equity_components['oci'].append(value)

# 4. Calculate the rollforward
print("\n" + "=" * 100)
print("4. RETAINED EARNINGS ROLLFORWARD CALCULATION")
print("=" * 100)

if beg_re and end_re:
    # Get net income (prefer non-dimensioned, then use MAX)
    net_income_query = text("""
        SELECT 
            MAX(CASE WHEN f.dimension_id IS NULL 
                THEN f.value_numeric ELSE NULL END) as net_income_no_dim,
            MAX(f.value_numeric) as net_income_max
        FROM fact_financial_metrics f
        JOIN dim_companies c ON f.company_id = c.company_id
        JOIN dim_concepts dc ON f.concept_id = dc.concept_id
        JOIN dim_time_periods t ON f.period_id = t.period_id
        WHERE f.value_numeric IS NOT NULL
          AND c.ticker = 'AMZN'
          AND t.fiscal_year = 2023
          AND t.period_type = 'duration'
          AND dc.normalized_label IN ('net_income', 'net_income_loss', 'profit_loss');
    """)
    
    ni_result = engine.connect().execute(net_income_query)
    ni_row = ni_result.fetchone()
    net_income = ni_row[0] if ni_row[0] else ni_row[1]
    
    # Get dividends
    dividends_query = text("""
        SELECT 
            MAX(f.value_numeric) as dividends
        FROM fact_financial_metrics f
        JOIN dim_companies c ON f.company_id = c.company_id
        JOIN dim_concepts dc ON f.concept_id = dc.concept_id
        JOIN dim_time_periods t ON f.period_id = t.period_id
        WHERE f.value_numeric IS NOT NULL
          AND c.ticker = 'AMZN'
          AND t.fiscal_year = 2023
          AND t.period_type = 'duration'
          AND dc.normalized_label LIKE '%dividend%'
          AND dc.normalized_label LIKE '%paid%';
    """)
    
    div_result = engine.connect().execute(dividends_query)
    dividends = div_result.fetchone()[0] or 0
    
    print(f"\nBasic Rollforward:")
    print(f"  Beginning RE (2022): ${beg_re:,.0f}")
    net_income_str = f"${net_income:,.0f}" if net_income else "NULL"
    print(f"  Net Income (from DB): {net_income_str}")
    print(f"  Dividends: ${dividends:,.0f}")
    
    if net_income:
        basic_expected = beg_re + net_income - dividends
        print(f"  Expected (Basic): ${basic_expected:,.0f}")
        print(f"  Actual Ending RE: ${end_re:,.0f}")
        difference = end_re - basic_expected
        print(f"  Difference: ${difference:,.0f} ({abs(difference)/end_re*100:.1f}%)")
        
        # Check if net income matches the change
        if abs(net_income - change) < 1000000000:  # Within $1B
            print(f"\n  ✅ NET INCOME MATCHES RE CHANGE!")
            print(f"     Net Income: ${net_income:,.0f}")
            print(f"     RE Change: ${change:,.0f}")
            print(f"     Difference: ${abs(net_income - change):,.0f}")
        else:
            print(f"\n  ❌ NET INCOME DOES NOT MATCH RE CHANGE")
            print(f"     Net Income: ${net_income:,.0f}")
            print(f"     RE Change: ${change:,.0f}")
            print(f"     Missing: ${change - net_income:,.0f}")

# 5. Get all adjustments we're currently capturing
print("\n" + "=" * 100)
print("5. CURRENT ADJUSTMENTS EXTRACTION (FROM VALIDATOR)")
print("=" * 100)

query4 = text("""
    WITH re_adjustments AS (
        SELECT 
            c.ticker,
            t.fiscal_year,
            MAX(CASE WHEN dc.normalized_label LIKE '%reclassification%from%aoci%'
                THEN f.value_numeric ELSE NULL END) as reclassifications_from_aoci,
            COALESCE(
                MAX(CASE WHEN dc.normalized_label LIKE '%stock%based%compensation%' 
                       AND (dc.normalized_label LIKE '%retained%' OR dc.normalized_label LIKE '%equity%adjustment%')
                    THEN f.value_numeric ELSE NULL END),
                MAX(CASE WHEN dc.normalized_label LIKE '%stock%based%compensation%tax%benefit%'
                       OR dc.normalized_label LIKE '%share%based%compensation%tax%benefit%'
                       OR dc.concept_name LIKE '%EmployeeServiceShareBasedCompensationTaxBenefit%'
                       OR dc.concept_name LIKE '%ShareBasedCompensationTaxBenefit%'
                    THEN f.value_numeric ELSE NULL END)
            ) as sbc_adjustments,
            COALESCE(
                MAX(CASE WHEN dc.normalized_label = 'treasury_stock_retired_cost_method_amount'
                    THEN f.value_numeric ELSE NULL END),
                MAX(CASE WHEN dc.normalized_label = 'stock_repurchased_value'
                    THEN f.value_numeric ELSE NULL END),
                MAX(CASE WHEN dc.normalized_label = 'stock_repurchased'
                    THEN f.value_numeric ELSE NULL END)
            ) as treasury_stock_retirement,
            MAX(CASE WHEN (dc.normalized_label LIKE '%pension%' OR dc.normalized_label LIKE '%postretirement%')
                   AND (dc.normalized_label LIKE '%adjustment%' OR dc.normalized_label LIKE '%equity%')
                   AND dc.normalized_label NOT LIKE '%oci%'
                   AND dc.normalized_label NOT LIKE '%comprehensive%income%'
                THEN f.value_numeric ELSE NULL END) as pension_adjustments,
            MAX(CASE WHEN (dc.normalized_label LIKE '%foreign%currency%translation%' 
                           OR dc.normalized_label LIKE '%fx%translation%')
                   AND dc.normalized_label NOT LIKE '%oci%'
                   AND dc.normalized_label NOT LIKE '%comprehensive%income%'
                   AND dc.normalized_label NOT LIKE '%aoci%'
                THEN f.value_numeric ELSE NULL END) as fx_translation_adjustments,
            MAX(CASE WHEN (
                dc.normalized_label LIKE '%equity%adjustment%' 
                OR (dc.normalized_label LIKE '%tax%benefit%' AND dc.normalized_label NOT LIKE '%stock%based%compensation%')
                OR (dc.normalized_label LIKE '%tax%credit%' AND dc.normalized_label NOT LIKE '%reconciliation%')
                OR (dc.normalized_label LIKE '%unrecognized%tax%benefit%' AND dc.normalized_label LIKE '%increase%')
                OR dc.normalized_label LIKE '%goodwill%translation%'
                OR dc.normalized_label LIKE '%fair_value%adjustment%warrant%'
            )
                   AND dc.normalized_label NOT LIKE '%stock%based%compensation%'
                   AND dc.normalized_label NOT LIKE '%oci%'
                   AND dc.normalized_label NOT LIKE '%comprehensive%income%'
                   AND dc.normalized_label NOT LIKE '%pension%'
                   AND dc.normalized_label NOT LIKE '%foreign%currency%'
                   AND dc.normalized_label NOT LIKE '%fx%'
                THEN f.value_numeric ELSE NULL END) as other_equity_adjustments
        FROM fact_financial_metrics f
        JOIN dim_companies c ON f.company_id = c.company_id
        JOIN dim_concepts dc ON f.concept_id = dc.concept_id
        JOIN dim_time_periods t ON f.period_id = t.period_id
        WHERE f.dimension_id IS NULL
          AND f.value_numeric IS NOT NULL
          AND t.period_type = 'duration'
          AND t.fiscal_year = 2023
          AND c.ticker = 'AMZN'
          AND (
              dc.normalized_label LIKE '%reclassification%from%aoci%'
              OR (dc.normalized_label LIKE '%stock%based%compensation%' 
                  AND (dc.normalized_label LIKE '%retained%' OR dc.normalized_label LIKE '%equity%adjustment%'))
              OR dc.normalized_label LIKE '%stock%based%compensation%tax%benefit%'
              OR dc.normalized_label LIKE '%share%based%compensation%tax%benefit%'
              OR dc.concept_name LIKE '%EmployeeServiceShareBasedCompensationTaxBenefit%'
              OR dc.concept_name LIKE '%ShareBasedCompensationTaxBenefit%'
              OR dc.normalized_label IN ('treasury_stock_retired_cost_method_amount', 'stock_repurchased_value', 'stock_repurchased')
              OR ((dc.normalized_label LIKE '%pension%' OR dc.normalized_label LIKE '%postretirement%')
                  AND (dc.normalized_label LIKE '%adjustment%' OR dc.normalized_label LIKE '%equity%')
                  AND dc.normalized_label NOT LIKE '%oci%')
              OR ((dc.normalized_label LIKE '%foreign%currency%translation%' 
                   OR dc.normalized_label LIKE '%fx%translation%')
                  AND dc.normalized_label NOT LIKE '%oci%'
                  AND dc.normalized_label NOT LIKE '%comprehensive%income%'
                  AND dc.normalized_label NOT LIKE '%aoci%')
              OR (dc.normalized_label LIKE '%equity%adjustment%' 
                  AND dc.normalized_label NOT LIKE '%stock%based%compensation%'
                  AND dc.normalized_label NOT LIKE '%oci%'
                  AND dc.normalized_label NOT LIKE '%comprehensive%income%'
                  AND dc.normalized_label NOT LIKE '%pension%'
                  AND dc.normalized_label NOT LIKE '%foreign%currency%'
                  AND dc.normalized_label NOT LIKE '%fx%')
              OR (dc.normalized_label LIKE '%tax%benefit%' 
                  AND dc.normalized_label NOT LIKE '%stock%based%compensation%'
                  AND dc.normalized_label NOT LIKE '%reconciliation%')
              OR (dc.normalized_label LIKE '%tax%credit%' 
                  AND dc.normalized_label NOT LIKE '%reconciliation%')
              OR (dc.normalized_label LIKE '%unrecognized%tax%benefit%' 
                  AND dc.normalized_label LIKE '%increase%')
              OR dc.normalized_label LIKE '%goodwill%translation%'
              OR dc.normalized_label LIKE '%fair_value%adjustment%warrant%'
          )
        GROUP BY c.ticker, t.fiscal_year
    )
    SELECT 
        ticker,
        fiscal_year,
        COALESCE(reclassifications_from_aoci, 0) as reclassifications,
        COALESCE(sbc_adjustments, 0) as sbc_adjustments,
        COALESCE(treasury_stock_retirement, 0) as treasury_stock,
        COALESCE(pension_adjustments, 0) as pension,
        COALESCE(fx_translation_adjustments, 0) as fx_translation,
        COALESCE(other_equity_adjustments, 0) as other_equity,
        COALESCE(reclassifications_from_aoci, 0) + 
        COALESCE(sbc_adjustments, 0) - 
        COALESCE(treasury_stock_retirement, 0) + 
        COALESCE(pension_adjustments, 0) + 
        COALESCE(fx_translation_adjustments, 0) + 
        COALESCE(other_equity_adjustments, 0) as total_adjustments
    FROM re_adjustments;
""")

result4 = engine.connect().execute(query4)
print("\nCurrent Validator Adjustments:")
print("-" * 100)
for row in result4:
    print(f"  Reclassifications: ${row[2]:>15,.0f}")
    print(f"  SBC Adjustments: ${row[3]:>15,.0f}")
    print(f"  Treasury Stock (subtracted): ${row[4]:>15,.0f}")
    print(f"  Pension: ${row[5]:>15,.0f}")
    print(f"  FX Translation: ${row[6]:>15,.0f}")
    print(f"  Other Equity: ${row[7]:>15,.0f}")
    print(f"  Total Net Adjustments: ${row[8]:>15,.0f}")

# 6. Final summary
print("\n" + "=" * 100)
print("6. FINAL SUMMARY & RECOMMENDATION")
print("=" * 100)

if beg_re and end_re and net_income:
    change = end_re - beg_re
    basic_expected = beg_re + net_income - dividends
    difference = end_re - basic_expected
    total_adjustments = row[8] if row else 0
    
    print(f"\nRetained Earnings Rollforward:")
    print(f"  Beginning RE: ${beg_re:,.0f}")
    print(f"  Net Income (DB): ${net_income:,.0f}")
    print(f"  Dividends: ${dividends:,.0f}")
    print(f"  Expected (Basic): ${basic_expected:,.0f}")
    print(f"  Actual Ending RE: ${end_re:,.0f}")
    print(f"  Difference: ${difference:,.0f} ({abs(difference)/end_re*100:.1f}%)")
    print(f"\n  Current Adjustments Captured: ${total_adjustments:,.0f}")
    print(f"  Still Missing: ${difference - total_adjustments:,.0f}")
    
    print(f"\n  RE Change (2022→2023): ${change:,.0f}")
    print(f"  Net Income (DB): ${net_income:,.0f}")
    if abs(net_income - change) < 1000000000:
        print(f"  ✅ Net Income matches RE change - no adjustments needed!")
    else:
        print(f"  ❌ Net Income does NOT match RE change")
        print(f"     Missing: ${change - net_income:,.0f}")
        print(f"\n  RECOMMENDATION:")
        print(f"     Check if we're using the wrong net income concept")
        print(f"     Look for dimensioned net income values")
        print(f"     Or check if net income needs to be calculated differently")

print("\n" + "=" * 100)
print("ANALYSIS COMPLETE")
print("=" * 100)

