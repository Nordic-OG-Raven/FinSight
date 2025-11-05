"""
Calculate Missing Universal Metric Totals from Components

For metrics where companies report components but not the total (e.g., noncurrent_liabilities),
this module calculates the total by summing all related components using TAXONOMY-DEFINED
calculation relationships.

This is STANDARD and AUDITABLE - uses official XBRL calculation linkbases.
Integrated into the ETL pipeline to ensure calculated totals are available when companies
don't explicitly report them (common in US-GAAP for liability breakdowns).
"""

import sys
from pathlib import Path
import logging
from typing import Dict, List, Tuple

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from config import DATABASE_URI

logger = logging.getLogger(__name__)

# Metrics that may need calculated totals and their component patterns
METRIC_COMPONENT_PATTERNS = {
    'noncurrent_liabilities': [
        '%noncurrent%liabilit%',
        '%liabilit%noncurrent%',
        '%long%term%liabilit%',
    ],
    # Add more patterns as needed
}


def _calculate_revenue_from_components(engine) -> int:
    """
    Calculate revenue from components (e.g., SNY: RevenueFromSaleOfGoods + OtherRevenue).
    Returns count of calculated totals.
    """
    logger.info("Calculating revenue from components...")
    
    with engine.connect() as conn:
        # Find companies missing revenue but have revenue components
        missing_query = text("""
            SELECT DISTINCT c.ticker, c.company_id
            FROM dim_companies c
            WHERE NOT EXISTS (
                SELECT 1
                FROM fact_financial_metrics f
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                WHERE f.company_id = c.company_id
                  AND f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND dc.normalized_label IN ('revenue', 'revenue_from_contracts')
            )
            AND c.company_id > 0;
        """)
        
        missing_companies = [(row[0], row[1]) for row in conn.execute(missing_query)]
        
        if not missing_companies:
            return 0
        
        # For each company, sum revenue components
        calculated_count = 0
        
        for ticker, company_id in missing_companies:
            # Check if company has revenue_from_sale_of_goods + other_revenue (SNY pattern)
            sum_query = text("""
                SELECT 
                    f.period_id,
                    SUM(f.value_numeric) as total_revenue,
                    COUNT(DISTINCT f.concept_id) as component_count
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                WHERE c.ticker = :ticker
                  AND f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND dc.normalized_label IN ('revenue_from_sale_of_goods', 'other_revenue', 'revenue_from_contracts', 'revenue_from_collaborative_arrangements')
                GROUP BY f.period_id
                HAVING COUNT(DISTINCT f.concept_id) >= 2  -- At least 2 components
                ORDER BY f.period_id;
            """)
            
            sum_result = conn.execute(sum_query, {'ticker': ticker})
            periods = [(row[0], row[1], row[2]) for row in sum_result]
            
            if not periods:
                continue
            
            # Get or create revenue concept
            revenue_concept_query = text("""
                SELECT concept_id FROM dim_concepts
                WHERE normalized_label = 'revenue'
                LIMIT 1;
            """)
            
            revenue_concept_result = conn.execute(revenue_concept_query).fetchone()
            if not revenue_concept_result:
                continue
            
            revenue_concept_id = revenue_concept_result[0]
            
            # Create calculated totals
            for period_id, total_value, component_count in periods:
                filing_query = text("""
                    SELECT DISTINCT f.filing_id
                    FROM fact_financial_metrics f
                    WHERE f.company_id = :company_id
                      AND f.period_id = :period_id
                    LIMIT 1;
                """)
                
                filing_result = conn.execute(filing_query, {
                    'company_id': company_id,
                    'period_id': period_id
                }).fetchone()
                
                if filing_result:
                    if create_calculated_total_fact(engine, company_id, filing_result[0], period_id, 
                                                    revenue_concept_id, total_value):
                        calculated_count += 1
                        logger.info(f"  ✅ {ticker}: Created revenue total for period {period_id}: {total_value:,.0f} ({component_count} components)")
        
        return calculated_count


