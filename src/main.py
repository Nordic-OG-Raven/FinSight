#!/usr/bin/env python3
"""
FinSight Main CLI

Comprehensive financial data extraction pipeline.
Extracts ALL facts from XBRL filings and loads to PostgreSQL data warehouse.
"""
import sys
import argparse
import logging
import json
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingestion.fetch_sec import SECFilingDownloader
from src.parsing.parse_xbrl import ComprehensiveXBRLParser
from src.validation.checks import FinancialValidator
from src.validation.completeness import CompletenessTracker
from config import DATA_RAW, DATA_PROCESSED, DATA_REPORTS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_pipeline(ticker: str, year: int, filing_type: str = '10-K') -> bool:
    """
    Run the ETL pipeline for a given ticker/year.
    Used by the Flask API for programmatic access.
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info(f"Starting pipeline for {ticker} {year}")
        
        # Step 1: Download filing
        downloader = SECFilingDownloader(output_dir=DATA_RAW)
        filing_path = downloader.download_filing(ticker, year, filing_type)
        
        if not filing_path:
            logger.error(f"Failed to download filing for {ticker} {year}")
            return False
        
        logger.info(f"Downloaded: {filing_path}")
        
        # Step 2: Parse XBRL
        parser_obj = ComprehensiveXBRLParser()
        result = parser_obj.parse_filing(filing_path)
        
        if not result:
            logger.error(f"Failed to parse XBRL for {ticker} {year}")
            return False
        
        facts = result['facts']
        metadata = result['metadata']
        relationships = result.get('relationships', {})
        logger.info(f"Extracted {len(facts)} facts")
        
        # Step 3: Validate
        validator = FinancialValidator(tolerance_pct=1.0)
        validation_report = validator.validate_filing(
            facts=facts,
            company=ticker,
            filing_type=filing_type,
            fiscal_year_end=metadata.get('fiscal_year_end', f'{year}-12-31')
        )
        
        logger.info(f"Validation score: {validation_report.overall_score:.1%}")
        
        # Step 4: Completeness check
        tracker = CompletenessTracker()
        completeness_report = tracker.analyze_completeness(
            facts, 
            company=ticker, 
            filing_type=filing_type, 
            fiscal_year_end=metadata.get('fiscal_year_end', f'{year}-12-31')
        )
        
        logger.info(f"Completeness: {completeness_report.overall_completeness:.1%}")
        
        # Step 4.5: Always fill gaps with SEC API and check for missing years
        logger.info(f"Filling gaps with SEC API for all missing concepts and years...")
        logger.info(f"  Initial completeness: {completeness_report.overall_completeness:.1%}")
        logger.info(f"  Balance Sheet: {completeness_report.balance_sheet_completeness:.1%}")
        logger.info(f"  Income Statement: {completeness_report.income_statement_completeness:.1%}")
        logger.info(f"  Cash Flow: {completeness_report.cash_flow_completeness:.1%}")
        
        # Determine taxonomy: IFRS for 20-F, US-GAAP for 10-K
        taxonomy = 'ifrs-full' if '20-F' in filing_type.upper() else 'us-gaap'
        
        # Check for missing years in existing facts
        existing_years = set()
        for fact in facts:
            period_end = fact.get('period_end')
            instant_date = fact.get('instant_date')
            if period_end:
                fact_year = period_end[:4] if isinstance(period_end, str) else str(period_end.year)
                existing_years.add(fact_year)
            if instant_date:
                fact_year = instant_date[:4] if isinstance(instant_date, str) else str(instant_date.year)
                existing_years.add(fact_year)
        
        # Fill gaps for current year and any missing years (typically 2-3 years of comparatives)
        years_to_fill = {str(year)}
        if existing_years:
            # Also try to fill for years that appear in the data but might be missing concepts
            years_to_fill.update(existing_years)
            # Also check for comparative years (typically year-1, year-2)
            for y in range(year - 2, year + 1):
                years_to_fill.add(str(y))
        
        logger.info(f"  Checking for missing data in years: {sorted(years_to_fill)}")
        
        # Fill gaps for each year (with caching to respect rate limits)
        # NOTE: This only fills TRULY missing concepts (not in facts list at all)
        # Post-load gap filling (after DB load) will catch wrong values and missing years
        cache_dir = DATA_RAW / 'sec_api_cache'
        for fill_year in sorted(years_to_fill):
            facts = tracker.fill_missing_with_sec_api(
                facts,
                company=ticker,
                year=int(fill_year),
                taxonomy=taxonomy,
                cache_dir=cache_dir  # Cache responses to avoid repeated API calls
            )

        # Balance-sheet instant facts (Assets, Liabilities) for comparative years 2+ years
        # back are often genuinely absent from the primary filing (only 2 comparative
        # columns are carried) and unreachable via SEC-API for foreign private issuers.
        # Pull them from that year's own filing instead — see
        # docs/NVO_GOLDEN_PATH_2026-08.md item 4.
        for fill_year in sorted(years_to_fill):
            if int(fill_year) < year:
                facts = tracker.fill_missing_instant_facts_from_comparative_filing(
                    facts,
                    company=ticker,
                    missing_year=int(fill_year),
                    filing_type=filing_type
                )

        logger.info(f"Gap filling complete. Total facts: {len(facts)}")
        
        # Re-run completeness check after gap filling
        completeness_report = tracker.analyze_completeness(
            facts,
            company=ticker,
            filing_type=filing_type,
            fiscal_year_end=metadata.get('fiscal_year_end', f'{year}-12-31')
        )
        logger.info(f"Completeness after gap filling:")
        logger.info(f"  Overall: {completeness_report.overall_completeness:.1%}")
        logger.info(f"  Balance Sheet: {completeness_report.balance_sheet_completeness:.1%}")
        logger.info(f"  Income Statement: {completeness_report.income_statement_completeness:.1%}")
        logger.info(f"  Cash Flow: {completeness_report.cash_flow_completeness:.1%}")
        
        # Step 4.75: Pre-load validation (input_check.py)
        logger.info("Running pre-load validation...")
        from src.validation.input_check import InputValidator
        
        input_validator = InputValidator(tolerance_pct=1.0)
        input_report = input_validator.validate_facts(facts, company=ticker)
        
        if not input_report.passed:
            logger.warning(f"Pre-load validation issues: {input_report.overall_score:.1%}")
            # Log specific issues for debugging
            for result in input_report.results:
                if not result.passed:
                    logger.warning(f"  {result.rule_name}: {result.message}")
        else:
            logger.info(f"Pre-load validation passed: {input_report.overall_score:.1%}")
        
        # Step 5: Save to database (using star schema loader - same as Railway uses)
        from database.load_financial_data import StarSchemaLoader
        import json
        
        # Create temporary JSON file for the loader (StarSchemaLoader expects JSON files)
        temp_json = DATA_PROCESSED / f"{ticker}_{year}_{filing_type.replace('-', '')}_temp_facts.json"
        temp_json.write_text(json.dumps({
            'company': ticker,
            'year': year,
            'filing_type': filing_type,
            'facts': facts,
            'metadata': metadata,
            'relationships': relationships
        }, indent=2, default=str))
        
        # Load using star schema loader (same as Railway uses)
        # This applies normalization, validation, and loads into correct schema
        loader = StarSchemaLoader()
        loader.load_json_file(temp_json)
        
        # Clean up temp file
        temp_json.unlink()
        
        loader.close()
        
        # Step 6: Post-load gap filling (catches missing concepts and wrong values)
        # This runs AFTER database load, so it can query what's actually in the DB
        logger.info("Running post-load gap filling to catch missing concepts and wrong values...")
        from src.utils.post_load_gap_filling import run_post_load_gap_filling
        
        years_to_check = list(years_to_fill)
        filled_post = run_post_load_gap_filling(
            ticker=ticker,
            years=[int(y) for y in years_to_check],
            taxonomy=taxonomy,
            primary_year=year,
            filing_type=filing_type
        )
        if filled_post > 0:
            logger.info(f"✅ Post-load gap filling added {filled_post} facts")
        
        # Step 6.5: Consistency validation (consistency_check.py)
        logger.info("Running consistency validation...")
        try:
            from src.validation.consistency_check import ConsistencyValidator
            
            consistency_validator = ConsistencyValidator(tolerance_pct=1.0)
            consistency_report = consistency_validator.validate_consistency(ticker)
            
            if not consistency_report.passed:
                logger.warning(f"Consistency issues: {consistency_report.overall_score:.1%}")
                for result in consistency_report.results:
                    if not result.passed:
                        logger.warning(f"  {result.rule_name}: {result.message}")
            else:
                logger.info(f"Consistency validation passed: {consistency_report.overall_score:.1%}")
        except Exception as e:
            logger.warning(f"Consistency validation failed: {e}")
            # Don't fail pipeline if consistency check fails
        
        # Step 7: Universal UI test (ui_test.py)
        logger.info("Running universal UI test...")
        try:
            from src.validation.ui_test import UniversalUITest
            
            ui_tester = UniversalUITest(api_base="http://localhost:5001")
            ui_report = ui_tester.test_company(ticker, year)
            
            if not ui_report.passed:
                logger.warning(f"UI test issues: {ui_report.overall_score:.1%}")
                for result in ui_report.results:
                    if not result.passed:
                        logger.warning(f"  {result.rule_name}: {result.message}")
            else:
                logger.info(f"UI test passed: {ui_report.overall_score:.1%}")
        except Exception as e:
            logger.warning(f"UI test failed: {e}")
            # Don't fail pipeline if UI test fails
        
        logger.info(f"Pipeline completed successfully for {ticker} {year}")
        return True
        
    except Exception as e:
        logger.error(f"Pipeline failed for {ticker} {year}: {e}", exc_info=True)
        return False


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='FinSight - Extract comprehensive financial data from XBRL filings',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract single company
  python src/main.py --ticker NVO --year 2024 --filing-type 20-F
  
  # Extract and save to custom location
  python src/main.py --ticker AAPL --year 2023 --output custom_data/
  
  # Skip download if file already exists
  python src/main.py --ticker NVO --year 2024 --skip-download
        """
    )
    
    # Required arguments
    parser.add_argument('--ticker', required=True, help='Stock ticker symbol')
    parser.add_argument('--year', type=int, required=True, help='Fiscal year')
    
    # Optional arguments
    parser.add_argument('--filing-type', default='10-K', 
                        help='Filing type (10-K, 20-F, etc.). Default: 10-K')
    parser.add_argument('--output', type=Path, default=DATA_PROCESSED,
                        help='Output directory for processed data')
    parser.add_argument('--skip-download', action='store_true',
                        help='Skip download if file already exists')
    parser.add_argument('--save-json', action='store_true', default=True,
                        help='Save facts to JSON file (default: True)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Print header
    print("=" * 70)
    print("🔍 FinSight - Comprehensive Financial Data Extraction")
    print("=" * 70)
    print(f"Company: {args.ticker}")
    print(f"Year: {args.year}")
    print(f"Filing Type: {args.filing_type}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()
    
    start_time = datetime.now()
    
    # Step 1: Download filing
    print("📥 Step 1/3: Downloading XBRL filing...")
    print("-" * 70)
    
    downloader = SECFilingDownloader(output_dir=DATA_RAW)
    
    if args.skip_download:
        # Check if file exists
        pattern = f"{args.ticker}_{args.year}_{args.filing_type.replace('-', '')}*.htm"
        existing_files = list(DATA_RAW.glob(pattern))
        
        if existing_files:
            filing_path = existing_files[0]
            logger.info(f"Using existing file: {filing_path}")
        else:
            logger.warning("No existing file found, downloading...")
            filing_path = downloader.download_filing(args.ticker, args.year, args.filing_type)
    else:
        filing_path = downloader.download_filing(args.ticker, args.year, args.filing_type)
    
    if not filing_path:
        print("\n❌ Failed to download filing")
        sys.exit(1)
    
    print(f"✅ Downloaded: {filing_path.name}")
    print(f"   Size: {filing_path.stat().st_size / 1024 / 1024:.1f} MB")
    print()
    
    # Step 2: Parse XBRL and extract ALL facts
    print("🔬 Step 2/3: Parsing XBRL and extracting ALL facts...")
    print("-" * 70)
    
    parser_obj = ComprehensiveXBRLParser()
    result = parser_obj.parse_filing(filing_path)
    
    if not result:
        print("\n❌ Failed to parse XBRL")
        sys.exit(1)
    
    facts = result['facts']
    metadata = result['metadata']
    
    print(f"✅ Parsing complete!")
    print(f"   Total facts extracted: {len(facts)}")
    
    # Apply normalization to facts BEFORE validation/completeness
    # This ensures completeness analysis uses normalized labels (works for both IFRS and US-GAAP)
    print("🔧 Applying normalization to facts...")
    try:
        from src.utils.taxonomy_mappings import get_normalized_label
        normalized_count = 0
        for fact in facts:
            concept_name = fact.get('concept')
            if concept_name:
                normalized = get_normalized_label(concept_name)
                if normalized:
                    fact['normalized_label'] = normalized
                    normalized_count += 1
        print(f"   ✅ Normalized {normalized_count}/{len(facts)} facts ({100*normalized_count/len(facts):.1f}%)")
    except Exception as e:
        logger.warning(f"Failed to apply normalization: {e}")
        print(f"   ⚠️  Normalization failed (completeness may be inaccurate for IFRS companies)")
    
    # Show breakdown by taxonomy
    from collections import Counter
    taxonomy_counts = Counter([f['taxonomy'] for f in facts])
    print(f"\n   Facts by taxonomy:")
    for taxonomy, count in taxonomy_counts.most_common():
        print(f"     {taxonomy}: {count}")
    
    print()
    
    # Step 3: Validate data quality
    print("🔍 Step 3/5: Validating data quality...")
    print("-" * 70)
    
    validator = FinancialValidator(tolerance_pct=1.0)
    validation_report = validator.validate_filing(
        facts=facts,
        company=args.ticker,
        filing_type=args.filing_type,
        fiscal_year_end=metadata.get('fiscal_year_end', str(args.year) + '-12-31')
    )
    
    print(f"✅ Validation complete!")
    print(f"   Overall Score: {validation_report.overall_score:.1%}")
    print(f"   Passed: {'✅ YES' if validation_report.passed else '❌ NO'}")
    print(f"   Passed Rules: {sum(1 for r in validation_report.results if r.passed)}/{len(validation_report.results)}")
    
    if validation_report.get_errors():
        print(f"   ⚠️  Errors: {len(validation_report.get_errors())}")
    if validation_report.get_warnings():
        print(f"   ⚠️  Warnings: {len(validation_report.get_warnings())}")
    
    print()
    
    # Step 4: Analyze initial completeness (before gap filling)
    tracker = CompletenessTracker()
    initial_completeness = tracker.analyze_completeness(
        facts=facts,
        company=args.ticker,
        filing_type=args.filing_type,
        fiscal_year_end=metadata.get('fiscal_year_end', str(args.year) + '-12-31')
    )
    
    # Step 4.5: Always fill gaps with SEC API and check for missing years
    print("🔧 Step 4/5: Filling gaps with SEC API...")
    print("-" * 70)
    print(f"   Initial: {initial_completeness.overall_completeness:.1%} "
          f"(BS: {initial_completeness.balance_sheet_completeness:.1%}, "
          f"IS: {initial_completeness.income_statement_completeness:.1%}, "
          f"CF: {initial_completeness.cash_flow_completeness:.1%})")
    
    # Determine taxonomy: IFRS for 20-F, US-GAAP for 10-K
    taxonomy = 'ifrs-full' if '20-F' in args.filing_type.upper() else 'us-gaap'
    
    # Check for missing years in existing facts
    existing_years = set()
    for fact in facts:
        period_end = fact.get('period_end')
        instant_date = fact.get('instant_date')
        if period_end:
            fact_year = period_end[:4] if isinstance(period_end, str) else str(period_end.year)
            existing_years.add(fact_year)
        if instant_date:
            fact_year = instant_date[:4] if isinstance(instant_date, str) else str(instant_date.year)
            existing_years.add(fact_year)
    
    # Fill gaps for current year and any missing years (typically 2-3 years of comparatives)
    years_to_fill = {str(args.year)}
    if existing_years:
        # Also try to fill for years that appear in the data but might be missing concepts
        years_to_fill.update(existing_years)
        # Also check for comparative years (typically year-1, year-2)
        for y in range(args.year - 2, args.year + 1):
            years_to_fill.add(str(y))
    
    total_filled = 0
    # Fill gaps for each year (with caching to respect rate limits)
    cache_dir = Path(DATA_RAW) / 'sec_api_cache'
    for fill_year in sorted(years_to_fill):
        facts_before = len(facts)
        facts = tracker.fill_missing_with_sec_api(
            facts,
            company=args.ticker,
            year=int(fill_year),
            taxonomy=taxonomy,
            cache_dir=cache_dir  # Cache responses to avoid repeated API calls
        )
        filled_this_year = len(facts) - facts_before
        total_filled += filled_this_year
        if filled_this_year > 0:
            print(f"   Year {fill_year}: +{filled_this_year} concepts")

    # Balance-sheet instant facts (Assets, Liabilities) for comparative years 2+ years
    # back are often genuinely absent from the primary filing and unreachable via
    # SEC-API for foreign private issuers — pull from that year's own filing instead.
    # See docs/NVO_GOLDEN_PATH_2026-08.md item 4.
    for fill_year in sorted(years_to_fill):
        if int(fill_year) < args.year:
            facts_before = len(facts)
            facts = tracker.fill_missing_instant_facts_from_comparative_filing(
                facts,
                company=args.ticker,
                missing_year=int(fill_year),
                filing_type=args.filing_type
            )
            filled_this_year = len(facts) - facts_before
            total_filled += filled_this_year
            if filled_this_year > 0:
                print(f"   Year {fill_year} (from comparative filing): +{filled_this_year} concepts")

    print(f"   ✅ Gap filling complete: +{total_filled} total concepts added")
    
    # Re-run completeness check after gap filling (THIS IS THE FINAL SCORE)
    completeness_report = tracker.analyze_completeness(
        facts,
        company=args.ticker,
        filing_type=args.filing_type,
        fiscal_year_end=metadata.get('fiscal_year_end', str(args.year) + '-12-31')
    )
    
    print()
    print("📊 Step 5/5: Final completeness analysis...")
    print("-" * 70)
    print(f"✅ Final completeness: {completeness_report.overall_completeness:.1%}")
    print(f"   Balance Sheet: {completeness_report.balance_sheet_completeness:.1%}")
    print(f"   Income Statement: {completeness_report.income_statement_completeness:.1%}")
    print(f"   Cash Flow: {completeness_report.cash_flow_completeness:.1%}")
    print(f"   Data Quality: {completeness_report.facts_with_numeric_values}/{completeness_report.total_facts} facts with numeric values")
    
    print()
    
    # Final safety net: drop any stray interim/historical facts re-introduced after the
    # primary parse (gap-filling queries the SEC companyfacts API, which returns a concept's
    # FULL history — e.g. 2016 quarter-ends — not just this annual report's periods). Keeping
    # them pollutes per-year statement validation and inflates dim_concepts on load.
    try:
        before = len(facts)
        facts = parser_obj._filter_to_annual_periods(facts)
        if len(facts) != before:
            print(f"🔧 Annual-period filter: {before} → {len(facts)} facts (dropped {before - len(facts)} interim/historical)")
    except Exception as e:
        logger.warning(f"Annual-period filter skipped: {e}")

    # Step 6: Save results
    print("💾 Step 6/6: Saving results...")
    print("-" * 70)

    # Ensure output directory exists
    args.output.mkdir(parents=True, exist_ok=True)
    
    # Save to JSON
    if args.save_json:
        output_file = args.output / f"{args.ticker}_{args.year}_{args.filing_type.replace('-', '')}_facts.json"
        
        # Get relationships from parse result
        relationships = result.get('relationships', {})
        
        output_data = {
            'company': args.ticker,
            'year': args.year,
            'filing_type': args.filing_type,
            'facts': facts,
            'metadata': metadata,
            'relationships': relationships,  # CRITICAL: Include relationships for database loading
            'validation': validation_report.to_dict(),
            'completeness': completeness_report.to_dict(),
            'extraction_timestamp': datetime.now().isoformat(),
            'total_facts': len(facts)
        }
        
        output_file.write_text(json.dumps(output_data, indent=2, default=str))
        print(f"✅ Saved JSON: {output_file}")
        print(f"   Size: {output_file.stat().st_size / 1024:.1f} KB")
    
    # Save validation report separately
    validation_file = DATA_REPORTS / f"{args.ticker}_{args.year}_validation.json"
    validation_file.write_text(json.dumps(validation_report.to_dict(), indent=2, default=str))
    print(f"✅ Saved validation: {validation_file}")
    
    # Save completeness report separately
    completeness_file = DATA_REPORTS / f"{args.ticker}_{args.year}_completeness.json"
    completeness_file.write_text(json.dumps(completeness_report.to_dict(), indent=2, default=str))
    print(f"✅ Saved completeness: {completeness_file}")
    
    # Create summary report
    report_file = DATA_REPORTS / f"{args.ticker}_{args.year}_summary.txt"
    DATA_REPORTS.mkdir(parents=True, exist_ok=True)
    
    with open(report_file, 'w') as f:
        f.write(f"FinSight Extraction Report\n")
        f.write(f"=" * 70 + "\n\n")
        f.write(f"Company: {args.ticker}\n")
        f.write(f"Year: {args.year}\n")
        f.write(f"Filing Type: {args.filing_type}\n")
        f.write(f"Source File: {filing_path.name}\n")
        f.write(f"Extraction Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write(f"Extraction Results\n")
        f.write(f"-" * 70 + "\n")
        f.write(f"Total Facts Extracted: {len(facts)}\n\n")
        f.write(f"Facts by Taxonomy:\n")
        for taxonomy, count in taxonomy_counts.most_common():
            f.write(f"  {taxonomy}: {count}\n")
        
        f.write(f"\nValidation Results\n")
        f.write(f"-" * 70 + "\n")
        f.write(f"Overall Score: {validation_report.overall_score:.1%}\n")
        f.write(f"Passed: {validation_report.passed}\n")
        f.write(f"Passed Rules: {sum(1 for r in validation_report.results if r.passed)}/{len(validation_report.results)}\n")
        f.write(f"Errors: {len(validation_report.get_errors())}\n")
        f.write(f"Warnings: {len(validation_report.get_warnings())}\n")
        
        f.write(f"\nCompleteness Analysis\n")
        f.write(f"-" * 70 + "\n")
        f.write(f"Overall Completeness: {completeness_report.overall_completeness:.1%}\n")
        f.write(f"Income Statement: {completeness_report.income_statement_completeness:.1%}\n")
        f.write(f"Balance Sheet: {completeness_report.balance_sheet_completeness:.1%}\n")
        f.write(f"Cash Flow: {completeness_report.cash_flow_completeness:.1%}\n")
        f.write(f"\nData Quality:\n")
        f.write(f"  Numeric Values: {completeness_report.facts_with_numeric_values}/{completeness_report.total_facts}\n")
        f.write(f"  With Periods: {completeness_report.facts_with_periods}/{completeness_report.total_facts}\n")
        f.write(f"  With Units: {completeness_report.facts_with_units}/{completeness_report.total_facts}\n")
        f.write(f"  With Dimensions: {completeness_report.facts_with_dimensions}/{completeness_report.total_facts}\n")
        
        f.write(f"\nDocument Metadata:\n")
        f.write(f"  Document Type: {metadata.get('document_type', 'N/A')}\n")
        f.write(f"  Namespaces: {len(metadata.get('namespaces', []))}\n")
    
    print(f"✅ Saved report: {report_file}")
    print()
    
    # Final summary
    duration = (datetime.now() - start_time).total_seconds()
    
    print("=" * 70)
    print("🎉 Extraction Complete!")
    print("=" * 70)
    print(f"Total Facts: {len(facts)}")
    print(f"Duration: {duration:.1f} seconds")
    print(f"Facts/second: {len(facts) / duration:.1f}")
    print()
    print(f"📊 Next steps:")
    print(f"  1. Load to PostgreSQL:")
    print(f"     docker exec superset_db psql -U superset -d finsight -c \"SELECT COUNT(*) FROM financial_facts;\"")
    print(f"  2. View data:")
    print(f"     streamlit run src/ui/data_viewer.py")
    print(f"  3. Connect Superset:")
    print(f"     postgresql://superset:superset@superset_db:5432/finsight")
    print("=" * 70)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

