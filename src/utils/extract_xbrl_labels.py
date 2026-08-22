#!/usr/bin/env python3
"""
Extract original XBRL labels from label linkbase and store them in the database.

This script extracts the actual text labels that companies use in their filings
(e.g., "Net sales" for NVO) from the XBRL label linkbase and stores them
so they can be used for validation and display.
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional
from sqlalchemy import create_engine, text
from config import DATABASE_URI

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from arelle import ModelManager, Cntlr
from arelle.ModelDtsObject import ModelConcept


def extract_labels_from_filing(filing_path: Path, model_xbrl) -> Dict[str, str]:
    """
    Extract original labels from XBRL label linkbase.
    
    Args:
        filing_path: Path to XBRL filing
        model_xbrl: Arelle ModelXbrl object (already loaded)
    
    Returns:
        Dictionary mapping concept_name -> label_text
    """
    labels = {}
    
    # Standard label role (most common)
    label_role = "http://www.xbrl.org/2003/role/label"
    
    # Get all concepts from the model
    if not model_xbrl or not hasattr(model_xbrl, 'qnameConcepts'):
        return labels
    
    for qname, concept in model_xbrl.qnameConcepts.items():
        if not concept:
            continue
        
        concept_name = qname.localName if hasattr(qname, 'localName') else str(qname)
        if not concept_name:
            continue
        
        # Try to get label using Arelle's label method
        label_text = None
        try:
            if hasattr(concept, 'label'):
                label_result = concept.label(label_role)
                if label_result:
                    label_text = str(label_result).strip()
        except Exception:
            pass
        
        # Fallback: try genLabel
        if not label_text:
            try:
                if hasattr(concept, 'genLabel'):
                    label_text = str(concept.genLabel).strip() if concept.genLabel else None
            except Exception:
                pass
        
        # Fallback: try label() with different roles
        if not label_text:
            for role in [
                "http://www.xbrl.org/2003/role/label",
                "http://www.xbrl.org/2003/role/verboseLabel",
                "http://www.xbrl.org/2003/role/documentation",
            ]:
                try:
                    if hasattr(concept, 'label'):
                        label_result = concept.label(role)
                        if label_result:
                            label_text = str(label_result).strip()
                            break
                except Exception:
                    continue
        
        if label_text:
            labels[concept_name] = label_text
    
    return labels


def store_labels_in_database(labels: Dict[str, str], filing_id: int, engine):
    """
    Store extracted labels in the database.
    
    We'll add an 'original_label' column to rel_presentation_hierarchy
    or create a new table. For now, let's update dim_concepts with original_label
    if it doesn't already have preferred_label.
    """
    with engine.begin() as conn:
        # First, check if original_label column exists in dim_concepts
        check_column = text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'dim_concepts' 
            AND column_name = 'original_label'
        """)
        result = conn.execute(check_column)
        column_exists = result.fetchone() is not None
        
        if not column_exists:
            # Add original_label column
            conn.execute(text("""
                ALTER TABLE dim_concepts 
                ADD COLUMN original_label VARCHAR(500)
            """))
            conn.commit()
        
        # Get concept_ids for the concepts we have labels for
        concept_names = list(labels.keys())
        if not concept_names:
            return
        
        # Update dim_concepts with original labels
        # Only update if original_label is NULL (preserve existing labels)
        for concept_name, label_text in labels.items():
            # Find concept_id by concept_name
            # Note: concept_name might be in different taxonomies, so we need to handle that
            update_query = text("""
                UPDATE dim_concepts
                SET original_label = :label_text
                WHERE concept_name = :concept_name
                  AND (original_label IS NULL OR original_label = '')
            """)
            conn.execute(update_query, {
                "concept_name": concept_name,
                "label_text": label_text
            })
        
        conn.commit()
        print(f"Stored {len(labels)} labels in database")


def extract_and_store_labels(filing_path: Path, filing_id: int):
    """
    Extract labels from XBRL filing and store in database.
    """
    print(f"Extracting labels from: {filing_path}")
    
    # Load XBRL model using Arelle
    model_manager = ModelManager.initialize(Cntlr.Cntlr())
    controller = Cntlr.Cntlr()
    
    try:
        file_url = filing_path.absolute().as_uri()
        model_xbrl = model_manager.load(file_url)
        
        if not model_xbrl:
            print(f"Failed to load XBRL file: {filing_path}")
            return
        
        # Extract labels
        labels = extract_labels_from_filing(filing_path, model_xbrl)
        print(f"Extracted {len(labels)} labels")
        
        if labels:
            # Store in database
            engine = create_engine(DATABASE_URI)
            store_labels_in_database(labels, filing_id, engine)
            print(f"✅ Successfully stored {len(labels)} labels")
        else:
            print("⚠️  No labels extracted")
            
    except Exception as e:
        print(f"Error extracting labels: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Extract XBRL labels from filing")
    parser.add_argument("filing_path", type=Path, help="Path to XBRL filing")
    parser.add_argument("filing_id", type=int, help="Filing ID in database")
    
    args = parser.parse_args()
    
    extract_and_store_labels(args.filing_path, args.filing_id)

