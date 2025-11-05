#!/usr/bin/env python3
"""
Generate SUGGESTIONS for universal metric mappings (NOT auto-apply).

This script:
1. Uses downloaded taxonomy linkbases (authoritative source)
2. Analyzes multi-company usage patterns (statistical)
3. Generates a REVIEWABLE report
4. Requires explicit approval before applying

SAFETY: This is a SUGGESTION engine, not an auto-mapper.
"""
import sys
from pathlib import Path
from typing import Dict, List, Tuple
from sqlalchemy import create_engine, text
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import DATABASE_URI


def analyze_taxonomy_hierarchy(engine):
    """Use taxonomy linkbases to identify parent concepts (likely totals)"""
    suggestions = {}
    
    with engine.connect() as conn:
        # Get concepts that are parents in calculation relationships
        # These are likely "total" concepts (universal metrics)
        result = conn.execute(text("""
            SELECT DISTINCT
                dc_parent.concept_name as parent_concept,
                dc_parent.normalized_label as parent_label,
                COUNT(DISTINCT rch.child_concept_id) as child_count,
                COUNT(DISTINCT c.ticker) as company_count
            FROM rel_calculation_hierarchy rch
            JOIN dim_concepts dc_parent ON rch.parent_concept_id = dc_parent.concept_id
            LEFT JOIN fact_financial_metrics f ON f.concept_id = dc_parent.concept_id
            LEFT JOIN dim_companies c ON f.company_id = c.company_id
            WHERE rch.source = 'xbrl'  -- Only from authoritative taxonomy
              AND f.dimension_id IS NULL
            GROUP BY dc_parent.concept_name, dc_parent.normalized_label
            HAVING COUNT(DISTINCT c.ticker) >= 8  -- Used by 8+ companies
            ORDER BY company_count DESC, child_count DESC
            LIMIT 50
        """))
        
        for row in result:
            parent_concept = row[0]
            parent_label = row[1]
            child_count = row[2]
            company_count = row[3]
            
            if parent_label not in suggestions:
                suggestions[parent_label] = {
                    'concept': parent_concept,
                    'confidence': 'high' if company_count >= 10 else 'medium',
                    'companies': company_count,
                    'children': child_count,
                    'source': 'taxonomy_hierarchy'
                }
    
    return suggestions


def analyze_multi_company_usage(engine):
    """Find concepts used by 80%+ of companies (likely universal)"""
    suggestions = {}
    
    with engine.connect() as conn:
        # Get total company count
        result = conn.execute(text("SELECT COUNT(*) FROM dim_companies WHERE ticker != 'TAXONOMY'"))
        total_companies = result.fetchone()[0]
        threshold = int(total_companies * 0.8)  # 80% threshold
        
        # Find concepts used by most companies
        result = conn.execute(text("""
            SELECT DISTINCT
                dc.concept_name,
                dc.normalized_label,
                COUNT(DISTINCT c.ticker) as company_count,
                COUNT(DISTINCT f.fact_id) as fact_count
            FROM fact_financial_metrics f
            JOIN dim_companies c ON f.company_id = c.company_id
            JOIN dim_concepts dc ON f.concept_id = dc.concept_id
            WHERE f.dimension_id IS NULL
              AND dc.normalized_label IS NOT NULL
              AND dc.concept_name NOT LIKE '%Note%'
              AND dc.concept_name NOT LIKE '%Policy%'
              AND dc.concept_name NOT LIKE '%Disclosure%'
              AND dc.concept_name NOT LIKE '%TextBlock%'
              AND dc.concept_name NOT LIKE 'Abstract%'
            GROUP BY dc.concept_name, dc.normalized_label
            HAVING COUNT(DISTINCT c.ticker) >= :threshold
            ORDER BY company_count DESC, fact_count DESC
        """), {'threshold': threshold})
        
        for row in result:
            concept = row[0]
            label = row[1]
            company_count = row[2]
            fact_count = row[3]
            
            if label not in suggestions:
                suggestions[label] = {
                    'concept': concept,
                    'confidence': 'high',
                    'companies': company_count,
                    'facts': fact_count,
                    'source': 'multi_company_usage'
                }
    
    return suggestions


