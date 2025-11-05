#!/usr/bin/env python3
"""
Load missing company-years to Railway using the VALIDATED PIPELINE.

This script uses the existing run_pipeline() function which includes:
- XBRL parsing (if files don't exist)
- Financial validation (balance sheet checks)
- Completeness analysis
- Proper database loading into star schema

The pipeline will:
1. Use existing downloaded files if available (no re-download)
2. Parse XBRL (or use existing parsed JSON)
3. Validate all financial data
4. Load into Railway database using star schema
"""
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Import the VALIDATED pipeline
from src.main import run_pipeline

# Missing company-years to load (7 total)
MISSING_COMPANIES = [
    ("AMZN", 2023, "10-K"),
    ("ASML", 2023, "20-F"),
    ("BAC", 2023, "10-K"),
    ("CAT", 2023, "10-K"),
    ("JPM", 2023, "10-K"),
    ("JPM", 2024, "10-K"),
    ("WMT", 2023, "10-K"),
]

def main():
    print("="*80)
    print("📥 Loading Missing Company-Years to Railway using VALIDATED PIPELINE")
    print("="*80)
    print()
    print("This uses run_pipeline() which includes:")
    print("  ✅ XBRL parsing")
    print("  ✅ Financial validation (balance sheet checks)")
    print("  ✅ Completeness analysis")
    print("  ✅ Proper database loading")
    print()
    
    # Check if Railway environment variables are set
    railway_host = os.getenv('RAILWAY_POSTGRES_HOST')
    database_url = os.getenv('DATABASE_URL')
    
    if not railway_host and not database_url:
        print("⚠️  WARNING: Railway environment variables not detected!")
        print("   This script needs Railway database connection.")
        print()
        print("   Run via Railway CLI (recommended):")
        print("     railway link")
        print("     railway run python load_missing_to_railway.py")
        print()
        return 1
    
    total = len(MISSING_COMPANIES)
    loaded = 0
    failed = 0
    
    print(f"Found {total} company-years to load:")
    for ticker, year, filing_type in MISSING_COMPANIES:
        print(f"  - {ticker} {year} ({filing_type})")
    print()
    
    for idx, (ticker, year, filing_type) in enumerate(MISSING_COMPANIES, 1):
        print(f"[{idx}/{total}] Processing {ticker} {year} using full pipeline...")
        print("-" * 80)
        
        try:
            # Use the VALIDATED pipeline function
            # This will:
            # 1. Download filing (from SEC or use existing)
            # 2. Parse XBRL
            # 3. Validate (balance sheet checks, etc.)
            # 4. Check completeness
            # 5. Load to database
            success = run_pipeline(ticker=ticker, year=year, filing_type=filing_type)
            
            if success:
                print(f"   ✅ Successfully loaded {ticker} {year}")
                loaded += 1
            else:
                print(f"   ❌ Pipeline failed for {ticker} {year}")
                failed += 1
                
        except Exception as e:
            print(f"   ❌ Failed to process {ticker} {year}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
        
        print()
    
    print("="*80)
    print(f"✅ Processing complete!")
    print(f"   Loaded: {loaded}/{total}")
    print(f"   Failed: {failed}/{total}")
    print("="*80)
    
    if loaded > 0:
        print()
        print("Next steps:")
        print("  1. Verify data loaded: curl https://finsight-production-d5c1.up.railway.app/api/companies")
        print("  2. Check storage: curl https://finsight-production-d5c1.up.railway.app/api/companies | jq .storage")
    
    return 0 if failed == 0 else 1

if __name__ == '__main__':
    sys.exit(main())

