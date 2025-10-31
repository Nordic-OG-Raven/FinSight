#!/usr/bin/env python3
"""
Download US-GAAP and IFRS Taxonomies with Calculation Linkbases

Downloads complete taxonomy packages from FASB and IFRS Foundation.
Extracts calculation relationships to build financial statement hierarchies.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from arelle import Cntlr, ModelManager
from arelle import XbrlConst
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def download_and_extract_taxonomy(taxonomy_url, taxonomy_name, output_file):
    """
    Download taxonomy and extract calculation relationships.
    
    Args:
        taxonomy_url: URL to taxonomy entry point XSD
        taxonomy_name: Name for logging (e.g., 'US-GAAP-2024')
        output_file: Path to save extracted relationships JSON
        
    Returns:
        Number of relationships extracted
    """
    logger.info(f"Downloading {taxonomy_name} taxonomy...")
    logger.info(f"  URL: {taxonomy_url}")
    logger.info(f"  (First run may take 5-10 minutes to download)")
    
    controller = Cntlr.Cntlr(logFileName="logToBuffer")
    controller.webCache.workOffline = False  # Enable network access
    model_manager = ModelManager.initialize(controller)
    
    try:
        # Load taxonomy (Arelle will download and cache)
        taxonomy = model_manager.load(taxonomy_url)
        
        if not taxonomy:
            logger.error(f"Failed to load {taxonomy_name}")
            return 0
        
        logger.info(f"  ✅ Taxonomy loaded")
        
        # Extract calculation relationships
        calc_arcrole = 'http://www.xbrl.org/2003/arcrole/summation-item'
        calc_rels = taxonomy.relationshipSet(calc_arcrole)
        
        if not calc_rels:
            logger.warning(f"  No calculation relationships found")
            return 0
        
        relationships = []
        processed_pairs = set()  # Prevent duplicates
        
        for rel in calc_rels.modelRelationships:
            try:
                # Get parent and child concept names
                parent_qname = rel.fromModelObject.qname
                child_qname = rel.toModelObject.qname
                
                if not parent_qname or not child_qname:
                    continue
                
                # Extract local name (remove namespace)
                parent_name = str(parent_qname).split('}')[1] if '}' in str(parent_qname) else str(parent_qname)
                child_name = str(child_qname).split('}')[1] if '}' in str(child_qname) else str(child_qname)
                
                # Get weight (1.0 for addition, -1.0 for subtraction)
                weight = float(rel.weight) if hasattr(rel, 'weight') else 1.0
                
                # Get order (for display ordering)
                order = float(rel.order) if hasattr(rel, 'order') else None
                
                # Create unique key
                pair_key = (parent_name, child_name)
                if pair_key in processed_pairs:
                    continue
                processed_pairs.add(pair_key)
                
                relationships.append({
                    'parent_concept': parent_name,
                    'child_concept': child_name,
                    'weight': weight,
                    'order': order,
                    'arcrole': calc_arcrole,
                    'taxonomy': taxonomy_name
                })
                
            except Exception as e:
                logger.debug(f"Error processing relationship: {e}")
                continue
        
        logger.info(f"  ✅ Extracted {len(relationships)} calculation relationships")
        
        # Save to JSON
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump({
                'taxonomy': taxonomy_name,
                'taxonomy_url': taxonomy_url,
                'relationships': relationships,
                'relationship_count': len(relationships)
            }, f, indent=2)
        
        logger.info(f"  ✅ Saved to {output_path}")
        
        taxonomy.close()
        controller.close()
        
        return len(relationships)
        
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        controller.close()
        return 0


def main():
    """Download both US-GAAP and IFRS taxonomies"""
    
    taxonomies = [
        {
            'url': 'https://xbrl.fasb.org/us-gaap/2024/entire/us-gaap-entryPoint-all-2024.xsd',
            'name': 'US-GAAP-2024',
            'output': 'data/taxonomies/us-gaap-2024-calc.json'
        },
        {
            'url': 'https://xbrl.fasb.org/us-gaap/2023/entire/us-gaap-entryPoint-all-2023.xsd',
            'name': 'US-GAAP-2023',
            'output': 'data/taxonomies/us-gaap-2023-calc.json'
        },
    ]
    
    print('=' * 120)
    print('DOWNLOADING TAXONOMY CALCULATION LINKBASES')
    print('=' * 120)
    print()
    
    total_relationships = 0
    
    for tax in taxonomies:
        count = download_and_extract_taxonomy(tax['url'], tax['name'], tax['output'])
        total_relationships += count
        print()
    
    print('=' * 120)
    print(f'✅ COMPLETE: Downloaded {total_relationships} total calculation relationships')
    print('=' * 120)
    
    return 0 if total_relationships > 0 else 1


if __name__ == '__main__':
    sys.exit(main())

