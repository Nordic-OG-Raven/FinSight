#!/usr/bin/env python3
"""
UI Test Script for FinSight Financial Statements

Tests the API endpoint to verify that financial statements contain:
- Exactly the expected items (no more, no less)
- Items in the correct order
- All items have data (no missing values for all years)

Automatically starts the Flask API if it's not running.
"""

import sys
import os
import requests
import json
import subprocess
import time
import signal
import atexit
from typing import List, Dict, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Global variable to track API process
_api_process = None

# Expected items for Novo Nordisk Income Statement (in exact order)
EXPECTED_NOVO_INCOME_STATEMENT = [
    "Net sales",  # revenue
    "Cost of goods sold",  # cost_of_sales
    "Gross profit",  # gross_profit
    "Sales and distribution costs",  # selling_expense_and_distribution_costs
    "Research and development costs",  # research_development
    "Administrative costs",  # administrative_expense
    "Other operating income and expenses",  # other_operating_income_expense
    "Operating profit",  # operating_income
    "Financial income",  # finance_income
    "Financial expenses",  # finance_costs
    "Profit before income taxes",  # income_before_tax
    "Income taxes",  # income_tax_expense_continuing_operations
    "Net profit",  # net_income_including_noncontrolling_interest or net_profit
    "Earnings per share",  # header (synthetic or from XBRL)
    "Basic earnings per share",  # basic_earnings_loss_per_share
    "Diluted earnings per share",  # diluted_earnings_loss_per_share
]

# Expected items for Novo Nordisk Comprehensive Income Statement (in exact order)
# Based on Novo's 2024 annual report structure
# Note: Includes actual line items, category headers/subtotals, and spacing as they appear in the report
EXPECTED_NOVO_COMPREHENSIVE_INCOME = [
    "Net profit",
    "",  # space
    "Other comprehensive income",  # header
    "Remeasurements of retirement benefit obligations",
    "Items that will not be reclassified subsequently to the income statement",
    "",  # space
    "Exchange rate adjustments of investments in subsidiaries",
    "Cash flow hedges",  # header
    "Realisation of previously deferred (gains)/losses",
    "Deferred gains/(losses) related to acquisition of businesses",
    "Deferred gains/(losses) on hedges open at year-end",
    "Tax and other items",
    "Items that will be reclassified subsequently to the income statement",
    "",  # space
    "Other comprehensive income",
    "Total comprehensive income",
]

# Expected items for Novo Nordisk Balance Sheet (in exact order)
# Based on Novo's 2024 annual report structure
# Left side (Assets) and Right side (Equity and Liabilities)
EXPECTED_NOVO_BALANCE_SHEET_ASSETS = [
    "Assets",  # header
    "Intangible assets",
    "Property, plant and equipment",
    "Investments in associated companies",
    "Deferred income tax assets",
    "Other receivables and prepayments",
    "Other financial assets",
    "Total non-current assets",
    "Inventories",
    "Trade receivables",
    "Tax receivables",
    "Other receivables and prepayments",
    "Marketable securities",
    "Derivative financial instruments",
    "Cash at bank",
    "Total current assets",
    "Total assets",
]

EXPECTED_NOVO_BALANCE_SHEET_LIABILITIES_EQUITY = [
    "Equity and liabilities",  # header
    "Share capital",
    "Treasury shares",
    "Retained earnings",
    "Other reserves",
    "Total equity",
    "Borrowings",
    "Deferred income tax liabilities",
    "Retirement benefit obligations",
    "Other liabilities",
    "Provisions",
    "Total non-current liabilities",
    "Borrowings",
    "Trade payables",
    "Tax payables",
    "Other liabilities",
    "Derivative financial instruments",
    "Provisions",
    "Total current liabilities",
    "Total liabilities",
    "Total equity and liabilities",
]

# Expected items for Novo Nordisk Cash Flow Statement (in exact order)
# Based on Novo's 2024 annual report structure
EXPECTED_NOVO_CASH_FLOW = [
    "Net profit",
    "Adjustment of non-cash items",  # header
    "Income taxes in the income statement",
    "Depreciation, amortisation and impairment losses",
    "Other non-cash items",
    "Changes in working capital",
    "Interest received",
    "Interest paid",
    "Income taxes paid",
    "Net cash flows from operating activities",
    "Purchase of intangible assets",
    "Purchase of property, plant and equipment",
    "Cash used for acquisition of businesses",
    "Proceeds from other financial assets",
    "Purchase of other financial assets",
    "Purchase of marketable securities",
    "Sale of marketable securities",
    "Net cash flows from investing activities",
    "Purchase of treasury shares",
    "Dividends paid",
    "Proceeds from borrowings",
    "Repayment of borrowings",
    "Net cash flows from financing activities",
    "Net cash generated from activities",
    "Cash and cash equivalents at the beginning of the year",
    "Exchange gains/(losses) on cash and cash equivalents",
    "Cash and cash equivalents at the end of the year",
]

# Expected items for Novo Nordisk Statement of Changes in Equity (in exact order)
# Based on Novo's 2024 annual report structure (IFRS/EU style)
# Note: This is a matrix-style statement with columns for each equity component
# Includes spaces as they appear in the report
EXPECTED_NOVO_EQUITY_STATEMENT = [
    "Balance at the beginning of the year",
    "Net profit",
    "",  # space
    "Other comprehensive income",
    "Total comprehensive income",
    "Transfer of cash flow hedge reserve to intangible assets",  # Note: label may vary slightly
    "",  # space
    "Transactions with owners",  # header (should NOT say "header" in the label)
    "Dividends",
    "Share-based payments",
    "Purchase of treasury shares",
    "Reduction of the B share capital",
    "Tax related to transactions with owners",
    "Balance at the end of the year",
]

# Expected items for US-GAAP Statement of Changes in Equity (in exact order)
# Based on US-GAAP standard structure
EXPECTED_US_EQUITY_STATEMENT = [
    "Balance at the beginning of the year",
    "Net income",  # US uses "Net income" instead of "Net profit"
    "Other comprehensive income",
    "Total comprehensive income",
    "Common stock transactions",  # US typically groups by equity component
    "Treasury stock transactions",
    "Retained earnings changes",
    "Other equity changes",
    "Balance at the end of the year",
]

# Expected values for Novo Nordisk Comprehensive Income (2024, 2023, 2022) in DKK millions
# Values from Novo's 2024 annual report
EXPECTED_NOVO_COMPREHENSIVE_INCOME_VALUES = {
    "Net profit": {
        2024: 100988,
        2023: 83683,
        2022: 55525
    },
    "Remeasurements of retirement benefit obligations": {
        2024: -119,
        2023: 13,
        2022: 615
    },
    "Items that will not be reclassified subsequently to the income statement": {
        2024: -119,
        2023: 13,
        2022: 615
    },
    "Exchange rate adjustments of investments in subsidiaries": {
        2024: 3096,
        2023: -1404,
        2022: 2289
    },
    "Realisation of previously deferred (gains)/losses": {
        2024: -1612,
        2023: -1026,
        2022: 1740
    },
    "Deferred gains/(losses) related to acquisition of businesses": {
        2024: 1154,
        2023: 0,  # Dash in report, treated as 0
        2022: 0  # Dash in report, treated as 0
    },
    "Deferred gains/(losses) on hedges open at year-end": {
        2024: -5763,
        2023: 1612,
        2022: 1026
    },
    "Tax and other items": {
        2024: 1343,
        2023: -355,
        2022: -892
    },
    "Items that will be reclassified subsequently to the income statement": {
        2024: -1782,
        2023: -1173,
        2022: 4163
    },
    "Other comprehensive income": {
        2024: -1901,
        2023: -1160,
        2022: 4778
    },
    "Total comprehensive income": {
        2024: 99087,
        2023: 82523,
        2022: 60303
    },
}


def humanize_label(label: str, statement_type: str = "income_statement") -> str:
    """Convert normalized_label to human-readable format matching Novo report"""
    # Map normalized labels to Novo report labels
    label_map = {
        # Income statement
        "revenue": "Net sales",
        "cost_of_sales": "Cost of goods sold",
        "gross_profit": "Gross profit",
        "selling_expense_and_distribution_costs": "Sales and distribution costs",
        "research_development": "Research and development costs",
        "administrative_expense": "Administrative costs",
        "other_operating_income_expense": "Other operating income and expenses",
        "operating_income": "Operating profit",
        "finance_income": "Financial income",
        "finance_costs": "Financial expenses",
        "income_before_tax": "Profit before income taxes",
        "income_tax_expense_continuing_operations": "Income taxes",
        "net_income_including_noncontrolling_interest": "Net profit",
        "earnings_per_share_header": "Earnings per share",
        "basic_earnings_loss_per_share": "Basic earnings per share",
        "diluted_earnings_loss_per_share": "Diluted earnings per share",
        # Comprehensive income
        "other_comprehensive_income_net_of_tax_exchange_differences_on_translation": "Exchange rate adjustments of investments in subsidiaries",
        "other_comprehensive_income_net_of_tax_gains_losses_on_remeasurements_of_defined_benefit_plans": "Remeasurements of retirement benefit obligations",
        "reclassification_adjustments_on_cash_flow_hedges_before_tax": "Realisation of previously deferred (gains)/losses",
        "other_comprehensive_income_that_will_not_be_reclassified_to_profit_or_loss_before_tax": "Items that will not be reclassified subsequently to the income statement",
        "income_tax_and_other_relating_to_components_of_other_comprehensive_income": "Tax and other items",
        "other_comprehensive_income_that_will_be_reclassified_to_profit_or_loss_net_of_tax": "Items that will be reclassified subsequently to the income statement",
        "comprehensive_income": "Total comprehensive income",
        "gains_losses_on_cash_flow_hedges_before_tax": "Deferred gains/(losses) on hedges open at year-end",
        "gains_losses_on_cash_flow_hedges_related_to_acquisition_of_businesses": "Deferred gains/(losses) related to acquisition of businesses",
        "oci_total": "Other comprehensive income",
    }
    
    # Check exact match first
    if label in label_map:
        return label_map[label]
    
    # Handle special cases
    if label == "earnings_per_share_header":
        return "Earnings per share"
    
    # Convert snake_case to Title Case as fallback
    return label.replace("_", " ").title()


