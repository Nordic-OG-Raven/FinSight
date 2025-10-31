#!/usr/bin/env python3
"""
Analyze normalization conflicts to determine resolution strategy.

For each conflict, checks if concepts are:
1. Used together in same filing/period (→ semantically different, must separate)
2. Never used together (→ cross-taxonomy variants, safe to merge)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from config import DATABASE_URI


def analyze_conflicts():
    """Analyze all normalization conflicts"""
    engine = create_engine(DATABASE_URI)
    
    # Get all semantic conflicts
    with engine.connect() as conn:
        result = conn.execute(text("""
        SELECT 
            dc.normalized_label,
            STRING_AGG(DISTINCT dc.concept_name, ' | ' ORDER BY dc.concept_name) as concepts
        FROM dim_concepts dc
        GROUP BY dc.normalized_label
        HAVING COUNT(DISTINCT dc.concept_name) > 1
        ORDER BY dc.normalized_label;
        """))
        
        conflicts = [(row[0], row[1].split(' | ')) for row in result]
    
    print(f"Analyzing {len(conflicts)} conflicts...")
    print("=" * 120)
    print()
    
    must_separate = []
    safe_to_merge = []
    
    for label, concepts in conflicts:
        # Check if any company uses multiple concepts in same period
        with engine.connect() as conn:
            placeholders = ', '.join([f"'{c}'" for c in concepts])
            query = text(f"""
            SELECT 
                c.ticker,
                dt.fiscal_year,
                COUNT(DISTINCT dc.concept_name) as concept_count
            FROM fact_financial_metrics f
            JOIN dim_companies c ON f.company_id = c.company_id
            JOIN dim_concepts dc ON f.concept_id = dc.concept_id
            JOIN dim_time_periods dt ON f.period_id = dt.period_id
            WHERE dc.concept_name IN ({placeholders})
              AND f.dimension_id IS NULL
            GROUP BY c.ticker, dt.fiscal_year
            HAVING COUNT(DISTINCT dc.concept_name) > 1
            LIMIT 1;
            """)
            
            result = conn.execute(query)
            has_overlap = result.fetchone() is not None
        
        if has_overlap:
            must_separate.append((label, concepts))
        else:
            safe_to_merge.append((label, concepts))
    
    # Print results
    print(f"\n{'='*120}")
    print("MUST SEPARATE (Used together in same filing/period):")
    print(f"{'='*120}\n")
    for label, concepts in must_separate:
        print(f"{label}:")
        for c in concepts:
            print(f"  - {c}")
        print()
    
    print(f"\n{'='*120}")
    print("SAFE TO MERGE (Never used together - cross-taxonomy variants):")
    print(f"{'='*120}\n")
    for label, concepts in safe_to_merge:
        print(f"{label}:")
        for c in concepts:
            print(f"  - {c}")
        print()
    
    print(f"\n{'='*120}")
    print("SUMMARY:")
    print(f"  Must separate: {len(must_separate)}")
    print(f"  Safe to merge: {len(safe_to_merge)}")
    print(f"  Total conflicts: {len(conflicts)}")
    print(f"{'='*120}\n")


if __name__ == '__main__':
    analyze_conflicts()

