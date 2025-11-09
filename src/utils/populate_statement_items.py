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
from pathlib import Path
from typing import Dict, List, Optional
from sqlalchemy import create_engine, text
from config import DATABASE_URI

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def is_main_statement_item(role_uri: Optional[str], source: str, statement_type: str, normalized_label: Optional[str] = None) -> bool:
    """
    Determine if a presentation hierarchy item is a main statement item (not detail/disclosure).
    
    Args:
        role_uri: XBRL role URI from presentation hierarchy
        source: 'xbrl' or 'standard'
        statement_type: 'income_statement', 'balance_sheet', etc.
    
    Returns:
        True if this is a main statement item, False if it's a detail/disclosure
    """
    # Standard templates are always main items
    if source == 'standard':
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
    # Handle both full label and shortened "cash_and_equivalents" (which is end-of-year cash)
    if 'cash_and_cash_equivalents_at_the_end' in label_lower or (label_lower == 'cash_and_equivalents' and 'beginning' not in label_lower):
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
    
    # Other comprehensive income (must come before total)
    # Handle both "other_comprehensive_income" and "oci_total" patterns
    if 'oci_total' in label_lower or ('other_comprehensive_income' in label_lower and 'total' not in label_lower and 'net_of_tax' not in label_lower):
        return 2
    
    # Total comprehensive income
    # Handle both "total_comprehensive_income" and "comprehensive_income" (without "other" prefix)
    if 'total_comprehensive_income' in label_lower or (label_lower == 'comprehensive_income' and 'other' not in label_lower):
        return 3
    
    # Transfer of cash flow hedge reserve to intangible assets
    if 'amount_removed_from_reserve_of_cash_flow_hedges' in label_lower or ('transfer' in label_lower and 'cash_flow_hedge' in label_lower):
        return 4
    
    # Transactions with owners (header) - synthetic, handled separately
    if 'transactions_with_owners_header' in label_lower:
        return 5
    
    # Dividends (first transaction item)
    if 'dividends_paid' in label_lower or ('dividend' in label_lower and 'paid' in label_lower):
        return 6
    
    # Share-based payments (second transaction item)
    if 'increase_decrease_through_sharebased_payment' in label_lower or ('sharebased_payment' in label_lower and 'tax' not in label_lower):
        return 7
    
    # Purchase of treasury shares (third transaction item)
    if 'purchase_of_treasury_shares' in label_lower or ('payments_to_acquire_or_redeem_entitys_shares' in label_lower):
        return 8
    
    # Reduction of the B share capital (fourth transaction item)
    if 'reduction_of_issued_capital' in label_lower or ('reduction' in label_lower and 'capital' in label_lower):
        return 9
    
    # Tax related to transactions with owners (last transaction item - must come after all others)
    if 'decrease_increase_through_tax_on_sharebased' in label_lower or ('tax' in label_lower and 'sharebased' in label_lower and 'payment' in label_lower):
        return 10
    
    # Balance at the end of the year
    if 'balance' in label_lower and 'end' in label_lower:
        return 11
    
    # Fallback: use a high number so unmapped items appear at the end
    return 999


