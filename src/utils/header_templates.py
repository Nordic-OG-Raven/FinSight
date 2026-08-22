"""
Standard header templates for financial statements.

These templates provide fallback headers when XBRL doesn't provide them.
Only used when XBRL parent-child relationships and label roles don't provide headers.
"""

from typing import List, Dict

STANDARD_HEADERS = {
    'income_statement': {
        'ifrs': [
            {
                'normalized_label': 'earnings_per_share_header',
                'display_order': 14,
                'preferred_label': 'Earnings per share',
                'required_items': ['basic_earnings_loss_per_share', 'diluted_earnings_loss_per_share']
            },
        ],
        'us_gaap': [
            {
                'normalized_label': 'earnings_per_share_header',
                'display_order': 14,
                'preferred_label': 'Earnings per share',
                'required_items': ['basic_earnings_loss_per_share', 'diluted_earnings_loss_per_share']
            },
        ],
    },
    'equity_statement': {
        'ifrs': [
            {
                'normalized_label': 'transactions_with_owners_header',
                'display_order': 8,
                'preferred_label': 'Transactions with owners',
                'required_items': ['dividends_paid', 'share_based_payment_expense', 'purchase_of_treasury_shares']
            },
        ],
        'us_gaap': [
            {
                'normalized_label': 'transactions_with_owners_header',
                'display_order': 8,
                'preferred_label': 'Transactions with owners',
                'required_items': ['dividends_paid', 'share_based_payment_expense', 'purchase_of_treasury_shares']
            },
        ],
    },
    'comprehensive_income': {
        'ifrs': [
            {
                'normalized_label': 'other_comprehensive_income_header',
                'display_order': 2.0,  # After Net profit (1.0) and space, before OCI items (3.0+)
                'preferred_label': 'Other comprehensive income',
                'required_items': ['other_comprehensive_income', 'oci_total']
            },
        ],
        'us_gaap': [
            {
                'normalized_label': 'other_comprehensive_income_header',
                'display_order': 2.0,  # After Net profit (1.0) and space, before OCI items (3.0+)
                'preferred_label': 'Other comprehensive income',
                'required_items': ['other_comprehensive_income', 'oci_total']
            },
        ],
    },
    'cash_flow': {
        'ifrs': [
            {
                'normalized_label': 'adjustment_of_non_cash_items_header',
                'display_order': 1.5,  # After Net profit (1.0), before adjustment items (2.0+)
                'preferred_label': 'Adjustment of non-cash items',
                'required_items': [
                    'depreciation_amortisation_and_impairment_losses',
                    'adjustments_for_depreciation_and_amortisation_expense_and_impairment_loss_reversal_of_impair_f480a5a7',
                    'changes_in_working_capital',
                    'increase_decrease_in_working_capital',
                    'other_non_cash_items'
                ]
            },
        ],
        'us_gaap': [
            {
                'normalized_label': 'adjustment_of_non_cash_items_header',
                'display_order': 1.5,  # After Net profit (1.0), before adjustment items (2.0+)
                'preferred_label': 'Adjustment of non-cash items',
                'required_items': [
                    'depreciation_amortisation_and_impairment_losses',
                    'adjustments_for_depreciation_and_amortisation_expense_and_impairment_loss_reversal_of_impair_f480a5a7',
                    'changes_in_working_capital',
                    'increase_decrease_in_working_capital',
                    'other_non_cash_items'
                ]
            },
        ],
    },
    'balance_sheet': {
        'ifrs': [
            {
                'normalized_label': 'assets_header',
                'display_order': 0,
                'preferred_label': 'Assets',
                'required_items': ['intangible_assets', 'property_plant_equipment', 'inventories', 'cash_and_equivalents'],
                'side': 'assets'
            },
            {
                'normalized_label': 'equity_and_liabilities_header',
                'display_order': 0,
                'preferred_label': 'Equity and liabilities',
                'required_items': ['share_capital', 'retained_earnings', 'borrowings', 'trade_payables'],
                'side': 'liabilities_equity'
            },
        ],
        'us_gaap': [
            {
                'normalized_label': 'assets_header',
                'display_order': 0,
                'preferred_label': 'Assets',
                'required_items': ['intangible_assets', 'property_plant_equipment', 'inventories', 'cash_and_equivalents'],
                'side': 'assets'
            },
            {
                'normalized_label': 'equity_and_liabilities_header',
                'display_order': 0,
                'preferred_label': 'Equity and liabilities',
                'required_items': ['share_capital', 'retained_earnings', 'borrowings', 'trade_payables'],
                'side': 'liabilities_equity'
            },
        ],
    },
}


def get_template_headers(statement_type: str, accounting_standard: str) -> List[Dict]:
    """
    Get standard template headers for a statement type and accounting standard.
    
    Args:
        statement_type: 'income_statement', 'equity_statement', 'comprehensive_income', etc.
        accounting_standard: 'ifrs', 'us_gaap', etc.
    
    Returns:
        List of template header definitions
    """
    # Normalize accounting standard
    standard_lower = accounting_standard.lower() if accounting_standard else 'us_gaap'
    if 'ifrs' in standard_lower:
        standard_key = 'ifrs'
    else:
        standard_key = 'us_gaap'
    
    return STANDARD_HEADERS.get(statement_type, {}).get(standard_key, [])


def should_apply_template_header(
    template_header: Dict,
    existing_items: List[Dict],
    concept_labels: Dict[str, str]
) -> bool:
    """
    Check if a template header should be applied.
    
    A template header should be applied if:
    1. The header doesn't already exist
    2. At least one required item exists in the statement
    
    Args:
        template_header: Template header definition
        existing_items: List of existing items in the statement
        concept_labels: Dictionary mapping concept_id -> normalized_label
    
    Returns:
        True if template header should be applied
    """
    normalized_label = template_header['normalized_label']
    required_items = template_header.get('required_items', [])
    
    # Check if header already exists
    header_exists = any(
        item.get('normalized_label') == normalized_label or
        item.get('is_header', False) and 
        (item.get('preferred_label', '').lower() == template_header['preferred_label'].lower())
        for item in existing_items
    )
    
    if header_exists:
        return False
    
    # Check if at least one required item exists
    existing_normalized_labels = {
        concept_labels.get(item.get('concept_id', ''), '')
        for item in existing_items
    }
    
    has_required_items = any(
        req_item in existing_normalized_labels
        for req_item in required_items
    )
    
    return has_required_items

