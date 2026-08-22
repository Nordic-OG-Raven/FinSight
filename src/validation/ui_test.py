#!/usr/bin/env python3
"""
Universal UI Test Module

Tests the API endpoint to verify that financial statements contain:
- Exactly the expected items (no more, no less)
- Items in the correct order
- All items have data (no missing values for all years)

Works for ANY company by querying rel_statement_items instead of hardcoding.
"""

import sys
import os
import requests
import subprocess
import time
import signal
import atexit
import logging
from typing import List, Dict, Optional, Any
from pathlib import Path
from sqlalchemy import create_engine, text
from config import DATABASE_URI

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.validation.checks import ValidationResult, ValidationReport

logger = logging.getLogger(__name__)

# Global variable to track API process
_api_process = None


def build_api_url(api_base: str, endpoint: str) -> str:
    """
    Build API URL using the SAME format as the website.
    Website uses: /api/finsight?path=/api/statements/{ticker}/{year}
    This ensures UITest.py tests the EXACT same endpoint as the website.
    """
    if api_base.endswith('/api/finsight') or '?path=' in api_base:
        # Next.js proxy (SAME AS WEBSITE) - this is the default
        return f"{api_base}?path={endpoint}"
    elif api_base.startswith('http://localhost:5001') or api_base.startswith('https://'):
        # Direct Flask API call (fallback for direct testing)
        return f"{api_base}{endpoint}"
    else:
        # Assume Next.js proxy format
        return f"{api_base}?path={endpoint}"


def check_api_running(api_base: str, timeout: int = 5) -> bool:
    """Check if API is running and responding"""
    try:
        # For Next.js proxy, check the proxy endpoint
        if api_base.endswith('/api/finsight') or '?path=' in api_base:
            # Next.js proxy - check if it can reach the backend
            response = requests.get(f"{api_base}?path=/api/companies", timeout=timeout)
            return response.status_code == 200
        else:
            # Direct Flask API - check /health endpoint
            health_url = f"{api_base}/health" if not api_base.endswith('/health') else api_base
            response = requests.get(health_url, timeout=timeout)
            return response.status_code == 200
    except (requests.exceptions.RequestException, requests.exceptions.Timeout):
        return False


def start_api(api_port: int = 5001) -> subprocess.Popen:
    """Start Flask API in background"""
    script_dir = Path(__file__).parent.parent.parent
    api_main = script_dir / "api" / "main.py"
    
    if not api_main.exists():
        raise FileNotFoundError(f"API file not found: {api_main}")
    
    # Use the same Python interpreter
    python_exe = sys.executable
    
    # Set PORT environment variable for API
    env = os.environ.copy()
    env['PORT'] = str(api_port)
    
    # Start API in background
    # Redirect output to log file
    log_file = script_dir / "api.log"
    with open(log_file, 'w') as f:
        process = subprocess.Popen(
            [python_exe, str(api_main)],
            stdout=f,
            stderr=subprocess.STDOUT,
            cwd=str(script_dir),
            env=env,
            start_new_session=True  # Detach from parent process
        )
    
    print(f"   Started API process (PID: {process.pid})")
    print(f"   Log file: {log_file}")
    return process


def wait_for_api(api_base: str, max_wait: int = 30, check_interval: int = 1) -> bool:
    """Wait for API to become ready"""
    print(f"   Waiting for API to be ready (max {max_wait}s)...")
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        if check_api_running(api_base, timeout=2):
            elapsed = time.time() - start_time
            print(f"   ✅ API is ready (took {elapsed:.1f}s)")
            return True
        time.sleep(check_interval)
    
    print(f"   ❌ API did not become ready within {max_wait}s")
    return False


def ensure_api_running(api_base: str, api_port: int = 5001) -> bool:
    """Ensure API is running, start it if necessary"""
    global _api_process
    
    print(f"\n{'='*80}")
    print("Checking API Status")
    print(f"{'='*80}\n")
    
    # Check if API is already running (try both the specified base and port 5001)
    if check_api_running(api_base, timeout=2):
        print(f"✅ API is already running at {api_base}")
        return True
    
    # Also check if API is running on port 5001 (common case when pipeline starts it)
    if 'localhost:5001' not in api_base:
        if check_api_running("http://localhost:5001", timeout=2):
            print(f"✅ API is running on http://localhost:5001 (updating api_base)")
            return True
    
    # API not running - start it
    print(f"⚠️  API is not running. Starting API on port {api_port}...")
    try:
        _api_process = start_api(api_port)
        
        # Wait for API to be ready
        if wait_for_api(api_base, max_wait=30):
            return True
        else:
            print(f"❌ Failed to start API")
            return False
    except Exception as e:
        print(f"❌ Error starting API: {e}")
        return False


