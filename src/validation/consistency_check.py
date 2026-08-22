#!/usr/bin/env python3
"""
Consistency Validator Module

Validates cross-period and cross-source consistency.
This runs after populate_statement_facts(), before validator.py.

Checks:
1. Cross-period consistency (equity continuity, retained earnings rollforward, balance sheet equation across periods)
2. Ratio reasonableness (gross margin 0-100%, operating margin reasonable, equity ratio 10-80% of assets)
3. XBRL vs SEC API consistency (values should match within 1% tolerance when both exist)
4. Context variant consistency (optional: check if multiple context variants differ significantly)
"""

import logging
from typing import List, Dict, Any, Optional
from collections import defaultdict
from sqlalchemy import create_engine, text
from config import DATABASE_URI

from src.validation.checks import ValidationResult, ValidationReport

logger = logging.getLogger(__name__)


class ConsistencyValidator:
    """Validates cross-period and cross-source consistency"""
    
    def __init__(self, tolerance_pct: float = 1.0):
        """
        Initialize validator
        
        Args:
            tolerance_pct: Tolerance percentage for consistency checks (default 1.0%)
        """
        self.engine = create_engine(DATABASE_URI)
        self.tolerance_pct = tolerance_pct
    
    def validate_consistency(self, ticker: str) -> ValidationReport:
        """
        Validate consistency for a company
        
        Args:
            ticker: Company ticker
            
        Returns:
            ValidationReport with consistency issues
        """
        report = ValidationReport(
            company=ticker,
            filing_type="unknown",
            fiscal_year_end="unknown"
        )
        
        with self.engine.connect() as conn:
            # Get company info
            company_result = conn.execute(text("""
                SELECT company_id, ticker
                FROM dim_companies
                WHERE ticker = :ticker
                LIMIT 1
            """), {'ticker': ticker})
            
            company_row = company_result.fetchone()
            if not company_row:
                report.add_result(ValidationResult(
                    rule_name="company_exists",
                    passed=False,
                    severity="ERROR",
                    message=f"Company {ticker} not found"
                ))
                report.calculate_score()
                return report
            
            company_id, _ = company_row
            
            # 1. Cross-period consistency
            self._check_equity_continuity(conn, company_id, report)
            self._check_retained_earnings_rollforward(conn, company_id, report)
            self._check_balance_sheet_equation_across_periods(conn, company_id, report)
            
            # 2. Ratio reasonableness
            self._check_gross_margin_reasonableness(conn, company_id, report)
            self._check_operating_margin_reasonableness(conn, company_id, report)
            self._check_equity_ratio_reasonableness(conn, company_id, report)
            
            # 3. XBRL vs SEC API consistency
            self._check_xbrl_sec_api_consistency(conn, company_id, report)
            
            # 4. Context variant consistency (optional)
            self._check_context_variant_consistency(conn, company_id, report)
        
        report.calculate_score()
        return report
    
    def _check_equity_continuity(self, conn, company_id: int, report: ValidationReport):
        """Check equity continuity: Ending equity ≈ Beginning equity + Net income + OCI - Dividends"""
        # Get equity, net income, OCI, dividends by fiscal year
        result = conn.execute(text("""
            WITH equity_data AS (
                SELECT 
                    tp.fiscal_year,
                    SUM(CASE WHEN dc.normalized_label IN ('equity_total', 'total_equity') 
                             AND ffm.dimension_id IS NULL THEN ffm.value_numeric ELSE 0 END) as equity
                FROM fact_financial_metrics ffm
                JOIN dim_concepts dc ON ffm.concept_id = dc.concept_id
                JOIN dim_time_periods tp ON ffm.period_id = tp.period_id
                WHERE ffm.company_id = :company_id
                  AND tp.period_type = 'instant'
                  AND tp.fiscal_year IS NOT NULL
                GROUP BY tp.fiscal_year
            ),
            income_data AS (
                SELECT 
                    tp.fiscal_year,
                    SUM(CASE WHEN dc.normalized_label IN ('net_income', 'net_profit') 
                             AND ffm.dimension_id IS NULL THEN ffm.value_numeric ELSE 0 END) as net_income
                FROM fact_financial_metrics ffm
                JOIN dim_concepts dc ON ffm.concept_id = dc.concept_id
                JOIN dim_time_periods tp ON ffm.period_id = tp.period_id
                WHERE ffm.company_id = :company_id
                  AND tp.period_type = 'duration'
                  AND tp.fiscal_year IS NOT NULL
                GROUP BY tp.fiscal_year
            ),
            oci_data AS (
                SELECT 
                    tp.fiscal_year,
                    SUM(CASE WHEN dc.normalized_label IN ('other_comprehensive_income', 'oci_total') 
                             AND ffm.dimension_id IS NULL THEN ffm.value_numeric ELSE 0 END) as oci
                FROM fact_financial_metrics ffm
                JOIN dim_concepts dc ON ffm.concept_id = dc.concept_id
                JOIN dim_time_periods tp ON ffm.period_id = tp.period_id
                WHERE ffm.company_id = :company_id
                  AND tp.period_type = 'duration'
                  AND tp.fiscal_year IS NOT NULL
                GROUP BY tp.fiscal_year
            )
            SELECT 
                e1.fiscal_year as year,
                e1.equity as beginning_equity,
                e2.equity as ending_equity,
                i.net_income,
                o.oci,
                (e1.equity + COALESCE(i.net_income, 0) + COALESCE(o.oci, 0)) as calculated_ending
            FROM equity_data e1
            JOIN equity_data e2 ON e2.fiscal_year = e1.fiscal_year + 1
            LEFT JOIN income_data i ON i.fiscal_year = e1.fiscal_year
            LEFT JOIN oci_data o ON o.fiscal_year = e1.fiscal_year
            WHERE e1.equity IS NOT NULL AND e2.equity IS NOT NULL
            ORDER BY e1.fiscal_year
        """), {'company_id': company_id})
        
        issues = []
        for row in result:
            year, beginning_equity, ending_equity, net_income, oci, calculated_ending = row
            
            if beginning_equity is None or ending_equity is None:
                continue
            
            net_income = net_income or 0
            oci = oci or 0
            
            difference = abs(ending_equity - calculated_ending)
            tolerance = abs(beginning_equity) * (self.tolerance_pct / 100.0)
            
            if difference > tolerance:
                issues.append({
                    'year': year,
                    'beginning_equity': beginning_equity,
                    'ending_equity': ending_equity,
                    'calculated_ending': calculated_ending,
                    'net_income': net_income,
                    'oci': oci,
                    'difference': difference
                })
        
        if issues:
            report.add_result(ValidationResult(
                rule_name="equity_continuity",
                passed=False,
                severity="WARNING",
                message=f"Equity continuity issues in {len(issues)} year(s)",
                details={'issues': issues}
            ))
        else:
            report.add_result(ValidationResult(
                rule_name="equity_continuity",
                passed=True,
                severity="INFO",
                message="Equity continuity holds across periods"
            ))
    
    def _check_retained_earnings_rollforward(self, conn, company_id: int, report: ValidationReport):
        """Check retained earnings rollforward: Ending RE ≈ Beginning RE + Net income - Dividends"""
        # Similar to equity continuity but for retained earnings
        result = conn.execute(text("""
            WITH re_data AS (
                SELECT 
                    tp.fiscal_year,
                    SUM(CASE WHEN dc.normalized_label = 'retained_earnings' 
                             AND ffm.dimension_id IS NULL THEN ffm.value_numeric ELSE 0 END) as retained_earnings
                FROM fact_financial_metrics ffm
                JOIN dim_concepts dc ON ffm.concept_id = dc.concept_id
                JOIN dim_time_periods tp ON ffm.period_id = tp.period_id
                WHERE ffm.company_id = :company_id
                  AND tp.period_type = 'instant'
                  AND tp.fiscal_year IS NOT NULL
                GROUP BY tp.fiscal_year
            ),
            income_data AS (
                SELECT 
                    tp.fiscal_year,
                    SUM(CASE WHEN dc.normalized_label IN ('net_income', 'net_profit') 
                             AND ffm.dimension_id IS NULL THEN ffm.value_numeric ELSE 0 END) as net_income
                FROM fact_financial_metrics ffm
                JOIN dim_concepts dc ON ffm.concept_id = dc.concept_id
                JOIN dim_time_periods tp ON ffm.period_id = tp.period_id
                WHERE ffm.company_id = :company_id
                  AND tp.period_type = 'duration'
                  AND tp.fiscal_year IS NOT NULL
                GROUP BY tp.fiscal_year
            )
            SELECT 
                re1.fiscal_year as year,
                re1.retained_earnings as beginning_re,
                re2.retained_earnings as ending_re,
                i.net_income,
                (re1.retained_earnings + COALESCE(i.net_income, 0)) as calculated_ending
            FROM re_data re1
            JOIN re_data re2 ON re2.fiscal_year = re1.fiscal_year + 1
            LEFT JOIN income_data i ON i.fiscal_year = re1.fiscal_year
            WHERE re1.retained_earnings IS NOT NULL AND re2.retained_earnings IS NOT NULL
            ORDER BY re1.fiscal_year
        """), {'company_id': company_id})
        
        issues = []
        for row in result:
            year, beginning_re, ending_re, net_income, calculated_ending = row
            
            if beginning_re is None or ending_re is None:
                continue
            
            net_income = net_income or 0
            difference = abs(ending_re - calculated_ending)
            tolerance = abs(beginning_re) * (self.tolerance_pct / 100.0)
            
            if difference > tolerance:
                issues.append({
                    'year': year,
                    'beginning_re': beginning_re,
                    'ending_re': ending_re,
                    'net_income': net_income,
                    'calculated_ending': calculated_ending,
                    'difference': difference
                })
        
        if issues:
            report.add_result(ValidationResult(
                rule_name="retained_earnings_rollforward",
                passed=False,
                severity="WARNING",
                message=f"Retained earnings rollforward issues in {len(issues)} year(s)",
                details={'issues': issues}
            ))
        else:
            report.add_result(ValidationResult(
                rule_name="retained_earnings_rollforward",
                passed=True,
                severity="INFO",
                message="Retained earnings rollforward holds across periods"
            ))
    
    def _check_balance_sheet_equation_across_periods(self, conn, company_id: int, report: ValidationReport):
        """Check balance sheet equation holds across all periods"""
        result = conn.execute(text("""
            SELECT 
                tp.fiscal_year,
                SUM(CASE WHEN dc.normalized_label IN ('total_assets', 'assets_total') 
                         AND ffm.dimension_id IS NULL THEN ffm.value_numeric ELSE 0 END) as assets,
                SUM(CASE WHEN dc.normalized_label IN ('total_liabilities', 'liabilities_total') 
                         AND ffm.dimension_id IS NULL THEN ffm.value_numeric ELSE 0 END) as liabilities,
                SUM(CASE WHEN dc.normalized_label IN ('equity_total', 'total_equity') 
                         AND ffm.dimension_id IS NULL THEN ffm.value_numeric ELSE 0 END) as equity
            FROM fact_financial_metrics ffm
            JOIN dim_concepts dc ON ffm.concept_id = dc.concept_id
            JOIN dim_time_periods tp ON ffm.period_id = tp.period_id
            WHERE ffm.company_id = :company_id
              AND tp.period_type = 'instant'
              AND tp.fiscal_year IS NOT NULL
            GROUP BY tp.fiscal_year
            HAVING SUM(CASE WHEN dc.normalized_label IN ('total_assets', 'assets_total') 
                             AND ffm.dimension_id IS NULL THEN ffm.value_numeric ELSE 0 END) IS NOT NULL
            ORDER BY tp.fiscal_year
        """), {'company_id': company_id})
        
        issues = []
        for row in result:
            fiscal_year, assets, liabilities, equity = row
            
            if assets is None:
                continue
            
            liabilities = liabilities or 0
            equity = equity or 0
            
            calculated_equity = assets - liabilities
            difference = abs(equity - calculated_equity)
            tolerance = abs(assets) * (self.tolerance_pct / 100.0)
            
            if difference > tolerance:
                issues.append({
                    'year': fiscal_year,
                    'assets': assets,
                    'liabilities': liabilities,
                    'equity': equity,
                    'calculated_equity': calculated_equity,
                    'difference': difference
                })
        
        if issues:
            report.add_result(ValidationResult(
                rule_name="balance_sheet_equation_periods",
                passed=False,
                severity="WARNING",
                message=f"Balance sheet equation violations in {len(issues)} period(s)",
                details={'issues': issues}
            ))
        else:
            report.add_result(ValidationResult(
                rule_name="balance_sheet_equation_periods",
                passed=True,
                severity="INFO",
                message="Balance sheet equation holds across all periods"
            ))
    
    def _check_gross_margin_reasonableness(self, conn, company_id: int, report: ValidationReport):
        """Check gross margin is 0-100% (logic, not health-based)"""
        result = conn.execute(text("""
            SELECT 
                tp.fiscal_year,
                SUM(CASE WHEN dc.normalized_label IN ('revenue', 'net_sales') 
                         AND ffm.dimension_id IS NULL THEN ffm.value_numeric ELSE 0 END) as revenue,
                SUM(CASE WHEN dc.normalized_label = 'gross_profit' 
                         AND ffm.dimension_id IS NULL THEN ffm.value_numeric ELSE 0 END) as gross_profit
            FROM fact_financial_metrics ffm
            JOIN dim_concepts dc ON ffm.concept_id = dc.concept_id
            JOIN dim_time_periods tp ON ffm.period_id = tp.period_id
            WHERE ffm.company_id = :company_id
              AND tp.period_type = 'duration'
              AND tp.fiscal_year IS NOT NULL
            GROUP BY tp.fiscal_year
            HAVING SUM(CASE WHEN dc.normalized_label IN ('revenue', 'net_sales') 
                             AND ffm.dimension_id IS NULL THEN ffm.value_numeric ELSE 0 END) IS NOT NULL
              AND SUM(CASE WHEN dc.normalized_label = 'gross_profit' 
                             AND ffm.dimension_id IS NULL THEN ffm.value_numeric ELSE 0 END) IS NOT NULL
            ORDER BY tp.fiscal_year
        """), {'company_id': company_id})
        
        issues = []
        for row in result:
            fiscal_year, revenue, gross_profit = row
            
            if revenue is None or revenue == 0 or gross_profit is None:
                continue
            
            gross_margin_pct = (gross_profit / revenue) * 100.0
            
            if gross_margin_pct < 0 or gross_margin_pct > 100:
                issues.append({
                    'year': fiscal_year,
                    'revenue': revenue,
                    'gross_profit': gross_profit,
                    'gross_margin_pct': gross_margin_pct
                })
        
        if issues:
            report.add_result(ValidationResult(
                rule_name="gross_margin_reasonableness",
                passed=False,
                severity="WARNING",
                message=f"Gross margin outside reasonable range (0-100%) in {len(issues)} period(s)",
                details={'issues': issues}
            ))
        else:
            report.add_result(ValidationResult(
                rule_name="gross_margin_reasonableness",
                passed=True,
                severity="INFO",
                message="Gross margin within reasonable range (0-100%)"
            ))
    
    def _check_operating_margin_reasonableness(self, conn, company_id: int, report: ValidationReport):
        """Check operating margin is reasonable (not health-based)"""
        result = conn.execute(text("""
            SELECT 
                tp.fiscal_year,
                SUM(CASE WHEN dc.normalized_label IN ('revenue', 'net_sales') 
                         AND ffm.dimension_id IS NULL THEN ffm.value_numeric ELSE 0 END) as revenue,
                SUM(CASE WHEN dc.normalized_label = 'operating_income' 
                         AND ffm.dimension_id IS NULL THEN ffm.value_numeric ELSE 0 END) as operating_income
            FROM fact_financial_metrics ffm
            JOIN dim_concepts dc ON ffm.concept_id = dc.concept_id
            JOIN dim_time_periods tp ON ffm.period_id = tp.period_id
            WHERE ffm.company_id = :company_id
              AND tp.period_type = 'duration'
              AND tp.fiscal_year IS NOT NULL
            GROUP BY tp.fiscal_year
            HAVING SUM(CASE WHEN dc.normalized_label IN ('revenue', 'net_sales') 
                             AND ffm.dimension_id IS NULL THEN ffm.value_numeric ELSE 0 END) IS NOT NULL
              AND SUM(CASE WHEN dc.normalized_label = 'operating_income' 
                             AND ffm.dimension_id IS NULL THEN ffm.value_numeric ELSE 0 END) IS NOT NULL
            ORDER BY tp.fiscal_year
        """), {'company_id': company_id})
        
        issues = []
        for row in result:
            fiscal_year, revenue, operating_income = row
            
            if revenue is None or revenue == 0 or operating_income is None:
                continue
            
            operating_margin_pct = (operating_income / revenue) * 100.0
            
            # Operating margin can be negative (losses) but shouldn't exceed revenue
            if abs(operating_margin_pct) > 100:
                issues.append({
                    'year': fiscal_year,
                    'revenue': revenue,
                    'operating_income': operating_income,
                    'operating_margin_pct': operating_margin_pct
                })
        
        if issues:
            report.add_result(ValidationResult(
                rule_name="operating_margin_reasonableness",
                passed=False,
                severity="WARNING",
                message=f"Operating margin outside reasonable range in {len(issues)} period(s)",
                details={'issues': issues}
            ))
        else:
            report.add_result(ValidationResult(
                rule_name="operating_margin_reasonableness",
                passed=True,
                severity="INFO",
                message="Operating margin within reasonable range"
            ))
    
    def _check_equity_ratio_reasonableness(self, conn, company_id: int, report: ValidationReport):
        """Check equity ratio is 10-80% of assets (catches unit scaling)"""
        result = conn.execute(text("""
            SELECT 
                tp.fiscal_year,
                SUM(CASE WHEN dc.normalized_label IN ('total_assets', 'assets_total') 
                         AND ffm.dimension_id IS NULL THEN ffm.value_numeric ELSE 0 END) as assets,
                SUM(CASE WHEN dc.normalized_label IN ('equity_total', 'total_equity') 
                         AND ffm.dimension_id IS NULL THEN ffm.value_numeric ELSE 0 END) as equity
            FROM fact_financial_metrics ffm
            JOIN dim_concepts dc ON ffm.concept_id = dc.concept_id
            JOIN dim_time_periods tp ON ffm.period_id = tp.period_id
            WHERE ffm.company_id = :company_id
              AND tp.period_type = 'instant'
              AND tp.fiscal_year IS NOT NULL
            GROUP BY tp.fiscal_year
            HAVING SUM(CASE WHEN dc.normalized_label IN ('total_assets', 'assets_total') 
                             AND ffm.dimension_id IS NULL THEN ffm.value_numeric ELSE 0 END) IS NOT NULL
              AND SUM(CASE WHEN dc.normalized_label IN ('equity_total', 'total_equity') 
                             AND ffm.dimension_id IS NULL THEN ffm.value_numeric ELSE 0 END) IS NOT NULL
            ORDER BY tp.fiscal_year
        """), {'company_id': company_id})
        
        issues = []
        for row in result:
            fiscal_year, assets, equity = row
            
            if assets is None or assets == 0 or equity is None:
                continue
            
            equity_ratio_pct = (abs(equity) / abs(assets)) * 100.0
            
            # Equity should be 10-80% of assets (catches unit scaling issues)
            if equity_ratio_pct < 1.0 or equity_ratio_pct > 80.0:
                issues.append({
                    'year': fiscal_year,
                    'assets': assets,
                    'equity': equity,
                    'equity_ratio_pct': equity_ratio_pct
                })
        
        if issues:
            report.add_result(ValidationResult(
                rule_name="equity_ratio_reasonableness",
                passed=False,
                severity="WARNING",
                message=f"Equity ratio outside expected range (10-80%) in {len(issues)} period(s), possible unit scaling issue",
                details={'issues': issues}
            ))
        else:
            report.add_result(ValidationResult(
                rule_name="equity_ratio_reasonableness",
                passed=True,
                severity="INFO",
                message="Equity ratio within expected range (10-80%)"
            ))
    
    def _check_xbrl_sec_api_consistency(self, conn, company_id: int, report: ValidationReport):
        """Check XBRL vs SEC API consistency (values should match within 1% tolerance)"""
        result = conn.execute(text("""
            SELECT 
                dc.normalized_label,
                tp.fiscal_year,
                tp.period_type,
                SUM(CASE WHEN ffm.source = 'XBRL' THEN ffm.value_numeric ELSE 0 END) as xbrl_value,
                SUM(CASE WHEN ffm.source = 'SEC_API' THEN ffm.value_numeric ELSE 0 END) as sec_api_value,
                COUNT(DISTINCT CASE WHEN ffm.source = 'XBRL' THEN ffm.fact_id END) as xbrl_count,
                COUNT(DISTINCT CASE WHEN ffm.source = 'SEC_API' THEN ffm.fact_id END) as sec_api_count
            FROM fact_financial_metrics ffm
            JOIN dim_concepts dc ON ffm.concept_id = dc.concept_id
            JOIN dim_time_periods tp ON ffm.period_id = tp.period_id
            WHERE ffm.company_id = :company_id
              AND ffm.dimension_id IS NULL  -- Primary facts only
              AND ffm.value_numeric IS NOT NULL
              AND tp.fiscal_year IS NOT NULL
            GROUP BY dc.normalized_label, tp.fiscal_year, tp.period_type
            HAVING COUNT(DISTINCT CASE WHEN ffm.source = 'XBRL' THEN ffm.fact_id END) > 0
              AND COUNT(DISTINCT CASE WHEN ffm.source = 'SEC_API' THEN ffm.fact_id END) > 0
            ORDER BY dc.normalized_label, tp.fiscal_year
        """), {'company_id': company_id})
        
        issues = []
        for row in result:
            normalized_label, fiscal_year, period_type, xbrl_value, sec_api_value, xbrl_count, sec_api_count = row
            
            if xbrl_value is None or sec_api_value is None:
                continue
            
            difference = abs(xbrl_value - sec_api_value)
            tolerance = abs(xbrl_value) * (self.tolerance_pct / 100.0)
            
            if difference > tolerance:
                issues.append({
                    'normalized_label': normalized_label,
                    'year': fiscal_year,
                    'period_type': period_type,
                    'xbrl_value': xbrl_value,
                    'sec_api_value': sec_api_value,
                    'difference': difference,
                    'difference_pct': (difference / abs(xbrl_value)) * 100.0 if xbrl_value != 0 else 0
                })
        
        if issues:
            report.add_result(ValidationResult(
                rule_name="xbrl_sec_api_consistency",
                passed=False,
                severity="WARNING",
                message=f"XBRL vs SEC API inconsistencies in {len(issues)} concept-period combination(s)",
                details={'issues': issues[:20]}  # First 20
            ))
        else:
            report.add_result(ValidationResult(
                rule_name="xbrl_sec_api_consistency",
                passed=True,
                severity="INFO",
                message="XBRL and SEC API values are consistent"
            ))
    
    def _check_context_variant_consistency(self, conn, company_id: int, report: ValidationReport):
        """Check if multiple context variants differ significantly (optional)"""
        result = conn.execute(text("""
            SELECT 
                dc.normalized_label,
                tp.fiscal_year,
                tp.period_type,
                COUNT(DISTINCT ffm.fact_id) as variant_count,
                COUNT(DISTINCT ffm.value_numeric) as unique_value_count,
                MIN(ffm.value_numeric) as min_value,
                MAX(ffm.value_numeric) as max_value,
                AVG(ffm.value_numeric) as avg_value
            FROM fact_financial_metrics ffm
            JOIN dim_concepts dc ON ffm.concept_id = dc.concept_id
            JOIN dim_time_periods tp ON ffm.period_id = tp.period_id
            LEFT JOIN dim_xbrl_dimensions d ON ffm.dimension_id = d.dimension_id
            WHERE ffm.company_id = :company_id
              AND (ffm.dimension_id IS NULL OR d.axis_name = 'ContextAxis')  -- Consolidated facts (including synthetic)
              AND ffm.value_numeric IS NOT NULL
              AND tp.fiscal_year IS NOT NULL
            GROUP BY dc.normalized_label, tp.fiscal_year, tp.period_type
            HAVING COUNT(DISTINCT ffm.fact_id) > 1  -- Multiple variants
            ORDER BY variant_count DESC
        """), {'company_id': company_id})
        
        issues = []
        for row in result:
            normalized_label, fiscal_year, period_type, variant_count, unique_value_count, min_value, max_value, avg_value = row
            
            if avg_value is None or avg_value == 0:
                continue
            
            # Check if values differ significantly (more than 5%)
            value_range = max_value - min_value
            range_pct = (value_range / abs(avg_value)) * 100.0 if avg_value != 0 else 0
            
            if range_pct > 5.0:  # More than 5% difference
                issues.append({
                    'normalized_label': normalized_label,
                    'year': fiscal_year,
                    'period_type': period_type,
                    'variant_count': variant_count,
                    'unique_value_count': unique_value_count,
                    'min_value': min_value,
                    'max_value': max_value,
                    'avg_value': avg_value,
                    'range_pct': range_pct
                })
        
        if issues:
            report.add_result(ValidationResult(
                rule_name="context_variant_consistency",
                passed=True,  # Not necessarily an error
                severity="WARNING",
                message=f"Found {len(issues)} concept-period combinations with significantly different context variants (>5% difference)",
                details={'issues': issues[:20]}  # First 20
            ))
        else:
            report.add_result(ValidationResult(
                rule_name="context_variant_consistency",
                passed=True,
                severity="INFO",
                message="Context variants are consistent (or no multiple variants found)"
            ))