def _calculate_current_liabilities_from_components(engine) -> int:
    """
    Calculate current_liabilities from components (e.g., SNY IFRS).
    Returns count of calculated totals.
    """
    logger.info("Calculating current_liabilities from components...")
    
    with engine.connect() as conn:
        missing_query = text("""
            SELECT DISTINCT c.ticker, c.company_id
            FROM dim_companies c
            WHERE NOT EXISTS (
                SELECT 1
                FROM fact_financial_metrics f
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                WHERE f.company_id = c.company_id
                  AND f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND dc.normalized_label = 'current_liabilities'
            )
            AND c.company_id > 0;
        """)
        
        missing_companies = [(row[0], row[1]) for row in conn.execute(missing_query)]
        
        if not missing_companies:
            return 0
        
        calculated_count = 0
        
        for ticker, company_id in missing_companies:
            # Sum all current liability components
            sum_query = text("""
                SELECT 
                    f.period_id,
                    SUM(f.value_numeric) as total_current,
                    COUNT(DISTINCT f.concept_id) as component_count
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                WHERE c.ticker = :ticker
                  AND f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND (
                      (dc.concept_name ILIKE '%Current%' AND dc.concept_name ILIKE '%Liabilit%')
                      OR (dc.normalized_label LIKE '%current%' AND dc.normalized_label LIKE '%liabilit%')
                  )
                  AND dc.normalized_label != 'current_liabilities'
                GROUP BY f.period_id
                HAVING COUNT(DISTINCT f.concept_id) >= 3  -- At least 3 components (to avoid false positives)
                ORDER BY f.period_id;
            """)
            
            sum_result = conn.execute(sum_query, {'ticker': ticker})
            periods = [(row[0], row[1], row[2]) for row in sum_result]
            
            if not periods:
                continue
            
            # Get or create current_liabilities concept
            concept_query = text("""
                SELECT concept_id FROM dim_concepts
                WHERE normalized_label = 'current_liabilities'
                LIMIT 1;
            """)
            
            concept_result = conn.execute(concept_query).fetchone()
            if not concept_result:
                continue
            
            concept_id = concept_result[0]
            
            for period_id, total_value, component_count in periods:
                filing_query = text("""
                    SELECT DISTINCT f.filing_id
                    FROM fact_financial_metrics f
                    WHERE f.company_id = :company_id
                      AND f.period_id = :period_id
                    LIMIT 1;
                """)
                
                filing_result = conn.execute(filing_query, {
                    'company_id': company_id,
                    'period_id': period_id
                }).fetchone()
                
                if filing_result:
                    if create_calculated_total_fact(engine, company_id, filing_result[0], period_id, 
                                                    concept_id, total_value):
                        calculated_count += 1
                        logger.info(f"  ✅ {ticker}: Created current_liabilities total: {total_value:,.0f} ({component_count} components)")
        
        return calculated_count


def _calculate_bank_current_liabilities(engine) -> int:
    """
    Calculate current_liabilities for banks from deposit liabilities.
    Banks report deposit liabilities as components of current_liabilities.
    Returns count of calculated totals.
    """
    logger.info("Calculating current_liabilities for banks (from deposit liabilities)...")
    
    with engine.connect() as conn:
        missing_query = text("""
            SELECT DISTINCT c.ticker, c.company_id
            FROM dim_companies c
            WHERE NOT EXISTS (
                SELECT 1
                FROM fact_financial_metrics f
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                WHERE f.company_id = c.company_id
                  AND f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND dc.normalized_label IN ('current_liabilities', 'liabilities_current', 'current_liabilities_ifrs_variant')
            )
            AND c.company_id > 0;
        """)
        
        missing_companies = [(row[0], row[1]) for row in conn.execute(missing_query)]
        
        if not missing_companies:
            return 0
        
        calculated_count = 0
        
        for ticker, company_id in missing_companies:
            # For banks: sum deposit liabilities (components of current_liabilities)
            # Check if company has deposit liabilities (indicates it's a bank)
            deposit_query = text("""
                SELECT 
                    t.period_id,
                    SUM(f.value_numeric) as total_deposits
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                JOIN dim_time_periods t ON f.period_id = t.period_id
                WHERE c.ticker = :ticker
                  AND f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND (
                      dc.normalized_label LIKE '%deposit%liabilit%'
                      OR dc.normalized_label LIKE '%interest_bearing_deposit%'
                      OR dc.normalized_label LIKE '%noninterest_bearing_deposit%'
                  )
                GROUP BY t.period_id
                HAVING SUM(f.value_numeric) > 0
            """)
            
            deposit_result = conn.execute(deposit_query, {'ticker': ticker})
            periods = [(row[0], row[1]) for row in deposit_result]
            
            if periods:
                # Company has deposit liabilities - use as current_liabilities for banks
                concept_query = text("""
                    SELECT concept_id FROM dim_concepts
                    WHERE normalized_label IN ('current_liabilities', 'liabilities_current')
                    LIMIT 1;
                """)
                
                concept_result = conn.execute(concept_query).fetchone()
                if concept_result:
                    concept_id = concept_result[0]
                    
                    for period_id, total_value in periods:
                        if total_value > 0:
                            filing_query = text("""
                                SELECT DISTINCT f.filing_id
                                FROM fact_financial_metrics f
                                WHERE f.company_id = :company_id
                                  AND f.period_id = :period_id
                                LIMIT 1;
                            """)
                            
                            filing_result = conn.execute(filing_query, {
                                'company_id': company_id,
                                'period_id': period_id
                            }).fetchone()
                            
                            if filing_result:
                                if create_calculated_total_fact(engine, company_id, filing_result[0], period_id,
                                                                concept_id, total_value):
                                    calculated_count += 1
                                    logger.info(f"  ✅ {ticker}: Created current_liabilities from deposit liabilities: {total_value:,.0f}")
        
        return calculated_count