def cleanup_api():
    """Cleanup API process if we started it"""
    global _api_process
    if _api_process:
        try:
            _api_process.terminate()
            _api_process.wait(timeout=5)
            print(f"   Stopped API process (PID: {_api_process.pid})")
        except subprocess.TimeoutExpired:
            _api_process.kill()
            print(f"   Killed API process (PID: {_api_process.pid})")
        except Exception as e:
            print(f"   Error stopping API: {e}")
        _api_process = None


# Register cleanup on exit
atexit.register(cleanup_api)
signal.signal(signal.SIGINT, lambda s, f: (cleanup_api(), sys.exit(0)))
signal.signal(signal.SIGTERM, lambda s, f: (cleanup_api(), sys.exit(0)))


class UniversalUITest:
    """Universal UI test - works for any company"""
    
    def __init__(self, api_base: str = "http://localhost:5001"):
        """
        Initialize universal UI test
        
        Args:
            api_base: API base URL
        """
        self.api_base = api_base
        self.engine = create_engine(DATABASE_URI)
    
    def test_company(self, ticker: str, year: int, statement_types: Optional[List[str]] = None) -> ValidationReport:
        """
        Test API output for any company
        
        Args:
            ticker: Company ticker
            year: Fiscal year
            statement_types: List of statement types to test (default: all)
            
        Returns:
            ValidationReport with test results
        """
        if statement_types is None:
            statement_types = ['income_statement', 'comprehensive_income', 'balance_sheet', 'cash_flow', 'equity_statement']
        
        report = ValidationReport(
            company=ticker,
            filing_type="unknown",
            fiscal_year_end=f"{year}-12-31"
        )
        
        # Ensure API is running
        if not ensure_api_running(self.api_base):
            report.add_result(ValidationResult(
                rule_name="api_available",
                passed=False,
                severity="ERROR",
                message=f"API not available at {self.api_base}"
            ))
            report.calculate_score()
            return report
        
        # Get expected items from rel_statement_items
        expected_items = self._get_expected_items(ticker, year, statement_types)
        
        if not expected_items:
            report.add_result(ValidationResult(
                rule_name="expected_items_found",
                passed=False,
                severity="ERROR",
                message=f"No expected items found in rel_statement_items for {ticker} {year}"
            ))
            report.calculate_score()
            return report
        
        # Call API
        api_data = self._call_api(ticker, year)
        
        if not api_data:
            report.add_result(ValidationResult(
                rule_name="api_response",
                passed=False,
                severity="ERROR",
                message=f"API call failed for {ticker} {year}"
            ))
            report.calculate_score()
            return report
        
        # Validate output for each statement type
        for statement_type in statement_types:
            self._validate_statement(
                statement_type,
                expected_items.get(statement_type, []),
                api_data.get('statements', {}).get(statement_type, []),
                report
            )
        
        report.calculate_score()
        return report
    
    def _get_expected_items(self, ticker: str, year: int, statement_types: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Query rel_statement_items - no hardcoding needed
        
        Returns:
            Dict mapping statement_type to list of expected items with display_order
        """
        expected_items = {stmt_type: [] for stmt_type in statement_types}
        
        with self.engine.connect() as conn:
            query = text("""
                SELECT 
                    si.statement_type,
                    co.preferred_label,
                    co.normalized_label,
                    si.display_order,
                    si.is_header,
                    si.is_main_item,
                    COALESCE(co.hierarchy_level, 0) as hierarchy_level
                FROM rel_statement_items si
                JOIN dim_concepts co ON si.concept_id = co.concept_id
                JOIN dim_filings f ON si.filing_id = f.filing_id
                JOIN dim_companies c ON f.company_id = c.company_id
                WHERE c.ticker = :ticker
                  AND EXTRACT(YEAR FROM f.fiscal_year_end) = :year
                  AND si.statement_type = ANY(:statement_types)
                  AND si.is_main_item = TRUE
                  AND si.is_header = FALSE  -- Exclude headers (API doesn't return them)
                  AND si.display_order < 1000  -- Exclude disclosure items (order_index >= 1000 are disclosures)
                ORDER BY 
                    si.statement_type, 
                    si.display_order,
                    -COALESCE(co.hierarchy_level, 0),  -- DESC (higher levels first, matching API)
                    co.normalized_label  -- Alphabetical tie-breaker (matching API)
            """)
            
            result = conn.execute(query, {
                'ticker': ticker,
                'year': year,
                'statement_types': statement_types
            })
            
            for row in result:
                statement_type, preferred_label, normalized_label, display_order, is_header, is_main_item, hierarchy_level = row
                if statement_type in expected_items:
                    expected_items[statement_type].append({
                        'preferred_label': preferred_label or normalized_label,
                        'normalized_label': normalized_label,
                        'display_order': display_order,
                        'is_header': is_header,
                        'is_main_item': is_main_item,
                        'hierarchy_level': hierarchy_level
                    })
        
        return expected_items
    
    def _call_api(self, ticker: str, year: int) -> Optional[Dict[str, Any]]:
        """Call API endpoint"""
        url = build_api_url(self.api_base, f"/api/statements/{ticker}/{year}")
        
        try:
            response = requests.get(url, timeout=120)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            logger.error(f"API request timed out after 120s")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            return None
    
    def _validate_statement(
        self,
        statement_type: str,
        expected_items: List[Dict[str, Any]],
        api_items: List[Dict[str, Any]],
        report: ValidationReport
    ):
        """Compare expected items with API output"""
        if not expected_items:
            report.add_result(ValidationResult(
                rule_name=f"{statement_type}_expected_items",
                passed=True,
                severity="INFO",
                message=f"No expected items defined for {statement_type}"
            ))
            return
        
        if not api_items:
            report.add_result(ValidationResult(
                rule_name=f"{statement_type}_api_items",
                passed=False,
                severity="ERROR",
                message=f"No items returned from API for {statement_type}"
            ))
            return
        
        # Group API items by normalized_label (API returns one item per year).
        # Headers/spacers are deliberately included in the API response (they're used for
        # frontend section rendering — confirmed in api/main.py's get_financial_statements,
        # "Headers are already in fact tables with is_header=True... no post-processing
        # needed"), but _get_expected_items() above deliberately excludes them (matching
        # what a real financial statement's line items are, not its visual structure).
        # Filter them out here too so the missing/extra comparison is on the same set both
        # sides use — the order-comparison logic below already does this same filtering;
        # this used to be inconsistent with it, producing "extra" items for every header
        # and spacer, confirmed for NVO's balance_sheet/comprehensive_income/
        # equity_statement. See docs/NVO_GOLDEN_PATH_2026-08.md item 4.
        def _is_header_or_spacer(normalized_label: str) -> bool:
            return (
                normalized_label.endswith('_header')
                or normalized_label.endswith('_space1')
                or normalized_label.endswith('_space2')
                or 'space' in normalized_label.lower()
            )

        api_items_by_label = {}
        for item in api_items:
            normalized = item.get('normalized_label', '')
            if _is_header_or_spacer(normalized):
                continue
            if normalized not in api_items_by_label:
                api_items_by_label[normalized] = []
            api_items_by_label[normalized].append(item)

        # Check for missing items
        expected_labels = {item['normalized_label'] for item in expected_items}
        api_labels = set(api_items_by_label.keys())
        missing_labels = expected_labels - api_labels
        extra_labels = api_labels - expected_labels
        
        # Check item order
        # CRITICAL: API response is already sorted by presentation_order_index, hierarchy_level, normalized_label
        # We should use the API's order directly instead of re-sorting to avoid order mismatches
        # Get unique normalized labels in API order (first occurrence of each label)
        api_labels_ordered = []
        seen = set()
        for item in api_items:  # API items are already sorted
            normalized = item.get('normalized_label', '')
            if normalized not in seen and not _is_header_or_spacer(normalized):
                api_labels_ordered.append(normalized)
                seen.add(normalized)
        
        # Compare order with expected
        expected_labels_ordered = [item['normalized_label'] for item in expected_items]
        order_correct = api_labels_ordered == expected_labels_ordered
        
        # Collect detailed order issues
        order_issues = []
        if not order_correct:
            # Find items in wrong position
            expected_positions = {label: idx for idx, label in enumerate(expected_labels_ordered)}
            api_positions = {label: idx for idx, label in enumerate(api_labels_ordered)}
            
            # Check each expected item
            for expected_label in expected_labels_ordered:
                if expected_label in api_positions:
                    expected_pos = expected_positions[expected_label]
                    actual_pos = api_positions[expected_label]
                    if expected_pos != actual_pos:
                        order_issues.append({
                            'item': expected_label,
                            'expected_position': expected_pos,
                            'actual_position': actual_pos
                        })
        
        # Check for missing values (items with no data for any year)
        missing_values = []
        for normalized in expected_labels:
            if normalized in api_items_by_label:
                items = api_items_by_label[normalized]
                # Check if any item has a value
                has_value = any(item.get('value') is not None for item in items)
                if not has_value:
                    missing_values.append(normalized)
        
        # Check value mismatches (compare expected vs actual values from rel_statement_items)
        # This is a simplified check - for detailed value validation, use the old UITest.py logic
        value_mismatches = []
        # Note: Detailed value mismatch checking would require expected values from rel_statement_items
        # or fact tables. For now, we only flag items with missing values.
        
        # Build result
        issues = []
        if missing_labels:
            issues.append(f"{len(missing_labels)} missing items")
        if extra_labels:
            issues.append(f"{len(extra_labels)} extra items")
        if not order_correct:
            issues.append("incorrect order")
        if missing_values:
            issues.append(f"{len(missing_values)} items with missing values")
        
        passed = len(issues) == 0
        
        report.add_result(ValidationResult(
            rule_name=f"{statement_type}_validation",
            passed=passed,
            severity="ERROR" if not passed else "INFO",
            message=f"{statement_type}: {', '.join(issues) if issues else 'all checks passed'}",
            details={
                'expected_count': len(expected_items),
                'api_count': len(api_labels),
                'missing_labels': list(missing_labels)[:10],  # First 10
                'extra_labels': list(extra_labels)[:10],  # First 10
                'missing_values': missing_values[:10],  # First 10
                'order_correct': order_correct,
                'order_issues': order_issues[:20],  # First 20 order issues
                'value_mismatches': value_mismatches[:20]  # First 20 value mismatches
            }
        ))


def test_company(ticker: str, year: int, api_base: str = "http://localhost:5001", 
                 statement_types: Optional[List[str]] = None) -> ValidationReport:
    """
    Convenience function to test a company
    
    Args:
        ticker: Company ticker
        year: Fiscal year
        api_base: API base URL
        statement_types: List of statement types to test (default: all)
        
    Returns:
        ValidationReport
    """
    tester = UniversalUITest(api_base=api_base)
    return tester.test_company(ticker, year, statement_types)


def main():
    """Main CLI entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Universal UI Test for FinSight API")
    parser.add_argument("--api-base", default="http://localhost:5001", help="API base URL")
    parser.add_argument("--api-port", type=int, default=5001, help="API port (for starting API)")
    parser.add_argument("--ticker", default="NVO", help="Company ticker")
    parser.add_argument("--year", type=int, default=2024, help="Filing year")
    parser.add_argument("--test", choices=["income", "comprehensive", "balance", "cashflow", "equity", "all"], 
                       default="all", help="Which test(s) to run")
    parser.add_argument("--keep-api", action="store_true", help="Keep API running after test")
    
    args = parser.parse_args()
    
    # Map test names to statement types
    test_map = {
        'income': ['income_statement'],
        'comprehensive': ['comprehensive_income'],
        'balance': ['balance_sheet'],
        'cashflow': ['cash_flow'],
        'equity': ['equity_statement'],
        'all': None  # None means all
    }
    
    statement_types = test_map.get(args.test)
    
    # Run test
    report = test_company(
        ticker=args.ticker,
        year=args.year,
        api_base=args.api_base,
        statement_types=statement_types
    )
    
    # Print results
    print(f"\n{'='*80}")
    print(f"UI Test Results for {args.ticker} {args.year}")
    print(f"{'='*80}\n")
    print(f"Overall Score: {report.overall_score:.1%}")
    print(f"Passed: {'✅ YES' if report.passed else '❌ NO'}\n")
    
    for result in report.results:
        status = "✅" if result.passed else "❌"
        print(f"{status} {result.rule_name}: {result.message}")
        if result.details:
            if result.details.get('missing_labels'):
                print(f"   Missing: {', '.join(result.details['missing_labels'][:5])}")
            if result.details.get('extra_labels'):
                print(f"   Extra: {', '.join(result.details['extra_labels'][:5])}")
    
    # Cleanup if requested
    if not args.keep_api:
        cleanup_api()
    
    # Exit with error code if test failed
    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()

