#!/usr/bin/env python3
"""
Unified FinSight Validation Framework

Validates financial data at multiple stages:
1. Raw XBRL facts (post-parsing, pre-load)
2. Database (post-load, post-normalization)

Run validation after each pipeline stage to ensure data quality.
"""
import sys
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from config import DATABASE_URI

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
    """Complete validation report"""
    validation_type: str  # 'raw_facts' or 'database'
    target: str  # company/filing or 'all'
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


class RawFactsValidator:
    """Validates raw XBRL facts before database loading"""
    
    def __init__(self, tolerance_pct: float = 1.0):
        self.tolerance_pct = tolerance_pct
    
    def validate_filing(
        self,
        facts: List[Dict[str, Any]],
        company: str,
        filing_type: str,
        fiscal_year_end: str
    ) -> ValidationReport:
        """
        Run all validation rules on a filing's raw facts
        
        Args:
            facts: List of financial facts (from XBRL parser)
            company: Company ticker
            filing_type: Filing type (10-K, 20-F, etc.)
            fiscal_year_end: Fiscal year end date
            
        Returns:
            ValidationReport with all results
        """
        report = ValidationReport(
            validation_type='raw_facts',
            target=f'{company}/{filing_type}/{fiscal_year_end}'
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
        """Group facts by reporting period"""
        grouped = {}
        for fact in facts:
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
        """Check: Assets = Liabilities + Equity"""
        assets = self._find_concept_value(facts, ['Assets', 'AssetsTotal'])
        liabilities = self._find_concept_value(facts, ['Liabilities', 'LiabilitiesTotal'])
        equity = self._find_concept_value(facts, ['StockholdersEquity', 'Equity'])
        
        if not (assets and liabilities and equity):
            return None
        
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
    
    def _check_eps_calculation(
        self,
        facts: List[Dict[str, Any]],
        period: str
    ) -> Optional[ValidationResult]:
        """Check: EPS ≈ Net Income / Weighted Average Shares"""
        net_income = self._find_concept_value(facts, ['NetIncomeLoss', 'NetIncome'])
        basic_shares = self._find_concept_value(facts, ['WeightedAverageNumberOfSharesOutstandingBasic'])
        basic_eps = self._find_concept_value(facts, ['EarningsPerShareBasic'])
        
        if not (net_income and basic_shares and basic_eps):
            return None
        
        calculated_eps = net_income / basic_shares if basic_shares != 0 else 0
        diff = abs(calculated_eps - basic_eps)
        diff_pct = (diff / abs(basic_eps) * 100) if basic_eps != 0 else 100
        
        eps_tolerance = max(self.tolerance_pct, 3.0)
        passed = diff_pct <= eps_tolerance
        
        return ValidationResult(
            rule_name='eps_calculation',
            passed=passed,
            severity='WARNING' if not passed else 'INFO',
            message=f"EPS Calculation (Period: {period})",
            details={
                'net_income': float(net_income),
                'shares': float(basic_shares),
                'reported_eps': float(basic_eps),
                'calculated_eps': float(calculated_eps),
                'difference_pct': float(diff_pct)
            },
            expected_value=float(calculated_eps),
            actual_value=float(basic_eps),
            tolerance_pct=eps_tolerance
        )
    
    def _check_completeness(self, facts: List[Dict[str, Any]]) -> List[ValidationResult]:
        """Check for presence of critical concepts"""
        results = []
        
        critical_concepts = {
            'Revenue': ['Revenue', 'Revenues', 'SalesRevenueNet'],
            'Net Income': ['NetIncomeLoss', 'NetIncome'],
            'Assets': ['Assets', 'AssetsTotal'],
            'Equity': ['StockholdersEquity', 'Equity'],
            'Cash': ['Cash', 'CashAndCashEquivalentsAtCarryingValue']
        }
        
        for category, concept_names in critical_concepts.items():
            found = self._find_concept_value(facts, concept_names)
            passed = found is not None
            
            results.append(ValidationResult(
                rule_name=f'has_{category.lower().replace(" ", "_")}',
                passed=passed,
                severity='WARNING' if not passed else 'INFO',
                message=f"Critical Concept: {category}",
                details={'found': passed, 'searched_concepts': concept_names}
            ))
        
        return results
    
    def _check_duplicates(self, facts: List[Dict[str, Any]]) -> Optional[ValidationResult]:
        """Check for duplicate facts"""
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
            details={'duplicate_count': len(duplicates)}
        )
    
    def _find_concept_value(
        self,
        facts: List[Dict[str, Any]],
        concept_names: List[str]
    ) -> Optional[float]:
        """Find numeric value for a concept by name"""
        for name in concept_names:
            for fact in facts:
                if fact.get('concept', '').lower() == name.lower():
                    if not fact.get('dimensions'):
                        value = fact.get('value_numeric')
                        if value is not None:
                            try:
                                return float(value)
                            except (ValueError, TypeError):
                                continue
        return None


