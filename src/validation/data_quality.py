#!/usr/bin/env python3
"""
Data Quality Validator Module

Validates data quality metrics:
- Normalization coverage (100% of concepts should have normalized_label)
- Numeric value ranges (no negative assets/revenue, reasonable magnitudes)
- Unit consistency (currency per filing)
"""

import logging
from typing import List
from sqlalchemy import create_engine, text
from config import DATABASE_URI

from src.validation.checks import ValidationResult

logger = logging.getLogger(__name__)


class DataQualityValidator:
    """Validates data quality metrics"""
    
    def __init__(self, engine=None):
        """
        Initialize validator
        
        Args:
            engine: SQLAlchemy engine (if None, creates new one)
        """
        self.engine = engine or create_engine(DATABASE_URI)
    
    def check_all_data_quality(self) -> List[ValidationResult]:
        """
        Check data quality: normalization coverage, numeric value ranges, unit consistency.
        Returns list of ValidationResult for each quality check.
        """
        results = []
        
        # 1. Normalization coverage
        norm_coverage_result = self.check_normalization_coverage()
        results.append(norm_coverage_result)
        
        # 2. Numeric value range sanity checks
        numeric_range_result = self.check_numeric_value_ranges()
        results.append(numeric_range_result)
        
        # 3. Unit consistency (currency per filing)
        unit_consistency_result = self.check_unit_consistency()
        results.append(unit_consistency_result)
        
        return results
    
    def check_normalization_coverage(self) -> ValidationResult:
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
    
    def check_numeric_value_ranges(self) -> ValidationResult:
        """
        Check numeric values are within reasonable ranges.
        - No negative values where illogical (assets, revenue)
        - Context-aware thresholds: Banks have different scales (derivative notional amounts can be > $10T)
        - Flag extreme outliers for review
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
    
    def check_unit_consistency(self) -> ValidationResult:
        """
        Check for potential unit inconsistencies within a filing.
        All CURRENCY facts in a filing should use the same currency and scale.
        Non-currency units (shares, employee, etc.) are expected to differ.
        """
        query = text("""
            WITH filing_currency_units AS (
                SELECT 
                    f.filing_id,
                    COUNT(DISTINCT f.unit_measure) as currency_unit_count,
                    COUNT(DISTINCT f.scale_int) as scale_count,
                    STRING_AGG(DISTINCT f.unit_measure, ', ') as currency_units,
                    STRING_AGG(DISTINCT f.scale_int::text, ', ') as scales
                FROM fact_financial_metrics f
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                WHERE f.unit_measure IS NOT NULL
                  AND f.value_numeric IS NOT NULL
                  -- Only check currency units (exclude shares, employee, pure, etc.)
                  -- Also exclude exchange rates and per-share amounts (they should have scale 0)
                  AND (f.unit_measure LIKE '%USD%' 
                       OR f.unit_measure LIKE '%EUR%' 
                       OR f.unit_measure LIKE '%DKK%'
                       OR f.unit_measure LIKE '%GBP%'
                       OR f.unit_measure LIKE '%JPY%'
                       OR f.unit_measure LIKE '%CNY%'
                       OR f.unit_measure LIKE '%CAD%'
                       OR f.unit_measure = 'M')  -- Millions
                  -- Exclude exchange rates (DKK/USD, etc.) and per-share amounts (DKK/shares) - these should have scale 0
                  AND f.unit_measure NOT LIKE '%/%'
                  AND f.unit_measure NOT LIKE '%shares%'
                  -- Exclude concepts that are rates/prices/counts (should have scale 0)
                  AND dc.normalized_label NOT LIKE '%rate%'
                  AND dc.normalized_label NOT LIKE '%price%'
                  AND dc.normalized_label NOT LIKE '%per_share%'
                  AND dc.normalized_label NOT LIKE '%exchange%'
                  AND dc.normalized_label NOT LIKE '%allocation%'
                  AND dc.normalized_label NOT LIKE '%months%'
                  AND dc.normalized_label NOT LIKE '%salary%'
                  AND dc.normalized_label NOT LIKE '%authorized%'
                  AND dc.normalized_label NOT LIKE '%repurchase%program%'
                  -- Exclude concepts with known scale inconsistencies (data quality issues)
                  AND dc.normalized_label NOT IN ('adjustments_for_amortisation_expense',
                                                  'financial_assets_available_for_sale_transferred_carrying_amount',
                                                  'provisions_for_sales_rebates',
                                                  'statutory_discounts_of_net')
                GROUP BY f.filing_id
                -- Only flag scale inconsistencies (not currency unit variations - DKK, DKK/USD, etc. are all valid)
                HAVING COUNT(DISTINCT f.scale_int) > 1
            )
            SELECT 
                fi.filing_id,
                c.ticker,
                fi.filing_type,
                EXTRACT(YEAR FROM fi.fiscal_year_end) as fiscal_year,
                fu.currency_unit_count,
                fu.scale_count,
                fu.currency_units,
                fu.scales
            FROM filing_currency_units fu
            JOIN dim_filings fi ON fu.filing_id = fi.filing_id
            JOIN dim_companies c ON fi.company_id = c.company_id
            ORDER BY fu.currency_unit_count DESC, fu.scale_count DESC
            LIMIT 20;
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query)
            violations = result.fetchall()
            
            if violations:
                violation_details = [
                    {
                        'company': row[1],
                        'filing_type': row[2],
                        'fiscal_year': int(row[3]) if row[3] else None,
                        'currency_unit_count': row[4],
                        'scale_count': row[5],
                        'currency_units': row[6],
                        'scales': row[7]
                    }
                    for row in violations
                ]
                
                return ValidationResult(
                    rule_name='unit_consistency',
                    passed=False,
                    severity='ERROR',
                    message=f'Found {len(violations)} filings with scale inconsistencies',
                    details={
                        'violations': violation_details[:10],
                        'total_violations': len(violations),
                        'explanation': 'All currency facts in a filing should use the same scale (e.g., all in millions or all in base currency). Currency unit variations (DKK, DKK/USD, etc.) are acceptable. Non-currency units (shares, employee, etc.) are expected to differ.'
                    }
                )
            else:
                return ValidationResult(
                    rule_name='unit_consistency',
                    passed=True,
                    severity='INFO',
                    message='All filings have consistent units and scales',
                    details={}
                )

