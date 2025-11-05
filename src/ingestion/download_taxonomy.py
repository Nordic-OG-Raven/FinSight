#!/usr/bin/env python3
"""
Download US-GAAP and IFRS Taxonomies with Calculation Linkbases

Downloads complete taxonomy packages from FASB and IFRS Foundation.
Extracts calculation relationships to build financial statement hierarchies.
"""
import sys
from pathlib import Path
import zipfile
import tempfile
import urllib.request
import shutil
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from arelle import Cntlr, ModelManager
from arelle import XbrlConst
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def download_and_extract_taxonomy(taxonomy_url, taxonomy_name, output_file, is_zip=False):
    """
    Download taxonomy and extract calculation relationships.
    
    Args:
        taxonomy_url: URL to taxonomy entry point XSD (or ZIP file for ESEF)
        taxonomy_name: Name for logging (e.g., 'US-GAAP-2024', 'IFRS-2024', 'ESEF-2024')
        output_file: Path to save extracted relationships JSON
        is_zip: If True, download as ZIP and extract entry point
        
    Returns:
        Number of relationships extracted
    """
    logger.info(f"Downloading {taxonomy_name} taxonomy...")
    logger.info(f"  URL: {taxonomy_url}")
    logger.info(f"  (First run may take 5-10 minutes to download)")
    
    controller = Cntlr.Cntlr(logFileName="logToBuffer")
    controller.webCache.workOffline = False  # Enable network access
    model_manager = ModelManager.initialize(controller)
    
    # Handle ZIP files (ESEF) - download, extract, find entry point
    actual_taxonomy_url = taxonomy_url
    temp_dir = None
    temp_zip_path = None
    
    try:
        if is_zip:
            logger.info(f"  Downloading ZIP file...")
            # Download ZIP to temp file
            temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
            temp_zip_path = temp_zip.name
            temp_zip.close()
            
            urllib.request.urlretrieve(taxonomy_url, temp_zip_path)
            logger.info(f"  ✅ ZIP downloaded")
            
            # Extract ZIP
            temp_dir = tempfile.mkdtemp()
            with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            logger.info(f"  ✅ ZIP extracted to {temp_dir}")
            
            # Find entry point XSD (look for files ending in -entryPoint-all-*.xsd or similar)
            entry_points = list(Path(temp_dir).rglob('*-entryPoint-all-*.xsd'))
            if not entry_points:
                # Try alternative naming patterns
                entry_points = list(Path(temp_dir).rglob('*entryPoint*.xsd'))
            
            if not entry_points:
                logger.error(f"  ❌ Could not find entry point XSD in ESEF ZIP")
                return 0
            
            # Use the first entry point found (or the 'all' one if available)
            entry_point = None
            for ep in entry_points:
                if 'all' in ep.name.lower():
                    entry_point = ep
                    break
            
            if not entry_point:
                entry_point = entry_points[0]
            
            # Convert to file:// URL for Arelle
            actual_taxonomy_url = entry_point.as_uri()
            logger.info(f"  ✅ Found entry point: {entry_point.name}")
        
        # Load taxonomy (Arelle will download and cache, or use local file)
        taxonomy = model_manager.load(actual_taxonomy_url)
        
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
        
        # Save calculation relationships to JSON
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump({
                'taxonomy': taxonomy_name,
                'taxonomy_url': taxonomy_url,
                'relationships': relationships,
                'relationship_count': len(relationships)
            }, f, indent=2)
        
        logger.info(f"  ✅ Saved calculation relationships to {output_path}")
        
        # ALSO: Extract reference linkbase for semantic equivalence
        logger.info(f"  Extracting reference linkbase for semantic equivalence detection...")
        semantic_equivalence = {}  # authoritative_reference -> list of concept_names
        
        ref_arcrole = 'http://www.xbrl.org/2003/arcrole/concept-reference'
        ref_rels = taxonomy.relationshipSet(ref_arcrole)
        
        if ref_rels:
            logger.info(f"  Reference linkbase found, extracting authoritative references...")
            concept_references = {}  # concept_name -> list of authoritative references
            
            for rel in ref_rels.modelRelationships:
                try:
                    # Get concept and reference
                    concept_obj = rel.fromModelObject
                    ref_obj = rel.toModelObject
                    
                    # Check objects exist (proper way to check, not boolean)
                    if concept_obj is None or ref_obj is None:
                        continue
                    
                    # Get concept name from qname
                    if not hasattr(concept_obj, 'qname'):
                        continue
                    
                    concept_name = concept_obj.qname.localName if concept_obj.qname else None
                    if not concept_name:
                        continue
                    
                    # Extract authoritative reference metadata
                    # Reference resources link concepts to authoritative literature (FASB ASC, IFRS paragraphs)
                    # Concepts with identical reference resources are semantically equivalent
                    # 
                    # Strategy: Use document + XML row to uniquely identify each reference resource
                    # Same reference resource = same authoritative definition
                    ref_key = None
                    
                    # Build unique identifier: document basename + XML row
                    doc_basename = None
                    xml_row = None
                    
                    if hasattr(ref_obj, 'modelDocument') and ref_obj.modelDocument:
                        doc_basename = getattr(ref_obj.modelDocument, 'basename', None)
                    
                    if hasattr(ref_obj, 'xmlRow'):
                        xml_row = ref_obj.xmlRow
                    
                    # Combine document and row for unique reference identifier
                    if doc_basename:
                        if xml_row:
                            ref_key = f"{doc_basename}:{xml_row}"
                        else:
                            # Fallback: use document + object ID if no xmlRow
                            ref_key = f"{doc_basename}:{id(ref_obj)}"
                    elif hasattr(ref_obj, 'modelDocument') and ref_obj.modelDocument:
                        # Use URI if no basename
                        doc_uri = getattr(ref_obj.modelDocument, 'uri', None)
                        if doc_uri:
                            if xml_row:
                                ref_key = f"{doc_uri}:{xml_row}"
                            else:
                                ref_key = f"{doc_uri}:{id(ref_obj)}"
                    
                    # Fallback: Use object ID as last resort
                    if not ref_key:
                        ref_key = str(id(ref_obj))
                    
                    if ref_key:
                        if concept_name not in concept_references:
                            concept_references[concept_name] = []
                        concept_references[concept_name].append(ref_key)
                    
                except Exception as e:
                    logger.debug(f"Error processing reference relationship: {e}")
                    continue
            
            # Group concepts by authoritative references (semantic equivalence)
            # Concepts with identical references are semantically equivalent
            ref_to_concepts = {}  # reference_key -> list of concepts
            
            for concept_name, refs in concept_references.items():
                # Create unique key from all references for this concept
                ref_key = '|'.join(sorted(set(refs))) if refs else None
                
                if ref_key:
                    if ref_key not in ref_to_concepts:
                        ref_to_concepts[ref_key] = []
                    ref_to_concepts[ref_key].append(concept_name)
            
            # Create semantic equivalence groups (concepts sharing same references)
            for ref_key, concepts in ref_to_concepts.items():
                if len(concepts) > 1:  # Multiple concepts with same reference = semantically equivalent
                    # Use shortest concept name as canonical
                    canonical = min(concepts, key=len)
                    semantic_equivalence[canonical] = concepts
            
            logger.info(f"  ✅ Extracted reference linkbase for {len(concept_references)} concepts")
            logger.info(f"  ✅ Found {len(semantic_equivalence)} semantic equivalence groups")
        else:
            logger.warning(f"  No reference linkbase found, will use label linkbase as fallback")
        
        # ALSO: Extract concept labels for synonym mapping (fallback)
        logger.info(f"  Extracting concept labels for synonym detection (fallback)...")
        concepts_with_labels = []
        synonym_groups = {}  # label -> list of concept names
        
        label_role = "http://www.xbrl.org/2003/role/label"
        
        for qname, concept in taxonomy.qnameConcepts.items():
            try:
                concept_name = concept.qname.localName if hasattr(concept, 'qname') else str(qname)
                namespace = concept.qname.namespaceURI if hasattr(concept, 'qname') else None
                
                # Skip abstract/conceptual concepts (they're organizational, not data)
                if hasattr(concept, 'isAbstract') and concept.isAbstract:
                    continue
                
                # Get label
                label = None
                try:
                    if hasattr(concept, 'label'):
                        label_result = concept.label(label_role)
                        if label_result:
                            label = str(label_result).strip()
                except:
                    pass
                
                # Fallback to genLabel
                if not label and hasattr(concept, 'genLabel'):
                    label = str(concept.genLabel).strip() if concept.genLabel else None
                
                # Get definition if available
                definition = None
                try:
                    if hasattr(concept, 'genDefinition'):
                        definition = str(concept.genDefinition).strip() if concept.genDefinition else None
                except:
                    pass
                
                if label:  # Only include concepts with labels
                    concepts_with_labels.append({
                        'concept_name': concept_name,
                        'namespace': namespace,
                        'label': label,
                        'definition': definition,
                        'qname': str(qname)
                    })
                    
                    # Group by label for synonym detection
                    label_key = label.lower().strip()  # Case-insensitive grouping
                    if label_key not in synonym_groups:
                        synonym_groups[label_key] = []
                    synonym_groups[label_key].append(concept_name)
                
            except Exception as e:
                logger.debug(f"Error extracting label for {qname}: {e}")
                continue
        
        logger.info(f"  ✅ Extracted {len(concepts_with_labels)} concepts with labels")
        
        # Find synonym groups (concepts with same label)
        synonyms = {}
        for label_key, concept_names in synonym_groups.items():
            if len(concept_names) > 1:  # Multiple concepts with same label = synonyms
                # Use the shortest concept name as the "canonical" one (usually the most general)
                canonical = min(concept_names, key=len)
                synonyms[canonical] = concept_names
        
        logger.info(f"  ✅ Found {len(synonyms)} synonym groups")
        
        # Save concept labels and synonyms to separate JSON file
        labels_output = output_path.parent / output_path.stem.replace('-calc', '-labels') / output_path.name.replace('-calc.json', '-labels.json')
        labels_output.parent.mkdir(parents=True, exist_ok=True)
        
        with open(labels_output, 'w') as f:
            json.dump({
                'taxonomy': taxonomy_name,
                'taxonomy_url': taxonomy_url,
                'concepts': concepts_with_labels,
                'concept_count': len(concepts_with_labels),
                'synonyms': synonyms,  # Label-based synonyms (fallback)
                'synonym_group_count': len(synonyms),
                'total_synonym_concepts': sum(len(v) for v in synonyms.values()),
                'semantic_equivalence': semantic_equivalence,  # Reference linkbase-based (authoritative)
                'semantic_equivalence_group_count': len(semantic_equivalence),
                'total_equivalent_concepts': sum(len(v) for v in semantic_equivalence.values())
            }, f, indent=2)
        
        logger.info(f"  ✅ Saved concept labels and synonyms to {labels_output}")
        if semantic_equivalence:
            logger.info(f"  ✅ Semantic equivalence groups saved ({len(semantic_equivalence)} groups)")
        
        taxonomy.close()
        controller.close()
        
        return len(relationships)
        
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        controller.close()
        return 0
    
    finally:
        # Clean up temp files (ZIP downloads)
        if temp_dir and Path(temp_dir).exists():
            shutil.rmtree(temp_dir)
            logger.debug(f"  Cleaned up temp directory: {temp_dir}")
        
        if temp_zip_path and Path(temp_zip_path).exists():
            Path(temp_zip_path).unlink()
            logger.debug(f"  Cleaned up temp ZIP: {temp_zip_path}")


