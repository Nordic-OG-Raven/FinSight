#!/usr/bin/env python3
"""
Validation Aggregator

Unified validation system that collects ALL actual issues from existing validators.
No arbitrary scores - just lists what's wrong and needs fixing.

This prevents the "fix one thing, break another" problem by:
1. Running ALL validations before/after each fix
2. Listing all issues clearly
3. Comparing before/after to detect new issues (regressions)

Usage:
    aggregator = ValidationAggregator()
    before = aggregator.collect_all_issues(filing_id)
    # ... apply fix ...
    after = aggregator.collect_all_issues(filing_id)
    comparison = aggregator.compare_issues(before, after)
    if comparison.new_issues:
        print(f"⚠️ {len(comparison.new_issues)} new issues detected!")
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from config import DATABASE_URI


@dataclass
class ValidationIssue:
    """Single validation issue - what's wrong and needs fixing"""
    category: str  # e.g., 'accounting_identity', 'missing_data', 'value_mismatch'
    statement_type: Optional[str]  # 'income_statement', 'balance_sheet', etc.
    issue: str  # Clear description of what's wrong
    details: Dict = field(default_factory=dict)  # Additional context
    
    def __str__(self) -> str:
        """Human-readable format"""
        stmt = f"[{self.statement_type}] " if self.statement_type else ""
        return f"{stmt}{self.issue}"
    
    def __hash__(self) -> int:
        """Make hashable for set operations"""
        return hash((self.category, self.statement_type, self.issue))
    
    def __eq__(self, other) -> bool:
        """Equality based on category, statement_type, and issue"""
        if not isinstance(other, ValidationIssue):
            return False
        return (self.category == other.category and
                self.statement_type == other.statement_type and
                self.issue == other.issue)


@dataclass
class ValidationResult:
    """Complete validation result - just a list of issues"""
    filing_id: int
    ticker: str
    year: int
    timestamp: datetime
    issues: List[ValidationIssue] = field(default_factory=list)
    
    def get_issues_by_category(self) -> Dict[str, List[ValidationIssue]]:
        """Group issues by category"""
        grouped = {}
        for issue in self.issues:
            if issue.category not in grouped:
                grouped[issue.category] = []
            grouped[issue.category].append(issue)
        return grouped
    
    def get_issues_by_statement(self) -> Dict[str, List[ValidationIssue]]:
        """Group issues by statement type"""
        grouped = {}
        for issue in self.issues:
            stmt = issue.statement_type or 'other'
            if stmt not in grouped:
                grouped[stmt] = []
            grouped[stmt].append(issue)
        return grouped


@dataclass
class ValidationComparison:
    """Comparison between two validation results"""
    new_issues: List[ValidationIssue]  # Issues that appeared after fix
    fixed_issues: List[ValidationIssue]  # Issues that were fixed
    unchanged_issues: List[ValidationIssue]  # Issues that still exist


