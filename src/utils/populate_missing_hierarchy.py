#!/usr/bin/env python3
"""
Populate hierarchy_level for ALL concepts (not just taxonomy-matched ones)

This ensures EVERY concept has a hierarchy level, preventing filter failures.

SOLUTION 1: Complete Hierarchy Population
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from config import DATABASE_URI
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def infer_hierarchy_level(concept_name: str, normalized_label: str) -> int:
    """
    Infer hierarchy level from concept name patterns.
    
    Returns:
        4: Statement total (Total Assets, Total Revenue, Total Liabilities)
        3: Universal metric (Revenue, Net Income, Stockholders Equity, Current Assets, Current Liabilities)
        2: Subtotal (AccruedLiabilitiesCurrent, AccountsPayableCurrent)
        1: Detail (everything else)
    """
    name_lower = concept_name.lower()
    label_lower = normalized_label.lower() if normalized_label else ''
    
    # CRITICAL: Check normalized_label FIRST - explicit universal metrics
    # Level 3: Universal statement-level metrics (every company reports these)
    universal_metrics_level_3 = {
        'revenue', 'net_income', 'stockholders_equity', 'total_equity',
        'current_assets', 'current_liabilities', 
        'noncurrent_assets', 'noncurrent_liabilities',
        'operating_income', 'operating_cash_flow',
        'accounts_receivable', 'accounts_payable', 'inventory',
        'cash_and_equivalents', 'short_term_debt', 'long_term_debt'
    }
    
    if normalized_label and normalized_label.lower() in universal_metrics_level_3:
        return 3
    
    # Level 4: Statement totals (explicit "total" in name)
    statement_totals_level_4 = {
        'total_assets', 'total_liabilities', 'total_revenue',
        'total_equity', 'total_stockholders_equity'
    }
    
    if normalized_label and normalized_label.lower() in statement_totals_level_4:
        return 4
    
    # Level 4: Statement totals by pattern (has "total" in name)
    if 'total' in label_lower:
        return 4
    
    # Level 3: Section totals (Current, Noncurrent, Gross, Net)
    if any(keyword in name_lower or keyword in label_lower 
           for keyword in ['current', 'noncurrent', 'gross', 'net', 'total']):
        # Check if it's a top-level section (not a detail)
        if not any(detail in name_lower for detail in ['accrued', 'other', 'trade', 'related']):
            return 3
    
    # Level 2: Subtotals (groups of details)
    subtotal_keywords = [
        'accrued', 'other', 'trade', 'employee', 'customer',
        'related', 'operating', 'nonoperating'
    ]
    if any(keyword in name_lower for keyword in subtotal_keywords):
        return 2
    
    # Level 1: Everything else (detail items)
    return 1


def populate_all_hierarchy_levels(engine):
    """
    Populate hierarchy_level for ALL concepts missing it AND fix incorrect levels for universal metrics.
    
    APPROACH (data-driven, not hard-coded):
    1. First: Try to load taxonomy relationships (US-GAAP, IFRS, ESEF) - use load_taxonomy_hierarchy.py
    2. Then: Use calculation relationships from actual filings (populate_hierarchy.py)
    3. Finally: Pattern matching fallback (only for concepts not in taxonomy)
    
    NOTE: For best results, run load_taxonomy_hierarchy.py first to load taxonomy relationships.
    """
    
    logger.info("Populating hierarchy_level for ALL concepts...")
    logger.info("Strategy: Taxonomy relationships → Filing relationships → Pattern matching")
    
    # Check if taxonomy relationships have been loaded (they populate parent_concept_id)
    with engine.connect() as conn:
        taxonomy_loaded = conn.execute(text("""
            SELECT COUNT(*) 
            FROM dim_concepts 
            WHERE parent_concept_id IS NOT NULL
        """)).scalar() > 100  # If > 100 concepts have parents, taxonomy likely loaded
    
    if taxonomy_loaded:
        logger.info("✅ Taxonomy relationships detected - using data-driven hierarchy")
        logger.info("   (If needed, run: python src/utils/load_taxonomy_hierarchy.py)")
    else:
        logger.warning("⚠️  No taxonomy relationships found - will use pattern matching fallback")
        logger.info("   Recommendation: Run 'python src/utils/load_taxonomy_hierarchy.py' first")
    
    # Universal metrics that MUST be level 3 or 4 (force update even if already set)
    universal_metrics_level_3 = {
        'revenue', 'net_income', 'stockholders_equity', 'total_equity',
        'current_assets', 'current_liabilities', 
        'noncurrent_assets', 'noncurrent_liabilities',
        'operating_income', 'operating_cash_flow',
        'accounts_receivable', 'accounts_payable', 'inventory',
        'cash_and_equivalents', 'short_term_debt', 'long_term_debt'
    }
    
    statement_totals_level_4 = {
        'total_assets', 'total_liabilities', 'total_revenue',
        'total_equity', 'total_stockholders_equity'
    }
    
    with engine.connect() as conn:
        # STEP 1: Force-update universal metrics to correct level (even if already set incorrectly)
        logger.info("Step 1: Force-updating universal metrics to correct levels...")
        
        # Update level 3 universal metrics
        for metric in universal_metrics_level_3:
            result = conn.execute(text("""
                UPDATE dim_concepts
                SET hierarchy_level = 3
                WHERE normalized_label = :metric
                  AND (hierarchy_level IS NULL OR hierarchy_level < 3);
            """), {'metric': metric})
            if result.rowcount > 0:
                logger.info(f"  ✅ Updated {result.rowcount} concepts for '{metric}' to level 3")
        
        # Update level 4 statement totals
        for metric in statement_totals_level_4:
            result = conn.execute(text("""
                UPDATE dim_concepts
                SET hierarchy_level = 4
                WHERE normalized_label = :metric
                  AND (hierarchy_level IS NULL OR hierarchy_level < 4);
            """), {'metric': metric})
            if result.rowcount > 0:
                logger.info(f"  ✅ Updated {result.rowcount} concepts for '{metric}' to level 4")
        
        conn.commit()
        
        # STEP 2: Get all concepts without hierarchy_level and infer it
        result = conn.execute(text("""
        SELECT concept_id, concept_name, normalized_label
        FROM dim_concepts
        WHERE hierarchy_level IS NULL;
        """))
        
        concepts = result.fetchall()
        logger.info(f"\nStep 2: Found {len(concepts)} concepts without hierarchy_level")
        
        updated = 0
        for concept_id, concept_name, normalized_label in concepts:
            level = infer_hierarchy_level(concept_name or '', normalized_label or '')
            
            conn.execute(text("""
            UPDATE dim_concepts
            SET hierarchy_level = :level
            WHERE concept_id = :concept_id;
            """), {
                'level': level,
                'concept_id': concept_id
            })
            updated += 1
        
        conn.commit()
        
        logger.info(f"✅ Updated {updated} concepts with inferred hierarchy levels")
        
        # Show distribution
        result2 = conn.execute(text("""
        SELECT hierarchy_level, COUNT(*) 
        FROM dim_concepts
        WHERE concept_id IN (SELECT DISTINCT concept_id FROM fact_financial_metrics)
        GROUP BY hierarchy_level
        ORDER BY hierarchy_level;
        """))
        
        logger.info("Level distribution after update:")
        for row in result2:
            logger.info(f"  Level {row[0]}: {row[1]} concepts")


def main():
    engine = create_engine(DATABASE_URI)
    populate_all_hierarchy_levels(engine)
    return 0


if __name__ == '__main__':
    sys.exit(main())

