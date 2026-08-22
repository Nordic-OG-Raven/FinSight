"""
Fix Equity Values in fact_financial_metrics

Corrects equity values that are clearly wrong (unit scaling issues) by calculating
them as Assets - Liabilities. This ensures the balance sheet equation holds.

UNIVERSAL FIX: Runs after all data is loaded to correct equity values that are
incorrectly scaled (e.g., equity in millions when assets/liabilities in base currency).
"""
import logging
from sqlalchemy import create_engine, text
from config import DATABASE_URI

logger = logging.getLogger(__name__)


def fix_equity_values():
    """
    Fix equity values in fact_financial_metrics that are clearly wrong.
    
    CRITICAL: Equity should be ~30-50% of assets for healthy companies.
    If equity is < 1% of assets, it's clearly wrong (likely unit scaling issue).
    
    Updates fact_financial_metrics directly to ensure balance sheet equation holds.
    """
    engine = create_engine(DATABASE_URI)
    fixed_count = 0
    
    with engine.begin() as conn:
        # Find equity values that are clearly wrong
        query = text("""
            WITH wrong_equity AS (
                SELECT 
                    fm_equity.fact_id,
                    fm_equity.filing_id,
                    fm_equity.period_id,
                    fm_equity.value_numeric as equity_value,
                    fm_assets.value_numeric as assets_value,
                    fm_liab.value_numeric as liabilities_value,
                    fm_assets.value_numeric - COALESCE(fm_liab.value_numeric, 0) as calculated_equity,
                    c.ticker,
                    tp.fiscal_year
                FROM fact_financial_metrics fm_equity
                JOIN dim_concepts dc_equity ON fm_equity.concept_id = dc_equity.concept_id
                JOIN dim_companies c ON fm_equity.company_id = c.company_id
                JOIN dim_time_periods tp ON fm_equity.period_id = tp.period_id
                JOIN fact_financial_metrics fm_assets ON 
                    fm_assets.filing_id = fm_equity.filing_id
                    AND fm_assets.period_id = fm_equity.period_id
                    AND fm_assets.dimension_id IS NULL
                JOIN dim_concepts dc_assets ON fm_assets.concept_id = dc_assets.concept_id
                LEFT JOIN fact_financial_metrics fm_liab ON 
                    fm_liab.filing_id = fm_equity.filing_id
                    AND fm_liab.period_id = fm_equity.period_id
                    AND fm_liab.dimension_id IS NULL
                LEFT JOIN dim_concepts dc_liab ON fm_liab.concept_id = dc_liab.concept_id
                WHERE (dc_equity.normalized_label = 'equity_total' OR dc_equity.normalized_label = 'total_equity')
                  AND (dc_assets.normalized_label = 'total_assets' OR dc_assets.normalized_label = 'assets_total')
                  AND (dc_liab.normalized_label = 'total_liabilities' OR dc_liab.normalized_label = 'liabilities_total' OR dc_liab.normalized_label IS NULL)
                  AND fm_equity.dimension_id IS NULL
                  AND tp.period_type = 'instant'
                  AND fm_equity.value_numeric IS NOT NULL
                  AND fm_assets.value_numeric IS NOT NULL
                  -- Equity is clearly wrong if:
                  -- 1. It's < 1% of assets (unit scaling issue), OR
                  -- 2. It differs significantly from calculated equity (Assets - Liabilities)
                  -- For healthy companies, equity should be ~30-50% of assets
                  AND (
                      ABS(fm_equity.value_numeric) < ABS(fm_assets.value_numeric) * 0.01
                      OR ABS(fm_equity.value_numeric - (fm_assets.value_numeric - COALESCE(fm_liab.value_numeric, 0))) > ABS(fm_assets.value_numeric - COALESCE(fm_liab.value_numeric, 0)) * 0.05  -- More than 5% difference from calculated
                  )
            )
            SELECT fact_id, filing_id, period_id, equity_value, assets_value, liabilities_value, calculated_equity, ticker, fiscal_year
            FROM wrong_equity
            ORDER BY ticker, fiscal_year
        """)
        
        wrong_equities = conn.execute(query).fetchall()
        
        if wrong_equities:
            logger.info(f"Found {len(wrong_equities)} equity values that need fixing")
            
            for row in wrong_equities:
                fact_id, filing_id, period_id, equity_value, assets_value, liabilities_value, calculated_equity, ticker, fiscal_year = row
                
                # Update equity value with calculated value
                update_query = text("""
                    UPDATE fact_financial_metrics
                    SET value_numeric = :calculated_equity,
                        is_calculated = TRUE
                    WHERE fact_id = :fact_id
                """)
                
                conn.execute(update_query, {
                    'calculated_equity': calculated_equity,
                    'fact_id': fact_id
                })
                
                fixed_count += 1
                logger.debug(f"Fixed equity for {ticker} {fiscal_year}: {equity_value:,.0f} -> {calculated_equity:,.0f}")
        
        if fixed_count > 0:
            logger.info(f"✅ Fixed {fixed_count} equity values")
        else:
            logger.info("✅ No equity values needed fixing")
    
    return fixed_count


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    fixed = fix_equity_values()
    print(f"Fixed {fixed} equity values")

