#!/usr/bin/env python3
"""
Calculate and populate financial ratios.

This script calculates common financial ratios and stores them in fact_ratios table.
Ratios are pre-calculated for performance and can be used for cross-company analysis.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from config import DATABASE_URI


def calculate_ratios(company_id: int = None, period_id: int = None):
    """
    Calculate financial ratios for companies/periods.
    
    Args:
        company_id: If provided, only calculate for this company
        period_id: If provided, only calculate for this period
    """
    engine = create_engine(DATABASE_URI)
    
    with engine.connect() as conn:
        # Define ratio calculations
        ratios = [
            {
                'ratio_type': 'roe',
                'numerator_label': 'net_income',
                'denominator_label': 'equity_total',
                'description': 'Return on Equity = Net Income / Total Equity'
            },
            {
                'ratio_type': 'roa',
                'numerator_label': 'net_income',
                'denominator_label': 'total_assets',
                'description': 'Return on Assets = Net Income / Total Assets'
            },
            {
                'ratio_type': 'current_ratio',
                'numerator_label': 'current_assets',
                'denominator_label': 'current_liabilities',
                'description': 'Current Ratio = Current Assets / Current Liabilities'
            },
            {
                'ratio_type': 'debt_to_equity',
                'numerator_label': 'total_liabilities',
                'denominator_label': 'equity_total',
                'description': 'Debt to Equity = Total Liabilities / Total Equity'
            },
            {
                'ratio_type': 'gross_margin',
                'numerator_label': 'gross_profit',
                'denominator_label': 'revenue',
                'description': 'Gross Margin = Gross Profit / Revenue'
            },
            {
                'ratio_type': 'net_margin',
                'numerator_label': 'net_income',
                'denominator_label': 'revenue',
                'description': 'Net Margin = Net Income / Revenue'
            },
        ]
        
        # Build WHERE clause
        where_clause = "WHERE 1=1"
        params = {}
        if company_id:
            where_clause += " AND fm.company_id = :company_id"
            params['company_id'] = company_id
        if period_id:
            where_clause += " AND fm.period_id = :period_id"
            params['period_id'] = period_id
        
        ratios_calculated = 0
        
        for ratio_def in ratios:
            ratio_type = ratio_def['ratio_type']
            numerator_label = ratio_def['numerator_label']
            denominator_label = ratio_def['denominator_label']
            
            # Get concept IDs
            numerator_result = conn.execute(text("""
                SELECT concept_id FROM dim_concepts 
                WHERE normalized_label = :numerator_label
                LIMIT 1
            """), {"numerator_label": numerator_label})
            numerator_row = numerator_result.fetchone()
            numerator_concept_id = numerator_row[0] if numerator_row else None
            
            denominator_result = conn.execute(text("""
                SELECT concept_id FROM dim_concepts 
                WHERE normalized_label = :denominator_label
                LIMIT 1
            """), {"denominator_label": denominator_label})
            denominator_row = denominator_result.fetchone()
            denominator_concept_id = denominator_row[0] if denominator_row else None
            
            if not numerator_concept_id or not denominator_concept_id:
                print(f"   ⚠️  Skipping {ratio_type}: concepts not found")
                continue
            
            # Calculate ratio for each company-period combination
            query = text(f"""
                INSERT INTO fact_ratios (
                    company_id, period_id, ratio_type, ratio_value,
                    numerator_concept_id, denominator_concept_id, calculation_method
                )
                SELECT 
                    num.company_id,
                    num.period_id,
                    :ratio_type,
                    CASE 
                        WHEN den.value_numeric IS NOT NULL AND den.value_numeric != 0 
                        THEN num.value_numeric / den.value_numeric
                        ELSE NULL
                    END as ratio_value,
                    :numerator_concept_id,
                    :denominator_concept_id,
                    :description
                FROM fact_financial_metrics num
                JOIN fact_financial_metrics den ON 
                    num.company_id = den.company_id
                    AND num.period_id = den.period_id
                    AND num.filing_id = den.filing_id
                    AND num.dimension_id IS NULL
                    AND den.dimension_id IS NULL
                WHERE num.concept_id = :numerator_concept_id
                  AND den.concept_id = :denominator_concept_id
                  AND num.value_numeric IS NOT NULL
                  AND den.value_numeric IS NOT NULL
                  {where_clause}
                ON CONFLICT (company_id, period_id, ratio_type) 
                DO UPDATE SET
                    ratio_value = EXCLUDED.ratio_value,
                    numerator_concept_id = EXCLUDED.numerator_concept_id,
                    denominator_concept_id = EXCLUDED.denominator_concept_id,
                    calculation_method = EXCLUDED.calculation_method
            """)
            
            query_params = {
                'ratio_type': ratio_type,
                'numerator_concept_id': numerator_concept_id,
                'denominator_concept_id': denominator_concept_id,
                'description': ratio_def['description'],
                **params
            }
            
            result = conn.execute(query, query_params)
            ratios_calculated += result.rowcount
            conn.commit()
        
        print(f"   ✅ Calculated {ratios_calculated} ratios")
        return ratios_calculated


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Calculate financial ratios')
    parser.add_argument('--company-id', type=int, help='Calculate for specific company')
    parser.add_argument('--period-id', type=int, help='Calculate for specific period')
    args = parser.parse_args()
    
    calculate_ratios(company_id=args.company_id, period_id=args.period_id)

