"""
Financial Validation Rules

Implements accounting identity checks and cross-statement validation.
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of a single validation rule"""
    rule_name: str
    passed: bool
    severity: str  # ERROR, WARNING, INFO
    message: str
    details: Optional[Dict[str, Any]] = None
    expected_value: Optional[float] = None
    actual_value: Optional[float] = None
    tolerance_pct: Optional[float] = None


@dataclass
class ValidationReport:
    """Complete validation report for a filing"""
    company: str
    filing_type: str
    fiscal_year_end: str
    results: List[ValidationResult] = field(default_factory=list)
    overall_score: float = 0.0
    passed: bool = False
    validation_timestamp: datetime = field(default_factory=datetime.now)
    
    def add_result(self, result: ValidationResult):
        """Add a validation result"""
        self.results.append(result)
    
    def calculate_score(self):
        """Calculate overall quality score (0-1)"""
        if not self.results:
            self.overall_score = 0.0
            return
        
        # Weight by severity
        total_weight = 0
        passed_weight = 0
        
        for result in self.results:
            if result.severity == 'ERROR':
                weight = 3
            elif result.severity == 'WARNING':
                weight = 2
            else:  # INFO
                weight = 1
            
            total_weight += weight
            if result.passed:
                passed_weight += weight
        
        self.overall_score = passed_weight / total_weight if total_weight > 0 else 0.0
        self.passed = self.overall_score >= 0.90  # 90% threshold
    
    def get_errors(self) -> List[ValidationResult]:
        """Get all ERROR severity results"""
        return [r for r in self.results if r.severity == "ERROR"]
    
    def get_warnings(self) -> List[ValidationResult]:
        """Get all WARNING severity results"""
        return [r for r in self.results if r.severity == "WARNING"]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'company': self.company,
            'filing_type': self.filing_type,
            'fiscal_year_end': self.fiscal_year_end,
            'overall_score': self.overall_score,
            'passed': self.passed,
            'total_rules': len(self.results),
            'passed_rules': sum(1 for r in self.results if r.passed),
            'errors': len(self.get_errors()),
            'warnings': len(self.get_warnings()),
            'results': [
                {
                    'rule': r.rule_name,
                    'passed': r.passed,
                    'severity': r.severity,
                    'message': r.message,
                    'details': r.details
                }
                for r in self.results
            ],
            'validation_timestamp': self.validation_timestamp.isoformat()
        }


