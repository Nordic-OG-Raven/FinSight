"""
Suggest Mappings from Taxonomy Labels - ONE-TIME DISCOVERY TOOL

This script uses taxonomy labels to suggest mappings for universal metrics.
This is a MANUAL REVIEW tool, not an automatic fix.

Usage:
    python src/utils/suggest_mappings_from_taxonomy_labels.py
    
Output:
    - Prints suggested mappings for manual review
    - These should be manually added to taxonomy_mappings.py after verification
    - NOT integrated into pipeline - this is a development tool
"""

import sys
import json
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Universal metrics and their label keywords
UNIVERSAL_METRIC_KEYWORDS = {
    'noncurrent_liabilities': ['noncurrent', 'non-current', 'long-term', 'liabilit'],
    'current_liabilities': ['current', 'short-term', 'liabilit'],
    'stockholders_equity': ['stockholders', 'shareholders', 'equity', 'owners'],
    'total_assets': ['total', 'assets'],
    'revenue': ['revenue', 'sales', 'revenues'],
    'net_income': ['net', 'income', 'profit', 'loss', 'earnings'],
    'accounts_receivable': ['receivable', 'receivables', 'trade receivable'],
    'accounts_payable': ['payable', 'payables', 'trade payable'],
    'cash_and_equivalents': ['cash', 'equivalents', 'cash and cash equivalents'],
    'operating_cash_flow': ['operating', 'cash', 'flow', 'from operations'],
}


def load_taxonomy_labels(taxonomy_dir: Path) -> dict:
    """Load all taxonomy labels from JSON files."""
    labels_files = list(taxonomy_dir.glob("*/*-labels.json")) + list(taxonomy_dir.glob("*-labels.json"))
    
    all_concepts = {}
    
    for labels_file in labels_files:
        with open(labels_file, 'r') as f:
            data = json.load(f)
        
        for concept in data.get('concepts', []):
            concept_name = concept.get('concept_name')
            label = concept.get('label', '').strip()
            taxonomy = data.get('taxonomy', 'unknown')
            
            if concept_name and label:
                all_concepts[concept_name] = {
                    'label': label,
                    'taxonomy': taxonomy,
                    'qname': concept.get('qname', '')
                }
    
    return all_concepts


def suggest_mappings_for_metric(concepts: dict, metric: str, keywords: list) -> list:
    """
    Find concepts whose labels match keywords for a universal metric.
    Returns: [(concept_name, label, taxonomy, match_score)]
    """
    suggestions = []
    
    label_lower = ' '.join(keywords).lower()
    
    for concept_name, info in concepts.items():
        label = info['label'].lower()
        
        # Check if label contains all or most keywords
        matches = sum(1 for kw in keywords if kw in label)
        match_score = matches / len(keywords)
        
        # Must match at least 60% of keywords
        if match_score >= 0.6:
            # Exclude obvious non-matches
            if metric == 'current_liabilities' and 'noncurrent' in label:
                continue
            if metric == 'noncurrent_liabilities' and 'current' in label and 'noncurrent' not in label:
                continue
            
            suggestions.append((concept_name, info['label'], info['taxonomy'], match_score))
    
    # Sort by match score (highest first)
    suggestions.sort(key=lambda x: x[3], reverse=True)
    return suggestions


def main():
    """Suggest mappings from taxonomy labels for manual review."""
    
    taxonomy_dir = Path(__file__).parent.parent.parent / 'data' / 'taxonomies'
    
    if not taxonomy_dir.exists():
        print(f"❌ Taxonomy directory not found: {taxonomy_dir}")
        print("   Run: python src/ingestion/download_taxonomy.py")
        return 1
    
    print("="*100)
    print("SUGGESTING MAPPINGS FROM TAXONOMY LABELS")
    print("="*100)
    print("\n⚠️  This is a DEVELOPMENT TOOL for manual review.")
    print("   Suggested mappings should be verified and manually added to taxonomy_mappings.py")
    print("   DO NOT auto-apply these - they need accounting standards verification\n")
    
    # Load all taxonomy labels
    concepts = load_taxonomy_labels(taxonomy_dir)
    print(f"✅ Loaded {len(concepts)} concepts from taxonomies\n")
    
    # For each universal metric, suggest mappings
    for metric, keywords in UNIVERSAL_METRIC_KEYWORDS.items():
        suggestions = suggest_mappings_for_metric(concepts, metric, keywords)
        
        if suggestions:
            print(f"\n{'='*100}")
            print(f"{metric.upper()}")
            print(f"{'='*100}")
            print(f"Found {len(suggestions)} potential mappings:\n")
            
            for concept_name, label, taxonomy, score in suggestions[:10]:  # Top 10
                print(f"  Match Score: {score:.1%}")
                print(f"  Concept: {concept_name}")
                print(f"  Label: '{label}'")
                print(f"  Taxonomy: {taxonomy}")
                print(f"  Suggested mapping: '{concept_name}' → '{metric}'")
                print()
        else:
            print(f"{metric}: No suggestions found")
    
    print("\n" + "="*100)
    print("NEXT STEPS:")
    print("="*100)
    print("1. Review suggestions above")
    print("2. Verify against accounting standards (US-GAAP/IFRS)")
    print("3. Manually add verified mappings to src/utils/taxonomy_mappings.py")
    print("4. Re-run normalization and validation")
    print("\n⚠️  DO NOT auto-apply - manual curation is REQUIRED for data quality")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

