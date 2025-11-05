#!/usr/bin/env python3
"""
Big 4/Hedge Fund Approach: Investigate remaining RE errors
Analyze Statement of Changes in Equity for each error company
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from config import DATABASE_URI

engine = create_engine(DATABASE_URI)

errors = [
    ('GOOGL', 2024, 41727000000),  # $41.7B
    ('MRNA', 2023, 3041000000),    # $3.0B
    ('NVDA', 2024, 9084000000),    # $9.1B
    ('WMT', 2023, 10595000000),    # $10.6B
    ('ASML', 2023, 1454000000),    # $1.5B
    ('LLY', 2023, 1095300000),     # $1.1B
]

print("=" * 100)
print("BIG 4/HEDGE FUND APPROACH: RETAINED EARNINGS ERROR INVESTIGATION")
print("Analyzing Statement of Changes in Equity for missing adjustments")
print("=" * 100)

for ticker, year, missing_amount in errors:
    print(f"\n{'='*100}")
    print(f"{ticker} {year} - Missing: ${missing_amount:,.0f}")
    print(f"{'='*100}")
    
    # Get RE values and net income from RE change
    query_re = text("""
        SELECT 
            MAX(CASE WHEN t.fiscal_year = :year AND t.period_type = 'instant'
                THEN f.value_numeric END) as ending_re,
            MAX(CASE WHEN t.fiscal_year = :year - 1 AND t.period_type = 'instant'
                THEN f.value_numeric END) as beginning_re,
            MAX(CASE WHEN dc.normalized_label LIKE '%dividend%' AND dc.normalized_label LIKE '%paid%'
                AND t.period_type = 'duration' AND t.fiscal_year = :year
                THEN f.value_numeric ELSE NULL END) as dividends
        FROM fact_financial_metrics f
        JOIN dim_companies c ON f.company_id = c.company_id
        JOIN dim_concepts dc ON f.concept_id = dc.concept_id
        JOIN dim_time_periods t ON f.period_id = t.period_id
        WHERE f.dimension_id IS NULL
          AND f.value_numeric IS NOT NULL
          AND c.ticker = :ticker
          AND ((t.fiscal_year = :year AND t.period_type = 'instant' AND dc.normalized_label = 'retained_earnings')
               OR (t.fiscal_year = :year AND t.period_type = 'duration' AND dc.normalized_label LIKE '%dividend%' AND dc.normalized_label LIKE '%paid%')
               OR (t.fiscal_year = :year - 1 AND t.period_type = 'instant' AND dc.normalized_label = 'retained_earnings'))
    """)
    
    result_re = engine.connect().execute(query_re, {'ticker': ticker, 'year': year})
    row = result_re.fetchone()
    
    if not row or not row[0] or not row[1]:
        print(f"  ⚠️ No RE data")
        continue
    
    ending_re, beginning_re, dividends = row[0], row[1], row[2] or 0
    net_income_from_re = ending_re - beginning_re + dividends
    
    print(f"\n  RE Values:")
    print(f"    Beginning RE: ${beginning_re:,.0f}")
    print(f"    Ending RE: ${ending_re:,.0f}")
    print(f"    Net Income (from RE): ${net_income_from_re:,.0f}")
    print(f"    Dividends: ${dividends:,.0f}")
    
    # Get all equity-related concepts (Statement of Changes in Equity)
    query_equity = text("""
        SELECT 
            dc.normalized_label,
            dc.concept_name,
            f.value_numeric,
            t.period_type
        FROM fact_financial_metrics f
        JOIN dim_companies c ON f.company_id = c.company_id
        JOIN dim_concepts dc ON f.concept_id = dc.concept_id
        JOIN dim_time_periods t ON f.period_id = t.period_id
        WHERE f.dimension_id IS NULL
          AND f.value_numeric IS NOT NULL
          AND c.ticker = :ticker
          AND t.fiscal_year = :year
          AND t.period_type = 'duration'
          AND ABS(f.value_numeric) > 1000000  -- > $1M
          AND (
              dc.concept_name LIKE '%Equity%'
              OR dc.concept_name LIKE '%Stock%'
              OR dc.concept_name LIKE '%Capital%'
              OR dc.normalized_label LIKE '%equity%'
              OR dc.normalized_label LIKE '%stock%'
              OR dc.normalized_label LIKE '%capital%'
          )
          AND dc.normalized_label NOT LIKE '%oci%'
          AND dc.normalized_label NOT LIKE '%comprehensive%income%'
          AND dc.normalized_label != 'retained_earnings'
        ORDER BY ABS(f.value_numeric) DESC
        LIMIT 30;
    """)
    
    result_equity = engine.connect().execute(query_equity, {'ticker': ticker, 'year': year})
    
    print(f"\n  Large Equity-Related Concepts (>$1M):")
    print(f"    {'Label':<50} | {'Concept':<50} | {'Value':>15}")
    print(f"    {'-'*50} | {'-'*50} | {'-'*15}")
    
    total_equity_changes = 0
    potential_adjustments = []
    
    for row_equity in result_equity:
        label, concept, value, period_type = row_equity
        print(f"    {label:<50} | {concept:<50} | ${value:>15,.0f}")
        
        # Check if this could be a missing adjustment
        if abs(value) > abs(missing_amount) * 0.1:  # > 10% of missing amount
            potential_adjustments.append((label, concept, value))
            total_equity_changes += value
    
    print(f"\n  Potential Adjustments (>10% of missing):")
    if potential_adjustments:
        for label, concept, value in potential_adjustments:
            print(f"    - {label}: ${value:,.0f}")
    else:
        print(f"    ⚠️ No large equity adjustments found")
    
    print(f"\n  Summary:")
    print(f"    Missing Amount: ${missing_amount:,.0f}")
    print(f"    Total Equity Changes: ${total_equity_changes:,.0f}")
    print(f"    Gap: ${abs(missing_amount) - abs(total_equity_changes):,.0f}")

print("\n" + "="*100)
print("INVESTIGATION COMPLETE")
print("="*100)

