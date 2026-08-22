"""
Post-Load Gap Filling

Fills missing concepts and corrects wrong values AFTER data is loaded to database.
This catches cases where:
1. XBRL has wrong values (scaling issues)
2. Concepts exist but are missing for specific years
3. Normalized labels exist but wrong concept names were used

This runs AFTER database load, so it can query what's actually in the DB.
"""
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy import create_engine, text
from pathlib import Path

from config import DATABASE_URI
from scripts.sec_api_validator import fetch_sec_facts, get_cik_from_ticker
from src.utils.taxonomy_mappings import get_normalized_label

logger = logging.getLogger(__name__)


def fill_missing_from_database(
    ticker: str,
    years: List[int],
    taxonomy: str = 'ifrs-full',
    cache_dir: Optional[Path] = None,
    primary_year: Optional[int] = None,
    filing_type: Optional[str] = None
) -> int:
    """
    Query database for missing concepts/years and fill from SEC API.

    This runs AFTER database load, so it can:
    1. Find concepts that are missing for specific years
    2. Detect wrong values by comparing XBRL vs SEC_API
    3. Add SEC_API data even when XBRL exists (loader prefers SEC_API)

    Args:
        ticker: Company ticker
        years: List of years to check for missing concepts — these are DATA years
            (comparative periods potentially covered by the one filing being processed),
            not separate filings.
        taxonomy: Taxonomy to use
        cache_dir: Optional cache directory for SEC API responses
        primary_year: The fiscal year of the filing actually being loaded (e.g. 2024 for
            NVO's FY2024 20-F). All gap-filled facts — even ones representing a
            comparative year like 2022 — belong to THIS ONE filing document, not to a
            separate filing keyed to their own data year. Without this, each `year` in
            `years` was used directly as the temp JSON's `fiscal_year_end`, so
            `get_or_create_filing()` created a brand new, wrong filing record per
            comparative year instead of attaching supplementary facts to the filing they
            actually supplement. Confirmed causing spurious `dim_filings` rows and a
            downstream "phantom period" in fact_income_statement — see
            docs/NVO_GOLDEN_PATH_2026-08.md. Falls back to the loop's own `year` (old,
            buggy behavior) only if not provided, for backward compatibility.
        filing_type: The filing type of the primary filing (e.g. '20-F'). Falls back to
            taxonomy-based inference if not provided.

    Returns:
        Number of facts added
    """
    engine = create_engine(DATABASE_URI)
    
    # Get CIK
    cik = get_cik_from_ticker(ticker)
    if not cik:
        logger.warning(f"CIK not found for {ticker}, skipping post-load gap filling")
        return 0
    
    filled_count = 0
    
    with engine.connect() as conn:
        for year in years:
            # Find missing concepts for this year
            # Two cases:
            # 1. Normalized labels that exist for company but missing for this year
            # 2. Normalized labels that exist for this year but ONLY from XBRL (add SEC_API as alternative)
            result = conn.execute(text("""
                WITH company_concepts AS (
                    -- All normalized labels this company has (any year)
                    SELECT DISTINCT dc.normalized_label
                    FROM fact_financial_metrics f
                    JOIN dim_companies c ON f.company_id = c.company_id
                    JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                    WHERE c.ticker = :ticker
                      AND dc.normalized_label IS NOT NULL
                      AND f.dimension_id IS NULL
                ),
                missing_for_year AS (
                    -- Normalized labels that exist for company but missing for this year
                    -- UNIVERSAL FIX: Check both fiscal_year (for duration periods) and instant_date year (for instant periods like balance sheet)
                    SELECT cc.normalized_label
                    FROM company_concepts cc
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM fact_financial_metrics f
                        JOIN dim_companies c ON f.company_id = c.company_id
                        JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                        JOIN dim_time_periods dt ON f.period_id = dt.period_id
                        WHERE c.ticker = :ticker
                          AND dc.normalized_label = cc.normalized_label
                          AND (
                              -- For duration periods: check fiscal_year
                              (dt.period_type = 'duration' AND dt.fiscal_year = :year)
                              OR
                              -- For instant periods (balance sheet): check instant_date year
                              (dt.period_type = 'instant' AND dt.instant_date IS NOT NULL 
                               AND EXTRACT(YEAR FROM dt.instant_date) = :year)
                          )
                          AND f.dimension_id IS NULL
                          AND f.value_numeric IS NOT NULL
                    )
                ),
                xbrl_only_for_year AS (
                    -- Normalized labels that exist for this year but ONLY from XBRL (no SEC_API)
                    -- Add SEC_API as alternative (loader will prefer SEC_API)
                    -- UNIVERSAL FIX: Check both fiscal_year (for duration periods) and instant_date year (for instant periods)
                    SELECT DISTINCT dc.normalized_label
                    FROM fact_financial_metrics f
                    JOIN dim_companies c ON f.company_id = c.company_id
                    JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                    JOIN dim_time_periods dt ON f.period_id = dt.period_id
                    WHERE c.ticker = :ticker
                      AND (
                          -- For duration periods: check fiscal_year
                          (dt.period_type = 'duration' AND dt.fiscal_year = :year)
                          OR
                          -- For instant periods (balance sheet): check instant_date year
                          (dt.period_type = 'instant' AND dt.instant_date IS NOT NULL 
                           AND EXTRACT(YEAR FROM dt.instant_date) = :year)
                      )
                      AND f.dimension_id IS NULL
                      AND f.value_numeric IS NOT NULL
                      AND f.source = 'XBRL'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM fact_financial_metrics f2
                          JOIN dim_companies c2 ON f2.company_id = c2.company_id
                          JOIN dim_concepts dc2 ON f2.concept_id = dc2.concept_id
                          JOIN dim_time_periods dt2 ON f2.period_id = dt2.period_id
                          WHERE c2.ticker = :ticker
                            AND dc2.normalized_label = dc.normalized_label
                            AND (
                                -- For duration periods: check fiscal_year
                                (dt2.period_type = 'duration' AND dt2.fiscal_year = :year)
                                OR
                                -- For instant periods (balance sheet): check instant_date year
                                (dt2.period_type = 'instant' AND dt2.instant_date IS NOT NULL 
                                 AND EXTRACT(YEAR FROM dt2.instant_date) = :year)
                            )
                            AND f2.dimension_id IS NULL
                            AND f2.source = 'SEC_API'
                      )
                )
                SELECT normalized_label FROM missing_for_year
                UNION
                SELECT normalized_label FROM xbrl_only_for_year
                -- No limit - we want ALL missing concepts, not just first 200
            """), {'ticker': ticker, 'year': year})
            
            missing_labels = [row[0] for row in result]
            
            if not missing_labels:
                continue
            
            logger.info(f"Found {len(missing_labels)} missing normalized labels for {ticker} {year}")
            if len(missing_labels) > 0:
                logger.info(f"Missing labels (first 30): {missing_labels[:30]}")
                # Log critical missing concepts
                critical_missing = [label for label in missing_labels if any(term in label.lower() for term in ['assets', 'liabilities', 'equity', 'cash_flow_hedge', 'total_'])]
                if critical_missing:
                    logger.warning(f"Critical missing concepts: {critical_missing[:10]}")
            
            # Fetch SEC API data for this year
            sec_facts = None
            cache_file = None
            if cache_dir:
                cache_dir = Path(cache_dir)
                cache_dir.mkdir(parents=True, exist_ok=True)
                cache_file = cache_dir / f"sec_api_{ticker}_{year}_{taxonomy}.json"
                if cache_file.exists():
                    try:
                        import json
                        with open(cache_file, 'r') as f:
                            sec_facts = json.load(f)
                        logger.debug(f"Using cached SEC API data for {ticker} {year}")
                    except Exception as e:
                        logger.debug(f"Cache read failed: {e}, fetching from API")
            
            if sec_facts is None:
                logger.info(f"Fetching SEC API data for {ticker} {year}...")
                sec_facts = fetch_sec_facts(cik, year, taxonomy)
                
                if sec_facts and cache_file:
                    try:
                        import json
                        with open(cache_file, 'w') as f:
                            json.dump(sec_facts, f, indent=2)
                    except Exception as e:
                        logger.debug(f"Cache write failed: {e}")
            
            if not sec_facts:
                continue
            
            # Find SEC API facts that match missing normalized labels
            # UNIVERSAL FIX: Try multiple normalized_label variants and fuzzy matching
            facts_to_add = []
            matched_labels = set()  # Track which missing_labels we've matched
            
            for key, facts_list in sec_facts.items():
                for sec_fact in facts_list:
                    concept_name = sec_fact.get('concept', '')
                    if not concept_name:
                        continue
                    
                    sec_normalized = get_normalized_label(concept_name)
                    if not sec_normalized:
                        continue
                    
                    # Try exact match first
                    matched_missing_label = None
                    if sec_normalized in missing_labels:
                        matched_missing_label = sec_normalized
                    else:
                        # UNIVERSAL FIX: Try fuzzy matching for concepts like "Assets" vs "total_assets"
                        for missing_label in missing_labels:
                            if missing_label in matched_labels:
                                continue  # Already matched
                            # Check if labels are similar (e.g., "assets" vs "total_assets")
                            if (missing_label in sec_normalized or sec_normalized in missing_label or
                                missing_label.replace('total_', '') == sec_normalized.replace('total_', '') or
                                missing_label.replace('_total', '') == sec_normalized.replace('_total', '') or
                                missing_label.replace('_', '') == sec_normalized.replace('_', '')):
                                # Found a fuzzy match!
                                matched_missing_label = missing_label
                                matched_labels.add(missing_label)
                                logger.debug(f"Fuzzy match: {missing_label} <-> {sec_normalized}")
                                break
                    
                    if not matched_missing_label:
                        continue
                    
                    # Found a match! Add this fact
                    period = sec_fact.get('period', {})
                    period_end = period.get('end') or period.get('instant', f'{year}-12-31')
                    is_instant = 'instant' in period or (period.get('frame', '').endswith('I') and 'end' in period)
                    
                    # Determine if balance sheet item
                    is_balance_sheet = sec_normalized and any(bs_term in sec_normalized.lower() for bs_term in [
                        'assets', 'liabilities', 'equity', 'property_plant_equipment', 'inventory',
                        'accounts_receivable', 'cash_and_equivalents', 'accounts_payable', 'debt'
                    ])
                    
                    fact_dict = {
                        'concept': concept_name,
                        'value': sec_fact.get('value'),
                        'value_numeric': sec_fact.get('value'),
                        'normalized_label': matched_missing_label,  # Use the matched missing label (not sec_normalized)
                        'period_end': period_end if not is_balance_sheet and 'end' in period else None,
                        'instant_date': period_end if (is_balance_sheet or is_instant) else None,
                        'unit_measure': sec_fact.get('unit', ''),
                        'source': 'SEC_API',
                        'is_gap_filled': True,
                        'taxonomy': sec_fact.get('taxonomy', taxonomy)
                    }
                    facts_to_add.append(fact_dict)
            
            if facts_to_add:
                # Load these facts using the loader
                from database.load_financial_data import StarSchemaLoader
                import json
                from config import DATA_PROCESSED
                
                # Create temporary JSON file. CRITICAL: 'year'/'fiscal_year_end' here must
                # identify the FILING being supplemented (primary_year), not the data year
                # these particular facts happen to cover — get_or_create_filing() uses this
                # to resolve filing_id, and `year` (this loop's comparative year, e.g. 2022)
                # is not a separate filing, it's a period within the same one filing. See
                # the primary_year parameter docstring above.
                target_year = primary_year if primary_year is not None else year
                target_filing_type = filing_type or ('20-F' if taxonomy == 'ifrs-full' else '10-K')
                temp_json = DATA_PROCESSED / f"{ticker}_{year}_post_load_gap_fill.json"
                temp_json.write_text(json.dumps({
                    'company': ticker,
                    'year': target_year,
                    'filing_type': target_filing_type,
                    'facts': facts_to_add,
                    'metadata': {'fiscal_year_end': f'{target_year}-12-31'},
                    'relationships': {}  # Loader expects dict, not list
                }, indent=2, default=str))
                
                # Load using star schema loader
                # is_incremental=True: this JSON is a small supplementary batch on top of
                # an already-loaded filing, not a complete filing's facts — the default
                # (False) clears the filing's existing data first and demands full
                # statement coverage, both wrong for a handful of gap-filled facts. See
                # database/load_financial_data.py's load_json_file docstring and
                # docs/NVO_GOLDEN_PATH_2026-08.md item 5.
                loader = StarSchemaLoader()
                loader.load_json_file(temp_json, is_incremental=True)
                loader.close()
                
                temp_json.unlink()
                
                filled_count += len(facts_to_add)
                logger.info(f"✅ Added {len(facts_to_add)} facts from SEC API for {ticker} {year}")
    
                # CRITICAL: Populate presentation hierarchy for SEC_API facts
                # SEC API provides facts but NOT presentation hierarchy metadata (order_index, role_uri, etc.)
                # Use standard templates or infer from other years
                populate_sec_api_metadata(conn, ticker, year)
    
    return filled_count


