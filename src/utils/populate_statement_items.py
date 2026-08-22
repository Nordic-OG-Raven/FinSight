#!/usr/bin/env python3
"""
Populate rel_statement_items table from rel_presentation_hierarchy.

This function:
1. Filters presentation hierarchy to only main statement items (not detail/disclosure)
2. Computes display_order (handles EPS items, headers, etc.)
3. Sets is_header flag for header items
4. Sets is_main_item flag (exclude detail/disclosure items)

This is Approach 2 from STATEMENT_ORGANIZATION_STRATEGY.md
"""

import sys
import logging
from pathlib import Path
from typing import Dict, List, Optional
from sqlalchemy import create_engine, text
from config import DATABASE_URI

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logger = logging.getLogger(__name__)


def is_main_statement_item(role_uri: Optional[str], source: str, statement_type: str, normalized_label: Optional[str] = None, order_index: Optional[int] = None, concept_name: Optional[str] = None) -> bool:
    """
    Determine if a presentation hierarchy item is a main statement item (not detail/disclosure).
    
    Args:
        role_uri: XBRL role URI from presentation hierarchy
        source: 'xbrl' or 'standard'
        statement_type: 'income_statement', 'balance_sheet', etc.
        normalized_label: Optional normalized label for additional filtering
        order_index: Optional order index - items with order_index >= 1000 are typically disclosures
    
    Returns:
        True if this is a main statement item, False if it's a detail/disclosure
    """
    # UNIVERSAL FIX: Filter out disclosure items by order_index
    # Items with order_index >= 1000 are typically disclosure items (notes, schedules, etc.)
    # This works across all companies because XBRL uses high order_index values for disclosures
    if order_index is not None and order_index >= 1000:
        return False
    
    # UNIVERSAL FIX: Filter disclosure items by label patterns (works for all companies)
    # These patterns indicate disclosure/note items that shouldn't be in main statements
    label_lower = (normalized_label or '').lower()
    concept_lower = (concept_name or '').lower()
    combined_label = f"{label_lower} {concept_lower}"
    
    disclosure_patterns = [
        'undiscounted cash flows', 'percent of', 'description of', 'number of',
        'maximum borrowing capacity', 'not practicably determinable', 'recognised as of',
        'transferred', 'carrying amount', 'fair value', 'discount rate',
        'applied to', 'projections', 'indirect production costs', 'consequences of',
        'granted each', 'outstanding in', 'as a percentage', 'other provisions',
        'provisions for', 'provisions recognised', 'line of credit', 'shortterm borrowings'
    ]
    
    if any(pattern in combined_label for pattern in disclosure_patterns):
        return False
    
    # Standard templates are always main items (but still check for disclosure patterns)
    if source == 'standard':
        # Even standard templates can have disclosure items - filter them out
        if any(pattern in combined_label for pattern in disclosure_patterns):
            return False
        return True
    
    # CRITICAL: For comprehensive_income, allow NULL role_uri (items routed from other statement types)
    # This must be checked BEFORE the general "if not role_uri" check
    if statement_type == 'comprehensive_income':
        if role_uri is None:
            # NULL role_uri - allow for comprehensive income (items routed from cash_flow, other, etc.)
            return True
    
    # If no role_uri, can't determine - exclude to be safe (for other statement types)
    if not role_uri:
        return False
    
    role_uri_lower = role_uri.lower()
    
    # Check statement type specific patterns
    if statement_type == 'income_statement':
        # Must be income statement role, not balance sheet, cash flow, or equity
        if not ('incomestatement' in role_uri_lower or 'statementofcomprehensiveincome' in role_uri_lower):
            return False
        if 'balancesheet' in role_uri_lower or 'balance' in role_uri_lower and 'sheet' in role_uri_lower:
            return False
        if 'cashflow' in role_uri_lower:
            return False
        if 'equity' in role_uri_lower:
            return False
        
        # Exclude detail/disclosure patterns (generic patterns that work for all companies)
        # Note: 'segment' is excluded only if it's a segment breakdown role, not if it's in the main statement
        # 'tax', 'results', 'capital' are excluded only if they indicate detail/disclosure roles
        if any(pattern in role_uri_lower for pattern in [
            'detail', 'disclosure', 'reconciliation', 'breakdown', 'note', 
            'table', 'policy'
        ]):
            return False
        
        # Exclude segment breakdown roles (but allow main statement items that happen to mention segments)
        if '/segment' in role_uri_lower or 'segmentinformation' in role_uri_lower:
            return False
        
        # Exclude tax detail roles (but allow main statement tax items)
        if 'tax' in role_uri_lower and ('detail' in role_uri_lower or 'reconciliation' in role_uri_lower):
            return False
        
        # Allow combined income statement + comprehensive income roles
        # These are standard IFRS patterns (e.g., "IncomestatementandStatementofcomprehensiveincome")
        if 'incomestatementandstatementofcomprehensiveincome' in role_uri_lower:
            # Exclude if it has sub-paths after the main role (indicates detail variant)
            # Example: "IncomestatementandStatementofcomprehensiveincomeStatementofcomprehensiveincome" is OK
            # But "IncomestatementandStatementofcomprehensiveincome/Detail" is not
            if '/role/incomestatementandstatementofcomprehensiveincome/' in role_uri_lower:
                return False
            return True
        
        # Allow standard income statement patterns (works for all companies)
        if '/role/incomestatement' in role_uri_lower or '/role/statementofcomprehensiveincome' in role_uri_lower:
            # Exclude if it has sub-paths (indicates detail variant)
            if '/role/incomestatement/' in role_uri_lower or '/role/statementofcomprehensiveincome/' in role_uri_lower:
                return False
            return True
        
        return False
    
    elif statement_type == 'balance_sheet':
        # Use role_uri patterns to identify main balance sheet items
        # This is the authoritative source - no routing needed if parse_xbrl.py extracts statement_type correctly
        if not role_uri:
            return False  # No role_uri means we can't verify it's a main item
        
        if not ('balancesheet' in role_uri_lower or 
                ('balance' in role_uri_lower and 'sheet' in role_uri_lower) or 
                'statementoffinancialposition' in role_uri_lower):
            return False
        if 'cashflow' in role_uri_lower:
            return False
        if any(pattern in role_uri_lower for pattern in ['detail', 'disclosure']):
            return False
        return True
    
    elif statement_type == 'cash_flow':
        if not ('cashflow' in role_uri_lower or 'statementofcashflows' in role_uri_lower):
            return False
        if any(pattern in role_uri_lower for pattern in ['detail', 'disclosure']):
            return False
        return True
    
    elif statement_type == 'comprehensive_income':
        # Allow comprehensive income items from:
        # 1. Combined income statement + comprehensive income roles
        # 2. Equity statement roles (comprehensive income often appears there)
        # 3. NULL role_uri (items from standard templates or missing role_uri) - handled at top of function
        if 'statementofcomprehensiveincome' in role_uri_lower or 'incomestatementandstatement' in role_uri_lower:
            # Standard comprehensive income role - check for detail/disclosure
            if any(pattern in role_uri_lower for pattern in ['detail', 'disclosure']):
                return False
            return True
        elif 'equitystatement' in role_uri_lower:
            # Equity statement - allow if not detail/disclosure
            if any(pattern in role_uri_lower for pattern in ['detail', 'disclosure']):
                return False
            return True
        # For other role URIs, still allow if not detail/disclosure (items routed from 'other' statement_type)
        if any(pattern in role_uri_lower for pattern in ['detail', 'disclosure']):
            return False
        return True
    
    elif statement_type == 'equity_statement':
        # Equity statement: Statement of Changes in Equity
        if not ('equitystatement' in role_uri_lower or 
                'statementofchangesinequity' in role_uri_lower or
                'changesinequity' in role_uri_lower):
            return False
        if any(pattern in role_uri_lower for pattern in ['detail', 'disclosure']):
            return False
        # CRITICAL: Exclude balance sheet items (like "Total equity") from equity statement
        # Equity statement shows CHANGES in equity, not the balance sheet equity total
        if normalized_label and ('equity_total' in normalized_label.lower() or 
                                 normalized_label.lower() == 'total_equity'):
            return False  # This is a balance sheet item, not an equity statement item
        return True
    
    return False


def determine_balance_sheet_side(normalized_label: str, concept_name: str = None) -> Optional[str]:
    """
    Determine balance sheet side (assets vs liabilities_equity) based on concept type.
    This is UNIVERSAL - works for all companies following IFRS/US-GAAP.
    
    Args:
        normalized_label: Normalized label of the concept
        concept_name: XBRL concept name (optional, for additional matching)
    
    Returns:
        'assets' or 'liabilities_equity' or None if cannot determine
    """
    label_lower = (normalized_label or '').lower()
    concept_lower = (concept_name or '').lower()
    combined = f"{label_lower} {concept_lower}"
    
    # ASSETS (Left side)
    # Standard asset patterns
    asset_patterns = [
        'asset', 'receivable', 'inventory', 'inventories', 'prepayment', 'prepayments',
        'cash', 'bank', 'securities', 'investment', 'equipment', 'plant', 'property',
        'intangible', 'goodwill', 'deferred_tax_asset', 'current_tax_asset',
        'derivative_financial_asset', 'financial_asset', 'marketable_security'
    ]
    
    # LIABILITIES & EQUITY (Right side)
    # Standard liability patterns
    liability_patterns = [
        'liability', 'liabilities', 'payable', 'payables', 'borrowing', 'borrowings',
        'debt', 'deferred_tax_liability', 'current_tax_liability', 'provision', 'provisions',
        'obligation', 'obligations', 'derivative_financial_liability', 'financial_liability'
    ]
    
    # Equity patterns
    equity_patterns = [
        'equity', 'share_capital', 'issued_capital', 'treasury_share', 'treasury_shares',
        'retained_earnings', 'reserve', 'reserves', 'stockholders_equity',
        'equity_attributable', 'noncontrolling_interest'
    ]
    
    # Check for assets first
    # CRITICAL: Check for specific asset items before general patterns
    # "Investments in associates" is an ASSET, not equity (even though it's accounted for using equity method)
    if 'investment' in combined and 'associate' in combined:
        return 'assets'  # Investments in associates are assets
    
    if any(pattern in combined for pattern in asset_patterns):
        # Exclude liability/equity items that might contain "asset" in their name
        if not any(pattern in combined for pattern in ['liability', 'equity', 'payable']):
            return 'assets'
    
    # Check for liabilities
    if any(pattern in combined for pattern in liability_patterns):
        return 'liabilities_equity'
    
    # Check for equity
    if any(pattern in combined for pattern in equity_patterns):
        return 'liabilities_equity'
    
    # Special cases: totals that indicate side
    if 'total_assets' in label_lower or 'assets_total' in label_lower:
        return 'assets'
    
    if ('total_liabilities' in label_lower or 'liabilities_total' in label_lower or
        'equity_and_liabilities' in label_lower or 'liabilities_and_stockholders_equity' in label_lower or
        'total_equity' in label_lower or 'equity_total' in label_lower):
        return 'liabilities_equity'
    
    # Default: cannot determine
    return None


def compute_comprehensive_income_order(normalized_label: str) -> int:
    """
    Compute display_order for comprehensive income items based on IFRS standard structure.
    This is UNIVERSAL - works for all companies following IFRS/US-GAAP.
    
    Standard IFRS comprehensive income structure:
    0. Net profit (from income statement)
    1. Remeasurements of retirement benefit obligations
    2. Items that will not be reclassified...
    3. Exchange rate adjustments...
    4. Cash flow hedges (header)
    5. Realisation of previously deferred...
    6. Deferred gains/(losses) related to acquisition...
    7. Deferred gains/(losses) on hedges open...
    8. Tax and other items
    9. Items that will be reclassified...
    10. Other comprehensive income (total)
    11. Total comprehensive income
    
    Returns:
        display_order for comprehensive income items
    """
    label_lower = normalized_label.lower()
    
    # Net profit (from income statement) - already handled separately with display_order=0
    if 'net_income' in label_lower and 'noncontrolling' in label_lower:
        return 0
    
    # "Other comprehensive income" header - comes right after Net profit
    if 'other_comprehensive_income_header' in label_lower:
        return 1  # Right after Net profit (0)
    
    # Remeasurements of retirement benefit obligations (first OCI item)
    if 'remeasurement' in label_lower and 'defined_benefit' in label_lower:
        return 2  # After header (1)
    
    # Items that will not be reclassified (subtotal for remeasurements)
    if 'will_not_be_reclassified' in label_lower:
        return 3  # After remeasurements (2)
    
    # Exchange rate adjustments
    if 'exchange' in label_lower and ('translation' in label_lower or 'differences' in label_lower):
        return 4  # After "will not be reclassified" (3)
    
    # Cash flow hedges header
    if 'cash_flow_hedges_header' in label_lower:
        return 5  # After exchange rate adjustments (4)
    
    # Cash flow hedges items (grouped together)
    if 'reclassification_adjustments_on_cash_flow_hedges' in label_lower:
        return 6  # Realisation of previously deferred (after header at 5)
    if 'cash_flow_hedges_related_to_acquisition' in label_lower:
        return 7  # Related to acquisition (after realisation at 6)
    if 'cash_flow_hedges_before_tax' in label_lower and 'reclassification' not in label_lower:
        return 8  # On hedges open at year-end (after acquisition at 7)
    
    # Tax and other items
    if 'tax' in label_lower and 'other' in label_lower and 'comprehensive' in label_lower:
        return 9  # After all cash flow hedge items (8)
    
    # Items that will be reclassified (subtotal for cash flow hedges + exchange)
    # Check for both patterns: "will_be_reclassified" and "will be reclassified"
    if 'will_be_reclassified' in label_lower or ('will' in label_lower and 'be' in label_lower and 'reclassified' in label_lower):
        return 10  # After tax and other items (9)
    
    # Other comprehensive income (total OCI) - comes near the end, before total comprehensive income
    if 'oci_total' in label_lower or ('other_comprehensive_income' in label_lower and 'total' in label_lower):
        return 15  # After all OCI items, before total comprehensive income
    
    # Total comprehensive income (grand total) - always last
    if 'comprehensive_income' in label_lower and 'other' not in label_lower and 'oci' not in label_lower:
        return 16  # Always last
    
    # Default: use a high number so unknown items appear at the end
    return 999


