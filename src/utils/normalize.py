"""
Data Normalization Utilities

Handles scale normalization, currency detection, and data standardization
for financial facts extracted from XBRL filings.
"""
import re
import logging
from typing import Optional, Dict, Any, Tuple
from decimal import Decimal, InvalidOperation
from datetime import datetime, date

logger = logging.getLogger(__name__)


# Common currency codes
CURRENCY_CODES = {
    'usd', 'eur', 'gbp', 'jpy', 'cny', 'chf', 'cad', 'aud', 'nzd',
    'sek', 'nok', 'dkk', 'inr', 'brl', 'rub', 'krw', 'hkd', 'sgd',
    'mxn', 'zar', 'try', 'pln', 'thb', 'myr', 'idr', 'php'
}

# Scale indicators in XBRL
SCALE_PATTERNS = {
    'thousands': 1_000,
    'thousand': 1_000,
    'millions': 1_000_000,
    'million': 1_000_000,
    'billions': 1_000_000_000,
    'billion': 1_000_000_000,
}


class FinancialDataNormalizer:
    """Normalize financial data from XBRL filings"""
    
    def __init__(self):
        self.stats = {
            'scaled_values': 0,
            'currency_detected': 0,
            'dates_normalized': 0,
            'negative_values': 0,
            'errors': 0
        }
    
    def normalize_fact(self, fact: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize a single financial fact
        
        Args:
            fact: Raw fact dictionary from parser
            
        Returns:
            Normalized fact dictionary with additional fields
        """
        normalized = fact.copy()
        
        # Detect and apply scale
        scale_info = self._detect_scale(fact)
        if scale_info['scale_factor'] != 1:
            normalized['original_value_numeric'] = fact.get('value_numeric')
            normalized['scale_factor'] = scale_info['scale_factor']
            normalized['scale_description'] = scale_info['description']
            
            if fact.get('value_numeric'):
                try:
                    normalized['value_numeric'] = float(fact['value_numeric']) * scale_info['scale_factor']
                    self.stats['scaled_values'] += 1
                except (TypeError, ValueError) as e:
                    logger.warning(f"Failed to apply scale to {fact.get('concept')}: {e}")
                    self.stats['errors'] += 1
        
        # Detect and normalize currency
        currency_info = self._detect_currency(fact)
        normalized['currency'] = currency_info['currency']
        normalized['currency_source'] = currency_info['source']
        if currency_info['currency']:
            self.stats['currency_detected'] += 1
        
        # Normalize dates
        date_info = self._normalize_dates(fact)
        if date_info:
            normalized.update(date_info)
            self.stats['dates_normalized'] += 1
        
        # Handle negative values (track for validation)
        if fact.get('value_numeric') and float(fact.get('value_numeric', 0)) < 0:
            normalized['is_negative'] = True
            self.stats['negative_values'] += 1
        else:
            normalized['is_negative'] = False
        
        # Standardize data types
        normalized['value_numeric_decimal'] = self._to_decimal(normalized.get('value_numeric'))
        
        return normalized
    
    def _detect_scale(self, fact: Dict[str, Any]) -> Dict[str, Any]:
        """
        Detect scale factor from unit, context, or decimals attribute
        
        XBRL files can indicate scale in multiple ways:
        - decimals="-3" means thousands
        - decimals="-6" means millions
        - Unit measure might include scale
        - Context might have text like "in thousands"
        """
        scale_info = {
            'scale_factor': 1,
            'description': 'units',
            'source': 'none'
        }
        
        # Method 1: Check decimals attribute
        decimals = fact.get('decimals')
        if decimals and isinstance(decimals, str):
            try:
                decimal_val = int(decimals)
                if decimal_val < 0:
                    scale_factor = 10 ** abs(decimal_val)
                    scale_info['scale_factor'] = scale_factor
                    
                    # Describe the scale
                    if scale_factor == 1_000:
                        scale_info['description'] = 'thousands'
                    elif scale_factor == 1_000_000:
                        scale_info['description'] = 'millions'
                    elif scale_factor == 1_000_000_000:
                        scale_info['description'] = 'billions'
                    else:
                        scale_info['description'] = f'10^{abs(decimal_val)}'
                    
                    scale_info['source'] = 'decimals_attribute'
                    return scale_info
            except (ValueError, TypeError):
                pass
        
        # Method 2: Check unit measure
        unit_measure = fact.get('unit_measure', '')
        if isinstance(unit_measure, str):
            unit_lower = unit_measure.lower()
            for pattern, factor in SCALE_PATTERNS.items():
                if pattern in unit_lower:
                    scale_info['scale_factor'] = factor
                    scale_info['description'] = pattern
                    scale_info['source'] = 'unit_measure'
                    return scale_info
        
        # Method 3: Check value_text for scale indicators
        value_text = fact.get('value_text', '')
        if isinstance(value_text, str) and len(value_text) < 100:
            value_lower = value_text.lower()
            for pattern, factor in SCALE_PATTERNS.items():
                if pattern in value_lower:
                    scale_info['scale_factor'] = factor
                    scale_info['description'] = pattern
                    scale_info['source'] = 'value_text'
                    return scale_info
        
        return scale_info
    
    def _detect_currency(self, fact: Dict[str, Any]) -> Dict[str, str]:
        """
        Detect currency from unit measure or context
        
        Returns:
            Dictionary with currency code and source
        """
        currency_info = {
            'currency': None,
            'source': 'none'
        }
        
        # Check unit measure first
        unit_measure = fact.get('unit_measure', '')
        if isinstance(unit_measure, str):
            unit_lower = unit_measure.lower()
            
            # Direct currency code match
            for currency_code in CURRENCY_CODES:
                if currency_code in unit_lower:
                    currency_info['currency'] = currency_code.upper()
                    currency_info['source'] = 'unit_measure'
                    return currency_info
            
            # Check for common currency symbols
            if '$' in unit_measure or 'dollar' in unit_lower:
                currency_info['currency'] = 'USD'
                currency_info['source'] = 'unit_measure_symbol'
                return currency_info
            elif '€' in unit_measure or 'euro' in unit_lower:
                currency_info['currency'] = 'EUR'
                currency_info['source'] = 'unit_measure_symbol'
                return currency_info
            elif '£' in unit_measure or 'pound' in unit_lower:
                currency_info['currency'] = 'GBP'
                currency_info['source'] = 'unit_measure_symbol'
                return currency_info
        
        # Check unit_type
        unit_type = fact.get('unit_type', '')
        if unit_type == 'currency':
            # Try to infer from unit_id or other fields
            unit_id = fact.get('unit_id', '')
            if isinstance(unit_id, str):
                unit_id_upper = unit_id.upper()
                for currency_code in CURRENCY_CODES:
                    if currency_code.upper() in unit_id_upper:
                        currency_info['currency'] = currency_code.upper()
                        currency_info['source'] = 'unit_id'
                        return currency_info
        
        return currency_info
    
    def _normalize_dates(self, fact: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Ensure dates are in ISO 8601 format (YYYY-MM-DD)
        
        Returns:
            Dictionary with normalized date fields
        """
        date_fields = {}
        
        for field in ['period_start', 'period_end', 'instant_date', 'fiscal_year_end']:
            value = fact.get(field)
            if value:
                normalized_date = self._parse_date(value)
                if normalized_date:
                    date_fields[field] = normalized_date.isoformat() if isinstance(normalized_date, date) else normalized_date
        
        return date_fields if date_fields else None
    
    def _parse_date(self, value: Any) -> Optional[date]:
        """Parse various date formats to datetime.date"""
        if isinstance(value, date):
            return value
        
        if isinstance(value, datetime):
            return value.date()
        
        if isinstance(value, str):
            # Try common formats
            for fmt in ['%Y-%m-%d', '%Y%m%d', '%m/%d/%Y', '%d/%m/%Y']:
                try:
                    return datetime.strptime(value, fmt).date()
                except ValueError:
                    continue
        
        return None
    
    def _to_decimal(self, value: Any) -> Optional[Decimal]:
        """Convert numeric value to Decimal for precise calculations"""
        if value is None:
            return None
        
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None
    
    def get_stats(self) -> Dict[str, int]:
        """Return normalization statistics"""
        return self.stats.copy()


def normalize_concept_name(concept: str) -> str:
    """
    Normalize concept names for easier matching
    
    Args:
        concept: Raw XBRL concept name
        
    Returns:
        Normalized concept name
    """
    # Convert PascalCase to snake_case
    concept = re.sub('([A-Z]+)([A-Z][a-z])', r'\1_\2', concept)
    concept = re.sub(r'([a-z\d])([A-Z])', r'\1_\2', concept)
    return concept.lower()


def identify_statement_type(concept: str) -> Optional[str]:
    """
    Identify which financial statement a concept belongs to
    
    Args:
        concept: XBRL concept name
        
    Returns:
        'income_statement', 'balance_sheet', 'cash_flow', 'equity', 'footnotes', or None
    """
    concept_lower = concept.lower()
    
    # Income Statement indicators
    income_keywords = [
        'revenue', 'sales', 'income', 'profit', 'loss', 'expense', 'cost',
        'margin', 'earnings', 'ebit', 'ebitda', 'grosspro', 'operatingincome'
    ]
    
    # Balance Sheet indicators
    balance_keywords = [
        'asset', 'liability', 'equity', 'cash', 'receivable', 'payable',
        'inventory', 'property', 'debt', 'retained', 'capital', 'stockholder'
    ]
    
    # Cash Flow indicators
    cashflow_keywords = [
        'cashflow', 'operating activit', 'investing activit', 'financing activit',
        'depreciation', 'amortization', 'capex', 'dividendspaid'
    ]
    
    # Equity Statement indicators
    equity_keywords = [
        'sharesoutstanding', 'sharesissued', 'treasurystock', 'dividends',
        'stockrepurchase'
    ]
    
    # Check each category
    for keyword in income_keywords:
        if keyword in concept_lower:
            return 'income_statement'
    
    for keyword in cashflow_keywords:
        if keyword in concept_lower:
            return 'cash_flow'
    
    for keyword in equity_keywords:
        if keyword in concept_lower:
            return 'equity'
    
    for keyword in balance_keywords:
        if keyword in concept_lower:
            return 'balance_sheet'
    
    return 'footnotes'


def main():
    """Test normalization functions"""
    import json
    
    # Test with real data
    test_fact = {
        'concept': 'Revenue',
        'value_numeric': 1000,
        'decimals': '-6',  # millions
        'unit_measure': 'USD',
        'period_end': '2024-12-31'
    }
    
    normalizer = FinancialDataNormalizer()
    normalized = normalizer.normalize_fact(test_fact)
    
    print("Test Normalization:")
    print(json.dumps(normalized, indent=2, default=str))
    print(f"\nStats: {normalizer.get_stats()}")


if __name__ == '__main__':
    main()

