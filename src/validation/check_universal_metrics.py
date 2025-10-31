#!/usr/bin/env python3
"""
SOLUTION 2: Universal Metrics Validator

Validates that ALL companies report mandatory financial metrics.
These are metrics that EVERY publicly listed company MUST report.

This runs as part of the validation pipeline and HARD FAILS if missing.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from config import DATABASE_URI
from typing import List, Dict, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Universal metrics that EVERY public company MUST report
# NOTE: Use ACTUAL normalized labels from database (check taxonomy_mappings.py)
UNIVERSAL_METRICS = {
    # Balance Sheet
    'total_assets': 'Total Assets',
    'current_liabilities': 'Current Liabilities', 
    'noncurrent_liabilities': 'Noncurrent Liabilities',
    'stockholders_equity': 'Stockholders Equity',
    
    # Income Statement
    'revenue': 'Revenue',
    'net_income': 'Net Income',
    
    # Cash Flow
    'operating_cash_flow': 'Operating Cash Flow',
    
    # Common line items
    'accounts_receivable': 'Accounts Receivable',
    'accounts_payable': 'Accounts Payable',
    'cash_and_equivalents': 'Cash and Cash Equivalents',
}


def check_universal_metrics_completeness(engine) -> Dict[str, Any]:
    """
    Check that all companies report universal metrics.
    
    Returns:
        {
            'passed': bool,
            'missing_by_company': {company: [missing_metrics]},
            'missing_by_metric': {metric: [companies_without_it]},
            'coverage_pct': float
        }
    """
    logger.info("Checking universal metrics completeness...")
    
    with engine.connect() as conn:
        # Get all companies
        result = conn.execute(text("""
        SELECT ticker, company_id
        FROM dim_companies
        WHERE company_id > 0  -- Exclude taxonomy placeholder
        ORDER BY ticker;
        """))
        
        companies = {row[0]: row[1] for row in result}
        
        missing_by_company = {}
        missing_by_metric = {metric: [] for metric in UNIVERSAL_METRICS.keys()}
        
        for ticker, company_id in companies.items():
            # Check each universal metric
            result2 = conn.execute(text("""
            SELECT DISTINCT normalized_label
            FROM fact_financial_metrics f
            JOIN dim_concepts dc ON f.concept_id = dc.concept_id
            WHERE f.company_id = :company_id
              AND f.dimension_id IS NULL
              AND f.value_numeric IS NOT NULL
              AND dc.normalized_label IN :metrics;
            """), {
                'company_id': company_id,
                'metrics': tuple(UNIVERSAL_METRICS.keys())
            })
            
            reported_metrics = {row[0] for row in result2}
            missing_metrics = set(UNIVERSAL_METRICS.keys()) - reported_metrics
            
            if missing_metrics:
                missing_by_company[ticker] = list(missing_metrics)
                for metric in missing_metrics:
                    missing_by_metric[metric].append(ticker)
        
        total_expected = len(companies) * len(UNIVERSAL_METRICS)
        total_missing = sum(len(missing) for missing in missing_by_company.values())
        coverage_pct = (1.0 - total_missing / total_expected) * 100 if total_expected > 0 else 0
        
        return {
            'passed': len(missing_by_company) == 0,
            'missing_by_company': missing_by_company,
            'missing_by_metric': {k: v for k, v in missing_by_metric.items() if v},
            'coverage_pct': coverage_pct,
            'total_companies': len(companies),
            'total_metrics': len(UNIVERSAL_METRICS),
            'expected_total': total_expected,
            'total_missing': total_missing
        }


def main():
    engine = create_engine(DATABASE_URI)
    results = check_universal_metrics_completeness(engine)
    
    print("\n" + "=" * 120)
    print("UNIVERSAL METRICS COMPLETENESS CHECK")
    print("=" * 120)
    print(f"\nCoverage: {results['coverage_pct']:.1f}%")
    print(f"Companies checked: {results['total_companies']}")
    print(f"Universal metrics: {results['total_metrics']}")
    print(f"Missing combinations: {results['total_missing']}/{results['expected_total']}")
    
    if results['missing_by_company']:
        print(f"\n❌ FAILED: {len(results['missing_by_company'])} companies missing universal metrics")
        print("\nMissing by company:")
        for ticker, metrics in results['missing_by_company'].items():
            print(f"  {ticker}: {', '.join(metrics)}")
    
    if results['missing_by_metric']:
        print("\nMissing by metric:")
        for metric, companies in results['missing_by_metric'].items():
            print(f"  {metric}: {len(companies)} companies ({', '.join(companies[:5])})")
    
    if results['passed']:
        print("\n✅ PASSED: All companies report all universal metrics")
    
    return 0 if results['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())