def compute_cash_flow_order(normalized_label: str) -> int:
    """
    Compute display_order for cash flow statement items based on IFRS/US-GAAP standard structure.
    This is UNIVERSAL - works for all companies following IFRS/US-GAAP.
    
    Standard cash flow statement structure:
    0. Net profit
    1. Adjustment of non-cash items (header)
    2. Income taxes in the income statement
    3. Depreciation, amortisation and impairment losses
    4. Other non-cash items
    5. Changes in working capital
    6. Interest received
    7. Interest paid
    8. Income taxes paid
    9. Net cash flows from operating activities
    10. Purchase of intangible assets
    11. Purchase of property, plant and equipment
    12. Cash used for acquisition of businesses
    13. Proceeds from other financial assets
    14. Purchase of other financial assets
    15. Purchase of marketable securities
    16. Sale of marketable securities
    17. Net cash flows from investing activities
    18. Purchase of treasury shares
    19. Dividends paid
    20. Proceeds from borrowings
    21. Repayment of borrowings
    22. Net cash flows from financing activities
    23. Net cash generated from activities
    24. Cash and cash equivalents at the beginning of the year
    25. Exchange gains/(losses) on cash and cash equivalents
    26. Cash and cash equivalents at the end of the year
    
    Returns:
        display_order for cash flow items
    """
    label_lower = normalized_label.lower()
    
    # Net profit (from income statement)
    if 'net_income' in label_lower or 'profit_loss' in label_lower:
        return 0
    
    # "Adjustment of non-cash items" header - comes right after Net profit
    if 'adjustment_of_non_cash_items_header' in label_lower or 'adjustments_for_non_cash_items_header' in label_lower:
        return 1
    
    # Income taxes in the income statement (adjustment)
    if 'adjustments_for_income_tax' in label_lower or ('income_tax' in label_lower and 'adjustment' in label_lower):
        return 2
    
    # Depreciation, amortisation and impairment losses
    if 'adjustments_for_depreciation' in label_lower or 'depreciation' in label_lower and 'amortisation' in label_lower:
        return 3
    
    # Other non-cash items
    if 'other_adjustments_for_noncash' in label_lower:
        return 4
    
    # Changes in working capital
    if 'increase_decrease_in_working_capital' in label_lower:
        return 5
    
    # Interest received
    if 'interest_received' in label_lower and 'operating' in label_lower:
        return 6
    
    # Interest paid
    if 'interest_paid' in label_lower and 'operating' in label_lower:
        return 7
    
    # Income taxes paid
    if 'income_taxes_paid' in label_lower and 'operating' in label_lower:
        return 8
    
    # Net cash flows from operating activities
    if ('cash_flows_from' in label_lower and 'operating' in label_lower) or 'operating_cash_flow' in label_lower:
        return 9
    
    # Investing activities
    if 'purchase_of_intangible_assets' in label_lower and 'investing' in label_lower:
        return 10
    if 'purchase_of_property_plant_and_equipment' in label_lower and 'investing' in label_lower:
        return 11
    if 'cash_flows_used_in_obtaining_control' in label_lower:
        return 12
    if 'proceeds_from_sale_of_other_financial_assets' in label_lower and 'investing' in label_lower:
        return 13
    if 'purchase_of_other_financial_assets' in label_lower and 'investing' in label_lower:
        return 14
    if ('purchase_of_financial_assets_measured_at_fair_value' in label_lower or 'purchase_of_financial_assets_measured_at_fair_value_through_profit_or_loss' in label_lower) and ('investing' in label_lower or 'classified_as_inv' in label_lower):
        return 15
    if 'proceeds_from_disposal_of_marketable_securities' in label_lower and 'investing' in label_lower:
        return 16
    if ('cash_flows_from' in label_lower and 'investing' in label_lower) or 'investing_cash_flow' in label_lower:
        return 17
    
    # Financing activities
    if 'payments_to_acquire_or_redeem_entitys_shares' in label_lower:
        return 18
    if 'dividends_paid' in label_lower and 'financing' in label_lower:
        return 19
    if 'proceeds_from_borrowings' in label_lower and 'financing' in label_lower:
        return 20
    if 'repayments_of_borrowings' in label_lower and 'financing' in label_lower:
        return 21
    if ('cash_flows_from' in label_lower and 'financing' in label_lower) or 'financing_cash_flow' in label_lower:
        return 22
    
    # Net cash generated from activities
    if 'increase_decrease_in_cash_and_cash_equivalents_before_effect' in label_lower:
        return 23
    
    # Cash and cash equivalents at the beginning of the year
    if 'cash_and_cash_equivalents_at_the_beginning' in label_lower:
        return 24
    
    # Exchange gains/(losses) on cash and cash equivalents
    if 'effect_of_exchange_rate_changes_on_cash_and_cash_equivalents' in label_lower:
        return 25
    
    # Cash and cash equivalents at the end of the year
    # UNIVERSAL FIX: Handle all cash equivalent variants (works for all companies)
    # Handle both full label and shortened "cash_and_equivalents" (which is end-of-year cash)
    # Also handle bank-specific labels like "cash_at_bank", "balances_with_banks" in cash flow
    if ('cash_and_cash_equivalents_at_the_end' in label_lower or 
        (label_lower in ['cash_and_equivalents', 'cash_at_bank', 'balances_with_banks'] and 'beginning' not in label_lower)):
        return 26
    
    # Fallback: use a high number so unmapped items appear at the end
    return 999


def compute_equity_order(normalized_label: str) -> int:
    """
    Compute display_order for equity statement items based on IFRS/US-GAAP standard structure.
    This is UNIVERSAL - works for all companies following IFRS/US-GAAP.
    
    Standard equity statement structure:
    0. Balance at the beginning of the year
    1. Net profit
    2. Other comprehensive income
    3. Total comprehensive income
    4. Transfer of cash flow hedge reserve to intangible assets
    5. Transactions with owners (header)
    6. Dividends
    7. Share-based payments
    8. Purchase of treasury shares
    9. Reduction of the B share capital
    10. Tax related to transactions with owners
    11. Balance at the end of the year
    
    Returns:
        display_order for equity statement items
    """
    label_lower = normalized_label.lower()
    
    # Balance at the beginning of the year
    if 'balance' in label_lower and 'beginning' in label_lower:
        return 0
    
    # Net profit (from income statement)
    if 'net_income' in label_lower or ('profit_loss' in label_lower and 'comprehensive' not in label_lower):
        return 1
    
    # Space 1: After Net profit (synthetic, handled separately)
    # Expected position: 3 (after Net profit at 1, before Other comprehensive income at 4)
    # UNIVERSAL FIX: Handle both normalized_label variants (with and without underscore)
    if 'equity_statement_space_1' in label_lower or 'equity_statement_space1' in label_lower:
        return 3
    
    # Other comprehensive income (must come before total)
    # Handle both "other_comprehensive_income" and "oci_total" patterns
    # Expected position: 4 (after space at 3)
    if 'oci_total' in label_lower or ('other_comprehensive_income' in label_lower and 'total' not in label_lower and 'net_of_tax' not in label_lower):
        return 4
    
    # Total comprehensive income
    # Handle both "total_comprehensive_income" and "comprehensive_income" (without "other" prefix)
    # Expected position: 5 (after Other comprehensive income at 4)
    if 'total_comprehensive_income' in label_lower or (label_lower == 'comprehensive_income' and 'other' not in label_lower):
        return 5
    
    # Transfer of cash flow hedge reserve to intangible assets
    # Expected position: 6 (after Total comprehensive income at 5)
    if 'amount_removed_from_reserve_of_cash_flow_hedges' in label_lower or ('transfer' in label_lower and 'cash_flow_hedge' in label_lower):
        return 6
    
    # Space 2: After Transfer of cash flow hedge reserve (synthetic, handled separately)
    # Expected position: 7 (after Transfer at 6, before Transactions with owners at 8)
    # UNIVERSAL FIX: Handle both normalized_label variants (with and without underscore)
    if 'equity_statement_space_2' in label_lower or 'equity_statement_space2' in label_lower:
        return 7
    
    # Transactions with owners (header) - synthetic, handled separately
    # Expected position: 8 (after space at 7)
    if 'transactions_with_owners_header' in label_lower:
        return 8
    
    # Dividends (first transaction item)
    # Expected position: 9 (after Transactions with owners header at 8)
    if 'dividends_paid' in label_lower or ('dividend' in label_lower and 'paid' in label_lower):
        return 9
    
    # Share-based payments (second transaction item)
    # Expected position: 10 (after Dividends at 9)
    if 'increase_decrease_through_sharebased_payment' in label_lower or ('sharebased_payment' in label_lower and 'tax' not in label_lower):
        return 10
    
    # Purchase of treasury shares (third transaction item)
    # Expected position: 11 (after Share-based payments at 10)
    if 'purchase_of_treasury_shares' in label_lower or ('payments_to_acquire_or_redeem_entitys_shares' in label_lower):
        return 11
    
    # Reduction of the B share capital (fourth transaction item)
    # Expected position: 12 (after Purchase of treasury shares at 11)
    if 'reduction_of_issued_capital' in label_lower or ('reduction' in label_lower and 'capital' in label_lower):
        return 12
    
    # Tax related to transactions with owners (last transaction item - must come after all others)
    # Expected position: 13 (after Reduction at 12)
    if 'decrease_increase_through_tax_on_sharebased' in label_lower or ('tax' in label_lower and 'sharebased' in label_lower and 'payment' in label_lower):
        return 13
    
    # Balance at the end of the year
    # Expected position: 14 (after Tax at 13)
    if 'balance' in label_lower and 'end' in label_lower:
        return 14
    
    # Fallback: use a high number so unmapped items appear at the end
    return 999


def infer_display_order_from_other_years(
    conn, 
    filing_id: int, 
    concept_id: int, 
    statement_type: str
) -> Optional[int]:
    """
    Infer display_order from other filings of the same company where XBRL succeeded.
    
    Priority:
    1. Most recent filing with valid order_index
    2. Most common order_index across all years (if multiple exist)
    3. None (fallback to standard templates)
    
    Args:
        conn: Database connection
        filing_id: Current filing ID (to exclude from search)
        concept_id: Concept ID to find order for
        statement_type: Statement type (income_statement, balance_sheet, etc.)
    
    Returns:
        Inferred display_order or None if no valid orders found
    """
    query = text("""
        WITH company_filings AS (
            SELECT f2.filing_id, f2.fiscal_year_end
            FROM dim_filings f1
            JOIN dim_filings f2 ON f1.company_id = f2.company_id
            WHERE f1.filing_id = :filing_id
              AND f2.filing_id != :filing_id
        ),
        valid_orders AS (
            SELECT si.display_order, COUNT(*) as count, MAX(cf.fiscal_year_end) as latest_year
            FROM rel_statement_items si
            JOIN company_filings cf ON si.filing_id = cf.filing_id
            WHERE si.concept_id = :concept_id
              AND si.statement_type = :statement_type
              AND si.display_order IS NOT NULL
              AND si.source = 'xbrl'  -- Only trust XBRL orders
            GROUP BY si.display_order
        )
        SELECT display_order
        FROM valid_orders
        ORDER BY latest_year DESC, count DESC
        LIMIT 1
    """)
    
    try:
        result = conn.execute(query, {
            'filing_id': filing_id,
            'concept_id': concept_id,
            'statement_type': statement_type
        })
        row = result.fetchone()
        if row:
            logger.info(f"Inferred display_order={row[0]} for filing_id={filing_id}, concept_id={concept_id}, statement_type={statement_type} from other years")
            return row[0]
    except Exception as e:
        logger.warning(f"Failed to infer display_order for filing_id={filing_id}, concept_id={concept_id}: {e}")
    
    return None


def compute_display_order(
    order_index: int, 
    normalized_label: str, 
    statement_type: str, 
    max_order_in_statement: Optional[int] = None,
    use_xbrl_order: bool = True  # NEW: Flag to enable/disable XBRL-first
) -> int:
    """
    Compute display_order with XBRL-first approach.
    
    Priority:
    1. XBRL order_index (if available and valid)
    2. Standard templates (only when XBRL is broken/missing)
    
    Args:
        order_index: Original order_index from presentation hierarchy
        normalized_label: Normalized label of the concept
        statement_type: Statement type
        max_order_in_statement: Maximum order_index in the statement (for EPS positioning)
        use_xbrl_order: If True, use XBRL order_index as primary source (default: True)
    
    Returns:
        Corrected display_order
    """
    label_lower = normalized_label.lower()
    
    # PRIMARY: Use XBRL order if available and valid
    if use_xbrl_order and order_index is not None and order_index < 1000:
        # Only apply minimal corrections (e.g., EPS positioning)
        if statement_type == 'income_statement' and 'earnings' in label_lower and 'share' in label_lower:
            # EPS items: place after net profit (minimal correction)
            if max_order_in_statement is not None:
                return max_order_in_statement + 2 + order_index
            else:
                # Fallback: use fixed offset (net income typically at 13, so header at 14, basic at 15, diluted at 16)
                return 15 + order_index
        
        # CRITICAL FIX: Cash flow tie-breaker - Net profit must come before Income taxes
        # When both have XBRL order_index = 1, use template order as tie-breaker
        if statement_type == 'cash_flow' and order_index == 1:
            if 'net_income' in label_lower or 'net_profit' in label_lower or 'profit_loss' in label_lower:
                return 1.0  # Net profit at exactly 1.0
            elif 'adjustments_for_income_tax' in label_lower or ('income_tax' in label_lower and 'adjustment' in label_lower):
                return 1.01  # Income taxes slightly after (1.01) so it comes after Net profit (1.0)
        
        return order_index  # Use XBRL order directly
    
    # FALLBACK: Use standard templates only when XBRL is broken/missing
    if statement_type == 'comprehensive_income':
        return compute_comprehensive_income_order(normalized_label)
    if statement_type == 'cash_flow':
        return compute_cash_flow_order(normalized_label)
    if statement_type == 'equity_statement':
        return compute_equity_order(normalized_label)
    
    return 999  # Unmapped items


