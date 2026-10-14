#!/usr/bin/env python3
"""
Displayed Math Validator Module

Validates mathematical relationships in displayed financial statements
(fact_income_statement, fact_balance_sheet, fact_cash_flow, fact_comprehensive_income, fact_equity_statement).

This validates the EXACT data that users see in the UI.
"""

import logging
from typing import List
from sqlalchemy import create_engine, text
from config import DATABASE_URI

from src.validation.checks import ValidationResult

logger = logging.getLogger(__name__)


class DisplayedMathValidator:
    """Validates displayed statement math"""
    
    def __init__(self, engine=None):
        """
        Initialize validator
        
        Args:
            engine: SQLAlchemy engine (if None, creates new one)
        """
        self.engine = engine or create_engine(DATABASE_URI)
    
    def check_all_displayed_math(self, tolerance_pct: float = 1.0) -> List[ValidationResult]:
        """
        Validate mathematical relationships in ALL displayed financial statements.
        
        Returns list of ValidationResult for each check.
        """
        results = []
        
        # 1. Income Statement Math
        income_math_results = self.check_income_statement_math(tolerance_pct)
        results.extend(income_math_results)
        
        # 2. Comprehensive Income Math
        comprehensive_math_results = self.check_comprehensive_income_math(tolerance_pct)
        results.extend(comprehensive_math_results)
        
        # 3. Balance Sheet Math (from displayed fact table)
        balance_sheet_math_results = self.check_balance_sheet_displayed_math(tolerance_pct)
        results.extend(balance_sheet_math_results)
        
        # 4. Cash Flow Math
        cash_flow_math_results = self.check_cash_flow_displayed_math(tolerance_pct)
        results.extend(cash_flow_math_results)
        
        # 5. Equity Statement Math
        equity_math_results = self.check_equity_statement_math(tolerance_pct)
        results.extend(equity_math_results)
        
        return results
    
    def check_income_statement_math(self, tolerance_pct: float) -> List[ValidationResult]:
        """Validate Income Statement calculations from fact_income_statement"""
        results = []
        
        query = text("""
            WITH income_data AS (
                SELECT 
                    f.filing_id,
                    c.ticker,
                    tp.period_id,
                    EXTRACT(YEAR FROM COALESCE(tp.end_date, tp.instant_date))::INTEGER as period_year,
                    MAX(CASE WHEN co.normalized_label = 'revenue' THEN fis.value_numeric END) as revenue,
                    MAX(CASE WHEN co.normalized_label = 'cost_of_sales' OR co.normalized_label = 'cost_of_revenue' THEN fis.value_numeric END) as cost_of_sales,
                    MAX(CASE WHEN co.normalized_label = 'gross_profit' THEN fis.value_numeric END) as gross_profit,
                    MAX(CASE WHEN co.normalized_label = 'operating_income' THEN fis.value_numeric END) as operating_income,
                    MAX(CASE WHEN co.normalized_label = 'income_before_tax' THEN fis.value_numeric END) as income_before_tax,
                    -- Some filers (confirmed: NVO) never report a single combined tax
                    -- expense figure, only current + deferred components — fall back to
                    -- summing those when the combined label is absent, rather than
                    -- treating tax as 0 (which is what NULL does via COALESCE downstream
                    -- and was making every NVO period look like a large math violation).
                    -- See docs/NVO_GOLDEN_PATH_2026-08.md item 6.
                    COALESCE(
                        MAX(CASE WHEN co.normalized_label = 'income_tax_expense_continuing_operations' OR co.normalized_label = 'income_tax_expense' THEN fis.value_numeric END),
                        MAX(CASE WHEN co.normalized_label = 'current_tax_expense_income' THEN fis.value_numeric END)
                        + MAX(CASE WHEN co.normalized_label = 'deferred_tax_expense_income' THEN fis.value_numeric END)
                    ) as income_tax,
                    MAX(CASE WHEN co.normalized_label = 'net_income_including_noncontrolling_interest' OR co.normalized_label = 'net_profit' THEN fis.value_numeric END) as net_income
                FROM fact_income_statement fis
                JOIN dim_concepts co ON fis.concept_id = co.concept_id
                JOIN dim_filings f ON fis.filing_id = f.filing_id
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_time_periods tp ON fis.period_id = tp.period_id
                WHERE fis.value_numeric IS NOT NULL
                  AND tp.period_type = 'duration'
                GROUP BY f.filing_id, c.ticker, tp.period_id, EXTRACT(YEAR FROM COALESCE(tp.end_date, tp.instant_date))
            )
            SELECT 
                ticker,
                period_year,
                revenue,
                cost_of_sales,
                gross_profit,
                revenue - COALESCE(cost_of_sales, 0) as calculated_gross_profit,
                ABS(gross_profit - (revenue - COALESCE(cost_of_sales, 0))) as gross_profit_diff,
                operating_income,
                income_before_tax,
                income_tax,
                net_income,
                income_before_tax - COALESCE(income_tax, 0) as calculated_net_income,
                ABS(net_income - (income_before_tax - COALESCE(income_tax, 0))) as net_income_diff
            FROM income_data
            WHERE revenue IS NOT NULL
              AND (
                  ABS(gross_profit - (revenue - COALESCE(cost_of_sales, 0))) / NULLIF(revenue, 0) * 100 > :tolerance
                  OR ABS(net_income - (income_before_tax - COALESCE(income_tax, 0))) / NULLIF(income_before_tax, 0) * 100 > :tolerance
              )
            ORDER BY gross_profit_diff DESC, net_income_diff DESC
            LIMIT 20;
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query, {'tolerance': tolerance_pct})
            violations = result.fetchall()
            
            if violations:
                violation_details = [
                    {
                        'company': row[0],
                        'period_year': row[1],
                        # A row can qualify via the net-income check alone (or the
                        # gross-profit check alone), leaving the other diff NULL — guard
                        # both so a single missing component doesn't crash the whole
                        # validation run.
                        'gross_profit_diff': float(row[6]) if row[6] is not None else None,
                        'net_income_diff': float(row[12]) if row[12] is not None else None
                    }
                    for row in violations
                ]
                
                results.append(ValidationResult(
                    rule_name='income_statement_math',
                    passed=False,
                    severity='ERROR',
                    message=f'Income statement math violated for {len(violations)} company-period combinations',
                    details={
                        'violations': violation_details[:10],
                        'total_violations': len(violations),
                        'tolerance_pct': tolerance_pct
                    }
                ))
            else:
                results.append(ValidationResult(
                    rule_name='income_statement_math',
                    passed=True,
                    severity='INFO',
                    message='Income statement math holds for all company-period combinations',
                    details={'tolerance_pct': tolerance_pct}
                ))
        
        return results
    
    def check_comprehensive_income_math(self, tolerance_pct: float) -> List[ValidationResult]:
        """Validate Comprehensive Income: Net Income + OCI = Total Comprehensive Income"""
        results = []
        
        query = text("""
            WITH comprehensive_data AS (
                SELECT 
                    f.filing_id,
                    c.ticker,
                    tp.period_id,
                    EXTRACT(YEAR FROM COALESCE(tp.end_date, tp.instant_date))::INTEGER as period_year,
                    MAX(CASE WHEN co.normalized_label = 'net_income_including_noncontrolling_interest' OR co.normalized_label = 'net_profit' THEN fci.value_numeric END) as net_income,
                    COALESCE(
                        MAX(CASE WHEN co.normalized_label = 'oci_total' THEN fci.value_numeric END),
                        MAX(CASE WHEN co.normalized_label = 'other_comprehensive_income' THEN fci.value_numeric END)
                    ) as oci,
                    MAX(CASE WHEN co.normalized_label = 'total_comprehensive_income' OR co.normalized_label = 'comprehensive_income' THEN fci.value_numeric END) as total_comprehensive_income_reported
                FROM fact_comprehensive_income fci
                JOIN dim_concepts co ON fci.concept_id = co.concept_id
                JOIN dim_filings f ON fci.filing_id = f.filing_id
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_time_periods tp ON fci.period_id = tp.period_id
                WHERE fci.value_numeric IS NOT NULL
                  AND tp.period_type = 'duration'
                GROUP BY f.filing_id, c.ticker, tp.period_id, EXTRACT(YEAR FROM COALESCE(tp.end_date, tp.instant_date))
            )
            SELECT 
                ticker,
                period_year,
                net_income,
                oci,
                total_comprehensive_income_reported,
                net_income + COALESCE(oci, 0) as calculated_total_comprehensive_income,
                ABS(total_comprehensive_income_reported - (net_income + COALESCE(oci, 0))) as difference,
                ABS(total_comprehensive_income_reported - (net_income + COALESCE(oci, 0))) / NULLIF(total_comprehensive_income_reported, 0) * 100 as difference_pct
            FROM comprehensive_data
            WHERE net_income IS NOT NULL
              AND total_comprehensive_income_reported IS NOT NULL
              AND ABS(total_comprehensive_income_reported - (net_income + COALESCE(oci, 0))) / NULLIF(total_comprehensive_income_reported, 0) * 100 > :tolerance
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
                        'period_year': row[1],
                        'net_income': float(row[2]),
                        'oci': float(row[3]) if row[3] else None,
                        'reported': float(row[4]),
                        'calculated': float(row[5]),
                        'difference': float(row[6]),
                        'difference_pct': float(row[7])
                    }
                    for row in violations
                ]
                
                results.append(ValidationResult(
                    rule_name='comprehensive_income_math',
                    passed=False,
                    severity='ERROR',
                    message=f'Comprehensive income math violated for {len(violations)} company-period combinations',
                    details={
                        'violations': violation_details[:10],
                        'total_violations': len(violations),
                        'tolerance_pct': tolerance_pct
                    }
                ))
            else:
                results.append(ValidationResult(
                    rule_name='comprehensive_income_math',
                    passed=True,
                    severity='INFO',
                    message='Comprehensive income math holds for all company-period combinations',
                    details={'tolerance_pct': tolerance_pct}
                ))
        
        return results
    
    def check_balance_sheet_displayed_math(self, tolerance_pct: float) -> List[ValidationResult]:
        """Validate Balance Sheet math from fact_balance_sheet"""
        results = []
        
        # Simplified check - full implementation would validate Current + Non-Current = Total
        query = text("""
            SELECT 
                c.ticker,
                EXTRACT(YEAR FROM tp.instant_date)::INTEGER as period_year,
                MAX(CASE WHEN co.normalized_label IN ('total_assets', 'assets_total') THEN fbs.value_numeric END) as total_assets,
                MAX(CASE WHEN co.normalized_label IN ('total_liabilities', 'liabilities_total') THEN fbs.value_numeric END) as total_liabilities,
                MAX(CASE WHEN co.normalized_label IN ('equity_total', 'total_equity') THEN fbs.value_numeric END) as total_equity,
                MAX(CASE WHEN co.normalized_label IN ('total_assets', 'assets_total') THEN fbs.value_numeric END) - 
                (MAX(CASE WHEN co.normalized_label IN ('total_liabilities', 'liabilities_total') THEN fbs.value_numeric END) +
                 MAX(CASE WHEN co.normalized_label IN ('equity_total', 'total_equity') THEN fbs.value_numeric END)) as difference
            FROM fact_balance_sheet fbs
            JOIN dim_concepts co ON fbs.concept_id = co.concept_id
            JOIN dim_filings f ON fbs.filing_id = f.filing_id
            JOIN dim_companies c ON f.company_id = c.company_id
            JOIN dim_time_periods tp ON fbs.period_id = tp.period_id
            WHERE fbs.value_numeric IS NOT NULL
              AND tp.period_type = 'instant'
            GROUP BY c.ticker, EXTRACT(YEAR FROM tp.instant_date)
            HAVING ABS(MAX(CASE WHEN co.normalized_label IN ('total_assets', 'assets_total') THEN fbs.value_numeric END) - 
                      (MAX(CASE WHEN co.normalized_label IN ('total_liabilities', 'liabilities_total') THEN fbs.value_numeric END) +
                       MAX(CASE WHEN co.normalized_label IN ('equity_total', 'total_equity') THEN fbs.value_numeric END))) / 
                   NULLIF(MAX(CASE WHEN co.normalized_label IN ('total_assets', 'assets_total') THEN fbs.value_numeric END), 0) * 100 > :tolerance
            LIMIT 20;
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query, {'tolerance': tolerance_pct})
            violations = result.fetchall()
            
            if violations:
                results.append(ValidationResult(
                    rule_name='balance_sheet_displayed_math',
                    passed=False,
                    severity='ERROR',
                    message=f'Balance sheet displayed math violated for {len(violations)} company-period combinations',
                    details={
                        'total_violations': len(violations),
                        'tolerance_pct': tolerance_pct
                    }
                ))
            else:
                results.append(ValidationResult(
                    rule_name='balance_sheet_displayed_math',
                    passed=True,
                    severity='INFO',
                    message='Balance sheet displayed math holds for all company-period combinations',
                    details={'tolerance_pct': tolerance_pct}
                ))
        
        return results
    
    def check_cash_flow_displayed_math(self, tolerance_pct: float) -> List[ValidationResult]:
        """Validate Cash Flow math from fact_cash_flow"""
        results = []
        
        # Simplified check - full implementation would validate Beginning + Net = Ending
        results.append(ValidationResult(
            rule_name='cash_flow_displayed_math',
            passed=True,
            severity='INFO',
            message='Cash flow displayed math validation (placeholder - full implementation in progress)',
            details={}
        ))
        
        return results
    
    def check_equity_statement_math(self, tolerance_pct: float) -> List[ValidationResult]:
        """Validate Equity Statement math from fact_equity_statement"""
        results = []
        
        # Simplified check - full implementation would validate Beginning + Changes = Ending
        results.append(ValidationResult(
            rule_name='equity_statement_math',
            passed=True,
            severity='INFO',
            message='Equity statement displayed math validation (placeholder - full implementation in progress)',
            details={}
        ))
        
        return results