class DatabaseValidator:
    """Validates database-level data quality"""
    
    def __init__(self):
        self.engine = create_engine(DATABASE_URI)
    
    def validate_all(self) -> ValidationReport:
        """Run all database validation checks"""
        report = ValidationReport(
            validation_type='database',
            target='all'
        )
        
        # Check normalization conflicts
        norm_result = self._check_normalization_conflicts()
        report.add_result(norm_result)
        
        # Check user-facing duplicates
        dup_result = self._check_user_facing_duplicates()
        report.add_result(dup_result)
        
        # Check company data
        company_results = self._check_company_data()
        report.results.extend(company_results)
        
        # Check data completeness
        completeness_results = self._check_data_completeness()
        report.results.extend(completeness_results)
        
        # Calculate overall score
        report.calculate_score()
        
        return report
    
    def _check_normalization_conflicts(self) -> ValidationResult:
        """Check for multiple concepts mapped to same normalized label"""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
            SELECT COUNT(*)
            FROM (
                SELECT normalized_label
                FROM dim_concepts
                GROUP BY normalized_label
                HAVING COUNT(DISTINCT concept_id) > 1
            ) conflicts;
            """))
            
            conflict_count = result.scalar()
            passed = conflict_count < 60  # Acceptable threshold
            
            return ValidationResult(
                rule_name='normalization_conflicts',
                passed=passed,
                severity='WARNING' if not passed else 'INFO',
                message="Normalization Conflicts",
                details={'conflict_count': conflict_count},
                actual_value=float(conflict_count)
            )
    
    def _check_user_facing_duplicates(self) -> ValidationResult:
        """Check for user-facing duplicates"""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
            SELECT COUNT(*)
            FROM (
                SELECT c.ticker, dc.normalized_label, dt.fiscal_year
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                JOIN dim_time_periods dt ON f.period_id = dt.period_id
                WHERE f.dimension_id IS NULL
                  AND dc.normalized_label NOT LIKE '%_note'
                  AND dc.normalized_label NOT LIKE '%_disclosure%'
                GROUP BY c.ticker, dc.normalized_label, dt.fiscal_year
                HAVING COUNT(DISTINCT f.concept_id) > 1
            ) dups;
            """))
            
            dup_count = result.scalar()
            passed = dup_count == 0
            
            return ValidationResult(
                rule_name='user_facing_duplicates',
                passed=passed,
                severity='ERROR' if not passed else 'INFO',
                message="User-Facing Duplicates",
                details={'duplicate_count': dup_count},
                actual_value=float(dup_count)
            )
    
    def _check_company_data(self) -> List[ValidationResult]:
        """Check if all companies have data"""
        results = []
        
        with self.engine.connect() as conn:
            result = conn.execute(text("""
            SELECT 
                c.ticker,
                COUNT(DISTINCT f.filing_id) as filings,
                COUNT(f.fact_id) as facts
            FROM dim_companies c
            LEFT JOIN fact_financial_metrics f ON c.company_id = f.company_id
            GROUP BY c.company_id, c.ticker
            ORDER BY c.ticker;
            """))
            
            for row in result:
                has_data = row[1] > 0  # Has filings
                adequate_data = row[2] >= 100  # Has enough facts
                
                results.append(ValidationResult(
                    rule_name=f'company_has_data_{row[0]}',
                    passed=has_data and adequate_data,
                    severity='ERROR' if not has_data else 'WARNING' if not adequate_data else 'INFO',
                    message=f"Company Data: {row[0]}",
                    details={'filings': row[1], 'facts': row[2]}
                ))
        
        return results
    
    def _check_data_completeness(self) -> List[ValidationResult]:
        """Check for completeness of critical metrics"""
        results = []
        
        critical_metrics = ['revenue', 'net_income', 'total_assets', 'stockholders_equity']
        
        with self.engine.connect() as conn:
            for metric in critical_metrics:
                result = conn.execute(text(f"""
                SELECT COUNT(DISTINCT c.ticker)
                FROM dim_companies c
                LEFT JOIN fact_financial_metrics f ON c.company_id = f.company_id
                LEFT JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                WHERE dc.normalized_label = :metric;
                """), {'metric': metric})
                
                company_count = result.scalar()
                
                total_companies_result = conn.execute(text("SELECT COUNT(*) FROM dim_companies;"))
                total_companies = total_companies_result.scalar()
                
                passed = company_count >= total_companies * 0.8  # 80% of companies have it
                
                results.append(ValidationResult(
                    rule_name=f'metric_coverage_{metric}',
                    passed=passed,
                    severity='WARNING' if not passed else 'INFO',
                    message=f"Metric Coverage: {metric}",
                    details={
                        'companies_with_metric': company_count,
                        'total_companies': total_companies,
                        'coverage_pct': (company_count / total_companies * 100) if total_companies > 0 else 0
                    }
                ))
        
        return results


