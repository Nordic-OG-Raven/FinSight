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
from src.utils.logging_utils import truncate_log_message

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
    
    logger.info(truncate_log_message(f"Loading synonyms from {len(labels_files)} file(s)..."))
    
    synonym_mapping = {}
    semantic_equivalence_used = False
    
    # PRIORITY 1: Semantic equivalence from reference linkbase (authoritative)
    if use_semantic_equivalence:
        for labels_file in labels_files:
            logger.debug(truncate_log_message(f"  Loading: {labels_file.name}"))
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
            logger.debug(truncate_log_message(f"✅ Built {len(synonym_mapping)} mappings"))
        
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
    
    logger.debug(truncate_log_message("Applying taxonomy synonyms..."))
    
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
            # CRITICAL: Check if update would create duplicate facts before updating
            # If facts with this concept would conflict with existing facts with the canonical normalized_label,
            # skip the update (the facts are already correct or would violate unique constraint)
            check_conflict = conn.execute(
                text("""
                    SELECT COUNT(*) as conflict_count
                    FROM fact_financial_metrics fm_synonym
                    JOIN dim_concepts dc_synonym ON fm_synonym.concept_id = dc_synonym.concept_id
                    WHERE dc_synonym.concept_name = :synonym
                      AND EXISTS (
                          SELECT 1
                          FROM fact_financial_metrics fm_existing
                          JOIN dim_concepts dc_existing ON fm_existing.concept_id = dc_existing.concept_id
                          WHERE dc_existing.normalized_label = :normalized
                            AND fm_existing.filing_id = fm_synonym.filing_id
                            AND fm_existing.fiscal_year = fm_synonym.fiscal_year
                            AND fm_existing.period_type = fm_synonym.period_type
                            AND (fm_existing.dimension_id = fm_synonym.dimension_id 
                                 OR (fm_existing.dimension_id IS NULL AND fm_synonym.dimension_id IS NULL))
                            AND fm_existing.fact_id != fm_synonym.fact_id
                      )
                """),
                {
                    'synonym': synonym_concept,
                    'normalized': canonical_normalized
                }
            )
            conflict_count = check_conflict.fetchone()[0]
            
            if conflict_count > 0:
                logger.warning(f"Skipping synonym mapping {synonym_concept} → {canonical_normalized}: "
                             f"would create {conflict_count} duplicate fact(s)")
                continue
            
            # Safe to update - no conflicts
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
        
        logger.debug(truncate_log_message(f"✅ Updated {updated_count:,} concepts"))
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

