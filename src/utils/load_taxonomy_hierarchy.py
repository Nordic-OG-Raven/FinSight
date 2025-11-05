#!/usr/bin/env python3
"""
Load Taxonomy-Level Hierarchy Relationships

Loads the US-GAAP taxonomy calculation relationships JSON file into the database
and uses it as the authoritative source for hierarchy levels.

This replaces hard-coded pattern matching with actual taxonomy data.
"""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from config import DATABASE_URI
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_taxonomy_relationships(json_file: str):
    """Load taxonomy relationships from JSON file"""
    
    json_path = Path(json_file)
    if not json_path.exists():
        logger.error(f"Taxonomy file not found: {json_path}")
        return 0
    
    logger.info(f"Loading taxonomy relationships from {json_path}")
    
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    taxonomy_name = data.get('taxonomy', 'US-GAAP')
    relationships = data.get('relationships', [])
    
    logger.info(f"  Found {len(relationships)} relationships in taxonomy '{taxonomy_name}'")
    
    engine = create_engine(DATABASE_URI)
    
    with engine.connect() as conn:
        loaded = 0
        
        for rel in relationships:
            try:
                # Handle namespace prefixes (us-gaap:, ifrs-full:, etc.)
                parent_full = rel.get('parent_concept', '')
                child_full = rel.get('child_concept', '')
                
                # Remove namespace prefixes (e.g., "us-gaap:Revenue" -> "Revenue")
                parent_name = parent_full.split(':')[-1] if ':' in parent_full else parent_full
                child_name = child_full.split(':')[-1] if ':' in child_full else child_full
                
                weight = rel.get('weight', 1.0)
                order_index = rel.get('order')
                
                if not parent_name or not child_name:
                    continue
                
                # Find concept IDs by name (match any taxonomy variant)
                # This works for US-GAAP, IFRS, and other frameworks
                parent_result = conn.execute(text("""
                    SELECT concept_id FROM dim_concepts
                    WHERE concept_name = :name
                    LIMIT 1
                """), {'name': parent_name})
                parent_row = parent_result.fetchone()
                
                child_result = conn.execute(text("""
                    SELECT concept_id FROM dim_concepts
                    WHERE concept_name = :name
                    LIMIT 1
                """), {'name': child_name})
                child_row = child_result.fetchone()
                
                # If both concepts exist, update parent_concept_id directly
                # This is taxonomy-authoritative, so we can set it directly on dim_concepts
                if parent_row and child_row:
                    parent_id = parent_row[0]
                    child_id = child_row[0]
                    
                    # Update dim_concepts with taxonomy-based parent relationship
                    # Only update if not already set from taxonomy, or override if from pattern matching
                    result = conn.execute(text("""
                        UPDATE dim_concepts
                        SET parent_concept_id = :parent_id,
                            calculation_weight = :weight
                        WHERE concept_id = :child_id
                          AND (
                              parent_concept_id IS NULL 
                              OR concept_id NOT IN (
                                  SELECT DISTINCT parent_concept_id 
                                  FROM rel_calculation_hierarchy 
                                  WHERE filing_id > 0  -- Has filing-level relationship
                              )
                          );
                    """), {
                        'parent_id': parent_id,
                        'child_id': child_id,
                        'weight': weight
                    })
                    
                    if result.rowcount > 0:
                        loaded += 1
                    
            except Exception as e:
                logger.debug(f"Error processing relationship {rel}: {e}")
                continue
        
        conn.commit()
        logger.info(f"  ✅ Loaded {loaded} taxonomy relationships into database")
        
        return loaded


