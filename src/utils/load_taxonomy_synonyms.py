#!/usr/bin/env python3
"""
Load Taxonomy-Driven Synonym Mappings

Loads concept labels from taxonomy JSON files and builds synonym mappings.
Concepts with identical labels are considered synonyms (same semantic meaning).
"""
import sys
import json
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from config import DATABASE_URI
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_taxonomy_synonyms(taxonomy_dir: Path, use_semantic_equivalence: bool = True) -> dict:
    """
    Load taxonomy synonyms using semantic equivalence (reference linkbase) or label fallback.
    
    Priority:
    1. Semantic equivalence from reference linkbase (authoritative - same authoritative references)
    2. Label-based synonyms (fallback - same labels)
    
    Returns:
        dict: {concept_name: canonical_concept_name} mapping
    """
    labels_files = list(taxonomy_dir.glob("*/*-labels.json")) + list(taxonomy_dir.glob("*-labels.json"))
    
    if not labels_files:
        logger.warning(f"No taxonomy label files found in {taxonomy_dir}")
        return {}
    
    logger.info(f"Loading synonyms from {len(labels_files)} taxonomy file(s)...")
    
    synonym_mapping = {}
    semantic_equivalence_used = False
    
    # PRIORITY 1: Semantic equivalence from reference linkbase (authoritative)
    if use_semantic_equivalence:
        for labels_file in labels_files:
            logger.info(f"  Loading semantic equivalence from: {labels_file.name}")
            with open(labels_file, 'r') as f:
                data = json.load(f)
            
            semantic_equivalence = data.get('semantic_equivalence', {})
            
            if semantic_equivalence:
                semantic_equivalence_used = True
                logger.info(f"    Found {len(semantic_equivalence)} semantic equivalence groups")
                
                # For each equivalence group, map all concepts to canonical
                for canonical, equivalent_concepts in semantic_equivalence.items():
                    for concept_name in equivalent_concepts:
                        if concept_name != canonical:
                            synonym_mapping[concept_name] = canonical
        
        if semantic_equivalence_used:
            logger.info(f"✅ Built {len(synonym_mapping)} synonym mappings from reference linkbase (semantic equivalence)")
        
        # If no semantic equivalence found, fall through to label-based
    
    # PRIORITY 2: Label-based synonyms (fallback if reference linkbase unavailable)
    if not semantic_equivalence_used:
        logger.info("  Using label-based synonyms (fallback)...")
        
        # Group concepts by label (case-insensitive)
        label_to_concepts = defaultdict(list)
        
        for labels_file in labels_files:
            logger.info(f"  Loading: {labels_file.name}")
            with open(labels_file, 'r') as f:
                data = json.load(f)
            
            concepts = data.get('concepts', [])
            
            for concept in concepts:
                concept_name = concept.get('concept_name')
                label = concept.get('label', '').strip().lower()
                
                if concept_name and label:
                    label_to_concepts[label].append(concept_name)
        
        # Build synonym mappings from labels
        # For each label with multiple concepts, pick shortest as canonical
        for label, concepts_list in label_to_concepts.items():
            if len(concepts_list) > 1:  # Multiple concepts with same label = synonyms
                # Use shortest concept name as canonical (usually most general)
                canonical = min(concepts_list, key=len)
                
                # Map all synonyms to canonical
                for synonym in concepts_list:
                    if synonym != canonical:
                        synonym_mapping[synonym] = canonical
        
        if not semantic_equivalence_used:
            logger.info(f"✅ Built {len(synonym_mapping)} synonym mappings from labels (fallback)")
            logger.info(f"   Synonym groups: {len([g for g in label_to_concepts.values() if len(g) > 1]):,}")
    
    return synonym_mapping


def apply_taxonomy_synonyms_to_db(engine, synonym_mapping: dict):
    """
    Apply taxonomy-driven synonym mappings to dim_concepts.
    
    For concepts that are synonyms (same label), update their normalized_label
    to use the canonical concept's normalized label.
    """
    if not synonym_mapping:
        logger.warning("No synonym mappings provided")
        return 0
    
    logger.info("Applying taxonomy synonyms to database...")
    
    with engine.connect() as conn:
        updated_count = 0
        
        for synonym_concept, canonical_concept in synonym_mapping.items():
            # Find canonical concept's normalized_label
            canonical_result = conn.execute(
                text("""
                    SELECT normalized_label 
                    FROM dim_concepts 
                    WHERE concept_name = :name
                    LIMIT 1
                """),
                {'name': canonical_concept}
            )
            canonical_row = canonical_result.fetchone()
            
            if not canonical_row or not canonical_row[0]:
                continue  # Canonical not in database or not normalized yet
            
            canonical_normalized = canonical_row[0]
            
            # Update synonym to use canonical's normalized label
            result = conn.execute(
                text("""
                    UPDATE dim_concepts
                    SET normalized_label = :normalized
                    WHERE concept_name = :synonym
                      AND normalized_label IS DISTINCT FROM :normalized
                """),
                {
                    'synonym': synonym_concept,
                    'normalized': canonical_normalized
                }
            )
            
            if result.rowcount > 0:
                updated_count += 1
        
        conn.commit()
        
        logger.info(f"✅ Updated {updated_count:,} concepts with taxonomy synonyms")
        return updated_count


def main():
    """Load taxonomy synonyms and apply to database"""
    
    taxonomy_dir = Path(__file__).parent.parent.parent / 'data' / 'taxonomies'
    
    if not taxonomy_dir.exists():
        logger.error(f"Taxonomy directory not found: {taxonomy_dir}")
        logger.error("Run: python src/ingestion/download_taxonomy.py")
        return 1
    
    # Step 1: Load synonym mappings from taxonomy files
    synonym_mapping = load_taxonomy_synonyms(taxonomy_dir)
    
    if not synonym_mapping:
        logger.warning("No synonyms found - this is OK if concepts have unique labels")
        return 0
    
    # Step 2: Apply to database
    engine = create_engine(DATABASE_URI)
    updated = apply_taxonomy_synonyms_to_db(engine, synonym_mapping)
    
    logger.info("\n✅ Taxonomy synonym mapping complete!")
    return 0


if __name__ == '__main__':
    sys.exit(main())