def _calculate_noncurrent_liabilities(engine) -> int:
    """
    Calculate noncurrent_liabilities from components OR from total - current.
    Returns count of calculated totals.
    """
    logger.info("Calculating noncurrent_liabilities...")
    
    with engine.connect() as conn:
        missing_query = text("""
            SELECT DISTINCT c.ticker, c.company_id
            FROM dim_companies c
            WHERE NOT EXISTS (
                SELECT 1
                FROM fact_financial_metrics f
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                WHERE f.company_id = c.company_id
                  AND f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND dc.normalized_label = 'noncurrent_liabilities'
            )
            AND c.company_id > 0;
        """)
        
        missing_companies = [(row[0], row[1]) for row in conn.execute(missing_query)]
        
        if not missing_companies:
            return 0
        
        calculated_count = 0
        
        for ticker, company_id in missing_companies:
            # Strategy 1: Calculate from components (if available)
            components = find_noncurrent_liability_components(engine, ticker)
            
            if components and len(components) > 0:
                # Use component summation
                noncurrent_concept_query = text("""
                    SELECT concept_id FROM dim_concepts
                    WHERE normalized_label IN ('noncurrent_liabilities', 'liabilities_noncurrent')
                    LIMIT 1;
                """)
                
                concept_result = conn.execute(noncurrent_concept_query).fetchone()
                if concept_result:
                    concept_id = concept_result[0]
                    
                    for period_id, total_value, component_count in components:
                        filing_query = text("""
                            SELECT DISTINCT f.filing_id
                            FROM fact_financial_metrics f
                            WHERE f.company_id = :company_id
                              AND f.period_id = :period_id
                            LIMIT 1;
                        """)
                        
                        filing_result = conn.execute(filing_query, {
                            'company_id': company_id,
                            'period_id': period_id
                        }).fetchone()
                        
                        if filing_result:
                            if create_calculated_total_fact(engine, company_id, filing_result[0], period_id, 
                                                            concept_id, total_value):
                                calculated_count += 1
                                logger.info(f"  ✅ {ticker}: Created noncurrent_liabilities from components: {total_value:,.0f}")
            
            # Strategy 2: Calculate as total_liabilities - current_liabilities (if Strategy 1 didn't work)
            else:
                calc_query = text("""
                    SELECT 
                        t.fiscal_year,
                        t.period_id,
                        SUM(CASE 
                            WHEN dc.normalized_label IN ('total_liabilities', 'liabilities') 
                            THEN f.value_numeric ELSE 0 END) -
                        SUM(CASE 
                            WHEN dc.normalized_label IN ('current_liabilities', 'liabilities_current') 
                            THEN f.value_numeric ELSE 0 END) as noncurrent_calc
                    FROM fact_financial_metrics f
                    JOIN dim_companies c ON f.company_id = c.company_id
                    JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                    JOIN dim_time_periods t ON f.period_id = t.period_id
                    WHERE c.ticker = :ticker
                      AND f.dimension_id IS NULL
                      AND f.value_numeric IS NOT NULL
                      AND dc.normalized_label IN (
                          'total_liabilities', 
                          'liabilities',  -- Total liabilities variant
                          'current_liabilities', 
                          'liabilities_current'  -- Current liabilities variant
                      )
                    GROUP BY t.fiscal_year, t.period_id
                    HAVING SUM(CASE 
                        WHEN dc.normalized_label IN ('total_liabilities', 'liabilities') THEN 1 ELSE 0 END) > 0
                       AND SUM(CASE 
                        WHEN dc.normalized_label IN ('current_liabilities', 'liabilities_current') THEN 1 ELSE 0 END) > 0
                    ORDER BY t.fiscal_year;
                """)
                
                calc_result = conn.execute(calc_query, {'ticker': ticker})
                calc_periods = [(row[1], row[2]) for row in calc_result]  # period_id, noncurrent_calc
                
                if calc_periods:
                    concept_query = text("""
                        SELECT concept_id FROM dim_concepts
                        WHERE normalized_label IN ('noncurrent_liabilities', 'liabilities_noncurrent')
                        LIMIT 1;
                    """)
                    
                    concept_result = conn.execute(concept_query).fetchone()
                    if concept_result:
                        concept_id = concept_result[0]
                        
                        for period_id, noncurrent_value in calc_periods:
                            if noncurrent_value > 0:  # Sanity check
                                filing_query = text("""
                                    SELECT DISTINCT f.filing_id
                                    FROM fact_financial_metrics f
                                    WHERE f.company_id = :company_id
                                      AND f.period_id = :period_id
                                    LIMIT 1;
                                """)
                                
                                filing_result = conn.execute(filing_query, {
                                    'company_id': company_id,
                                    'period_id': period_id
                                }).fetchone()
                                
                                if filing_result:
                                    if create_calculated_total_fact(engine, company_id, filing_result[0], period_id, 
                                                                    concept_id, noncurrent_value):
                                        calculated_count += 1
                                        logger.info(f"  ✅ {ticker}: Created noncurrent_liabilities (Total - Current): {noncurrent_value:,.0f}")
        
        return calculated_count


