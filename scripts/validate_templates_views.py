#!/usr/bin/env python3
"""
Validation script to compare new template-based functions vs denormalized fact tables.

This script:
1. Queries denormalized fact tables (fact_income_statement, etc.)
2. Queries new functions (get_income_statement(), etc.)
3. Compares results to ensure they return the same data
4. Reports any discrepancies

Run this after migration to validate the new architecture.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from config import DATABASE_URI


def compare_statement(filing_id: int, period_id: int, statement_type: str, conn):
    """Compare denormalized table vs function for a specific statement"""
    
    # Get function name
    function_map = {
        'income_statement': 'get_income_statement',
        'balance_sheet': 'get_balance_sheet',
        'cash_flow': 'get_cash_flow',
        'comprehensive_income': 'get_comprehensive_income',
        'equity_statement': 'get_equity_statement'
    }
    
    function_name = function_map.get(statement_type)
    if not function_name:
        print(f"   ⚠️  Unknown statement type: {statement_type}")
        return False
    
    # Get table name
    table_map = {
        'income_statement': 'fact_income_statement',
        'balance_sheet': 'fact_balance_sheet',
        'cash_flow': 'fact_cash_flow',
        'comprehensive_income': 'fact_comprehensive_income',
        'equity_statement': 'fact_equity_statement'
    }
    
    table_name = table_map.get(statement_type)
    
    # Query denormalized table
    try:
        table_query = text(f"""
            SELECT 
                concept_id,
                value_numeric,
                display_order,
                is_header
            FROM {table_name}
            WHERE filing_id = :filing_id AND period_id = :period_id
            ORDER BY display_order
        """)
        table_result = conn.execute(table_query, {
            "filing_id": filing_id,
            "period_id": period_id
        })
        table_rows = table_result.fetchall()
    except Exception as e:
        print(f"   ⚠️  Error querying {table_name}: {e}")
        return False
    
    # Query function
    try:
        function_query = text(f"""
            SELECT 
                concept_id,
                value_numeric,
                display_order,
                is_header
            FROM {function_name}(:filing_id, :period_id)
            ORDER BY display_order
        """)
        function_result = conn.execute(function_query, {
            "filing_id": filing_id,
            "period_id": period_id
        })
        function_rows = function_result.fetchall()
    except Exception as e:
        print(f"   ⚠️  Error querying {function_name}(): {e}")
        return False
    
    # Compare
    table_dict = {(row[0], row[2]): (row[1], row[3]) for row in table_rows}
    function_dict = {(row[0], row[2]): (row[1], row[3]) for row in function_rows}
    
    # Check for differences
    table_keys = set(table_dict.keys())
    function_keys = set(function_dict.keys())
    
    missing_in_function = table_keys - function_keys
    extra_in_function = function_keys - table_keys
    value_differences = []
    
    for key in table_keys & function_keys:
        table_val, table_header = table_dict[key]
        func_val, func_header = function_dict[key]
        
        if table_header != func_header:
            value_differences.append(f"  {key}: header mismatch (table={table_header}, func={func_header})")
        
        if table_val != func_val:
            if table_val is None and func_val is None:
                continue
            if table_val is None or func_val is None:
                # NULL mismatches are expected - functions include template items without values
                # Only report if table has value but function doesn't (data loss)
                if table_val is not None and func_val is None:
                    value_differences.append(f"  {key}: NULL mismatch (table={table_val}, func={func_val})")
            else:
                try:
                    if abs(float(table_val) - float(func_val)) > 0.01:  # Allow small floating point differences
                        value_differences.append(f"  {key}: value mismatch (table={table_val}, func={func_val})")
                except (TypeError, ValueError):
                    # Non-numeric comparison - skip
                    pass
    
    if missing_in_function or extra_in_function or value_differences:
        print(f"   ❌ Mismatches found:")
        if missing_in_function:
            print(f"      Missing in function: {len(missing_in_function)} items")
        if extra_in_function:
            print(f"      Extra in function: {len(extra_in_function)} items")
        if value_differences:
            print(f"      Value differences: {len(value_differences)} items")
            for diff in value_differences[:5]:  # Show first 5
                print(f"        {diff}")
        return False
    else:
        print(f"   ✅ Match: {len(table_rows)} items")
        return True


def main():
    """Main validation function"""
    print("=" * 70)
    print("Validation: Template-Based Functions vs Denormalized Tables")
    print("=" * 70)
    
    engine = create_engine(DATABASE_URI)
    
    with engine.connect() as conn:
        # Get all filings with their periods
        query = text("""
            SELECT DISTINCT f.filing_id, tp.period_id, c.ticker
            FROM dim_filings f
            JOIN dim_companies c ON f.company_id = c.company_id
            JOIN fact_financial_metrics fm ON fm.filing_id = f.filing_id
            JOIN dim_time_periods tp ON fm.period_id = tp.period_id
            ORDER BY f.filing_id, tp.period_id
            LIMIT 10
        """)
        
        result = conn.execute(query)
        filings_periods = result.fetchall()
        
        if not filings_periods:
            print("⚠️  No filings found in database")
            return
        
        print(f"\nFound {len(filings_periods)} filing-period combinations to validate")
        print("(Limited to 10 for initial validation)\n")
        
        statement_types = ['income_statement', 'balance_sheet', 'cash_flow', 'comprehensive_income', 'equity_statement']
        
        total_checks = 0
        passed_checks = 0
        
        for filing_id, period_id, ticker in filings_periods:
            print(f"\nFiling {filing_id} ({ticker}), Period {period_id}:")
            
            for statement_type in statement_types:
                print(f"  {statement_type}:", end=" ")
                total_checks += 1
                if compare_statement(filing_id, period_id, statement_type, conn):
                    passed_checks += 1
        
        print("\n" + "=" * 70)
        print(f"Results: {passed_checks}/{total_checks} checks passed")
        print("=" * 70)
        
        if passed_checks == total_checks:
            print("\n✅ All validations passed! New architecture is working correctly.")
        else:
            print(f"\n⚠️  {total_checks - passed_checks} validation(s) failed.")
            print("   Review discrepancies above and fix before deprecating denormalized tables.")


if __name__ == '__main__':
    main()