def find_unmapped_alternatives(engine):
    """Find concepts that match universal metric patterns but aren't mapped"""
    universal_patterns = {
        'revenue': ['Revenue', 'Revenues', 'Sales'],
        'net_income': ['NetIncome', 'ProfitLoss', 'Earnings'],
        'operating_income': ['OperatingIncome', 'OperatingProfit', 'OperatingEarnings'],
        'total_assets': ['Assets', 'TotalAssets'],
        'total_liabilities': ['Liabilities', 'TotalLiabilities'],
        'stockholders_equity': ['Equity', 'Stockholders', 'Shareholders'],
        'current_assets': ['CurrentAssets', 'AssetsCurrent'],
        'current_liabilities': ['CurrentLiabilities', 'LiabilitiesCurrent'],
        'cash_and_equivalents': ['Cash', 'CashEquivalents'],
        'accounts_receivable': ['Receivables', 'AccountsReceivable', 'TradeReceivables'],
        'accounts_payable': ['Payables', 'AccountsPayable', 'TradePayables'],
        'operating_cash_flow': ['OperatingCash', 'CashFlow', 'CashFromOperating'],
    }
    
    suggestions = {}
    
    with engine.connect() as conn:
        for target_label, patterns in universal_patterns.items():
            # Check current coverage
            result = conn.execute(text("""
                SELECT COUNT(DISTINCT c.ticker) as company_count
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                WHERE dc.normalized_label = :target_label
                  AND f.dimension_id IS NULL
            """), {'target_label': target_label})
            
            current_coverage = result.fetchone()[0] or 0
            total_companies = 11
            
            if current_coverage < total_companies:
                # Find unmapped alternatives
                pattern_sql = ' OR '.join([f"dc.concept_name LIKE '%{p}%'" for p in patterns])
                
                result = conn.execute(text(f"""
                    SELECT DISTINCT
                        dc.concept_name,
                        dc.normalized_label,
                        COUNT(DISTINCT c.ticker) as company_count
                    FROM dim_concepts dc
                    JOIN fact_financial_metrics f ON dc.concept_id = f.concept_id
                    JOIN dim_companies c ON f.company_id = c.company_id
                    WHERE ({pattern_sql})
                      AND dc.normalized_label != :target_label
                      AND f.dimension_id IS NULL
                      AND dc.concept_name NOT LIKE '%Note%'
                      AND dc.concept_name NOT LIKE '%Policy%'
                      AND dc.concept_name NOT LIKE '%Disclosure%'
                      AND dc.concept_name NOT LIKE '%TextBlock%'
                      AND dc.concept_name NOT LIKE '%Table%'
                      AND dc.concept_name NOT LIKE 'Abstract%'
                    GROUP BY dc.concept_name, dc.normalized_label
                    HAVING COUNT(DISTINCT c.ticker) >= 3
                    ORDER BY company_count DESC
                    LIMIT 10
                """), {'target_label': target_label})
                
                for row in result:
                    key = f"{target_label}|{row[0]}"
                    suggestions[key] = {
                        'target_label': target_label,
                        'concept_name': row[0],
                        'current_label': row[1],
                        'companies': row[2],
                        'confidence': 'medium' if row[2] >= 6 else 'low',
                        'source': 'pattern_match',
                        'missing_companies': total_companies - current_coverage
                    }
    
    return suggestions


def main():
    """Generate mapping suggestions (REVIEW ONLY, NOT AUTO-APPLY)"""
    engine = create_engine(DATABASE_URI)
    
    print("="*100)
    print("GENERATING UNIVERSAL METRIC MAPPING SUGGESTIONS")
    print("="*100)
    print("\n⚠️  THIS IS A SUGGESTION ENGINE - NOT AUTO-APPLYING CHANGES")
    print("   Review all suggestions before applying.\n")
    
    all_suggestions = {}
    
    # 1. Taxonomy hierarchy analysis (authoritative)
    print("📊 Analyzing taxonomy hierarchies...")
    taxonomy_suggestions = analyze_taxonomy_hierarchy(engine)
    all_suggestions.update(taxonomy_suggestions)
    print(f"   Found {len(taxonomy_suggestions)} suggestions from taxonomy")
    
    # 2. Multi-company usage analysis (statistical)
    print("\n📊 Analyzing multi-company usage patterns...")
    usage_suggestions = analyze_multi_company_usage(engine)
    all_suggestions.update(usage_suggestions)
    print(f"   Found {len(usage_suggestions)} high-usage concepts")
    
    # 3. Unmapped alternatives (pattern matching)
    print("\n📊 Finding unmapped alternatives...")
    unmapped_suggestions = find_unmapped_alternatives(engine)
    all_suggestions.update(unmapped_suggestions)
    print(f"   Found {len(unmapped_suggestions)} unmapped alternatives")
    
    # Generate report
    print("\n" + "="*100)
    print("MAPPING SUGGESTIONS REPORT")
    print("="*100)
    
    # Group by confidence
    high_confidence = [s for s in all_suggestions.values() if s.get('confidence') == 'high']
    medium_confidence = [s for s in all_suggestions.values() if s.get('confidence') == 'medium']
    low_confidence = [s for s in all_suggestions.values() if s.get('confidence') == 'low']
    
    print(f"\n🔴 HIGH CONFIDENCE ({len(high_confidence)} suggestions):")
    print("   These are SAFE to apply - from authoritative sources or 10+ companies")
    for sug in sorted(high_confidence, key=lambda x: x.get('companies', 0), reverse=True)[:20]:
        if 'target_label' in sug:
            print(f"   → Map '{sug['concept_name']}' → '{sug['target_label']}' ({sug['companies']} companies, {sug.get('missing_companies', 0)} missing)")
        else:
            print(f"   → '{sug.get('concept', 'N/A')}' is universal ({sug.get('companies', 0)} companies)")
    
    print(f"\n🟡 MEDIUM CONFIDENCE ({len(medium_confidence)} suggestions):")
    print("   REVIEW CAREFULLY - may need manual verification")
    for sug in sorted(medium_confidence, key=lambda x: x.get('companies', 0), reverse=True)[:15]:
        if 'target_label' in sug:
            print(f"   → Map '{sug['concept_name']}' → '{sug['target_label']}' ({sug['companies']} companies, {sug.get('missing_companies', 0)} missing)")
        else:
            print(f"   → '{sug.get('concept', 'N/A')}' ({sug.get('companies', 0)} companies)")
    
    print(f"\n🟢 LOW CONFIDENCE ({len(low_confidence)} suggestions):")
    print("   MANUAL REVIEW REQUIRED - high risk of errors")
    print(f"   (Skipping display - too many low-confidence suggestions)")
    
    # Save to JSON for review
    output_file = Path(__file__).parent.parent.parent / "data" / "mapping_suggestions.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w') as f:
        json.dump(all_suggestions, f, indent=2, default=str)
    
    print(f"\n✅ Suggestions saved to: {output_file}")
    print("\n⚠️  NEXT STEPS:")
    print("   1. Review suggestions in the JSON file")
    print("   2. Manually add HIGH CONFIDENCE mappings to taxonomy_mappings.py")
    print("   3. Re-run normalization")
    print("   4. Validate results")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())