def find_noncurrent_liability_components(engine, company_ticker: str) -> List[Tuple[int, float, int]]:
    """
    Find all noncurrent liability components for a company.
    Returns: [(period_id, total_value, component_count)] grouped by period
    """
    with engine.connect() as conn:
        # Find all noncurrent liability concepts for this company
        query = text("""
            SELECT DISTINCT
                dc.concept_id,
                dc.concept_name,
                dc.normalized_label
            FROM fact_financial_metrics f
            JOIN dim_companies c ON f.company_id = c.company_id
            JOIN dim_concepts dc ON f.concept_id = dc.concept_id
            WHERE c.ticker = :ticker
              AND f.dimension_id IS NULL
              AND f.value_numeric IS NOT NULL
              AND (
                  dc.normalized_label LIKE '%noncurrent%liabilit%'
                  OR dc.concept_name ILIKE '%NoncurrentLiabilit%'
                  OR dc.concept_name ILIKE '%LiabilitiesNoncurrent%'
                  OR dc.concept_name ILIKE '%LongTermLiabilit%'
              )
              AND dc.normalized_label != 'noncurrent_liabilities'  -- Exclude if total already exists
            ORDER BY dc.concept_name;
        """)
        
        result = conn.execute(query, {'ticker': company_ticker})
        components = [(row[0], row[1], row[2]) for row in result]
        
        if not components:
            return []
        
        logger.info(f"  Found {len(components)} noncurrent liability components for {company_ticker}")
        
        # Sum components by period
        query_sum = text("""
            WITH components AS (
                SELECT DISTINCT dc.concept_id
                FROM dim_concepts dc
                WHERE dc.concept_id = ANY(:component_ids)
            )
            SELECT 
                f.period_id,
                SUM(f.value_numeric) as total_value,
                COUNT(DISTINCT f.concept_id) as component_count
            FROM fact_financial_metrics f
            JOIN dim_companies c ON f.company_id = c.company_id
            JOIN components comp ON f.concept_id = comp.concept_id
            WHERE c.ticker = :ticker
              AND f.dimension_id IS NULL
              AND f.value_numeric IS NOT NULL
            GROUP BY f.period_id
            HAVING COUNT(DISTINCT f.concept_id) >= 1  -- At least 1 component (sum all available)
            ORDER BY f.period_id;
        """)
        
        component_ids = [c[0] for c in components]
        result_sum = conn.execute(query_sum, {
            'ticker': company_ticker,
            'component_ids': component_ids
        })
        
        return [(row[0], row[1], row[2]) for row in result_sum]


def create_calculated_total_fact(engine, company_id: int, filing_id: int, period_id: int, 
                                 concept_id: int, total_value: float) -> bool:
    """
    Create a calculated total fact in the database.
    Returns True if successful, False otherwise.
    """
    try:
        with engine.connect() as conn:
            # Check if fact already exists
            check_query = text("""
                SELECT fact_id FROM fact_financial_metrics
                WHERE company_id = :company_id
                  AND filing_id = :filing_id
                  AND period_id = :period_id
                  AND concept_id = :concept_id
                  AND dimension_id IS NULL;
            """)
            
            existing = conn.execute(check_query, {
                'company_id': company_id,
                'filing_id': filing_id,
                'period_id': period_id,
                'concept_id': concept_id
            }).fetchone()
            
            if existing:
                logger.debug(f"  Calculated total already exists, skipping")
                return True
            
            # Insert calculated total
            # Get filing_id from period_id (simplified - in reality might need to get from period)
            insert_query = text("""
                INSERT INTO fact_financial_metrics (
                    company_id, filing_id, concept_id, period_id, dimension_id,
                    value_numeric, scale_int, is_calculated
                )
                SELECT 
                    :company_id,
                    :filing_id,
                    :concept_id,
                    :period_id,
                    NULL,
                    :total_value,
                    0,
                    TRUE
                WHERE NOT EXISTS (
                    SELECT 1 FROM fact_financial_metrics
                    WHERE company_id = :company_id
                      AND filing_id = :filing_id
                      AND period_id = :period_id
                      AND concept_id = :concept_id
                      AND dimension_id IS NULL
                );
            """)
            
            conn.execute(insert_query, {
                'company_id': company_id,
                'filing_id': filing_id,
                'concept_id': concept_id,
                'period_id': period_id,
                'total_value': total_value
            })
            
            conn.commit()
            return True
            
    except Exception as e:
        logger.error(f"Error creating calculated total: {e}")
        return False