def print_validation_report(report: ValidationReport, verbose: bool = True):
    """Print validation report"""
    print("=" * 80)
    print(f"VALIDATION REPORT: {report.validation_type.upper()}")
    print(f"Target: {report.target}")
    print(f"Timestamp: {report.validation_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    print()
    
    errors = report.get_errors()
    warnings = report.get_warnings()
    info = [r for r in report.results if r.severity == 'INFO' and r.passed]
    
    if errors:
        print(f"❌ ERRORS ({len(errors)}):")
        for err in errors:
            print(f"  - {err.rule_name}: {err.message}")
            if verbose and err.details:
                print(f"    Details: {err.details}")
        print()
    
    if warnings:
        print(f"⚠️  WARNINGS ({len(warnings)}):")
        for warn in warnings:
            print(f"  - {warn.rule_name}: {warn.message}")
            if verbose and warn.details:
                print(f"    Details: {warn.details}")
        print()
    
    if info and verbose:
        print(f"✅ PASSED ({len(info)}):")
        for i in info[:5]:  # Show first 5
            print(f"  - {i.rule_name}: {i.message}")
        if len(info) > 5:
            print(f"  ... and {len(info) - 5} more")
        print()
    
    print("=" * 80)
    print(f"OVERALL SCORE: {report.overall_score:.1%}")
    print(f"STATUS: {'✅ PASSED' if report.passed else '❌ FAILED'}")
    print("=" * 80)


def main():
    """Run database validation"""
    import argparse
    
    parser = argparse.ArgumentParser(description='FinSight Data Validation')
    parser.add_argument('--type', choices=['database', 'facts'], default='database',
                       help='Validation type')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    if args.type == 'database':
        validator = DatabaseValidator()
        report = validator.validate_all()
        print_validation_report(report, verbose=args.verbose)
        
        # Exit with error code if validation failed
        sys.exit(0 if report.passed else 1)
    
    # For facts validation, would need to provide facts data
    print("Facts validation requires providing raw facts data")
    sys.exit(1)


if __name__ == '__main__':
    main()

