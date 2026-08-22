"""
Fix Unit Scaling Issues in fact_financial_metrics

Detects and corrects unit scaling issues for balance sheet items (assets, liabilities, equity)
by using the balance sheet equation: Assets = Liabilities + Equity

UNIVERSAL FIX: Runs after all data is loaded to correct values that are incorrectly scaled.
"""
import logging
from sqlalchemy import create_engine, text
from config import DATABASE_URI

logger = logging.getLogger(__name__)


def fix_unit_scaling():
    """
    Fix unit scaling issues in fact_financial_metrics for balance sheet items.
    
    Detects when balance sheet equation doesn't hold due to unit scaling errors:
    - Assets way too large (> 100x larger than Liabilities + Equity)
    - Assets way too small (< 0.01x of Liabilities + Equity)
    
    Fixes by detecting the correct scale factor and applying it.
    """
    engine = create_engine(DATABASE_URI)
    fixed_count = 0
    
    with engine.begin() as conn:
        # Find balance sheet items with unit scaling issues
        query = text("""
            WITH balance_sheet_data AS (
                SELECT 
                    c.ticker,
                    tp.fiscal_year,
                    tp.period_id,
                    f.filing_id,
                    MAX(CASE WHEN dc.normalized_label = 'total_assets' THEN f.fact_id END) as assets_fact_id,
                    MAX(CASE WHEN dc.normalized_label = 'total_assets' THEN f.value_numeric END) as assets_value,
                    MAX(CASE WHEN dc.normalized_label = 'total_liabilities' THEN f.value_numeric END) as liabilities_value,
                    MAX(CASE WHEN dc.normalized_label IN ('equity_total', 'stockholders_equity') THEN f.value_numeric END) as equity_value,
                    MAX(CASE WHEN dc.normalized_label = 'equity_and_liabilities' THEN f.value_numeric END) as equity_and_liabilities_value,
                    MAX(CASE WHEN dc.normalized_label = 'liabilities_and_stockholders_equity' THEN f.value_numeric END) as liabilities_and_stockholders_equity_value
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                JOIN dim_time_periods tp ON f.period_id = tp.period_id
                WHERE f.dimension_id IS NULL
                  AND tp.period_type = 'instant'
                  AND tp.fiscal_year IS NOT NULL
                  AND f.value_numeric IS NOT NULL
                GROUP BY c.ticker, tp.fiscal_year, tp.period_id, f.filing_id
                HAVING MAX(CASE WHEN dc.normalized_label = 'total_assets' THEN f.value_numeric END) IS NOT NULL
            ),
            scaling_issues AS (
                SELECT 
                    ticker,
                    fiscal_year,
                    period_id,
                    filing_id,
                    assets_fact_id,
                    assets_value,
                    COALESCE(
                        equity_and_liabilities_value,
                        liabilities_and_stockholders_equity_value,
                        COALESCE(liabilities_value, 0) + COALESCE(equity_value, 0)
                    ) as liab_equity_value,
                    -- Calculate ratio to detect scaling issues
                    CASE 
                        WHEN assets_value > 0 AND COALESCE(equity_and_liabilities_value, liabilities_and_stockholders_equity_value, COALESCE(liabilities_value, 0) + COALESCE(equity_value, 0)) > 0
                        THEN assets_value / NULLIF(COALESCE(equity_and_liabilities_value, liabilities_and_stockholders_equity_value, COALESCE(liabilities_value, 0) + COALESCE(equity_value, 0)), 0)
                        ELSE NULL
                    END as ratio
                FROM balance_sheet_data
                WHERE assets_value IS NOT NULL
                  AND (
                      COALESCE(equity_and_liabilities_value, liabilities_and_stockholders_equity_value, COALESCE(liabilities_value, 0) + COALESCE(equity_value, 0)) IS NOT NULL
                  )
            )
            SELECT 
                fm.fact_id,
                si.filing_id,
                si.period_id,
                si.ticker,
                si.fiscal_year,
                si.assets_value,
                si.liab_equity_value,
                si.ratio,
                -- Calculate correct assets value (use liab_equity as source of truth)
                si.liab_equity_value as corrected_assets_value
            FROM scaling_issues si
            JOIN fact_financial_metrics fm ON si.assets_fact_id = fm.fact_id
            WHERE si.ratio > 100 OR si.ratio < 0.01  -- Way off (unit scaling issue)
               OR ABS(si.assets_value - si.liab_equity_value) / NULLIF(si.assets_value, 0) > 0.90  -- > 90% difference
            ORDER BY ticker, fiscal_year
        """)
        
        issues = conn.execute(query).fetchall()
        
        if issues:
            logger.info(f"Found {len(issues)} unit scaling issues to fix")
            
            for row in issues:
                fact_id, filing_id, period_id, ticker, fiscal_year, assets_value, liab_equity_value, ratio, corrected_assets_value = row
                if not fact_id:  # Skip if no fact_id found
                    continue
                
                # Update assets value to match liab_equity (use liab_equity as source of truth)
                update_query = text("""
                    UPDATE fact_financial_metrics
                    SET value_numeric = :corrected_value,
                        is_calculated = TRUE
                    WHERE fact_id = :fact_id
                """)
                
                conn.execute(update_query, {
                    'corrected_value': corrected_assets_value,
                    'fact_id': fact_id
                })
                
                fixed_count += 1
                logger.info(f"Fixed unit scaling for {ticker} {fiscal_year}: Assets ${assets_value:,.0f} -> ${corrected_assets_value:,.0f} (ratio: {ratio:.2f}x)")
        
        # Also fix individual values that are clearly too large (>= 10^18, which exceeds NUMERIC(20,2) limit)
        # These are likely unit scaling issues where values are 1000x too large
        overflow_query = text("""
        SELECT 
            fm.fact_id,
            c.ticker,
            tp.fiscal_year,
            co.normalized_label,
            fm.value_numeric,
            -- Divide by 1000 if value is >= 10^18 (likely 1000x scaling error)
            CASE 
                WHEN ABS(fm.value_numeric) >= 1000000000000000000 THEN fm.value_numeric / 1000.0
                ELSE fm.value_numeric
            END as corrected_value
        FROM fact_financial_metrics fm
        JOIN dim_companies c ON fm.company_id = c.company_id
        JOIN dim_concepts co ON fm.concept_id = co.concept_id
        JOIN dim_time_periods tp ON fm.period_id = tp.period_id
        WHERE ABS(fm.value_numeric) >= 1000000000000000000  -- >= 10^18 (exceeds NUMERIC(20,2) limit)
          AND fm.dimension_id IS NULL
          AND fm.value_numeric IS NOT NULL
        ORDER BY ABS(fm.value_numeric) DESC
    """)
    
        overflow_issues = conn.execute(overflow_query).fetchall()
        
        overflow_fixed = 0
        if overflow_issues:
            logger.info(f"Found {len(overflow_issues)} values that exceed NUMERIC(20,2) limit")
        
        for row in overflow_issues:
            fact_id, ticker, fiscal_year, normalized_label, original_value, corrected_value = row
            
            # Update value (divide by 1000 to fix 1000x scaling error)
            update_query = text("""
                UPDATE fact_financial_metrics
                SET value_numeric = :corrected_value,
                    is_calculated = TRUE
                WHERE fact_id = :fact_id
            """)
            
            conn.execute(update_query, {
                'corrected_value': corrected_value,
                'fact_id': fact_id
            })
            
            overflow_fixed += 1
            logger.info(f"Fixed overflow for {ticker} {fiscal_year} {normalized_label}: {original_value:,.0f} -> {corrected_value:,.0f}")
        
        total_fixed = fixed_count + overflow_fixed
        if total_fixed > 0:
            logger.info(f"✅ Fixed {total_fixed} total unit scaling/overflow issues ({fixed_count} balance sheet, {overflow_fixed} overflow)")
        else:
            logger.info("✅ No unit scaling issues found")
    
    return total_fixed


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    fixed = fix_unit_scaling()
    print(f"Fixed {fixed} unit scaling issues")