def calculate_missing_totals(engine) -> Dict[str, int]:
    """
    Calculate missing universal metric totals for all companies that need them.
    Returns: {metric: count_of_calculated_totals}
    
    Uses accounting identities and component summation:
    - noncurrent_liabilities = total_liabilities - current_liabilities (if components not available)
    - revenue = sum of revenue components (if total not available)
    - current_liabilities = sum of current liability components (if total not available)
    """
    logger.info("="*100)
    logger.info("CALCULATING MISSING UNIVERSAL METRIC TOTALS")
    logger.info("="*100)
    
    results = {}
    
    # 1. Calculate revenue from components (e.g., SNY: RevenueFromSaleOfGoods + OtherRevenue)
    revenue_count = _calculate_revenue_from_components(engine)
    if revenue_count > 0:
        results['revenue'] = revenue_count
    
    # 2. Calculate current_liabilities from components (e.g., SNY IFRS, banks)
    current_liab_count = _calculate_current_liabilities_from_components(engine)
    if current_liab_count > 0:
        results['current_liabilities'] = current_liab_count
    
    # 2b. Calculate current_liabilities for banks (from deposit liabilities)
    bank_current_liab_count = _calculate_bank_current_liabilities(engine)
    if bank_current_liab_count > 0:
        results['current_liabilities'] = results.get('current_liabilities', 0) + bank_current_liab_count
    
    # 3. Calculate noncurrent_liabilities (from components OR total - current)
    noncurrent_count = _calculate_noncurrent_liabilities(engine)
    if noncurrent_count > 0:
        results['noncurrent_liabilities'] = noncurrent_count
    
    # 4. Calculate total_liabilities (from current + noncurrent, or from assets - equity)
    total_liab_count = _calculate_total_liabilities(engine)
    if total_liab_count > 0:
        results['total_liabilities'] = total_liab_count
    
    # 5. Calculate stockholders_equity (from assets - liabilities)
    equity_count = _calculate_stockholders_equity(engine)
    if equity_count > 0:
        results['stockholders_equity'] = equity_count
    
    # 6. Calculate accounts_payable for banks (from accrued_liabilities_and_other_liabilities)
    accounts_payable_count = _calculate_accounts_payable_from_accrued(engine)
    if accounts_payable_count > 0:
        results['accounts_payable'] = accounts_payable_count
    
    with engine.connect() as conn:
        # Find companies missing noncurrent_liabilities
        missing_query = text("""
            SELECT DISTINCT c.ticker, c.company_id
            FROM dim_companies c
            WHERE NOT EXISTS (
                SELECT 1
                FROM fact_financial_metrics f
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                WHERE f.company_id = c.company_id
                  AND f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND dc.normalized_label = 'noncurrent_liabilities'
            )
            AND c.company_id > 0;
        """)
        
        missing_companies = [(row[0], row[1]) for row in conn.execute(missing_query)]
        
        if not missing_companies:
            logger.info("✅ No companies missing noncurrent_liabilities!")
            return {'noncurrent_liabilities': 0}
        
        logger.info(f"Found {len(missing_companies)} companies missing noncurrent_liabilities")
        
        # Get or create the noncurrent_liabilities concept
        concept_query = text("""
            SELECT concept_id FROM dim_concepts
            WHERE normalized_label = 'noncurrent_liabilities'
            LIMIT 1;
        """)
        
        concept_result = conn.execute(concept_query).fetchone()
        
        if not concept_result:
            logger.warning("noncurrent_liabilities concept not found in dim_concepts - cannot calculate totals")
            return {'noncurrent_liabilities': 0}
        
        total_concept_id = concept_result[0]
        calculated_count = 0
        
        # For each company, sum components
        for ticker, company_id in missing_companies:
            logger.info(f"\nProcessing {ticker}...")
            
            components = find_noncurrent_liability_components(engine, ticker)
            
            if not components:
                logger.info(f"  No components found - cannot calculate total")
                continue
            
            # For each period, create calculated total
            for period_id, total_value, component_count in components:
                # Get filing_id from period (simplified - assumes one filing per period)
                filing_query = text("""
                    SELECT DISTINCT f.filing_id
                    FROM fact_financial_metrics f
                    WHERE f.company_id = :company_id
                      AND f.period_id = :period_id
                    LIMIT 1;
                """)
                
                filing_result = conn.execute(filing_query, {
                    'company_id': company_id,
                    'period_id': period_id
                }).fetchone()
                
                if not filing_result:
                    logger.warning(f"  No filing found for period {period_id}")
                    continue
                
                filing_id = filing_result[0]
                
                if create_calculated_total_fact(engine, company_id, filing_id, period_id, 
                                                total_concept_id, total_value):
                    calculated_count += 1
                    logger.info(f"  ✅ Created calculated total for period {period_id}: {total_value:,.0f} ({component_count} components)")
        
        results['noncurrent_liabilities'] = calculated_count
        logger.info(f"\n✅ Created {calculated_count} calculated totals for noncurrent_liabilities")
    
    return results