def compute_display_order(order_index: int, normalized_label: str, statement_type: str, max_order_in_statement: Optional[int] = None) -> int:
    """
    Compute display_order from order_index, handling special cases like EPS items.
    
    Args:
        order_index: Original order_index from presentation hierarchy
        normalized_label: Normalized label of the concept
        statement_type: Statement type
        max_order_in_statement: Maximum order_index in the statement (for EPS positioning)
    
    Returns:
        Corrected display_order
    """
    label_lower = normalized_label.lower()
    
    # For comprehensive income, use standard IFRS ordering (UNIVERSAL)
    if statement_type == 'comprehensive_income':
        return compute_comprehensive_income_order(normalized_label)
    
    # For cash flow, use standard IFRS/US-GAAP ordering (UNIVERSAL)
    if statement_type == 'cash_flow':
        return compute_cash_flow_order(normalized_label)
    
    # For equity statement, use standard IFRS/US-GAAP ordering (UNIVERSAL)
    if statement_type == 'equity_statement':
        return compute_equity_order(normalized_label)
    
    # For income statement, EPS items should appear after net profit (order 13)
    # If we know the max order, place EPS items after it
    if statement_type == 'income_statement':
        if 'earnings' in label_lower and 'share' in label_lower:
            # EPS items: push to end (after net income which is typically order 13)
            # Use 15 + order_index to ensure they come after net income (13) and header (14)
            # This way: basic_eps (order 1) -> display_order 15, diluted_eps (order 2) -> display_order 16
            return 15 + order_index
    
    return order_index


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
                ORDER BY ph.child_concept_id, ph.statement_type,
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
        
        # Process each item
        items_to_insert = []
        for row in rows:
            pres_id, filing_id_val, concept_id, stmt_type, order_idx, role_uri, source, normalized_label = row
            
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
            is_main = is_main_statement_item(role_uri, source or 'xbrl', stmt_type or 'other', normalized_label)
            
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
            
            # Compute display_order
            # For XBRL items: use order_index directly (EPS items handled separately)
            # For standard items: use large offset to ensure they come after XBRL items
            if source == 'xbrl':
                max_order = xbrl_items_by_statement.get((filing_id_val, stmt_type), None)
                display_order = compute_display_order(order_idx, normalized_label or '', stmt_type or 'other', max_order)
                
                # CRITICAL: For comprehensive_income, use standard IFRS ordering
                # This is handled by compute_display_order() which calls compute_comprehensive_income_order()
                # No additional adjustment needed here
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
                'side': side  # For balance sheet: 'assets' or 'liabilities_equity'
            })
        
        # Second pass: Add "Net profit" to comprehensive income (references income statement)
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
                # Find net_income concept_id directly from database
                # UNIVERSAL: Comprehensive income statements ALWAYS start with net profit from income statement
                concept_check = text("""
                    SELECT concept_id FROM dim_concepts 
                    WHERE normalized_label = 'net_income_including_noncontrolling_interest'
                    LIMIT 1
                """)
                concept_result = conn.execute(concept_check)
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
                        items_to_insert.append({
                            'filing_id': filing_id_val,
                            'concept_id': net_income_concept_id,
                            'statement_type': 'comprehensive_income',
                            'display_order': 0,  # First item in comprehensive income
                            'is_header': False,
                            'is_main_item': True,
                            'role_uri': None,  # Synthetic - references income statement
                            'source': 'xbrl'
                        })
        
        # Third pass: Create synthetic "Earnings per share" header for income statements with EPS items
        # This header should appear before EPS items (display_order = 13.5, between net income and EPS)
        for (filing_id_val, stmt_type), eps_concept_ids in eps_concepts_by_statement.items():
            if stmt_type == 'income_statement' and len(eps_concept_ids) > 0:
                # Check if header already exists
                header_exists = False
                for item in items_to_insert:
                    if (item['filing_id'] == filing_id_val and 
                        item['statement_type'] == stmt_type and 
                        item.get('is_header') and
                        'earnings' in (item.get('normalized_label', '') or '').lower() and
                        'share' in (item.get('normalized_label', '') or '').lower()):
                        header_exists = True
                        break
                
                if not header_exists:
                    # Find or create a synthetic concept for "Earnings per share" header
                    # We'll use a special normalized_label that the frontend can recognize
                    header_concept_query = text("""
                        SELECT concept_id FROM dim_concepts
                        WHERE normalized_label = 'earnings_per_share_header'
                        LIMIT 1
                    """)
                    header_concept_result = conn.execute(header_concept_query)
                    header_concept_row = header_concept_result.fetchone()
                    
                    if header_concept_row:
                        header_concept_id = header_concept_row[0]
                        # Check if header already in items_to_insert (avoid duplicate)
                        header_already_added = any(
                            item['concept_id'] == header_concept_id and 
                            item['filing_id'] == filing_id_val and 
                            item['statement_type'] == stmt_type
                            for item in items_to_insert
                        )
                        if not header_already_added:
                            # Add header item with display_order = 14 (right before EPS items at 15-16)
                            # Use 14 to ensure it comes after net income (13) but before EPS (15-16)
                            items_to_insert.append({
                                'filing_id': filing_id_val,
                                'concept_id': header_concept_id,
                                'statement_type': stmt_type,
                                'display_order': 14,  # Right before EPS items (15-16)
                                'is_header': True,
                                'is_main_item': True,
                                'role_uri': None,
                                'source': 'xbrl'
                            })
        
        # Fourth pass: Create synthetic "Other comprehensive income" header for comprehensive income
        # This header should appear right after Net profit, before OCI items
        for filing_id_val in filing_ids:
            # Check if we have comprehensive_income items (excluding Net profit)
            has_oci_items = any(
                item['filing_id'] == filing_id_val and 
                item['statement_type'] == 'comprehensive_income' and
                item.get('display_order', 999) > 0  # Exclude Net profit (order 0)
                for item in items_to_insert
            )
            
            if has_oci_items:
                # Find or create "Other comprehensive income" header concept
                header_concept_query = text("""
                    SELECT concept_id FROM dim_concepts
                    WHERE normalized_label = 'other_comprehensive_income_header'
                    LIMIT 1
                """)
                header_concept_result = conn.execute(header_concept_query)
                header_concept_row = header_concept_result.fetchone()
                
                if not header_concept_row:
                    # Create the header concept if it doesn't exist
                    create_header_query = text("""
                        INSERT INTO dim_concepts (
                            concept_name, taxonomy, normalized_label, preferred_label,
                            concept_type, is_abstract, statement_type
                        ) VALUES (
                            'OtherComprehensiveIncomeHeader', 'custom', 'other_comprehensive_income_header', 'Other comprehensive income',
                            'text', TRUE, 'comprehensive_income'
                        )
                        RETURNING concept_id
                    """)
                    header_concept_result = conn.execute(create_header_query)
                    header_concept_row = header_concept_result.fetchone()
                    conn.commit()
                
                if header_concept_row:
                    header_concept_id = header_concept_row[0]
                    # Check if header already in items_to_insert
                    header_already_added = any(
                        item['concept_id'] == header_concept_id and 
                        item['filing_id'] == filing_id_val and 
                        item['statement_type'] == 'comprehensive_income'
                        for item in items_to_insert
                    )
                    
                    if not header_already_added:
                        # "Other comprehensive income" header comes right after Net profit (order 0)
                        # and before first OCI item (Remeasurements, order 1)
                        items_to_insert.append({
                            'filing_id': filing_id_val,
                            'concept_id': header_concept_id,
                            'statement_type': 'comprehensive_income',
                            'display_order': 1,  # Right after Net profit (0), before Remeasurements (1)
                            'is_header': True,
                            'is_main_item': True,
                            'role_uri': None,
                            'source': 'xbrl'
                        })
        
        # Fifth pass: Create synthetic "Cash flow hedges" header for comprehensive income
        # This header should appear before cash flow hedge items
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
                # Find or create "Cash flow hedges" header concept
                header_concept_query = text("""
                    SELECT concept_id FROM dim_concepts
                    WHERE normalized_label = 'cash_flow_hedges_header'
                    LIMIT 1
                """)
                header_concept_result = conn.execute(header_concept_query)
                header_concept_row = header_concept_result.fetchone()
                
                if not header_concept_row:
                    # Create the header concept if it doesn't exist
                    create_header_query = text("""
                        INSERT INTO dim_concepts (
                            concept_name, taxonomy, normalized_label, preferred_label,
                            concept_type, is_abstract, statement_type
                        ) VALUES (
                            'CashFlowHedgesHeader', 'custom', 'cash_flow_hedges_header', 'Cash flow hedges',
                            'text', TRUE, 'comprehensive_income'
                        )
                        RETURNING concept_id
                    """)
                    header_concept_result = conn.execute(create_header_query)
                    header_concept_row = header_concept_result.fetchone()
                    conn.commit()
                
                if header_concept_row:
                    header_concept_id = header_concept_row[0]
                    # Check if header already in items_to_insert
                    header_already_added = any(
                        item['concept_id'] == header_concept_id and 
                        item['filing_id'] == filing_id_val and 
                        item['statement_type'] == 'comprehensive_income'
                        for item in items_to_insert
                    )
                    
                    if not header_already_added:
                        # Cash flow hedges header should appear before cash flow hedge items
                        # Based on standard IFRS structure, cash flow hedges header comes after exchange rate adjustments (3)
                        # and before realisation of previously deferred (4)
                        header_order = 4  # Standard IFRS position for "Cash flow hedges" header
                        
                        items_to_insert.append({
                            'filing_id': filing_id_val,
                            'concept_id': header_concept_id,
                            'statement_type': 'comprehensive_income',
                            'display_order': header_order,
                            'is_header': True,
                            'is_main_item': True,
                            'role_uri': None,
                            'source': 'xbrl'
                        })
        
        # Fifth pass: Create synthetic "Assets" header for balance sheet
        # This header should appear at position 0 (first item in assets section)
        for filing_id_val in filing_ids:
            # Check if we have balance_sheet items with assets side
            has_assets_items = any(
                item['filing_id'] == filing_id_val and 
                item['statement_type'] == 'balance_sheet' and
                item.get('side') == 'assets'
                for item in items_to_insert
            )
            
            if has_assets_items:
                # Find or create "Assets" header concept
                header_concept_query = text("""
                    SELECT concept_id FROM dim_concepts
                    WHERE normalized_label = 'assets_header'
                    LIMIT 1
                """)
                header_concept_result = conn.execute(header_concept_query)
                header_concept_row = header_concept_result.fetchone()
                
                if not header_concept_row:
                    # Create the header concept if it doesn't exist
                    create_header_query = text("""
                        INSERT INTO dim_concepts (
                            concept_name, taxonomy, normalized_label, preferred_label,
                            concept_type, is_abstract, statement_type
                        ) VALUES (
                            'AssetsHeader', 'synthetic', 'assets_header', 'Assets',
                            'text', TRUE, 'balance_sheet'
                        )
                        RETURNING concept_id
                    """)
                    create_result = conn.execute(create_header_query)
                    header_concept_id = create_result.fetchone()[0]
                    conn.commit()
                else:
                    header_concept_id = header_concept_row[0]
                
                # Check if header already in items_to_insert (avoid duplicate)
                header_already_added = any(
                    item['concept_id'] == header_concept_id and 
                    item['filing_id'] == filing_id_val and 
                    item['statement_type'] == 'balance_sheet'
                    for item in items_to_insert
                )
                
                if not header_already_added:
                    # "Assets" header comes first (display_order = 0, before first asset at 1)
                    items_to_insert.append({
                        'filing_id': filing_id_val,
                        'concept_id': header_concept_id,
                        'statement_type': 'balance_sheet',
                        'display_order': 0,  # First item in balance sheet (before all assets)
                        'is_header': True,
                        'is_main_item': True,
                        'role_uri': None,
                        'source': 'xbrl',
                        'side': 'assets'  # Assets header is on assets side
                    })
        
        # Sixth pass: Create synthetic "Equity and liabilities" header for balance sheet
        # This header should appear at the start of the liabilities_equity section
        for filing_id_val in filing_ids:
            # Check if we have balance_sheet items with liabilities_equity side
            has_liabilities_equity_items = any(
                item['filing_id'] == filing_id_val and 
                item['statement_type'] == 'balance_sheet' and
                item.get('side') == 'liabilities_equity'
                for item in items_to_insert
            )
            
            if has_liabilities_equity_items:
                # Find or create "Equity and liabilities" header concept
                header_concept_query = text("""
                    SELECT concept_id FROM dim_concepts
                    WHERE normalized_label = 'equity_and_liabilities_header'
                    LIMIT 1
                """)
                header_concept_result = conn.execute(header_concept_query)
                header_concept_row = header_concept_result.fetchone()
                
                if not header_concept_row:
                    # Create the header concept if it doesn't exist
                    create_header_query = text("""
                        INSERT INTO dim_concepts (
                            concept_name, taxonomy, normalized_label, preferred_label,
                            concept_type, is_abstract, statement_type
                        ) VALUES (
                            'EquityAndLiabilitiesHeader', 'synthetic', 'equity_and_liabilities_header', 'Equity and liabilities',
                            'text', TRUE, 'balance_sheet'
                        )
                        RETURNING concept_id
                    """)
                    create_result = conn.execute(create_header_query)
                    header_concept_id = create_result.fetchone()[0]
                    conn.commit()
                else:
                    header_concept_id = header_concept_row[0]
                
                # Check if header already in items_to_insert (avoid duplicate)
                header_already_added = any(
                    item['concept_id'] == header_concept_id and 
                    item['filing_id'] == filing_id_val and 
                    item['statement_type'] == 'balance_sheet'
                    for item in items_to_insert
                )
                
                if not header_already_added:
                    # Find the minimum display_order for liabilities_equity items
                    min_liabilities_order = min(
                        (item.get('display_order', 999) for item in items_to_insert
                         if item['filing_id'] == filing_id_val and 
                         item['statement_type'] == 'balance_sheet' and
                         item.get('side') == 'liabilities_equity'),
                        default=1
                    )
                    # "Equity and liabilities" header comes before first liabilities_equity item
                    items_to_insert.append({
                        'filing_id': filing_id_val,
                        'concept_id': header_concept_id,
                        'statement_type': 'balance_sheet',
                        'display_order': min_liabilities_order - 1,  # Before first liabilities_equity item
                        'is_header': True,
                        'is_main_item': True,
                        'role_uri': None,
                        'source': 'xbrl',
                        'side': 'liabilities_equity'  # Equity and liabilities header is on right side
                    })
        
        # Seventh pass: Create synthetic "Adjustment of non-cash items" header for cash flow statements
        # This header should appear right after Net profit, before adjustment items
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
                # Find or create "Adjustment of non-cash items" header concept
                header_concept_query = text("""
                    SELECT concept_id FROM dim_concepts
                    WHERE normalized_label = 'adjustment_of_non_cash_items_header'
                    LIMIT 1
                """)
                header_concept_result = conn.execute(header_concept_query)
                header_concept_row = header_concept_result.fetchone()
                
                if not header_concept_row:
                    # Create the header concept if it doesn't exist
                    create_header_query = text("""
                        INSERT INTO dim_concepts (
                            concept_name, taxonomy, normalized_label, concept_type,
                            balance_type, period_type, data_type, is_abstract, statement_type, preferred_label
                        ) VALUES (
                            'AdjustmentOfNonCashItemsHeader', 'synthetic', 'adjustment_of_non_cash_items_header', 'string',
                            NULL, 'duration', 'string', TRUE, 'cash_flow', 'Adjustment of non-cash items'
                        )
                        RETURNING concept_id
                    """)
                    create_result = conn.execute(create_header_query)
                    header_concept_id = create_result.fetchone()[0]
                    conn.commit()
                else:
                    header_concept_id = header_concept_row[0]
                
                # Check if header already in items_to_insert (avoid duplicate)
                header_already_added = any(
                    item['concept_id'] == header_concept_id and 
                    item['filing_id'] == filing_id_val and 
                    item['statement_type'] == 'cash_flow'
                    for item in items_to_insert
                )
                if not header_already_added:
                    items_to_insert.append({
                        'filing_id': filing_id_val,
                        'concept_id': header_concept_id,
                        'statement_type': 'cash_flow',
                        'display_order': 1,  # Right after Net profit (0)
                        'is_header': True,
                        'is_main_item': True,
                        'role_uri': None,
                        'source': 'xbrl'
                    })
        
        # Eighth pass: Create synthetic "Cash and cash equivalents at the beginning of the year" for cash flow statements
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
                        'source': 'calculated'  # Mark as calculated, not from XBRL
                    })
        
        # Ninth pass: Create synthetic "Transactions with owners" header for equity statements
        # This header should appear before transaction items (dividends, share-based payments, etc.)
        for filing_id_val in filing_ids:
            # Check if we have equity_statement items with transaction items
            equity_statement_concept_ids = [
                item['concept_id'] for item in items_to_insert
                if item['filing_id'] == filing_id_val and 
                   item['statement_type'] == 'equity_statement' and
                   item.get('display_order', 999) >= 6  # Transaction items start at order 6
            ]
            
            if equity_statement_concept_ids:
                # Query normalized_labels from database
                label_query = text("""
                    SELECT normalized_label FROM dim_concepts
                    WHERE concept_id = ANY(:concept_ids)
                """)
                label_result = conn.execute(label_query, {'concept_ids': equity_statement_concept_ids})
                normalized_labels = [row[0] or '' for row in label_result]
                
                # Check if any are transaction items (dividends, share-based payments, etc.)
                has_transaction_items = any(
                    ('dividend' in label.lower() or
                     'sharebased' in label.lower() or
                     'treasury' in label.lower() or
                     'reduction' in label.lower() or
                     'tax_on_sharebased' in label.lower())
                    for label in normalized_labels
                )
            else:
                has_transaction_items = False
            
            if has_transaction_items:
                # Find or create "Transactions with owners" header concept
                header_concept_query = text("""
                    SELECT concept_id FROM dim_concepts
                    WHERE normalized_label = 'transactions_with_owners_header'
                    LIMIT 1
                """)
                header_concept_result = conn.execute(header_concept_query)
                header_concept_row = header_concept_result.fetchone()
                
                if not header_concept_row:
                    # Create the header concept if it doesn't exist
                    create_header_query = text("""
                        INSERT INTO dim_concepts (
                            concept_name, taxonomy, normalized_label, concept_type,
                            balance_type, period_type, data_type, is_abstract, statement_type, preferred_label
                        ) VALUES (
                            'TransactionsWithOwnersHeader', 'synthetic', 'transactions_with_owners_header', 'string',
                            NULL, 'duration', 'string', TRUE, 'equity_statement', 'Transactions with owners'
                        )
                        RETURNING concept_id
                    """)
                    create_result = conn.execute(create_header_query)
                    header_concept_id = create_result.fetchone()[0]
                    conn.commit()
                else:
                    header_concept_id = header_concept_row[0]
                
                # Check if header already in items_to_insert (avoid duplicate)
                header_already_added = any(
                    item['concept_id'] == header_concept_id and 
                    item['filing_id'] == filing_id_val and 
                    item['statement_type'] == 'equity_statement'
                    for item in items_to_insert
                )
                if not header_already_added:
                    items_to_insert.append({
                        'filing_id': filing_id_val,
                        'concept_id': header_concept_id,
                        'statement_type': 'equity_statement',
                        'display_order': 5,  # Before transaction items (6+)
                        'is_header': True,
                        'is_main_item': True,
                        'role_uri': None,
                        'source': 'xbrl'
                    })
        
        # Tenth pass: Create synthetic "Balance at the beginning of the year" and "Balance at the end of the year" for equity statements
        # Beginning balance = previous year's end balance (from balance sheet)
        # End balance = current year's end balance (from balance sheet)
        for filing_id_val in filing_ids:
            # Check if we have equity_statement items
            has_equity_statement_items = any(
                item['filing_id'] == filing_id_val and 
                item['statement_type'] == 'equity_statement'
                for item in items_to_insert
            )
            
            if has_equity_statement_items:
                # Beginning balance concept
                beginning_concept_query = text("""
                    SELECT concept_id FROM dim_concepts
                    WHERE normalized_label = 'balance_at_the_beginning_of_the_year_equity'
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
                
                # End balance concept
                end_concept_query = text("""
                    SELECT concept_id FROM dim_concepts
                    WHERE normalized_label = 'balance_at_the_end_of_the_year_equity'
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
                
                # Add beginning balance (order 0)
                if not any(item['concept_id'] == beginning_concept_id and item['filing_id'] == filing_id_val and item['statement_type'] == 'equity_statement' for item in items_to_insert):
                    items_to_insert.append({
                        'filing_id': filing_id_val,
                        'concept_id': beginning_concept_id,
                        'statement_type': 'equity_statement',
                        'display_order': 0,  # First item
                        'is_header': False,
                        'is_main_item': True,
                        'role_uri': None,
                        'source': 'calculated'
                    })
                
                # Add end balance (order 11)
                if not any(item['concept_id'] == end_concept_id and item['filing_id'] == filing_id_val and item['statement_type'] == 'equity_statement' for item in items_to_insert):
                    items_to_insert.append({
                        'filing_id': filing_id_val,
                        'concept_id': end_concept_id,
                        'statement_type': 'equity_statement',
                        'display_order': 11,  # Last item
                        'is_header': False,
                        'is_main_item': True,
                        'role_uri': None,
                        'source': 'calculated'
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
            for item in items_to_insert:
                if 'side' not in item or item['side'] is None:
                    item['side'] = None  # Explicitly set to None for non-balance-sheet items
            
            insert_query = text("""
                INSERT INTO rel_statement_items (
                    filing_id, concept_id, statement_type, display_order,
                    is_header, is_main_item, role_uri, source, side
                ) VALUES (
                    :filing_id, :concept_id, :statement_type, :display_order,
                    :is_header, :is_main_item, :role_uri, :source, :side
                )
            """)
            
            conn.execute(insert_query, items_to_insert)
            conn.commit()
            
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

