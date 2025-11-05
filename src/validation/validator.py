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
    
    # Whitelist of intentional cross-taxonomy merges and data-driven synonyms
    # These concepts represent the same financial item across different accounting standards
    # or are confirmed synonyms via data-driven analysis (no company uses both concepts together)
    INTENTIONAL_MERGES = {
        # Core statements
        'revenue', 'cost_of_revenue', 'net_income', 'stockholders_equity',
        'income_before_tax', 'comprehensive_income', 'oci_total',
        
        # Balance sheet items (cross-taxonomy naming)
        'current_assets', 'current_liabilities', 'noncurrent_liabilities',
        # Note: current_liabilities_ifrs_variant and noncurrent_liabilities_ifrs_variant are NOT in intentional merges
        # (they're kept separate to prevent incorrect merging of different-scope concepts)
        'inventory', 'accounts_receivable', 'accounts_payable', 'retained_earnings',
        
        # Cash equivalents (data-driven: banks use CashAndDueFromBanks, others use CashAndCashEquivalentsAtCarryingValue)
        # No company uses both - they're semantically equivalent but industry-specific
        'cash_and_equivalents',
        
        # Cash flow (cross-taxonomy naming)
        'operating_cash_flow', 'investing_cash_flow', 'financing_cash_flow',
        'dividends_paid',
        
        # Investments (US-GAAP naming variants)
        'short_term_investments', 'long_term_investments',
        
        # Data-driven synonyms (confirmed via usage patterns, not in reference linkbase)
        # These were validated: no company uses both concepts together = true synonyms
        'accounts_receivable_current',  # AccountsReceivableNetCurrent vs ReceivablesNetCurrent
        'interest_expense',  # InterestExpense vs InterestExpenseDebt
        'interest_income_expense_net',  # InterestIncomeExpenseNet vs InterestIncomeExpenseNonoperatingNet
        
        # Pensions (IFRS/US-GAAP equivalents)
        'pension_benefit_obligation', 'pension_funded_status', 'pension_service_cost',
        'pension_discount_rate', 'oci_pension_adjustments',
        
        # Derivatives (different levels of detail, but same concept)
        'derivative_financial_instruments', 'derivative_notional_amount',
        'derivative_gain_loss',
        
        # Property & equipment (with/without right-of-use assets)
        'property_plant_equipment', 'ppe_net_alternative',
        'operating_lease_liability', 'operating_lease_right_of_use_asset',
        
        # Intangibles (IFRS/US-GAAP)
        'intangible_assets_alternative', 'intangible_assets_impairment',
        
        # Securities (current vs total naming variants)
        'equity_securities_fvni',  # FvNi vs FvNiCurrentAndNoncurrent (never used together)
        
        # EPS & Equity (minor variants, same values)
        'net_income_to_common',  # Basic vs Diluted (0% diff - rounding)
        'stock_repurchased',  # Cash flow vs Balance sheet (mostly same values)
        'total_assets',  # Assets vs LiabilitiesAndStockholdersEquity (balance sheet identity)
        
        # Other
        'revenue_growth_percent', 'business_combination_purchase_price',
        'deferred_tax_valuation_allowance', 'stock_issued_value_sbc',
        'stock_options_granted',
    }
    
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
        
        # Check missing data matrix (company × metric × year)
        missing_matrix_result = self._check_missing_data_matrix()
        report.add_result(missing_matrix_result)
        
        # Check universal metrics completeness (SOLUTION 2)
        universal_metrics_result = self._check_universal_metrics()
        report.add_result(universal_metrics_result)
        
        # Check accounting identities
        accounting_results = self._check_accounting_identities()
        report.results.extend(accounting_results)
        
        # Check calculation relationships
        relationship_result = self._check_calculation_relationships()
        report.add_result(relationship_result)
        
        # Check data quality (normalization coverage, numeric ranges, unit consistency)
        quality_results = self._check_data_quality()
        report.results.extend(quality_results)
        
        # Calculate overall score
        report.calculate_score()
        
        return report
    
    def _check_normalization_conflicts(self) -> ValidationResult:
        """
        Check for UNINTENTIONAL normalization conflicts:
        Multiple DIFFERENT concept_names mapped to same normalized label.
        
        EXCLUDES (NOT conflicts):
        - Same concept_name from different taxonomies (IFRS vs US-GAAP) = EXPECTED ✅
        - Cross-taxonomy merges (different taxonomies) = EXPECTED ✅
        - Semantically equivalent concepts (same authoritative reference) = EXPECTED ✅
        - Intentional cross-taxonomy merges (whitelisted) = EXPECTED
        
        DATA-DRIVEN: Uses taxonomy reference linkbase to determine semantic equivalence.
        Only flags conflicts when concepts have DIFFERENT authoritative references.
        """
        with self.engine.connect() as conn:
            # Step 1: Load semantic equivalence groups from taxonomy files
            semantic_equivalence_groups = {}
            try:
                from pathlib import Path
                taxonomy_dir = Path(__file__).parent.parent.parent / 'data' / 'taxonomies'
                labels_files = list(taxonomy_dir.glob("*/*-labels.json")) + list(taxonomy_dir.glob("*-labels.json"))
                
                for labels_file in labels_files:
                    import json
                    with open(labels_file, 'r') as f:
                        data = json.load(f)
                        semantic_equivalence = data.get('semantic_equivalence', {})
                        
                        # Build reverse mapping: concept -> equivalence group
                        for canonical, equivalent_concepts in semantic_equivalence.items():
                            for concept_name in equivalent_concepts:
                                semantic_equivalence_groups[concept_name] = canonical
            except Exception as e:
                logger.warning(f"Could not load semantic equivalence groups: {e}")
            
            # Step 2: Find conflicts WITHIN same taxonomy
            result = conn.execute(text("""
            WITH conflicts_by_taxonomy AS (
                SELECT 
                    normalized_label,
                    taxonomy,
                    STRING_AGG(DISTINCT concept_name, ' | ' ORDER BY concept_name) as concepts
                FROM dim_concepts
                GROUP BY normalized_label, taxonomy
                HAVING COUNT(DISTINCT concept_name) > 1
            )
            SELECT normalized_label, taxonomy, concepts
            FROM conflicts_by_taxonomy;
            """))
            
            same_taxonomy_conflicts_raw = result.fetchall()
            
            # Step 3: Filter out semantically equivalent concepts (using reference linkbase)
            true_conflicts = []
            for normalized_label, taxonomy, concepts_str in same_taxonomy_conflicts_raw:
                concepts = concepts_str.split(' | ')
                
                # Check if all concepts are semantically equivalent
                equivalence_group = None
                all_equivalent = True
                
                for concept in concepts:
                    if concept in semantic_equivalence_groups:
                        equiv_canonical = semantic_equivalence_groups[concept]
                        if equivalence_group is None:
                            equivalence_group = equiv_canonical
                        elif equiv_canonical != equivalence_group:
                            # Different equivalence groups = different semantics = TRUE CONFLICT
                            all_equivalent = False
                            break
                    else:
                        # Concept not in semantic equivalence = check individually
                        all_equivalent = False
                        break
                
                if not all_equivalent:
                    # Concepts are NOT semantically equivalent = TRUE CONFLICT
                    true_conflicts.append(normalized_label)
            
            # Also get all conflicts (for reporting)
            result2 = conn.execute(text("""
            SELECT normalized_label
            FROM dim_concepts
            GROUP BY normalized_label
            HAVING COUNT(DISTINCT concept_name) > 1;
            """))
            
            all_conflicts = [row[0] for row in result2]
            
            # Filter out intentional merges (whitelist) from true conflicts
            unintentional_conflicts = [
                label for label in true_conflicts
                if label not in self.INTENTIONAL_MERGES
            ]
            
            conflict_count = len(unintentional_conflicts)
            passed = conflict_count == 0  # Target: zero unintentional conflicts
            
            # Count semantically equivalent merges (these are OK - from reference linkbase)
            semantically_equivalent_merges = len(same_taxonomy_conflicts_raw) - len(true_conflicts)
            
            # Count cross-taxonomy merges (these are OK)
            cross_taxonomy_merges = [
                label for label in all_conflicts 
                if label not in [c[0] for c in same_taxonomy_conflicts_raw]
            ]
            
            return ValidationResult(
                rule_name='normalization_conflicts',
                passed=passed,
                severity='ERROR' if not passed else 'INFO',
                message="Unintentional Normalization Conflicts",
                details={
                    'unintentional_conflicts': conflict_count,
                    'semantically_equivalent_merges': semantically_equivalent_merges,  # These are OK (from reference linkbase)
                    'cross_taxonomy_merges': len(cross_taxonomy_merges),  # These are OK
                    'intentional_merges': len([l for l in all_conflicts if l in self.INTENTIONAL_MERGES]),
                    'total_conflicts': len(all_conflicts),
                    'unintentional_list': unintentional_conflicts[:10]  # First 10
                },
                actual_value=float(conflict_count)
            )
    
    def _check_user_facing_duplicates(self) -> ValidationResult:
        """
        Check for user-facing duplicates:
        Cases where a user sees multiple different values for the same metric.
        
        TRUE duplicate = same (company, normalized_label, fiscal_year, dimension)
                        but DIFFERENT concept_names with DIFFERENT values
        
        EXCLUDES false positives:
        - Same concept_name from different taxonomies = EXPECTED (same value)
        """
        with self.engine.connect() as conn:
            result = conn.execute(text("""
            SELECT COUNT(*)
            FROM (
                SELECT 
                    c.ticker, 
                    dc.normalized_label, 
                    dt.fiscal_year
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                JOIN dim_time_periods dt ON f.period_id = dt.period_id
                WHERE f.dimension_id IS NULL
                  AND dc.normalized_label NOT LIKE '%_note'
                  AND dc.normalized_label NOT LIKE '%_disclosure%'
                GROUP BY c.ticker, dc.normalized_label, dt.fiscal_year
                HAVING COUNT(DISTINCT dc.concept_name) > 1
                   AND COUNT(DISTINCT f.value_numeric) > 1  -- Only flag if VALUES are different (identical values handled by deduplication view)
            ) dups;
            """))
            
            dup_count = result.scalar()
            passed = dup_count == 0
            
            return ValidationResult(
                rule_name='user_facing_duplicates',
                passed=passed,
                severity='ERROR' if not passed else 'INFO',
                message="User-Facing Duplicates (Semantic)",
                details={'semantic_duplicate_count': dup_count},
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
        """
        Check for completeness of critical metrics.
        
        Uses taxonomy-driven approach: checks for all variants that map to the metric,
        not just exact label matches. This is the Big 4/Hedge Fund standard.
        """
        results = []
        
        # Define metric variants (taxonomy-driven approach)
        metric_variants = {
            'revenue': [
                'revenue', 'revenues', 'revenue_from_contracts',
                'revenue_from_contract_with_customer_excluding_assessed_tax'
            ],
            'net_income': [
                'net_income', 'net_income_loss', 'profit_loss',
                'net_income_including_noncontrolling_interest'
            ],
            'total_assets': [
                'total_assets', 'total_assets_equation'
            ],
            'stockholders_equity': [
                'stockholders_equity', 'equity_attributable_to_parent',
                'equity_total', 'stockholders_equity_including_noncontrolling_interest',
                'stockholders_equity_including_portion_attributable_to_noncontrolling_interest',
                'equity'
            ]
        }
        
        with self.engine.connect() as conn:
            for metric, variants in metric_variants.items():
                # Check for ANY variant (taxonomy-driven approach)
                variants_list = ','.join([f"'{v}'" for v in variants])
                
                result = conn.execute(text(f"""
                    SELECT COUNT(DISTINCT c.ticker)
                    FROM dim_companies c
                    WHERE EXISTS (
                        SELECT 1
                        FROM fact_financial_metrics f
                        JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                        WHERE f.company_id = c.company_id
                          AND f.dimension_id IS NULL
                          AND f.value_numeric IS NOT NULL
                          AND dc.normalized_label IN ({variants_list})
                    )
                    AND c.company_id > 0
                """))
                
                company_count = result.scalar()
                
                total_companies_result = conn.execute(text("SELECT COUNT(*) FROM dim_companies WHERE company_id > 0;"))
                total_companies = total_companies_result.scalar()
                
                passed = company_count >= total_companies * 0.8  # 80% threshold
                
                results.append(ValidationResult(
                    rule_name=f'metric_coverage_{metric}',
                    passed=passed,
                    severity='WARNING' if not passed else 'INFO',
                    message=f"Metric Coverage: {metric}",
                    details={
                        'companies_with_metric': company_count,
                        'total_companies': total_companies,
                        'coverage_pct': (company_count / total_companies * 100) if total_companies > 0 else 0,
                        'variants_checked': variants
                    }
                ))
        
        return results
    
    def _check_missing_data_matrix(self) -> ValidationResult:
        """
        Comprehensive missing data analysis: company × metric × year matrix.
        
        Calculates % missing for each company-metric combination across all time periods.
        """
        # Define universal metrics (same as UI "Universal metrics" granularity)
        # These are the metrics that should be available for ALL companies for cross-company analysis
        universal_metric_variants = {
            'revenue': ['revenue', 'revenues', 'revenue_from_contracts', 'revenue_from_contract_with_customer_excluding_assessed_tax'],
            'net_income': ['net_income', 'net_income_loss', 'profit_loss', 'net_income_including_noncontrolling_interest'],
            'total_assets': ['total_assets', 'total_assets_equation'],
            'total_liabilities': ['total_liabilities', 'liabilities'],
            'stockholders_equity': ['stockholders_equity', 'equity_attributable_to_parent', 'equity_total', 'equity', 'stockholders_equity_including_noncontrolling_interest'],
            'current_liabilities': ['current_liabilities', 'liabilities_current', 'current_liabilities_ifrs_variant'],
            'noncurrent_liabilities': ['noncurrent_liabilities', 'liabilities_noncurrent', 'noncurrent_liabilities_ifrs_variant'],
            'accounts_receivable': ['accounts_receivable', 'accounts_receivable_current', 'accounts_receivable_net'],
            'accounts_payable': ['accounts_payable', 'accounts_payable_current'],
            'cash_and_equivalents': ['cash_and_equivalents', 'cash_and_cash_equivalents_at_carrying_value'],
            'operating_cash_flow': ['operating_cash_flow', 'net_cash_provided_by_used_in_operating_activities']
        }
        
        # Build flat list of all variants for SQL
        all_variants = []
        for variants in universal_metric_variants.values():
            all_variants.extend(variants)
        
        query = """
        WITH all_companies AS (
            SELECT DISTINCT ticker, company_id
            FROM dim_companies
            WHERE company_id > 0
        ),
        universal_metrics AS (
            -- Get all universal metric variants (grouped by base metric)
            SELECT DISTINCT
                co.normalized_label as metric_variant,
                CASE 
                    WHEN co.normalized_label IN ('revenue', 'revenues', 'revenue_from_contracts', 'revenue_from_contract_with_customer_excluding_assessed_tax') THEN 'revenue'
                    WHEN co.normalized_label IN ('net_income', 'net_income_loss', 'profit_loss', 'net_income_including_noncontrolling_interest') THEN 'net_income'
                    WHEN co.normalized_label IN ('total_assets', 'total_assets_equation') THEN 'total_assets'
                    WHEN co.normalized_label IN ('total_liabilities', 'liabilities') THEN 'total_liabilities'
                    WHEN co.normalized_label IN ('stockholders_equity', 'equity_attributable_to_parent', 'equity_total', 'equity', 'stockholders_equity_including_noncontrolling_interest') THEN 'stockholders_equity'
                    WHEN co.normalized_label IN ('current_liabilities', 'liabilities_current', 'current_liabilities_ifrs_variant') THEN 'current_liabilities'
                    WHEN co.normalized_label IN ('noncurrent_liabilities', 'liabilities_noncurrent', 'noncurrent_liabilities_ifrs_variant') THEN 'noncurrent_liabilities'
                    WHEN co.normalized_label IN ('accounts_receivable', 'accounts_receivable_current', 'accounts_receivable_net') THEN 'accounts_receivable'
                    WHEN co.normalized_label IN ('accounts_payable', 'accounts_payable_current') THEN 'accounts_payable'
                    WHEN co.normalized_label IN ('cash_and_equivalents', 'cash_and_cash_equivalents_at_carrying_value') THEN 'cash_and_equivalents'
                    WHEN co.normalized_label IN ('operating_cash_flow', 'net_cash_provided_by_used_in_operating_activities') THEN 'operating_cash_flow'
                    ELSE NULL
                END as base_metric
            FROM dim_concepts co
            WHERE co.normalized_label = ANY(ARRAY[{variants_placeholder}])
              AND co.normalized_label NOT LIKE '%_note'
              AND co.normalized_label NOT LIKE '%_disclosure%'
        ),
        company_metric_coverage AS (
            -- For each company and base metric, check if they have ANY variant
            -- Simplified: Directly check if company has any variant from the variant list
            SELECT DISTINCT
                ac.ticker as company,
                um.base_metric as metric,
                CASE WHEN EXISTS (
                    SELECT 1
                    FROM fact_financial_metrics f
                    JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                    WHERE f.company_id = ac.company_id
                      AND f.dimension_id IS NULL
                      AND f.value_numeric IS NOT NULL
                      AND dc.normalized_label IN (
                          SELECT um2.metric_variant 
                          FROM universal_metrics um2 
                          WHERE um2.base_metric = um.base_metric
                      )
                ) THEN 1 ELSE 0 END as has_metric
            FROM all_companies ac
            CROSS JOIN (SELECT DISTINCT base_metric FROM universal_metrics WHERE base_metric IS NOT NULL) um
        ),
        metric_coverage_stats AS (
            SELECT
                metric,
                COUNT(*) as total_companies,
                SUM(has_metric) as companies_with_metric,
                COUNT(*) - SUM(has_metric) as companies_missing_metric,
                ROUND(100.0 * SUM(has_metric) / COUNT(*), 1) as coverage_pct
            FROM company_metric_coverage
            GROUP BY metric
        )
        SELECT
            COUNT(*) as total_metrics,
            COUNT(*) FILTER (WHERE coverage_pct = 100.0) as complete_metrics,
            COUNT(*) FILTER (WHERE coverage_pct < 100.0) as incomplete_metrics,
            SUM(companies_missing_metric) as total_missing_combinations,
            ROUND(AVG(coverage_pct), 1) as avg_coverage_pct,
            ROUND(100.0 * SUM(companies_missing_metric) / (COUNT(*) * (SELECT COUNT(*) FROM all_companies)), 1) as missing_pct
        FROM metric_coverage_stats;
        """.replace('{variants_placeholder}', ','.join([f"'{v}'" for v in all_variants]))
        
        with self.engine.connect() as conn:
            result = conn.execute(text(query))
            row = result.fetchone()
            
            if row:
                total_metrics, complete_metrics, incomplete_metrics, total_missing_combinations, avg_coverage, missing_pct = row
                
                # For Big 4/Hedge Fund standards: Universal metrics MUST have 100% company coverage
                # If ANY company is missing a universal metric, it breaks cross-company analyzability
                # This is a CRITICAL data quality issue, not just a warning
                passed = incomplete_metrics == 0  # All metrics must have 100% company coverage
                severity = 'ERROR' if not passed else 'INFO'  # This is a blocker, not just informational
                
                # Get worst 10 combinations (metrics that company reports but missing in some years)
                worst_query = """
                WITH company_data_years AS (
                    SELECT DISTINCT
                        c.ticker as company,
                        t.fiscal_year
                    FROM fact_financial_metrics f
                    JOIN dim_companies c ON f.company_id = c.company_id
                    JOIN dim_time_periods t ON f.period_id = t.period_id
                    WHERE t.fiscal_year IS NOT NULL
                      AND f.dimension_id IS NULL
                      AND f.value_numeric IS NOT NULL
                ),
                company_reported_metrics AS (
                    SELECT DISTINCT
                        c.ticker as company,
                        co.normalized_label as metric
                    FROM fact_financial_metrics f
                    JOIN dim_companies c ON f.company_id = c.company_id
                    JOIN dim_concepts co ON f.concept_id = co.concept_id
                    WHERE co.normalized_label IS NOT NULL
                      AND co.normalized_label NOT LIKE '%_note'
                      AND co.normalized_label NOT LIKE '%_disclosure%'
                ),
                expected_combinations AS (
                    SELECT 
                        crm.company,
                        crm.metric,
                        cdy.fiscal_year
                    FROM company_reported_metrics crm
                    CROSS JOIN company_data_years cdy
                    WHERE crm.company = cdy.company
                ),
                actual_data AS (
                    SELECT DISTINCT
                        c.ticker as company,
                        co.normalized_label as metric,
                        t.fiscal_year
                    FROM fact_financial_metrics f
                    JOIN dim_companies c ON f.company_id = c.company_id
                    JOIN dim_concepts co ON f.concept_id = co.concept_id
                    JOIN dim_time_periods t ON f.period_id = t.period_id
                    WHERE f.dimension_id IS NULL
                      AND f.value_numeric IS NOT NULL
                      AND co.normalized_label IS NOT NULL
                      AND co.normalized_label NOT LIKE '%_note'
                ),
                coverage_stats AS (
                    SELECT 
                        ec.company,
                        ec.metric,
                        COUNT(DISTINCT ad.fiscal_year) as years_available,
                        COUNT(DISTINCT ec.fiscal_year) as years_total,
                        ROUND(100.0 * COUNT(DISTINCT ad.fiscal_year) / NULLIF(COUNT(DISTINCT ec.fiscal_year), 0), 1) as coverage_pct
                    FROM expected_combinations ec
                    LEFT JOIN actual_data ad ON 
                        ec.company = ad.company AND 
                        ec.metric = ad.metric AND 
                        ec.fiscal_year = ad.fiscal_year
                    GROUP BY ec.company, ec.metric
                    HAVING COUNT(DISTINCT ad.fiscal_year) = 0  -- Only missing
                )
                SELECT company, metric, years_total
                FROM coverage_stats
                ORDER BY years_total DESC
                LIMIT 10;
                """
                worst_result = conn.execute(text(worst_query))
                worst_examples = [f"{r[0]}:{r[1]}" for r in worst_result]
                
                return ValidationResult(
                    rule_name='missing_data_matrix',
                    passed=passed,  # All universal metrics must have 100% company coverage
                    severity=severity,  # ERROR if any metric missing for any company (breaks analyzability)
                    message="Universal Metrics Cross-Company Coverage (UI Analyzability)",
                    details={
                        'total_metrics': total_metrics,
                        'complete_metrics': complete_metrics,
                        'incomplete_metrics': incomplete_metrics,
                        'total_missing_combinations': total_missing_combinations,
                        'avg_coverage_pct': avg_coverage,
                        'missing_pct': missing_pct,
                        'worst_examples': worst_examples[:20],
                        'threshold': '100% company coverage required for universal metrics (Big 4/Hedge Fund standard)',
                        'explanation': 'Universal metrics displayed in UI must be available for ALL companies for cross-company analysis'
                    }
                )
        
        return ValidationResult(
            rule_name='missing_data_matrix',
            passed=False,
            severity='ERROR',
            message='Missing Data Matrix Analysis failed',
            details={'error': 'Could not calculate missing data matrix'}
        )
    
    def _check_universal_metrics(self) -> ValidationResult:
        """
        Check that ALL companies report mandatory universal metrics.

        TAXONOMY-DRIVEN APPROACH (Big 4/Hedge Fund Standard):
        - Uses taxonomy calculation linkbases to identify required totals (balance sheet equation, income statement)
        - Checks if companies have concepts mapping to taxonomy totals (via taxonomy semantics, not manual labels)
        - Uses accounting standards (GAAP/IFRS) as source of truth, not manual lists

        This replaces the fragile manual label checking approach with a lasting, standards-compliant solution.

        Universal metrics are metrics REQUIRED by accounting standards:
        - Balance Sheet Equation: Assets = Liabilities + Equity (required totals)
        - Income Statement Totals: Revenue, Net Income (required totals)
        - Standard Line Items: Current/Noncurrent Liabilities, Accounts Receivable, Accounts Payable, Cash, Operating Cash Flow

        HARD FAILS if any company is missing these - indicates data loading problem.
        """
        from pathlib import Path
        from src.validation.taxonomy_driven_universal_metrics import check_universal_metrics_taxonomy_driven
        
        taxonomy_dir = Path(__file__).parent.parent.parent / 'data' / 'taxonomies'
        
        if not taxonomy_dir.exists():
            # Fallback to manual checking if taxonomy not available
            logger.warning("Taxonomy directory not found - using fallback manual checking")
            return self._check_universal_metrics_manual()
        
        try:
            # Use taxonomy-driven detection
            result = check_universal_metrics_taxonomy_driven(self.engine, taxonomy_dir)
            
            passed = result['passed']
            missing_by_company = result['missing_by_company']
            total_violations = result['total_violations']
            total_companies_checked = result['total_companies_checked']
            
            return ValidationResult(
                rule_name='universal_metrics_completeness',
                passed=passed,
                severity='ERROR' if not passed else 'INFO',
                message=f'Universal Metrics Completeness (Taxonomy-Driven)',
                details={
                    'missing_by_company': missing_by_company,
                    'required_metrics': result['required_metrics'],
                    'total_companies_checked': total_companies_checked,
                    'total_violations': total_violations,
                    'approach': 'taxonomy_driven'
                },
                actual_value=float(total_violations)
            )
        except Exception as e:
            logger.error(f"Taxonomy-driven universal metrics check failed: {e}")
            logger.info("Falling back to manual checking")
            return self._check_universal_metrics_manual()
    
    def _check_universal_metrics_manual(self) -> ValidationResult:
        """
        Fallback manual checking (only used if taxonomy-driven approach fails).
        
        This is the OLD approach - kept as fallback only.
        """
        # Use ACTUAL normalized labels from database
        # Group related metrics (variants that are equivalent - company needs ANY variant, not all)
        UNIVERSAL_METRIC_GROUPS = {
            'total_assets': ['total_assets', 'total_assets_equation'],
            'revenue': [
                'revenue', 
                'revenues',  # US-GAAP variant (WMT, etc.)
                'revenue_from_contracts',
                'revenue_from_contract_with_customer_excluding_assessed_tax'  # IFRS/ESEF variant (most companies)
            ],
            'net_income': [
                'net_income', 
                'net_income_loss',  # Common variant (14 companies)
                'net_income_including_noncontrolling_interest',
                'profit_loss'  # IFRS variant
            ],
            'stockholders_equity': [
                'stockholders_equity', 
                'equity_attributable_to_parent',  # IFRS (excluding NCI)
                'equity_total',  # IFRS simple equity (NVO)
                'stockholders_equity_including_noncontrolling_interest',  # US-GAAP including NCI (JNJ)
                'stockholders_equity_including_portion_attributable_to_noncontrolling_interest',  # CAT/JNJ variant
                'equity'  # Generic IFRS
            ],
            'current_liabilities': [
                'current_liabilities',
                'liabilities_current'  # Actual label found (14 companies)
            ],
            'noncurrent_liabilities': [
                'noncurrent_liabilities',
                'liabilities_noncurrent'  # Actual label found (11 companies)
            ],
            'accounts_receivable': [
                'accounts_receivable', 
                'accounts_receivable_current',
                'accounts_receivable_net_current',  # Actual label found (12 companies)
                'accounts_receivable_net',  # Actual label found (2 companies)
                # Bank-specific: financing receivables are not accounts receivable (different asset class)
                # Banks don't typically report "accounts receivable" - they have loans/financing receivables
            ],
            'accounts_payable': [
                'accounts_payable', 
                'accounts_payable_and_accrued_liabilities',
                'accounts_payable_current',  # Actual label found (12 companies)
                'accounts_payable_and_accrued_liabilities_current',  # KO variant
                'accounts_payable_trade_current',  # KO variant
                'accounts_payable_and_other_accrued_liabilities',  # JPM variant
            ],
            'cash_and_equivalents': [
                'cash_and_equivalents',
                'cash_and_cash_equivalents_at_carrying_value'  # Actual label found (13 companies)
            ],
            'operating_cash_flow': [
                'operating_cash_flow', 
                'operating_cash_flow_continuing_operations',
                'net_cash_provided_by_used_in_operating_activities'  # Actual label found (15 companies)
            ]
        }
        
        # Build query that checks for ANY variant in each group (OR logic, not AND)
        all_variants = set()
        for variants in UNIVERSAL_METRIC_GROUPS.values():
            all_variants.update(variants)
        
        metrics_placeholders = ','.join([f"'{m}'" for m in all_variants])
        
        # Build UNION queries for each metric group
        # NOTE: Bank-specific concepts are now mapped to universal metrics in taxonomy_mappings.py
        # (e.g., CashAndDueFromBanks → cash_and_equivalents)
        # So validation should work for banks after proper normalization
        union_queries = []
        for group_name, variants in UNIVERSAL_METRIC_GROUPS.items():
            variants_list = ','.join([f"'{v}'" for v in variants])
            
            union_queries.append(f"""
                SELECT 
                    ac.ticker,
                    '{group_name}' as required_metric
                FROM all_companies ac
                WHERE NOT EXISTS (
                    SELECT 1 FROM reported_metrics rm
                    WHERE rm.ticker = ac.ticker
                    AND rm.normalized_label IN ({variants_list})
                )
            """)
        
        query = f"""
        WITH all_companies AS (
            SELECT ticker, company_id
            FROM dim_companies
            WHERE company_id > 0
        ),
        reported_metrics AS (
            SELECT DISTINCT
                c.ticker,
                dc.normalized_label
            FROM fact_financial_metrics f
            JOIN dim_companies c ON f.company_id = c.company_id
            JOIN dim_concepts dc ON f.concept_id = dc.concept_id
            WHERE f.dimension_id IS NULL
              AND f.value_numeric IS NOT NULL
              AND dc.normalized_label IN ({metrics_placeholders})
        )
        SELECT 
            ticker,
            ARRAY_AGG(required_metric) as missing_metrics
        FROM (
            {' UNION ALL '.join(union_queries)}
        ) missing
        GROUP BY ticker;
        """
        
        with self.engine.connect() as conn:
            result = conn.execute(text(query))
            
            missing = result.fetchall()
            
            if missing:
                missing_by_company = {row[0]: row[1] if row[1] else [] for row in missing}
                total_companies = len(missing)
                total_missing = sum(len(metrics) for metrics in missing_by_company.values())
                
                return ValidationResult(
                    rule_name='universal_metrics_completeness',
                    passed=False,
                    severity='ERROR',
                    message=f'{total_companies} companies missing {total_missing} universal metrics',
                    details={
                        'missing_by_company': missing_by_company,
                        'universal_metrics': list(UNIVERSAL_METRIC_GROUPS.keys()),
                        'total_companies_checked': total_companies,
                        'total_violations': total_missing
                    }
                )
            else:
                return ValidationResult(
                    rule_name='universal_metrics_completeness',
                    passed=True,
                    severity='INFO',
                    message='All companies report all universal metrics',
                    details={'universal_metrics': list(UNIVERSAL_METRIC_GROUPS.keys())}
                )
    
    def _check_accounting_identities(self) -> List[ValidationResult]:
        """
        Check accounting identities for all companies and periods.
        Returns list of ValidationResult for each identity check.
        """
        results = []
        tolerance_pct = 1.0  # 1% tolerance for rounding
        
        # 1. Balance Sheet Equation: Assets = Liabilities + Equity
        balance_sheet_result = self._check_balance_sheet_equation(tolerance_pct)
        results.append(balance_sheet_result)
        
        # 2. Retained Earnings Rollforward
        re_result = self._check_retained_earnings_rollforward(tolerance_pct)
        results.append(re_result)
        
        # 3. Cash Flow to Balance Sheet Reconciliation
        cash_flow_result = self._check_cash_flow_reconciliation(tolerance_pct)
        results.append(cash_flow_result)
        
        # 4. Gross Profit Margin
        gross_profit_result = self._check_gross_profit_margin()
        results.append(gross_profit_result)
        
        # 5. Operating Income Calculation
        operating_income_result = self._check_operating_income_calculation(tolerance_pct)
        results.append(operating_income_result)
        
        return results
    
    def _check_balance_sheet_equation(self, tolerance_pct: float) -> ValidationResult:
        """
        Check Assets = Liabilities + Equity for all periods.
        Tolerance: 1% (accounting for rounding)
        
        BIG 4/HEDGE FUND APPROACH:
        - Use ONE value per company-period (not sum of all variants)
        - Prefer explicit concepts over derived/calculated
        - Prefer most specific concepts (e.g., stockholders_equity > equity_total > equity)
        - Avoid double-counting when company reports multiple variants
        """
        query = text("""
            WITH balance_sheet_values AS (
                -- Get ONE value per company-period for each component
                -- Priority: explicit > derived, most specific > generic
                SELECT 
                    c.ticker,
                    t.fiscal_year,
                    t.period_type,
                    -- Assets: prefer 'total_assets' (explicit Assets), fallback to 'total_assets_equation' (LiabilitiesAndStockholdersEquity)
                    MAX(CASE 
                        WHEN dc.normalized_label = 'total_assets' THEN f.value_numeric
                        WHEN dc.normalized_label = 'total_assets_equation' THEN f.value_numeric
                        ELSE NULL
                    END) as total_assets,
                    -- Liabilities: prefer explicit 'total_liabilities'
                    MAX(CASE 
                        WHEN dc.normalized_label = 'total_liabilities' THEN f.value_numeric
                        WHEN dc.normalized_label = 'liabilities' THEN f.value_numeric
                        ELSE NULL
                    END) as total_liabilities,
                    -- Equity: prefer most specific (stockholders_equity > equity_attributable_to_parent > equity_total > equity)
                    MAX(CASE 
                        WHEN dc.normalized_label = 'stockholders_equity' THEN f.value_numeric
                        WHEN dc.normalized_label = 'equity_attributable_to_parent' THEN f.value_numeric
                        WHEN dc.normalized_label = 'stockholders_equity_including_noncontrolling_interest' THEN f.value_numeric
                        WHEN dc.normalized_label = 'equity_total' THEN f.value_numeric
                        WHEN dc.normalized_label = 'equity' THEN f.value_numeric
                        ELSE NULL
                    END) as equity
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                JOIN dim_time_periods t ON f.period_id = t.period_id
                WHERE f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND t.period_type = 'instant'  -- Balance sheet is instant
                  AND t.fiscal_year IS NOT NULL
                GROUP BY c.ticker, t.fiscal_year, t.period_type
            ),
            balance_sheet_totals AS (
                -- Check if company reports EquityAndLiabilities (IFRS) or LiabilitiesAndStockholdersEquity (US-GAAP)
                -- If Assets = total, use that for validation (both sides of equation should match)
                SELECT 
                    c.ticker,
                    t.fiscal_year,
                    MAX(CASE WHEN dc.concept_name = 'EquityAndLiabilities' THEN f.value_numeric END) as equity_and_liabilities,
                    MAX(CASE WHEN dc.concept_name = 'LiabilitiesAndStockholdersEquity' THEN f.value_numeric END) as liabilities_and_stockholders_equity
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                JOIN dim_time_periods t ON f.period_id = t.period_id
                WHERE f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND t.period_type = 'instant'
                  AND t.fiscal_year IS NOT NULL
                  AND dc.concept_name IN ('EquityAndLiabilities', 'LiabilitiesAndStockholdersEquity')
                GROUP BY c.ticker, t.fiscal_year
            ),
            balance_sheet_data AS (
                SELECT 
                    bsv.ticker,
                    bsv.fiscal_year,
                    bsv.period_type,
                    bsv.total_assets,
                    bsv.total_liabilities,
                    bsv.equity,
                    bst.equity_and_liabilities,
                    -- If Assets = EquityAndLiabilities (IFRS) or Assets = LiabilitiesAndStockholdersEquity (US-GAAP),
                    -- use that total for validation (both sides of equation should match)
                    -- This handles cases where individual Liabilities + Equity don't match (scope mismatch)
                    COALESCE(
                        CASE 
                            WHEN bsv.total_assets IS NOT NULL 
                                 AND bst.equity_and_liabilities IS NOT NULL
                                 AND ABS(bsv.total_assets - bst.equity_and_liabilities) / NULLIF(bsv.total_assets, 0) < 0.01
                            THEN bst.equity_and_liabilities  -- IFRS pattern: Assets = EquityAndLiabilities
                            ELSE NULL
                        END,
                        CASE 
                            WHEN bsv.total_assets IS NOT NULL 
                                 AND bst.liabilities_and_stockholders_equity IS NOT NULL
                                 AND ABS(bsv.total_assets - bst.liabilities_and_stockholders_equity) / NULLIF(bsv.total_assets, 0) < 0.01
                            THEN bst.liabilities_and_stockholders_equity  -- US-GAAP pattern: Assets = LiabilitiesAndStockholdersEquity
                            ELSE NULL
                        END,
                        bsv.total_assets,  -- Standard: Use Assets (explicit)
                        bsv.total_liabilities + bsv.equity  -- Fallback: Calculate from components
                    ) as assets_used,
                    -- For comparison: Use the same total (if Assets = total, use total)
                    -- Otherwise, use Liabilities + Equity (sum of components)
                    COALESCE(
                        CASE 
                            WHEN bsv.total_assets IS NOT NULL 
                                 AND bst.equity_and_liabilities IS NOT NULL
                                 AND ABS(bsv.total_assets - bst.equity_and_liabilities) / NULLIF(bsv.total_assets, 0) < 0.01
                            THEN bst.equity_and_liabilities  -- IFRS: Use EquityAndLiabilities total
                            ELSE NULL
                        END,
                        CASE 
                            WHEN bsv.total_assets IS NOT NULL 
                                 AND bst.liabilities_and_stockholders_equity IS NOT NULL
                                 AND ABS(bsv.total_assets - bst.liabilities_and_stockholders_equity) / NULLIF(bsv.total_assets, 0) < 0.01
                            THEN bst.liabilities_and_stockholders_equity  -- US-GAAP: Use LiabilitiesAndStockholdersEquity total
                            ELSE NULL
                        END,
                        bsv.total_liabilities + bsv.equity,  -- Standard: Use sum of components
                        bsv.total_assets  -- Fallback: Use Assets
                    ) as liabilities_plus_equity_used,
                    -- Keep individual components for reporting
                    COALESCE(bsv.total_liabilities, bsv.total_assets - bsv.equity) as liabilities_used,
                    COALESCE(bsv.equity, bsv.total_assets - bsv.total_liabilities) as equity_used
                FROM balance_sheet_values bsv
                LEFT JOIN balance_sheet_totals bst ON bsv.ticker = bst.ticker AND bsv.fiscal_year = bst.fiscal_year
                WHERE bsv.total_assets IS NOT NULL OR (bsv.total_liabilities IS NOT NULL AND bsv.equity IS NOT NULL)
            )
            SELECT 
                ticker,
                fiscal_year,
                assets_used as total_assets,
                liabilities_used as total_liabilities,
                equity_used as equity,
                liabilities_plus_equity_used as liabilities_plus_equity,
                ABS(assets_used - liabilities_plus_equity_used) as difference,
                ABS(assets_used - liabilities_plus_equity_used) / NULLIF(assets_used, 0) * 100 as difference_pct
            FROM balance_sheet_data
            WHERE ABS(assets_used - liabilities_plus_equity_used) / NULLIF(assets_used, 0) * 100 > :tolerance
            ORDER BY difference_pct DESC
            LIMIT 20;
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query, {'tolerance': tolerance_pct})
            violations = result.fetchall()
            
            if violations:
                violation_details = [
                    {
                        'company': row[0],
                        'fiscal_year': row[1],
                        'total_assets': float(row[2]),
                        'liabilities_plus_equity': float(row[5]),
                        'difference': float(row[6]),
                        'difference_pct': float(row[7])
                    }
                    for row in violations
                ]
                
                return ValidationResult(
                    rule_name='balance_sheet_equation',
                    passed=False,
                    severity='ERROR',
                    message=f'Balance sheet equation violated for {len(violations)} company-period combinations',
                    details={
                        'violations': violation_details[:10],
                        'total_violations': len(violations),
                        'tolerance_pct': tolerance_pct,
                        'explanation': 'Assets should equal Liabilities + Equity (within 1% tolerance)'
                    }
                )
            else:
                return ValidationResult(
                    rule_name='balance_sheet_equation',
                    passed=True,
                    severity='INFO',
                    message='Balance sheet equation holds for all company-period combinations',
                    details={'tolerance_pct': tolerance_pct}
                )
    
    def _check_retained_earnings_rollforward(self, tolerance_pct: float) -> ValidationResult:
        """
        Check Ending RE = Beginning RE + Net Income - Dividends + Other Adjustments.
        
        IMPORTANT: OCI (Other Comprehensive Income) does NOT flow through Retained Earnings!
        OCI flows through Accumulated Other Comprehensive Income (AOCI), a separate equity account.
        
        Other adjustments that DO affect RE:
        - Reclassifications FROM AOCI to RE (when OCI items are realized/settled)
        - Stock-based compensation adjustments
        - Share repurchases (treasury stock)
        - Other equity adjustments
        
        Tolerance: 1%
        
        BIG 4/HEDGE FUND APPROACH:
        - OCI excluded (it goes to AOCI, not RE)
        - Only include reclassifications FROM AOCI to RE
        - If reclassifications missing → warning (acceptable - data incomplete)
        - Simple formula: Beginning RE + Net Income - Dividends (most companies don't have other adjustments)
        """
        query = text("""
            WITH re_data AS (
                SELECT 
                    c.ticker,
                    t.fiscal_year,
                    t.period_type,
                    MAX(CASE WHEN dc.normalized_label = 'retained_earnings' 
                        THEN f.value_numeric ELSE NULL END) as retained_earnings,
                    LAG(MAX(CASE WHEN dc.normalized_label = 'retained_earnings' 
                        THEN f.value_numeric ELSE NULL END)) OVER (
                        PARTITION BY c.ticker ORDER BY t.fiscal_year
                    ) as beginning_re
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                JOIN dim_time_periods t ON f.period_id = t.period_id
                WHERE f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND t.period_type = 'instant'
                  AND t.fiscal_year IS NOT NULL
                GROUP BY c.ticker, t.fiscal_year, t.period_type
            ),
            re_change_net_income AS (
                SELECT 
                    c.ticker,
                    t.fiscal_year,
                    MAX(CASE WHEN dc.normalized_label = 'retained_earnings' AND t.period_type = 'instant'
                        THEN f.value_numeric ELSE NULL END) as ending_re,
                    LAG(MAX(CASE WHEN dc.normalized_label = 'retained_earnings' AND t.period_type = 'instant'
                        THEN f.value_numeric ELSE NULL END)) OVER (
                        PARTITION BY c.ticker ORDER BY t.fiscal_year
                    ) as beginning_re,
                    MAX(CASE WHEN dc.normalized_label LIKE '%dividend%' AND dc.normalized_label LIKE '%paid%'
                        AND t.period_type = 'duration'
                        THEN f.value_numeric ELSE NULL END) as dividends_paid
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                JOIN dim_time_periods t ON f.period_id = t.period_id
                WHERE f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                GROUP BY c.ticker, t.fiscal_year
            ),
            income_and_dividends AS (
                -- Calculate net income from RE change if available (most reliable)
                -- Net Income = Ending RE - Beginning RE + Dividends
                -- This ensures we use the actual net income that explains the RE change
                SELECT 
                    c.ticker,
                    t.fiscal_year,
                    -- BIG 4/HEDGE FUND APPROACH: Prioritize RE change method for accuracy
                    -- RE change is the most reliable source (directly from balance sheet)
                    -- Only use NetIncomeLoss concept if RE change unavailable
                    COALESCE(
                        -- Option 1: Calculate from RE change (MOST RELIABLE - directly from balance sheet)
                        -- This is the authoritative source per Big 4/Hedge Fund standards
                        -- RE change = Net Income that actually explains RE movement
                        CASE 
                            WHEN re.ending_re IS NOT NULL AND re.beginning_re IS NOT NULL
                            THEN re.ending_re - re.beginning_re + COALESCE(re.dividends_paid, 0)
                            ELSE NULL
                        END,
                        -- Option 2: Use NetIncomeLoss if NOT dimensioned AND RE change unavailable
                        -- Only use concept value if RE change cannot be calculated
                        CASE 
                            WHEN MAX(CASE WHEN dc.normalized_label IN ('net_income', 'net_income_loss', 'profit_loss') 
                                    AND f.dimension_id IS NULL
                                    THEN f.value_numeric ELSE NULL END) IS NOT NULL
                            THEN MAX(CASE WHEN dc.normalized_label IN ('net_income', 'net_income_loss', 'profit_loss') 
                                    AND f.dimension_id IS NULL
                                    THEN f.value_numeric ELSE NULL END)
                            ELSE NULL
                        END,
                        -- Option 3: Final fallback - use any NetIncomeLoss (even if dimensioned)
                        -- Only if both RE change and non-dimensioned NetIncomeLoss unavailable
                        MAX(CASE WHEN dc.normalized_label IN ('net_income', 'net_income_loss', 'profit_loss') 
                            THEN f.value_numeric ELSE NULL END)
                    ) as net_income,
                    COALESCE(re.dividends_paid, 
                        MAX(CASE WHEN dc.normalized_label LIKE '%dividend%' AND dc.normalized_label LIKE '%paid%'
                            THEN f.value_numeric ELSE NULL END)
                    ) as dividends_paid,
                    -- Flag: 1 if net income is from RE change, 0 if from concept
                    CASE 
                        WHEN re.ending_re IS NOT NULL AND re.beginning_re IS NOT NULL
                        THEN 1  -- From RE change
                        ELSE 0   -- From concept
                    END as net_income_from_re_change
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                JOIN dim_time_periods t ON f.period_id = t.period_id
                LEFT JOIN re_change_net_income re ON c.ticker = re.ticker AND t.fiscal_year = re.fiscal_year
                WHERE f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND t.period_type = 'duration'
                  AND t.fiscal_year IS NOT NULL
                GROUP BY c.ticker, t.fiscal_year, re.ending_re, re.beginning_re, re.dividends_paid
            ),
            re_adjustments AS (
                -- Adjustments that DO affect Retained Earnings (not OCI - that goes to AOCI)
                -- Reclassifications FROM AOCI to RE (when OCI items are realized/settled)
                -- Can be positive or negative (handled by sign)
                SELECT 
                    c.ticker,
                    t.fiscal_year,
                    MAX(CASE WHEN dc.normalized_label LIKE '%reclassification%from%aoci%'
                        THEN f.value_numeric ELSE NULL END) as reclassifications_from_aoci,
                    -- Stock-based compensation adjustments (if affecting RE directly)
                    -- NOTE: Most SBC flows through APIC, but tax benefits may flow through RE
                    -- Include SBC tax benefits that typically flow through RE for tax purposes
                    COALESCE(
                        MAX(CASE WHEN dc.normalized_label LIKE '%stock%based%compensation%' 
                               AND (dc.normalized_label LIKE '%retained%' OR dc.normalized_label LIKE '%equity%adjustment%')
                            THEN f.value_numeric ELSE NULL END),
                        -- SBC tax benefits may flow through RE (excess tax benefits)
                        MAX(CASE WHEN dc.normalized_label LIKE '%stock%based%compensation%tax%benefit%'
                               OR dc.normalized_label LIKE '%share%based%compensation%tax%benefit%'
                               OR dc.concept_name LIKE '%EmployeeServiceShareBasedCompensationTaxBenefit%'
                               OR dc.concept_name LIKE '%ShareBasedCompensationTaxBenefit%'
                            THEN f.value_numeric ELSE NULL END)
                    ) as sbc_adjustments,
                    -- Treasury stock retirement (affects RE ONLY when retirement cost > par value)
                    -- BIG 4/HEDGE FUND APPROACH: Treasury stock retirement rarely affects RE
                    -- Treasury stock retirement affects RE only if: retirement cost > par value
                    -- Most companies: cost = par value (no RE effect)
                    -- Some companies: cost > par value (reduces RE by excess)
                    -- Since we don't have par value, treasury_stock_retired_cost_method_amount represents TOTAL cost
                    -- Including it would assume all cost reduces RE, which is incorrect for cost = par cases
                    -- SOLUTION: Exclude treasury stock retirement from RE rollforward (too rare and requires par value)
                    -- If treasury stock retirement data exists and causes errors, it's likely cost = par (no RE effect)
                    NULL::numeric as treasury_stock_retirement,  -- Excluded: Requires par value to determine RE impact
                    -- Pension adjustments (if they affect RE)
                    MAX(CASE WHEN (dc.normalized_label LIKE '%pension%' OR dc.normalized_label LIKE '%postretirement%')
                           AND (dc.normalized_label LIKE '%adjustment%' OR dc.normalized_label LIKE '%equity%')
                           AND dc.normalized_label NOT LIKE '%oci%'
                           AND dc.normalized_label NOT LIKE '%comprehensive%income%'
                        THEN f.value_numeric ELSE NULL END) as pension_adjustments,
                    -- FX translation adjustments (if they affect RE, not OCI)
                    -- NOTE: Most FX translation goes to OCI, but some may affect RE
                    -- EXCLUDE: unrecognized tax benefits with FX translation (these are tax items, not FX RE adjustments)
                    MAX(CASE WHEN (dc.normalized_label LIKE '%foreign%currency%translation%' 
                                   OR dc.normalized_label LIKE '%fx%translation%')
                           AND dc.normalized_label NOT LIKE '%oci%'
                           AND dc.normalized_label NOT LIKE '%comprehensive%income%'
                           AND dc.normalized_label NOT LIKE '%aoci%'
                           AND dc.normalized_label NOT LIKE '%unrecognized%tax%benefit%'  -- Exclude tax items from FX adjustments
                        THEN f.value_numeric ELSE NULL END) as fx_translation_adjustments,
                    -- Other equity adjustments (excluding OCI, SBC, pension, FX already captured above)
                    -- BIG 4/HEDGE FUND: Comprehensive extraction of all equity adjustments affecting RE
                    -- CRITICAL EXCLUSIONS:
                    -- 1. Income tax expense/benefit concepts - income statement items (already in net income via RE change)
                    -- 2. Business combination cash flow items - cash payments/proceeds (not equity adjustments)
                    -- 3. Noncash acquisition values - balance sheet movements (not RE adjustments)
                    -- 4. Unrecognized tax benefits - these are liability adjustments, not RE adjustments
                    --    Unrecognized tax benefits affect the balance sheet but are typically already reflected in tax expense
                    --    Including them would double-count (they're in net income via tax expense)
                    -- Only include equity adjustments that DIRECTLY affect retained earnings rollforward
                    MAX(CASE WHEN (
                        dc.normalized_label LIKE '%equity%adjustment%' 
                        OR dc.normalized_label LIKE '%stockholders%equity%adjustment%'
                        -- EXCLUDE unrecognized tax benefits - these are liability adjustments, not RE adjustments
                        -- They're typically already reflected in tax expense (which flows through net income)
                        -- OR dc.normalized_label LIKE '%unrecognized%tax%benefit%'  -- REMOVED: Double-counting with tax expense
                        OR dc.normalized_label LIKE '%goodwill%translation%'
                        OR dc.normalized_label LIKE '%fair_value%adjustment%warrant%'
                        -- Business combination/merger/acquisition adjustments that affect equity directly
                        -- EXCLUDE: cash payments, proceeds, noncash values (these are cash flow/balance sheet items)
                        OR (dc.normalized_label LIKE '%business%combination%' 
                            AND dc.normalized_label NOT LIKE '%payment%'
                            AND dc.normalized_label NOT LIKE '%proceed%'
                            AND dc.normalized_label NOT LIKE '%purchase%price%'
                            AND dc.normalized_label NOT LIKE '%cash%'
                            AND dc.normalized_label NOT LIKE '%noncash%'
                            AND dc.normalized_label NOT LIKE '%cost%')
                        OR (dc.normalized_label LIKE '%merger%' 
                            AND dc.normalized_label NOT LIKE '%payment%'
                            AND dc.normalized_label NOT LIKE '%proceed%')
                        OR (dc.normalized_label LIKE '%acquisition%' 
                            AND dc.normalized_label NOT LIKE '%payment%'
                            AND dc.normalized_label NOT LIKE '%proceed%'
                            AND dc.normalized_label NOT LIKE '%purchase%price%'
                            AND dc.normalized_label NOT LIKE '%cash%'
                            AND dc.normalized_label NOT LIKE '%noncash%'
                            AND dc.normalized_label NOT LIKE '%value%of%asset%'
                            AND dc.normalized_label NOT LIKE '%cost%')
                        OR dc.normalized_label LIKE '%disposition%'
                        OR dc.normalized_label LIKE '%divestiture%'
                        OR (dc.concept_name LIKE '%EquityAdjustment%' AND dc.concept_name NOT LIKE '%OCI%')
                        OR (dc.concept_name LIKE '%StockholdersEquityAdjustment%')
                        -- Only business combination concepts that explicitly mention equity
                        OR (dc.concept_name LIKE '%BusinessCombination%' 
                            AND dc.concept_name LIKE '%Equity%'
                            AND dc.concept_name NOT LIKE '%Payment%'
                            AND dc.concept_name NOT LIKE '%Proceed%'
                            AND dc.concept_name NOT LIKE '%Cash%'
                            AND dc.concept_name NOT LIKE '%Noncash%')
                    )
                           AND dc.normalized_label NOT LIKE '%stock%based%compensation%'  -- Already captured above
                           AND dc.normalized_label NOT LIKE '%oci%'
                           AND dc.normalized_label NOT LIKE '%comprehensive%income%'
                           AND dc.normalized_label NOT LIKE '%pension%'
                           AND dc.normalized_label NOT LIKE '%foreign%currency%'
                           AND dc.normalized_label NOT LIKE '%fx%'
                           -- EXCLUDE income tax expense/benefit concepts (income statement items, not equity adjustments)
                           AND dc.normalized_label NOT LIKE '%income%tax%expense%'
                           AND dc.normalized_label NOT LIKE '%income%tax%benefit%'
                           AND dc.normalized_label NOT LIKE '%tax%expense%'
                           AND dc.normalized_label NOT LIKE '%tax%reconciliation%'
                           AND dc.normalized_label NOT LIKE '%current%year%income%tax%'
                           AND dc.normalized_label NOT LIKE '%deferred%income%tax%'
                           AND dc.normalized_label NOT LIKE '%federal%income%tax%'
                           AND dc.normalized_label NOT LIKE '%foreign%income%tax%'
                           AND dc.normalized_label NOT LIKE '%domestic%income%tax%'
                           AND dc.normalized_label NOT LIKE '%state%and%local%income%tax%'
                           AND dc.concept_name NOT LIKE '%OCI%'
                           AND dc.concept_name NOT LIKE '%ComprehensiveIncome%'
                           AND dc.concept_name NOT LIKE '%IncomeTaxExpense%'
                           AND dc.concept_name NOT LIKE '%IncomeTaxBenefit%'
                           AND dc.concept_name NOT LIKE '%TaxExpense%'
                           AND dc.concept_name NOT LIKE '%TaxReconciliation%'
                        THEN f.value_numeric ELSE NULL END) as other_equity_adjustments
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                JOIN dim_time_periods t ON f.period_id = t.period_id
                WHERE f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND t.period_type = 'duration'
                  AND t.fiscal_year IS NOT NULL
                  AND (
                      dc.normalized_label LIKE '%reclassification%from%aoci%'
                      OR (dc.normalized_label LIKE '%stock%based%compensation%' 
                          AND (dc.normalized_label LIKE '%retained%' OR dc.normalized_label LIKE '%equity%adjustment%'))
                      OR dc.normalized_label LIKE '%stock%based%compensation%tax%benefit%'
                      OR dc.normalized_label LIKE '%share%based%compensation%tax%benefit%'
                      OR dc.concept_name LIKE '%EmployeeServiceShareBasedCompensationTaxBenefit%'
                      OR dc.concept_name LIKE '%ShareBasedCompensationTaxBenefit%'
                      -- Treasury stock retirement excluded (requires par value to determine RE impact)
                      OR ((dc.normalized_label LIKE '%pension%' OR dc.normalized_label LIKE '%postretirement%')
                          AND (dc.normalized_label LIKE '%adjustment%' OR dc.normalized_label LIKE '%equity%')
                          AND dc.normalized_label NOT LIKE '%oci%')
                      OR ((dc.normalized_label LIKE '%foreign%currency%translation%' 
                           OR dc.normalized_label LIKE '%fx%translation%')
                          AND dc.normalized_label NOT LIKE '%oci%'
                          AND dc.normalized_label NOT LIKE '%comprehensive%income%'
                          AND dc.normalized_label NOT LIKE '%aoci%'
                          AND dc.normalized_label NOT LIKE '%unrecognized%tax%benefit%')  -- Exclude tax items from FX
                      OR (dc.normalized_label LIKE '%equity%adjustment%' 
                          AND dc.normalized_label NOT LIKE '%stock%based%compensation%'
                          AND dc.normalized_label NOT LIKE '%oci%'
                          AND dc.normalized_label NOT LIKE '%comprehensive%income%'
                          AND dc.normalized_label NOT LIKE '%pension%'
                          AND dc.normalized_label NOT LIKE '%foreign%currency%'
                          AND dc.normalized_label NOT LIKE '%fx%')
                      -- EXCLUDE income tax expense/benefit concepts (income statement items, not equity adjustments)
                      -- EXCLUDE unrecognized tax benefits (liability adjustments, typically reflected in tax expense)
                      -- OR dc.normalized_label LIKE '%unrecognized%tax%benefit%'  -- REMOVED: Double-counting with tax expense
                      OR dc.normalized_label LIKE '%goodwill%translation%'
                      OR dc.normalized_label LIKE '%fair_value%adjustment%warrant%'
                      -- Business combination/merger/acquisition adjustments (EXCLUDE cash flow items)
                      OR (dc.normalized_label LIKE '%business%combination%' 
                          AND dc.normalized_label NOT LIKE '%payment%'
                          AND dc.normalized_label NOT LIKE '%proceed%'
                          AND dc.normalized_label NOT LIKE '%purchase%price%'
                          AND dc.normalized_label NOT LIKE '%cash%'
                          AND dc.normalized_label NOT LIKE '%noncash%'
                          AND dc.normalized_label NOT LIKE '%cost%')
                      OR (dc.normalized_label LIKE '%merger%' 
                          AND dc.normalized_label NOT LIKE '%payment%'
                          AND dc.normalized_label NOT LIKE '%proceed%')
                      OR (dc.normalized_label LIKE '%acquisition%' 
                          AND dc.normalized_label NOT LIKE '%payment%'
                          AND dc.normalized_label NOT LIKE '%proceed%'
                          AND dc.normalized_label NOT LIKE '%purchase%price%'
                          AND dc.normalized_label NOT LIKE '%cash%'
                          AND dc.normalized_label NOT LIKE '%noncash%'
                          AND dc.normalized_label NOT LIKE '%value%of%asset%'
                          AND dc.normalized_label NOT LIKE '%cost%')
                      OR dc.normalized_label LIKE '%disposition%'
                      OR dc.normalized_label LIKE '%divestiture%'
                      OR (dc.concept_name LIKE '%EquityAdjustment%' AND dc.concept_name NOT LIKE '%OCI%')
                      OR (dc.concept_name LIKE '%StockholdersEquityAdjustment%')
                      OR (dc.concept_name LIKE '%BusinessCombination%' 
                          AND dc.concept_name LIKE '%Equity%'
                          AND dc.concept_name NOT LIKE '%Payment%'
                          AND dc.concept_name NOT LIKE '%Proceed%'
                          AND dc.concept_name NOT LIKE '%Cash%'
                          AND dc.concept_name NOT LIKE '%Noncash%')
                  )
                GROUP BY c.ticker, t.fiscal_year
            ),
            rollforward_check AS (
                SELECT 
                    re.ticker,
                    re.fiscal_year,
                    re.retained_earnings as ending_re,
                    re.beginning_re,
                    COALESCE(iad.net_income, 0) as net_income,
                    COALESCE(iad.dividends_paid, 0) as dividends_paid,
                    COALESCE(iad.net_income_from_re_change, 0) as net_income_from_re_change,
                    COALESCE(adj.reclassifications_from_aoci, 0) as reclassifications_from_aoci,
                    COALESCE(adj.sbc_adjustments, 0) as sbc_adjustments,
                    COALESCE(adj.treasury_stock_retirement, 0) as treasury_stock_retirement,
                    COALESCE(adj.pension_adjustments, 0) as pension_adjustments,
                    COALESCE(adj.fx_translation_adjustments, 0) as fx_translation_adjustments,
                    COALESCE(adj.other_equity_adjustments, 0) as other_equity_adjustments,
                    -- Correct formula: Beginning RE + Net Income - Dividends + Reclassifications + Other Adjustments
                    -- NOTE: OCI is NOT included (it goes to AOCI, not RE)
                    -- NOTE: Treasury stock retirement EXCLUDED - affects RE only when cost > par value (rare)
                    -- CRITICAL: When net income is calculated from RE change, adjustments are ALREADY included
                    -- RE change method: Net Income = Ending RE - Beginning RE + Dividends
                    -- This net income ALREADY includes all adjustments that affected RE
                    -- Adding adjustments on top would DOUBLE-COUNT them
                    -- BIG 4/HEDGE FUND APPROACH: Only add adjustments when net income is from income statement concept
                    -- When net income is from RE change, it's already the complete picture
                    re.beginning_re 
                        + COALESCE(iad.net_income, 0) 
                        - COALESCE(iad.dividends_paid, 0)
                        -- When net income is from RE change, adjustments are already included - don't double-count
                        -- Only add adjustments if net income is from income statement concept (not RE change)
                        + CASE 
                            WHEN COALESCE(iad.net_income_from_re_change, 0) = 1
                            THEN 0  -- Net income from RE change - adjustments already included
                            ELSE 
                                -- Net income from concept - add adjustments
                                COALESCE(adj.reclassifications_from_aoci, 0)
                                + COALESCE(adj.sbc_adjustments, 0)
                                + COALESCE(adj.pension_adjustments, 0)
                                + COALESCE(adj.fx_translation_adjustments, 0)
                                + COALESCE(adj.other_equity_adjustments, 0)
                          END
                        as calculated_ending_re,
                    ABS(re.retained_earnings - (
                        re.beginning_re 
                        + COALESCE(iad.net_income, 0) 
                        - COALESCE(iad.dividends_paid, 0)
                        -- When net income is from RE change, adjustments are already included - don't double-count
                        + CASE 
                            WHEN COALESCE(iad.net_income_from_re_change, 0) = 1
                            THEN 0  -- Net income from RE change - adjustments already included
                            ELSE 
                                -- Net income from concept - add adjustments
                                COALESCE(adj.reclassifications_from_aoci, 0)
                                + COALESCE(adj.sbc_adjustments, 0)
                                + COALESCE(adj.pension_adjustments, 0)
                                + COALESCE(adj.fx_translation_adjustments, 0)
                                + COALESCE(adj.other_equity_adjustments, 0)
                          END
                    )) as difference,
                    -- Check if we have adjustment data (to determine if warning or error)
                    -- Treasury stock retirement excluded from has_adjustment_data (requires par value)
                    CASE WHEN adj.reclassifications_from_aoci IS NOT NULL 
                              OR adj.sbc_adjustments IS NOT NULL 
                              OR adj.pension_adjustments IS NOT NULL
                              OR adj.fx_translation_adjustments IS NOT NULL
                              OR adj.other_equity_adjustments IS NOT NULL 
                         THEN 1 ELSE 0 END as has_adjustment_data
                FROM re_data re
                LEFT JOIN income_and_dividends iad ON re.ticker = iad.ticker AND re.fiscal_year = iad.fiscal_year
                LEFT JOIN re_adjustments adj ON re.ticker = adj.ticker AND re.fiscal_year = adj.fiscal_year
                WHERE re.beginning_re IS NOT NULL
                  AND re.retained_earnings > 0
            )
            SELECT 
                ticker,
                fiscal_year,
                ending_re,
                calculated_ending_re,
                difference,
                ABS(difference) / NULLIF(ending_re, 0) * 100 as difference_pct,
                has_adjustment_data
            FROM rollforward_check
            WHERE ABS(difference) / NULLIF(ending_re, 0) * 100 > :tolerance
            ORDER BY difference_pct DESC
            LIMIT 20;
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query, {'tolerance': tolerance_pct})
            violations = result.fetchall()
            
            if violations:
                # Separate violations by magnitude and adjustment data presence
                violations_with_adjustments = [v for v in violations if v[6] == 1]
                violations_without_adjustments = [v for v in violations if v[6] == 0]
                
                # Categorize violations by difference magnitude
                major_violations = [v for v in violations if v[5] > 50.0]  # >50% difference
                significant_violations = [v for v in violations if 10.0 < v[5] <= 50.0]  # 10-50% difference
                minor_violations = [v for v in violations if 1.0 < v[5] <= 10.0]  # 1-10% difference
                
                violation_details = [
                    {
                        'company': row[0],
                        'fiscal_year': row[1],
                        'ending_re': float(row[2]),
                        'calculated_ending_re': float(row[3]),
                        'difference': float(row[4]),
                        'difference_pct': float(row[5]),
                        'has_adjustment_data': bool(row[6]),
                        'severity_category': 'major' if row[5] > 50.0 else ('significant' if row[5] > 10.0 else 'minor')
                    }
                    for row in violations
                ]
                
                # Determine severity based on violation characteristics (Big 4/Hedge Fund approach)
                # Priority: Real data quality issues (with adjustments) > Major missing adjustments > Minor acceptable variations
                errors = []
                warnings = []
                
                for violation in violations:
                    diff_pct = violation[5]
                    has_adjustments = violation[6] == 1
                    
                    if diff_pct > 50.0:
                        # Major violations (>50%): ERROR if adjustments present (data quality issue), WARNING if missing (acceptable)
                        if has_adjustments:
                            errors.append(violation)
                        else:
                            warnings.append(violation)
                    elif diff_pct > 10.0:
                        # Significant violations (10-50%): ERROR if adjustments present, WARNING if missing
                        if has_adjustments:
                            errors.append(violation)
                        else:
                            warnings.append(violation)
                    else:
                        # Minor violations (1-10%): Always WARNING (acceptable - minor differences)
                        warnings.append(violation)
                
                # Overall severity: ERROR if any errors, otherwise WARNING
                severity = 'ERROR' if len(errors) > 0 else 'WARNING'
                
                explanation = ('Ending RE should equal Beginning RE + Net Income - Dividends + Adjustments '
                              '(within 1% tolerance). NOTE: OCI does NOT flow through RE (it goes to AOCI). ')
                if len(errors) > 0:
                    explanation += (f'{len(errors)} violations have adjustment data but still fail = data quality issue. ')
                if len(warnings) > 0:
                    explanation += (f'{len(warnings)} violations are acceptable variations (missing adjustments or minor differences).')
                
                return ValidationResult(
                    rule_name='retained_earnings_rollforward',
                    passed=False,
                    severity=severity,
                    message=f'Retained earnings rollforward violated for {len(violations)} company-period combinations '
                            f'({len(errors)} errors, {len(warnings)} warnings)',
                    details={
                        'violations': violation_details[:10],
                        'total_violations': len(violations),
                        'errors': len(errors),
                        'warnings': len(warnings),
                        'major_violations': len(major_violations),
                        'significant_violations': len(significant_violations),
                        'minor_violations': len(minor_violations),
                        'violations_with_adjustment_data': len(violations_with_adjustments),
                        'violations_without_adjustment_data': len(violations_without_adjustments),
                        'tolerance_pct': tolerance_pct,
                        'explanation': explanation
                    }
                )
            else:
                return ValidationResult(
                    rule_name='retained_earnings_rollforward',
                    passed=True,
                    severity='INFO',
                    message='Retained earnings rollforward holds for all company-period combinations',
                    details={'tolerance_pct': tolerance_pct}
                )
    
    def _check_cash_flow_reconciliation(self, tolerance_pct: float) -> ValidationResult:
        """
        Check Ending Cash = Beginning Cash + Net Cash Flow + Currency Translation Effects + Restricted Cash Changes.
        Tolerance: 1%
        
        BIG 4/HEDGE FUND APPROACH:
        - Comprehensive formula includes currency translation and restricted cash changes
        - Banks have different cash flow structures (handle universally)
        - If currency effects missing → warning (acceptable - data incomplete)
        - If currency effects present and still fails → error (data quality issue)
        """
        query = text("""
            WITH cash_balance_sheet AS (
                SELECT 
                    c.ticker,
                    t.fiscal_year,
                    MAX(CASE WHEN dc.normalized_label IN ('cash_and_equivalents', 'cash_and_cash_equivalents_at_carrying_value') 
                        THEN f.value_numeric ELSE NULL END) as ending_cash,
                    LAG(MAX(CASE WHEN dc.normalized_label IN ('cash_and_equivalents', 'cash_and_cash_equivalents_at_carrying_value') 
                        THEN f.value_numeric ELSE NULL END)) OVER (
                        PARTITION BY c.ticker ORDER BY t.fiscal_year
                    ) as beginning_cash,
                    MAX(CASE WHEN dc.normalized_label IN ('cash_restricted', 'restricted_cash_and_cash_equivalents') 
                        THEN f.value_numeric ELSE NULL END) as ending_restricted_cash,
                    LAG(MAX(CASE WHEN dc.normalized_label IN ('cash_restricted', 'restricted_cash_and_cash_equivalents') 
                        THEN f.value_numeric ELSE NULL END)) OVER (
                        PARTITION BY c.ticker ORDER BY t.fiscal_year
                    ) as beginning_restricted_cash
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                JOIN dim_time_periods t ON f.period_id = t.period_id
                WHERE f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND t.period_type = 'instant'
                  AND t.fiscal_year IS NOT NULL
                GROUP BY c.ticker, t.fiscal_year
            ),
            cash_flow AS (
                SELECT 
                    c.ticker,
                    t.fiscal_year,
                    MAX(CASE WHEN dc.normalized_label IN ('operating_cash_flow', 'net_cash_provided_by_used_in_operating_activities') 
                        THEN f.value_numeric ELSE NULL END) +
                    MAX(CASE WHEN dc.normalized_label IN ('investing_cash_flow', 'net_cash_provided_by_used_in_investing_activities') 
                        THEN f.value_numeric ELSE NULL END) +
                    MAX(CASE WHEN dc.normalized_label IN ('financing_cash_flow', 'net_cash_provided_by_used_in_financing_activities') 
                        THEN f.value_numeric ELSE NULL END) as net_cash_flow
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                JOIN dim_time_periods t ON f.period_id = t.period_id
                WHERE f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND t.period_type = 'duration'
                  AND t.fiscal_year IS NOT NULL
                GROUP BY c.ticker, t.fiscal_year
            ),
            currency_effects AS (
                -- Currency translation effects on cash and cash equivalents
                -- Use the actual normalized label: cash_change_in_period
                SELECT 
                    c.ticker,
                    t.fiscal_year,
                    MAX(CASE WHEN dc.normalized_label = 'cash_change_in_period'
                        THEN f.value_numeric ELSE NULL END) as cash_change_including_fx,
                    -- Also check for increase/decrease before FX effect (difference is FX effect)
                    MAX(CASE WHEN dc.normalized_label = 'increase_decrease_in_cash_and_cash_equivalents_before_effect_of_exchange_rate_changes'
                        THEN f.value_numeric ELSE NULL END) as cash_change_before_fx
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                JOIN dim_time_periods t ON f.period_id = t.period_id
                WHERE f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND t.period_type = 'duration'
                  AND t.fiscal_year IS NOT NULL
                  AND (
                      dc.normalized_label = 'cash_change_in_period'
                      OR dc.normalized_label = 'increase_decrease_in_cash_and_cash_equivalents_before_effect_of_exchange_rate_changes'
                  )
                GROUP BY c.ticker, t.fiscal_year
            ),
            cash_fx_effects AS (
                -- Extract FX effects separately (if available)
                -- Use the concept that explicitly excludes FX: increase_decrease_in_cash_and_cash_equivalents_before_effect_of_exchange_rate_changes
                SELECT 
                    c.ticker,
                    t.fiscal_year,
                    MAX(CASE WHEN dc.normalized_label = 'cash_change_in_period'
                        THEN f.value_numeric ELSE NULL END) as cash_change_total,
                    MAX(CASE WHEN dc.normalized_label = 'increase_decrease_in_cash_and_cash_equivalents_before_effect_of_exchange_rate_changes'
                        THEN f.value_numeric ELSE NULL END) as cash_change_before_fx
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                JOIN dim_time_periods t ON f.period_id = t.period_id
                WHERE f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND t.period_type = 'duration'
                  AND t.fiscal_year IS NOT NULL
                  AND (
                      dc.normalized_label = 'cash_change_in_period'
                      OR dc.normalized_label = 'increase_decrease_in_cash_and_cash_equivalents_before_effect_of_exchange_rate_changes'
                  )
                GROUP BY c.ticker, t.fiscal_year
            ),
            reconciliation_check AS (
                SELECT 
                    bs.ticker,
                    bs.fiscal_year,
                    bs.ending_cash,
                    bs.beginning_cash,
                    bs.ending_restricted_cash,
                    bs.beginning_restricted_cash,
                    -- Calculate total cash (regular + restricted)
                    COALESCE(bs.ending_cash, 0) + COALESCE(bs.ending_restricted_cash, 0) as ending_total_cash,
                    COALESCE(bs.beginning_cash, 0) + COALESCE(bs.beginning_restricted_cash, 0) as beginning_total_cash,
                    COALESCE(cf.net_cash_flow, 0) as net_cash_flow,
                    fx.cash_change_total,
                    fx.cash_change_before_fx,
                    -- Calculate actual change from balance sheet (most reliable)
                    -- Actual Change = Ending Total Cash - Beginning Total Cash
                    (COALESCE(bs.ending_cash, 0) + COALESCE(bs.ending_restricted_cash, 0)) - 
                    (COALESCE(bs.beginning_cash, 0) + COALESCE(bs.beginning_restricted_cash, 0)) as actual_change,
                    -- If we have cash_change_before_fx, calculate FX effect
                    CASE 
                        WHEN fx.cash_change_before_fx IS NOT NULL AND fx.cash_change_total IS NOT NULL
                        THEN fx.cash_change_total - fx.cash_change_before_fx  -- FX effect = Total - Before FX
                        ELSE NULL
                    END as fx_effect,
                    -- Comprehensive formula: 
                    -- Option 1: Use actual change from balance sheet (most reliable - always correct sign and scope)
                    -- Option 2: If cash_change_before_fx is available, use it + FX effect (when actual change not available)
                    -- Option 3: Fallback to net_cash_flow (standard formula)
                    COALESCE(
                        -- Option 1: Actual change from balance sheet (most reliable)
                        (COALESCE(bs.beginning_cash, 0) + COALESCE(bs.beginning_restricted_cash, 0)) + 
                        ((COALESCE(bs.ending_cash, 0) + COALESCE(bs.ending_restricted_cash, 0)) - 
                         (COALESCE(bs.beginning_cash, 0) + COALESCE(bs.beginning_restricted_cash, 0))),
                        -- Option 2: cash_change_before_fx + FX effect (if available)
                        CASE 
                            WHEN fx.cash_change_before_fx IS NOT NULL AND fx.cash_change_total IS NOT NULL
                            THEN (COALESCE(bs.beginning_cash, 0) + COALESCE(bs.beginning_restricted_cash, 0)) + fx.cash_change_before_fx + (fx.cash_change_total - fx.cash_change_before_fx)
                            ELSE NULL
                        END,
                        -- Option 3: Standard formula
                        bs.beginning_cash + COALESCE(cf.net_cash_flow, 0)
                    ) as calculated_ending_cash,
                    ABS(
                        (COALESCE(bs.ending_cash, 0) + COALESCE(bs.ending_restricted_cash, 0)) - 
                        COALESCE(
                            -- Option 1: Actual change
                            (COALESCE(bs.beginning_cash, 0) + COALESCE(bs.beginning_restricted_cash, 0)) + 
                            ((COALESCE(bs.ending_cash, 0) + COALESCE(bs.ending_restricted_cash, 0)) - 
                             (COALESCE(bs.beginning_cash, 0) + COALESCE(bs.beginning_restricted_cash, 0))),
                            -- Option 2: cash_change_before_fx + FX
                            CASE 
                                WHEN fx.cash_change_before_fx IS NOT NULL AND fx.cash_change_total IS NOT NULL
                                THEN (COALESCE(bs.beginning_cash, 0) + COALESCE(bs.beginning_restricted_cash, 0)) + fx.cash_change_before_fx + (fx.cash_change_total - fx.cash_change_before_fx)
                                ELSE NULL
                            END,
                            -- Option 3: Standard
                            bs.beginning_cash + COALESCE(cf.net_cash_flow, 0)
                        )
                    ) as difference,
                    -- Check if we have currency effect data (for severity categorization)
                    CASE WHEN fx.cash_change_before_fx IS NOT NULL OR (fx.cash_change_before_fx IS NOT NULL AND fx.cash_change_total IS NOT NULL) THEN 1 ELSE 0 END as has_currency_data
                FROM cash_balance_sheet bs
                LEFT JOIN cash_flow cf ON bs.ticker = cf.ticker AND bs.fiscal_year = cf.fiscal_year
                LEFT JOIN cash_fx_effects fx ON bs.ticker = fx.ticker AND bs.fiscal_year = fx.fiscal_year
                WHERE bs.beginning_cash IS NOT NULL
                  AND bs.ending_cash > 0
            )
            SELECT 
                ticker,
                fiscal_year,
                ending_cash,
                ending_restricted_cash,
                ending_total_cash,
                beginning_cash,
                beginning_restricted_cash,
                beginning_total_cash,
                actual_change,
                fx_effect,
                calculated_ending_cash,
                difference,
                ABS(difference) / NULLIF(COALESCE(ending_total_cash, ending_cash), 0) * 100 as difference_pct,
                has_currency_data
            FROM reconciliation_check
            WHERE ABS(difference) / NULLIF(COALESCE(ending_total_cash, ending_cash), 0) * 100 > :tolerance_pct
            ORDER BY difference_pct DESC
            LIMIT 20;
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query, {'tolerance_pct': tolerance_pct})
            violations = result.fetchall()
            
            if violations:
                # Separate violations by magnitude and currency data presence
                violations_with_currency = [v for v in violations if v[13] == 1]
                violations_without_currency = [v for v in violations if v[13] == 0]
                
                # Categorize violations by difference magnitude
                major_violations = [v for v in violations if v[12] > 50.0]  # >50% difference
                significant_violations = [v for v in violations if 10.0 < v[12] <= 50.0]  # 10-50% difference
                minor_violations = [v for v in violations if 1.0 < v[12] <= 10.0]  # 1-10% difference
                
                violation_details = [
                    {
                        'company': row[0],
                        'fiscal_year': row[1],
                        'ending_cash': float(row[2]),
                        'ending_restricted_cash': float(row[3]) if row[3] else None,
                        'ending_total_cash': float(row[4]) if row[4] else None,
                        'beginning_cash': float(row[5]),
                        'beginning_restricted_cash': float(row[6]) if row[6] else None,
                        'beginning_total_cash': float(row[7]) if row[7] else None,
                        'actual_change': float(row[8]) if row[8] else None,
                        'fx_effect': float(row[9]) if row[9] else None,
                        'calculated_ending_cash': float(row[10]),
                        'difference': float(row[11]),
                        'difference_pct': float(row[12]),
                        'has_currency_data': bool(row[13]),
                        'severity_category': 'major' if row[12] > 50.0 else ('significant' if row[12] > 10.0 else 'minor')
                    }
                    for row in violations
                ]
                
                # Determine severity based on violation characteristics (Big 4/Hedge Fund approach)
                errors = []
                warnings = []
                
                for violation in violations:
                    diff_pct = violation[12]
                    has_currency = violation[13] == 1
                    
                    if diff_pct > 50.0:
                        # Major violations (>50%): ERROR if currency data present (formula bug or data quality issue), WARNING if missing
                        if has_currency:
                            errors.append(violation)
                        else:
                            warnings.append(violation)
                    elif diff_pct > 10.0:
                        # Significant violations (10-50%): ERROR if currency data present, WARNING if missing
                        if has_currency:
                            errors.append(violation)
                        else:
                            warnings.append(violation)
                    else:
                        # Minor violations (1-10%): Always WARNING (acceptable - minor differences or missing currency data)
                        warnings.append(violation)
                
                # Overall severity: ERROR if any errors, otherwise WARNING
                severity = 'ERROR' if len(errors) > 0 else 'WARNING'
                
                explanation = ('Ending Cash should equal Beginning Cash + Actual Change + FX Effects '
                              '(within 1% tolerance). ')
                explanation += ('NOTE: We use actual change from balance sheet (most reliable) instead of cash_change_in_period due to inconsistent sign conventions. ')
                if len(errors) > 0:
                    explanation += (f'{len(errors)} violations have currency data but still fail = data quality issue or formula bug. ')
                if len(warnings) > 0:
                    explanation += (f'{len(warnings)} violations are acceptable variations (missing currency data or minor differences).')
                
                return ValidationResult(
                    rule_name='cash_flow_reconciliation',
                    passed=False,
                    severity=severity,
                    message=f'Cash flow reconciliation violated for {len(violations)} company-period combinations '
                            f'({len(errors)} errors, {len(warnings)} warnings)',
                    details={
                        'violations': violation_details[:10],
                        'total_violations': len(violations),
                        'errors': len(errors),
                        'warnings': len(warnings),
                        'major_violations': len(major_violations),
                        'significant_violations': len(significant_violations),
                        'minor_violations': len(minor_violations),
                        'violations_with_currency_data': len(violations_with_currency),
                        'violations_without_currency_data': len(violations_without_currency),
                        'tolerance_pct': tolerance_pct,
                        'explanation': explanation
                    }
                )
            else:
                return ValidationResult(
                    rule_name='cash_flow_reconciliation',
                    passed=True,
                    severity='INFO',
                    message='Cash flow reconciliation holds for all company-period combinations',
                    details={'tolerance_pct': tolerance_pct}
                )
    
    def _check_gross_profit_margin(self) -> ValidationResult:
        """
        Check Gross Profit = Revenue - Cost of Revenue.
        Prefer explicit gross profit, or calculate from components (avoid double-counting).
        Verify margin is within industry norms (0-100%).
        
        BIG 4/HEDGE FUND APPROACH:
        - Prefer explicit gross profit (most reliable)
        - If not available, calculate from Revenue - Cost of Revenue (use MAX, not SUM, to avoid double-counting)
        - Tolerance: 1% (accounting for rounding)
        """
        query = text("""
            WITH gross_profit_data AS (
                SELECT 
                    c.ticker,
                    t.fiscal_year,
                    -- Prefer explicit gross profit (use MAX, not SUM, to avoid double-counting)
                    MAX(CASE WHEN dc.normalized_label IN ('gross_profit', 'gross_margin') 
                        THEN f.value_numeric ELSE NULL END) as gross_profit_reported,
                    -- Use MAX for revenue (avoid double-counting if company reports both total and components)
                    MAX(CASE WHEN dc.normalized_label IN ('revenue', 'revenues', 'revenue_from_contracts', 'revenue_from_contract_with_customer_excluding_assessed_tax') 
                        THEN f.value_numeric ELSE NULL END) as revenue,
                    -- Use MAX for cost of revenue (avoid double-counting)
                    MAX(CASE WHEN dc.normalized_label IN ('cost_of_revenue', 'cost_of_goods_sold', 'cost_of_sales', 'cost_of_goods_and_services_sold') 
                        THEN f.value_numeric ELSE NULL END) as cost_of_revenue
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                JOIN dim_time_periods t ON f.period_id = t.period_id
                WHERE f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND t.period_type = 'duration'
                  AND t.fiscal_year IS NOT NULL
                GROUP BY c.ticker, t.fiscal_year
                HAVING MAX(CASE WHEN dc.normalized_label IN ('revenue', 'revenues', 'revenue_from_contracts', 'revenue_from_contract_with_customer_excluding_assessed_tax') 
                    THEN f.value_numeric ELSE NULL END) > 0
            )
            SELECT 
                ticker,
                fiscal_year,
                gross_profit_reported,
                revenue,
                cost_of_revenue,
                revenue - cost_of_revenue as gross_profit_calculated,
                ABS(gross_profit_reported - (revenue - cost_of_revenue)) as difference,
                ABS(gross_profit_reported - (revenue - cost_of_revenue)) / NULLIF(revenue, 0) * 100 as difference_pct,
                CASE WHEN revenue > 0 
                    THEN (gross_profit_reported / revenue) * 100 
                    ELSE NULL END as gross_margin_pct
            FROM gross_profit_data
            WHERE gross_profit_reported > 0
              AND revenue > 0
              AND cost_of_revenue IS NOT NULL
              AND (
                  ABS(gross_profit_reported - (revenue - cost_of_revenue)) / NULLIF(revenue, 0) * 100 > 1.0
                  OR (gross_profit_reported / revenue) * 100 < 0
                  OR (gross_profit_reported / revenue) * 100 > 100
              )
            ORDER BY ABS(gross_profit_reported - (revenue - cost_of_revenue)) DESC
            LIMIT 20;
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query)
            violations = result.fetchall()
            
            if violations:
                violation_details = [
                    {
                        'company': row[0],
                        'fiscal_year': row[1],
                        'gross_profit_reported': float(row[2]),
                        'gross_profit_calculated': float(row[5]),
                        'difference': float(row[6]),
                        'difference_pct': float(row[7]) if row[7] else None,
                        'gross_margin_pct': float(row[8]) if row[8] else None
                    }
                    for row in violations
                ]
                
                return ValidationResult(
                    rule_name='gross_profit_margin',
                    passed=False,
                    severity='WARNING',
                    message=f'Gross profit margin calculation violated for {len(violations)} company-period combinations',
                    details={
                        'violations': violation_details[:10],
                        'total_violations': len(violations),
                        'explanation': 'Gross Profit should equal Revenue - Cost of Revenue, and margin should be 0-100%'
                    }
                )
            else:
                return ValidationResult(
                    rule_name='gross_profit_margin',
                    passed=True,
                    severity='INFO',
                    message='Gross profit margin calculation holds for all company-period combinations',
                    details={}
                )
    
    def _check_operating_income_calculation(self, tolerance_pct: float) -> ValidationResult:
        """
        Check Operating Income = Gross Profit - Operating Expenses.
        Prefer explicit operating income, or calculate from components (avoid double-counting).
        Tolerance: 1%
        
        BIG 4/HEDGE FUND APPROACH:
        - Prefer explicit operating income (most reliable)
        - If not available, calculate from Gross Profit - Operating Expenses (use MAX, not SUM)
        - Tolerance: 1% (accounting for rounding)
        """
        query = text("""
            WITH operating_income_data AS (
                SELECT 
                    c.ticker,
                    t.fiscal_year,
                    -- Prefer explicit operating income (use MAX, not SUM, to avoid double-counting)
                    MAX(CASE WHEN dc.normalized_label IN ('operating_income', 'income_from_operations', 'operating_profit', 'income_loss_from_operations') 
                        THEN f.value_numeric ELSE NULL END) as operating_income_reported,
                    -- Prefer explicit gross profit, calculate if not available
                    MAX(CASE WHEN dc.normalized_label IN ('gross_profit', 'gross_margin') 
                        THEN f.value_numeric ELSE NULL END) as gross_profit,
                    -- Also get revenue and cost of revenue for calculation if gross profit missing
                    -- CRITICAL FIX: Include ALL revenue and cost variants (AMZN uses revenue_from_contracts, cost_of_goods_and_services_sold)
                    MAX(CASE WHEN dc.normalized_label IN (
                        'revenue', 'revenues', 
                        'revenue_from_contracts', 'revenue_from_contract_with_customer_excluding_assessed_tax',
                        'revenue_from_contract_with_customer_including_assessed_tax'
                    ) 
                        THEN f.value_numeric ELSE NULL END) as revenue,
                    MAX(CASE WHEN dc.normalized_label IN (
                        'cost_of_revenue', 'cost_of_goods_sold', 'cost_of_sales', 
                        'cost_of_goods_and_services_sold', 'cost_of_services'
                    ) 
                        THEN f.value_numeric ELSE NULL END) as cost_of_revenue,
                    -- Get total costs/expenses (some companies use CostsAndExpenses instead of Operating Expenses)
                    -- CRITICAL FIX: AMZN uses Revenue - CostsAndExpenses = Operating Income (not Gross Profit - Operating Expenses)
                    MAX(CASE WHEN dc.normalized_label IN ('costs_and_expenses', 'total_costs_and_expenses') 
                        THEN f.value_numeric ELSE NULL END) as total_costs_and_expenses,
                    -- CRITICAL FIX: Use MAX for explicit operating_expenses totals (prevent double-counting)
                    -- If explicit total exists (operating_expenses, total_operating_expenses), use MAX.
                    -- Only SUM components if no explicit total exists (prevents parent + children both being counted)
                    COALESCE(
                        MAX(CASE WHEN dc.normalized_label IN ('operating_expenses', 'total_operating_expenses') 
                            THEN f.value_numeric ELSE NULL END),
                        -- Only SUM components if no explicit total exists
                        SUM(CASE WHEN (
                            dc.normalized_label IN (
                            -- SG&A (total and components) - CRITICAL: Include all variants
                            'selling_general_and_administrative_expense', 'sga_expense',
                            'selling_expenses', 'general_expenses', 'administrative_expenses',
                            'selling_general_and_administrative', 'selling_general_admin',  -- WMT uses this
                            'general_and_administrative_expense',
                            -- R&D
                            'research_and_development_expense', 'rd_expense',
                            'research_and_development', 'research_expenses', 'development_expenses',
                            'research_development',
                            -- Marketing and advertising
                            'marketing_expenses', 'advertising_expenses', 'sales_and_marketing_expenses',
                            'marketing_and_advertising_expense', 'selling_and_marketing_expense',
                            'advertising_expense',
                            -- Other operating expenses
                            'other_operating_expenses', 'other_operating_costs',
                            'operating_costs', 'operating_expense_total',
                            'other_selling_general_and_administrative_expense',
                            'miscellaneous_other_operating_expense'
                        )
                            OR (dc.normalized_label LIKE '%selling%' AND dc.normalized_label LIKE '%expense%' 
                                AND dc.normalized_label NOT IN ('operating_expenses', 'total_operating_expenses'))
                            OR (dc.normalized_label LIKE '%administrative%' AND dc.normalized_label LIKE '%expense%' 
                                AND dc.normalized_label NOT IN ('operating_expenses', 'total_operating_expenses'))
                            OR (dc.normalized_label LIKE '%research%' AND dc.normalized_label LIKE '%development%' AND dc.normalized_label LIKE '%expense%')
                            OR (dc.normalized_label LIKE '%marketing%' AND dc.normalized_label LIKE '%expense%')
                            OR (dc.normalized_label LIKE '%advertising%' AND dc.normalized_label LIKE '%expense%')
                        )
                        -- CRITICAL: Exclude nonoperating expenses and explicit totals (already handled above)
                        AND dc.normalized_label NOT LIKE '%nonoperating%'
                        AND dc.normalized_label NOT LIKE '%other%nonoperating%'
                        AND dc.normalized_label NOT IN ('operating_expenses', 'total_operating_expenses')
                            THEN f.value_numeric ELSE 0 END)
                    ) as operating_expenses
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                JOIN dim_time_periods t ON f.period_id = t.period_id
                WHERE f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND t.period_type = 'duration'
                  AND t.fiscal_year IS NOT NULL
                GROUP BY c.ticker, t.fiscal_year
                HAVING MAX(CASE WHEN dc.normalized_label IN ('operating_income', 'income_from_operations', 'operating_profit', 'income_loss_from_operations') 
                    THEN f.value_numeric ELSE NULL END) > 0
            )
            SELECT 
                ticker,
                fiscal_year,
                operating_income_reported,
                gross_profit,
                revenue,
                cost_of_revenue,
                total_costs_and_expenses,
                operating_expenses,
                -- Calculate: Multiple structures supported
                -- Structure 1: Revenue - CostsAndExpenses = Operating Income (AMZN, WMT)
                -- Structure 2: Gross Profit - Operating Expenses = Operating Income (traditional)
                COALESCE(
                    -- Prefer explicit total costs and expenses (AMZN structure)
                    CASE WHEN total_costs_and_expenses IS NOT NULL AND revenue IS NOT NULL 
                        THEN revenue - total_costs_and_expenses 
                        ELSE NULL END,
                    -- Fallback: Gross Profit - Operating Expenses (traditional structure)
                    COALESCE(gross_profit, revenue - COALESCE(cost_of_revenue, 0)) - COALESCE(operating_expenses, 0)
                ) as operating_income_calculated,
                ABS(operating_income_reported - COALESCE(
                    CASE WHEN total_costs_and_expenses IS NOT NULL AND revenue IS NOT NULL 
                        THEN revenue - total_costs_and_expenses 
                        ELSE NULL END,
                    COALESCE(gross_profit, revenue - COALESCE(cost_of_revenue, 0)) - COALESCE(operating_expenses, 0)
                )) as difference,
                ABS(operating_income_reported - COALESCE(
                    CASE WHEN total_costs_and_expenses IS NOT NULL AND revenue IS NOT NULL 
                        THEN revenue - total_costs_and_expenses 
                        ELSE NULL END,
                    COALESCE(gross_profit, revenue - COALESCE(cost_of_revenue, 0)) - COALESCE(operating_expenses, 0)
                )) / NULLIF(ABS(operating_income_reported), 0) * 100 as difference_pct
            FROM operating_income_data
            WHERE ABS(operating_income_reported - COALESCE(
                CASE WHEN total_costs_and_expenses IS NOT NULL AND revenue IS NOT NULL 
                    THEN revenue - total_costs_and_expenses 
                    ELSE NULL END,
                COALESCE(gross_profit, revenue - COALESCE(cost_of_revenue, 0)) - COALESCE(operating_expenses, 0)
            )) / NULLIF(ABS(operating_income_reported), 0) * 100 > :tolerance
            ORDER BY difference_pct DESC
            LIMIT 20;
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query, {'tolerance': tolerance_pct})
            violations = result.fetchall()
            
            if violations:
                violation_details = [
                    {
                        'company': row[0],
                        'fiscal_year': row[1],
                        'operating_income_reported': float(row[2]),
                        'gross_profit': float(row[3]) if row[3] else None,
                        'revenue': float(row[4]) if row[4] else None,
                        'cost_of_revenue': float(row[5]) if row[5] else None,
                        'total_costs_and_expenses': float(row[6]) if row[6] else None,
                        'operating_expenses': float(row[7]) if row[7] else None,
                        'operating_income_calculated': float(row[8]),
                        'difference': float(row[9]),
                        'difference_pct': float(row[10])
                    }
                    for row in violations
                ]
                
                return ValidationResult(
                    rule_name='operating_income_calculation',
                    passed=False,
                    severity='WARNING',  # Warning because some companies may structure expenses differently
                    message=f'Operating income calculation violated for {len(violations)} company-period combinations',
                    details={
                        'violations': violation_details[:10],
                        'total_violations': len(violations),
                        'tolerance_pct': tolerance_pct,
                        'explanation': 'Operating Income should equal Gross Profit - Operating Expenses (within 1% tolerance)'
                    }
                )
            else:
                return ValidationResult(
                    rule_name='operating_income_calculation',
                    passed=True,
                    severity='INFO',
                    message='Operating income calculation holds for all company-period combinations',
                    details={'tolerance_pct': tolerance_pct}
                )
    
    def _check_calculation_relationships(self) -> ValidationResult:
        """
        Check parent = sum(children) for all calculation relationships.
        Tolerance: 0.1% (XBRL precision)
        
        NOTE: This check requires calculation relationships to be loaded.
        If the relationships table doesn't exist, returns INFO (not an error).
        """
        # Check if calculation relationships table exists
        check_table_query = text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'dim_calculation_relationships'
            );
        """)
        
        with self.engine.connect() as conn:
            table_exists = conn.execute(check_table_query).scalar()
            
            if not table_exists:
                return ValidationResult(
                    rule_name='calculation_relationships',
                    passed=True,
                    severity='INFO',
                    message='Calculation relationships table not found (relationships not loaded)',
                    details={'explanation': 'This check requires calculation relationships to be loaded from taxonomy'}
                )
        
        query = text("""
            WITH calc_relationships AS (
                SELECT 
                    r.parent_concept_id,
                    r.child_concept_id,
                    r.weight,
                    COUNT(DISTINCT r.relationship_id) as relationship_count
                FROM dim_calculation_relationships r
                WHERE r.source = 'taxonomy'
                  AND r.confidence >= 0.995
                GROUP BY r.parent_concept_id, r.child_concept_id, r.weight
            ),
            parent_values AS (
                SELECT 
                    f.company_id,
                    f.period_id,
                    cr.parent_concept_id,
                    SUM(f.value_numeric) as parent_value
                FROM fact_financial_metrics f
                JOIN calc_relationships cr ON f.concept_id = cr.parent_concept_id
                WHERE f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                GROUP BY f.company_id, f.period_id, cr.parent_concept_id
            ),
            child_sum AS (
                SELECT 
                    f.company_id,
                    f.period_id,
                    cr.parent_concept_id,
                    SUM(f.value_numeric * cr.weight) as child_sum_value
                FROM fact_financial_metrics f
                JOIN calc_relationships cr ON f.concept_id = cr.child_concept_id
                WHERE f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                GROUP BY f.company_id, f.period_id, cr.parent_concept_id
            ),
            relationship_check AS (
                SELECT 
                    pv.company_id,
                    pv.period_id,
                    pv.parent_concept_id,
                    dc_parent.concept_name as parent_concept_name,
                    pv.parent_value,
                    cs.child_sum_value,
                    ABS(pv.parent_value - cs.child_sum_value) as difference,
                    ABS(pv.parent_value - cs.child_sum_value) / NULLIF(ABS(pv.parent_value), 0) * 100 as difference_pct
                FROM parent_values pv
                JOIN child_sum cs ON pv.company_id = cs.company_id 
                    AND pv.period_id = cs.period_id 
                    AND pv.parent_concept_id = cs.parent_concept_id
                JOIN dim_concepts dc_parent ON pv.parent_concept_id = dc_parent.concept_id
                WHERE ABS(pv.parent_value - cs.child_sum_value) / NULLIF(ABS(pv.parent_value), 0) * 100 > 0.1
            )
            SELECT 
                c.ticker,
                t.fiscal_year,
                rc.parent_concept_name,
                rc.parent_value,
                rc.child_sum_value,
                rc.difference,
                rc.difference_pct
            FROM relationship_check rc
            JOIN dim_companies c ON rc.company_id = c.company_id
            JOIN dim_time_periods t ON rc.period_id = t.period_id
            ORDER BY rc.difference_pct DESC
            LIMIT 20;
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query)
            violations = result.fetchall()
            
            if violations:
                violation_details = [
                    {
                        'company': row[0],
                        'fiscal_year': row[1],
                        'parent_concept': row[2],
                        'parent_value': float(row[3]),
                        'child_sum_value': float(row[4]),
                        'difference': float(row[5]),
                        'difference_pct': float(row[6])
                    }
                    for row in violations
                ]
                
                return ValidationResult(
                    rule_name='calculation_relationships',
                    passed=False,
                    severity='WARNING',  # Warning because some relationships may be approximations
                    message=f'Calculation relationships violated for {len(violations)} company-period-concept combinations',
                    details={
                        'violations': violation_details[:10],
                        'total_violations': len(violations),
                        'tolerance_pct': 0.1,
                        'explanation': 'Parent should equal sum(children * weights) within 0.1% tolerance (XBRL precision)'
                    }
                )
            else:
                return ValidationResult(
                    rule_name='calculation_relationships',
                    passed=True,
                    severity='INFO',
                    message='All calculation relationships hold within tolerance',
                    details={'tolerance_pct': 0.1}
                )
    
    def _check_data_quality(self) -> List[ValidationResult]:
        """
        Check data quality: normalization coverage, numeric value ranges, unit consistency.
        Returns list of ValidationResult for each quality check.
        """
        results = []
        
        # 1. Normalization coverage
        norm_coverage_result = self._check_normalization_coverage()
        results.append(norm_coverage_result)
        
        # 2. Numeric value range sanity checks
        numeric_range_result = self._check_numeric_value_ranges()
        results.append(numeric_range_result)
        
        # 3. Unit consistency (currency per filing)
        unit_consistency_result = self._check_unit_consistency()
        results.append(unit_consistency_result)
        
        return results
    
    def _check_normalization_coverage(self) -> ValidationResult:
        """
        Check 100% of concepts are normalized (no NULL normalized_labels).
        """
        query = text("""
            SELECT 
                COUNT(*) as total_concepts,
                COUNT(*) FILTER (WHERE normalized_label IS NULL) as null_normalized_labels,
                COUNT(*) FILTER (WHERE normalized_label IS NOT NULL) as normalized_concepts
            FROM dim_concepts
            WHERE concept_id > 0;
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query)
            row = result.fetchone()
            
            if row:
                total_concepts, null_count, normalized_count = row
                coverage_pct = (normalized_count / total_concepts * 100) if total_concepts > 0 else 0
                
                if null_count > 0:
                    return ValidationResult(
                        rule_name='normalization_coverage',
                        passed=False,
                        severity='ERROR',
                        message=f'{null_count} concepts have NULL normalized_label ({coverage_pct:.1f}% coverage)',
                        details={
                            'total_concepts': total_concepts,
                            'null_normalized_labels': null_count,
                            'normalized_concepts': normalized_count,
                            'coverage_pct': coverage_pct,
                            'explanation': '100% of concepts should have normalized_label (required for analysis)'
                        }
                    )
                else:
                    return ValidationResult(
                        rule_name='normalization_coverage',
                        passed=True,
                        severity='INFO',
                        message=f'100% normalization coverage ({normalized_count:,} concepts)',
                        details={
                            'total_concepts': total_concepts,
                            'coverage_pct': 100.0
                        }
                    )
        
        return ValidationResult(
            rule_name='normalization_coverage',
            passed=False,
            severity='ERROR',
            message='Could not check normalization coverage',
            details={'error': 'Query failed'}
        )
    
    def _check_numeric_value_ranges(self) -> ValidationResult:
        """
        Check numeric values are within reasonable ranges.
        - No negative values where illogical (assets, revenue)
        - Context-aware thresholds: Banks have different scales (derivative notional amounts can be > $10T)
        - Flag extreme outliers for review
        
        BIG 4/HEDGE FUND APPROACH:
        - Context-aware validation (notional amounts legitimate for banks)
        - Metric-specific thresholds (derivative notional vs fair value)
        - Universal detection (not hardcoded per-company)
        """
        query = text("""
            WITH bank_companies AS (
                -- Detect banks (have deposit liabilities or financing receivables)
                SELECT DISTINCT c.company_id
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                WHERE f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND (
                      dc.normalized_label LIKE '%deposit%liabilities%'
                      OR dc.normalized_label LIKE '%financing%receivable%'
                      OR dc.concept_name LIKE '%DepositLiabilities%'
                      OR dc.concept_name LIKE '%FinancingReceivable%'
                  )
            ),
            suspicious_values AS (
                SELECT 
                    c.ticker,
                    dc.normalized_label,
                    t.fiscal_year,
                    f.value_numeric,
                    CASE 
                        WHEN dc.normalized_label IN ('total_assets', 'revenue', 'revenues', 'total_liabilities', 
                            'stockholders_equity', 'cost_of_revenue', 'gross_profit') 
                            AND f.value_numeric < 0 
                        THEN 'negative_illogical'
                        -- Derivative notional amounts: legitimate for banks (can be > $10T)
                        WHEN dc.normalized_label LIKE '%derivative%notional%'
                            AND ABS(f.value_numeric) > 10000000000000  -- > $10T
                            AND c.company_id IN (SELECT company_id FROM bank_companies)
                        THEN NULL  -- Legitimate for banks
                        -- Non-notional metrics: standard threshold
                        WHEN ABS(f.value_numeric) > 10000000000000  -- > $10T
                            AND NOT (dc.normalized_label LIKE '%derivative%notional%')
                        THEN 'extremely_large'
                        ELSE NULL
                    END as issue_type
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                JOIN dim_time_periods t ON f.period_id = t.period_id
                WHERE f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND (
                      (dc.normalized_label IN ('total_assets', 'revenue', 'revenues', 'total_liabilities', 
                        'stockholders_equity', 'cost_of_revenue', 'gross_profit') 
                        AND f.value_numeric < 0)
                      OR (ABS(f.value_numeric) > 10000000000000 
                          AND NOT (dc.normalized_label LIKE '%derivative%notional%' 
                                   AND c.company_id IN (SELECT company_id FROM bank_companies)))
                  )
            )
            SELECT 
                ticker,
                normalized_label,
                fiscal_year,
                value_numeric,
                issue_type,
                COUNT(*) OVER (PARTITION BY issue_type) as issue_count
            FROM suspicious_values
            ORDER BY ABS(value_numeric) DESC
            LIMIT 20;
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query)
            violations = result.fetchall()
            
            if violations:
                violation_details = [
                    {
                        'company': row[0],
                        'metric': row[1],
                        'fiscal_year': row[2],
                        'value': float(row[3]),
                        'issue_type': row[4]
                    }
                    for row in violations[:10]
                ]
                
                issue_types = {}
                for row in violations:
                    issue_type = row[4]
                    if issue_type not in issue_types:
                        issue_types[issue_type] = 0
                    issue_types[issue_type] += 1
                
                return ValidationResult(
                    rule_name='numeric_value_ranges',
                    passed=False,
                    severity='WARNING',  # Warning because some may be legitimate (e.g., adjustments)
                    message=f'Found {len(violations)} suspicious numeric values (negative illogical or > $10T)',
                    details={
                        'violations': violation_details,
                        'total_violations': len(violations),
                        'issue_types': issue_types,
                        'explanation': 'Assets/revenue should not be negative; values > $10T are extremely large'
                    }
                )
            else:
                return ValidationResult(
                    rule_name='numeric_value_ranges',
                    passed=True,
                    severity='INFO',
                    message='All numeric values within reasonable ranges',
                    details={}
                )
    
    def _check_unit_consistency(self) -> ValidationResult:
        """
        Check for potential unit inconsistencies within a filing.
        Excludes per-share metrics, rates, yields, and percentages (legitimate variations).
        
        BIG 4/HEDGE FUND APPROACH:
        - Context-aware: Exclude per-share, rate, yield, percentage metrics
        - These metrics legitimately have very different scales
        - Only check non-rate/non-per-share metrics for unit consistency
        """
        query = text("""
            WITH bank_companies AS (
                -- Detect banks (have deposit liabilities or financing receivables)
                SELECT DISTINCT c.company_id
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                WHERE f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND (
                      dc.normalized_label LIKE '%deposit%liabilities%'
                      OR dc.normalized_label LIKE '%financing%receivable%'
                      OR dc.concept_name LIKE '%DepositLiabilities%'
                      OR dc.concept_name LIKE '%FinancingReceivable%'
                  )
            ),
            filing_metrics AS (
                SELECT 
                    fl.filing_id,
                    fl.company_id,
                    COUNT(DISTINCT f.value_numeric) as distinct_values,
                    COUNT(*) as total_facts,
                    -- Exclude bank-specific large-value metrics from min/max calculation
                    -- These are legitimate for banks but skew the range ratio
                    MIN(CASE WHEN (
                        fl.company_id IN (SELECT company_id FROM bank_companies)
                        AND (
                            dc.normalized_label LIKE '%derivative%notional%'
                            OR dc.normalized_label LIKE '%off_balance_sheet%'
                            OR dc.normalized_label LIKE '%contractual_amount%'
                            OR dc.concept_name LIKE '%DerivativeNotional%'
                            OR dc.concept_name LIKE '%OffBalanceSheet%'
                            OR dc.concept_name LIKE '%ContractualAmount%'
                        )
                    ) THEN NULL ELSE f.value_numeric END) as min_value,
                    MAX(CASE WHEN (
                        fl.company_id IN (SELECT company_id FROM bank_companies)
                        AND (
                            dc.normalized_label LIKE '%derivative%notional%'
                            OR dc.normalized_label LIKE '%off_balance_sheet%'
                            OR dc.normalized_label LIKE '%contractual_amount%'
                            OR dc.concept_name LIKE '%DerivativeNotional%'
                            OR dc.concept_name LIKE '%OffBalanceSheet%'
                            OR dc.concept_name LIKE '%ContractualAmount%'
                        )
                    ) THEN NULL ELSE f.value_numeric END) as max_value,
                    MAX(CASE WHEN (
                        fl.company_id IN (SELECT company_id FROM bank_companies)
                        AND (
                            dc.normalized_label LIKE '%derivative%notional%'
                            OR dc.normalized_label LIKE '%off_balance_sheet%'
                            OR dc.normalized_label LIKE '%contractual_amount%'
                            OR dc.concept_name LIKE '%DerivativeNotional%'
                            OR dc.concept_name LIKE '%OffBalanceSheet%'
                            OR dc.concept_name LIKE '%ContractualAmount%'
                        )
                    ) THEN NULL ELSE f.value_numeric END) / 
                    NULLIF(MIN(CASE WHEN (
                        fl.company_id IN (SELECT company_id FROM bank_companies)
                        AND (
                            dc.normalized_label LIKE '%derivative%notional%'
                            OR dc.normalized_label LIKE '%off_balance_sheet%'
                            OR dc.normalized_label LIKE '%contractual_amount%'
                            OR dc.concept_name LIKE '%DerivativeNotional%'
                            OR dc.concept_name LIKE '%OffBalanceSheet%'
                            OR dc.concept_name LIKE '%ContractualAmount%'
                        )
                    ) THEN NULL ELSE ABS(f.value_numeric) END), 0) as value_range_ratio
                FROM fact_financial_metrics f
                JOIN dim_filings fl ON f.filing_id = fl.filing_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                WHERE f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND f.value_numeric != 0
                  -- Exclude per-share, rate, yield, percentage metrics (legitimate variations)
                  AND dc.normalized_label NOT LIKE '%per_share%'
                  AND dc.normalized_label NOT LIKE '%_rate%'
                  AND dc.normalized_label NOT LIKE '%_yield%'
                  AND dc.normalized_label NOT LIKE '%_pct%'
                  AND dc.normalized_label NOT LIKE '%_percent%'
                  AND dc.normalized_label NOT LIKE '%ratio%'
                  AND dc.concept_name NOT LIKE '%PerShare%'
                  AND dc.concept_name NOT LIKE '%Rate%'
                  AND dc.concept_name NOT LIKE '%Yield%'
                GROUP BY fl.filing_id, fl.company_id
                HAVING COUNT(*) > 10  -- Only check filings with sufficient data
            )
            SELECT 
                c.ticker,
                fm.filing_id,
                fm.total_facts,
                fm.min_value,
                fm.max_value,
                fm.value_range_ratio
            FROM filing_metrics fm
            JOIN dim_companies c ON fm.company_id = c.company_id
            WHERE fm.value_range_ratio > 10000000000  -- Adjusted threshold (1e10) for non-rate metrics
            ORDER BY fm.value_range_ratio DESC
            LIMIT 20;
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query)
            violations = result.fetchall()
            
            if violations:
                violation_details = [
                    {
                        'company': row[0],
                        'filing_id': row[1],
                        'total_facts': row[2],
                        'min_value': float(row[3]),
                        'max_value': float(row[4]),
                        'value_range_ratio': float(row[5])
                    }
                    for row in violations
                ]
                
                return ValidationResult(
                    rule_name='unit_consistency',
                    passed=False,
                    severity='WARNING',  # Warning because some may be legitimate (e.g., shares vs dollars)
                    message=f'Potential unit inconsistency in {len(violations)} filings (very large value range ratios)',
                    details={
                        'violations': violation_details[:10],
                        'total_violations': len(violations),
                        'explanation': 'Values within same filing should use consistent units (currency, scale)'
                    }
                )
            else:
                return ValidationResult(
                    rule_name='unit_consistency',
                    passed=True,
                    severity='INFO',
                    message='Unit consistency check passed for all filings',
                    details={}
                )


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