def main():

    """Download US-GAAP, IFRS, and ESEF taxonomies"""
    
    taxonomies = [
        # US-GAAP Taxonomies
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
        # IFRS Taxonomies (from IFRS Foundation)
        # Note: IFRS taxonomy URLs may need to be updated if the structure changes
        {
            'url': 'https://xbrl.ifrs.org/taxonomy/2024-01-31/full_ifrs/full_ifrs-entryPoint-all-2024-01-31.xsd',
            'name': 'IFRS-2024',
            'output': 'data/taxonomies/ifrs-2024-calc.json'
        },
        {
            'url': 'https://xbrl.ifrs.org/taxonomy/2023-01-31/full_ifrs/full_ifrs-entryPoint-all-2023-01-31.xsd',
            'name': 'IFRS-2023',
            'output': 'data/taxonomies/ifrs-2023-calc.json'
        },
        # ESEF Taxonomy (European Single Electronic Format - extends IFRS)
        # ESEF typically uses IFRS taxonomy with additional extensions
        {
            'url': 'https://www.esma.europa.eu/sites/default/files/esef_taxonomy_2024.zip',
            'name': 'ESEF-2024',
            'output': 'data/taxonomies/esef-2024-calc.json',
            'is_zip': True  # ESEF comes as a ZIP file, needs special handling
        },
    ]
    
    print('=' * 120)
    print('DOWNLOADING TAXONOMY CALCULATION LINKBASES AND CONCEPT LABELS')
    print('=' * 120)
    print()
    
    total_relationships = 0
    
    for tax in taxonomies:
        is_zip = tax.get('is_zip', False)
        count = download_and_extract_taxonomy(
            tax['url'], 
            tax['name'], 
            tax['output'],
            is_zip=is_zip
        )
        total_relationships += count
        print()
    
    print('=' * 120)
    print(f'✅ COMPLETE: Downloaded {total_relationships} total calculation relationships')
    print('   Also extracted concept labels and synonym mappings for taxonomy-driven normalization')
    print('=' * 120)
    
    return 0 if total_relationships > 0 else 1


if __name__ == '__main__':
    sys.exit(main())