def populate_templates_from_items(conn, filing_id: Optional[int], items: List[Dict]):
    """
    Populate dim_statement_templates and rel_statement_overrides from rel_statement_items.
    
    This function:
    1. Checks if items match existing templates (standard items)
    2. Creates templates for common items (if not exists)
    3. Creates overrides for custom items (filing-specific)
    
    Args:
        conn: Database connection
        filing_id: Filing ID (if None, skip override population)
        items: List of statement items from populate_statement_items
    """
    if not items or filing_id is None:
        return
    
    # Get company accounting standard to determine format_type
    company_query = text("""
        SELECT c.accounting_standard
        FROM dim_filings f
        JOIN dim_companies c ON f.company_id = c.company_id
        WHERE f.filing_id = :filing_id
    """)
    result = conn.execute(company_query, {"filing_id": filing_id})
    row = result.fetchone()
    if not row:
        return
    
    accounting_standard = row[0] or 'US-GAAP'
    format_type = 'ifrs' if accounting_standard == 'IFRS' else 'us_gaap' if accounting_standard == 'US-GAAP' else 'standard'
    
    # Get concept info for items
    concept_ids = [item['concept_id'] for item in items if item.get('concept_id')]
    if not concept_ids:
        return
    
    concept_query = text("""
        SELECT concept_id, normalized_label, preferred_label
        FROM dim_concepts
        WHERE concept_id = ANY(:concept_ids)
    """)
    concept_result = conn.execute(concept_query, {"concept_ids": concept_ids})
    concepts = {row[0]: {'normalized_label': row[1], 'preferred_label': row[2]} for row in concept_result}
    
    # Process each item
    for item in items:
        concept_id = item.get('concept_id')
        if not concept_id:
            continue
        
        concept_info = concepts.get(concept_id, {})
        normalized_label = concept_info.get('normalized_label')
        preferred_label = concept_info.get('preferred_label')
        statement_type = item.get('statement_type')
        display_order = item.get('display_order')
        is_header = item.get('is_header', False)
        side = item.get('side')
        
        if not statement_type or display_order is None:
            continue
        
        # Determine item_label
        item_label = preferred_label or normalized_label or ('Header' if is_header else 'Item')
        
        # Check if template exists for this (statement_type, format_type, item_order)
        template_check = text("""
            SELECT template_id FROM dim_statement_templates
            WHERE statement_type = :statement_type
              AND format_type = :format_type
              AND item_order = :item_order
        """)
        template_result = conn.execute(template_check, {
            "statement_type": statement_type,
            "format_type": format_type,
            "item_order": display_order
        })
        template_row = template_result.fetchone()
        
        if template_row:
            # Template exists - check if we need an override
            template_id = template_row[0]
            
            # Check if override already exists
            override_check = text("""
                SELECT override_id FROM rel_statement_overrides
                WHERE filing_id = :filing_id AND item_order = :item_order
            """)
            override_result = conn.execute(override_check, {
                "filing_id": filing_id,
                "item_order": display_order
            })
            
            if not override_result.fetchone():
                # Create override if item differs from template or is custom
                # For now, only create override if item_label differs significantly
                # (This is a simple heuristic - can be enhanced)
                try:
                    conn.execute(text("""
                        INSERT INTO rel_statement_overrides (
                            filing_id, template_id, item_order, item_label,
                            normalized_label, is_header, is_spacer, side, is_custom
                        ) VALUES (
                            :filing_id, :template_id, :item_order, :item_label,
                            :normalized_label, :is_header, FALSE, :side, FALSE
                        )
                        ON CONFLICT (filing_id, item_order) DO NOTHING
                    """), {
                        "filing_id": filing_id,
                        "template_id": template_id,
                        "item_order": display_order,
                        "item_label": item_label,
                        "normalized_label": normalized_label,
                        "is_header": is_header,
                        "side": side
                    })
                except Exception:
                    # Table might not exist - skip silently
                    pass
        else:
            # No template exists - could create one, but for now just create override
            # (Templates should be populated via migration script for canonical items)
            try:
                conn.execute(text("""
                    INSERT INTO rel_statement_overrides (
                        filing_id, template_id, item_order, item_label,
                        normalized_label, is_header, is_spacer, side, is_custom
                    ) VALUES (
                        :filing_id, NULL, :item_order, :item_label,
                        :normalized_label, :is_header, FALSE, :side, TRUE
                    )
                    ON CONFLICT (filing_id, item_order) DO NOTHING
                """), {
                    "filing_id": filing_id,
                    "item_order": display_order,
                    "item_label": item_label,
                    "normalized_label": normalized_label,
                    "is_header": is_header,
                    "side": side
                })
            except Exception:
                # Table might not exist - skip silently
                pass
    
    conn.commit()


def detect_xbrl_label_role_headers(
    conn,
    filing_id: int,
    statement_type: str
) -> List[Dict]:
    """
    Detect headers from XBRL label roles.
    
    A concept is a header if:
    1. It has label_role='documentation' in dim_concepts
    2. It's in rel_presentation_hierarchy for this statement
    3. It has no facts (or all facts are NULL)
    
    Returns:
        List of header items with concept_id, display_order, header_source='xbrl_label_role'
    """
    documentation_role = "http://www.xbrl.org/2003/role/documentation"
    
    query = text("""
        WITH concepts_with_documentation_role AS (
            SELECT 
                co.concept_id,
                co.normalized_label,
                co.preferred_label
            FROM dim_concepts co
            WHERE co.label_role = :documentation_role
        ),
        concepts_in_presentation AS (
            SELECT DISTINCT
                ph.child_concept_id as concept_id,
                MIN(ph.order_index) as min_order_index
            FROM rel_presentation_hierarchy ph
            WHERE ph.filing_id = :filing_id
              AND ph.statement_type = :statement_type
            GROUP BY ph.child_concept_id
        ),
        concepts_without_facts AS (
            SELECT 
                cpr.concept_id,
                cpr.min_order_index
            FROM concepts_in_presentation cpr
            JOIN concepts_with_documentation_role cdr ON cpr.concept_id = cdr.concept_id
            WHERE NOT EXISTS (
                SELECT 1 
                FROM fact_financial_metrics fm
                WHERE fm.filing_id = :filing_id
                  AND fm.concept_id = cpr.concept_id
                  AND fm.dimension_id IS NULL
                  AND fm.value_numeric IS NOT NULL
            )
        )
        SELECT 
            cwf.concept_id,
            CASE 
                -- Position headers BEFORE their children to avoid conflicts
                -- Use min_order_index - 0.5 to place header before first child
                WHEN cwf.min_order_index > 0 THEN cwf.min_order_index - 0.5
                ELSE 0  -- If children start at 0, header goes at -0.5 (will be adjusted to 0)
            END as display_order,
            co.normalized_label,
            co.preferred_label
        FROM concepts_without_facts cwf
        JOIN dim_concepts co ON cwf.concept_id = co.concept_id
        WHERE NOT EXISTS (
            -- Exclude if already in rel_statement_items (avoid duplicates)
            SELECT 1 FROM rel_statement_items si
            WHERE si.filing_id = :filing_id
              AND si.concept_id = cwf.concept_id
              AND si.statement_type = :statement_type
        )
        ORDER BY cwf.min_order_index
    """)
    
    try:
        result = conn.execute(query, {
            'filing_id': filing_id,
            'statement_type': statement_type,
            'documentation_role': documentation_role
        })
        headers = []
        for row in result.fetchall():
            headers.append({
                'concept_id': row[0],
                'display_order': row[1],
                'normalized_label': row[2],
                'preferred_label': row[3]
            })
        
        if headers:
            logger.info(f"Detected {len(headers)} XBRL label role headers for filing_id={filing_id}, statement_type={statement_type}")
        
        return headers
    except Exception as e:
        logger.warning(f"Failed to detect XBRL label role headers for filing_id={filing_id}, statement_type={statement_type}: {e}")
        return []


def detect_xbrl_parent_headers(
    conn,
    filing_id: int,
    statement_type: str
) -> List[Dict]:
    """
    Detect headers from XBRL parent-child relationships.
    
    A parent concept is a header if:
    1. It has children in rel_presentation_hierarchy
    2. It has no facts in fact_financial_metrics (or all facts are NULL)
    3. It's in the same statement_type
    
    Returns:
        List of header items with concept_id, display_order, header_source='xbrl_parent'
    """
    query = text("""
        WITH parent_concepts AS (
            SELECT DISTINCT ph.parent_concept_id, ph.filing_id, ph.statement_type
            FROM rel_presentation_hierarchy ph
            WHERE ph.filing_id = :filing_id
              AND ph.statement_type = :statement_type
              AND ph.parent_concept_id IS NOT NULL
        ),
        parents_with_children AS (
            SELECT 
                pc.parent_concept_id,
                pc.filing_id,
                pc.statement_type,
                MIN(ph.order_index) as min_order_index  -- Use minimum order_index of children as header position
            FROM parent_concepts pc
            JOIN rel_presentation_hierarchy ph ON 
                ph.filing_id = pc.filing_id
                AND ph.parent_concept_id = pc.parent_concept_id
                AND ph.statement_type = pc.statement_type
            GROUP BY pc.parent_concept_id, pc.filing_id, pc.statement_type
            HAVING COUNT(ph.child_concept_id) > 0  -- Must have at least one child
        ),
        parents_without_facts AS (
            SELECT 
                pwc.parent_concept_id,
                pwc.filing_id,
                pwc.statement_type,
                pwc.min_order_index
            FROM parents_with_children pwc
            WHERE NOT EXISTS (
                SELECT 1 
                FROM fact_financial_metrics fm
                WHERE fm.filing_id = pwc.filing_id
                  AND fm.concept_id = pwc.parent_concept_id
                  AND fm.dimension_id IS NULL
                  AND fm.value_numeric IS NOT NULL
            )
        )
        SELECT 
            pwf.parent_concept_id as concept_id,
            CASE 
                -- Position headers BEFORE their children to avoid conflicts
                -- Use min_order_index - 0.5 to place header before first child
                WHEN pwf.min_order_index > 0 THEN pwf.min_order_index - 0.5
                ELSE 0  -- If children start at 0, header goes at -0.5 (will be adjusted to 0)
            END as display_order,
            co.normalized_label,
            co.preferred_label,
            co.is_abstract
        FROM parents_without_facts pwf
        JOIN dim_concepts co ON pwf.parent_concept_id = co.concept_id
        WHERE NOT EXISTS (
            -- Exclude if already in rel_statement_items (avoid duplicates)
            SELECT 1 FROM rel_statement_items si
            WHERE si.filing_id = pwf.filing_id
              AND si.concept_id = pwf.parent_concept_id
              AND si.statement_type = pwf.statement_type
        )
        ORDER BY pwf.min_order_index
    """)
    
    try:
        result = conn.execute(query, {
            'filing_id': filing_id,
            'statement_type': statement_type
        })
        headers = []
        for row in result.fetchall():
            headers.append({
                'concept_id': row[0],
                'display_order': row[1],
                'normalized_label': row[2],
                'preferred_label': row[3],
                'is_abstract': row[4]
            })
        
        if headers:
            logger.info(f"Detected {len(headers)} XBRL parent headers for filing_id={filing_id}, statement_type={statement_type}")
        
        return headers
    except Exception as e:
        logger.warning(f"Failed to detect XBRL parent headers for filing_id={filing_id}, statement_type={statement_type}: {e}")
        return []


