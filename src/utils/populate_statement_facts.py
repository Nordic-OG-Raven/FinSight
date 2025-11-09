"""
Populate statement-specific fact tables (Approach 2: Denormalized for Performance)

This module populates fact_income_statement, fact_balance_sheet, fact_cash_flow,
and fact_comprehensive_income tables with pre-filtered, pre-ordered facts.

Only main statement items (is_main_item=TRUE) are copied from fact_financial_metrics.
Detail items stay in fact_financial_metrics for other queries.

CRITICAL: This is integrated into the ETL pipeline (load_financial_data.py),
not a separate script. It runs automatically when data is loaded.
"""

import sys
from pathlib import Path
from typing import Optional
from sqlalchemy import create_engine, text
from config import DATABASE_URI

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def populate_statement_facts(filing_id: Optional[int] = None):
    """
    Populate statement-specific fact tables from fact_financial_metrics.
    
    Only copies main statement items (where rel_statement_items.is_main_item = TRUE)
    and filters out comprehensive income items from income statement.
    
    Args:
        filing_id: If provided, only process this filing. Otherwise, process all filings.
    """
    engine = create_engine(DATABASE_URI)
    
    with engine.begin() as conn:
        # Determine which filings to process
        if filing_id:
            filings_to_process = [filing_id]
        else:
            filings_query = text("SELECT DISTINCT filing_id FROM rel_statement_items")
            result = conn.execute(filings_query)
            filings_to_process = [row[0] for row in result.fetchall()]
        
        for current_filing_id in filings_to_process:
            print(f"   Populating statement facts for filing_id: {current_filing_id}")
            
            # Process each statement type
            statement_types = [
                ('income_statement', 'fact_income_statement'),
                ('balance_sheet', 'fact_balance_sheet'),
                ('cash_flow', 'fact_cash_flow'),
                ('comprehensive_income', 'fact_comprehensive_income'),
                ('equity_statement', 'fact_equity_statement')
            ]
            
            for statement_type, table_name in statement_types:
                # Delete existing data for this filing and statement type
                delete_query = text(f"""
                    DELETE FROM {table_name}
                    WHERE filing_id = :filing_id
                """)
                conn.execute(delete_query, {"filing_id": current_filing_id})
                
                # Insert main statement items
                # CRITICAL: For income_statement, exclude comprehensive income items
                # For comprehensive_income, only include OCI items
                if statement_type == 'income_statement':
                    # Income statement: exclude comprehensive income items
                    # CRITICAL: Include headers even if they have no facts (value_numeric IS NULL)
                    insert_query = text(f"""
                        INSERT INTO {table_name} (
                            filing_id, concept_id, period_id, value_numeric, unit_measure,
                            display_order, is_header, hierarchy_level, parent_concept_id
                        )
                        SELECT 
                            si.filing_id,
                            si.concept_id,
                            COALESCE(fm.period_id, (SELECT period_id FROM fact_financial_metrics WHERE filing_id = si.filing_id LIMIT 1)),
                            fm.value_numeric,
                            fm.unit_measure,
                            si.display_order,
                            si.is_header,
                            co.hierarchy_level,
                            -- CRITICAL FIX: For main statement items, ensure parent relationships make sense
                            -- If parent comes AFTER this item in display_order, it's wrong - set to NULL
                            CASE 
                                WHEN co.parent_concept_id IS NOT NULL THEN
                                    CASE 
                                        WHEN EXISTS (
                                            SELECT 1 FROM rel_statement_items si2
                                            JOIN dim_concepts co2 ON si2.concept_id = co2.concept_id
                                            WHERE si2.filing_id = si.filing_id
                                              AND si2.statement_type = si.statement_type
                                              AND co2.concept_id = co.parent_concept_id
                                              AND si2.display_order > si.display_order
                                        ) THEN NULL  -- Parent comes after this item - wrong relationship!
                                        ELSE co.parent_concept_id  -- Parent comes before - OK
                                    END
                                ELSE NULL
                            END as parent_concept_id
                        FROM rel_statement_items si
                        JOIN dim_concepts co ON si.concept_id = co.concept_id
                        LEFT JOIN fact_financial_metrics fm ON 
                            fm.filing_id = si.filing_id 
                            AND fm.concept_id = si.concept_id
                            AND fm.dimension_id IS NULL
                        WHERE si.filing_id = :filing_id
                          AND si.statement_type = :statement_type
                          AND si.is_main_item = TRUE
                          -- Include headers even if they have no facts
                          AND (si.is_header = TRUE OR fm.value_numeric IS NOT NULL)
                          -- CRITICAL: Exclude cash flow statement items that were incorrectly routed to comprehensive_income
                          AND NOT (
                              co.normalized_label ILIKE '%increase_decrease_in_cash%'
                              OR co.normalized_label ILIKE '%effect_of_exchange_rate_changes_on_cash%'
                          )
                          -- Exclude comprehensive income items from income statement
                          AND NOT (
                              co.normalized_label ILIKE '%comprehensive_income%'
                              OR co.normalized_label ILIKE '%other_comprehensive_income%'
                              OR co.normalized_label ILIKE '%oci%'
                              OR co.normalized_label ILIKE '%remeasurement%'
                              OR co.normalized_label ILIKE '%exchange_differences%'
                              OR co.normalized_label ILIKE '%cash_flow_hedge%'
                              OR co.normalized_label ILIKE '%reclassification%'
                              OR co.normalized_label ILIKE '%fair_value_hedge%'
                              OR co.normalized_label ILIKE '%defined_benefit%'
                          )
                        ON CONFLICT (filing_id, concept_id, period_id) DO UPDATE
                        SET value_numeric = EXCLUDED.value_numeric,
                            unit_measure = EXCLUDED.unit_measure,
                            display_order = EXCLUDED.display_order,
                            is_header = EXCLUDED.is_header,
                            hierarchy_level = EXCLUDED.hierarchy_level,
                            parent_concept_id = EXCLUDED.parent_concept_id
                    """)
                elif statement_type == 'comprehensive_income':
                    # Comprehensive income: only include OCI items
                    # CRITICAL: Exclude cash flow statement items that were incorrectly routed
                    # CRITICAL: Include headers even if they have no facts
                    # UNIVERSAL SIGN CORRECTIONS: Based on IFRS/US-GAAP accounting standards
                    # - Reclassification adjustments: reverse sign (they reverse the original deferred gain/loss)
                    # - Tax items in OCI: reverse sign (tax benefits are credits, tax expenses are debits)
                    insert_query = text(f"""
                        INSERT INTO {table_name} (
                            filing_id, concept_id, period_id, value_numeric, unit_measure,
                            display_order, is_header, hierarchy_level, parent_concept_id
                        )
                        SELECT 
                            si.filing_id,
                            si.concept_id,
                            COALESCE(fm.period_id, (SELECT period_id FROM fact_financial_metrics WHERE filing_id = si.filing_id LIMIT 1)),
                            -- UNIVERSAL SIGN CORRECTIONS for comprehensive income items
                            -- Based on IFRS/US-GAAP: reclassification adjustments and tax items need sign reversal
                            CASE 
                                -- Reclassification adjustments: reverse sign (universal IFRS/US-GAAP rule)
                                -- Only apply to items that are explicitly reclassification adjustments for cash flow hedges
                                WHEN co.normalized_label ILIKE '%reclassification_adjustments%' 
                                     AND co.normalized_label ILIKE '%cash_flow_hedges%' 
                                     AND co.normalized_label ILIKE '%before_tax%' THEN
                                    -fm.value_numeric
                                -- Tax items in OCI: reverse sign (universal IFRS/US-GAAP rule)
                                -- Only apply to items that are explicitly tax items relating to OCI components
                                -- Pattern: "income_tax_and_other_relating_to_components_of_other_comprehensive_income"
                                WHEN co.normalized_label ILIKE '%income_tax_and_other_relating_to_components_of_other_comprehensive_income%' THEN
                                    -fm.value_numeric
                                WHEN co.normalized_label ILIKE '%income_tax_relating_to_components_of_other_comprehensive_income%' THEN
                                    -fm.value_numeric
                                ELSE
                                    fm.value_numeric
                            END as value_numeric,
                            fm.unit_measure,
                            si.display_order,
                            si.is_header,
                            co.hierarchy_level,
                            -- CRITICAL FIX: For main statement items, ensure parent relationships make sense
                            -- If parent comes AFTER this item in display_order, it's wrong - set to NULL
                            CASE 
                                WHEN co.parent_concept_id IS NOT NULL THEN
                                    CASE 
                                        WHEN EXISTS (
                                            SELECT 1 FROM rel_statement_items si2
                                            JOIN dim_concepts co2 ON si2.concept_id = co2.concept_id
                                            WHERE si2.filing_id = si.filing_id
                                              AND si2.statement_type = si.statement_type
                                              AND co2.concept_id = co.parent_concept_id
                                              AND si2.display_order > si.display_order
                                        ) THEN NULL  -- Parent comes after this item - wrong relationship!
                                        ELSE co.parent_concept_id  -- Parent comes before - OK
                                    END
                                ELSE NULL
                            END as parent_concept_id
                        FROM rel_statement_items si
                        JOIN dim_concepts co ON si.concept_id = co.concept_id
                        LEFT JOIN fact_financial_metrics fm ON 
                            fm.filing_id = si.filing_id 
                            AND fm.concept_id = si.concept_id
                            AND fm.dimension_id IS NULL
                        WHERE si.filing_id = :filing_id
                          AND si.statement_type = :statement_type
                          AND si.is_main_item = TRUE
                          -- Include headers even if they have no facts
                          AND (si.is_header = TRUE OR fm.value_numeric IS NOT NULL)
                          -- CRITICAL: Exclude cash flow statement items that were incorrectly routed to comprehensive_income
                          AND NOT (
                            co.normalized_label ILIKE '%increase_decrease_in_cash%'
                            OR co.normalized_label ILIKE '%effect_of_exchange_rate_changes_on_cash%'
                          )
                        ON CONFLICT (filing_id, concept_id, period_id) DO UPDATE
                        SET value_numeric = EXCLUDED.value_numeric,
                            unit_measure = EXCLUDED.unit_measure,
                            display_order = EXCLUDED.display_order,
                            is_header = EXCLUDED.is_header,
                            hierarchy_level = EXCLUDED.hierarchy_level,
                            parent_concept_id = EXCLUDED.parent_concept_id
                    """)
                elif statement_type == 'balance_sheet':
                    # Balance sheet: include all main items with side information
                    # CRITICAL: Include headers even if they have no facts
                    insert_query = text(f"""
                        INSERT INTO {table_name} (
                            filing_id, concept_id, period_id, value_numeric, unit_measure,
                            display_order, is_header, hierarchy_level, parent_concept_id, side
                        )
                        SELECT 
                            si.filing_id,
                            si.concept_id,
                            COALESCE(fm.period_id, (SELECT period_id FROM fact_financial_metrics WHERE filing_id = si.filing_id LIMIT 1)),
                            fm.value_numeric,
                            fm.unit_measure,
                            si.display_order,
                            si.is_header,
                            co.hierarchy_level,
                            -- CRITICAL FIX: For main statement items, ensure parent relationships make sense
                            -- If parent comes AFTER this item in display_order, it's wrong - set to NULL
                            CASE 
                                WHEN co.parent_concept_id IS NOT NULL THEN
                                    CASE 
                                        WHEN EXISTS (
                                            SELECT 1 FROM rel_statement_items si2
                                            JOIN dim_concepts co2 ON si2.concept_id = co2.concept_id
                                            WHERE si2.filing_id = si.filing_id
                                              AND si2.statement_type = si.statement_type
                                              AND co2.concept_id = co.parent_concept_id
                                              AND si2.display_order > si.display_order
                                        ) THEN NULL  -- Parent comes after this item - wrong relationship!
                                        ELSE co.parent_concept_id  -- Parent comes before - OK
                                    END
                                ELSE NULL
                            END as parent_concept_id,
                            si.side  -- Include side for balance sheet
                        FROM rel_statement_items si
                        JOIN dim_concepts co ON si.concept_id = co.concept_id
                        LEFT JOIN fact_financial_metrics fm ON 
                            fm.filing_id = si.filing_id 
                            AND fm.concept_id = si.concept_id
                            AND fm.dimension_id IS NULL
                        WHERE si.filing_id = :filing_id
                          AND si.statement_type = :statement_type
                          AND si.is_main_item = TRUE
                          -- Include headers even if they have no facts
                          AND (si.is_header = TRUE OR fm.value_numeric IS NOT NULL)
                        ON CONFLICT (filing_id, concept_id, period_id) DO UPDATE
                        SET value_numeric = EXCLUDED.value_numeric,
                            unit_measure = EXCLUDED.unit_measure,
                            display_order = EXCLUDED.display_order,
                            is_header = EXCLUDED.is_header,
                            hierarchy_level = EXCLUDED.hierarchy_level,
                            parent_concept_id = EXCLUDED.parent_concept_id,
                            side = EXCLUDED.side
                    """)
                elif statement_type == 'cash_flow':
                    # Cash flow: include all main items (no side column)
                    # CRITICAL: Include headers even if they have no facts
                    # UNIVERSAL: Calculate "Cash and cash equivalents at the beginning of the year" from previous year's balance sheet
                    insert_query = text(f"""
                        INSERT INTO {table_name} (
                            filing_id, concept_id, period_id, value_numeric, unit_measure,
                            display_order, is_header, hierarchy_level, parent_concept_id
                        )
                        SELECT 
                            si.filing_id,
                            si.concept_id,
                            COALESCE(fm.period_id, (SELECT period_id FROM fact_financial_metrics WHERE filing_id = si.filing_id LIMIT 1)),
                            -- UNIVERSAL CALCULATION: Beginning-of-year cash = previous year's end-of-year cash
                            -- For "Cash and cash equivalents at the beginning of the year", calculate from previous year's balance sheet
                            CASE 
                                WHEN co.normalized_label = 'cash_and_cash_equivalents_at_the_beginning_of_the_year' THEN
                                    -- UNIVERSAL CALCULATION: Beginning cash = previous year's end cash OR beginning of current year from same filing
                                    -- Strategy 1: Get from previous year's balance sheet (if available)
                                    COALESCE(
                                        (
                                            SELECT fbs.value_numeric
                                            FROM fact_balance_sheet fbs
                                            JOIN dim_concepts co_cash ON fbs.concept_id = co_cash.concept_id
                                            JOIN dim_filings f_prev ON fbs.filing_id = f_prev.filing_id
                                            JOIN dim_time_periods tp_prev ON fbs.period_id = tp_prev.period_id
                                            JOIN dim_filings f_current ON f_current.company_id = f_prev.company_id
                                            WHERE f_current.filing_id = si.filing_id
                                              AND EXTRACT(YEAR FROM f_prev.fiscal_year_end) = EXTRACT(YEAR FROM f_current.fiscal_year_end) - 1
                                              AND (co_cash.normalized_label = 'cash_and_equivalents' 
                                                   OR co_cash.normalized_label = 'balances_with_banks'
                                                   OR co_cash.normalized_label = 'cash_and_cash_equivalents')
                                              AND tp_prev.period_type = 'instant'
                                              AND (tp_prev.end_date = f_prev.fiscal_year_end OR tp_prev.end_date IS NULL)
                                            ORDER BY tp_prev.end_date DESC NULLS LAST, f_prev.fiscal_year_end DESC
                                            LIMIT 1
                                        ),
                                        -- Strategy 2: Get beginning-of-year balance from current filing's balance sheet (if it has multiple periods)
                                        (
                                            SELECT fbs.value_numeric
                                            FROM fact_balance_sheet fbs
                                            JOIN dim_concepts co_cash ON fbs.concept_id = co_cash.concept_id
                                            JOIN dim_time_periods tp ON fbs.period_id = tp.period_id
                                            WHERE fbs.filing_id = si.filing_id
                                              AND (co_cash.normalized_label = 'cash_and_equivalents' 
                                                   OR co_cash.normalized_label = 'balances_with_banks'
                                                   OR co_cash.normalized_label = 'cash_and_cash_equivalents')
                                              AND tp.period_type = 'instant'
                                              AND EXTRACT(YEAR FROM tp.instant_date) = EXTRACT(YEAR FROM (SELECT fiscal_year_end FROM dim_filings WHERE filing_id = si.filing_id))
                                              AND EXTRACT(MONTH FROM tp.instant_date) = 1  -- Beginning of year (January 1)
                                            ORDER BY tp.instant_date ASC
                                            LIMIT 1
                                        )
                                    )
                                ELSE
                                    fm.value_numeric
                            END as value_numeric,
                            COALESCE(fm.unit_measure, 
                                -- For beginning cash, get unit from previous year's balance sheet
                                CASE 
                                    WHEN co.normalized_label = 'cash_and_cash_equivalents_at_the_beginning_of_the_year' THEN
                                        COALESCE(
                                            (
                                                SELECT fbs.unit_measure
                                                FROM fact_balance_sheet fbs
                                                JOIN dim_concepts co_cash ON fbs.concept_id = co_cash.concept_id
                                                JOIN dim_filings f_prev ON fbs.filing_id = f_prev.filing_id
                                                JOIN dim_time_periods tp_prev ON fbs.period_id = tp_prev.period_id
                                                JOIN dim_filings f_current ON f_current.company_id = f_prev.company_id
                                                WHERE f_current.filing_id = si.filing_id
                                                  AND EXTRACT(YEAR FROM f_prev.fiscal_year_end) = EXTRACT(YEAR FROM f_current.fiscal_year_end) - 1
                                                  AND (co_cash.normalized_label = 'cash_and_equivalents' 
                                                       OR co_cash.normalized_label = 'balances_with_banks'
                                                       OR co_cash.normalized_label = 'cash_and_cash_equivalents')
                                                  AND tp_prev.period_type = 'instant'
                                                  AND (tp_prev.end_date = f_prev.fiscal_year_end OR tp_prev.end_date IS NULL)
                                                ORDER BY tp_prev.end_date DESC NULLS LAST, f_prev.fiscal_year_end DESC
                                                LIMIT 1
                                            ),
                                            (
                                                SELECT fbs.unit_measure
                                                FROM fact_balance_sheet fbs
                                                JOIN dim_concepts co_cash ON fbs.concept_id = co_cash.concept_id
                                                JOIN dim_time_periods tp ON fbs.period_id = tp.period_id
                                                WHERE fbs.filing_id = si.filing_id
                                                  AND (co_cash.normalized_label = 'cash_and_equivalents' 
                                                       OR co_cash.normalized_label = 'balances_with_banks'
                                                       OR co_cash.normalized_label = 'cash_and_cash_equivalents')
                                                  AND tp.period_type = 'instant'
                                                  AND EXTRACT(YEAR FROM tp.instant_date) = EXTRACT(YEAR FROM (SELECT fiscal_year_end FROM dim_filings WHERE filing_id = si.filing_id))
                                                  AND EXTRACT(MONTH FROM tp.instant_date) = 1
                                                ORDER BY tp.instant_date ASC
                                                LIMIT 1
                                            )
                                        )
                                    ELSE fm.unit_measure
                                END
                            ) as unit_measure,
                            si.display_order,
                            si.is_header,
                            co.hierarchy_level,
                            -- CRITICAL FIX: For main statement items, ensure parent relationships make sense
                            -- If parent comes AFTER this item in display_order, it's wrong - set to NULL
                            CASE 
                                WHEN co.parent_concept_id IS NOT NULL THEN
                                    CASE 
                                        WHEN EXISTS (
                                            SELECT 1 FROM rel_statement_items si2
                                            JOIN dim_concepts co2 ON si2.concept_id = co2.concept_id
                                            WHERE si2.filing_id = si.filing_id
                                              AND si2.statement_type = si.statement_type
                                              AND co2.concept_id = co.parent_concept_id
                                              AND si2.display_order > si.display_order
                                        ) THEN NULL  -- Parent comes after this item - wrong relationship!
                                        ELSE co.parent_concept_id  -- Parent comes before - OK
                                    END
                                ELSE NULL
                            END as parent_concept_id
                        FROM rel_statement_items si
                        JOIN dim_concepts co ON si.concept_id = co.concept_id
                        LEFT JOIN fact_financial_metrics fm ON 
                            fm.filing_id = si.filing_id 
                            AND fm.concept_id = si.concept_id
                            AND fm.dimension_id IS NULL
                        WHERE si.filing_id = :filing_id
                          AND si.statement_type = :statement_type
                          AND si.is_main_item = TRUE
                          -- Include headers even if they have no facts
                          -- Include beginning cash even if it has no fact (it's calculated)
                          AND (si.is_header = TRUE 
                               OR fm.value_numeric IS NOT NULL 
                               OR co.normalized_label = 'cash_and_cash_equivalents_at_the_beginning_of_the_year')
                        ON CONFLICT (filing_id, concept_id, period_id) DO UPDATE
                        SET value_numeric = EXCLUDED.value_numeric,
                            unit_measure = EXCLUDED.unit_measure,
                            display_order = EXCLUDED.display_order,
                            is_header = EXCLUDED.is_header,
                            hierarchy_level = EXCLUDED.hierarchy_level,
                            parent_concept_id = EXCLUDED.parent_concept_id
                    """)
                elif statement_type == 'equity_statement':
                    # Equity statement: include all main items with equity component breakdown
                    # UNIVERSAL: Extract equity_component from XBRL dimensions (ComponentsOfEquityAxis)
                    # Matrix format: rows = movements, columns = components (Share capital, Treasury shares, Retained earnings, Other reserves, Total)
                    # CRITICAL: Include headers even if they have no facts
                    # UNIVERSAL: Calculate "Balance at the beginning of the year" and "Balance at the end of the year" from balance sheet
                    # UNIVERSAL: Apply sign correction for equity statement items (IFRS/US-GAAP accounting principles)
                    # CRITICAL: For beginning/end balance, create facts for ALL periods in the filing (not just one period)
                    insert_query = text(f"""
                        INSERT INTO {table_name} (
                            filing_id, concept_id, period_id, value_numeric, unit_measure,
                            display_order, is_header, hierarchy_level, parent_concept_id, equity_component
                        )
                        -- Regular items (with consolidated facts) - one fact per period
                        SELECT 
                            si.filing_id,
                            si.concept_id,
                            COALESCE(fci.period_id, fm.period_id) as period_id,
                            -- UNIVERSAL SIGN CORRECTION for equity statement items
                            -- Use fact_comprehensive_income for comprehensive income items (already processed with correct signs)
                            -- Use fact_financial_metrics for other items
                            CASE 
                                -- Comprehensive income items: use from fact_comprehensive_income (already has correct signs)
                                WHEN co.normalized_label = 'other_comprehensive_income' OR co.normalized_label = 'oci_total' THEN
                                    COALESCE(fci.value_numeric, fm.value_numeric)
                                WHEN co.normalized_label = 'total_comprehensive_income' OR co.normalized_label = 'comprehensive_income' THEN
                                    ABS(COALESCE(fci.value_numeric, fm.value_numeric, 0))  -- Always positive
                                -- Dividends paid: negative (outflow from equity)
                                WHEN co.normalized_label = 'dividends_paid' THEN -ABS(COALESCE(fm.value_numeric, 0))
                                -- Purchase of treasury shares: negative (outflow from equity)
                                WHEN co.normalized_label = 'purchase_of_treasury_shares' OR co.normalized_label LIKE '%payments_to_acquire_or_redeem_entitys_shares%' THEN -ABS(COALESCE(fm.value_numeric, 0))
                                -- Transfer of cash flow hedge reserve: negative (outflow from equity)
                                WHEN co.normalized_label LIKE '%amount_removed_from_reserve_of_cash_flow_hedges%' THEN -ABS(COALESCE(fm.value_numeric, 0))
                                -- Reduction of share capital: negative (outflow from equity)
                                WHEN co.normalized_label = 'reduction_of_issued_capital' OR (co.normalized_label LIKE '%reduction%' AND co.normalized_label LIKE '%capital%') THEN -ABS(COALESCE(fm.value_numeric, 0))
                                -- Tax related to transactions with owners: reverse sign (tax benefits are credits)
                                WHEN co.normalized_label LIKE '%tax_on_sharebased%' OR co.normalized_label LIKE '%decrease_increase_through_tax_on_sharebased%' THEN -COALESCE(fm.value_numeric, 0)
                                -- Share-based payments: keep original sign (positive)
                                -- Other items: use consolidated value
                                ELSE COALESCE(fm.value_numeric, 0)
                            END as value_numeric,
                            COALESCE(fci.unit_measure, fm.unit_measure,
                                CASE 
                                    WHEN co.normalized_label = 'balance_at_the_beginning_of_the_year_equity' THEN
                                        COALESCE(
                                            (
                                                SELECT fbs.unit_measure
                                                FROM fact_balance_sheet fbs
                                                JOIN dim_concepts co_equity ON fbs.concept_id = co_equity.concept_id
                                                JOIN dim_filings f_prev ON fbs.filing_id = f_prev.filing_id
                                                JOIN dim_time_periods tp_prev ON fbs.period_id = tp_prev.period_id
                                                JOIN dim_filings f_current ON f_current.company_id = f_prev.company_id
                                                WHERE f_current.filing_id = si.filing_id
                                                  AND EXTRACT(YEAR FROM f_prev.fiscal_year_end) = EXTRACT(YEAR FROM f_current.fiscal_year_end) - 1
                                                  AND (co_equity.normalized_label = 'equity_total' OR co_equity.normalized_label = 'total_equity')
                                                  AND tp_prev.period_type = 'instant'
                                                ORDER BY COALESCE(tp_prev.end_date, tp_prev.instant_date) DESC
                                                LIMIT 1
                                            ),
                                            (
                                                SELECT fbs.unit_measure
                                                FROM fact_balance_sheet fbs
                                                JOIN dim_concepts co_equity ON fbs.concept_id = co_equity.concept_id
                                                JOIN dim_time_periods tp ON fbs.period_id = tp.period_id
                                                WHERE fbs.filing_id = si.filing_id
                                                  AND (co_equity.normalized_label = 'equity_total' OR co_equity.normalized_label = 'total_equity')
                                                  AND tp.period_type = 'instant'
                                                  AND EXTRACT(YEAR FROM tp.instant_date) = EXTRACT(YEAR FROM (SELECT fiscal_year_end FROM dim_filings WHERE filing_id = si.filing_id))
                                                  AND EXTRACT(MONTH FROM tp.instant_date) = 1
                                                ORDER BY tp.instant_date ASC
                                                LIMIT 1
                                            )
                                        )
                                    WHEN co.normalized_label = 'balance_at_the_end_of_the_year_equity' THEN
                                        (
                                            SELECT fbs.unit_measure
                                            FROM fact_balance_sheet fbs
                                            JOIN dim_concepts co_equity ON fbs.concept_id = co_equity.concept_id
                                            JOIN dim_time_periods tp ON fbs.period_id = tp.period_id
                                            WHERE fbs.filing_id = si.filing_id
                                              AND (co_equity.normalized_label = 'equity_total' OR co_equity.normalized_label = 'total_equity')
                                              AND tp.period_type = 'instant'
                                              AND EXTRACT(YEAR FROM tp.instant_date) = EXTRACT(YEAR FROM (SELECT fiscal_year_end FROM dim_filings WHERE filing_id = si.filing_id)) + 1
                                              AND EXTRACT(MONTH FROM tp.instant_date) = 1
                                            ORDER BY tp.instant_date DESC
                                            LIMIT 1
                                        )
                                    ELSE fm.unit_measure
                                END
                            ) as unit_measure,
                            si.display_order,
                            si.is_header,
                            co.hierarchy_level,
                            -- CRITICAL FIX: For main statement items, ensure parent relationships make sense
                            -- If parent comes AFTER this item in display_order, it's wrong - set to NULL
                            CASE 
                                WHEN co.parent_concept_id IS NOT NULL THEN
                                    CASE 
                                        WHEN EXISTS (
                                            SELECT 1 FROM rel_statement_items si2
                                            JOIN dim_concepts co2 ON si2.concept_id = co2.concept_id
                                            WHERE si2.filing_id = si.filing_id
                                              AND si2.statement_type = si.statement_type
                                              AND co2.concept_id = co.parent_concept_id
                                              AND si2.display_order > si.display_order
                                        ) THEN NULL  -- Parent comes after this item - wrong relationship!
                                        ELSE co.parent_concept_id  -- Parent comes before - OK
                                    END
                                ELSE NULL
                            END as parent_concept_id,
                            NULL as equity_component  -- Consolidated facts = totals (no component breakdown)
                        FROM rel_statement_items si
                        JOIN dim_concepts co ON si.concept_id = co.concept_id
                        -- UNIVERSAL FIX: For comprehensive income items, use fact_comprehensive_income (already processed)
                        LEFT JOIN fact_comprehensive_income fci ON 
                            fci.filing_id = si.filing_id 
                            AND fci.concept_id = si.concept_id
                            AND (co.normalized_label = 'other_comprehensive_income' 
                                 OR co.normalized_label = 'oci_total'
                                 OR co.normalized_label = 'total_comprehensive_income'
                                 OR co.normalized_label = 'comprehensive_income')
                        LEFT JOIN fact_financial_metrics fm ON 
                            fm.filing_id = si.filing_id 
                            AND fm.concept_id = si.concept_id
                            AND fm.dimension_id IS NULL
                            AND NOT (co.normalized_label = 'other_comprehensive_income' 
                                     OR co.normalized_label = 'oci_total'
                                     OR co.normalized_label = 'total_comprehensive_income'
                                     OR co.normalized_label = 'comprehensive_income')
                        WHERE si.filing_id = :filing_id
                          AND si.statement_type = :statement_type
                          AND si.is_main_item = TRUE
                          -- Only include items with consolidated facts (exclude headers and beginning/end balance)
                          AND COALESCE(fci.value_numeric, fm.value_numeric) IS NOT NULL 
                          AND COALESCE(fci.period_id, fm.period_id) IS NOT NULL
                          AND ABS(COALESCE(fci.value_numeric, fm.value_numeric)) > 0.001  -- Only non-zero consolidated facts
                          AND co.normalized_label NOT IN ('balance_at_the_beginning_of_the_year_equity', 'balance_at_the_end_of_the_year_equity')
                          -- CRITICAL: Exclude concepts that have dimension facts with ComponentsOfEquityAxis
                          -- (those will be handled in the second UNION ALL with component breakdowns)
                          AND NOT EXISTS (
                              SELECT 1 FROM fact_financial_metrics fm_dim_check
                              JOIN dim_xbrl_dimensions d_check ON fm_dim_check.dimension_id = d_check.dimension_id
                              WHERE fm_dim_check.filing_id = si.filing_id
                                AND fm_dim_check.concept_id = si.concept_id
                                AND fm_dim_check.dimension_id IS NOT NULL
                                AND d_check.dimension_json ? 'ComponentsOfEquityAxis'
                                AND ABS(fm_dim_check.value_numeric) > 0.001
                          )
                        
                        UNION ALL
                        
                        -- UNIVERSAL: Equity component breakdown from dimension facts
                        -- Extract equity_component from ComponentsOfEquityAxis dimension
                        -- CRITICAL: Aggregate by (filing_id, concept_id, period_id, equity_component) to prevent duplicates
                        SELECT 
                            si.filing_id,
                            si.concept_id,
                            MAX(COALESCE(fci_dim.period_id, fm_dim.period_id)) as period_id,
                            -- UNIVERSAL SIGN CORRECTION for equity statement items (by component)
                            -- Use fact_comprehensive_income for comprehensive income items (already processed)
                            -- Sum values for same (concept, period, component) combination
                            SUM(
                                CASE 
                                    -- Comprehensive income items: use from fact_comprehensive_income (already has correct signs)
                                    WHEN co.normalized_label = 'other_comprehensive_income' OR co.normalized_label = 'oci_total' THEN
                                        COALESCE(fci_dim.value_numeric, fm_dim.value_numeric)
                                    WHEN co.normalized_label = 'total_comprehensive_income' OR co.normalized_label = 'comprehensive_income' THEN
                                        ABS(COALESCE(fci_dim.value_numeric, fm_dim.value_numeric, 0))  -- Always positive
                                    -- Dividends paid: negative (outflow from equity)
                                    WHEN co.normalized_label = 'dividends_paid' THEN -ABS(COALESCE(fm_dim.value_numeric, 0))
                                    -- Purchase of treasury shares: negative (outflow from equity)
                                    WHEN co.normalized_label = 'purchase_of_treasury_shares' OR co.normalized_label LIKE '%payments_to_acquire_or_redeem_entitys_shares%' THEN -ABS(COALESCE(fm_dim.value_numeric, 0))
                                    -- Transfer of cash flow hedge reserve: negative (outflow from equity)
                                    WHEN co.normalized_label LIKE '%amount_removed_from_reserve_of_cash_flow_hedges%' THEN -ABS(COALESCE(fm_dim.value_numeric, 0))
                                    -- Reduction of share capital: component-specific sign correction
                                    -- For share_capital: negative (outflow from equity)
                                    -- For treasury_shares: positive (reducing negative balance increases equity)
                                    WHEN co.normalized_label = 'reduction_of_issued_capital' OR (co.normalized_label LIKE '%reduction%' AND co.normalized_label LIKE '%capital%') THEN
                                        CASE 
                                            WHEN d.dimension_json->'ComponentsOfEquityAxis'->>'member' = 'TreasurySharesMember' THEN
                                                ABS(COALESCE(fm_dim.value_numeric, 0))  -- Positive for treasury shares (reducing negative balance)
                                            ELSE
                                                -ABS(COALESCE(fm_dim.value_numeric, 0))  -- Negative for other components (outflow from equity)
                                        END
                                    -- Tax related to transactions with owners: reverse sign (tax benefits are credits)
                                    WHEN co.normalized_label LIKE '%tax_on_sharebased%' OR co.normalized_label LIKE '%decrease_increase_through_tax_on_sharebased%' THEN -COALESCE(fm_dim.value_numeric, 0)
                                    -- Share-based payments: keep original sign (positive)
                                    -- Other items: use dimension value
                                    ELSE COALESCE(fm_dim.value_numeric, 0)
                                END
                            ) as value_numeric,
                            COALESCE(MAX(fci_dim.unit_measure), MAX(fm_dim.unit_measure)) as unit_measure,
                            MAX(si.display_order) as display_order,
                            BOOL_OR(si.is_header) as is_header,
                            MAX(co.hierarchy_level) as hierarchy_level,
                            -- CRITICAL FIX: For main statement items, ensure parent relationships make sense
                            MAX(
                                CASE 
                                    WHEN co.parent_concept_id IS NOT NULL THEN
                                        CASE 
                                            WHEN EXISTS (
                                                SELECT 1 FROM rel_statement_items si2
                                                JOIN dim_concepts co2 ON si2.concept_id = co2.concept_id
                                                WHERE si2.filing_id = si.filing_id
                                                  AND si2.statement_type = si.statement_type
                                                  AND co2.concept_id = co.parent_concept_id
                                                  AND si2.display_order > si.display_order
                                            ) THEN NULL
                                            ELSE co.parent_concept_id
                                        END
                                    ELSE NULL
                                END
                            ) as parent_concept_id,
                            -- UNIVERSAL: Extract equity_component from ComponentsOfEquityAxis dimension
                            CASE 
                                WHEN MAX(d.dimension_json->'ComponentsOfEquityAxis'->>'member') = 'IssuedCapitalMember' THEN 'share_capital'
                                WHEN MAX(d.dimension_json->'ComponentsOfEquityAxis'->>'member') = 'TreasurySharesMember' THEN 'treasury_shares'
                                WHEN MAX(d.dimension_json->'ComponentsOfEquityAxis'->>'member') = 'RetainedEarningsMember' THEN 'retained_earnings'
                                WHEN MAX(d.dimension_json->'ComponentsOfEquityAxis'->>'member') = 'OtherReservesMember' THEN 'other_reserves'
                                ELSE NULL
                            END as equity_component
                        FROM rel_statement_items si
                        JOIN dim_concepts co ON si.concept_id = co.concept_id
                        -- UNIVERSAL FIX: For comprehensive income items, use fact_comprehensive_income (already processed)
                        -- Note: fact_comprehensive_income is consolidated (no dimensions), so we use it for the concept but not by component
                        LEFT JOIN fact_comprehensive_income fci_dim ON 
                            fci_dim.filing_id = si.filing_id 
                            AND fci_dim.concept_id = si.concept_id
                            AND (co.normalized_label = 'other_comprehensive_income' 
                                 OR co.normalized_label = 'oci_total'
                                 OR co.normalized_label = 'total_comprehensive_income'
                                 OR co.normalized_label = 'comprehensive_income')
                        JOIN fact_financial_metrics fm_dim ON 
                            fm_dim.filing_id = si.filing_id 
                            AND fm_dim.concept_id = si.concept_id
                            AND fm_dim.dimension_id IS NOT NULL
                            AND NOT (co.normalized_label = 'other_comprehensive_income' 
                                     OR co.normalized_label = 'oci_total'
                                     OR co.normalized_label = 'total_comprehensive_income'
                                     OR co.normalized_label = 'comprehensive_income')
                        JOIN dim_xbrl_dimensions d ON fm_dim.dimension_id = d.dimension_id
                        WHERE si.filing_id = :filing_id
                          AND si.statement_type = :statement_type
                          AND si.is_main_item = TRUE
                          -- Only include dimension facts with ComponentsOfEquityAxis
                          AND d.dimension_json ? 'ComponentsOfEquityAxis'
                          AND ABS(COALESCE(fci_dim.value_numeric, fm_dim.value_numeric)) > 0.001
                          AND co.normalized_label NOT IN ('balance_at_the_beginning_of_the_year_equity', 'balance_at_the_end_of_the_year_equity')
                        GROUP BY si.filing_id, si.concept_id, fm_dim.period_id,
                            -- Group by equity_component (extracted from dimension)
                            CASE 
                                WHEN d.dimension_json->'ComponentsOfEquityAxis'->>'member' = 'IssuedCapitalMember' THEN 'share_capital'
                                WHEN d.dimension_json->'ComponentsOfEquityAxis'->>'member' = 'TreasurySharesMember' THEN 'treasury_shares'
                                WHEN d.dimension_json->'ComponentsOfEquityAxis'->>'member' = 'RetainedEarningsMember' THEN 'retained_earnings'
                                WHEN d.dimension_json->'ComponentsOfEquityAxis'->>'member' = 'OtherReservesMember' THEN 'other_reserves'
                                ELSE NULL
                            END
                        
                        UNION ALL
                        
                        -- UNIVERSAL FIX: Items where consolidated is 0 but dimension facts exist (e.g., reduction_of_issued_capital)
                        -- For reduction of capital, component-specific sign correction
                        SELECT 
                            si.filing_id,
                            si.concept_id,
                            fm_dim.period_id,
                            -- Use dimension value with correct sign (component-specific)
                            -- For reduction_of_issued_capital: treasury shares = positive, others = negative
                            CASE 
                                WHEN co.normalized_label = 'reduction_of_issued_capital' OR (co.normalized_label LIKE '%reduction%' AND co.normalized_label LIKE '%capital%') THEN
                                    -- Component-specific sign correction
                                    CASE 
                                        -- For treasury shares: positive (reducing negative balance increases equity)
                                        -- Check if ANY dimension in this group is TreasurySharesMember
                                        WHEN EXISTS (
                                            SELECT 1 FROM fact_financial_metrics fm_check
                                            JOIN dim_xbrl_dimensions d_check ON fm_check.dimension_id = d_check.dimension_id
                                            WHERE fm_check.filing_id = si.filing_id
                                              AND fm_check.concept_id = si.concept_id
                                              AND fm_check.period_id = fm_dim.period_id
                                              AND d_check.dimension_json->'ComponentsOfEquityAxis'->>'member' = 'TreasurySharesMember'
                                              AND ABS(fm_check.value_numeric) > 0.001
                                        ) THEN
                                            ABS(MAX(fm_dim.value_numeric))  -- Positive for treasury shares
                                        -- For other components: negative (outflow from equity)
                                        ELSE
                                            CASE 
                                                WHEN MIN(fm_dim.value_numeric) < 0 THEN MIN(fm_dim.value_numeric)
                                                ELSE -ABS(MAX(fm_dim.value_numeric))
                                            END
                                    END
                                ELSE
                                    -- For other items, sum all dimensions
                                    SUM(fm_dim.value_numeric)
                            END as value_numeric,
                            MAX(fm_dim.unit_measure) as unit_measure,
                            si.display_order,
                            si.is_header,
                            co.hierarchy_level,
                            -- CRITICAL FIX: For main statement items, ensure parent relationships make sense
                            CASE 
                                WHEN co.parent_concept_id IS NOT NULL THEN
                                    CASE 
                                        WHEN EXISTS (
                                            SELECT 1 FROM rel_statement_items si2
                                            JOIN dim_concepts co2 ON si2.concept_id = co2.concept_id
                                            WHERE si2.filing_id = si.filing_id
                                              AND si2.statement_type = si.statement_type
                                              AND co2.concept_id = co.parent_concept_id
                                              AND si2.display_order > si.display_order
                                        ) THEN NULL
                                        ELSE co.parent_concept_id
                                    END
                                ELSE NULL
                            END as parent_concept_id,
                            NULL as equity_component  -- Aggregated dimension facts = totals
                        FROM rel_statement_items si
                        JOIN dim_concepts co ON si.concept_id = co.concept_id
                        JOIN fact_financial_metrics fm_dim ON 
                            fm_dim.filing_id = si.filing_id 
                            AND fm_dim.concept_id = si.concept_id
                            AND fm_dim.dimension_id IS NOT NULL
                        LEFT JOIN fact_financial_metrics fm_cons ON 
                            fm_cons.filing_id = si.filing_id 
                            AND fm_cons.concept_id = si.concept_id
                            AND fm_cons.dimension_id IS NULL
                            AND fm_cons.period_id = fm_dim.period_id
                        WHERE si.filing_id = :filing_id
                          AND si.statement_type = :statement_type
                          AND si.is_main_item = TRUE
                          -- Only include if consolidated is 0 or NULL but dimension facts exist
                          -- AND dimension does NOT have ComponentsOfEquityAxis (already handled above)
                          AND (fm_cons.value_numeric IS NULL OR ABS(fm_cons.value_numeric) < 0.001)
                          AND ABS(fm_dim.value_numeric) > 0.001
                          AND co.normalized_label NOT IN ('balance_at_the_beginning_of_the_year_equity', 'balance_at_the_end_of_the_year_equity')
                          -- Check if ANY dimension in this group has ComponentsOfEquityAxis (using aggregated check)
                          AND NOT EXISTS (
                              SELECT 1 FROM fact_financial_metrics fm_check
                              JOIN dim_xbrl_dimensions d2 ON fm_check.dimension_id = d2.dimension_id
                              WHERE fm_check.filing_id = si.filing_id
                                AND fm_check.concept_id = si.concept_id
                                AND fm_check.period_id = fm_dim.period_id
                                AND d2.dimension_json ? 'ComponentsOfEquityAxis'
                                AND ABS(fm_check.value_numeric) > 0.001
                          )
                        GROUP BY si.filing_id, si.concept_id, fm_dim.period_id, si.display_order, si.is_header, co.hierarchy_level, co.parent_concept_id, si.statement_type, co.normalized_label
                        
                        UNION ALL
                        
                        -- Headers: create facts for all periods (with NULL values)
                        SELECT 
                            si.filing_id,
                            si.concept_id,
                            tp.period_id,
                            NULL as value_numeric,
                            NULL as unit_measure,
                            si.display_order,
                            si.is_header,
                            co.hierarchy_level,
                            co.parent_concept_id,
                            NULL as equity_component  -- Headers have no component breakdown
                        FROM rel_statement_items si
                        JOIN dim_concepts co ON si.concept_id = co.concept_id
                        CROSS JOIN (
                            SELECT DISTINCT tp.period_id
                            FROM fact_financial_metrics fm_periods
                            JOIN dim_time_periods tp ON fm_periods.period_id = tp.period_id
                            WHERE fm_periods.filing_id = :filing_id
                              AND tp.period_type = 'duration'
                        ) tp
                        WHERE si.filing_id = :filing_id
                          AND si.statement_type = :statement_type
                          AND si.is_main_item = TRUE
                          AND si.is_header = TRUE
                        
                        UNION ALL
                        
                        -- Beginning/end balance: create facts for ALL periods with component breakdowns
                        -- UNIVERSAL: Extract component breakdowns from balance sheet (balance sheet also has ComponentsOfEquityAxis)
                        -- CRITICAL FIX: Use DISTINCT ON to prevent duplicate rows, and filter to only annual periods
                        -- Wrap in subquery to allow DISTINCT ON with ORDER BY
                        SELECT * FROM (
                            SELECT DISTINCT ON (si.filing_id, si.concept_id, tp.period_id, comp.equity_component)
                            si.filing_id,
                            si.concept_id,
                            tp.period_id,
                            -- UNIVERSAL CALCULATION: Beginning balance = previous year's end balance, End balance = current year's end balance
                            -- Get component-specific values from balance sheet
                            CASE 
                                WHEN co.normalized_label = 'balance_at_the_beginning_of_the_year_equity' THEN
                                    -- Get previous year's end balance from balance sheet (by component)
                                    -- UNIVERSAL: Get from fact_financial_metrics with ComponentsOfEquityAxis dimension
                                    COALESCE(
                                        -- Strategy 1: Get from previous year's filing (most accurate) - with component breakdown
                                        (
                                            SELECT fm.value_numeric
                                            FROM fact_financial_metrics fm
                                            JOIN dim_xbrl_dimensions d ON fm.dimension_id = d.dimension_id
                                            JOIN dim_concepts co_equity ON fm.concept_id = co_equity.concept_id
                                            JOIN dim_filings f_prev ON fm.filing_id = f_prev.filing_id
                                            JOIN dim_time_periods tp_prev ON fm.period_id = tp_prev.period_id
                                            JOIN dim_filings f_current ON f_current.company_id = f_prev.company_id
                                            WHERE f_current.filing_id = si.filing_id
                                              AND EXTRACT(YEAR FROM f_prev.fiscal_year_end) = EXTRACT(YEAR FROM f_current.fiscal_year_end) - 1
                                              AND (
                                                  (comp.equity_component = 'share_capital' AND d.dimension_json->'ComponentsOfEquityAxis'->>'member' = 'IssuedCapitalMember' AND (co_equity.normalized_label = 'share_capital' OR co_equity.normalized_label = 'equity_total'))
                                                  OR (comp.equity_component = 'treasury_shares' AND d.dimension_json->'ComponentsOfEquityAxis'->>'member' = 'TreasurySharesMember' AND (co_equity.normalized_label = 'treasury_shares' OR co_equity.normalized_label = 'equity_total'))
                                                  OR (comp.equity_component = 'retained_earnings' AND d.dimension_json->'ComponentsOfEquityAxis'->>'member' = 'RetainedEarningsMember' AND (co_equity.normalized_label = 'retained_earnings' OR co_equity.normalized_label = 'equity_total'))
                                                  OR (comp.equity_component = 'other_reserves' AND d.dimension_json->'ComponentsOfEquityAxis'->>'member' = 'OtherReservesMember' AND (co_equity.normalized_label LIKE '%other_reserve%' OR co_equity.normalized_label = 'equity_total'))
                                                  OR (comp.equity_component IS NULL AND fm.dimension_id IS NULL AND (co_equity.normalized_label = 'equity_total' OR co_equity.normalized_label = 'total_equity'))
                                              )
                                              AND tp_prev.period_type = 'instant'
                                              -- CRITICAL FIX: For beginning balance, use the START of the duration period
                                              -- (which represents the end of the previous year)
                                              -- For period 2024-01-01 to 2025-01-01, we need 2024-01-01 (end of 2023)
                                              AND tp_prev.instant_date = 
                                                  CASE 
                                                      WHEN tp.period_type = 'duration' AND tp.start_date IS NOT NULL THEN
                                                          tp.start_date  -- Use start date of duration period (represents end of previous year)
                                                      WHEN tp.period_type = 'duration' AND tp.end_date IS NOT NULL THEN
                                                          tp.end_date  -- Fallback: use end date
                                                      ELSE
                                                          COALESCE(tp.end_date, tp.instant_date)  -- Fallback: use instant date
                                                  END
                                            ORDER BY COALESCE(tp_prev.end_date, tp_prev.instant_date) DESC
                                            LIMIT 1
                                        ),
                                        -- Strategy 2: Get beginning-of-year balance from current filing (with component breakdown)
                                        (
                                            SELECT fm.value_numeric
                                            FROM fact_financial_metrics fm
                                            LEFT JOIN dim_xbrl_dimensions d ON fm.dimension_id = d.dimension_id
                                            JOIN dim_concepts co_equity ON fm.concept_id = co_equity.concept_id
                                            JOIN dim_time_periods tp_bs ON fm.period_id = tp_bs.period_id
                                            WHERE fm.filing_id = si.filing_id
                                              AND (
                                                  (comp.equity_component = 'share_capital' AND d.dimension_json->'ComponentsOfEquityAxis'->>'member' = 'IssuedCapitalMember' AND (co_equity.normalized_label = 'share_capital' OR co_equity.normalized_label = 'equity_total'))
                                                  OR (comp.equity_component = 'treasury_shares' AND d.dimension_json->'ComponentsOfEquityAxis'->>'member' = 'TreasurySharesMember' AND (co_equity.normalized_label = 'treasury_shares' OR co_equity.normalized_label = 'equity_total'))
                                                  OR (comp.equity_component = 'retained_earnings' AND d.dimension_json->'ComponentsOfEquityAxis'->>'member' = 'RetainedEarningsMember' AND (co_equity.normalized_label = 'retained_earnings' OR co_equity.normalized_label = 'equity_total'))
                                                  OR (comp.equity_component = 'other_reserves' AND d.dimension_json->'ComponentsOfEquityAxis'->>'member' = 'OtherReservesMember' AND (co_equity.normalized_label LIKE '%other_reserve%' OR co_equity.normalized_label = 'equity_total'))
                                                  OR (comp.equity_component IS NULL AND fm.dimension_id IS NULL AND (co_equity.normalized_label = 'equity_total' OR co_equity.normalized_label = 'total_equity'))
                                              )
                                              AND tp_bs.period_type = 'instant'
                                              -- CRITICAL FIX: For beginning balance, use the START of the duration period
                                              -- (which represents the end of the previous year)
                                              -- For period 2024-01-01 to 2025-01-01, we need 2024-01-01 (end of 2023)
                                              AND tp_bs.instant_date = 
                                                  CASE 
                                                      WHEN tp.period_type = 'duration' AND tp.start_date IS NOT NULL THEN
                                                          tp.start_date  -- Use start date of duration period (represents end of previous year)
                                                      WHEN tp.period_type = 'duration' AND tp.end_date IS NOT NULL THEN
                                                          tp.end_date  -- Fallback: use end date
                                                      ELSE
                                                          COALESCE(tp.end_date, tp.instant_date)  -- Fallback: use instant date
                                                  END
                                            ORDER BY tp_bs.instant_date ASC
                                            LIMIT 1
                                        )
                                    )
                                WHEN co.normalized_label = 'balance_at_the_end_of_the_year_equity' THEN
                                    -- Get current year's end balance from balance sheet (by component)
                                    -- UNIVERSAL: Get from fact_financial_metrics with ComponentsOfEquityAxis dimension
                                    (
                                        SELECT fm.value_numeric
                                        FROM fact_financial_metrics fm
                                        LEFT JOIN dim_xbrl_dimensions d ON fm.dimension_id = d.dimension_id
                                        JOIN dim_concepts co_equity ON fm.concept_id = co_equity.concept_id
                                        JOIN dim_time_periods tp_bs ON fm.period_id = tp_bs.period_id
                                        WHERE fm.filing_id = si.filing_id
                                          AND (
                                              (comp.equity_component = 'share_capital' AND d.dimension_json->'ComponentsOfEquityAxis'->>'member' = 'IssuedCapitalMember' AND (co_equity.normalized_label = 'share_capital' OR co_equity.normalized_label = 'equity_total'))
                                              OR (comp.equity_component = 'treasury_shares' AND d.dimension_json->'ComponentsOfEquityAxis'->>'member' = 'TreasurySharesMember' AND (co_equity.normalized_label = 'treasury_shares' OR co_equity.normalized_label = 'equity_total'))
                                              OR (comp.equity_component = 'retained_earnings' AND d.dimension_json->'ComponentsOfEquityAxis'->>'member' = 'RetainedEarningsMember' AND (co_equity.normalized_label = 'retained_earnings' OR co_equity.normalized_label = 'equity_total'))
                                              OR (comp.equity_component = 'other_reserves' AND d.dimension_json->'ComponentsOfEquityAxis'->>'member' = 'OtherReservesMember' AND (co_equity.normalized_label LIKE '%other_reserve%' OR co_equity.normalized_label = 'equity_total'))
                                              OR (comp.equity_component IS NULL AND fm.dimension_id IS NULL AND (co_equity.normalized_label = 'equity_total' OR co_equity.normalized_label = 'total_equity'))
                                          )
                                          AND tp_bs.period_type = 'instant'
                                          -- CRITICAL FIX: For ending balance, use the END of the duration period
                                          -- (which represents the end of the current year)
                                          -- For period 2024-01-01 to 2025-01-01, we need 2025-01-01 (end of 2024)
                                          AND tp_bs.instant_date = 
                                              CASE 
                                                  WHEN tp.period_type = 'duration' AND tp.end_date IS NOT NULL THEN
                                                      tp.end_date  -- Use end date of duration period (represents end of current year)
                                                  ELSE
                                                      COALESCE(tp.end_date, tp.instant_date)  -- Fallback: use instant date
                                              END
                                        ORDER BY tp_bs.instant_date DESC
                                        LIMIT 1
                                    )
                            END as value_numeric,
                            -- Get unit from balance sheet
                            COALESCE(
                                (
                                    SELECT fbs.unit_measure
                                    FROM fact_balance_sheet fbs
                                    JOIN dim_concepts co_equity ON fbs.concept_id = co_equity.concept_id
                                    WHERE fbs.filing_id = si.filing_id
                                      AND (co_equity.normalized_label = 'equity_total' OR co_equity.normalized_label = 'total_equity')
                                    LIMIT 1
                                ),
                                'DKK'
                            ) as unit_measure,
                            si.display_order,
                            si.is_header,
                            co.hierarchy_level,
                            co.parent_concept_id,
                            comp.equity_component  -- Component breakdown: 'share_capital', 'treasury_shares', 'retained_earnings', 'other_reserves', NULL for totals
                        FROM rel_statement_items si
                        JOIN dim_concepts co ON si.concept_id = co.concept_id
                        -- CROSS JOIN with annual periods only (filter out quarterly and very short periods) AND all equity components (including NULL for totals)
                        -- CRITICAL FIX: Filter to only annual periods to prevent duplicates
                        CROSS JOIN (
                            SELECT DISTINCT tp.period_id, tp.start_date, tp.end_date, tp.instant_date, tp.period_type, tp.fiscal_year, tp.fiscal_quarter
                            FROM fact_financial_metrics fm_periods
                            JOIN dim_time_periods tp ON fm_periods.period_id = tp.period_id
                            WHERE fm_periods.filing_id = :filing_id
                              AND tp.period_type = 'duration'
                              -- CRITICAL: Only use annual periods (not quarterly or very short periods)
                              -- Filter out quarterly periods (fiscal_quarter IS NULL or 0) and very short periods (< 30 days)
                              AND (tp.fiscal_quarter IS NULL OR tp.fiscal_quarter = 0)
                              AND (
                                  tp.end_date IS NULL 
                                  OR tp.start_date IS NULL 
                                  OR (tp.end_date - tp.start_date) >= 30  -- At least 30 days (filters out 1-day periods)
                              )
                        ) tp
                        CROSS JOIN (
                            SELECT equity_component FROM (VALUES 
                                ('share_capital'::VARCHAR(50)),
                                ('treasury_shares'::VARCHAR(50)),
                                ('retained_earnings'::VARCHAR(50)),
                                ('other_reserves'::VARCHAR(50)),
                                (NULL::VARCHAR(50))
                            ) AS comp(equity_component)
                        ) comp
                            WHERE si.filing_id = :filing_id
                              AND si.statement_type = :statement_type
                              AND si.is_main_item = TRUE
                              -- Only create beginning/end balance facts
                              AND co.normalized_label IN ('balance_at_the_beginning_of_the_year_equity', 'balance_at_the_end_of_the_year_equity')
                            -- CRITICAL: Order by period_id to ensure DISTINCT ON selects the correct row
                            ORDER BY si.filing_id, si.concept_id, tp.period_id, comp.equity_component, tp.fiscal_year DESC, tp.fiscal_quarter NULLS LAST
                        ) AS beginning_end_balance
                        ON CONFLICT (filing_id, concept_id, period_id, equity_component) DO UPDATE
                        SET value_numeric = EXCLUDED.value_numeric,
                            unit_measure = EXCLUDED.unit_measure,
                            display_order = EXCLUDED.display_order,
                            is_header = EXCLUDED.is_header,
                            hierarchy_level = EXCLUDED.hierarchy_level,
                            parent_concept_id = EXCLUDED.parent_concept_id,
                            equity_component = EXCLUDED.equity_component
                    """)
                
                result = conn.execute(insert_query, {
                    "filing_id": current_filing_id,
                    "statement_type": statement_type
                })
                rows_inserted = result.rowcount
                
                if rows_inserted > 0:
                    print(f"      ✅ Populated {rows_inserted} facts for {statement_type}")
                else:
                    print(f"      ⚠️  No facts found for {statement_type}")


if __name__ == "__main__":
    # Example usage:
    # To populate for a specific filing:
    # populate_statement_facts(filing_id=1)
    # To populate for all filings:
    populate_statement_facts()

