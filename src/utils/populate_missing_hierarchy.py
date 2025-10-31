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
        4: Statement total (Assets, Revenue, LiabilitiesAndStockholdersEquity)
        3: Section total (LiabilitiesCurrent, AssetsCurrent, RevenueGross)
        2: Subtotal (AccruedLiabilitiesCurrent, AccountsPayableCurrent)
        1: Detail (everything else)
    """
    name_lower = concept_name.lower()
    label_lower = normalized_label.lower()
    
    # Level 4: Statement totals
    statement_totals = [
        'assets', 'revenue', 'liabilitiesandstockholdersequity',
        'stockholdersequity', 'netincome', 'totalassets',
        'totalliabilities', 'totalrevenue'
    ]
    if any(total in name_lower or total in label_lower for total in statement_totals):
        if 'total' in name_lower or 'total' in label_lower:
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
    """Populate hierarchy_level for ALL concepts missing it"""
    
    logger.info("Populating hierarchy_level for ALL concepts...")
    
    with engine.connect() as conn:
        # Get all concepts without hierarchy_level
        result = conn.execute(text("""
        SELECT concept_id, concept_name, normalized_label
        FROM dim_concepts
        WHERE hierarchy_level IS NULL;
        """))
        
        concepts = result.fetchall()
        logger.info(f"Found {len(concepts)} concepts without hierarchy_level")
        
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