def normalize_label_for_matching(label: str) -> str:
    """Normalize label for matching (lowercase, remove special chars)"""
    return label.lower().replace("_", " ").replace("-", " ").strip()


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
            # Direct Flask API
            response = requests.get(f"{api_base}/health", timeout=timeout)
            return response.status_code == 200
    except (requests.exceptions.RequestException, requests.exceptions.Timeout):
        return False


def start_api(api_port: int = 5001) -> subprocess.Popen:
    """Start Flask API in background"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    api_main = os.path.join(script_dir, "api", "main.py")
    
    if not os.path.exists(api_main):
        raise FileNotFoundError(f"API file not found: {api_main}")
    
    # Use the same Python interpreter
    python_exe = sys.executable
    
    # Set PORT environment variable for API
    env = os.environ.copy()
    env['PORT'] = str(api_port)
    
    # Start API in background
    # Redirect output to log file
    log_file = os.path.join(script_dir, "api.log")
    with open(log_file, 'w') as f:
        process = subprocess.Popen(
            [python_exe, api_main],
            stdout=f,
            stderr=subprocess.STDOUT,
            cwd=script_dir,
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
    
    # Check if API is already running
    if check_api_running(api_base, timeout=2):
        print(f"✅ API is already running at {api_base}")
        return True
    
    print(f"⚠️  API is not running at {api_base}")
    print(f"   Starting API on port {api_port}...")
    
    try:
        # Start API
        _api_process = start_api(api_port)
        
        # Wait for API to be ready
        if wait_for_api(api_base):
            # Register cleanup function
            atexit.register(cleanup_api)
            return True
        else:
            print(f"   ❌ Failed to start API")
            if _api_process:
                _api_process.terminate()
                _api_process.wait(timeout=5)
            return False
            
    except Exception as e:
        print(f"   ❌ Error starting API: {e}")
        if _api_process:
            try:
                _api_process.terminate()
                _api_process.wait(timeout=5)
            except:
                pass
        return False


def cleanup_api():
    """Clean up API process on exit"""
    global _api_process
    if _api_process:
        print(f"\n{'='*80}")
        print("Cleaning up API process")
        print(f"{'='*80}\n")
        try:
            print(f"   Terminating API process (PID: {_api_process.pid})...")
            _api_process.terminate()
            _api_process.wait(timeout=5)
            print(f"   ✅ API process terminated")
        except subprocess.TimeoutExpired:
            print(f"   ⚠️  API process did not terminate gracefully, killing...")
            _api_process.kill()
            _api_process.wait()
            print(f"   ✅ API process killed")
        except Exception as e:
            print(f"   ⚠️  Error cleaning up API process: {e}")
        _api_process = None


def test_income_statement(api_base: str, ticker: str = "NVO", year: int = 2024) -> Dict:
    """
    Test income statement endpoint and verify items
    
    Returns:
        Dict with test results
    """
    print(f"\n{'='*80}")
    print(f"Testing Income Statement for {ticker} {year}")
    print(f"{'='*80}\n")
    
    # Call API - MUST use EXACT same endpoint as website
    url = build_api_url(api_base, f"/api/statements/{ticker}/{year}")
    print(f"Calling: {url} (same endpoint as website)")
    
    try:
        print(f"Making request (timeout: 120s)...")
        response = requests.get(url, timeout=120)
        print(f"Response status: {response.status_code}")
        response.raise_for_status()
        data = response.json()
        print(f"Response received: {len(data.get('statements', {}).get('income_statement', []))} income statement items")
    except requests.exceptions.Timeout as e:
        return {
            "success": False,
            "error": f"API request timed out after 120s: {e}",
            "items_found": [],
            "items_missing": EXPECTED_NOVO_INCOME_STATEMENT.copy(),
            "items_extra": [],
            "order_correct": False
        }
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": f"API request failed: {e}",
            "items_found": [],
            "items_missing": EXPECTED_NOVO_INCOME_STATEMENT.copy(),
            "items_extra": [],
            "order_correct": False
        }
    
    # Get income statement items
    income_statement = data.get("statements", {}).get("income_statement", [])
    
    if not income_statement:
        return {
            "success": False,
            "error": "No income statement items returned",
            "items_found": [],
            "items_missing": EXPECTED_NOVO_INCOME_STATEMENT.copy(),
            "items_extra": [],
            "order_correct": False
        }
    
    # CRITICAL: Check for NULL presentation_order_index values
    null_order_items = []
    for item in income_statement:
        if item.get("presentation_order_index") is None:
            null_order_items.append(item.get("normalized_label", "N/A"))
    
    if null_order_items:
        print(f"\n❌ CRITICAL ERROR: {len(null_order_items)} items have NULL presentation_order_index:")
        for label in null_order_items[:10]:  # Show first 10
            print(f"   - {label}")
        if len(null_order_items) > 10:
            print(f"   ... and {len(null_order_items) - 10} more")
        print("\n   This will cause incorrect ordering in the UI!")
    
    # CRITICAL: Verify items are actually sorted by presentation_order_index
    # Check if the API response is sorted correctly
    order_issues_in_response = []
    prev_order = None
    prev_label = None
    for i, item in enumerate(income_statement):
        order = item.get("presentation_order_index")
        label = item.get("normalized_label", "N/A")
        if order is not None and prev_order is not None:
            if order < prev_order:
                order_issues_in_response.append({
                    "position": i,
                    "item": label,
                    "order": order,
                    "prev_item": prev_label,
                    "prev_order": prev_order
                })
        prev_order = order
        prev_label = label
    
    if order_issues_in_response:
        print(f"\n❌ CRITICAL ERROR: API response is NOT sorted correctly!")
        print(f"   Found {len(order_issues_in_response)} ordering violations:")
        for issue in order_issues_in_response[:5]:  # Show first 5
            print(f"   - Position {issue['position']}: {issue['item']} (order={issue['order']}) comes after {issue['prev_item']} (order={issue['prev_order']})")
        if len(order_issues_in_response) > 5:
            print(f"   ... and {len(order_issues_in_response) - 5} more violations")
        print("\n   The API is returning items in the wrong order!")
    
    # Extract labels from API response
    # Group items by normalized_label (since API returns one item per year)
    api_items_by_normalized = {}
    for item in income_statement:
        normalized = item.get("normalized_label", "")
        if normalized not in api_items_by_normalized:
            api_items_by_normalized[normalized] = []
        api_items_by_normalized[normalized].append(item)
    
    # Convert to humanized labels (one per normalized_label)
    # CRITICAL: Sort by presentation_order_index to match expected order
    api_labels = []
    api_items_by_label = {}
    api_items_with_order = []
    for normalized, items in api_items_by_normalized.items():
        humanized = humanize_label(normalized, "income_statement")
        first_item = items[0]  # Use the first item for metadata
        order = first_item.get("presentation_order_index", 999999)
        api_items_with_order.append({
            "normalized": normalized,
            "humanized": humanized,
            "order": order,
            "item": first_item
        })
    
    # Sort by presentation_order_index (this is how frontend should sort)
    api_items_with_order.sort(key=lambda x: (
        x["order"] if x["order"] != 999999 else 999999,
        x["normalized"]
    ))
    
    # Build final lists
    for item_data in api_items_with_order:
        api_labels.append(item_data["humanized"])
        api_items_by_label[item_data["humanized"]] = item_data["item"]
    
    print(f"\nFound {len(api_labels)} unique items in API response (sorted by presentation_order_index):\n")
    for i, item_data in enumerate(api_items_with_order, 1):
        item = item_data["item"]
        order = item_data["order"]
        label = item_data["humanized"]
        values = []
        for year_val in [2024, 2023, 2022]:
            # Check if item has data for this year
            matching_item = next((it for it in api_items_by_normalized[item_data["normalized"]] if it.get("period_year") == year_val), None)
            if matching_item:
                val = matching_item.get("value")
                values.append(f"{year_val}: {val if val is not None else '—'}")
        order_display = order if order != 999999 else "NULL"
        print(f"  {i:2}. order={order_display:6} | {label}")
        if values:
            print(f"      {', '.join(values)}")
        else:
            print(f"      (no data)")
    
    # Check for expected items
    print(f"\n{'='*80}")
    print("VERIFICATION RESULTS")
    print(f"{'='*80}\n")
    
    items_found = []
    items_missing = []
    items_extra = []
    
    # Check each expected item
    for expected_label in EXPECTED_NOVO_INCOME_STATEMENT:
        # Try to find matching item
        found = False
        for api_label in api_labels:
            # Normalize for comparison
            expected_norm = normalize_label_for_matching(expected_label)
            api_norm = normalize_label_for_matching(api_label)
            
            # Check if labels match
            if expected_norm == api_norm:
                found = True
                items_found.append({
                    "expected": expected_label,
                    "found": api_label,
                    "position_expected": EXPECTED_NOVO_INCOME_STATEMENT.index(expected_label) + 1,
                    "position_actual": api_labels.index(api_label) + 1
                })
                break
        
        if not found:
            items_missing.append(expected_label)
    
    # Check for extra items (items in API but not expected)
    for api_label in api_labels:
        found_in_expected = False
        for expected_label in EXPECTED_NOVO_INCOME_STATEMENT:
            expected_norm = normalize_label_for_matching(expected_label)
            api_norm = normalize_label_for_matching(api_label)
            if expected_norm == api_norm:
                found_in_expected = True
                break
        
        if not found_in_expected:
            items_extra.append(api_label)
    
    # Check order
    order_correct = True
    order_issues = []
    for item_info in items_found:
        expected_pos = item_info["position_expected"]
        actual_pos = item_info["position_actual"]
        if expected_pos != actual_pos:
            order_correct = False
            order_issues.append({
                "item": item_info["expected"],
                "expected_position": expected_pos,
                "actual_position": actual_pos
            })
    
    # Print results
    print(f"✅ Items Found: {len(items_found)}/{len(EXPECTED_NOVO_INCOME_STATEMENT)}")
    if items_found:
        print("   Found items:")
        for item_info in items_found:
            pos_match = "✅" if item_info["position_expected"] == item_info["position_actual"] else "❌"
            print(f"   {pos_match} {item_info['expected']} (expected pos: {item_info['position_expected']}, actual pos: {item_info['position_actual']})")
    
    if items_missing:
        print(f"\n❌ Items Missing: {len(items_missing)}")
        for item in items_missing:
            print(f"   - {item}")
    
    if items_extra:
        print(f"\n❌ Extra Items (not expected): {len(items_extra)}")
        for item in items_extra:
            print(f"   - {item}")
    
    if order_issues:
        print(f"\n❌ Order Issues: {len(order_issues)}")
        for issue in order_issues:
            print(f"   - {issue['item']}: expected position {issue['expected_position']}, actual position {issue['actual_position']}")
    
    # Overall result
    # CRITICAL: Test fails if there are NULL presentation_order_index values or ordering issues
    has_critical_errors = len(null_order_items) > 0 or len(order_issues_in_response) > 0
    success = (
        not has_critical_errors and
        len(items_found) == len(EXPECTED_NOVO_INCOME_STATEMENT) and
        len(items_missing) == 0 and
        len(items_extra) == 0 and
        order_correct
    )
    
    print(f"\n{'='*80}")
    if success:
        print("✅ TEST PASSED: All items present, correct order, no extra items")
    else:
        print("❌ TEST FAILED: Issues found (see above)")
    print(f"{'='*80}\n")
    
    return {
        "success": success,
        "items_found": items_found,
        "items_missing": items_missing,
        "items_extra": items_extra,
        "order_correct": order_correct,
        "order_issues": order_issues,
        "null_order_items": null_order_items,
        "order_issues_in_response": order_issues_in_response,
        "total_items_expected": len(EXPECTED_NOVO_INCOME_STATEMENT),
        "total_items_found": len(api_labels)
    }


def test_comprehensive_income(api_base: str, ticker: str = "NVO", year: int = 2024) -> Dict:
    """
    Test comprehensive income statement endpoint and verify items and values
    
    Returns:
        Dict with test results
    """
    print(f"\n{'='*80}")
    print(f"Testing Comprehensive Income Statement for {ticker} {year}")
    print(f"{'='*80}\n")
    
    # Call API - MUST use EXACT same endpoint as website
    url = build_api_url(api_base, f"/api/statements/{ticker}/{year}")
    print(f"Calling: {url} (same endpoint as website)")
    
    try:
        print(f"Making request (timeout: 120s)...")
        response = requests.get(url, timeout=120)
        print(f"Response status: {response.status_code}")
        response.raise_for_status()
        data = response.json()
        comprehensive_income = data.get("statements", {}).get("comprehensive_income", [])
        print(f"Response received: {len(comprehensive_income)} comprehensive income items")
    except requests.exceptions.Timeout as e:
        return {
            "success": False,
            "error": f"API request timed out after 120s: {e}",
            "items_found": [],
            "items_missing": EXPECTED_NOVO_COMPREHENSIVE_INCOME.copy(),
            "items_extra": [],
            "values_correct": False
        }
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": f"API request failed: {e}",
            "items_found": [],
            "items_missing": EXPECTED_NOVO_COMPREHENSIVE_INCOME.copy(),
            "items_extra": [],
            "values_correct": False
        }
    
    if not comprehensive_income:
        return {
            "success": False,
            "error": "No comprehensive income items returned",
            "items_found": [],
            "items_missing": EXPECTED_NOVO_COMPREHENSIVE_INCOME.copy(),
            "items_extra": [],
            "values_correct": False
        }
    
    # Extract labels from API response
    # Use preferred_label from API (LASTING - populated during ETL)
    api_items_by_normalized = {}
    for item in comprehensive_income:
        normalized = item.get("normalized_label", "")
        if normalized not in api_items_by_normalized:
            api_items_by_normalized[normalized] = []
        api_items_by_normalized[normalized].append(item)
    
    # Convert to labels using preferred_label from API, fallback to humanize
    api_items_with_order = []
    for normalized, items in api_items_by_normalized.items():
        first_item = items[0]
        # Use preferred_label from API (LASTING - from database)
        preferred_label = first_item.get("preferred_label")
        if preferred_label:
            humanized = preferred_label
        else:
            # Fallback to humanize if preferred_label not available
            humanized = humanize_label(normalized, "comprehensive_income")
        order = first_item.get("presentation_order_index", 999999)
        api_items_with_order.append({
            "normalized": normalized,
            "humanized": humanized,
            "order": order,
            "items": items
        })
    
    # Sort by presentation_order_index
    api_items_with_order.sort(key=lambda x: (
        x["order"] if x["order"] != 999999 else 999999,
        x["normalized"]
    ))
    
    # Build final lists
    api_labels = [item["humanized"] for item in api_items_with_order]
    api_items_by_label = {item["humanized"]: item["items"] for item in api_items_with_order}
    
    print(f"\nFound {len(api_labels)} unique items in API response (sorted by presentation_order_index):\n")
    for i, item_data in enumerate(api_items_with_order, 1):
        order = item_data["order"]
        label = item_data["humanized"]
        values = []
        for year_val in [2024, 2023, 2022]:
            matching_item = next((it for it in item_data["items"] if it.get("period_year") == year_val), None)
            if matching_item:
                val = matching_item.get("value")
                unit = matching_item.get("unit", "")
                # Convert to millions for display (DKK values are in base units)
                if val is not None and unit and "DKK" in unit.upper():
                    val_millions = val / 1e6
                    values.append(f"{year_val}: {val_millions:.0f}")
                else:
                    values.append(f"{year_val}: {val if val is not None else '—'}")
        order_display = order if order != 999999 else "NULL"
        print(f"  {i:2}. order={order_display:6} | {label}")
        if values:
            print(f"      {', '.join(values)}")
    
    # Check for expected items
    print(f"\n{'='*80}")
    print("VERIFICATION RESULTS")
    print(f"{'='*80}\n")
    
    items_found = []
    items_missing = []
    items_extra = []
    value_errors = []
    
    # Check each expected item
    # Handle empty strings (spaces) - they should match empty labels or be skipped
    for expected_label in EXPECTED_NOVO_COMPREHENSIVE_INCOME:
        # Skip empty strings (spaces) for now - they're visual separators
        if expected_label == "":
            continue
            
        found = False
        for api_label in api_labels:
            expected_norm = normalize_label_for_matching(expected_label)
            api_norm = normalize_label_for_matching(api_label)
            
            if expected_norm == api_norm:
                found = True
                items_found.append({
                    "expected": expected_label,
                    "found": api_label,
                    "position_expected": EXPECTED_NOVO_COMPREHENSIVE_INCOME.index(expected_label) + 1,
                    "position_actual": api_labels.index(api_label) + 1
                })
                
                # Verify values
                if expected_label in EXPECTED_NOVO_COMPREHENSIVE_INCOME_VALUES:
                    expected_values = EXPECTED_NOVO_COMPREHENSIVE_INCOME_VALUES[expected_label]
                    api_items = api_items_by_label[api_label]
                    
                    for year_val in [2024, 2023, 2022]:
                        expected_val = expected_values.get(year_val)
                        matching_item = next((it for it in api_items if it.get("period_year") == year_val), None)
                        
                        if matching_item:
                            api_val = matching_item.get("value")
                            unit = matching_item.get("unit", "")
                            
                            # Convert to millions if DKK
                            if api_val is not None and unit and "DKK" in unit.upper():
                                api_val_millions = api_val / 1e6
                            else:
                                api_val_millions = api_val
                            
                            # Compare with tolerance (allow small rounding differences)
                            if expected_val is not None and api_val_millions is not None:
                                diff = abs(expected_val - api_val_millions)
                                if diff > 1.0:  # Allow 1 million tolerance
                                    value_errors.append({
                                        "item": expected_label,
                                        "year": year_val,
                                        "expected": expected_val,
                                        "actual": api_val_millions,
                                        "diff": diff
                                    })
                            elif expected_val is not None and api_val_millions is None:
                                value_errors.append({
                                    "item": expected_label,
                                    "year": year_val,
                                    "expected": expected_val,
                                    "actual": None,
                                    "diff": "MISSING"
                                })
                
                break
        
        if not found:
            items_missing.append(expected_label)
    
    # Check for extra items
    for api_label in api_labels:
        found_in_expected = False
        for expected_label in EXPECTED_NOVO_COMPREHENSIVE_INCOME:
            expected_norm = normalize_label_for_matching(expected_label)
            api_norm = normalize_label_for_matching(api_label)
            if expected_norm == api_norm:
                found_in_expected = True
                break
        
        if not found_in_expected:
            items_extra.append(api_label)
    
    # Print results
    expected_non_empty = [x for x in EXPECTED_NOVO_COMPREHENSIVE_INCOME if x != ""]
    print(f"✅ Items Found: {len(items_found)}/{len(expected_non_empty)}")
    if items_found:
        print("   Found items:")
        for item_info in items_found:
            print(f"   ✅ {item_info['expected']} (expected pos: {item_info['position_expected']}, actual pos: {item_info['position_actual']})")
    
    if items_missing:
        print(f"\n❌ Items Missing: {len(items_missing)}")
        for item in items_missing:
            print(f"   - {item}")
    
    if items_extra:
        print(f"\n❌ Extra Items (not expected): {len(items_extra)}")
        for item in items_extra:
            print(f"   - {item}")
    
    if value_errors:
        print(f"\n❌ Value Errors: {len(value_errors)}")
        for error in value_errors:
            print(f"   - {error['item']} ({error['year']}): expected {error['expected']}, got {error['actual']} (diff: {error['diff']})")
    
    # Overall result
    # Count non-empty expected items (spaces are visual separators, not data items)
    expected_non_empty = [x for x in EXPECTED_NOVO_COMPREHENSIVE_INCOME if x != ""]
    success = (
        len(items_found) == len(expected_non_empty) and
        len(items_missing) == 0 and
        len(items_extra) == 0 and
        len(value_errors) == 0
    )
    
    print(f"\n{'='*80}")
    if success:
        print("✅ TEST PASSED: All items present, correct values, no extra items")
    else:
        print("❌ TEST FAILED: Issues found (see above)")
    print(f"{'='*80}\n")
    
    return {
        "success": success,
        "items_found": items_found,
        "items_missing": items_missing,
        "items_extra": items_extra,
        "value_errors": value_errors,
        "values_correct": len(value_errors) == 0,
        "total_items_expected": len([x for x in EXPECTED_NOVO_COMPREHENSIVE_INCOME if x != ""]),
        "total_items_found": len(api_labels)
    }


def test_balance_sheet(api_base: str, ticker: str = "NVO", year: int = 2024) -> Dict:
    """
    Test balance sheet endpoint and verify items and sides
    
    Returns:
        Dict with test results
    """
    print(f"\n{'='*80}")
    print(f"Testing Balance Sheet for {ticker} {year}")
    print(f"{'='*80}\n")
    
    # Call API - MUST use EXACT same endpoint as website
    url = build_api_url(api_base, f"/api/statements/{ticker}/{year}")
    print(f"Calling: {url} (same endpoint as website)")
    
    try:
        print(f"Making request (timeout: 120s)...")
        response = requests.get(url, timeout=120)
        print(f"Response status: {response.status_code}")
        response.raise_for_status()
        data = response.json()
        balance_sheet = data.get("statements", {}).get("balance_sheet", [])
        print(f"Response received: {len(balance_sheet)} balance sheet items")
    except requests.exceptions.Timeout as e:
        return {
            "success": False,
            "error": f"API request timed out after 120s: {e}",
            "items_found": [],
            "items_missing": EXPECTED_NOVO_BALANCE_SHEET_ASSETS + EXPECTED_NOVO_BALANCE_SHEET_LIABILITIES_EQUITY,
            "items_extra": [],
            "sides_correct": False
        }
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": f"API request failed: {e}",
            "items_found": [],
            "items_missing": EXPECTED_NOVO_BALANCE_SHEET_ASSETS + EXPECTED_NOVO_BALANCE_SHEET_LIABILITIES_EQUITY,
            "items_extra": [],
            "sides_correct": False
        }
    
    if not balance_sheet:
        return {
            "success": False,
            "error": "No balance sheet items returned",
            "items_found": [],
            "items_missing": EXPECTED_NOVO_BALANCE_SHEET_ASSETS + EXPECTED_NOVO_BALANCE_SHEET_LIABILITIES_EQUITY,
            "items_extra": [],
            "sides_correct": False
        }
    
    # Separate items by side
    assets_items = [item for item in balance_sheet if item.get("side") == "assets"]
    liabilities_equity_items = [item for item in balance_sheet if item.get("side") == "liabilities_equity"]
    items_without_side = [item for item in balance_sheet if not item.get("side")]
    
    print(f"Items by side:")
    print(f"  Assets: {len(assets_items)} items")
    print(f"  Liabilities & Equity: {len(liabilities_equity_items)} items")
    if items_without_side:
        print(f"  ⚠️  Items without side: {len(items_without_side)} items")
        for item in items_without_side[:5]:
            print(f"     - {item.get('normalized_label', 'N/A')} -> {item.get('preferred_label', 'N/A')}")
    
    # Extract labels from API response (group by normalized_label)
    def process_items(items, side_name):
        api_items_by_normalized = {}
        for item in items:
            normalized = item.get("normalized_label", "")
            if normalized not in api_items_by_normalized:
                api_items_by_normalized[normalized] = []
            api_items_by_normalized[normalized].append(item)
        
        # Convert to labels using preferred_label from API
        api_items_with_order = []
        for normalized, items_list in api_items_by_normalized.items():
            first_item = items_list[0]
            preferred_label = first_item.get("preferred_label")
            if preferred_label:
                humanized = preferred_label
            else:
                # Fallback to humanize
                humanized = humanize_label(normalized, "balance_sheet")
            order = first_item.get("presentation_order_index", 999999)
            api_items_with_order.append({
                "normalized": normalized,
                "humanized": humanized,
                "order": order,
                "items": items_list
            })
        
        # Sort by presentation_order_index
        api_items_with_order.sort(key=lambda x: (
            x["order"] if x["order"] != 999999 else 999999,
            x["normalized"]
        ))
        
        return [item["humanized"] for item in api_items_with_order], api_items_with_order
    
    assets_labels, assets_items_with_order = process_items(assets_items, "Assets")
    liabilities_equity_labels, liabilities_equity_items_with_order = process_items(liabilities_equity_items, "Liabilities & Equity")
    
    print(f"\nASSETS (Left side) - Found {len(assets_labels)} items:\n")
    for i, item_data in enumerate(assets_items_with_order, 1):
        order = item_data["order"]
        label = item_data["humanized"]
        order_display = order if order != 999999 else "NULL"
        print(f"  {i:2}. order={order_display:6} | {label}")
    
    print(f"\nLIABILITIES & EQUITY (Right side) - Found {len(liabilities_equity_labels)} items:\n")
    for i, item_data in enumerate(liabilities_equity_items_with_order, 1):
        order = item_data["order"]
        label = item_data["humanized"]
        order_display = order if order != 999999 else "NULL"
        print(f"  {i:2}. order={order_display:6} | {label}")
    
    # Check for expected items
    print(f"\n{'='*80}")
    print("VERIFICATION RESULTS")
    print(f"{'='*80}\n")
    
    def check_items(expected_list, actual_list, side_name):
        items_found = []
        items_missing = []
        items_extra = []
        
        for expected_label in expected_list:
            found = False
            for actual_label in actual_list:
                expected_norm = normalize_label_for_matching(expected_label)
                actual_norm = normalize_label_for_matching(actual_label)
                if expected_norm == actual_norm:
                    found = True
                    items_found.append({
                        "expected": expected_label,
                        "found": actual_label,
                        "position_expected": expected_list.index(expected_label) + 1,
                        "position_actual": actual_list.index(actual_label) + 1
                    })
                    break
            if not found:
                items_missing.append(expected_label)
        
        for actual_label in actual_list:
            found_in_expected = False
            for expected_label in expected_list:
                expected_norm = normalize_label_for_matching(expected_label)
                actual_norm = normalize_label_for_matching(actual_label)
                if expected_norm == actual_norm:
                    found_in_expected = True
                    break
            if not found_in_expected:
                items_extra.append(actual_label)
        
        return items_found, items_missing, items_extra
    
    assets_found, assets_missing, assets_extra = check_items(EXPECTED_NOVO_BALANCE_SHEET_ASSETS, assets_labels, "Assets")
    liabilities_found, liabilities_missing, liabilities_extra = check_items(EXPECTED_NOVO_BALANCE_SHEET_LIABILITIES_EQUITY, liabilities_equity_labels, "Liabilities & Equity")
    
    print(f"ASSETS:")
    print(f"  ✅ Items Found: {len(assets_found)}/{len(EXPECTED_NOVO_BALANCE_SHEET_ASSETS)}")
    if assets_found:
        for item_info in assets_found:
            pos_match = "✅" if item_info["position_expected"] == item_info["position_actual"] else "❌"
            print(f"   {pos_match} {item_info['expected']} (expected pos: {item_info['position_expected']}, actual pos: {item_info['position_actual']})")
    if assets_missing:
        print(f"  ❌ Items Missing: {len(assets_missing)}")
        for item in assets_missing:
            print(f"     - {item}")
    if assets_extra:
        print(f"  ❌ Extra Items: {len(assets_extra)}")
        for item in assets_extra[:10]:
            print(f"     - {item}")
    
    print(f"\nLIABILITIES & EQUITY:")
    print(f"  ✅ Items Found: {len(liabilities_found)}/{len(EXPECTED_NOVO_BALANCE_SHEET_LIABILITIES_EQUITY)}")
    if liabilities_found:
        for item_info in liabilities_found:
            pos_match = "✅" if item_info["position_expected"] == item_info["position_actual"] else "❌"
            print(f"   {pos_match} {item_info['expected']} (expected pos: {item_info['position_expected']}, actual pos: {item_info['position_actual']})")
    if liabilities_missing:
        print(f"  ❌ Items Missing: {len(liabilities_missing)}")
        for item in liabilities_missing:
            print(f"     - {item}")
    if liabilities_extra:
        print(f"  ❌ Extra Items: {len(liabilities_extra)}")
        for item in liabilities_extra[:10]:
            print(f"     - {item}")
    
    # Overall result
    all_found = len(assets_found) + len(liabilities_found)
    all_expected = len(EXPECTED_NOVO_BALANCE_SHEET_ASSETS) + len(EXPECTED_NOVO_BALANCE_SHEET_LIABILITIES_EQUITY)
    all_missing = len(assets_missing) + len(liabilities_missing)
    all_extra = len(assets_extra) + len(liabilities_extra)
    sides_correct = len(items_without_side) == 0
    
    success = (
        all_found == all_expected and
        all_missing == 0 and
        all_extra == 0 and
        sides_correct
    )
    
    print(f"\n{'='*80}")
    if success:
        print("✅ TEST PASSED: All items present, correct sides, no extra items")
    else:
        print("❌ TEST FAILED: Issues found (see above)")
    print(f"{'='*80}\n")
    
    return {
        "success": success,
        "assets_found": assets_found,
        "assets_missing": assets_missing,
        "assets_extra": assets_extra,
        "liabilities_found": liabilities_found,
        "liabilities_missing": liabilities_missing,
        "liabilities_extra": liabilities_extra,
        "sides_correct": sides_correct,
        "items_without_side": len(items_without_side),
        "total_items_expected": all_expected,
        "total_items_found": all_found
    }


def test_cash_flow(api_base: str, ticker: str = "NVO", year: int = 2024) -> Dict:
    """
    Test cash flow statement endpoint and verify items
    
    Returns:
        Dict with test results
    """
    print(f"\n{'='*80}")
    print(f"Testing Cash Flow Statement for {ticker} {year}")
    print(f"{'='*80}\n")
    
    # Call API - MUST use EXACT same endpoint as website
    url = build_api_url(api_base, f"/api/statements/{ticker}/{year}")
    print(f"Calling: {url} (same endpoint as website)")
    
    try:
        print(f"Making request (timeout: 120s)...")
        response = requests.get(url, timeout=120)
        print(f"Response status: {response.status_code}")
        response.raise_for_status()
        data = response.json()
        cash_flow = data.get("statements", {}).get("cash_flow", [])
        print(f"Response received: {len(cash_flow)} cash flow items")
    except requests.exceptions.Timeout as e:
        return {
            "success": False,
            "error": f"API request timed out after 120s: {e}",
            "items_found": [],
            "items_missing": EXPECTED_NOVO_CASH_FLOW.copy(),
            "items_extra": [],
            "order_correct": False
        }
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": f"API request failed: {e}",
            "items_found": [],
            "items_missing": EXPECTED_NOVO_CASH_FLOW.copy(),
            "items_extra": [],
            "order_correct": False
        }
    
    if not cash_flow:
        return {
            "success": False,
            "error": "No cash flow items returned",
            "items_found": [],
            "items_missing": EXPECTED_NOVO_CASH_FLOW.copy(),
            "items_extra": [],
            "order_correct": False
        }
    
    # Extract labels from API response (group by normalized_label)
    api_items_by_normalized = {}
    for item in cash_flow:
        normalized = item.get("normalized_label", "")
        if normalized not in api_items_by_normalized:
            api_items_by_normalized[normalized] = []
        api_items_by_normalized[normalized].append(item)
    
    # Convert to labels using preferred_label from API
    api_items_with_order = []
    for normalized, items in api_items_by_normalized.items():
        first_item = items[0]
        preferred_label = first_item.get("preferred_label")
        if preferred_label:
            humanized = preferred_label
        else:
            # Fallback to humanize
            humanized = humanize_label(normalized, "cash_flow")
        order = first_item.get("presentation_order_index", 999999)
        api_items_with_order.append({
            "normalized": normalized,
            "humanized": humanized,
            "order": order,
            "items": items
        })
    
    # Sort by presentation_order_index
    api_items_with_order.sort(key=lambda x: (
        x["order"] if x["order"] != 999999 else 999999,
        x["normalized"]
    ))
    
    # Build final lists
    api_labels = [item["humanized"] for item in api_items_with_order]
    
    print(f"\nFound {len(api_labels)} unique items in API response (sorted by presentation_order_index):\n")
    for i, item_data in enumerate(api_items_with_order, 1):
        order = item_data["order"]
        label = item_data["humanized"]
        values = []
        for year_val in [2024, 2023, 2022]:
            matching_item = next((it for it in item_data["items"] if it.get("period_year") == year_val), None)
            if matching_item:
                val = matching_item.get("value")
                unit = matching_item.get("unit", "")
                # Convert to millions for display (DKK values are in base units)
                if val is not None and unit and "DKK" in unit.upper():
                    val_millions = val / 1e6
                    values.append(f"{year_val}: {val_millions:.0f}")
                else:
                    values.append(f"{year_val}: {val if val is not None else '—'}")
        order_display = order if order != 999999 else "NULL"
        print(f"  {i:2}. order={order_display:6} | {label}")
        if values:
            print(f"      {', '.join(values)}")
    
    # Check for expected items
    print(f"\n{'='*80}")
    print("VERIFICATION RESULTS")
    print(f"{'='*80}\n")
    
    items_found = []
    items_missing = []
    items_extra = []
    
    # Check each expected item
    for expected_label in EXPECTED_NOVO_CASH_FLOW:
        # Skip empty strings (spaces) - they're visual separators
        if expected_label == "":
            continue
            
        found = False
        for api_label in api_labels:
            expected_norm = normalize_label_for_matching(expected_label)
            api_norm = normalize_label_for_matching(api_label)
            
            if expected_norm == api_norm:
                found = True
                items_found.append({
                    "expected": expected_label,
                    "found": api_label,
                    "position_expected": EXPECTED_NOVO_CASH_FLOW.index(expected_label) + 1,
                    "position_actual": api_labels.index(api_label) + 1
                })
                break
        
        if not found:
            items_missing.append(expected_label)
    
    # Check for extra items
    for api_label in api_labels:
        found_in_expected = False
        for expected_label in EXPECTED_NOVO_CASH_FLOW:
            expected_norm = normalize_label_for_matching(expected_label)
            api_norm = normalize_label_for_matching(api_label)
            if expected_norm == api_norm:
                found_in_expected = True
                break
        
        if not found_in_expected:
            items_extra.append(api_label)
    
    # Check order
    order_correct = True
    order_issues = []
    for item_info in items_found:
        expected_pos = item_info["position_expected"]
        actual_pos = item_info["position_actual"]
        if expected_pos != actual_pos:
            order_correct = False
            order_issues.append({
                "item": item_info["expected"],
                "expected_position": expected_pos,
                "actual_position": actual_pos
            })
    
    # Print results
    expected_non_empty = [x for x in EXPECTED_NOVO_CASH_FLOW if x != ""]
    print(f"✅ Items Found: {len(items_found)}/{len(expected_non_empty)}")
    if items_found:
        print("   Found items:")
        for item_info in items_found:
            pos_match = "✅" if item_info["position_expected"] == item_info["position_actual"] else "❌"
            print(f"   {pos_match} {item_info['expected']} (expected pos: {item_info['position_expected']}, actual pos: {item_info['position_actual']})")
    
    if items_missing:
        print(f"\n❌ Items Missing: {len(items_missing)}")
        for item in items_missing:
            print(f"   - {item}")
    
    if items_extra:
        print(f"\n❌ Extra Items (not expected): {len(items_extra)}")
        for item in items_extra[:10]:
            print(f"   - {item}")
        if len(items_extra) > 10:
            print(f"   ... and {len(items_extra) - 10} more")
    
    if order_issues:
        print(f"\n❌ Order Issues: {len(order_issues)}")
        for issue in order_issues:
            print(f"   - {issue['item']}: expected position {issue['expected_position']}, actual position {issue['actual_position']}")
    
    # Overall result
    success = (
        len(items_found) == len(expected_non_empty) and
        len(items_missing) == 0 and
        len(items_extra) == 0 and
        order_correct
    )
    
    print(f"\n{'='*80}")
    if success:
        print("✅ TEST PASSED: All items present, correct order, no extra items")
    else:
        print("❌ TEST FAILED: Issues found (see above)")
    print(f"{'='*80}\n")
    
    return {
        "success": success,
        "items_found": items_found,
        "items_missing": items_missing,
        "items_extra": items_extra,
        "order_correct": order_correct,
        "order_issues": order_issues,
        "total_items_expected": len(expected_non_empty),
        "total_items_found": len(api_labels)
    }


def validate_equity_component_patterns(items: List[Dict], years: List[int]) -> Dict:
    """
    Universal validation for equity statement component breakdowns.
    
    Rules:
    1. Headers (is_header=True): Should be blank across ALL components
    2. Balance at beginning/end: Should have values for ALL components (including Total)
    3. Net profit: Typically only in Retained earnings (or Total if consolidated)
    4. Other comprehensive income: Typically only in Other reserves (or Total if consolidated)
    5. Total comprehensive income: Should have values (typically in Retained earnings or Total)
    6. Transactions with owners (header): Should be blank
    7. Dividends: Typically only in Retained earnings (or Total)
    8. Share-based payments: Could be in Share capital or Retained earnings (or Total)
    9. Purchase of treasury shares: Typically only in Treasury shares (or Total)
    10. Reduction of share capital: Typically only in Share capital (or Total)
    11. Tax related to transactions: Could be in any component (or Total)
    12. Transfer of cash flow hedge reserve: Typically only in Other reserves (or Total)
    
    Universal principle: Each movement should have at least ONE value per year
    (either in a specific component OR in Total, but not both blank)
    """
    components = ['share_capital', 'treasury_shares', 'retained_earnings', 'other_reserves', None]  # None = Total
    component_labels = {
        'share_capital': 'Share capital',
        'treasury_shares': 'Treasury shares',
        'retained_earnings': 'Retained earnings',
        'other_reserves': 'Other reserves',
        None: 'Total'
    }
    
    # Group items by normalized_label (movement) and period_year
    movement_map = {}  # movement -> year -> component -> value
    movement_metadata = {}  # movement -> {is_header, preferred_label, normalized_label}
    
    for item in items:
        movement = item.get("normalized_label", "")
        year = item.get("period_year")
        component = item.get("equity_component")  # None for totals
        value = item.get("value")
        is_header = item.get("is_header", False)
        
        if not movement or year is None:
            continue
        
        if movement not in movement_map:
            movement_map[movement] = {}
            movement_metadata[movement] = {
                "is_header": is_header,
                "preferred_label": item.get("preferred_label", ""),
                "normalized_label": movement
            }
        
        if year not in movement_map[movement]:
            movement_map[movement][year] = {}
        
        movement_map[movement][year][component] = value
    
    issues = []
    warnings = []
    
    # Validate each movement
    for movement, year_map in movement_map.items():
        metadata = movement_metadata[movement]
        is_header = metadata["is_header"]
        label = metadata["preferred_label"] or movement
        
        # Rule 1: Headers should be blank across ALL components
        if is_header:
            for year in years:
                if year in year_map:
                    for component in components:
                        value = year_map[year].get(component)
                        if value is not None and abs(value) > 0.001:
                            issues.append({
                                "type": "header_has_value",
                                "movement": label,
                                "year": year,
                                "component": component_labels.get(component, "Unknown"),
                                "value": value
                            })
            continue  # Skip other validations for headers
        
        # Rule 2: Balance at beginning/end should have values for ALL components
        is_balance = "balance" in movement.lower() and ("beginning" in movement.lower() or "end" in movement.lower())
        if is_balance:
            for year in years:
                if year in year_map:
                    missing_components = []
                    for component in components:
                        value = year_map[year].get(component)
                        if value is None or abs(value) < 0.001:
                            missing_components.append(component_labels.get(component, "Unknown"))
                    
                    if missing_components:
                        issues.append({
                            "type": "balance_missing_components",
                            "movement": label,
                            "year": year,
                            "missing_components": missing_components
                        })
            continue  # Skip other validations for balances
        
        # Rule 3-12: Each movement should have at least ONE value per year
        # (either in a specific component OR in Total, but not both blank)
        for year in years:
            if year in year_map:
                has_any_value = False
                component_values = {}
                
                for component in components:
                    value = year_map[year].get(component)
                    component_values[component_labels.get(component, "Unknown")] = value
                    if value is not None and abs(value) > 0.001:
                        has_any_value = True
                
                if not has_any_value:
                    issues.append({
                        "type": "movement_all_blank",
                        "movement": label,
                        "year": year,
                        "component_values": component_values
                    })
                else:
                    # Check for component-specific patterns (warnings, not errors)
                    movement_lower = movement.lower()
                    label_lower = label.lower()
                    
                    # Dividends should primarily be in retained_earnings
                    if "dividend" in movement_lower or "dividend" in label_lower:
                        total_value = year_map[year].get(None)
                        retained_value = year_map[year].get("retained_earnings")
                        if total_value is not None and retained_value is None:
                            warnings.append({
                                "type": "dividend_not_in_retained_earnings",
                                "movement": label,
                                "year": year,
                                "has_total_only": True
                            })
                    
                    # Purchase of treasury shares should primarily be in treasury_shares
                    if "treasury" in movement_lower and ("purchase" in movement_lower or "acquire" in movement_lower):
                        total_value = year_map[year].get(None)
                        treasury_value = year_map[year].get("treasury_shares")
                        if total_value is not None and treasury_value is None:
                            warnings.append({
                                "type": "treasury_purchase_not_in_treasury_shares",
                                "movement": label,
                                "year": year,
                                "has_total_only": True
                            })
                    
                    # Reduction of capital should primarily be in share_capital
                    if "reduction" in movement_lower and "capital" in movement_lower:
                        total_value = year_map[year].get(None)
                        share_capital_value = year_map[year].get("share_capital")
                        if total_value is not None and share_capital_value is None:
                            warnings.append({
                                "type": "reduction_not_in_share_capital",
                                "movement": label,
                                "year": year,
                                "has_total_only": True
                            })
    
    return {
        "issues": issues,
        "warnings": warnings,
        "movement_count": len(movement_map),
        "total_issues": len(issues),
        "total_warnings": len(warnings)
    }


def test_equity_statement(api_base: str, ticker: str = "NVO", year: int = 2024) -> Dict:
    """
    Test equity statement endpoint and verify items
    
    Returns:
        Dict with test results
    """
    print(f"\n{'='*80}")
    print(f"Testing Statement of Changes in Equity for {ticker} {year}")
    print(f"{'='*80}\n")
    
    # Call API - MUST use EXACT same endpoint as website
    url = build_api_url(api_base, f"/api/statements/{ticker}/{year}")
    print(f"Calling: {url} (same endpoint as website)")
    
    try:
        print(f"Making request (timeout: 120s)...")
        response = requests.get(url, timeout=120)
        print(f"Response status: {response.status_code}")
        response.raise_for_status()
        data = response.json()
        equity_statement = data.get("statements", {}).get("equity_statement", [])
        print(f"Response received: {len(equity_statement)} equity statement items")
    except requests.exceptions.Timeout as e:
        return {
            "success": False,
            "error": f"API request timed out after 120s: {e}",
            "items_found": [],
            "items_missing": EXPECTED_NOVO_EQUITY_STATEMENT.copy(),
            "items_extra": [],
            "order_correct": False
        }
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": f"API request failed: {e}",
            "items_found": [],
            "items_missing": EXPECTED_NOVO_EQUITY_STATEMENT.copy(),
            "items_extra": [],
            "order_correct": False
        }
    
    if not equity_statement:
        return {
            "success": False,
            "error": "No equity statement items returned",
            "items_found": [],
            "items_missing": EXPECTED_NOVO_EQUITY_STATEMENT.copy(),
            "items_extra": [],
            "order_correct": False
        }
    
    # Extract labels from API response (group by normalized_label)
    api_items_by_normalized = {}
    for item in equity_statement:
        normalized = item.get("normalized_label", "")
        if normalized not in api_items_by_normalized:
            api_items_by_normalized[normalized] = []
        api_items_by_normalized[normalized].append(item)
    
    # Convert to labels using preferred_label from API
    # CRITICAL: Remove "header" suffix from header labels (e.g., "Transactions with owners header" -> "Transactions with owners")
    api_items_with_order = []
    for normalized, items in api_items_by_normalized.items():
        first_item = items[0]
        preferred_label = first_item.get("preferred_label")
        if preferred_label:
            humanized = preferred_label
            # Remove "header" suffix if present (case-insensitive)
            if first_item.get("is_header", False):
                humanized = humanized.replace(" header", "").replace(" Header", "").strip()
        else:
            # Fallback to humanize
            humanized = humanize_label(normalized, "equity_statement")
            # Remove "header" suffix if present
            if first_item.get("is_header", False):
                humanized = humanized.replace(" header", "").replace(" Header", "").strip()
        order = first_item.get("presentation_order_index", 999999)
        api_items_with_order.append({
            "normalized": normalized,
            "humanized": humanized,
            "order": order,
            "items": items,
            "is_header": first_item.get("is_header", False)
        })
    
    # Sort by presentation_order_index
    api_items_with_order.sort(key=lambda x: (
        x["order"] if x["order"] != 999999 else 999999,
        x["normalized"]
    ))
    
    # Build final lists (without spaces initially)
    api_labels_raw = [item["humanized"] for item in api_items_with_order]
    
    # Detect accounting standard from API response or ticker
    # Check if "Net profit" (IFRS) or "Net income" (US-GAAP) is present
    has_net_profit = any("net profit" in label.lower() for label in api_labels_raw)
    has_net_income = any("net income" in label.lower() and "comprehensive" not in label.lower() for label in api_labels_raw)
    
    # Determine expected order based on accounting standard
    if has_net_profit or ticker.upper() in ["NVO", "SNY"]:  # IFRS companies
        expected_order = EXPECTED_NOVO_EQUITY_STATEMENT
        reporting_style = "IFRS/EU"
    elif has_net_income:  # US-GAAP companies
        expected_order = EXPECTED_US_EQUITY_STATEMENT
        reporting_style = "US-GAAP"
    else:
        # Default to IFRS for now (can be enhanced)
        expected_order = EXPECTED_NOVO_EQUITY_STATEMENT
        reporting_style = "IFRS/EU (default)"
    
    # Build final list WITHOUT adding spaces - API doesn't return spaces
    # The matching logic will handle space detection
    api_labels = [item_data["humanized"] for item_data in api_items_with_order]
    
    print(f"\nDetected reporting style: {reporting_style}")
    print(f"Found {len(api_labels)} unique items in API response (sorted by presentation_order_index):\n")
    for i, item_data in enumerate(api_items_with_order, 1):
        order = item_data["order"]
        label = item_data["humanized"]
        values = []
        for year_val in [2024, 2023, 2022]:
            matching_item = next((it for it in item_data["items"] if it.get("period_year") == year_val), None)
            if matching_item:
                val = matching_item.get("value")
                unit = matching_item.get("unit", "")
                # Convert to millions for display (DKK values are in base units)
                if val is not None and unit and "DKK" in unit.upper():
                    val_millions = val / 1e6
                    values.append(f"{year_val}: {val_millions:.0f}")
                else:
                    values.append(f"{year_val}: {val if val is not None else '—'}")
        order_display = order if order != 999999 else "NULL"
        print(f"  {i:2}. order={order_display:6} | {label}")
        if values:
            print(f"      {', '.join(values)}")
    
    # Check for expected items
    print(f"\n{'='*80}")
    print("VERIFICATION RESULTS")
    print(f"{'='*80}\n")
    print(f"Expected order ({reporting_style}):")
    for i, expected in enumerate(expected_order, 1):
        if expected == "":
            print(f"  {i:2}. (space)")
        else:
            print(f"  {i:2}. {expected}")
    print()
    
    items_found = []
    items_missing = []
    items_extra = []
    order_issues = []
    order_correct = True
    
    # Expected values for Novo Nordisk Equity Statement (2024, 2023, 2022) in DKK millions
    # Values from Novo's 2024 annual report
    EXPECTED_NOVO_EQUITY_STATEMENT_VALUES = {
        "Balance at the beginning of the year": {
            2024: 106561,  # 2023's end balance
            2023: 83486,   # 2022's end balance
            2022: 70746    # 2021's end balance
        },
        "Net profit": {
            2024: 100988,
            2023: 83683,
            2022: 55525
        },
        "Other comprehensive income": {
            2024: -1901,
            2023: -1160,
            2022: 4778
        },
        "Total comprehensive income": {
            2024: 99087,
            2023: 82523,
            2022: 60303
        },
        "Transfer of cash flow hedge reserve to intangible assets": {
            2024: -900,
            2023: 0,
            2022: 0
        },
        "Dividends": {
            2024: -44140,
            2023: -31767,
            2022: -25303
        },
        "Share-based payments": {
            2024: 2289,
            2023: 2149,
            2022: 1539
        },
        "Purchase of treasury shares": {
            2024: -20181,
            2023: -29924,
            2022: -24086
        },
        "Reduction of the B share capital": {
            2024: -5,
            2023: -5,
            2022: -6
        },
        "Tax related to transactions with owners": {
            2024: 770,
            2023: 94,
            2022: 287
        },
        "Balance at the end of the year": {
            2024: 143486,  # 2024's end balance
            2023: 106561,  # 2023's end balance
            2022: 83486    # 2022's end balance
        }
    }
    
    # Check each expected item - match in exact order including spaces
    expected_non_empty = [label for label in expected_order if label != ""]
    items_found = []
    items_missing = []
    order_issues = []
    
    # Build a mapping of expected position to label (including spaces)
    expected_positions = {i+1: label for i, label in enumerate(expected_order)}
    
    # Match items in STRICT order - must match exactly including spaces
    # CRITICAL: When a space is missing, ALL subsequent items are shifted and out of order
    expected_idx = 0
    api_idx = 0
    space_offset = 0  # Track how many spaces are missing (causes position shifts)
    
    while expected_idx < len(expected_order) and api_idx < len(api_labels):
        expected_label = expected_order[expected_idx]
        api_label = api_labels[api_idx] if api_idx < len(api_labels) else None
        
        # Skip API spaces
        if api_label == "":
            api_idx += 1
            continue
        
        expected_norm = normalize_label_for_matching(expected_label) if expected_label else ""
        api_norm = normalize_label_for_matching(api_label) if api_label else ""
        
        if expected_label == "":
            # Expected space but got item - CRITICAL ERROR
            # This means ALL subsequent items will be out of position
            order_correct = False
            space_offset += 1  # Track that we're missing a space
            print(f"   ❌ MISSING SPACE: Expected space at position {expected_idx + 1}, but got '{api_label}'")
            print(f"      This shifts ALL subsequent items by {space_offset} position(s)!")
            expected_idx += 1
            # DO NOT advance api_idx - check if current item matches next expected
        elif expected_norm == api_norm:
            # Match found - check if position is correct
            expected_pos = expected_idx + 1
            actual_pos = api_idx + 1
            
            items_found.append({
                "expected": expected_label,
                "found": api_label,
                "position_expected": expected_pos,
                "position_actual": actual_pos
            })
            
            # Calculate expected position without spaces (API doesn't return spaces)
            spaces_before = sum(1 for i in range(expected_idx) if expected_order[i] == "")
            expected_pos_without_spaces = expected_pos - spaces_before
            
            # Position should match when accounting for missing spaces
            # Only report error if position doesn't match even after accounting for spaces
            if actual_pos != expected_pos_without_spaces:
                # This means item is truly out of order (not just shifted by missing spaces)
                order_issues.append({
                    "item": expected_label,
                    "expected_position": expected_pos,
                    "actual_position": actual_pos
                })
                order_correct = False
                print(f"   ❌ OUT OF ORDER: '{expected_label}' - expected at position {expected_pos} (position {expected_pos_without_spaces} without spaces), found at {actual_pos}")
            # If position matches after accounting for spaces, item is in correct relative order
            
            expected_idx += 1
            api_idx += 1
        else:
            # Mismatch - item is out of order or missing
            # Check if this expected item appears later in API (out of order)
            found_later = False
            for later_idx in range(api_idx, len(api_labels)):
                later_label = api_labels[later_idx]
                if later_label == "":
                    continue
                later_norm = normalize_label_for_matching(later_label)
                if expected_norm == later_norm:
                    found_later = True
                    actual_pos = later_idx + 1
                    expected_pos = expected_idx + 1
                    order_issues.append({
                        "item": expected_label,
                        "expected_position": expected_pos,
                        "actual_position": actual_pos
                    })
                    order_correct = False
                    print(f"   ❌ OUT OF ORDER: '{expected_label}' - expected at position {expected_pos}, found at {actual_pos}")
                    expected_idx += 1
                    api_idx = later_idx + 1
                    break
            
            if not found_later:
                items_missing.append(expected_label)
                order_correct = False
                print(f"   ❌ MISSING: '{expected_label}' - expected at position {expected_idx + 1}, not found")
                expected_idx += 1
    
    # Check for any remaining expected items
    while expected_idx < len(expected_order):
        if expected_order[expected_idx] != "":
            items_missing.append(expected_order[expected_idx])
        expected_idx += 1
    
    # Check for extra items in API response
    for api_label in api_labels:
        if api_label == "":  # Skip spaces
            continue
        found_in_expected = False
        for expected_label in expected_order:
            if expected_label == "":
                continue
            expected_norm = normalize_label_for_matching(expected_label)
            api_norm = normalize_label_for_matching(api_label)
            if expected_norm == api_norm:
                found_in_expected = True
                break
        
        if not found_in_expected:
            items_extra.append(api_label)
    
    # Check values for found items
    for item_info in items_found:
        expected_label = item_info["expected"]
        matching_item_data = next((item for item in api_items_with_order if item["humanized"] == item_info["found"]), None)
        
        if expected_label in EXPECTED_NOVO_EQUITY_STATEMENT_VALUES and matching_item_data:
            expected_values = EXPECTED_NOVO_EQUITY_STATEMENT_VALUES[expected_label]
            for year_val in [2024, 2023, 2022]:
                # For equity statements, prefer total (NULL component) or use share_capital component for capital reductions
                matching_items = [it for it in matching_item_data["items"] if it.get("period_year") == year_val]
                if matching_items:
                    # Prefer total (NULL component) if available
                    total_item = next((it for it in matching_items if it.get("equity_component") is None), None)
                    if total_item:
                        val = total_item.get("value")
                    elif "reduction" in expected_label.lower() and "capital" in expected_label.lower():
                        # For capital reductions, use share_capital component
                        share_capital_item = next((it for it in matching_items if it.get("equity_component") == "share_capital"), None)
                        val = share_capital_item.get("value") if share_capital_item else None
                    elif "treasury" in expected_label.lower() and "purchase" in expected_label.lower():
                        # For treasury purchases, prefer retained_earnings (larger value) or treasury_shares
                        retained_item = next((it for it in matching_items if it.get("equity_component") == "retained_earnings"), None)
                        treasury_item = next((it for it in matching_items if it.get("equity_component") == "treasury_shares"), None)
                        # Use retained_earnings if available (larger value), otherwise treasury_shares
                        val = retained_item.get("value") if retained_item else (treasury_item.get("value") if treasury_item else None)
                    elif "total comprehensive income" in expected_label.lower():
                        # For total comprehensive income, use retained_earnings component (should be positive)
                        retained_item = next((it for it in matching_items if it.get("equity_component") == "retained_earnings"), None)
                        val = retained_item.get("value") if retained_item else None
                    elif "other comprehensive income" in expected_label.lower() and "total" not in expected_label.lower():
                        # For other comprehensive income, use other_reserves component (OCI goes to reserves)
                        other_reserves_item = next((it for it in matching_items if it.get("equity_component") == "other_reserves"), None)
                        val = other_reserves_item.get("value") if other_reserves_item else None
                    else:
                        # For other items, use first available component or sum (fallback)
                        val = matching_items[0].get("value") if matching_items else None
                    
                    unit = matching_items[0].get("unit", "") if matching_items else ""
                    # Convert to millions for comparison (DKK values are in base units)
                    if val is not None and unit and "DKK" in unit.upper():
                        val_millions = val / 1e6
                        expected_val = expected_values.get(year_val)
                        if expected_val is not None:
                            # Allow 1 million tolerance for rounding
                            if abs(val_millions - expected_val) > 1:
                                print(f"   ⚠️  Value mismatch for {expected_label} {year_val}: expected {expected_val}, got {val_millions:.0f}")
                elif year_val in expected_values and expected_values[year_val] != 0:
                    print(f"   ⚠️  Missing value for {expected_label} {year_val}: expected {expected_values[year_val]}")
    
    # Validate component breakdowns using universal patterns
    print(f"\n{'='*80}")
    print("COMPONENT BREAKDOWN VALIDATION (Universal Patterns)")
    print(f"{'='*80}\n")
    
    validation_result = validate_equity_component_patterns(equity_statement, [2024, 2023, 2022])
    
    if validation_result["issues"]:
        print(f"❌ Component Breakdown Issues: {len(validation_result['issues'])}")
        for issue in validation_result["issues"][:20]:  # Show first 20
            if issue["type"] == "header_has_value":
                print(f"   ❌ Header '{issue['movement']}' has value in {issue['component']} for {issue['year']}: {issue['value']}")
            elif issue["type"] == "balance_missing_components":
                print(f"   ❌ Balance '{issue['movement']}' missing values in {issue['year']} for: {', '.join(issue['missing_components'])}")
            elif issue["type"] == "movement_all_blank":
                print(f"   ❌ Movement '{issue['movement']}' is completely blank for {issue['year']}")
                print(f"      Component values: {issue['component_values']}")
        if len(validation_result["issues"]) > 20:
            print(f"   ... and {len(validation_result['issues']) - 20} more issues")
    else:
        print(f"✅ Component Breakdown: No issues found")
    
    if validation_result["warnings"]:
        print(f"\n⚠️  Component Breakdown Warnings: {len(validation_result['warnings'])}")
        for warning in validation_result["warnings"][:10]:  # Show first 10
            if warning["type"] == "dividend_not_in_retained_earnings":
                print(f"   ⚠️  Dividends '{warning['movement']}' only in Total for {warning['year']} (expected in Retained earnings)")
            elif warning["type"] == "treasury_purchase_not_in_treasury_shares":
                print(f"   ⚠️  Treasury purchase '{warning['movement']}' only in Total for {warning['year']} (expected in Treasury shares)")
            elif warning["type"] == "reduction_not_in_share_capital":
                print(f"   ⚠️  Capital reduction '{warning['movement']}' only in Total for {warning['year']} (expected in Share capital)")
        if len(validation_result["warnings"]) > 10:
            print(f"   ... and {len(validation_result['warnings']) - 10} more warnings")
    
    # Print results
    print(f"\n{'='*80}")
    print("ITEM PRESENCE & ORDER VALIDATION")
    print(f"{'='*80}\n")
    
    print(f"✅ Items Found: {len(items_found)}/{len(expected_non_empty)} (excluding spaces)")
    if items_found:
        print("   Found items:")
        for item_info in items_found:
            pos_match = "✅" if item_info["position_expected"] == item_info["position_actual"] else "❌"
            print(f"   {pos_match} {item_info['expected']} (expected pos: {item_info['position_expected']}, actual pos: {item_info['position_actual']})")
    
    if items_missing:
        print(f"\n❌ Items Missing: {len(items_missing)}")
        for item in items_missing:
            print(f"   - {item}")
    
    if items_extra:
        print(f"\n❌ Extra Items (not expected): {len(items_extra)}")
        for item in items_extra[:10]:
            print(f"   - {item}")
        if len(items_extra) > 10:
            print(f"   ... and {len(items_extra) - 10} more")
    
    if order_issues:
        print(f"\n❌ Order Issues: {len(order_issues)}")
        for issue in order_issues:
            print(f"   - {issue['item']}: expected position {issue['expected_position']}, actual position {issue['actual_position']}")
    
    # Overall result
    # Success requires: correct items/order AND no component breakdown issues
    # Note: We check against expected_non_empty (excluding spaces) for item count
    success = (
        len(items_found) == len(expected_non_empty) and
        len(items_missing) == 0 and
        len(items_extra) == 0 and
        order_correct and
        validation_result["total_issues"] == 0
    )
    
    print(f"\n{'='*80}")
    if success:
        print("✅ TEST PASSED: All items present, correct order, no extra items, component breakdowns valid")
    else:
        print("❌ TEST FAILED: Issues found (see above)")
    print(f"{'='*80}\n")
    
    return {
        "success": success,
        "items_found": items_found,
        "items_missing": items_missing,
        "items_extra": items_extra,
        "order_correct": order_correct,
        "order_issues": order_issues,
        "total_items_expected": len(expected_non_empty),
        "reporting_style": reporting_style,
        "total_items_found": len(api_labels),
        "component_validation": validation_result
    }


def main():
    """Main test function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test FinSight API financial statements")
    parser.add_argument("--api-base", default="http://localhost:3000/api/finsight", help="API base URL (default: Next.js proxy, same as website)")
    parser.add_argument("--api-port", type=int, default=5001, help="API port (for starting API)")
    parser.add_argument("--ticker", default="NVO", help="Company ticker")
    parser.add_argument("--year", type=int, default=2024, help="Filing year")
    parser.add_argument("--keep-api", action="store_true", help="Keep API running after test (don't cleanup)")
    parser.add_argument("--test", choices=["income", "comprehensive", "balance", "cashflow", "equity", "all"], default="all", help="Which test(s) to run")
    
    args = parser.parse_args()
    
    # Ensure API is running
    if not ensure_api_running(args.api_base, args.api_port):
        print(f"\n❌ Failed to start API. Exiting.")
        sys.exit(1)
    
    # Run tests
    results = {}
    
    if args.test in ["income", "all"]:
        results["income_statement"] = test_income_statement(args.api_base, args.ticker, args.year)
    
    if args.test in ["comprehensive", "all"]:
        results["comprehensive_income"] = test_comprehensive_income(args.api_base, args.ticker, args.year)
    
    if args.test in ["balance", "all"]:
        results["balance_sheet"] = test_balance_sheet(args.api_base, args.ticker, args.year)
    
    if args.test in ["cashflow", "all"]:
        results["cash_flow"] = test_cash_flow(args.api_base, args.ticker, args.year)
    
    if args.test in ["equity", "all"]:
        results["equity_statement"] = test_equity_statement(args.api_base, args.ticker, args.year)
    
    # Cleanup if requested
    if not args.keep_api:
        cleanup_api()
    
    # Exit with error code if any test failed
    all_passed = all(r["success"] for r in results.values())
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