def populate_sec_api_metadata(conn, ticker: str, year: int):
    """
    Populate presentation hierarchy metadata for SEC_API facts.
    
    SEC API provides facts but NOT presentation hierarchy metadata (order_index, role_uri, preferred_label, etc.).
    This function:
    1. Finds SEC_API facts missing presentation hierarchy
    2. Uses standard templates or infers from other years (same company, same concept)
    3. Inserts into rel_presentation_hierarchy with source='standard'
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from src.utils.populate_standard_presentation_order import get_template_order
    
    # Find SEC_API facts missing presentation hierarchy
    result = conn.execute(text("""
        SELECT DISTINCT
            f.filing_id,
            f.concept_id,
            dc.normalized_label,
            dc.statement_type
        FROM fact_financial_metrics f
        JOIN dim_filings fil ON f.filing_id = fil.filing_id
        JOIN dim_companies c ON fil.company_id = c.company_id
        JOIN dim_concepts dc ON f.concept_id = dc.concept_id
        WHERE c.ticker = :ticker
          AND EXTRACT(YEAR FROM fil.fiscal_year_end) = :year
          AND f.source = 'SEC_API'
          AND f.dimension_id IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM rel_presentation_hierarchy ph
              WHERE ph.filing_id = f.filing_id
                AND ph.child_concept_id = f.concept_id
          )
    """), {'ticker': ticker, 'year': year})
    
    missing_metadata = result.fetchall()
    if not missing_metadata:
        return
    
    logger.info(f"Populating presentation hierarchy metadata for {len(missing_metadata)} SEC_API facts")
    
    inserted = 0
    for filing_id, concept_id, normalized_label, statement_type in missing_metadata:
        # Try to infer from other years (same company, same concept)
        infer_result = conn.execute(text("""
            SELECT ph.order_index, ph.statement_type, ph.role_uri
            FROM rel_presentation_hierarchy ph
            JOIN dim_filings fil ON ph.filing_id = fil.filing_id
            JOIN dim_companies c ON fil.company_id = c.company_id
            WHERE c.ticker = :ticker
              AND ph.child_concept_id = :concept_id
              AND ph.source = 'xbrl'
              AND ph.order_index IS NOT NULL
              AND ph.order_index < 1000
            ORDER BY fil.fiscal_year_end DESC
            LIMIT 1
        """), {'ticker': ticker, 'concept_id': concept_id})
        
        inferred = infer_result.fetchone()
        
        if inferred:
            # Use inferred order_index and role_uri from other years
            order_index, stmt_type, role_uri = inferred
            stmt_type = stmt_type or statement_type
        else:
            # Use standard template
            template_result = get_template_order(normalized_label, statement_type or 'other')
            if not template_result:
                continue
            _, order_index = template_result
            stmt_type = statement_type or 'other'
            role_uri = None
        
        # Insert presentation hierarchy
        try:
            conn.execute(text("""
                INSERT INTO rel_presentation_hierarchy (
                    filing_id, child_concept_id, order_index,
                    statement_type, role_uri, source, is_synthetic
                ) VALUES (
                    :filing_id, :concept_id, :order_index,
                    :statement_type, :role_uri, 'standard', TRUE
                )
                ON CONFLICT (filing_id, parent_concept_id, child_concept_id, order_index) DO NOTHING
            """), {
                'filing_id': filing_id,
                'concept_id': concept_id,
                'order_index': order_index,
                'statement_type': stmt_type,
                'role_uri': role_uri
            })
            inserted += 1
        except Exception as e:
            logger.debug(f"Failed to insert metadata for {normalized_label}: {e}")
            continue
    
    if inserted > 0:
        conn.commit()
        logger.info(f"✅ Populated presentation hierarchy metadata for {inserted} SEC_API facts")


def run_post_load_gap_filling(
    ticker: str,
    years: List[int],
    taxonomy: str = 'ifrs-full',
    primary_year: Optional[int] = None,
    filing_type: Optional[str] = None
):
    """
    Main entry point for post-load gap filling.

    This should be called AFTER data is loaded to database.

    primary_year/filing_type: identify the filing actually being processed (e.g. NVO's
    FY2024 20-F) — see fill_missing_from_database's docstring for why this must be passed
    through rather than derived from each comparative year in `years`.
    """
    cache_dir = Path(__file__).parent.parent.parent / 'data' / 'raw' / 'sec_api_cache'
    return fill_missing_from_database(ticker, years, taxonomy, cache_dir, primary_year=primary_year, filing_type=filing_type)

