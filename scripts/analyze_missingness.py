#!/usr/bin/env python3
"""
Missingness Analysis Script for FinSight

Analyzes why financial statement items show "-" (missing data) across years.
Identifies patterns in missing data to help diagnose root causes.
"""

import sys
import os
from collections import defaultdict
from sqlalchemy import create_engine, text

# Add parent directory to path to import config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE_URI

def analyze_company_missingness(ticker: str, filing_year: int):
    """Analyze missing data patterns for a specific company and filing year"""
    engine = create_engine(DATABASE_URI)
    
    with engine.connect() as conn:
        # First, get all available period years in this filing
        years_query = text("""
            SELECT DISTINCT EXTRACT(YEAR FROM COALESCE(p.end_date, p.instant_date))::INTEGER as period_year
            FROM fact_financial_metrics fm
            JOIN dim_companies c ON fm.company_id = c.company_id
            JOIN dim_time_periods p ON fm.period_id = p.period_id
            JOIN dim_filings f ON fm.filing_id = f.filing_id
            WHERE c.ticker = :ticker 
              AND EXTRACT(YEAR FROM f.fiscal_year_end) = :filing_year
              AND fm.dimension_id IS NULL
              AND fm.value_numeric IS NOT NULL
            ORDER BY period_year DESC
        """)
        years_result = conn.execute(years_query, {"ticker": ticker, "filing_year": filing_year})
        available_years = [row[0] for row in years_result.fetchall()]
        
        if not available_years:
            print(f"No data found for {ticker} filing year {filing_year}")
            return
        
        print(f"\n{'='*80}")
        print(f"Missingness Analysis: {ticker} Filing Year {filing_year}")
        print(f"{'='*80}")
        print(f"Available period years: {available_years}")
        print(f"Expected years to display: {available_years[:3] if len(available_years) > 3 else available_years}")
        print()
        
        # Get all facts grouped by statement type and normalized_label
        query = text("""
            SELECT 
                co.statement_type,
                co.normalized_label,
                co.concept_name,
                EXTRACT(YEAR FROM COALESCE(p.end_date, p.instant_date))::INTEGER as period_year,
                p.period_type,
                fm.value_numeric,
                fm.unit_measure,
                COUNT(*) OVER (PARTITION BY co.normalized_label) as total_facts_for_label
            FROM fact_financial_metrics fm
            JOIN dim_companies c ON fm.company_id = c.company_id
            JOIN dim_concepts co ON fm.concept_id = co.concept_id
            JOIN dim_time_periods p ON fm.period_id = p.period_id
            JOIN dim_filings f ON fm.filing_id = f.filing_id
            WHERE c.ticker = :ticker 
              AND EXTRACT(YEAR FROM f.fiscal_year_end) = :filing_year
              AND fm.dimension_id IS NULL
              AND fm.value_numeric IS NOT NULL
              AND EXTRACT(YEAR FROM COALESCE(p.end_date, p.instant_date)) = ANY(:years)
            ORDER BY co.statement_type, co.normalized_label, period_year DESC
        """)
        
        years_to_check = available_years[:3] if len(available_years) > 3 else available_years
        result = conn.execute(query, {
            "ticker": ticker,
            "filing_year": filing_year,
            "years": years_to_check
        })
        
        # Group by statement type and normalized_label
        by_statement = defaultdict(lambda: defaultdict(list))
        
        for row in result:
            stmt_type = row[0] or 'other'
            normalized_label = row[1]
            concept_name = row[2]
            period_year = row[3]
            period_type = row[4]
            value = row[5]
            unit = row[6]
            
            by_statement[stmt_type][normalized_label].append({
                'period_year': period_year,
                'period_type': period_type,
                'value': value,
                'unit': unit,
                'concept_name': concept_name
            })
        
        # Analyze each statement type
        for stmt_type in ['income_statement', 'balance_sheet', 'cash_flow']:
            if stmt_type not in by_statement:
                continue
                
            print(f"\n{'-'*80}")
            print(f"{stmt_type.upper().replace('_', ' ')}")
            print(f"{'-'*80}")
            
            items = by_statement[stmt_type]
            
            # Group by number of years with data
            by_year_count = defaultdict(list)
            
            for normalized_label, facts in items.items():
                years_with_data = set(f['period_year'] for f in facts)
                year_count = len(years_with_data)
                by_year_count[year_count].append({
                    'label': normalized_label,
                    'concept_name': facts[0]['concept_name'] if facts else '',
                    'years': sorted(years_with_data, reverse=True),
                    'facts': facts,
                    'units': set(f['unit'] for f in facts),
                    'period_types': set(f['period_type'] for f in facts)
                })
            
            # Report by year count (starting with 1 fact, then 2, etc.)
            for year_count in sorted(by_year_count.keys()):
                items_with_count = by_year_count[year_count]
                print(f"\n  Items with {year_count} year(s) of data ({len(items_with_count)} items):")
                
                # Show first 10 examples
                for item in items_with_count[:10]:
                    years_str = ', '.join(map(str, item['years']))
                    missing_years = [y for y in years_to_check if y not in item['years']]
                    missing_str = f" (missing: {', '.join(map(str, missing_years))})" if missing_years else ""
                    
                    units_str = ', '.join(sorted(item['units']))
                    period_types_str = ', '.join(sorted(str(pt) for pt in item['period_types']))
                    
                    print(f"    • {item['label'][:60]:<60}")
                    print(f"      Concept: {item['concept_name'][:70]}")
                    print(f"      Years: {years_str}{missing_str}")
                    print(f"      Units: {units_str}")
                    print(f"      Period types: {period_types_str}")
                    print()
                
                if len(items_with_count) > 10:
                    print(f"    ... and {len(items_with_count) - 10} more items with {year_count} year(s) of data")
            
            # Summary statistics
            total_items = len(items)
            items_with_all_years = len(by_year_count.get(len(years_to_check), []))
            items_missing_data = total_items - items_with_all_years
            
            print(f"\n  Summary:")
            print(f"    Total items: {total_items}")
            print(f"    Items with data for all {len(years_to_check)} years: {items_with_all_years}")
            print(f"    Items missing data for at least 1 year: {items_missing_data}")
            if total_items > 0:
                completeness = (items_with_all_years / total_items) * 100
                print(f"    Completeness: {completeness:.1f}%")
        
        # Check for potential duplicates (same concept with different normalized_labels)
        print(f"\n{'-'*80}")
        print("POTENTIAL DUPLICATES (same concept_name, different normalized_label)")
        print(f"{'-'*80}")
        
        duplicate_query = text("""
            SELECT 
                co.concept_name,
                COUNT(DISTINCT co.normalized_label) as label_count,
                ARRAY_AGG(DISTINCT co.normalized_label ORDER BY co.normalized_label) as labels,
                COUNT(DISTINCT EXTRACT(YEAR FROM COALESCE(p.end_date, p.instant_date))) as year_count
            FROM fact_financial_metrics fm
            JOIN dim_companies c ON fm.company_id = c.company_id
            JOIN dim_concepts co ON fm.concept_id = co.concept_id
            JOIN dim_time_periods p ON fm.period_id = p.period_id
            JOIN dim_filings f ON fm.filing_id = f.filing_id
            WHERE c.ticker = :ticker 
              AND EXTRACT(YEAR FROM f.fiscal_year_end) = :filing_year
              AND fm.dimension_id IS NULL
              AND fm.value_numeric IS NOT NULL
              AND EXTRACT(YEAR FROM COALESCE(p.end_date, p.instant_date)) = ANY(:years)
            GROUP BY co.concept_name
            HAVING COUNT(DISTINCT co.normalized_label) > 1
            ORDER BY label_count DESC, co.concept_name
            LIMIT 20
        """)
        
        dup_result = conn.execute(duplicate_query, {
            "ticker": ticker,
            "filing_year": filing_year,
            "years": years_to_check
        })
        
        duplicates = list(dup_result)
        if duplicates:
            for row in duplicates:
                concept_name = row[0]
                label_count = row[1]
                labels = row[2]
                year_count = row[3]
                print(f"  {concept_name[:60]}")
                print(f"    {label_count} different normalized_labels: {', '.join(labels[:3])}{'...' if len(labels) > 3 else ''}")
                print(f"    Appears in {year_count} year(s)")
                print()
        else:
            print("  No obvious duplicates found (same concept_name with different normalized_labels)")
        
        # Check for items missing in some years but existing with same concept_name in other years
        print(f"\n{'-'*80}")
        print("POTENTIAL MISSING DATA (exists in some years, missing in others)")
        print(f"{'-'*80}")
        
        missing_query = text("""
            WITH items_by_year AS (
                SELECT 
                    co.normalized_label,
                    co.concept_name,
                    co.statement_type,
                    EXTRACT(YEAR FROM COALESCE(p.end_date, p.instant_date))::INTEGER as period_year,
                    COUNT(*) as fact_count
                FROM fact_financial_metrics fm
                JOIN dim_companies c ON fm.company_id = c.company_id
                JOIN dim_concepts co ON fm.concept_id = co.concept_id
                JOIN dim_time_periods p ON fm.period_id = p.period_id
                JOIN dim_filings f ON fm.filing_id = f.filing_id
                WHERE c.ticker = :ticker 
                  AND EXTRACT(YEAR FROM f.fiscal_year_end) = :filing_year
                  AND fm.dimension_id IS NULL
                  AND fm.value_numeric IS NOT NULL
                  AND EXTRACT(YEAR FROM COALESCE(p.end_date, p.instant_date)) = ANY(:years)
                GROUP BY co.normalized_label, co.concept_name, co.statement_type, period_year
            ),
            items_summary AS (
                SELECT 
                    normalized_label,
                    concept_name,
                    statement_type,
                    ARRAY_AGG(DISTINCT period_year ORDER BY period_year DESC) as years_present,
                    COUNT(DISTINCT period_year) as year_count
                FROM items_by_year
                GROUP BY normalized_label, concept_name, statement_type
            )
            SELECT 
                i1.normalized_label,
                i1.concept_name,
                i1.statement_type,
                i1.years_present,
                i2.normalized_label as alt_label,
                i2.years_present as alt_years
            FROM items_summary i1
            LEFT JOIN items_summary i2 ON 
                i1.concept_name = i2.concept_name 
                AND i1.normalized_label != i2.normalized_label
            WHERE i1.year_count < :expected_year_count
              AND i1.statement_type IN ('income_statement', 'balance_sheet', 'cash_flow')
            ORDER BY i1.statement_type, i1.concept_name
            LIMIT 30
        """)
        
        missing_result = conn.execute(missing_query, {
            "ticker": ticker,
            "filing_year": filing_year,
            "years": years_to_check,
            "expected_year_count": len(years_to_check)
        })
        
        missing_items = list(missing_result)
        if missing_items:
            current_stmt = None
            for row in missing_items:
                if current_stmt != row[2]:
                    current_stmt = row[2]
                    print(f"\n  {current_stmt.upper().replace('_', ' ')}:")
                years_str = ', '.join(map(str, row[3]))
                missing_years = [y for y in years_to_check if y not in row[3]]
                missing_str = f" (missing: {', '.join(map(str, missing_years))})" if missing_years else ""
                print(f"    {row[0][:60]}")
                print(f"      Concept: {row[1][:70]}")
                print(f"      Present in: {years_str}{missing_str}")
                if row[4]:  # alt_label exists
                    alt_years_str = ', '.join(map(str, row[5]))
                    print(f"      ⚠️  Same concept with different label '{row[4]}' exists in: {alt_years_str}")
                print()
        else:
            print("  No items found that are missing in some years")

def main():
    if len(sys.argv) < 3:
        print("Usage: python analyze_missingness.py <TICKER> <FILING_YEAR>")
        print("Example: python analyze_missingness.py AAPL 2024")
        sys.exit(1)
    
    ticker = sys.argv[1].upper()
    filing_year = int(sys.argv[2])
    
    analyze_company_missingness(ticker, filing_year)

if __name__ == "__main__":
    main()