def _calculate_total_liabilities(engine) -> int:
    """
    Calculate total_liabilities from current + noncurrent, or from assets - equity.
    Returns count of calculated totals.
    """
    logger.info("Calculating total_liabilities...")
    
    with engine.connect() as conn:
        missing_query = text("""
            SELECT DISTINCT c.ticker, c.company_id
            FROM dim_companies c
            WHERE NOT EXISTS (
                SELECT 1
                FROM fact_financial_metrics f
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                WHERE f.company_id = c.company_id
                  AND f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND dc.normalized_label IN ('total_liabilities', 'liabilities')
            )
            AND c.company_id > 0;
        """)
        
        missing_companies = [(row[0], row[1]) for row in conn.execute(missing_query)]
        
        if not missing_companies:
            return 0
        
        calculated_count = 0
        
        for ticker, company_id in missing_companies:
            # Strategy 1: Calculate from current + noncurrent
            calc_query = text("""
                SELECT 
                    t.period_id,
                    SUM(CASE WHEN dc.normalized_label IN ('current_liabilities', 'liabilities_current') THEN f.value_numeric ELSE 0 END) +
                    SUM(CASE WHEN dc.normalized_label IN ('noncurrent_liabilities', 'liabilities_noncurrent') THEN f.value_numeric ELSE 0 END) as total_liab
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                JOIN dim_time_periods t ON f.period_id = t.period_id
                WHERE c.ticker = :ticker
                  AND f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND dc.normalized_label IN ('current_liabilities', 'liabilities_current', 'noncurrent_liabilities', 'liabilities_noncurrent')
                GROUP BY t.period_id
                HAVING SUM(CASE WHEN dc.normalized_label IN ('current_liabilities', 'liabilities_current') THEN 1 ELSE 0 END) > 0
                   AND SUM(CASE WHEN dc.normalized_label IN ('noncurrent_liabilities', 'liabilities_noncurrent') THEN 1 ELSE 0 END) > 0
            """)
            
            calc_result = conn.execute(calc_query, {'ticker': ticker})
            periods = [(row[0], row[1]) for row in calc_result]  # period_id, total_liab
            
            if periods:
                concept_query = text("""
                    SELECT concept_id FROM dim_concepts
                    WHERE normalized_label IN ('total_liabilities', 'liabilities')
                    LIMIT 1;
                """)
                
                concept_result = conn.execute(concept_query).fetchone()
                if concept_result:
                    concept_id = concept_result[0]
                    
                    for period_id, total_value in periods:
                        if total_value > 0:
                            filing_query = text("""
                                SELECT DISTINCT f.filing_id
                                FROM fact_financial_metrics f
                                WHERE f.company_id = :company_id
                                  AND f.period_id = :period_id
                                LIMIT 1;
                            """)
                            
                            filing_result = conn.execute(filing_query, {
                                'company_id': company_id,
                                'period_id': period_id
                            }).fetchone()
                            
                            if filing_result:
                                if create_calculated_total_fact(engine, company_id, filing_result[0], period_id,
                                                                concept_id, total_value):
                                    calculated_count += 1
                                    logger.info(f"  ✅ {ticker}: Created total_liabilities (Current + Noncurrent): {total_value:,.0f}")
            
            # Strategy 2: Calculate from assets - equity (if Strategy 1 didn't work)
            else:
                balance_sheet_query = text("""
                    SELECT 
                        t.period_id,
                        SUM(CASE WHEN dc.normalized_label IN ('total_assets', 'total_assets_equation') THEN f.value_numeric ELSE 0 END) -
                        SUM(CASE WHEN dc.normalized_label IN ('stockholders_equity', 'equity_attributable_to_parent', 'equity_total', 'equity') THEN f.value_numeric ELSE 0 END) as total_liab
                    FROM fact_financial_metrics f
                    JOIN dim_companies c ON f.company_id = c.company_id
                    JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                    JOIN dim_time_periods t ON f.period_id = t.period_id
                    WHERE c.ticker = :ticker
                      AND f.dimension_id IS NULL
                      AND f.value_numeric IS NOT NULL
                      AND (
                          dc.normalized_label IN ('total_assets', 'total_assets_equation')
                          OR dc.normalized_label IN ('stockholders_equity', 'equity_attributable_to_parent', 'equity_total', 'equity')
                      )
                    GROUP BY t.period_id
                    HAVING SUM(CASE WHEN dc.normalized_label IN ('total_assets', 'total_assets_equation') THEN 1 ELSE 0 END) > 0
                       AND SUM(CASE WHEN dc.normalized_label IN ('stockholders_equity', 'equity_attributable_to_parent', 'equity_total', 'equity') THEN 1 ELSE 0 END) > 0
                """)
                
                balance_result = conn.execute(balance_sheet_query, {'ticker': ticker})
                balance_periods = [(row[0], row[1]) for row in balance_result]
                
                if balance_periods:
                    concept_query = text("""
                        SELECT concept_id FROM dim_concepts
                        WHERE normalized_label IN ('total_liabilities', 'liabilities')
                        LIMIT 1;
                    """)
                    
                    concept_result = conn.execute(concept_query).fetchone()
                    if concept_result:
                        concept_id = concept_result[0]
                        
                        for period_id, total_value in balance_periods:
                            if total_value > 0:
                                filing_query = text("""
                                    SELECT DISTINCT f.filing_id
                                    FROM fact_financial_metrics f
                                    WHERE f.company_id = :company_id
                                      AND f.period_id = :period_id
                                    LIMIT 1;
                                """)
                                
                                filing_result = conn.execute(filing_query, {
                                    'company_id': company_id,
                                    'period_id': period_id
                                }).fetchone()
                                
                                if filing_result:
                                    if create_calculated_total_fact(engine, company_id, filing_result[0], period_id,
                                                                    concept_id, total_value):
                                        calculated_count += 1
                                        logger.info(f"  ✅ {ticker}: Created total_liabilities (Assets - Equity): {total_value:,.0f}")
        
        return calculated_count