def populate_statement_items(filing_id: Optional[int] = None):
    """
    Populate rel_statement_items table from rel_presentation_hierarchy.
    
    Args:
        filing_id: If provided, only process this filing. Otherwise, process all filings.
    """
    engine = create_engine(DATABASE_URI)
    
    with engine.connect() as conn:
        # First, check which filings have XBRL data vs standard templates
        # We only want to use standard templates if XBRL data doesn't exist
        # Build a set of (filing_id, statement_type) pairs that have XBRL data
        # CRITICAL: Use a transaction to ensure consistency
        xbrl_check = text("""
            SELECT DISTINCT filing_id, statement_type
            FROM rel_presentation_hierarchy
            WHERE source = 'xbrl'
            AND order_index IS NOT NULL
        """)
        xbrl_result = conn.execute(xbrl_check)
        xbrl_statements = {(int(row[0]), str(row[1])) for row in xbrl_result.fetchall()}
        
        # Get all presentation hierarchy items
        # CRITICAL: For income_statement, only use the main role URI to avoid duplicates
        # Different role URIs can have the same concept with different order_index values
        if filing_id:
            query = text("""
                SELECT DISTINCT ON (ph.child_concept_id, ph.statement_type)
                    ph.presentation_id,
                    ph.filing_id,
                    ph.child_concept_id,
                    ph.statement_type,
                    ph.order_index,
                    ph.role_uri,
                    ph.source,
                    co.normalized_label
                FROM rel_presentation_hierarchy ph
                JOIN dim_concepts co ON ph.child_concept_id = co.concept_id
                WHERE ph.filing_id = :filing_id
                AND ph.order_index IS NOT NULL
                AND ph.order_index < 1000  -- UNIVERSAL: Exclude disclosure items (order_index >= 1000)
                ORDER BY ph.child_concept_id, ph.statement_type,
                    CASE 
                        -- For income_statement: prioritize main income statement role_uri (case-insensitive)
                        WHEN ph.statement_type = 'income_statement' AND LOWER(ph.role_uri) LIKE '%incomestatementandstatement%' AND LOWER(ph.role_uri) NOT LIKE '%segment%' AND LOWER(ph.role_uri) NOT LIKE '%detail%' AND LOWER(ph.role_uri) NOT LIKE '%disclosure%' THEN 1
                        WHEN ph.statement_type = 'income_statement' AND LOWER(ph.role_uri) LIKE '%incomestatement%' AND LOWER(ph.role_uri) NOT LIKE '%segment%' AND LOWER(ph.role_uri) NOT LIKE '%detail%' AND LOWER(ph.role_uri) NOT LIKE '%disclosure%' THEN 2
                        
                        -- For cash_flow: prioritize main cash flow statement role_uri (case-insensitive)
                        WHEN ph.statement_type = 'cash_flow' AND LOWER(ph.role_uri) LIKE '%statementofcashflows%' AND LOWER(ph.role_uri) NOT LIKE '%segment%' AND LOWER(ph.role_uri) NOT LIKE '%detail%' AND LOWER(ph.role_uri) NOT LIKE '%disclosure%' AND LOWER(ph.role_uri) NOT LIKE '%reconciliation%' THEN 1
                        WHEN ph.statement_type = 'cash_flow' AND LOWER(ph.role_uri) LIKE '%cashflow%' AND LOWER(ph.role_uri) NOT LIKE '%segment%' AND LOWER(ph.role_uri) NOT LIKE '%detail%' AND LOWER(ph.role_uri) NOT LIKE '%disclosure%' AND LOWER(ph.role_uri) NOT LIKE '%reconciliation%' THEN 2
                        
                        -- For balance_sheet: prioritize main balance sheet role_uri (case-insensitive)
                        WHEN ph.statement_type = 'balance_sheet' AND (LOWER(ph.role_uri) LIKE '%balancesheet%' OR LOWER(ph.role_uri) LIKE '%statementoffinancialposition%') AND LOWER(ph.role_uri) NOT LIKE '%segment%' AND LOWER(ph.role_uri) NOT LIKE '%detail%' AND LOWER(ph.role_uri) NOT LIKE '%disclosure%' THEN 1
                        
                        -- For equity_statement: prioritize main equity statement role_uri (case-insensitive)
                        WHEN ph.statement_type = 'equity_statement' AND (LOWER(ph.role_uri) LIKE '%equitystatement%' OR LOWER(ph.role_uri) LIKE '%statementofchangesinequity%' OR LOWER(ph.role_uri) LIKE '%changesinequity%') AND LOWER(ph.role_uri) NOT LIKE '%segment%' AND LOWER(ph.role_uri) NOT LIKE '%detail%' AND LOWER(ph.role_uri) NOT LIKE '%disclosure%' THEN 1
                        
                        -- For comprehensive_income: prioritize comprehensive income role_uri (case-insensitive)
                        WHEN LOWER(ph.role_uri) LIKE '%statementofcomprehensiveincome%' THEN 3
                        WHEN LOWER(ph.role_uri) LIKE '%incomestatementandstatement%' THEN 4
                        
                        -- Generic fallback: any role_uri that's not detail/disclosure/segment (lowest priority)
                        WHEN ph.role_uri IS NOT NULL AND LOWER(ph.role_uri) NOT LIKE '%segment%' AND LOWER(ph.role_uri) NOT LIKE '%detail%' AND LOWER(ph.role_uri) NOT LIKE '%disclosure%' THEN 5
                        WHEN ph.role_uri IS NOT NULL THEN 6
                        ELSE 7
                    END,
                    -- UNIVERSAL: For income_statement, prefer higher order_index when same concept appears multiple times
                    -- This is universal because net income always appears at the END of income statement (not beginning)
                    -- In combined role_uris (e.g., "IncomestatementandStatementofcomprehensiveincome"), 
                    -- the same concept can appear in both sections with different order_index values.
                    -- For income_statement, we want the one that appears in the income statement section (higher order_index),
                    -- not the one from comprehensive income section (lower order_index).
                    CASE 
                        WHEN ph.statement_type = 'income_statement' THEN -ph.order_index  -- Prefer higher (later in statement)
                        ELSE ph.order_index  -- For other statements, use normal order
                    END
            """)
            params = {"filing_id": filing_id}
        else:
            query = text("""
                SELECT DISTINCT ON (ph.filing_id, ph.child_concept_id, ph.statement_type)
                    ph.presentation_id,
                    ph.filing_id,
                    ph.child_concept_id,
                    ph.statement_type,
                    ph.order_index,
                    ph.role_uri,
                    ph.source,
                    co.normalized_label
                FROM rel_presentation_hierarchy ph
                JOIN dim_concepts co ON ph.child_concept_id = co.concept_id
                WHERE ph.order_index IS NOT NULL
                AND ph.order_index < 1000  -- UNIVERSAL: Exclude disclosure items (order_index >= 1000)
                ORDER BY ph.filing_id, ph.child_concept_id, ph.statement_type,
                    CASE 
                        -- For income_statement: prioritize main income statement role_uri (case-insensitive)
                        WHEN ph.statement_type = 'income_statement' AND LOWER(ph.role_uri) LIKE '%incomestatementandstatement%' AND LOWER(ph.role_uri) NOT LIKE '%segment%' AND LOWER(ph.role_uri) NOT LIKE '%detail%' AND LOWER(ph.role_uri) NOT LIKE '%disclosure%' THEN 1
                        WHEN ph.statement_type = 'income_statement' AND LOWER(ph.role_uri) LIKE '%incomestatement%' AND LOWER(ph.role_uri) NOT LIKE '%segment%' AND LOWER(ph.role_uri) NOT LIKE '%detail%' AND LOWER(ph.role_uri) NOT LIKE '%disclosure%' THEN 2
                        -- For comprehensive_income: prioritize comprehensive income role_uri (case-insensitive)
                        WHEN LOWER(ph.role_uri) LIKE '%statementofcomprehensiveincome%' THEN 3
                        WHEN LOWER(ph.role_uri) LIKE '%incomestatementandstatement%' THEN 4
                        WHEN ph.role_uri IS NOT NULL AND LOWER(ph.role_uri) NOT LIKE '%segment%' AND LOWER(ph.role_uri) NOT LIKE '%detail%' AND LOWER(ph.role_uri) NOT LIKE '%disclosure%' THEN 5
                        WHEN ph.role_uri IS NOT NULL THEN 6
                        ELSE 7
                    END,
                    -- UNIVERSAL: For income_statement, prefer higher order_index when same concept appears multiple times
                    -- This is universal because net income always appears at the END of income statement (not beginning)
                    -- In combined role_uris (e.g., "IncomestatementandStatementofcomprehensiveincome"), 
                    -- the same concept can appear in both sections with different order_index values.
                    -- For income_statement, we want the one that appears in the income statement section (higher order_index),
                    -- not the one from comprehensive income section (lower order_index).
                    CASE 
                        WHEN ph.statement_type = 'income_statement' THEN -ph.order_index  -- Prefer higher (later in statement)
                        ELSE ph.order_index  -- For other statements, use normal order
                    END
            """)
            params = {}
        
        result = conn.execute(query, params)
        rows = result.fetchall()
        
        if not rows:
            print(f"   ⚠️  No presentation hierarchy items found")
            return 0
        
        # First pass: collect XBRL items to find max order for EPS positioning
        # Also track which concepts are EPS items for header creation
        xbrl_items_by_statement = {}  # (filing_id, statement_type) -> max_order
        eps_concepts_by_statement = {}  # (filing_id, statement_type) -> [concept_ids]
        for row in rows:
            pres_id, filing_id_val, concept_id, stmt_type, order_idx, role_uri, source, normalized_label = row
            if source == 'xbrl' and stmt_type:
                key = (filing_id_val, stmt_type)
                if key not in xbrl_items_by_statement:
                    xbrl_items_by_statement[key] = 0
                    eps_concepts_by_statement[key] = []
                if order_idx and order_idx > xbrl_items_by_statement[key]:
                    xbrl_items_by_statement[key] = order_idx
                # Track EPS items
                if normalized_label and ('earnings' in normalized_label.lower() and 'share' in normalized_label.lower()):
                    eps_concepts_by_statement[key].append(concept_id)
        
        # Get all concept_names in one query for efficiency
        concept_ids_list = [row[2] for row in rows]  # concept_id is at index 2
        concept_names_map = {}
        if concept_ids_list:
            concept_names_query = text("""
                SELECT concept_id, concept_name FROM dim_concepts 
                WHERE concept_id = ANY(:concept_ids)
            """)
            concept_names_result = conn.execute(concept_names_query, {'concept_ids': concept_ids_list})
            concept_names_map = {row[0]: row[1] for row in concept_names_result}
        
        # Process each item
        items_to_insert = []
        for row in rows:
            pres_id, filing_id_val, concept_id, stmt_type, order_idx, role_uri, source, normalized_label = row
            concept_name_val = concept_names_map.get(concept_id)
            
            # CRITICAL: Only use standard templates if XBRL data doesn't exist for this filing/statement_type
            if source == 'standard':
                # Check if XBRL exists for this filing/statement_type combo
                if (filing_id_val, stmt_type) in xbrl_statements:
                    continue  # Skip standard template items if XBRL exists
            
            # CRITICAL: statement_type should now be correctly extracted from role_uri in parse_xbrl.py
            # No routing needed - the authoritative source (role_uri) is used during ETL
            # Only route comprehensive income items that come from other statement types (legitimate case)
            role_uri_lower = (role_uri or '').lower() if role_uri else ''
            
            # Route to comprehensive_income ONLY if role_uri explicitly indicates it
            # This handles cases where OCI items appear in equity statements or combined statements
            is_explicit_oci_role = (
                'statementofcomprehensiveincome' in role_uri_lower and
                ('statementofcomprehensiveincome' in role_uri_lower.split('incomestatementandstatement')[-1] if 'incomestatementandstatement' in role_uri_lower else True)
            )
            is_equity_statement_oci = 'equitystatement' in role_uri_lower and 'comprehensive' in role_uri_lower
            
            # Route to comprehensive_income ONLY if role_uri explicitly indicates it
            if (is_explicit_oci_role or is_equity_statement_oci) and stmt_type in ['income_statement', 'other', 'cash_flow']:
                # Exclude core income statement items even if they have OCI role_uri
                label_lower = (normalized_label or '').lower()
                is_core_income_item = label_lower in [
                    'revenue', 'sales', 'cost_of_sales', 'gross_profit',
                    'operating_income', 'operating_profit', 'income_before_tax', 'net_income',
                    'net_income_including_noncontrolling_interest', 'net_profit',
                    'basic_earnings_loss_per_share', 'diluted_earnings_loss_per_share',
                    'selling_expense_and_distribution_costs', 'research_development', 'administrative_expense',
                    'finance_income', 'finance_costs', 'income_tax_expense_continuing_operations',
                    'other_operating_income_expense'
                ]
                
                if not is_core_income_item:
                    stmt_type = 'comprehensive_income'
            
            # Check if this is a main statement item
            is_main = is_main_statement_item(role_uri, source or 'xbrl', stmt_type or 'other', normalized_label, order_idx, concept_name_val)
            
            if not is_main:
                continue  # Skip detail/disclosure items
            
            # CRITICAL: Detail/disclosure items are already filtered by is_main_statement_item()
            # which checks role_uri patterns. No need for label-based filtering here.
            
            # CRITICAL: Exclude detail items from standard templates
            # Standard templates include many detail items that shouldn't be in main statement
            # Use role_uri check - if role_uri contains 'detail' or 'disclosure', skip it
            if source == 'standard':
                if role_uri and any(pattern in role_uri.lower() for pattern in ['detail', 'disclosure', 'reconciliation', 'note', 'schedule']):
                    continue  # Skip detail items from standard templates
            
            # UNIVERSAL FIX: Filter disclosure items by label patterns BEFORE adding to items_to_insert
            # This prevents disclosure items from appearing in main statements
            label_lower = (normalized_label or '').lower()
            concept_lower = (concept_name_val or '').lower() if concept_name_val else ''
            combined_label = f"{label_lower} {concept_lower}"
            
            disclosure_patterns = [
                'undiscounted cash flows', 'percent of', 'description of', 'number of',
                'maximum borrowing capacity', 'not practicably determinable', 'recognised as of',
                'transferred', 'carrying amount', 'fair value', 'discount rate',
                'applied to', 'projections', 'indirect production costs', 'consequences of',
                'granted each', 'outstanding in', 'as a percentage', 'other provisions',
                'provisions for', 'provisions recognised', 'line of credit', 'shortterm borrowings'
            ]
            
            if any(pattern in combined_label for pattern in disclosure_patterns):
                continue  # Skip disclosure items
            
            # Compute display_order
            # For XBRL items: use order_index directly (EPS items handled separately)
            # For standard items: use large offset to ensure they come after XBRL items
            inferred_order = False
            if source == 'xbrl':
                max_order = xbrl_items_by_statement.get((filing_id_val, stmt_type), None)
                # Check if order_idx is NULL (XBRL extraction failed for this item)
                if order_idx is None:
                    # Try to infer from other years
                    inferred_display_order = infer_display_order_from_other_years(
                        conn, filing_id_val, concept_id, stmt_type or 'other'
                    )
                    if inferred_display_order is not None:
                        display_order = inferred_display_order
                        inferred_order = True
                    else:
                        # Fallback to standard templates
                        display_order = compute_display_order(999, normalized_label or '', stmt_type or 'other', max_order, use_xbrl_order=False)
                        logger.info(f"Using standard template for display_order: filing_id={filing_id}, concept_id={concept_id}, statement_type={stmt_type}, normalized_label={normalized_label}")
                else:
                    display_order = compute_display_order(order_idx, normalized_label or '', stmt_type or 'other', max_order, use_xbrl_order=True)
                    logger.debug(f"Using XBRL order_index={order_idx} for filing_id={filing_id}, concept_id={concept_id}, statement_type={stmt_type}")
            else:
                # Standard template items: use order_index + large offset
                display_order = 10000 + order_idx
            
            # Check if this is a header (parent concept with no facts)
            # Headers are identified by checking if the concept has children but no facts
            is_header = False
            if stmt_type:
                header_check = text("""
                    SELECT 
                        CASE 
                            WHEN EXISTS (
                                SELECT 1 FROM rel_presentation_hierarchy ph2
                                WHERE ph2.filing_id = :filing_id
                                AND ph2.parent_concept_id = :concept_id
                            )
                            AND NOT EXISTS (
                                SELECT 1 FROM fact_financial_metrics fm
                                WHERE fm.filing_id = :filing_id
                                AND fm.concept_id = :concept_id
                                AND fm.dimension_id IS NULL
                                AND fm.value_numeric IS NOT NULL
                            )
                            THEN TRUE
                            ELSE FALSE
                        END as is_header
                """)
                header_result = conn.execute(header_check, {
                    "filing_id": filing_id_val,
                    "concept_id": concept_id
                })
                is_header = header_result.fetchone()[0] if header_result else False
            
            # Determine balance sheet side (universal, not company-specific)
            side = None
            if stmt_type == 'balance_sheet':
                # Get concept_name for better side determination
                concept_name_query = text("""
                    SELECT concept_name FROM dim_concepts WHERE concept_id = :concept_id
                """)
                concept_name_result = conn.execute(concept_name_query, {"concept_id": concept_id})
                concept_name_row = concept_name_result.fetchone()
                concept_name = concept_name_row[0] if concept_name_row else None
                side = determine_balance_sheet_side(normalized_label or '', concept_name or '')
            
            items_to_insert.append({
                'filing_id': filing_id_val,
                'concept_id': concept_id,
                'statement_type': stmt_type or 'other',
                'display_order': display_order,
                'is_header': is_header,
                'is_main_item': True,
                'role_uri': role_uri,
                'source': source or 'xbrl',
                'side': side,  # For balance sheet: 'assets' or 'liabilities_equity'
                'inferred_order': inferred_order,  # TRUE if order was inferred from other years
                'header_source': None  # Not a header (or will be set later for headers)
            })
        
        # Second pass: Detect XBRL parent-child headers (PRIMARY SOURCE)
        # This should run BEFORE synthetic header creation to avoid duplicates
        filing_ids = set(item['filing_id'] for item in items_to_insert)
        statement_types = ['income_statement', 'balance_sheet', 'cash_flow', 'comprehensive_income', 'equity_statement']
        
        for filing_id_val in filing_ids:
            for stmt_type in statement_types:
                # Check if we have items for this statement type
                has_items = any(
                    item['filing_id'] == filing_id_val and item['statement_type'] == stmt_type
                    for item in items_to_insert
                )
                if has_items:
                    # Detect XBRL parent headers
                    xbrl_headers = detect_xbrl_parent_headers(conn, filing_id_val, stmt_type)
                    for header in xbrl_headers:
                        # Check if header already exists (avoid duplicates)
                        header_exists = any(
                            item['filing_id'] == filing_id_val
                            and item['concept_id'] == header['concept_id']
                            and item['statement_type'] == stmt_type
                            for item in items_to_insert
                        )
                        if not header_exists:
                            # Determine side for balance sheet
                            side = None
                            display_order = header['display_order']
                            
                            if stmt_type == 'balance_sheet':
                                side = determine_balance_sheet_side(header.get('normalized_label', '') or '', '')
                                # Special handling for balance sheet section headers
                                # "Assets" and "Equity and liabilities" should be at position 0.0 for their sides
                                # Other headers preserve their decimal values (e.g., 0.5) from SQL query
                                normalized_label_lower = (header.get('normalized_label', '') or '').lower()
                                if 'asset' in normalized_label_lower and side == 'assets':
                                    display_order = 0.0  # Assets header at position 0.0
                                elif ('equity' in normalized_label_lower or 'liabilit' in normalized_label_lower) and side == 'liabilities_equity':
                                    display_order = 0.0  # Equity and liabilities header at position 0.0
                                # For all other headers, preserve the decimal value from SQL query (already set above)
                            
                            items_to_insert.append({
                                'filing_id': filing_id_val,
                                'concept_id': header['concept_id'],
                                'statement_type': stmt_type,
                                'display_order': display_order,
                                'is_header': True,
                                'is_main_item': True,
                                'role_uri': None,  # Headers don't have role_uri
                                'source': 'xbrl',
                                'side': side,
                                'inferred_order': False,
                                'header_source': 'xbrl_parent'  # Track source
                            })
        
        # Third pass: Detect XBRL label role headers (SECONDARY SOURCE)
        # This runs after XBRL parent headers to fill in any gaps
        for filing_id_val in filing_ids:
            for stmt_type in statement_types:
                # Check if we have items for this statement type
                has_items = any(
                    item['filing_id'] == filing_id_val and item['statement_type'] == stmt_type
                    for item in items_to_insert
                )
                if has_items:
                    # Detect XBRL label role headers
                    label_role_headers = detect_xbrl_label_role_headers(conn, filing_id_val, stmt_type)
                    for header in label_role_headers:
                        # Check if header already exists (avoid duplicates)
                        header_exists = any(
                            item['filing_id'] == filing_id_val
                            and item['concept_id'] == header['concept_id']
                            and item['statement_type'] == stmt_type
                            for item in items_to_insert
                        )
                        if not header_exists:
                            # Determine side for balance sheet
                            side = None
                            display_order = header['display_order']
                            
                            if stmt_type == 'balance_sheet':
                                side = determine_balance_sheet_side(header.get('normalized_label', '') or '', '')
                                # Special handling for balance sheet section headers
                                # "Assets" and "Equity and liabilities" should be at position 0.0 for their sides
                                # Other headers preserve their decimal values (e.g., 0.5) from SQL query
                                normalized_label_lower = (header.get('normalized_label', '') or '').lower()
                                if 'asset' in normalized_label_lower and side == 'assets':
                                    display_order = 0.0  # Assets header at position 0.0
                                elif ('equity' in normalized_label_lower or 'liabilit' in normalized_label_lower) and side == 'liabilities_equity':
                                    display_order = 0.0  # Equity and liabilities header at position 0.0
                                # For all other headers, preserve the decimal value from SQL query (already set above)
                            
                            items_to_insert.append({
                                'filing_id': filing_id_val,
                                'concept_id': header['concept_id'],
                                'statement_type': stmt_type,
                                'display_order': display_order,
                                'is_header': True,
                                'is_main_item': True,
                                'role_uri': None,  # Headers don't have role_uri
                                'source': 'xbrl',
                                'side': side,
                                'inferred_order': False,
                                'header_source': 'xbrl_label_role'  # Track source
                            })
        
        # Fourth pass: Apply standard template headers (TERTIARY SOURCE)
        # Only used when XBRL doesn't provide headers
        from src.utils.header_templates import get_template_headers, should_apply_template_header
        
        for filing_id_val in filing_ids:
            # Get accounting standard for this filing
            accounting_standard_query = text("""
                SELECT c.accounting_standard
                FROM dim_filings f
                JOIN dim_companies c ON f.company_id = c.company_id
                WHERE f.filing_id = :filing_id
            """)
            standard_result = conn.execute(accounting_standard_query, {"filing_id": filing_id_val})
            standard_row = standard_result.fetchone()
            accounting_standard = standard_row[0] if standard_row and standard_row[0] else 'us_gaap'
            
            for stmt_type in statement_types:
                # Check if we have items for this statement type
                existing_items = [
                    item for item in items_to_insert
                    if item['filing_id'] == filing_id_val and item['statement_type'] == stmt_type
                ]
                
                if not existing_items:
                    continue
                
                # Get template headers for this statement type
                template_headers = get_template_headers(stmt_type, accounting_standard)
                
                # Build concept_id -> normalized_label mapping for existing items
                concept_ids = [item['concept_id'] for item in existing_items]
                if concept_ids:
                    concept_label_query = text("""
                        SELECT concept_id, normalized_label
                        FROM dim_concepts
                        WHERE concept_id = ANY(:concept_ids)
                    """)
                    label_result = conn.execute(concept_label_query, {"concept_ids": concept_ids})
                    concept_labels = {row[0]: row[1] for row in label_result.fetchall()}
                else:
                    concept_labels = {}
                
                # Apply template headers if needed
                for template_header in template_headers:
                    if should_apply_template_header(template_header, existing_items, concept_labels):
                        # Check if header concept exists, create if not
                        header_concept_query = text("""
                            SELECT concept_id FROM dim_concepts
                            WHERE normalized_label = :normalized_label
                            LIMIT 1
                        """)
                        header_result = conn.execute(header_concept_query, {
                            "normalized_label": template_header['normalized_label']
                        })
                        header_row = header_result.fetchone()
                        
                        if not header_row:
                            # Create header concept
                            create_header_query = text("""
                                INSERT INTO dim_concepts (
                                    concept_name, taxonomy, normalized_label, concept_type,
                                    balance_type, period_type, data_type, is_abstract, 
                                    statement_type, preferred_label
                                ) VALUES (
                                    :concept_name, 'synthetic', :normalized_label, 'string',
                                    NULL, 'duration', 'string', TRUE, :statement_type, :preferred_label
                                )
                                RETURNING concept_id
                            """)
                            concept_name = template_header['normalized_label'].replace('_', ' ').title().replace(' ', '')
                            create_result = conn.execute(create_header_query, {
                                "concept_name": concept_name,
                                "normalized_label": template_header['normalized_label'],
                                "statement_type": stmt_type,
                                "preferred_label": template_header['preferred_label']
                            })
                            header_concept_id = create_result.fetchone()[0]
                            conn.commit()
                        else:
                            header_concept_id = header_row[0]
                        
                        # Check if header already in items_to_insert
                        header_exists = any(
                            item['filing_id'] == filing_id_val
                            and item['concept_id'] == header_concept_id
                            and item['statement_type'] == stmt_type
                            for item in items_to_insert
                        )
                        
                        if not header_exists:
                            # Determine side for balance sheet
                            side = None
                            display_order = template_header['display_order']
                            
                            # Special handling: Position headers after items that should come before them
                            if stmt_type == 'cash_flow' and template_header['normalized_label'] == 'adjustment_of_non_cash_items_header':
                                # Check if Net profit exists in items_to_insert first, then database
                                # If so, header should be at 1.5 (after Net profit, before adjustment items)
                                net_profit_order = None
                                # Check items_to_insert first
                                for item in existing_items:
                                    concept_label = concept_labels.get(item.get('concept_id', ''), '')
                                    if concept_label in ('net_profit', 'net_income'):
                                        net_profit_order = item.get('display_order')
                                        break
                                
                                # If not found in items_to_insert, check database
                                if net_profit_order is None:
                                    net_profit_query = text("""
                                        SELECT MIN(display_order) 
                                        FROM rel_statement_items si
                                        JOIN dim_concepts co ON si.concept_id = co.concept_id
                                        WHERE si.filing_id = :filing_id
                                          AND si.statement_type = 'cash_flow'
                                          AND (co.normalized_label = 'net_profit' OR co.normalized_label = 'net_income')
                                    """)
                                    net_profit_result = conn.execute(net_profit_query, {"filing_id": filing_id_val})
                                    net_profit_order = net_profit_result.scalar()
                                
                                if net_profit_order is not None:
                                    display_order = net_profit_order + 0.5  # After Net profit
                                else:
                                    display_order = 1.5  # Default: after position 1.0
                            
                            elif stmt_type == 'comprehensive_income' and template_header['normalized_label'] == 'other_comprehensive_income_header':
                                # Check if Net profit exists in items_to_insert first, then database
                                # If so, header should be at 2.0 (after Net profit and space)
                                net_profit_order = None
                                # Check items_to_insert first
                                for item in existing_items:
                                    concept_label = concept_labels.get(item.get('concept_id', ''), '')
                                    if concept_label in ('net_profit', 'net_income'):
                                        net_profit_order = item.get('display_order')
                                        break
                                
                                # If not found in items_to_insert, check database
                                if net_profit_order is None:
                                    net_profit_query = text("""
                                        SELECT MIN(display_order) 
                                        FROM rel_statement_items si
                                        JOIN dim_concepts co ON si.concept_id = co.concept_id
                                        WHERE si.filing_id = :filing_id
                                          AND si.statement_type = 'comprehensive_income'
                                          AND (co.normalized_label = 'net_profit' OR co.normalized_label = 'net_income')
                                    """)
                                    net_profit_result = conn.execute(net_profit_query, {"filing_id": filing_id_val})
                                    net_profit_order = net_profit_result.scalar()
                                
                                if net_profit_order is not None:
                                    display_order = net_profit_order + 1.0  # After Net profit (1.0) and space (1.5) = 2.0
                                else:
                                    display_order = 2.0  # Default: after position 1.0
                            
                            elif stmt_type == 'balance_sheet':
                                # Get side from template if specified, otherwise determine
                                side = template_header.get('side')
                                if not side:
                                    side = determine_balance_sheet_side(template_header.get('normalized_label', '') or '', '')
                                # Balance sheet section headers should be at position 0.0
                                # Other headers preserve their decimal values from template
                                if template_header.get('side'):
                                    display_order = 0.0
                                # Otherwise, use the display_order from template (may be decimal like 0.5)
                            
                            items_to_insert.append({
                                'filing_id': filing_id_val,
                                'concept_id': header_concept_id,
                                'statement_type': stmt_type,
                                'display_order': display_order,
                                'is_header': True,
                                'is_main_item': True,
                                'role_uri': None,
                                'source': 'template',
                                'side': side,
                                'inferred_order': False,
                                'header_source': 'template'  # Track source
                            })
                            logger.info(f"Applied template header '{template_header['preferred_label']}' for filing_id={filing_id_val}, statement_type={stmt_type}")
        
        # Fifth pass: Add "Net profit" to comprehensive income (references income statement)
        # UNIVERSAL: Comprehensive income statements ALWAYS start with net profit from income statement
        # This is standard IFRS/US-GAAP practice - all companies do this
        filing_ids = set(item['filing_id'] for item in items_to_insert)
        for filing_id_val in filing_ids:
            # Check if we have comprehensive_income items
            has_comprehensive = any(
                item['filing_id'] == filing_id_val and item['statement_type'] == 'comprehensive_income'
                for item in items_to_insert
            )
            if has_comprehensive:
                # Find net_income concept_id - try multiple normalized labels (UNIVERSAL - works for all companies)
                # Try net_income_including_noncontrolling_interest first, then net_profit, then net_income
                concept_check = text("""
                    SELECT concept_id FROM dim_concepts 
                    WHERE normalized_label IN (
                        'net_income_including_noncontrolling_interest',
                        'net_profit',
                        'net_income'
                    )
                    AND concept_id IN (
                        SELECT DISTINCT concept_id FROM fact_financial_metrics fm
                        JOIN dim_filings f ON fm.filing_id = f.filing_id
                        WHERE f.filing_id = :filing_id
                    )
                    LIMIT 1
                """)
                concept_result = conn.execute(concept_check, {'filing_id': filing_id_val})
                concept_row = concept_result.fetchone()
                if concept_row:
                    net_income_concept_id = concept_row[0]
                    # Check if already in comprehensive_income
                    already_added = any(
                        item['filing_id'] == filing_id_val and 
                        item['statement_type'] == 'comprehensive_income' and
                        item['concept_id'] == net_income_concept_id
                        for item in items_to_insert
                    )
                    if not already_added:
                        # Add net_income to comprehensive_income with display_order=0 (first)
                        # UNIVERSAL: Comprehensive income statements ALWAYS start with net profit from income statement
                        items_to_insert.append({
                            'filing_id': filing_id_val,
                            'concept_id': net_income_concept_id,
                            'statement_type': 'comprehensive_income',
                            'display_order': 0,  # First item in comprehensive income
                            'is_header': False,
                            'is_main_item': True,
                            'role_uri': None,  # Synthetic - references income statement
                            'source': 'synthetic',
                            'side': None,
                            'inferred_order': False  # Not inferred - synthetic item
                        })
        
        # Third pass: Add balance sheet concepts that have facts but aren't in presentation hierarchy
        # UNIVERSAL FIX: If a concept has balance sheet facts in fact_financial_metrics, it should be included
        # This ensures ALL data from the XBRL filing is captured, even if presentation hierarchy is incomplete
        # CRITICAL: Check BOTH consolidated AND dimension facts (many balance sheet concepts only have dimension facts)
        filing_ids_processed = set(item['filing_id'] for item in items_to_insert)
        for filing_id_val in filing_ids_processed:
            # Find balance sheet concepts with facts but not in rel_statement_items
            # CRITICAL: Check for concepts with EITHER consolidated OR dimension facts for ANY instant period
            # The 2024 report contains ALL comparative data (2022, 2023, 2024) - we need ALL of it
            missing_bs_query = text("""
                SELECT DISTINCT
                    co.concept_id,
                    co.normalized_label,
                    co.concept_name
                FROM dim_concepts co
                WHERE co.concept_id IN (
                    -- Concepts with consolidated facts for ANY instant period in this filing
                    SELECT DISTINCT fm.concept_id
                    FROM fact_financial_metrics fm
                    JOIN dim_time_periods p ON fm.period_id = p.period_id
                    WHERE fm.filing_id = :filing_id
                      AND p.period_type = 'instant'
                      AND fm.dimension_id IS NULL
                      AND fm.value_numeric IS NOT NULL
                    
                    UNION
                    
                    -- Concepts with dimension facts for ANY instant period in this filing
                    SELECT DISTINCT fm.concept_id
                    FROM fact_financial_metrics fm
                    JOIN dim_time_periods p ON fm.period_id = p.period_id
                    WHERE fm.filing_id = :filing_id
                      AND p.period_type = 'instant'
                      AND fm.dimension_id IS NOT NULL
                      AND fm.value_numeric IS NOT NULL
                )
                -- Check if concept looks like a balance sheet concept
                AND (
                    co.normalized_label LIKE '%asset%' 
                    OR co.normalized_label LIKE '%liability%'
                    OR co.normalized_label LIKE '%equity%'
                    OR co.normalized_label LIKE '%receivable%'
                    OR co.normalized_label LIKE '%payable%'
                    OR co.normalized_label LIKE '%inventory%'
                    OR co.normalized_label LIKE '%cash%'
                    OR co.normalized_label LIKE '%capital%'
                    OR co.normalized_label LIKE '%borrowing%'
                    OR co.normalized_label LIKE '%provision%'
                    OR co.concept_name LIKE '%Asset%'
                    OR co.concept_name LIKE '%Liability%'
                    OR co.concept_name LIKE '%Equity%'
                    OR co.concept_name LIKE '%Receivable%'
                    OR co.concept_name LIKE '%Payable%'
                    OR co.concept_name LIKE '%Inventory%'
                    OR co.concept_name LIKE '%Cash%'
                    OR co.concept_name LIKE '%Capital%'
                    OR co.concept_name LIKE '%Borrowing%'
                    OR co.concept_name LIKE '%Provision%'
                )
                -- Exclude if already in rel_statement_items
                AND NOT EXISTS (
                    SELECT 1 FROM rel_statement_items si
                    WHERE si.filing_id = :filing_id
                      AND si.concept_id = co.concept_id
                      AND si.statement_type = 'balance_sheet'
                )
                -- Exclude detail/disclosure items
                AND co.normalized_label NOT LIKE '%_note%'
                AND co.normalized_label NOT LIKE '%_disclosure%'
                AND co.normalized_label NOT LIKE '%_reconciliation%'
                AND co.normalized_label NOT LIKE '%_schedule%'
            """)
            missing_result = conn.execute(missing_bs_query, {"filing_id": filing_id_val})
            missing_rows = missing_result.fetchall()
            
            if missing_rows:
                # Get max display_order for balance sheet items to append new items
                max_bs_order = max(
                    (item['display_order'] for item in items_to_insert 
                     if item['filing_id'] == filing_id_val and item['statement_type'] == 'balance_sheet'),
                    default=0
                )
                
                for concept_id, normalized_label, concept_name in missing_rows:
                    # Determine side
                    side = determine_balance_sheet_side(normalized_label or '', concept_name or '')
                    
                    # Only add if we can determine it's a balance sheet item
                    if side:
                        items_to_insert.append({
                            'filing_id': filing_id_val,
                            'concept_id': concept_id,
                            'statement_type': 'balance_sheet',
                            'display_order': max_bs_order + 1000,  # Append at end
                            'is_header': False,
                            'is_main_item': True,
                            'role_uri': None,  # Not in presentation hierarchy
                            'source': 'xbrl',
                            'side': side,
                            'inferred_order': False  # Not inferred - from XBRL
                        })
        
        # Sixth pass: Removed hardcoded header creation - now handled by:
        # - XBRL parent-child relationships (Phase 3)
        # - XBRL label roles (Phase 4)
        # - Standard templates (Phase 5)
        # Headers are now detected automatically from XBRL data
        
        # Note: "Earnings per share" and "Other comprehensive income" headers are now handled by templates
        # "Cash flow hedges" and other headers are detected from XBRL parent-child relationships
        
        # Seventh pass: Create synthetic headers as LAST RESORT (only if not detected from XBRL/templates)
        # Check if headers already exist before creating synthetic ones
        # Most headers should now be detected from XBRL parent-child relationships or label roles
        
        # Note: The following sections create synthetic headers only if they don't already exist
        # This ensures we don't duplicate headers that were detected from XBRL
        
        # "Cash flow hedges" header (if not detected from XBRL)
        for filing_id_val in filing_ids:
            # Check if we have comprehensive_income items with cash flow hedges
            # Query database to get normalized_label for concept_ids
            cash_flow_hedge_concept_ids = []
            for item in items_to_insert:
                if (item['filing_id'] == filing_id_val and 
                    item['statement_type'] == 'comprehensive_income'):
                    # Query normalized_label from database
                    label_query = text("""
                        SELECT normalized_label FROM dim_concepts
                        WHERE concept_id = :concept_id
                    """)
                    label_result = conn.execute(label_query, {'concept_id': item['concept_id']})
                    label_row = label_result.fetchone()
                    if label_row:
                        normalized_label = (label_row[0] or '').lower()
                        if any(term in normalized_label for term in ['cash_flow_hedge', 'reclassification_adjustments_on_cash_flow_hedges']):
                            cash_flow_hedge_concept_ids.append(item['concept_id'])
            
            cash_flow_hedge_items = [
                item for item in items_to_insert
                if (item['filing_id'] == filing_id_val and 
                    item['statement_type'] == 'comprehensive_income' and
                    item['concept_id'] in cash_flow_hedge_concept_ids)
            ]
            
            if len(cash_flow_hedge_items) > 0:
                # Check if header already exists (from XBRL parent-child or label role)
                header_exists = any(
                    item['filing_id'] == filing_id_val
                    and item['statement_type'] == 'comprehensive_income'
                    and item.get('is_header', False)
                    and ('cash_flow_hedge' in (item.get('normalized_label', '') or '').lower() or
                         'cash flow hedge' in (item.get('preferred_label', '') or '').lower())
                    for item in items_to_insert
                )
                
                if not header_exists:
                    # Only create if not detected from XBRL - log warning
                    logger.warning(f"Creating synthetic 'Cash flow hedges' header for filing_id={filing_id_val} - not detected from XBRL")
                    
                # Find or create "Cash flow hedges" header concept
                header_concept_query = text("""
                    SELECT concept_id FROM dim_concepts
                    WHERE normalized_label = 'cash_flow_hedges_header'
                    LIMIT 1
                """)
                header_concept_result = conn.execute(header_concept_query)
                header_concept_row = header_concept_result.fetchone()
                
                if not header_concept_row:
                    create_header_query = text("""
                        INSERT INTO dim_concepts (
                            concept_name, taxonomy, normalized_label, preferred_label,
                            concept_type, is_abstract, statement_type
                        ) VALUES (
                                'CashFlowHedgesHeader', 'synthetic', 'cash_flow_hedges_header', 'Cash flow hedges',
                            'text', TRUE, 'comprehensive_income'
                        )
                        RETURNING concept_id
                    """)
                    header_concept_result = conn.execute(create_header_query)
                    header_concept_row = header_concept_result.fetchone()
                    conn.commit()
                
                if header_concept_row:
                    header_concept_id = header_concept_row[0]
                    # Position header after "Exchange rate adjustments" (typically at order 7.0)
                    # So header should be at 7.5, before hedge items at 8.0+
                    exchange_adj_order = None
                    
                    # Check items_to_insert first
                    for item in items_to_insert:
                        if (item['filing_id'] == filing_id_val and 
                            item['statement_type'] == 'comprehensive_income'):
                            # Query normalized_label from database
                            label_query = text("""
                                SELECT normalized_label FROM dim_concepts
                                WHERE concept_id = :concept_id
                            """)
                            label_result = conn.execute(label_query, {'concept_id': item['concept_id']})
                            label_row = label_result.fetchone()
                            if label_row:
                                normalized_label = (label_row[0] or '').lower()
                                if 'exchange' in normalized_label and 'translation' in normalized_label:
                                    exchange_adj_order = item.get('display_order')
                                    break
                    
                    # If not found in items_to_insert, check database
                    if exchange_adj_order is None:
                        exchange_adj_query = text("""
                            SELECT MIN(display_order) 
                            FROM rel_statement_items si
                            JOIN dim_concepts co ON si.concept_id = co.concept_id
                            WHERE si.filing_id = :filing_id
                              AND si.statement_type = 'comprehensive_income'
                              AND (co.normalized_label LIKE '%exchange%' AND co.normalized_label LIKE '%translation%')
                        """)
                        exchange_adj_result = conn.execute(exchange_adj_query, {"filing_id": filing_id_val})
                        exchange_adj_order = exchange_adj_result.scalar()
                    
                    if exchange_adj_order is not None:
                        cash_flow_hedges_order = exchange_adj_order + 0.5  # After exchange adjustments
                    else:
                        # Fallback: Find minimum order for cash flow hedge items
                        min_hedge_order = min(
                            (item.get('display_order', 999) for item in cash_flow_hedge_items),
                            default=7
                        )
                        cash_flow_hedges_order = min_hedge_order - 0.5  # Before first hedge item
                    
                    items_to_insert.append({
                        'filing_id': filing_id_val,
                        'concept_id': header_concept_id,
                        'statement_type': 'comprehensive_income',
                        'display_order': cash_flow_hedges_order,  # After exchange adjustments (7.0) = 7.5
                        'is_header': True,
                        'is_main_item': True,
                        'role_uri': None,
                        'source': 'synthetic',
                        'side': None,
                        'inferred_order': False,
                        'header_source': 'synthetic'  # Track as synthetic
                    })
        
        # "Assets" and "Equity and liabilities" headers for balance sheet (if not detected from XBRL)
        # These should typically be detected from XBRL parent-child relationships
        for filing_id_val in filing_ids:
            has_balance_sheet_items = any(
                item['filing_id'] == filing_id_val and 
                    item['statement_type'] == 'balance_sheet'
                for item in items_to_insert
            )
            
            if has_balance_sheet_items:
                # Check if "Assets" header exists
                assets_header_exists = any(
                    item['filing_id'] == filing_id_val
                    and item['statement_type'] == 'balance_sheet'
                    and item.get('is_header', False)
                    and item.get('side') == 'assets'
                    and ('asset' in (item.get('normalized_label', '') or '').lower() or
                         'asset' in (item.get('preferred_label', '') or '').lower())
                for item in items_to_insert
            )
            
                # Check if "Equity and liabilities" header exists
                equity_liab_header_exists = any(
                    item['filing_id'] == filing_id_val
                    and item['statement_type'] == 'balance_sheet'
                    and item.get('is_header', False)
                    and item.get('side') == 'liabilities_equity'
                    and ('equity' in (item.get('normalized_label', '') or '').lower() or
                         'liabilit' in (item.get('normalized_label', '') or '').lower())
                    for item in items_to_insert
                )
                
                # Only create if not detected from XBRL - these should be rare
                if not assets_header_exists or not equity_liab_header_exists:
                    logger.warning(f"Balance sheet headers not fully detected from XBRL for filing_id={filing_id_val} - may need synthetic headers")
                    # Note: Synthetic header creation for balance sheet removed - should be detected from XBRL
        
        # "Adjustment of non-cash items" header for cash flow (if not detected from XBRL)
        # This should typically be detected from XBRL parent-child relationships
        for filing_id_val in filing_ids:
            # Check if we have cash_flow items with adjustments (excluding Net profit)
            # Query database to get normalized_label for concept_ids in items_to_insert
            cash_flow_concept_ids = [
                item['concept_id'] for item in items_to_insert
                if item['filing_id'] == filing_id_val and 
                   item['statement_type'] == 'cash_flow' and
                   item.get('display_order', 999) > 0  # Exclude Net profit (order 0)
            ]
            
            if cash_flow_concept_ids:
                # Query normalized_labels from database
                label_query = text("""
                    SELECT normalized_label FROM dim_concepts
                    WHERE concept_id = ANY(:concept_ids)
                """)
                label_result = conn.execute(label_query, {'concept_ids': cash_flow_concept_ids})
                normalized_labels = [row[0] or '' for row in label_result]
                
                # Check if any are adjustment items
                has_adjustment_items = any(
                    ('adjustment' in label.lower() or
                     'depreciation' in label.lower() or
                     'working_capital' in label.lower())
                    for label in normalized_labels
                )
            else:
                has_adjustment_items = False
            
            if has_adjustment_items:
                # Check if header already exists (from XBRL parent-child or label role)
                header_exists = any(
                    item['filing_id'] == filing_id_val
                    and item['statement_type'] == 'cash_flow'
                    and item.get('is_header', False)
                    and ('adjustment' in (item.get('normalized_label', '') or '').lower() or
                         'non-cash' in (item.get('preferred_label', '') or '').lower())
                    for item in items_to_insert
                )
                
                if not header_exists:
                    # Only create if not detected from XBRL - log warning
                    logger.warning(f"Creating synthetic 'Adjustment of non-cash items' header for filing_id={filing_id_val} - not detected from XBRL")
                    # Note: Synthetic header creation removed - should be detected from XBRL parent-child relationships
        
        # Eighth pass: Create synthetic space headers for equity statements (industry-standard formatting)
        # IFRS/EU equity statements require visual spacing for readability
        # Space 1: After "Total comprehensive income" (position 3)
        # Space 2: After "Transfer of cash flow hedge reserve" (position 7)
        for filing_id_val in filing_ids:
            # Check if we have equity_statement items
            has_equity_items = any(
                item['filing_id'] == filing_id_val and 
                item['statement_type'] == 'equity_statement'
                for item in items_to_insert
            )
            
            if has_equity_items:
                # Space 1: After "Total comprehensive income" (display_order 3)
                # Create space header concept if it doesn't exist
                space1_concept_query = text("""
                    SELECT concept_id FROM dim_concepts
                    WHERE concept_name = 'EquityStatementSpace1' AND taxonomy = 'synthetic'
                    LIMIT 1
                """)
                space1_result = conn.execute(space1_concept_query)
                space1_row = space1_result.fetchone()
                
                if not space1_row:
                    create_space1_query = text("""
                        INSERT INTO dim_concepts (
                            concept_name, taxonomy, normalized_label, preferred_label,
                            concept_type, is_abstract, statement_type
                        ) VALUES (
                            'EquityStatementSpace1', 'synthetic', 'equity_statement_space_1', '',
                            'text', TRUE, 'equity_statement'
                        )
                        ON CONFLICT (concept_name, taxonomy) DO UPDATE SET
                            normalized_label = EXCLUDED.normalized_label,
                            preferred_label = EXCLUDED.preferred_label,
                            statement_type = EXCLUDED.statement_type
                        RETURNING concept_id
                    """)
                    space1_result = conn.execute(create_space1_query)
                    space1_concept_id = space1_result.fetchone()[0]
                    conn.commit()
                else:
                    space1_concept_id = space1_row[0]
                
                # Check if space 1 already added
                space1_already_added = any(
                    item['concept_id'] == space1_concept_id and 
                    item['filing_id'] == filing_id_val and 
                    item['statement_type'] == 'equity_statement'
                    for item in items_to_insert
                )
                
                if not space1_already_added:
                    # Space 1: After "Net profit" (display_order 1), before "Other comprehensive income" (display_order 4)
                    # Industry standard: Visual spacing after net profit section
                    # Expected position: 3 (after Net profit at 1, before Other comprehensive income at 4)
                    items_to_insert.append({
                        'filing_id': filing_id_val,
                        'concept_id': space1_concept_id,
                        'statement_type': 'equity_statement',
                        'display_order': 3,  # Between Net profit (1) and Other comprehensive income (4)
                        'is_header': True,
                        'is_main_item': True,
                        'role_uri': None,
                        'source': 'synthetic',
                        'side': None,
                        'inferred_order': False  # Not inferred - synthetic space
                    })
                
                # Space 2: After "Transfer of cash flow hedge reserve" (display_order 6), before "Transactions with owners" (display_order 8)
                space2_concept_query = text("""
                    SELECT concept_id FROM dim_concepts
                    WHERE concept_name = 'EquityStatementSpace2' AND taxonomy = 'synthetic'
                    LIMIT 1
                """)
                space2_result = conn.execute(space2_concept_query)
                space2_row = space2_result.fetchone()
                
                if not space2_row:
                    create_space2_query = text("""
                        INSERT INTO dim_concepts (
                            concept_name, taxonomy, normalized_label, preferred_label,
                            concept_type, is_abstract, statement_type
                        ) VALUES (
                            'EquityStatementSpace2', 'synthetic', 'equity_statement_space_2', '',
                            'text', TRUE, 'equity_statement'
                        )
                        ON CONFLICT (concept_name, taxonomy) DO UPDATE SET
                            normalized_label = EXCLUDED.normalized_label,
                            preferred_label = EXCLUDED.preferred_label,
                            statement_type = EXCLUDED.statement_type
                        RETURNING concept_id
                    """)
                    space2_result = conn.execute(create_space2_query)
                    space2_concept_id = space2_result.fetchone()[0]
                    conn.commit()
                else:
                    space2_concept_id = space2_row[0]
                
                # Check if space 2 already added
                space2_already_added = any(
                    item['concept_id'] == space2_concept_id and 
                    item['filing_id'] == filing_id_val and 
                    item['statement_type'] == 'equity_statement'
                    for item in items_to_insert
                )
                
                if not space2_already_added:
                    # Space 2: After "Transfer of cash flow hedge reserve" (display_order 6), before "Transactions with owners" (display_order 8)
                    # Industry standard: Visual spacing before transactions section
                    # Expected position: 7 (after Transfer at 6, before Transactions with owners at 8)
                    items_to_insert.append({
                        'filing_id': filing_id_val,
                        'concept_id': space2_concept_id,
                        'statement_type': 'equity_statement',
                        'display_order': 7,  # Between Transfer (6) and Transactions with owners (8)
                        'is_header': True,
                        'is_main_item': True,
                        'role_uri': None,
                        'source': 'synthetic',
                        'side': None,
                        'inferred_order': False  # Not inferred - synthetic space
                    })
        
        # Ninth pass: Create synthetic "Cash and cash equivalents at the beginning of the year" for cash flow statements
        # This is calculated from the previous year's end-of-year cash balance (universal accounting principle)
        for filing_id_val in filing_ids:
            # Check if we have cash_flow items (need to add beginning cash)
            has_cash_flow_items = any(
                item['filing_id'] == filing_id_val and 
                item['statement_type'] == 'cash_flow'
                for item in items_to_insert
            )
            
            if has_cash_flow_items:
                # Find or create "Cash and cash equivalents at the beginning of the year" concept
                header_concept_query = text("""
                    SELECT concept_id FROM dim_concepts
                    WHERE normalized_label = 'cash_and_cash_equivalents_at_the_beginning_of_the_year'
                    LIMIT 1
                """)
                header_concept_result = conn.execute(header_concept_query)
                header_concept_row = header_concept_result.fetchone()
                
                if not header_concept_row:
                    # Create the concept if it doesn't exist
                    create_concept_query = text("""
                        INSERT INTO dim_concepts (
                            concept_name, taxonomy, normalized_label, concept_type,
                            balance_type, period_type, data_type, is_abstract, statement_type, preferred_label
                        ) VALUES (
                            'CashAndCashEquivalentsAtTheBeginningOfTheYear', 'synthetic', 'cash_and_cash_equivalents_at_the_beginning_of_the_year', 'monetary',
                            NULL, 'instant', 'xbrli:monetaryItemType', FALSE, 'cash_flow', 'Cash and cash equivalents at the beginning of the year'
                        )
                        RETURNING concept_id
                    """)
                    create_result = conn.execute(create_concept_query)
                    beginning_cash_concept_id = create_result.fetchone()[0]
                    conn.commit()
                else:
                    beginning_cash_concept_id = header_concept_row[0]
                
                # Check if already in items_to_insert (avoid duplicate)
                already_added = any(
                    item['concept_id'] == beginning_cash_concept_id and 
                    item['filing_id'] == filing_id_val and 
                    item['statement_type'] == 'cash_flow'
                    for item in items_to_insert
                )
                if not already_added:
                    items_to_insert.append({
                        'filing_id': filing_id_val,
                        'concept_id': beginning_cash_concept_id,
                        'statement_type': 'cash_flow',
                        'display_order': 24,  # Before exchange gains (25) and end-of-year cash (26)
                        'is_header': False,
                        'is_main_item': True,
                        'role_uri': None,
                        'source': 'calculated',  # Mark as calculated, not from XBRL
                        'side': None,
                        'inferred_order': False  # Not inferred - calculated item
                    })
        
        # "Transactions with owners" header is now handled by standard templates (Phase 5)
        # No need for hardcoded creation - template system handles it
        
        # Balance at beginning/end of year for equity statements (not headers - these are actual items)
        # UNIVERSAL FIX: Always create these concepts if they don't exist, then add to rel_statement_items for any filing with equity statements
        # Beginning balance = previous year's end balance (from balance sheet)
        # End balance = current year's end balance (from balance sheet)
        
        # First, ensure the concepts exist (create if needed) - UNIVERSAL: works for all companies
        beginning_concept_query = text("""
            SELECT concept_id FROM dim_concepts
            WHERE concept_name = 'BalanceAtBeginningOfYearEquity' AND taxonomy = 'synthetic'
            LIMIT 1
        """)
        beginning_result = conn.execute(beginning_concept_query)
        beginning_row = beginning_result.fetchone()
        
        if not beginning_row:
            create_beginning_query = text("""
                INSERT INTO dim_concepts (
                    concept_name, taxonomy, normalized_label, concept_type,
                    balance_type, period_type, data_type, is_abstract, statement_type, preferred_label
                ) VALUES (
                    'BalanceAtBeginningOfYearEquity', 'synthetic', 'balance_at_the_beginning_of_the_year_equity', 'monetary',
                    NULL, 'instant', 'xbrli:monetaryItemType', FALSE, 'equity_statement', 'Balance at the beginning of the year'
                )
                RETURNING concept_id
            """)
            create_beginning_result = conn.execute(create_beginning_query)
            beginning_concept_id = create_beginning_result.fetchone()[0]
            conn.commit()
        else:
            beginning_concept_id = beginning_row[0]
        
        # End balance concept - ensure it exists
        end_concept_query = text("""
            SELECT concept_id FROM dim_concepts
            WHERE concept_name = 'BalanceAtEndOfYearEquity' AND taxonomy = 'synthetic'
            LIMIT 1
        """)
        end_result = conn.execute(end_concept_query)
        end_row = end_result.fetchone()
        
        if not end_row:
            create_end_query = text("""
                INSERT INTO dim_concepts (
                    concept_name, taxonomy, normalized_label, concept_type,
                    balance_type, period_type, data_type, is_abstract, statement_type, preferred_label
                ) VALUES (
                    'BalanceAtEndOfYearEquity', 'synthetic', 'balance_at_the_end_of_the_year_equity', 'monetary',
                    NULL, 'instant', 'xbrli:monetaryItemType', FALSE, 'equity_statement', 'Balance at the end of the year'
                )
                RETURNING concept_id
            """)
            create_end_result = conn.execute(create_end_query)
            end_concept_id = create_end_result.fetchone()[0]
            conn.commit()
        else:
            end_concept_id = end_row[0]
        
        # Now add to rel_statement_items for all filings with equity statements
        # UNIVERSAL FIX: Check database directly for filings with equity statements, not just items_to_insert
        # This ensures we add beginning/ending balances even if equity_statement items aren't in items_to_insert yet
        for filing_id_val in filing_ids:
            # Check if we have equity_statement items in items_to_insert OR in database
            has_equity_statement_items = any(
                item['filing_id'] == filing_id_val and 
                item['statement_type'] == 'equity_statement'
                for item in items_to_insert
            )
            
            # Also check database directly
            if not has_equity_statement_items:
                equity_check_query = text("""
                    SELECT COUNT(*) FROM rel_statement_items si
                    JOIN dim_filings f ON si.filing_id = f.filing_id
                    WHERE si.filing_id = :filing_id AND si.statement_type = 'equity_statement'
                """)
                equity_check_result = conn.execute(equity_check_query, {'filing_id': filing_id_val})
                equity_count = equity_check_result.scalar()
                has_equity_statement_items = equity_count > 0
            
            if has_equity_statement_items:
                # Add beginning balance (order 0) - concepts already created above
                if not any(item['concept_id'] == beginning_concept_id and item['filing_id'] == filing_id_val and item['statement_type'] == 'equity_statement' for item in items_to_insert):
                    items_to_insert.append({
                        'filing_id': filing_id_val,
                        'concept_id': beginning_concept_id,
                        'statement_type': 'equity_statement',
                        'display_order': 0,  # First item
                        'is_header': False,
                        'is_main_item': True,
                        'role_uri': None,
                        'source': 'calculated',
                        'side': None,  # Not applicable for equity statement
                        'inferred_order': False  # Not inferred - calculated item
                    })
                
                # Add end balance (order 14) - concepts already created above
                # UNIVERSAL FIX: Use compute_equity_order to ensure correct display_order
                if not any(item['concept_id'] == end_concept_id and item['filing_id'] == filing_id_val and item['statement_type'] == 'equity_statement' for item in items_to_insert):
                    items_to_insert.append({
                        'filing_id': filing_id_val,
                        'concept_id': end_concept_id,
                        'statement_type': 'equity_statement',
                        'display_order': compute_equity_order('balance_at_end_of_year_equity'),  # Use compute_equity_order for correct position (14)
                        'is_header': False,
                        'is_main_item': True,
                        'role_uri': None,
                        'source': 'calculated',
                        'side': None,  # Not applicable for equity statement
                        'inferred_order': False  # Not inferred - calculated item
                    })
        
        # Deduplicate items_to_insert by (filing_id, concept_id, statement_type)
        seen_keys = set()
        deduplicated_items = []
        for item in items_to_insert:
            key = (item['filing_id'], item['concept_id'], item['statement_type'])
            if key not in seen_keys:
                seen_keys.add(key)
                deduplicated_items.append(item)
        
        items_to_insert = deduplicated_items
        
        # Eleventh pass: Create synthetic "Total equity and liabilities" for balance sheet
        # UNIVERSAL FIX: Add this AFTER all other items so we can calculate correct max display_order
        # This is a calculated total (total_equity + total_liabilities)
        # First, ensure the concept exists
        total_eq_liab_concept_query = text("""
            SELECT concept_id FROM dim_concepts
            WHERE concept_name = 'TotalEquityAndLiabilities' AND taxonomy = 'synthetic'
            LIMIT 1
        """)
        total_eq_liab_result = conn.execute(total_eq_liab_concept_query)
        total_eq_liab_row = total_eq_liab_result.fetchone()
        
        if not total_eq_liab_row:
            create_total_eq_liab_query = text("""
                INSERT INTO dim_concepts (
                    concept_name, taxonomy, normalized_label, preferred_label,
                    concept_type, is_abstract, statement_type
                ) VALUES (
                    'TotalEquityAndLiabilities', 'synthetic', 'total_equity_and_liabilities', 'Total equity and liabilities',
                    'monetary', FALSE, 'balance_sheet'
                )
                RETURNING concept_id
            """)
            create_result = conn.execute(create_total_eq_liab_query)
            total_eq_liab_concept_id = create_result.fetchone()[0]
            conn.commit()
        else:
            total_eq_liab_concept_id = total_eq_liab_row[0]
        
        # Add to rel_statement_items for all filings with balance sheet items
        # CRITICAL: Calculate max_liab_equity_order from FINAL items_to_insert (after all passes)
        for filing_id_val in filing_ids:
            has_balance_sheet_items = any(
                item['filing_id'] == filing_id_val and 
                item['statement_type'] == 'balance_sheet'
                for item in items_to_insert
            )
            
            if has_balance_sheet_items:
                # Check if already added
                already_added = any(
                    item['concept_id'] == total_eq_liab_concept_id and 
                    item['filing_id'] == filing_id_val and 
                    item['statement_type'] == 'balance_sheet'
                    for item in items_to_insert
                )
                
                if not already_added:
                    # UNIVERSAL FIX: Calculate max from FINAL items_to_insert (after all passes)
                    # CRITICAL: Exclude disclosure items (display_order >= 1000) from max calculation
                    max_liab_equity_order = 0
                    for item in items_to_insert:
                        if (item['filing_id'] == filing_id_val and 
                            item['statement_type'] == 'balance_sheet' and
                            item.get('side') == 'liabilities_equity' and
                            item.get('display_order', 0) < 1000 and  # Exclude disclosure items
                            item.get('display_order', 0) > max_liab_equity_order):
                            max_liab_equity_order = item.get('display_order', 0)
                    
                    # Total equity and liabilities goes at the end of liabilities_equity side
                    items_to_insert.append({
                        'filing_id': filing_id_val,
                        'concept_id': total_eq_liab_concept_id,
                        'statement_type': 'balance_sheet',
                        'display_order': max_liab_equity_order + 1,  # After all liabilities_equity items
                        'is_header': False,
                        'is_main_item': True,
                        'role_uri': None,
                        'source': 'calculated',
                        'side': 'liabilities_equity',
                        'inferred_order': False  # Not inferred - calculated item
                    })
        
        # UNIVERSAL FIX: Map "Cash at bank" to "Cash and cash equivalents at the end of the year" for cash flow
        # AND deduplicate if both exist
        # This works for all companies (IFRS and US-GAAP)
        for filing_id_val in filing_ids:
            # Get all cash flow items for this filing
            cash_flow_items = [
                item for item in items_to_insert
                if item['filing_id'] == filing_id_val and item['statement_type'] == 'cash_flow'
            ]
            
            if not cash_flow_items:
                continue
            
            # Query normalized_labels for these concepts
            concept_ids = [item['concept_id'] for item in cash_flow_items]
            label_query = text("""
                SELECT concept_id, normalized_label FROM dim_concepts
                WHERE concept_id = ANY(:concept_ids)
            """)
            label_result = conn.execute(label_query, {'concept_ids': concept_ids})
            concept_labels = {row[0]: row[1] for row in label_result}
            
            # UNIVERSAL FIX: Map "cash_at_bank" or "cash_and_equivalents" to "cash_and_cash_equivalents_at_the_end_of_the_year"
            # First, check if we have "cash_and_cash_equivalents_at_the_end_of_the_year" concept
            end_cash_concept_query = text("""
                SELECT concept_id FROM dim_concepts
                WHERE normalized_label = 'cash_and_cash_equivalents_at_the_end_of_the_year'
                LIMIT 1
            """)
            end_cash_result = conn.execute(end_cash_concept_query)
            end_cash_row = end_cash_result.fetchone()
            end_cash_concept_id = end_cash_row[0] if end_cash_row else None
            
            # Check if we have "cash_at_bank" or "cash_and_equivalents" in cash flow
            cash_at_bank_items = [
                item for item in cash_flow_items
                if concept_labels.get(item['concept_id']) in ['cash_at_bank', 'balances_with_banks', 'cash_and_equivalents']
                and 'beginning' not in (concept_labels.get(item['concept_id']) or '').lower()
            ]
            
            has_end_cash_label = any(
                concept_labels.get(item['concept_id']) == 'cash_and_cash_equivalents_at_the_end_of_the_year'
                for item in cash_flow_items
            )
            
            # If we have cash_at_bank but not end_cash_label, map it
            if cash_at_bank_items and not has_end_cash_label and end_cash_concept_id:
                # Replace cash_at_bank with end_cash concept
                for item in items_to_insert:
                    if (item['filing_id'] == filing_id_val and
                        item['statement_type'] == 'cash_flow' and
                        concept_labels.get(item['concept_id']) in ['cash_at_bank', 'balances_with_banks', 'cash_and_equivalents'] and
                        'beginning' not in (concept_labels.get(item['concept_id']) or '').lower()):
                        # Map to end_cash concept
                        item['concept_id'] = end_cash_concept_id
                        # Update normalized_label in concept_labels for future checks
                        concept_labels[item['concept_id']] = 'cash_and_cash_equivalents_at_the_end_of_the_year'
                        break  # Only map first occurrence
            
            # If we have both, remove cash_at_bank/balances_with_banks (deduplication)
            if has_end_cash_label or (cash_at_bank_items and end_cash_concept_id):
                items_to_insert = [
                    item for item in items_to_insert
                    if not (
                        item['filing_id'] == filing_id_val and
                        item['statement_type'] == 'cash_flow' and
                        concept_labels.get(item['concept_id']) in ['cash_at_bank', 'balances_with_banks'] and
                        'beginning' not in (concept_labels.get(item['concept_id']) or '').lower() and
                        # Don't remove if we just mapped it to end_cash
                        item['concept_id'] != end_cash_concept_id
                    )
                ]
        
        # Delete existing items for this filing/statement_type combination first
        # This ensures we don't have stale standard template items when XBRL exists
        if filing_id:
            delete_query = text("""
                DELETE FROM rel_statement_items
                WHERE filing_id = :filing_id
            """)
            conn.execute(delete_query, {"filing_id": filing_id})
        else:
            # Delete all items - we'll re-populate everything
            delete_query = text("DELETE FROM rel_statement_items")
            conn.execute(delete_query)
        
        # Insert items
        if items_to_insert:
            # Handle NULL side values properly
            # Set defaults for any missing fields
            for item in items_to_insert:
                if 'side' not in item or item['side'] is None:
                    item['side'] = None  # Explicitly set to None for non-balance-sheet items
                if 'inferred_order' not in item:
                    item['inferred_order'] = False  # Default to False if not set
                if 'header_source' not in item:
                    # Set header_source based on is_header flag
                    if item.get('is_header', False):
                        # If is_header=True but header_source not set, it's likely synthetic (will be updated later)
                        item['header_source'] = 'synthetic'  # Default for headers without explicit source
                    else:
                        item['header_source'] = None  # Not a header
            
            insert_query = text("""
                INSERT INTO rel_statement_items (
                    filing_id, concept_id, statement_type, display_order,
                    is_header, is_main_item, role_uri, source, side, inferred_order, header_source
                ) VALUES (
                    :filing_id, :concept_id, :statement_type, :display_order,
                    :is_header, :is_main_item, :role_uri, :source, :side, :inferred_order, :header_source
                )
            """)
            
            conn.execute(insert_query, items_to_insert)
            conn.commit()
            
            # UNIVERSAL FIX: Update display_order for equity statement items to ensure correct order
            # This ensures that display_order matches compute_equity_order() results
            if any(item.get('statement_type') == 'equity_statement' for item in items_to_insert):
                # Get all equity statement items and their normalized_labels
                equity_items_query = text("""
                    SELECT si.filing_id, si.concept_id, co.normalized_label
                    FROM rel_statement_items si
                    JOIN dim_concepts co ON si.concept_id = co.concept_id
                    WHERE si.statement_type = 'equity_statement'
                      AND (:filing_id IS NULL OR si.filing_id = :filing_id)
                """)
                equity_items_result = conn.execute(equity_items_query, {"filing_id": filing_id})
                equity_items = equity_items_result.fetchall()
                
                # Update display_order for each item using compute_equity_order
                for filing_id_val, concept_id_val, normalized_label in equity_items:
                    correct_order = compute_equity_order(normalized_label)
                    update_query = text("""
                        UPDATE rel_statement_items
                        SET display_order = :display_order
                        WHERE filing_id = :filing_id
                          AND concept_id = :concept_id
                          AND statement_type = 'equity_statement'
                    """)
                    conn.execute(update_query, {
                        "filing_id": filing_id_val,
                        "concept_id": concept_id_val,
                        "display_order": correct_order
                    })
                conn.commit()
            
            # Also populate templates/overrides if template tables exist
            try:
                populate_templates_from_items(conn, filing_id, items_to_insert)
            except Exception as e:
                # Don't fail if templates don't exist yet (backward compatibility)
                print(f"   ⚠️  Template population skipped: {e}")
            
            print(f"   ✅ Populated {len(items_to_insert)} statement items")
            return len(items_to_insert)
        else:
            print(f"   ⚠️  No main statement items found")
            return 0


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Populate rel_statement_items table')
    parser.add_argument('--filing-id', type=int, help='Process only this filing ID')
    args = parser.parse_args()
    
    populate_statement_items(filing_id=args.filing_id)