class ValidationAggregator:
    """
    Collects ALL actual issues from existing validators.
    No scores - just lists what's wrong and needs fixing.
    
    This prevents the "fix one thing, break another" problem by:
    1. Running ALL validations before/after each fix
    2. Listing all issues clearly
    3. Comparing before/after to detect new issues (regressions)
    """
    
    def __init__(self):
        self.engine = create_engine(DATABASE_URI)
    
    def collect_all_issues(
        self,
        filing_id: Optional[int] = None,
        ticker: Optional[str] = None,
        year: Optional[int] = None
    ) -> ValidationResult:
        """
        Collect ALL actual issues from existing validators.
        
        Args:
            filing_id: Specific filing to validate (if None, validates all)
            ticker: Company ticker (used if filing_id not provided)
            year: Fiscal year (used if filing_id not provided)
        
        Returns:
            ValidationResult with list of actual issues
        """
        # Get filing info
        if filing_id:
            filing_info = self._get_filing_info(filing_id)
        elif ticker and year:
            filing_id = self._get_filing_id(ticker, year)
            filing_info = self._get_filing_info(filing_id)
        else:
            raise ValueError("Must provide either filing_id or (ticker, year)")
        
        result = ValidationResult(
            filing_id=filing_id,
            ticker=filing_info['ticker'],
            year=filing_info['year'],
            timestamp=datetime.now(),
            issues=[]
        )
        
        # Collect issues from DatabaseValidator
        result.issues.extend(self._collect_database_validation_issues(filing_id))
        
        # Check for loading errors (Priority 1)
        result.issues.extend(self._check_loading_errors(filing_id))
        
        # Collect issues from UITest.py
        result.issues.extend(self._collect_ui_test_issues(filing_id, ticker=filing_info['ticker'], year=filing_info['year']))
        
        return result
    
    def compare_issues(
        self,
        before: ValidationResult,
        after: ValidationResult
    ) -> ValidationComparison:
        """
        Compare two validation results to detect regressions.
        
        Args:
            before: Validation result before fix
            after: Validation result after fix
        
        Returns:
            ValidationComparison showing what changed
        """
        if before.filing_id != after.filing_id:
            raise ValueError("Cannot compare validations for different filings")
        
        before_issues = set(before.issues)
        after_issues = set(after.issues)
        
        new_issues = list(after_issues - before_issues)
        fixed_issues = list(before_issues - after_issues)
        unchanged_issues = list(after_issues & before_issues)
        
        return ValidationComparison(
            new_issues=new_issues,
            fixed_issues=fixed_issues,
            unchanged_issues=unchanged_issues
        )
    
    def _collect_database_validation_issues(self, filing_id: int) -> List[ValidationIssue]:
        """Collect issues from DatabaseValidator"""
        issues = []
        
        try:
            from src.validation.validator import DatabaseValidator
            
            validator = DatabaseValidator()
            report = validator.validate_all()
            
            for result in report.results:
                if not result.passed:
                    # Extract statement type from rule name if possible
                    statement_type = None
                    rule_lower = result.rule_name.lower()
                    if 'income' in rule_lower or 'comprehensive' in rule_lower:
                        statement_type = 'income_statement'
                    elif 'balance' in rule_lower:
                        statement_type = 'balance_sheet'
                    elif 'cash' in rule_lower or 'cashflow' in rule_lower:
                        statement_type = 'cash_flow'
                    elif 'equity' in rule_lower:
                        statement_type = 'equity_statement'
                    
                    issues.append(ValidationIssue(
                        category='database_validation',
                        statement_type=statement_type,
                        issue=f"{result.rule_name}: {result.message}",
                        details={
                            'severity': result.severity,
                            'rule_name': result.rule_name
                        }
                    ))
        except Exception as e:
            issues.append(ValidationIssue(
                category='validation_error',
                statement_type=None,
                issue=f"Failed to run database validation: {str(e)}",
                details={'error': str(e)}
            ))
        
        return issues
    
    def _collect_ui_test_issues(self, filing_id: int, ticker: str, year: int) -> List[ValidationIssue]:
        """Collect issues from ui_test.py (universal UI test)"""
        issues = []
        
        try:
            # Import new universal UI test module
            from src.validation.ui_test import UniversalUITest
            
            tester = UniversalUITest(api_base='http://localhost:5001')
            report = tester.test_company(ticker, year)
            
            # Extract issues from ValidationReport
            for result in report.results:
                if not result.passed or result.details:
                    statement_type = result.rule_name.replace('_validation', '')
                    
                    # Check order issues - create ONE issue per order problem
                    if result.details and result.details.get('order_issues'):
                        order_issues = result.details['order_issues']
                        for order_issue in order_issues:
                            issues.append(ValidationIssue(
                                category='ui_test',
                                statement_type=statement_type,
                                issue=f"Order issue: {order_issue.get('item', 'unknown')} - expected position {order_issue.get('expected_pos')}, actual position {order_issue.get('actual_pos')}",
                                details=order_issue
                            ))
                    
                    # Check missing items - create ONE issue per missing item
                    if result.details and result.details.get('missing_labels'):
                        missing_labels = result.details['missing_labels']
                        for missing_label in missing_labels:
                            issues.append(ValidationIssue(
                                category='ui_test',
                                statement_type=statement_type,
                                issue=f"Missing item: {missing_label}",
                                details={'missing_label': missing_label}
                            ))
                    
                    # Check missing values (items with no data for any year)
                    if result.details and result.details.get('missing_values'):
                            missing_values = result.details['missing_values']
                            # Check if these are actionable (data exists in fact_financial_metrics)
                            actionable_missing = self._check_if_missing_values_are_actionable(
                                filing_id, missing_values, statement_type
                            )
                            if actionable_missing:
                                # Create ONE issue per actionable missing value
                                for missing_value in actionable_missing:
                                    issues.append(ValidationIssue(
                                        category='ui_test',
                                        statement_type=statement_type,
                                        issue=f"PIPELINE BUG: {missing_value} - data exists in fact_financial_metrics but not in statement table",
                                        details={'missing_value': missing_value, 'severity': 'ERROR'}
                                    ))
                            elif missing_values:
                                # CRITICAL: Main statement items (like cash_and_equivalents) are REQUIRED by law
                                # Check if any missing values are main statement items that must be present
                                critical_missing = self._check_if_critical_main_items(
                                    filing_id, missing_values, statement_type
                                )
                                if critical_missing:
                                    # Create ONE issue per critical missing value
                                    for missing_value in critical_missing:
                                        issues.append(ValidationIssue(
                                            category='ui_test',
                                            statement_type=statement_type,
                                            issue=f"CRITICAL: {missing_value} - REQUIRED BY LAW (main statement item) but missing data",
                                            details={'missing_value': missing_value, 'severity': 'ERROR'}
                                        ))
                                else:
                                    # Create ONE issue per missing value
                                    for missing_value in missing_values:
                                        issues.append(ValidationIssue(
                                            category='ui_test',
                                            statement_type=statement_type,
                                            issue=f"Missing data: {missing_value} (data not in fact_financial_metrics - may be expected)",
                                            details={'missing_value': missing_value, 'severity': 'WARNING'}
                                        ))
                    
                    # Check value mismatches - create ONE issue per mismatch
                    if result.details and result.details.get('value_mismatches'):
                        value_mismatches = result.details['value_mismatches']
                        for mismatch in value_mismatches:
                            item = mismatch.get('item', 'unknown')
                            year = mismatch.get('year', 'unknown')
                            expected = mismatch.get('expected')
                            actual = mismatch.get('actual')
                            diff = mismatch.get('diff', 0)
                            issues.append(ValidationIssue(
                                category='ui_test',
                                statement_type=statement_type,
                                issue=f"Value mismatch: {item} ({year}) - expected {expected}, got {actual} (diff: {diff})",
                                details=mismatch
                            ))
            
        except Exception as e:
            issues.append(ValidationIssue(
                category='validation_error',
                statement_type=None,
                issue=f"Failed to run UI tests: {str(e)}",
                details={'error': str(e)}
            ))
        
        return issues
    
    def _check_if_missing_values_are_actionable(self, filing_id: int, missing_values: List[str], statement_type: str) -> List[str]:
        """
        Check if missing values are actionable (pipeline bug) vs expected (data not in source).
        Returns only items where data EXISTS in fact_financial_metrics but is MISSING from statement table.
        """
        actionable = []
        
        try:
            with self.engine.connect() as conn:
                # Map statement type to table
                table_map = {
                    'income_statement': 'fact_income_statement',
                    'balance_sheet': 'fact_balance_sheet',
                    'cash_flow': 'fact_cash_flow',
                    'equity_statement': 'fact_equity_statement',
                    'comprehensive_income': 'fact_comprehensive_income'
                }
                statement_table = table_map.get(statement_type)
                if not statement_table:
                    return []  # Can't check, return empty
                
                for normalized_label in missing_values:
                    # Check if data exists in fact_financial_metrics for this item
                    concept_query = text("""
                        SELECT concept_id FROM dim_concepts 
                        WHERE normalized_label = :normalized_label
                        LIMIT 1
                    """)
                    concept_result = conn.execute(concept_query, {'normalized_label': normalized_label})
                    concept_row = concept_result.fetchone()
                    if not concept_row:
                        continue  # Concept not found, skip
                    concept_id = concept_row[0]
                    
                    # Check if data exists in fact_financial_metrics
                    fact_query = text("""
                        SELECT COUNT(*) 
                        FROM fact_financial_metrics fm
                        JOIN dim_filings f ON fm.filing_id = f.filing_id
                        WHERE f.filing_id = :filing_id
                          AND fm.concept_id = :concept_id
                          AND fm.value_numeric IS NOT NULL
                    """)
                    fact_result = conn.execute(fact_query, {
                        'filing_id': filing_id,
                        'concept_id': concept_id
                    })
                    fact_count = fact_result.fetchone()[0]
                    
                    if fact_count > 0:
                        # Data exists in fact_financial_metrics - this is actionable
                        actionable.append(normalized_label)
        
        except Exception as e:
            logger.warning(f"Error checking actionable missing values: {e}")
        
        return actionable
    
    def _check_if_critical_main_items(self, filing_id: int, missing_values: List[str], statement_type: str) -> List[str]:
        """
        Check if missing values are critical main statement items that are REQUIRED BY LAW.
        Returns only items that are main statement items and must be present.
        """
        critical = []
        
        # Critical items that MUST be present in each statement type
        critical_items = {
            'cash_flow': [
                'cash_and_equivalents',
                'cash_and_cash_equivalents',
                'cash_and_cash_equivalents_at_the_end_of_the_year',
                'cash_at_bank',
                'balances_with_banks'
            ],
            'balance_sheet': [
                'total_assets',
                'assets_total',
                'total_liabilities',
                'liabilities_total',
                'total_equity',
                'equity_total',
                'total_equity_and_liabilities'
            ],
            'income_statement': [
                'revenue',
                'total_revenue',
                'net_income',
                'net_income_loss',
                'profit_loss'
            ]
        }
        
        critical_list = critical_items.get(statement_type, [])
        
        for normalized_label in missing_values:
            # Check if it's a critical item
            if any(critical_item in normalized_label.lower() for critical_item in critical_list):
                critical.append(normalized_label)
            # Also check if it's marked as a main item in rel_statement_items
            else:
                try:
                    with self.engine.connect() as conn:
                        query = text("""
                            SELECT COUNT(*) 
                            FROM rel_statement_items si
                            JOIN dim_concepts co ON si.concept_id = co.concept_id
                            JOIN dim_filings f ON si.filing_id = f.filing_id
                            WHERE f.filing_id = :filing_id
                              AND si.statement_type = :statement_type
                              AND si.is_main_item = TRUE
                              AND co.normalized_label = :normalized_label
                        """)
                        result = conn.execute(query, {
                            'filing_id': filing_id,
                            'statement_type': statement_type,
                            'normalized_label': normalized_label
                        })
                        count = result.fetchone()[0]
                        if count > 0:
                            critical.append(normalized_label)
                except Exception as e:
                    logger.warning(f"Error checking critical main items: {e}")
        
        return critical
    
    def _check_if_missing_years_are_actionable(self, filing_id: int, year_issues: List[Dict], statement_type: str) -> List[Dict]:
        """
        Check if missing years are actionable (pipeline bug) vs expected (data not in source).
        Returns only issues where data EXISTS in fact_financial_metrics but is MISSING from statement table.
        """
        actionable = []
        
        try:
            with self.engine.connect() as conn:
                # Map statement type to table
                table_map = {
                    'income_statement': 'fact_income_statement',
                    'balance_sheet': 'fact_balance_sheet',
                    'cash_flow': 'fact_cash_flow',
                    'equity_statement': 'fact_equity_statement',
                    'comprehensive_income': 'fact_comprehensive_income'
                }
                statement_table = table_map.get(statement_type)
                if not statement_table:
                    return year_issues  # Can't check, return all
                
                for issue in year_issues:
                    item_label = issue.get('item') or issue.get('normalized', '')
                    missing_years = issue.get('missing_years', [])
                    
                    if not item_label or not missing_years:
                        continue
                    
                    # Check if data exists in fact_financial_metrics for this item and missing years
                    for year in missing_years:
                        # Find concept_id for this normalized label
                        concept_query = text("""
                            SELECT concept_id FROM dim_concepts 
                            WHERE normalized_label = :label 
                            LIMIT 1
                        """)
                        concept_result = conn.execute(concept_query, {'label': item_label})
                        concept_row = concept_result.fetchone()
                        
                        if concept_row:
                            concept_id = concept_row[0]
                            # Check if data exists in fact_financial_metrics
                            fact_query = text("""
                                SELECT COUNT(*) FROM fact_financial_metrics fm
                                JOIN dim_time_periods tp ON fm.period_id = tp.period_id
                                WHERE fm.filing_id = :filing_id
                                  AND fm.concept_id = :concept_id
                                  AND tp.fiscal_year = :year
                                  AND fm.value_numeric IS NOT NULL
                            """)
                            fact_result = conn.execute(fact_query, {
                                'filing_id': filing_id,
                                'concept_id': concept_id,
                                'year': year
                            })
                            fact_count = fact_result.fetchone()[0]
                            
                            # Check if data is missing from statement table
                            if fact_count > 0:
                                stmt_query = text(f"""
                                    SELECT COUNT(*) FROM {statement_table} stmt
                                    JOIN dim_time_periods tp ON stmt.period_id = tp.period_id
                                    WHERE stmt.filing_id = :filing_id
                                      AND stmt.concept_id = :concept_id
                                      AND tp.fiscal_year = :year
                                """)
                                stmt_result = conn.execute(stmt_query, {
                                    'filing_id': filing_id,
                                    'concept_id': concept_id,
                                    'year': year
                                })
                                stmt_count = stmt_result.fetchone()[0]
                                
                                # If data exists in fact_financial_metrics but NOT in statement table = PIPELINE BUG
                                if stmt_count == 0:
                                    actionable.append(issue)
                                    break  # Only add once per issue
        except Exception as e:
            # If check fails, return all issues (better to be safe)
            return year_issues
        
        return actionable
    
    def _check_loading_errors(self, filing_id: int) -> List[ValidationIssue]:
        """Check for SQL/loading errors (Priority 1)"""
        issues = []
        
        try:
            with self.engine.connect() as conn:
                # Check if equity statement was populated
                result = conn.execute(text("""
                    SELECT COUNT(*) 
                    FROM fact_equity_statement 
                    WHERE filing_id = :filing_id
                """), {'filing_id': filing_id})
                equity_count = result.fetchone()[0]
                
                if equity_count == 0:
                    issues.append(ValidationIssue(
                        category='loading_error',
                        statement_type='equity_statement',
                        issue='fact_equity_statement is empty - loading may have failed',
                        details={'filing_id': filing_id, 'count': equity_count}
                    ))
                
                # Check if other statement tables are populated
                for table_name, statement_type in [
                    ('fact_income_statement', 'income_statement'),
                    ('fact_balance_sheet', 'balance_sheet'),
                    ('fact_cash_flow', 'cash_flow'),
                    ('fact_comprehensive_income', 'comprehensive_income')
                ]:
                    result = conn.execute(text(f"""
                        SELECT COUNT(*) 
                        FROM {table_name} 
                        WHERE filing_id = :filing_id
                    """), {'filing_id': filing_id})
                    count = result.fetchone()[0]
                    
                    if count == 0:
                        issues.append(ValidationIssue(
                            category='loading_error',
                            statement_type=statement_type,
                            issue=f'{table_name} is empty - loading may have failed',
                            details={'filing_id': filing_id, 'count': count}
                        ))
                
                # Check if fact_financial_metrics has data (base table)
                result = conn.execute(text("""
                    SELECT COUNT(*) 
                    FROM fact_financial_metrics 
                    WHERE filing_id = :filing_id
                """), {'filing_id': filing_id})
                base_count = result.fetchone()[0]
                
                if base_count == 0:
                    issues.append(ValidationIssue(
                        category='loading_error',
                        statement_type=None,
                        issue='fact_financial_metrics is empty - no data loaded at all',
                        details={'filing_id': filing_id, 'count': base_count}
                    ))
                    
        except Exception as e:
            issues.append(ValidationIssue(
                category='validation_error',
                statement_type=None,
                issue=f"Failed to check loading errors: {str(e)}",
                details={'error': str(e)}
            ))
        
        return issues
    
    def _get_filing_info(self, filing_id: int) -> Dict:
        """Get filing information"""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT c.ticker, EXTRACT(YEAR FROM f.fiscal_year_end)::INTEGER as year
                FROM dim_filings f
                JOIN dim_companies c ON f.company_id = c.company_id
                WHERE f.filing_id = :filing_id
            """), {'filing_id': filing_id})
            
            row = result.fetchone()
            if not row:
                raise ValueError(f"Filing {filing_id} not found")
            
            return {
                'ticker': row[0],
                'year': row[1]
            }
    
    def _get_filing_id(self, ticker: str, year: int) -> int:
        """Get filing_id from ticker and year"""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT f.filing_id
                FROM dim_filings f
                JOIN dim_companies c ON f.company_id = c.company_id
                WHERE c.ticker = :ticker
                  AND EXTRACT(YEAR FROM f.fiscal_year_end)::INTEGER = :year
                ORDER BY f.filing_id DESC
                LIMIT 1
            """), {'ticker': ticker, 'year': year})
            
            row = result.fetchone()
            if not row:
                raise ValueError(f"Filing not found for {ticker} {year}")
            
            return row[0]
    
    def print_validation_result(self, result: ValidationResult):
        """Print validation result in human-readable format"""
        print("\n" + "="*80)
        print(f"VALIDATION ISSUES: {result.ticker} {result.year}")
        print("="*80)
        print(f"Total Issues: {len(result.issues)}")
        print()
        
        if not result.issues:
            print("✅ No issues found!")
            print("="*80)
            return
        
        # Group by category
        by_category = result.get_issues_by_category()
        for category, category_issues in by_category.items():
            print(f"{category.upper()}:")
            for issue in category_issues:
                stmt = f" [{issue.statement_type}]" if issue.statement_type else ""
                print(f"  {stmt}: {issue.issue}")
            print()
        
        print("="*80)
    
    def print_comparison(self, comparison: ValidationComparison):
        """Print comparison in human-readable format"""
        print("\n" + "="*80)
        print("VALIDATION COMPARISON")
        print("="*80)
        
        if comparison.fixed_issues:
            print(f"✅ Fixed Issues ({len(comparison.fixed_issues)}):")
            for issue in comparison.fixed_issues[:10]:  # Show first 10
                stmt = f" [{issue.statement_type}]" if issue.statement_type else ""
                print(f"   - {issue.category}{stmt}: {issue.issue}")
            if len(comparison.fixed_issues) > 10:
                print(f"   ... and {len(comparison.fixed_issues) - 10} more")
            print()
        
        if comparison.new_issues:
            print(f"❌ New Issues ({len(comparison.new_issues)}):")
            for issue in comparison.new_issues[:10]:  # Show first 10
                stmt = f" [{issue.statement_type}]" if issue.statement_type else ""
                print(f"   + {issue.category}{stmt}: {issue.issue}")
            if len(comparison.new_issues) > 10:
                print(f"   ... and {len(comparison.new_issues) - 10} more")
            print()
        
        if comparison.unchanged_issues:
            print(f"➡️  Unchanged Issues ({len(comparison.unchanged_issues)}):")
            for issue in list(comparison.unchanged_issues)[:5]:  # Show first 5
                stmt = f" [{issue.statement_type}]" if issue.statement_type else ""
                print(f"   {issue.category}{stmt}: {issue.issue}")
            if len(comparison.unchanged_issues) > 5:
                print(f"   ... and {len(comparison.unchanged_issues) - 5} more")
            print()
        
        if not comparison.new_issues:
            print("✅ No regressions detected!")
        else:
            print("⚠️  Regressions detected - investigate before committing!")
        
        print("="*80)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Collect all validation issues')
    parser.add_argument('--ticker', required=True, help='Company ticker')
    parser.add_argument('--year', type=int, required=True, help='Fiscal year')
    
    args = parser.parse_args()
    
    aggregator = ValidationAggregator()
    result = aggregator.collect_all_issues(ticker=args.ticker, year=args.year)
    aggregator.print_validation_result(result)
