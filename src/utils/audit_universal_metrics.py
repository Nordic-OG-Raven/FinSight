#!/usr/bin/env python3
"""
Comprehensive audit of universal metrics - find ALL problems systematically.
"""
import sys
from pathlib import Path
from sqlalchemy import create_engine, text
import json

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import DATABASE_URI


UNIVERSAL_METRICS = {
    # INCOME STATEMENT
    'revenue': 'Total revenue/sales',
    'cost_of_revenue': 'Cost of goods sold/services',
    'gross_profit': 'Revenue - Cost of revenue',
    'operating_income': 'Income from operations',
    'net_income': 'Bottom line profit',
    
    # BALANCE SHEET - ASSETS
    'total_assets': 'Total assets',
    'current_assets': 'Current assets',
    'cash_and_equivalents': 'Cash on hand',
    'accounts_receivable': 'Money owed by customers',
    'inventory': 'Goods for sale',
    'property_plant_equipment': 'PP&E',
    
    # BALANCE SHEET - LIABILITIES
    'total_liabilities': 'Total liabilities',
    'current_liabilities': 'Current liabilities',
    'accounts_payable': 'Money owed to suppliers',
    'long_term_debt': 'Long-term debt',
    
    # BALANCE SHEET - EQUITY
    'stockholders_equity': 'Shareholders equity',
    
    # CASH FLOW
    'operating_cash_flow': 'Cash from operations',
    'investing_cash_flow': 'Cash from investing',
    'financing_cash_flow': 'Cash from financing',
}


def audit_all_metrics():
    engine = create_engine(DATABASE_URI)
    
    with engine.connect() as conn:
        # Get all companies
        result = conn.execute(text("SELECT ticker FROM dim_companies WHERE ticker != 'TAXONOMY' ORDER BY ticker"))
        all_companies = [row[0] for row in result]
        total_companies = len(all_companies)
        
        print("="*120)
        print("COMPREHENSIVE UNIVERSAL METRICS AUDIT")
        print("="*120)
        print(f"\nTotal companies: {total_companies}")
        print(f"Companies: {', '.join(all_companies)}")
        print("\n")
        
        problems = []
        
        for metric, description in UNIVERSAL_METRICS.items():
            # Check coverage
            result = conn.execute(text('''
                SELECT COUNT(DISTINCT c.ticker) as company_count
                FROM fact_financial_metrics f
                JOIN dim_companies c ON f.company_id = c.company_id
                JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                WHERE dc.normalized_label = :metric
                  AND f.dimension_id IS NULL
            '''), {'metric': metric})
            
            company_count = result.fetchone()[0] or 0
            missing_count = total_companies - company_count
            
            if missing_count > 0:
                # Find which companies are missing
                result2 = conn.execute(text('''
                    SELECT c.ticker
                    FROM dim_companies c
                    WHERE c.ticker != 'TAXONOMY'
                      AND c.ticker NOT IN (
                          SELECT DISTINCT c2.ticker
                          FROM fact_financial_metrics f
                          JOIN dim_companies c2 ON f.company_id = c2.company_id
                          JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                          WHERE dc.normalized_label = :metric
                            AND f.dimension_id IS NULL
                      )
                    ORDER BY c.ticker
                '''), {'metric': metric})
                missing_companies = [row[0] for row in result2]
                
                problems.append({
                    'metric': metric,
                    'description': description,
                    'missing_count': missing_count,
                    'missing_companies': missing_companies,
                    'coverage': f"{company_count}/{total_companies}"
                })
        
        # Sort by severity (most missing first)
        problems.sort(key=lambda x: x['missing_count'], reverse=True)
        
        print("🚨 PROBLEMATIC METRICS (Missing from some companies):")
        print("="*120)
        print(f"{'Metric':30} | {'Description':35} | {'Coverage':12} | {'Missing':8} | {'Companies'}")
        print("-"*120)
        
        for prob in problems:
            print(f"{prob['metric']:30} | {prob['description']:35} | {prob['coverage']:12} | {prob['missing_count']:8} | {', '.join(prob['missing_companies'])}")
        
        print(f"\n\nTotal problematic metrics: {len(problems)}")
        
        return problems, all_companies