def _calculate_stockholders_equity(engine) -> int:
    """
    Calculate stockholders_equity from assets - liabilities.
    Returns count of calculated totals.
    """
    logger.info("Calculating stockholders_equity...")
    
    with engine.connect() as conn:
        missing_query = text("""
            SELECT DISTINCT c.ticker, c.company_id
            FROM dim_companies c
            WHERE NOT EXISTS (
                SELECT 1
                FROM fact_financial_metrics f
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                WHERE f.company_id = c.company_id
                  AND f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND dc.normalized_label IN ('stockholders_equity', 'equity_attributable_to_parent', 'equity_total', 'equity')
            )
            AND c.company_id > 0;
        """)
        
        missing_companies = [(row[0], row[1]) for row in conn.execute(missing_query)]
        
        if not missing_companies:
            return 0
        
        calculated_count = 0
        
        for ticker, company_id in missing_companies:
            # Calculate from assets - liabilities
            balance_sheet_query = text("""
                SELECT 
                    t.period_id,
                    SUM(CASE WHEN dc.normalized_label IN ('total_assets', 'total_assets_equation') THEN f.value_numeric ELSE 0 END) -
                    SUM(CASE WHEN dc.normalized_label IN ('total_liabilities', 'liabilities') THEN f.value_numeric ELSE 0 END) as equity
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                JOIN dim_time_periods t ON f.period_id = t.period_id
                WHERE c.ticker = :ticker
                  AND f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND (
                      dc.normalized_label IN ('total_assets', 'total_assets_equation')
                      OR dc.normalized_label IN ('total_liabilities', 'liabilities')
                  )
                GROUP BY t.period_id
                HAVING SUM(CASE WHEN dc.normalized_label IN ('total_assets', 'total_assets_equation') THEN 1 ELSE 0 END) > 0
                   AND SUM(CASE WHEN dc.normalized_label IN ('total_liabilities', 'liabilities') THEN 1 ELSE 0 END) > 0
            """)
            
            balance_result = conn.execute(balance_sheet_query, {'ticker': ticker})
            periods = [(row[0], row[1]) for row in balance_result]
            
            if periods:
                concept_query = text("""
                    SELECT concept_id FROM dim_concepts
                    WHERE normalized_label IN ('stockholders_equity', 'equity_attributable_to_parent', 'equity_total', 'equity')
                    ORDER BY CASE normalized_label
                        WHEN 'stockholders_equity' THEN 1
                        WHEN 'equity_attributable_to_parent' THEN 2
                        WHEN 'equity_total' THEN 3
                        WHEN 'equity' THEN 4
                    END
                    LIMIT 1;
                """)
                
                concept_result = conn.execute(concept_query).fetchone()
                if concept_result:
                    concept_id = concept_result[0]
                    
                    for period_id, equity_value in periods:
                        if equity_value > 0:
                            filing_query = text("""
                                SELECT DISTINCT f.filing_id
                                FROM fact_financial_metrics f
                                WHERE f.company_id = :company_id
                                  AND f.period_id = :period_id
                                LIMIT 1;
                            """)
                            
                            filing_result = conn.execute(filing_query, {
                                'company_id': company_id,
                                'period_id': period_id
                            }).fetchone()
                            
                            if filing_result:
                                if create_calculated_total_fact(engine, company_id, filing_result[0], period_id,
                                                                concept_id, equity_value):
                                    calculated_count += 1
                                    logger.info(f"  ✅ {ticker}: Created stockholders_equity (Assets - Liabilities): {equity_value:,.0f}")
        
        return calculated_count


