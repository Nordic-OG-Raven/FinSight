#!/usr/bin/env python3
"""
Diagnostic script to scan ALL metrics and identify those with zero data points
for selected companies. This helps identify "phantom" metrics in the dropdown.

Usage:
    python src/validation/scan_zero_data_metrics.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from config import DATABASE_URI

def scan_zero_data_metrics(companies=None, start_year=None, end_year=None):
    """
    Scan ALL normalized labels and report which have ZERO data points
    for the selected companies.
    
    Args:
        companies: List of company tickers (e.g., ['AAPL', 'GOOGL'])
        start_year: Minimum fiscal year (optional)
        end_year: Maximum fiscal year (optional)
    
    Returns:
        dict with metrics that have zero data points
    """
    engine = create_engine(DATABASE_URI)
    
    print("=" * 120)
    print("SCANNING FOR METRICS WITH ZERO DATA POINTS")
    print("=" * 120)
    
    if companies:
        print(f"\nSelected companies: {', '.join(companies)}")
    else:
        print("\n⚠️  No companies selected - scanning all metrics (may take longer)")
    
    if start_year and end_year:
        print(f"Year range: {start_year} - {end_year}")
    
    print("\n" + "=" * 120)
    
    with engine.connect() as conn:
        # Step 1: Get ALL normalized labels from dropdown (all concepts)
        print("\n📊 Step 1: Loading all normalized labels from dim_concepts...")
        result1 = conn.execute(text("""
            SELECT DISTINCT normalized_label 
            FROM dim_concepts 
            WHERE normalized_label IS NOT NULL
              AND normalized_label NOT LIKE '%_note'
              AND normalized_label NOT LIKE '%_disclosure%'
              AND normalized_label NOT LIKE '%_section_header'
            ORDER BY normalized_label
        """))
        
        all_labels = [row[0] for row in result1]
        print(f"   Found {len(all_labels)} total metrics")
        
        # Step 2: For each label, count data points for selected companies
        print("\n📊 Step 2: Checking data availability for each metric...")
        
        zero_data_metrics = []
        metrics_with_data = []
        
        query = """
        SELECT COUNT(*) as fact_count
        FROM fact_financial_metrics f
        JOIN dim_companies c ON f.company_id = c.company_id
        JOIN dim_concepts dc ON f.concept_id = dc.concept_id
        LEFT JOIN dim_time_periods t ON f.period_id = t.period_id
        WHERE dc.normalized_label = :label
          AND f.dimension_id IS NULL
          AND f.value_numeric IS NOT NULL
        """
        
        params_base = {}
        
        if companies:
            query += " AND c.ticker = ANY(:companies)"
            params_base['companies'] = companies
        
        if start_year is not None and end_year is not None:
            query += " AND t.fiscal_year >= :start_year AND t.fiscal_year <= :end_year"
            params_base['start_year'] = start_year
            params_base['end_year'] = end_year
        
        # Process in batches for progress reporting
        batch_size = 100
        for i in range(0, len(all_labels), batch_size):
            batch = all_labels[i:i+batch_size]
            print(f"   Checking metrics {i+1} to {min(i+batch_size, len(all_labels))}...", end="\r")
            
            for label in batch:
                params = params_base.copy()
                params['label'] = label
                
                result = conn.execute(text(query), params)
                fact_count = result.scalar()
                
                if fact_count == 0:
                    zero_data_metrics.append(label)
                else:
                    metrics_with_data.append((label, fact_count))
        
        print(f"\n   ✅ Scanned {len(all_labels)} metrics")
        
        # Step 3: Report results
        print("\n" + "=" * 120)
        print("RESULTS")
        print("=" * 120)
        
        print(f"\n✅ Metrics WITH data: {len(metrics_with_data)}")
        print(f"❌ Metrics WITH ZERO data: {len(zero_data_metrics)}")
        
        if zero_data_metrics:
            print("\n" + "=" * 120)
            print("⚠️  METRICS WITH ZERO DATA POINTS (SHOULD BE REMOVED FROM DROPDOWN):")
            print("=" * 120)
            
            # Group by pattern (e.g., hash suffixes)
            hash_suffix_metrics = [m for m in zero_data_metrics if len(m) > 80]
            other_metrics = [m for m in zero_data_metrics if len(m) <= 80]
            
            if hash_suffix_metrics:
                print(f"\n📌 Likely truncated labels with hash suffixes ({len(hash_suffix_metrics)}):")
                for metric in sorted(hash_suffix_metrics)[:20]:  # Show first 20
                    print(f"   - {metric}")
                if len(hash_suffix_metrics) > 20:
                    print(f"   ... and {len(hash_suffix_metrics) - 20} more")
            
            if other_metrics:
                print(f"\n📌 Other metrics with zero data ({len(other_metrics)}):")
                for metric in sorted(other_metrics)[:50]:  # Show first 50
                    print(f"   - {metric}")
                if len(other_metrics) > 50:
                    print(f"   ... and {len(other_metrics) - 50} more")
            
            # Check if these metrics exist for OTHER companies (not selected)
            print("\n" + "=" * 120)
            print("🔍 Checking if zero-data metrics have data for OTHER companies...")
            print("=" * 120)
            
            for metric in zero_data_metrics[:10]:  # Check first 10
                result = conn.execute(text("""
                    SELECT 
                        c.ticker,
                        COUNT(*) as fact_count,
                        MIN(t.fiscal_year) as min_year,
                        MAX(t.fiscal_year) as max_year
                    FROM fact_financial_metrics f
                    JOIN dim_companies c ON f.company_id = c.company_id
                    JOIN dim_concepts dc ON f.concept_id = dc.concept_id
                    LEFT JOIN dim_time_periods t ON f.period_id = t.period_id
                    WHERE dc.normalized_label = :metric
                      AND f.dimension_id IS NULL
                      AND f.value_numeric IS NOT NULL
                """ + ("" if not companies else " AND c.ticker != ALL(:companies)") + """
                    GROUP BY c.ticker
                    ORDER BY fact_count DESC
                    LIMIT 5;
                """), {
                    'metric': metric,
                    'companies': companies if companies else []
                })
                
                other_companies = result.fetchall()
                if other_companies:
                    print(f"\n   {metric}:")
                    for row in other_companies:
                        print(f"      ✅ {row[0]}: {row[1]} facts (FY{row[2]}-{row[3]})")
        else:
            print("\n✅ SUCCESS: All metrics in dropdown have data for selected companies!")
        
        return {
            'total_metrics': len(all_labels),
            'metrics_with_data': len(metrics_with_data),
            'zero_data_metrics': zero_data_metrics,
            'zero_data_count': len(zero_data_metrics)
        }


if __name__ == "__main__":
    # Default: scan for commonly selected companies
    default_companies = ['AAPL', 'GOOGL', 'JNJ', 'KO', 'LLY']
    default_years = (2020, 2025)
    
    print("\n🔍 Scanning for zero-data metrics...")
    print(f"   Companies: {', '.join(default_companies)}")
    print(f"   Year range: {default_years[0]} - {default_years[1]}\n")
    
    results = scan_zero_data_metrics(
        companies=default_companies,
        start_year=default_years[0],
        end_year=default_years[1]
    )
    
    print("\n" + "=" * 120)
    print("SUMMARY")
    print("=" * 120)
    print(f"Total metrics scanned: {results['total_metrics']}")
    print(f"Metrics with data: {results['metrics_with_data']}")
    print(f"Metrics with ZERO data: {results['zero_data_count']}")
    
    if results['zero_data_count'] > 0:
        print(f"\n❌ ERROR: {results['zero_data_count']} metrics have zero data but appear in dropdown")
        print("   SOLUTION: Use get_normalized_labels_for_companies() to filter dropdown")
        sys.exit(1)
    else:
        print("\n✅ SUCCESS: All metrics have data!")
        sys.exit(0)

