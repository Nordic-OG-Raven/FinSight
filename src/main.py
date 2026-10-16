#!/usr/bin/env python3
"""
FinSight Main CLI — single-filing entrypoint on the edgartools extraction path.

Extract + validate + load one filing's XBRL into the PostgreSQL star schema. This is the
documented single-company entrypoint (`python src/main.py --ticker AVGO`);
`database/load_from_edgartools.py` is the batch loader and owns `StarSchemaLoader`, which this
reuses so there is one loader implementation.

The retired Arelle pipeline (fetch_sec → parse_xbrl → load_financial_data) was removed in the
2026-10 re-architecture — see docs/REARCHITECTURE.md. `run_pipeline()` keeps its signature so
the Flask API and existing callers keep working.
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DATABASE_URL
from src.extraction.edgartools_adapter import EdgarToolsExtractor
from database.load_from_edgartools import StarSchemaLoader
from src.validation.quality import write_report

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).resolve().parent.parent / "data" / "quality_reports"


def run_pipeline(ticker: str, year: int = None, filing_type: str = None) -> bool:
    """Extract → validate → load one filing via edgartools.

    Returns True iff the quality hard-gates passed (and the data was therefore persisted).
    `year` is accepted for backward compatibility but ignored — the edgartools path always
    loads the latest annual filing. Used by the Flask API for programmatic access.
    """
    try:
        if year is not None:
            logger.info(
                f"{ticker}: year={year} is informational — the edgartools path loads the "
                "latest annual filing (10-K/20-F/40-F)."
            )
        result = EdgarToolsExtractor().extract(ticker, filing_type=filing_type)
        loader = StarSchemaLoader(DATABASE_URL)
        try:
            n, report = loader.load(result)
        finally:
            loader.close()
        write_report(report, REPORT_DIR)
        if report.passed:
            logger.info(
                f"{ticker}: loaded {n} facts from {report.form} (FYE {report.fiscal_year_end}, "
                f"{report.currency}); quality={report.scores.get('overall')}"
            )
        else:
            logger.error(
                f"{ticker}: FAILED hard gates — not loaded. "
                + "; ".join(w for w in report.warnings if "HARD-GATE" in w)
            )
        return report.passed
    except Exception as e:
        logger.error(f"{ticker}: pipeline error: {type(e).__name__}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="FinSight — extract, validate, and load one filing (edgartools path)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python src/main.py --ticker AVGO              # latest annual report, auto-detected form
  python src/main.py --ticker NVO --filing-type 20-F
""",
    )
    parser.add_argument('--ticker', required=True, help='Stock ticker symbol')
    parser.add_argument('--filing-type', default=None,
                        help='10-K / 20-F / 40-F. Default: auto-detect the latest annual report')
    # Accepted for backward compatibility; ignored (the latest annual filing is always loaded).
    parser.add_argument('--year', type=int, default=None,
                        help='Accepted for compatibility; ignored (latest annual is loaded)')
    parser.add_argument('--skip-download', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--output', default=None, help=argparse.SUPPRESS)
    parser.add_argument('--save-json', action='store_true', default=True, help=argparse.SUPPRESS)
    parser.add_argument('--verbose', '-v', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    print("=" * 70)
    print("🔍 FinSight — extract · validate · load  (edgartools path)")
    print(f"Company: {args.ticker}" + (f"   Filing: {args.filing_type}" if args.filing_type else ""))
    print("=" * 70)

    ok = run_pipeline(args.ticker, year=args.year, filing_type=args.filing_type)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