def _calculate_accounts_payable_from_accrued(engine) -> int:
    """
    Calculate accounts_payable for companies that have accrued_liabilities_and_other_liabilities
    but not accounts_payable (e.g., BAC).
    
    Universal solution: If company has accrued_liabilities_and_other_liabilities but NOT accounts_payable,
    and does NOT have AccountsPayableCurrent (which would cause duplicates), map it to accounts_payable.
    Returns count of calculated totals.
    """
    logger.info("Calculating accounts_payable from accrued_liabilities_and_other_liabilities...")
    
    with engine.connect() as conn:
        missing_query = text("""
            SELECT DISTINCT c.ticker, c.company_id
            FROM dim_companies c
            WHERE NOT EXISTS (
                SELECT 1
                FROM fact_financial_metrics f
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                WHERE f.company_id = c.company_id
                  AND f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND dc.normalized_label IN ('accounts_payable', 'accounts_payable_current')
            )
            AND EXISTS (
                SELECT 1
                FROM fact_financial_metrics f
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                WHERE f.company_id = c.company_id
                  AND f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND dc.normalized_label = 'accrued_liabilities_and_other_liabilities'
            )
            AND NOT EXISTS (
                SELECT 1
                FROM fact_financial_metrics f
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                WHERE f.company_id = c.company_id
                  AND f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND dc.concept_name = 'AccountsPayableCurrent'
            )
            AND c.company_id > 0;
        """)
        
        missing_companies = [(row[0], row[1]) for row in conn.execute(missing_query)]
        
        if not missing_companies:
            return 0
        
        calculated_count = 0
        
        for ticker, company_id in missing_companies:
            # Get accrued_liabilities_and_other_liabilities values
            accrued_query = text("""
                SELECT 
                    t.period_id,
                    f.value_numeric
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                JOIN dim_time_periods t ON f.period_id = t.period_id
                WHERE c.ticker = :ticker
                  AND f.dimension_id IS NULL
                  AND f.value_numeric IS NOT NULL
                  AND dc.normalized_label = 'accrued_liabilities_and_other_liabilities'
            """)
            
            accrued_result = conn.execute(accrued_query, {'ticker': ticker})
            periods = [(row[0], row[1]) for row in accrued_result]
            
            if periods:
                # Get accounts_payable concept_id
                concept_query = text("""
                    SELECT concept_id FROM dim_concepts
                    WHERE normalized_label = 'accounts_payable'
                    LIMIT 1;
                """)
                
                concept_result = conn.execute(concept_query).fetchone()
                if concept_result:
                    concept_id = concept_result[0]
                    
                    for period_id, accrued_value in periods:
                        if accrued_value > 0:
                            filing_query = text("""
                                SELECT DISTINCT f.filing_id
                                FROM fact_financial_metrics f
                                WHERE f.company_id = :company_id
                                  AND f.period_id = :period_id
                                LIMIT 1;
                            """)
                            
                            filing_result = conn.execute(filing_query, {
                                'company_id': company_id,
                                'period_id': period_id
                            }).fetchone()
                            
                            if filing_result:
                                if create_calculated_total_fact(engine, company_id, filing_result[0], period_id,
                                                                concept_id, accrued_value):
                                    calculated_count += 1
                                    logger.info(f"  ✅ {ticker}: Created accounts_payable from accrued_liabilities_and_other_liabilities: {accrued_value:,.0f}")
        
        return calculated_count


def run_calculate_totals() -> Dict[str, int]:
    """
    Main function to calculate missing totals.
    This should be called from the ETL pipeline after normalization.
    """
    engine = create_engine(DATABASE_URI)
    return calculate_missing_totals(engine)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = run_calculate_totals()
    print(f"\nResults: {results}")

