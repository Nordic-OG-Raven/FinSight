#!/usr/bin/env python3
"""
Debug script for remaining Retained Earnings errors
Analyzes each error company to find missing adjustments
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from config import DATABASE_URI
import json

engine = create_engine(DATABASE_URI)

# Error companies to investigate
errors = [
    ('MRNA', 2023),
    ('GOOGL', 2024),
    ('NVDA', 2024),
    ('WMT', 2023),
    ('ASML', 2023),
    ('LLY', 2023),
]

print("=" * 100)
print("RETAINED EARNINGS ERROR INVESTIGATION")
print("Big 4/Hedge Fund Approach - Find Missing Adjustments")
print("=" * 100)

for ticker, year in errors:
    print(f"\n{'='*100}")
    print(f"COMPANY: {ticker} {year}")
    print(f"{'='*100}")
    
    # Get RE values
    query_re = text("""
        SELECT 
            MAX(CASE WHEN t.fiscal_year = :year AND t.period_type = 'instant'
                THEN f.value_numeric END) as ending_re,
            MAX(CASE WHEN t.fiscal_year = :year - 1 AND t.period_type = 'instant'
                THEN f.value_numeric END) as beginning_re
        FROM fact_financial_metrics f
        JOIN dim_companies c ON f.company_id = c.company_id
        JOIN dim_concepts dc ON f.concept_id = dc.concept_id
        JOIN dim_time_periods t ON f.period_id = t.period_id
        WHERE f.dimension_id IS NULL
          AND f.value_numeric IS NOT NULL
          AND c.ticker = :ticker
          AND t.fiscal_year IN (:year - 1, :year)
          AND dc.normalized_label = 'retained_earnings'
    """)
    
    result_re = engine.connect().execute(query_re, {'ticker': ticker, 'year': year})
    re_row = result_re.fetchone()
    if not re_row or not re_row[0] or not re_row[1]:
        print(f"  ⚠️ No RE data found")
        continue
    
    ending_re = re_row[0]
    beginning_re = re_row[1]
    re_change = ending_re - beginning_re
    
    print(f"\n  Retained Earnings:")
    print(f"    Beginning RE ({year-1}): ${beginning_re:,.0f}")
    print(f"    Ending RE ({year}): ${ending_re:,.0f}")
    print(f"    Change: ${re_change:,.0f}")
    
    # Get net income (from RE change)
    query_ni = text("""
        WITH re_change_net_income AS (
            SELECT 
                MAX(CASE WHEN t.fiscal_year = :year AND t.period_type = 'instant'
                    THEN f.value_numeric END) as ending_re,
                MAX(CASE WHEN t.fiscal_year = :year - 1 AND t.period_type = 'instant'
                    THEN f.value_numeric END) as beginning_re,
                MAX(CASE WHEN dc.normalized_label LIKE '%dividend%' AND dc.normalized_label LIKE '%paid%'
                    AND t.period_type = 'duration' AND t.fiscal_year = :year
                    THEN f.value_numeric ELSE NULL END) as dividends_paid
            FROM fact_financial_metrics f
            JOIN dim_companies c ON f.company_id = c.company_id
            JOIN dim_concepts dc ON f.concept_id = dc.concept_id
            JOIN dim_time_periods t ON f.period_id = t.period_id
            WHERE f.dimension_id IS NULL
              AND f.value_numeric IS NOT NULL
              AND c.ticker = :ticker
        )
        SELECT 
            ending_re - beginning_re + COALESCE(dividends_paid, 0) as net_income,
            COALESCE(dividends_paid, 0) as dividends
        FROM re_change_net_income;
    """)
    
    result_ni = engine.connect().execute(query_ni, {'ticker': ticker, 'year': year})
    ni_row = result_ni.fetchone()
    net_income = ni_row[0] if ni_row else None
    dividends = ni_row[1] if ni_row else 0
    
    ni_str = f"${net_income:,.0f}" if net_income else "NULL"
    print(f"\n  Net Income (from RE change): {ni_str}")
    print(f"  Dividends: ${dividends:,.0f}")
    
    # Expected RE
    expected_re = beginning_re + net_income - dividends
    missing = ending_re - expected_re
    
    print(f"\n  Expected RE: ${expected_re:,.0f}")
    print(f"  Actual RE: ${ending_re:,.0f}")
    print(f"  Missing: ${missing:,.0f} ({abs(missing)/ending_re*100:.1f}%)")
    
    # Get all adjustments currently captured
    query_adj = text("""
        SELECT 
            MAX(CASE WHEN dc.normalized_label LIKE '%reclassification%from%aoci%'
                THEN f.value_numeric ELSE NULL END) as reclassifications,
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
            ) as treasury_stock,
            MAX(CASE WHEN (dc.normalized_label LIKE '%pension%' OR dc.normalized_label LIKE '%postretirement%')
                   AND (dc.normalized_label LIKE '%adjustment%' OR dc.normalized_label LIKE '%equity%')
                   AND dc.normalized_label NOT LIKE '%oci%'
                   AND dc.normalized_label NOT LIKE '%comprehensive%income%'
                THEN f.value_numeric ELSE NULL END) as pension,
            MAX(CASE WHEN (dc.normalized_label LIKE '%foreign%currency%translation%' 
                           OR dc.normalized_label LIKE '%fx%translation%')
                   AND dc.normalized_label NOT LIKE '%oci%'
                   AND dc.normalized_label NOT LIKE '%comprehensive%income%'
                   AND dc.normalized_label NOT LIKE '%aoci%'
                THEN f.value_numeric ELSE NULL END) as fx_translation,
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
                THEN f.value_numeric ELSE NULL END) as other_equity
        FROM fact_financial_metrics f
        JOIN dim_companies c ON f.company_id = c.company_id
        JOIN dim_concepts dc ON f.concept_id = dc.concept_id
        JOIN dim_time_periods t ON f.period_id = t.period_id
        WHERE f.dimension_id IS NULL
          AND f.value_numeric IS NOT NULL
          AND c.ticker = :ticker
          AND t.fiscal_year = :year
          AND t.period_type = 'duration'
    """)
    
    result_adj = engine.connect().execute(query_adj, {'ticker': ticker, 'year': year})
    adj_row = result_adj.fetchone()
    
    if adj_row:
        reclass, sbc, tsr, pension, fx, other = adj_row
        total_adj = (reclass or 0) + (sbc or 0) - (tsr or 0) + (pension or 0) + (fx or 0) + (other or 0)
        
        print(f"\n  Current Adjustments Captured:")
        print(f"    Reclassifications: ${reclass or 0:>15,.0f}")
        print(f"    SBC Adjustments: ${sbc or 0:>15,.0f}")
        print(f"    Treasury Stock (subtracted): ${tsr or 0:>15,.0f}")
        print(f"    Pension: ${pension or 0:>15,.0f}")
        print(f"    FX Translation: ${fx or 0:>15,.0f}")
        print(f"    Other Equity: ${other or 0:>15,.0f}")
        print(f"    Total Net Adjustments: ${total_adj:>15,.0f}")
        
        # Calculate what's still missing
        expected_with_adj = beginning_re + net_income - dividends - (tsr or 0) + (reclass or 0) + (sbc or 0) + (pension or 0) + (fx or 0) + (other or 0)
        still_missing = ending_re - expected_with_adj
        
        print(f"\n  Expected RE (with adjustments): ${expected_with_adj:,.0f}")
        print(f"  Still Missing: ${still_missing:,.0f} ({abs(still_missing)/ending_re*100:.1f}%)")
        
        # Search for large equity-related concepts that might be missing
        print(f"\n  Searching for large equity-related adjustments (>$100M):")
        query_large = text("""
            SELECT 
                dc.normalized_label,
                dc.concept_name,
                f.value_numeric
            FROM fact_financial_metrics f
            JOIN dim_companies c ON f.company_id = c.company_id
            JOIN dim_concepts dc ON f.concept_id = dc.concept_id
            JOIN dim_time_periods t ON f.period_id = t.period_id
            WHERE f.dimension_id IS NULL
              AND f.value_numeric IS NOT NULL
              AND c.ticker = :ticker
              AND t.fiscal_year = :year
              AND t.period_type = 'duration'
              AND ABS(f.value_numeric) > 100000000  -- > $100M
              AND (
                  dc.concept_name LIKE '%Equity%'
                  OR dc.concept_name LIKE '%Stock%'
                  OR dc.concept_name LIKE '%Capital%'
                  OR dc.concept_name LIKE '%Adjustment%'
                  OR dc.normalized_label LIKE '%equity%'
                  OR dc.normalized_label LIKE '%stock%'
                  OR dc.normalized_label LIKE '%capital%'
                  OR dc.normalized_label LIKE '%adjustment%'
              )
              AND dc.normalized_label NOT LIKE '%oci%'
              AND dc.normalized_label NOT LIKE '%comprehensive%income%'
              AND dc.normalized_label NOT LIKE '%retained%earnings%'
              AND dc.normalized_label NOT IN (
                  'reclassifications_from_aoci',
                  'stock_repurchased',
                  'treasury_stock_retired_cost_method_amount',
                  'stock_repurchased_value'
              )
            ORDER BY ABS(f.value_numeric) DESC
            LIMIT 20;
        """)
        
        result_large = engine.connect().execute(query_large, {'ticker': ticker, 'year': year})
        print(f"    {'Label':<50} | {'Concept':<50} | {'Value':>15}")
        print(f"    {'-'*50} | {'-'*50} | {'-'*15}")
        found_potential = False
        for row in result_large:
            found_potential = True
            print(f"    {row[0]:<50} | {row[1]:<50} | ${row[2]:>15,.0f}")
        
        if not found_potential:
            print(f"    ⚠️ No large equity adjustments found")
            print(f"    This suggests the missing amount may be:")
            print(f"      - A major equity transaction (merger/acquisition)")
            print(f"      - A data quality issue in the source filing")
            print(f"      - An adjustment not captured in XBRL taxonomy")

print("\n" + "="*100)
print("INVESTIGATION COMPLETE")
print("="*100)

