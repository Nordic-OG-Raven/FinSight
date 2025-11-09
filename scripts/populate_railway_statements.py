#!/usr/bin/env python3
"""
Populate statement fact tables on Railway database.
Run this on Railway to populate all statement data.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.populate_statement_items import populate_statement_items
from src.utils.populate_statement_facts import populate_statement_facts
from sqlalchemy import create_engine, text
from config import DATABASE_URI

def main():
    print(f'Connecting to: {DATABASE_URI.split("@")[1] if "@" in DATABASE_URI else DATABASE_URI[:50]}')
    
    engine = create_engine(DATABASE_URI)
    with engine.connect() as conn:
        # Get all filing IDs
        result = conn.execute(text('SELECT filing_id FROM dim_filings ORDER BY filing_id'))
        filing_ids = [row[0] for row in result]
        print(f'Found {len(filing_ids)} filings')
        
        # Populate statement items
        print('\nPopulating rel_statement_items...')
        for filing_id in filing_ids:
            try:
                count = populate_statement_items(filing_id=filing_id)
                if count > 0:
                    print(f'  Filing {filing_id}: {count} items')
            except Exception as e:
                print(f'  Filing {filing_id}: ERROR - {str(e)[:100]}')
        
        # Populate statement facts
        print('\nPopulating statement fact tables...')
        total_income = 0
        total_balance = 0
        total_cash = 0
        total_comprehensive = 0
        total_equity = 0
        
        for filing_id in filing_ids:
            try:
                populate_statement_facts(filing_id=filing_id)
                
                # Count what was populated
                result = conn.execute(text("""
                    SELECT 
                        (SELECT COUNT(*) FROM fact_income_statement WHERE filing_id = :fid) as income,
                        (SELECT COUNT(*) FROM fact_balance_sheet WHERE filing_id = :fid) as balance,
                        (SELECT COUNT(*) FROM fact_cash_flow WHERE filing_id = :fid) as cash,
                        (SELECT COUNT(*) FROM fact_comprehensive_income WHERE filing_id = :fid) as comprehensive,
                        (SELECT COUNT(*) FROM fact_equity_statement WHERE filing_id = :fid) as equity
                """), {'fid': filing_id})
                row = result.fetchone()
                total_income += row[0] or 0
                total_balance += row[1] or 0
                total_cash += row[2] or 0
                total_comprehensive += row[3] or 0
                total_equity += row[4] or 0
                
                if filing_id % 5 == 0:
                    print(f'  Processed {filing_id}/{len(filing_ids)}...')
            except Exception as e:
                print(f'  Filing {filing_id}: ERROR - {str(e)[:100]}')
        
        print(f'\n✅ Done! Total facts:')
        print(f'  Income: {total_income}')
        print(f'  Balance: {total_balance}')
        print(f'  Cash Flow: {total_cash}')
        print(f'  Comprehensive: {total_comprehensive}')
        print(f'  Equity: {total_equity}')

if __name__ == '__main__':
    main()