class FinancialValidator:
    """Validate financial data using accounting identities and rules"""
    
    def __init__(self, tolerance_pct: float = 1.0):
        """
        Initialize validator
        
        Args:
            tolerance_pct: Tolerance percentage for checks (default 1%)
        """
        self.tolerance_pct = tolerance_pct
        self.stats = {
            'rules_run': 0,
            'rules_passed': 0,
            'rules_failed': 0
        }
    
    def validate_filing(
        self,
        facts: List[Dict[str, Any]],
        company: str,
        filing_type: str,
        fiscal_year_end: str
    ) -> ValidationReport:
        """
        Run all validation rules on a filing
        
        Args:
            facts: List of financial facts
            company: Company ticker
            filing_type: Filing type (10-K, 20-F, etc.)
            fiscal_year_end: Fiscal year end date
            
        Returns:
            ValidationReport with all results
        """
        report = ValidationReport(
            company=company,
            filing_type=filing_type,
            fiscal_year_end=fiscal_year_end
        )
        
        # Group facts by period for validation
        facts_by_period = self._group_by_period(facts)
        
        # Run validation rules for each period
        for period, period_facts in facts_by_period.items():
            # Balance Sheet equation
            balance_result = self._check_balance_sheet_equation(period_facts, period)
            if balance_result:
                report.add_result(balance_result)
            
            # EPS calculation
            eps_result = self._check_eps_calculation(period_facts, period)
            if eps_result:
                report.add_result(eps_result)
            
            # Cross-statement validation
            cross_result = self._check_cross_statement_consistency(period_facts, period)
            if cross_result:
                report.add_result(cross_result)
        
        # Data completeness checks
        completeness_results = self._check_completeness(facts)
        report.results.extend(completeness_results)
        
        # Duplicate detection
        duplicate_result = self._check_duplicates(facts)
        if duplicate_result:
            report.add_result(duplicate_result)
        
        # Calculate overall score
        report.calculate_score()
        
        return report
    
    def _group_by_period(self, facts: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group facts by reporting period - prioritize instant dates for balance sheet items"""
        grouped = {}
        
        for fact in facts:
            # Use instant_date for balance sheet items, period_end for others
            period = fact.get('instant_date') or fact.get('period_end')
            if period:
                period_key = str(period)
                if period_key not in grouped:
                    grouped[period_key] = []
                grouped[period_key].append(fact)
        
        return grouped
    
    def _check_balance_sheet_equation(
        self,
        facts: List[Dict[str, Any]],
        period: str
    ) -> Optional[ValidationResult]:
        """
        Check: Assets = Liabilities + Equity
        
        This is the fundamental accounting equation that must always hold.
        """
        # Filter for balance sheet items (instant date, not period)
        bs_facts = [f for f in facts if f.get('instant_date') == period]
        if not bs_facts:
            # Fallback to period_end if no instant dates
            bs_facts = facts
        
        # Find relevant concepts - prioritize exact matches for totals
        assets = self._find_concept_value(bs_facts, [
            'Assets',  # Exact match for total
            'AssetsTotal',
            'TotalAssets'
        ], exact_priority=True)
        
        # If no total assets found, try summing current + noncurrent
        if assets is None:
            current_assets = self._find_concept_value(bs_facts, ['AssetsCurrent', 'CurrentAssets'], exact_priority=True)
            noncurrent_assets = self._find_concept_value(bs_facts, ['AssetsNoncurrent', 'NoncurrentAssets'], exact_priority=True)
            if current_assets and noncurrent_assets:
                assets = current_assets + noncurrent_assets
        
        liabilities = self._find_concept_value(bs_facts, [
            'Liabilities',  # Exact match for total
            'LiabilitiesTotal',
            'TotalLiabilities'
        ], exact_priority=True)
        
        # If no total liabilities found, try summing current + noncurrent
        if liabilities is None:
            current_liab = self._find_concept_value(bs_facts, ['LiabilitiesCurrent'], exact_priority=True)
            noncurrent_liab = self._find_concept_value(bs_facts, ['LiabilitiesNoncurrent'], exact_priority=True)
            if current_liab and noncurrent_liab:
                liabilities = current_liab + noncurrent_liab
        
        equity = self._find_concept_value(bs_facts, [
            'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest',  # Total including NCI
            'Equity',  # IFRS
            'StockholdersEquity',  # US-GAAP
            'ShareholdersEquity',
            'TotalEquity',
            'EquityAttributableToOwnersOfParent'  # IFRS variant
        ], exact_priority=True)
        
        # If still no liabilities and we have assets and equity, calculate from equation
        # (Some companies don't report total liabilities explicitly)
        if liabilities is None and assets is not None and equity is not None:
            liabilities = assets - equity
        
        # Need all 3 values for a valid balance sheet check
        # (If we're missing any, this period doesn't have proper balance sheet data)
        if not (assets and liabilities and equity):
            return None
        
        # Calculate expected vs actual
        if assets and liabilities and equity:
            expected = liabilities + equity
            actual = assets
            diff = abs(actual - expected)
            diff_pct = (diff / actual * 100) if actual != 0 else 100
            
            passed = diff_pct <= self.tolerance_pct
            
            return ValidationResult(
                rule_name='balance_sheet_equation',
                passed=passed,
                severity='ERROR' if not passed else 'INFO',
                message=f"Balance Sheet Equation (Period: {period})",
                details={
                    'assets': float(assets),
                    'liabilities': float(liabilities),
                    'equity': float(equity),
                    'difference': float(diff),
                    'difference_pct': float(diff_pct)
                },
                expected_value=float(expected),
                actual_value=float(actual),
                tolerance_pct=self.tolerance_pct
            )
        
        return None
    
    def _check_eps_calculation(
        self,
        facts: List[Dict[str, Any]],
        period: str
    ) -> Optional[ValidationResult]:
        """
        Check: EPS ≈ Net Income / Weighted Average Shares
        
        Validates that reported EPS matches calculation from components.
        IMPORTANT: Must match Basic EPS with Basic shares, or Diluted EPS with Diluted shares
        """
        # Find net income - use EXACT matches only to avoid matching sub-components
        net_income = None
        ni_period = None
        for fact in facts:
            concept = fact.get('concept', '')
            # Exact match only for main net income
            if concept in ['NetIncomeLoss', 'NetIncome', 'ProfitLossAttributableToOwnersOfParent', 'ProfitLoss']:
                # Skip dimensional data
                if not fact.get('dimensions'):
                    # Check if this is for the period we're validating
                    period_end = fact.get('period_end', '')
                    # Convert to string for comparison
                    period_str = str(period) if period else ''
                    period_end_str = str(period_end) if period_end else ''
                    if period_str == period_end_str or period_str in period_end_str:
                        value = fact.get('value_numeric')
                        if value:
                            net_income = value
                            ni_period = period_end
                            break
        
        if not net_income:
            return None
        
        # Try Basic EPS calculation first - match same period
        basic_shares = None
        basic_eps = None
        
        for fact in facts:
            concept = fact.get('concept', '')
            period_end = str(fact.get('period_end', '')) if fact.get('period_end') else ''
            ni_period_str = str(ni_period) if ni_period else ''
            
            # Match shares for same period
            if concept == 'WeightedAverageNumberOfSharesOutstandingBasic':
                if period_end == ni_period_str and not fact.get('dimensions'):
                    basic_shares = fact.get('value_numeric')
            
            # Match EPS for same period
            if concept in ['EarningsPerShareBasic', 'BasicEarningsPerShare']:
                if period_end == ni_period_str and not fact.get('dimensions'):
                    basic_eps = fact.get('value_numeric')
        
        if basic_shares and basic_eps:
            calculated_eps = net_income / basic_shares if basic_shares != 0 else 0
            diff = abs(calculated_eps - basic_eps)
            diff_pct = (diff / abs(basic_eps) * 100) if basic_eps != 0 else 100
            
            # Allow 3% tolerance for EPS due to rounding in large numbers
            eps_tolerance = max(self.tolerance_pct, 3.0)
            passed = diff_pct <= eps_tolerance
            
            return ValidationResult(
                rule_name='eps_calculation',
                passed=passed,
                severity='WARNING' if not passed else 'INFO',
                message=f"EPS Calculation (Period: {period})",
                details={
                    'eps_type': 'Basic',
                    'net_income': float(net_income),
                    'shares': float(basic_shares),
                    'reported_eps': float(basic_eps),
                    'calculated_eps': float(calculated_eps),
                    'difference': float(diff),
                    'difference_pct': float(diff_pct)
                },
                expected_value=float(calculated_eps),
                actual_value=float(basic_eps),
                tolerance_pct=self.tolerance_pct
            )
        
        # Try Diluted EPS if Basic not available - match same period
        diluted_shares = None
        diluted_eps = None
        
        for fact in facts:
            concept = fact.get('concept', '')
            period_end = str(fact.get('period_end', '')) if fact.get('period_end') else ''
            ni_period_str = str(ni_period) if ni_period else ''
            
            # Match shares for same period
            if concept == 'WeightedAverageNumberOfDilutedSharesOutstanding':
                if period_end == ni_period_str and not fact.get('dimensions'):
                    diluted_shares = fact.get('value_numeric')
            
            # Match EPS for same period
            if concept in ['EarningsPerShareDiluted', 'DilutedEarningsPerShare']:
                if period_end == ni_period_str and not fact.get('dimensions'):
                    diluted_eps = fact.get('value_numeric')
        
        if diluted_shares and diluted_eps:
            calculated_eps = net_income / diluted_shares if diluted_shares != 0 else 0
            diff = abs(calculated_eps - diluted_eps)
            diff_pct = (diff / abs(diluted_eps) * 100) if diluted_eps != 0 else 100
            
            # Allow 3% tolerance for EPS due to rounding in large numbers
            eps_tolerance = max(self.tolerance_pct, 3.0)
            passed = diff_pct <= eps_tolerance
            
            return ValidationResult(
                rule_name='eps_calculation',
                passed=passed,
                severity='WARNING' if not passed else 'INFO',
                message=f"EPS Calculation (Period: {period})",
                details={
                    'eps_type': 'Diluted',
                    'net_income': float(net_income),
                    'shares': float(diluted_shares),
                    'reported_eps': float(diluted_eps),
                    'calculated_eps': float(calculated_eps),
                    'difference': float(diff),
                    'difference_pct': float(diff_pct)
                },
                expected_value=float(calculated_eps),
                actual_value=float(diluted_eps),
                tolerance_pct=self.tolerance_pct
            )
        
        # No EPS data available
        return None
    
    def _check_cross_statement_consistency(
        self,
        facts: List[Dict[str, Any]],
        period: str
    ) -> Optional[ValidationResult]:
        """
        Check that Net Income appears consistently across statements
        
        Net Income should be the same in Income Statement and Cash Flow Statement.
        """
        # Find net income - use EXACT concept names only
        # IMPORTANT: Don't mix ProfitLoss (total) with NetIncomeLoss (attributable to parent)
        # These are DIFFERENT concepts and SHOULD have different values!
        
        # Try NetIncomeLoss first (most common for US-GAAP, excludes noncontrolling interest)
        net_incomes = []
        
        for fact in facts:
            concept = fact.get('concept', '')
            # Only match NetIncomeLoss-related concepts (excludes ProfitLoss which includes noncontrolling interest)
            if concept in ['NetIncomeLoss', 'NetIncome', 
                          'ProfitLossAttributableToOwnersOfParent',
                          'NetIncomeLossAvailableToCommonStockholdersBasic']:
                # Filter for consolidated level only (no dimensions)
                # Skip any facts with dimensions (segments, equity components, etc.)
                dimensions = fact.get('dimensions', {})
                if dimensions:
                    continue
                
                value = fact.get('value_numeric')
                if value:
                    net_incomes.append(float(value))
        
        # If no NetIncomeLoss found, try ProfitLoss (IFRS standard)
        if len(net_incomes) < 2:
            for fact in facts:
                concept = fact.get('concept', '')
                if concept == 'ProfitLoss':
                    dimensions = fact.get('dimensions', {})
                    if dimensions:
                        continue
                    
                    value = fact.get('value_numeric')
                    if value:
                        net_incomes.append(float(value))
        
        if len(net_incomes) < 2:
            return None
        
        # Check if all values are similar
        min_val = min(net_incomes)
        max_val = max(net_incomes)
        diff = max_val - min_val
        diff_pct = (diff / max_val * 100) if max_val != 0 else 100
        
        passed = diff_pct <= self.tolerance_pct
        
        return ValidationResult(
            rule_name='cross_statement_consistency',
            passed=passed,
            severity='WARNING' if not passed else 'INFO',
            message=f"Cross-Statement Net Income Consistency (Period: {period})",
            details={
                'net_income_values': net_incomes,
                'min': min_val,
                'max': max_val,
                'difference': diff,
                'difference_pct': diff_pct
            },
            expected_value=min_val,
            actual_value=max_val,
            tolerance_pct=self.tolerance_pct
        )
    
    def _check_completeness(self, facts: List[Dict[str, Any]]) -> List[ValidationResult]:
        """Check for presence of critical concepts"""
        results = []
        
        critical_concepts = {
            'Revenue/Sales': ['Revenue', 'Revenues', 'SalesRevenueNet', 'RevenueFromContractWithCustomerExcludingAssessedTax'],
            'Net Income': ['NetIncomeLoss', 'ProfitLoss', 'NetIncome'],
            'Assets': ['Assets', 'AssetsTotal', 'TotalAssets'],
            'Equity': ['StockholdersEquity', 'Equity', 'ShareholdersEquity'],
            'Cash': ['Cash', 'CashAndCashEquivalentsAtCarryingValue', 'CashAndBankBalancesAtCentralBanks']
        }
        
        for category, concept_names in critical_concepts.items():
            found = self._find_concept_value(facts, concept_names)
            
            passed = found is not None
            
            results.append(ValidationResult(
                rule_name=f'has_{category.lower().replace("/", "_")}',
                passed=passed,
                severity='WARNING' if not passed else 'INFO',
                message=f"Critical Concept: {category}",
                details={'found': passed, 'searched_concepts': concept_names}
            ))
        
        return results
    
    def _check_duplicates(self, facts: List[Dict[str, Any]]) -> Optional[ValidationResult]:
        """Check for duplicate facts (same concept, period, dimensions, value)"""
        seen = {}
        duplicates = []
        
        for fact in facts:
            key = (
                fact.get('concept'),
                fact.get('period_end'),
                fact.get('instant_date'),
                str(fact.get('dimensions', {})),
                fact.get('value_text')
            )
            
            if key in seen:
                duplicates.append(fact.get('concept'))
            else:
                seen[key] = fact
        
        passed = len(duplicates) == 0
        
        return ValidationResult(
            rule_name='no_duplicates',
            passed=passed,
            severity='INFO',
            message="Duplicate Fact Detection",
            details={
                'duplicate_count': len(duplicates),
                'duplicate_concepts': list(set(duplicates))[:10]  # First 10
            }
        )
    
    def _find_concept_value(
        self,
        facts: List[Dict[str, Any]],
        concept_names: List[str],
        exact_priority: bool = False
    ) -> Optional[float]:
        """
        Find numeric value for a concept by name
        
        Args:
            facts: List of facts to search
            concept_names: List of concept names to search for
            exact_priority: If True, ONLY do exact matches (no fallback to partial)
        
        Returns:
            First matching numeric value found (consolidated only, no dimensions)
        """
        # First pass: try exact matches (iterate concept_names first for priority)
        for name in concept_names:
            for fact in facts:
                concept = fact.get('concept', '')
                
                # Skip facts with dimensions (we want consolidated totals only)
                if fact.get('dimensions'):
                    continue
                
                if concept == name or concept.lower() == name.lower():
                    value = fact.get('value_numeric')
                    if value is not None:
                        try:
                            result = float(value)
                            return result
                        except (ValueError, TypeError):
                            continue
        
        # If exact_priority is True, stop here - don't fallback to partial matches
        if exact_priority:
            return None
        
        # Second pass: partial matches (only if exact_priority is False)
        for fact in facts:
            concept = fact.get('concept', '')
            
            # Skip facts with dimensions (we want consolidated totals only)
            if fact.get('dimensions'):
                continue
            
            for name in concept_names:
                if name.lower() in concept.lower():
                    value = fact.get('value_numeric')
                    if value is not None:
                        try:
                            return float(value)
                        except (ValueError, TypeError):
                            continue
        
        return None


def main():
    """Test validation functions"""
    import json
    
    # Test with mock data
    test_facts = [
        {'concept': 'Assets', 'value_numeric': 1000000, 'period_end': '2024-12-31'},
        {'concept': 'Liabilities', 'value_numeric': 600000, 'period_end': '2024-12-31'},
        {'concept': 'StockholdersEquity', 'value_numeric': 400000, 'period_end': '2024-12-31'},
    ]
    
    validator = FinancialValidator(tolerance_pct=1.0)
    report = validator.validate_filing(
        facts=test_facts,
        company='TEST',
        filing_type='10-K',
        fiscal_year_end='2024-12-31'
    )
    
    print("Validation Report:")
    print(json.dumps(report.to_dict(), indent=2))


if __name__ == '__main__':
    main()