def infer_hierarchy_from_taxonomy(engine):
    """
    Infer hierarchy levels from taxonomy relationships (data-driven).
    
    Uses actual parent-child relationships from US-GAAP taxonomy that we just loaded:
    - Level 4: Statement totals (no parent in taxonomy)
    - Level 3: Universal metrics (parents exist, commonly reported)
    - Level 2: Subtotals (has parent and children)
    - Level 1: Details (has parent, no children)
    """
    logger.info("Inferring hierarchy levels from taxonomy relationships...")
    
    with engine.connect() as conn:
        # Infer hierarchy levels based on taxonomy tree structure (parent_concept_id we just set)
        
        # Level 4: Top-level concepts (no parent in taxonomy)
        result = conn.execute(text("""
            UPDATE dim_concepts
            SET hierarchy_level = 4
            WHERE parent_concept_id IS NULL
              AND concept_id IN (
                  SELECT DISTINCT parent_concept_id 
                  FROM dim_concepts 
                  WHERE parent_concept_id IS NOT NULL
              );
        """))
        logger.info(f"  ✅ Set {result.rowcount} concepts to Level 4 (statement totals)")
        conn.commit()
        
        # Level 1: Leaf nodes (has parent, not a parent to anyone)
        result = conn.execute(text("""
            UPDATE dim_concepts
            SET hierarchy_level = 1
            WHERE parent_concept_id IS NOT NULL
              AND concept_id NOT IN (
                  SELECT DISTINCT parent_concept_id 
                  FROM dim_concepts 
                  WHERE parent_concept_id IS NOT NULL
              );
        """))
        logger.info(f"  ✅ Set {result.rowcount} concepts to Level 1 (detail items)")
        conn.commit()
        
        # Level 2: Has parent AND is a parent (intermediate subtotals)
        result = conn.execute(text("""
            UPDATE dim_concepts dc
            SET hierarchy_level = 2
            WHERE dc.parent_concept_id IS NOT NULL
              AND dc.concept_id IN (
                  SELECT DISTINCT parent_concept_id 
                  FROM dim_concepts 
                  WHERE parent_concept_id IS NOT NULL
              )
              AND (SELECT hierarchy_level FROM dim_concepts WHERE concept_id = dc.parent_concept_id) = 4;
        """))
        logger.info(f"  ✅ Set {result.rowcount} concepts to Level 2 (subtotals)")
        conn.commit()
        
        # Level 3: Universal metrics (children of level 2, or direct children of level 4 that are also parents)
        result = conn.execute(text("""
            UPDATE dim_concepts dc
            SET hierarchy_level = 3
            WHERE dc.parent_concept_id IS NOT NULL
              AND (
                  (SELECT hierarchy_level FROM dim_concepts WHERE concept_id = dc.parent_concept_id) IN (2, 3)
                  OR (
                      dc.concept_id IN (
                          SELECT DISTINCT parent_concept_id 
                          FROM dim_concepts 
                          WHERE parent_concept_id IS NOT NULL
                      )
                      AND (SELECT hierarchy_level FROM dim_concepts WHERE concept_id = dc.parent_concept_id) = 4
                  )
              )
              AND dc.hierarchy_level IS NULL;
        """))
        logger.info(f"  ✅ Set {result.rowcount} concepts to Level 3 (section totals/universal metrics)")
        conn.commit()
        
        # Show distribution
        result = conn.execute(text("""
            SELECT hierarchy_level, COUNT(*) 
            FROM dim_concepts
            WHERE hierarchy_level IS NOT NULL
            GROUP BY hierarchy_level
            ORDER BY hierarchy_level;
        """))
        
        logger.info("\n  Hierarchy level distribution:")
        for row in result:
            level_name = {1: 'Detail', 2: 'Subtotal', 3: 'Section/Universal', 4: 'Statement Total'}.get(row[0], 'Unknown')
            logger.info(f"    Level {row[0]} ({level_name}): {row[1]} concepts")


def main():
    """Load taxonomy relationships and infer hierarchy levels"""
    
    taxonomy_dir = Path(__file__).parent.parent.parent / 'data' / 'taxonomies'
    
    # Find all taxonomy JSON files
    taxonomy_files = list(taxonomy_dir.glob('*-calc.json'))
    
    if not taxonomy_files:
        logger.error(f"No taxonomy files found in {taxonomy_dir}")
        logger.error("Run: python src/ingestion/download_taxonomy.py")
        return 1
    
    logger.info(f"Found {len(taxonomy_files)} taxonomy file(s)")
    
    engine = create_engine(DATABASE_URI)
    total_loaded = 0
    
    # Step 1: Load ALL taxonomy relationships (US-GAAP, IFRS, etc.)
    for taxonomy_file in taxonomy_files:
        logger.info(f"\nProcessing: {taxonomy_file.name}")
        loaded = load_taxonomy_relationships(str(taxonomy_file))
        total_loaded += loaded
    
    if total_loaded == 0:
        logger.warning("No taxonomy relationships loaded. Hierarchy levels may be incomplete.")
        return 1
    
    # Step 2: Infer hierarchy levels from taxonomy data (works for all taxonomies)
    logger.info("\n" + "="*80)
    logger.info("INFERRING HIERARCHY LEVELS FROM TAXONOMY DATA")
    logger.info("="*80)
    infer_hierarchy_from_taxonomy(engine)
    
    logger.info("\n✅ Taxonomy-driven hierarchy population complete!")
    logger.info(f"   Loaded {total_loaded} relationships from {len(taxonomy_files)} taxonomy file(s)")
    logger.info("   Hierarchy levels now derived from actual taxonomy relationships")
    logger.info("   (Data-driven, not pattern-matched)")
    logger.info("   Supports: US-GAAP, IFRS, and other XBRL frameworks")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())

