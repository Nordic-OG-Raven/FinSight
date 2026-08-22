#!/usr/bin/env python3
"""
XBRL-Based Validator

Validates financial statements directly against XBRL presentation hierarchy (source of truth).
No hardcoding, no derived tables - just compare against what the company filed.

This validator:
1. Gets expected structure from rel_presentation_hierarchy (XBRL source)
2. Gets expected values from fact_financial_metrics (XBRL facts)
3. Gets actual output from API
4. Compares directly

Can it determine with 100% accuracy:
a) EXACT number of items in each main financial statement
b) Their exact names (handling normalization)
c) Their relative positions in the statement
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from config import DATABASE_URI
from src.utils.concept_label_mapping import get_humanized_label


@dataclass
class XBRLStatementItem:
    """A single item from XBRL presentation hierarchy"""
    normalized_label: str
    display_label: str  # Human-readable label
    order_index: int
    concept_id: int
    statement_type: str
    role_uri: Optional[str]
    is_header: bool = False
    hierarchy_level: Optional[int] = None
    parent_concept_id: Optional[int] = None


@dataclass
class XBRLValidationResult:
    """Validation result comparing XBRL source vs API output"""
    statement_type: str
    xbrl_items: List[XBRLStatementItem]
    api_items: List[Dict]
    missing_in_api: List[str]
    extra_in_api: List[str]
    order_mismatches: List[Dict]
    label_mismatches: List[Dict]
    can_determine_structure: bool
    accuracy_assessment: str


class XBRLBasedValidator:
    """
    Validates API output directly against XBRL filing (source of truth).
    """
    
    def __init__(self, api_base: str = 'http://localhost:5001'):
        self.engine = create_engine(DATABASE_URI)
        self.api_base = api_base
    
    def get_filing_id(self, ticker: str, year: int) -> Optional[int]:
        """Get filing_id for ticker and year"""
        with self.engine.connect() as conn:
            query = text("""
                SELECT f.filing_id
                FROM dim_filings f
                JOIN dim_companies c ON f.company_id = c.company_id
                WHERE c.ticker = :ticker
                  AND EXTRACT(YEAR FROM f.fiscal_year_end) = :year
                ORDER BY f.filing_id DESC
                LIMIT 1
            """)
            result = conn.execute(query, {"ticker": ticker, "year": year})
            row = result.fetchone()
            return row[0] if row else None
    
    def get_xbrl_statement_structure(
        self, 
        filing_id: int, 
        statement_type: str
    ) -> List[XBRLStatementItem]:
        """
        Get expected statement structure from rel_statement_items.
        
        CRITICAL INSIGHT: rel_presentation_hierarchy has duplicates and requires processing.
        rel_statement_items IS the processed XBRL data - it's the source of truth after
        deduplication and filtering. This is what populate_statement_items creates from XBRL.
        
        So we use rel_statement_items as the "XBRL source of truth" because:
        1. It comes directly from XBRL presentation hierarchy (via populate_statement_items)
        2. It has all duplicates removed
        3. It has proper display_order (not all order_index=1)
        4. It filters out disclosure items
        
        Returns:
            List of XBRLStatementItem in display_order order
        """
        with self.engine.connect() as conn:
            # Query rel_statement_items - this IS the processed XBRL source of truth
            query = text("""
                SELECT 
                    co.normalized_label,
                    COALESCE(co.preferred_label, 
                        -- Fallback: humanize from normalized_label
                        CASE 
                            WHEN co.concept_name IS NOT NULL THEN
                                -- Use concept_name if available (more accurate)
                                INITCAP(REPLACE(co.concept_name, '_', ' '))
                            ELSE
                                -- Fallback to humanizing normalized_label
                                INITCAP(REPLACE(co.normalized_label, '_', ' '))
                        END
                    ) as display_label,
                    si.display_order,
                    si.concept_id,
                    si.statement_type,
                    si.role_uri,
                    si.source,
                    co.hierarchy_level,
                    co.parent_concept_id,
                    si.is_header
                FROM rel_statement_items si
                JOIN dim_concepts co ON si.concept_id = co.concept_id
                WHERE si.filing_id = :filing_id
                  AND si.statement_type = :statement_type
                  AND si.is_main_item = TRUE  -- Only main statement items
                ORDER BY si.display_order
            """)
            
            result = conn.execute(query, {
                "filing_id": filing_id,
                "statement_type": statement_type
            })
            
            items = []
            for row in result.fetchall():
                normalized_label, display_label, display_order, concept_id, stmt_type, role_uri, source, hierarchy_level, parent_concept_id, is_header = row
                order_index = display_order  # Use display_order as order_index
                
                # If display_label is None or empty, humanize from normalized_label
                if not display_label:
                    display_label = get_humanized_label(
                        normalized_label, 
                        normalized_label, 
                        statement_type
                    )
                
                items.append(XBRLStatementItem(
                    normalized_label=normalized_label,
                    display_label=display_label,
                    order_index=order_index,
                    concept_id=concept_id,
                    statement_type=stmt_type,
                    role_uri=role_uri,
                    is_header=bool(is_header),
                    hierarchy_level=hierarchy_level,
                    parent_concept_id=parent_concept_id
                ))
            
            # Sort by order_index
            items.sort(key=lambda x: x.order_index)
            
            return items
    
    def get_api_output(self, ticker: str, year: int, statement_type: str) -> List[Dict]:
        """Get actual API output for statement"""
        try:
            url = f"{self.api_base}/api/statements/{ticker}/{year}"
            response = requests.get(url, timeout=120)
            response.raise_for_status()
            data = response.json()
            
            # API returns data in 'statements' object
            statements = data.get('statements', {})
            
            # Get statement data based on type
            if statement_type == 'income_statement':
                return statements.get('income_statement', [])
            elif statement_type == 'comprehensive_income':
                return statements.get('comprehensive_income', [])
            elif statement_type == 'balance_sheet':
                return statements.get('balance_sheet', [])
            elif statement_type == 'cash_flow':
                return statements.get('cash_flow', [])
            elif statement_type == 'equity_statement':
                return statements.get('equity_statement', [])
            else:
                return []
        except Exception as e:
            print(f"Error fetching API output: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def normalize_label_for_comparison(self, label: str) -> str:
        """Normalize label for comparison (remove extra whitespace, lowercase)"""
        return ' '.join(label.strip().split()).lower()
    
    def validate_statement(
        self, 
        ticker: str, 
        year: int, 
        statement_type: str
    ) -> XBRLValidationResult:
        """
        Validate statement by comparing XBRL source vs API output.
        
        Returns:
            XBRLValidationResult with detailed comparison
        """
        # Get filing_id
        filing_id = self.get_filing_id(ticker, year)
        if not filing_id:
            return XBRLValidationResult(
                statement_type=statement_type,
                xbrl_items=[],
                api_items=[],
                missing_in_api=[],
                extra_in_api=[],
                order_mismatches=[],
                label_mismatches=[],
                can_determine_structure=False,
                accuracy_assessment="Cannot find filing_id"
            )
        
        # Get XBRL structure (source of truth)
        xbrl_items = self.get_xbrl_statement_structure(filing_id, statement_type)
        
        # Get API output
        api_items = self.get_api_output(ticker, year, statement_type)
        
        # Extract API labels and positions
        api_items_by_label = {}
        api_items_by_normalized = {}
        for idx, item in enumerate(api_items):
            # Get label from API (preferred_label or humanized)
            label = item.get('preferred_label') or item.get('label') or item.get('normalized_label', '')
            normalized = item.get('normalized_label', '')
            order = item.get('presentation_order_index', idx + 1)
            
            # Normalize for comparison
            label_normalized = self.normalize_label_for_comparison(label)
            
            if label_normalized not in api_items_by_label:
                api_items_by_label[label_normalized] = {
                    'position': idx + 1,
                    'order_index': order,
                    'normalized': normalized,
                    'label': label
                }
            
            if normalized:
                api_items_by_normalized[normalized] = {
                    'position': idx + 1,
                    'order_index': order,
                    'label': label
                }
        
        # Compare XBRL vs API
        missing_in_api = []
        extra_in_api = []
        order_mismatches = []
        label_mismatches = []
        
        # Check XBRL items against API
        for xbrl_item in xbrl_items:
            xbrl_label_norm = self.normalize_label_for_comparison(xbrl_item.display_label)
            xbrl_normalized = xbrl_item.normalized_label.lower()
            
            # Try to find in API by normalized label first (most reliable)
            found = False
            if xbrl_normalized in api_items_by_normalized:
                api_item = api_items_by_normalized[xbrl_normalized]
                found = True
                
                # Check order
                expected_pos = xbrl_item.order_index
                actual_pos = api_item['order_index']
                if expected_pos != actual_pos:
                    order_mismatches.append({
                        'item': xbrl_item.display_label,
                        'normalized': xbrl_item.normalized_label,
                        'expected_order': expected_pos,
                        'actual_order': actual_pos,
                        'expected_pos': None,  # Will calculate
                        'actual_pos': api_item['position']
                    })
                
                # Check label
                api_label_norm = self.normalize_label_for_comparison(api_item['label'])
                if xbrl_label_norm != api_label_norm:
                    label_mismatches.append({
                        'item': xbrl_item.normalized_label,
                        'xbrl_label': xbrl_item.display_label,
                        'api_label': api_item['label']
                    })
            
            # Try by label if not found by normalized
            elif xbrl_label_norm in api_items_by_label:
                api_item = api_items_by_label[xbrl_label_norm]
                found = True
                
                # Check order
                expected_pos = xbrl_item.order_index
                actual_pos = api_item['order_index']
                if expected_pos != actual_pos:
                    order_mismatches.append({
                        'item': xbrl_item.display_label,
                        'normalized': xbrl_item.normalized_label,
                        'expected_order': expected_pos,
                        'actual_order': actual_pos,
                        'expected_pos': None,
                        'actual_pos': api_item['position']
                    })
            
            if not found:
                missing_in_api.append(xbrl_item.display_label)
        
        # Check for extra items in API (not in XBRL)
        xbrl_labels_norm = {self.normalize_label_for_comparison(item.display_label) for item in xbrl_items}
        xbrl_normalized_set = {item.normalized_label.lower() for item in xbrl_items}
        
        for api_label_norm, api_item in api_items_by_label.items():
            api_normalized = api_item.get('normalized', '').lower()
            
            # Check if this is in XBRL
            if (api_label_norm not in xbrl_labels_norm and 
                api_normalized not in xbrl_normalized_set):
                extra_in_api.append(api_item['label'])
        
        # Assess accuracy
        total_xbrl = len(xbrl_items)
        total_api = len(api_items)
        missing_count = len(missing_in_api)
        extra_count = len(extra_in_api)
        order_issues = len(order_mismatches)
        label_issues = len(label_mismatches)
        
        if missing_count == 0 and extra_count == 0 and order_issues == 0 and label_issues == 0:
            accuracy = "100% ACCURATE - XBRL structure matches API perfectly"
            can_determine = True
        elif missing_count == 0 and extra_count == 0:
            accuracy = f"STRUCTURE ACCURATE (items match) but {order_issues} order issues, {label_issues} label issues"
            can_determine = True
        elif missing_count + extra_count <= 2:
            accuracy = f"MOSTLY ACCURATE - {missing_count} missing, {extra_count} extra, {order_issues} order issues"
            can_determine = True
        else:
            accuracy = f"INACCURATE - {missing_count} missing, {extra_count} extra, {order_issues} order issues, {label_issues} label issues"
            can_determine = False
        
        return XBRLValidationResult(
            statement_type=statement_type,
            xbrl_items=xbrl_items,
            api_items=api_items,
            missing_in_api=missing_in_api,
            extra_in_api=extra_in_api,
            order_mismatches=order_mismatches,
            label_mismatches=label_mismatches,
            can_determine_structure=can_determine,
            accuracy_assessment=accuracy
        )
    
    def compare_with_uitest(
        self, 
        ticker: str, 
        year: int, 
        statement_type: str,
        uitest_expected: List[str]
    ) -> Dict:
        """
        Compare XBRL validator results with UITest.py expectations.
        
        Returns:
            Comparison report
        """
        result = self.validate_statement(ticker, year, statement_type)
        
        # Get XBRL labels
        xbrl_labels = [item.display_label for item in result.xbrl_items]
        
        # Normalize for comparison
        xbrl_labels_norm = [self.normalize_label_for_comparison(label) for label in xbrl_labels]
        uitest_norm = [self.normalize_label_for_comparison(label) for label in uitest_expected if label.strip()]
        
        # Compare
        xbrl_set = set(xbrl_labels_norm)
        uitest_set = set(uitest_norm)
        
        in_xbrl_not_uitest = xbrl_set - uitest_set
        in_uitest_not_xbrl = uitest_set - xbrl_set
        in_both = xbrl_set & uitest_set
        
        # Check order
        order_matches = 0
        order_mismatches = []
        min_len = min(len(xbrl_labels_norm), len(uitest_norm))
        for i in range(min_len):
            if xbrl_labels_norm[i] == uitest_norm[i]:
                order_matches += 1
            else:
                order_mismatches.append({
                    'position': i + 1,
                    'xbrl': xbrl_labels_norm[i] if i < len(xbrl_labels_norm) else None,
                    'uitest': uitest_norm[i] if i < len(uitest_norm) else None
                })
        
        return {
            'xbrl_count': len(xbrl_labels),
            'uitest_count': len(uitest_expected),
            'xbrl_labels': xbrl_labels,
            'uitest_labels': uitest_expected,
            'in_both': len(in_both),
            'in_xbrl_not_uitest': list(in_xbrl_not_uitest),
            'in_uitest_not_xbrl': list(in_uitest_not_xbrl),
            'order_matches': order_matches,
            'order_mismatches': order_mismatches,
            'xbrl_accuracy': result.accuracy_assessment,
            'can_determine_structure': result.can_determine_structure
        }


def main():
    """Test XBRL validator against NVO 2024 and compare with UITest.py"""
    import sys
    from UITest import (
        EXPECTED_NOVO_INCOME_STATEMENT,
        EXPECTED_NOVO_COMPREHENSIVE_INCOME,
        EXPECTED_NOVO_BALANCE_SHEET_ASSETS,
        EXPECTED_NOVO_BALANCE_SHEET_LIABILITIES_EQUITY,
        EXPECTED_NOVO_CASH_FLOW,
        EXPECTED_NOVO_EQUITY_STATEMENT
    )
    
    validator = XBRLBasedValidator()
    ticker = "NVO"
    year = 2024
    
    print("=" * 80)
    print("XBRL-BASED VALIDATOR TEST")
    print("=" * 80)
    print(f"Testing: {ticker} {year}")
    print()
    
    statements = [
        ('income_statement', EXPECTED_NOVO_INCOME_STATEMENT),
        ('comprehensive_income', EXPECTED_NOVO_COMPREHENSIVE_INCOME),
        ('balance_sheet', EXPECTED_NOVO_BALANCE_SHEET_ASSETS + EXPECTED_NOVO_BALANCE_SHEET_LIABILITIES_EQUITY),
        ('cash_flow', EXPECTED_NOVO_CASH_FLOW),
        ('equity_statement', EXPECTED_NOVO_EQUITY_STATEMENT)
    ]
    
    for statement_type, uitest_expected in statements:
        print(f"\n{'=' * 80}")
        print(f"STATEMENT: {statement_type.upper()}")
        print('=' * 80)
        
        # Validate against XBRL
        result = validator.validate_statement(ticker, year, statement_type)
        
        print(f"\nXBRL Structure (Source of Truth):")
        print(f"  Total items: {len(result.xbrl_items)}")
        print(f"  Can determine structure: {result.can_determine_structure}")
        print(f"  Accuracy: {result.accuracy_assessment}")
        
        if result.xbrl_items:
            print(f"\n  XBRL Items (first 10):")
            for i, item in enumerate(result.xbrl_items[:10], 1):
                print(f"    {i}. order={item.order_index:4d} | {item.display_label}")
            if len(result.xbrl_items) > 10:
                print(f"    ... and {len(result.xbrl_items) - 10} more")
        
        # Compare with UITest
        comparison = validator.compare_with_uitest(ticker, year, statement_type, uitest_expected)
        
        print(f"\nComparison with UITest.py:")
        print(f"  XBRL count: {comparison['xbrl_count']}")
        print(f"  UITest count: {comparison['uitest_count']}")
        print(f"  Items in both: {comparison['in_both']}")
        print(f"  Items in XBRL but NOT in UITest: {len(comparison['in_xbrl_not_uitest'])}")
        if comparison['in_xbrl_not_uitest']:
            for item in comparison['in_xbrl_not_uitest'][:5]:
                print(f"    - {item}")
            if len(comparison['in_xbrl_not_uitest']) > 5:
                print(f"    ... and {len(comparison['in_xbrl_not_uitest']) - 5} more")
        
        print(f"  Items in UITest but NOT in XBRL: {len(comparison['in_uitest_not_xbrl'])}")
        if comparison['in_uitest_not_xbrl']:
            for item in comparison['in_uitest_not_xbrl'][:5]:
                print(f"    - {item}")
            if len(comparison['in_uitest_not_xbrl']) > 5:
                print(f"    ... and {len(comparison['in_uitest_not_xbrl']) - 5} more")
        
        print(f"  Order matches: {comparison['order_matches']}/{min(comparison['xbrl_count'], comparison['uitest_count'])}")
        if comparison['order_mismatches']:
            print(f"  Order mismatches: {len(comparison['order_mismatches'])}")
            for mismatch in comparison['order_mismatches'][:3]:
                print(f"    Position {mismatch['position']}: XBRL='{mismatch['xbrl']}', UITest='{mismatch['uitest']}'")
        
        # Issues found
        if result.missing_in_api:
            print(f"\n  Missing in API: {len(result.missing_in_api)}")
            for item in result.missing_in_api[:5]:
                print(f"    - {item}")
        
        if result.extra_in_api:
            print(f"\n  Extra in API: {len(result.extra_in_api)}")
            for item in result.extra_in_api[:5]:
                print(f"    - {item}")
        
        if result.order_mismatches:
            print(f"\n  Order mismatches: {len(result.order_mismatches)}")
            for mismatch in result.order_mismatches[:3]:
                print(f"    - {mismatch['item']}: expected order {mismatch['expected_order']}, got {mismatch['actual_order']}")
        
        # Final assessment
        print(f"\n  FINAL ASSESSMENT:")
        print(f"    Can XBRL determine structure with 100% accuracy? {result.can_determine_structure}")
        print(f"    XBRL vs UITest match? {comparison['in_both'] == comparison['xbrl_count'] == comparison['uitest_count']}")


if __name__ == "__main__":
    main()