def find_alternatives_for_problems(problems, all_companies):
    """For each problem, find what concepts missing companies are actually using"""
    engine = create_engine(DATABASE_URI)
    
    # Pattern mappings for finding alternatives
    PATTERNS = {
        'revenue': ['Revenue', 'Revenues', 'Sales', 'SalesRevenue'],
        'operating_income': ['OperatingIncome', 'OperatingProfit', 'OperatingEarnings', 'OperatingResult'],
        'total_liabilities': ['Liabilities', 'TotalLiabilities'],
        'current_assets': ['CurrentAssets', 'AssetsCurrent'],
        'current_liabilities': ['CurrentLiabilities', 'LiabilitiesCurrent'],
        'property_plant_equipment': ['PropertyPlant', 'PPE', 'PropertyPlantAndEquipment'],
    }
    
    print("\n\n" + "="*120)
    print("FINDING ALTERNATIVES FOR MISSING COMPANIES")
    print("="*120)
    
    fixes_needed = []
    
    for prob in problems:
        metric = prob['metric']
        missing_companies = prob['missing_companies']
        
        print(f"\n{'='*120}")
        print(f"📊 {metric.upper()} - Missing from: {', '.join(missing_companies)}")
        print(f"{'='*120}")
        
        patterns = PATTERNS.get(metric, [metric.replace('_', '')])
        
        with engine.connect() as conn:
            for company in missing_companies:
                print(f"\n  {company}:")
                
                # Find concepts this company has that match patterns
                pattern_sql = ' OR '.join([f"dc.concept_name LIKE '%{p}%'" for p in patterns])
                
                result = conn.execute(text(f'''
                    SELECT DISTINCT
                        dc.concept_name,
                        dc.normalized_label,
                        COUNT(*) as facts
                    FROM fact_financial_metrics f
                    JOIN dim_companies c ON f.company_id = c.company_id
                    JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                    WHERE c.ticker = :company
                      AND f.dimension_id IS NULL
                      AND ({pattern_sql})
                      AND dc.concept_name NOT LIKE '%Note%'
                      AND dc.concept_name NOT LIKE '%Policy%'
                      AND dc.concept_name NOT LIKE '%Disclosure%'
                      AND dc.concept_name NOT LIKE '%TextBlock%'
                      AND dc.concept_name NOT LIKE '%Table%'
                      AND dc.concept_name NOT LIKE 'Abstract%'
                    GROUP BY dc.concept_name, dc.normalized_label
                    ORDER BY facts DESC
                    LIMIT 10
                '''), {'company': company})
                
                found = False
                for row in result:
                    found = True
                    concept_name = row[0]
                    current_label = row[1]
                    facts = row[2]
                    print(f"    → {concept_name:60} | Currently: {current_label:30} | {facts} facts")
                    
                    # Check if this should be mapped
                    if current_label != metric and facts > 0:
                        fixes_needed.append({
                            'metric': metric,
                            'company': company,
                            'concept_name': concept_name,
                            'current_label': current_label,
                            'facts': facts,
                            'suggestion': f"Map '{concept_name}' → '{metric}'"
                        })
                
                if not found:
                    print(f"    ❌ NO ALTERNATIVES FOUND - Company may genuinely not report this")
    
    return fixes_needed


def main():
    problems, all_companies = audit_all_metrics()
    fixes = find_alternatives_for_problems(problems, all_companies)
    
    print("\n\n" + "="*120)
    print("SUMMARY OF FIXES NEEDED")
    print("="*120)
    
    # Group by metric
    by_metric = {}
    for fix in fixes:
        if fix['metric'] not in by_metric:
            by_metric[fix['metric']] = []
        by_metric[fix['metric']].append(fix)
    
    for metric, metric_fixes in sorted(by_metric.items()):
        print(f"\n📊 {metric.upper()} ({len(metric_fixes)} fixes):")
        for fix in metric_fixes:
            print(f"   {fix['company']:5} → Map '{fix['concept_name']}' → '{metric}' (currently: {fix['current_label']}, {fix['facts']} facts)")
    
    # Save to file
    output_file = Path(__file__).parent.parent.parent / "data" / "universal_metrics_fixes.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w') as f:
        json.dump({
            'problems': problems,
            'fixes': fixes
        }, f, indent=2, default=str)
    
    print(f"\n\n✅ Audit complete. Results saved to: {output_file}")
    print("\n⚠️  NEXT STEP: Review fixes and manually apply SAFE ones to taxonomy_mappings.py")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())

