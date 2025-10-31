#!/usr/bin/env python3
"""
Missing Data Analysis Script
Scans all companies, metrics, and time periods to identify missing data gaps.

Output: Matrix showing % missing data for each company-metric combination.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from config import DATABASE_URI
import pandas as pd
import argparse


def get_all_combinations(engine):
    """Get all possible company-metric-year combinations"""
    with engine.connect() as conn:
        # Get all companies
        companies = conn.execute(text("SELECT ticker FROM dim_companies ORDER BY ticker"))
        company_list = [row[0] for row in companies]
        
        # Get all metrics (normalized labels)
        metrics = conn.execute(text("""
            SELECT DISTINCT normalized_label 
            FROM dim_concepts 
            WHERE normalized_label IS NOT NULL
              AND normalized_label NOT LIKE '%_note'
              AND normalized_label NOT LIKE '%_disclosure%'
            ORDER BY normalized_label
        """))
        metric_list = [row[0] for row in metrics]
        
        # Get all fiscal years
        years = conn.execute(text("""
            SELECT DISTINCT fiscal_year 
            FROM dim_time_periods 
            WHERE fiscal_year IS NOT NULL
            ORDER BY fiscal_year
        """))
        year_list = [row[0] for row in years]
        
        return company_list, metric_list, year_list


def analyze_missing_data(engine, companies=None, metrics=None, years=None, verbose=False):
    """
    Analyze missing data patterns.
    
    Returns:
        DataFrame with columns: company, metric, years_available, years_total, coverage_pct
    """
    # Get all combinations
    all_companies, all_metrics, all_years = get_all_combinations(engine)
    
    # Use filters if provided
    if companies:
        all_companies = [c for c in all_companies if c in companies]
    if metrics:
        all_metrics = [m for m in all_metrics if m in metrics]
    if years:
        all_years = [y for y in all_years if y in years]
    
    if verbose:
        print(f"Analyzing {len(all_companies)} companies × {len(all_metrics)} metrics × {len(all_years)} years")
        print("=" * 120)
    
    # Query actual data availability
    query = """
    WITH company_data_years AS (
        -- Get all years where each company has ANY data
        SELECT DISTINCT
            c.ticker,
            t.fiscal_year
        FROM fact_financial_metrics f
        JOIN dim_companies c ON f.company_id = c.company_id
        JOIN dim_time_periods t ON f.period_id = t.period_id
        WHERE c.ticker = ANY(:companies)
          AND t.fiscal_year = ANY(:years)
          AND t.fiscal_year IS NOT NULL
          AND f.dimension_id IS NULL
          AND f.value_numeric IS NOT NULL
    ),
    company_reported_metrics AS (
        -- Get metrics that each company reports (at least once)
        SELECT DISTINCT
            c.ticker,
            co.normalized_label
        FROM fact_financial_metrics f
        JOIN dim_companies c ON f.company_id = c.company_id
        JOIN dim_concepts co ON f.concept_id = co.concept_id
        WHERE c.ticker = ANY(:companies)
          AND co.normalized_label = ANY(:metrics)
          AND co.normalized_label IS NOT NULL
          AND co.normalized_label NOT LIKE '%_note'
          AND co.normalized_label NOT LIKE '%_disclosure%'
    ),
    expected_combinations AS (
        -- For each company-metric pair, check coverage across ALL years where company has data
        SELECT 
            crm.ticker,
            crm.normalized_label,
            cdy.fiscal_year
        FROM company_reported_metrics crm
        CROSS JOIN company_data_years cdy
        WHERE crm.ticker = cdy.ticker
    ),
    actual_data AS (
        SELECT DISTINCT
            c.ticker,
            co.normalized_label,
            t.fiscal_year
        FROM fact_financial_metrics f
        JOIN dim_companies c ON f.company_id = c.company_id
        JOIN dim_concepts co ON f.concept_id = co.concept_id
        JOIN dim_time_periods t ON f.period_id = t.period_id
        WHERE c.ticker = ANY(:companies)
          AND co.normalized_label = ANY(:metrics)
          AND t.fiscal_year = ANY(:years)
          AND f.dimension_id IS NULL  -- Only consolidated facts
          AND f.value_numeric IS NOT NULL
          AND co.normalized_label NOT LIKE '%_note'
          AND co.normalized_label NOT LIKE '%_disclosure%'
    )
    SELECT 
        ec.ticker,
        ec.normalized_label,
        COUNT(DISTINCT ad.fiscal_year) as years_available,
        COUNT(DISTINCT ec.fiscal_year) as years_total,
        ROUND(100.0 * COUNT(DISTINCT ad.fiscal_year) / NULLIF(COUNT(DISTINCT ec.fiscal_year), 0), 1) as coverage_pct
    FROM expected_combinations ec
    LEFT JOIN actual_data ad ON 
        ec.ticker = ad.ticker AND 
        ec.normalized_label = ad.normalized_label AND 
        ec.fiscal_year = ad.fiscal_year
    GROUP BY ec.ticker, ec.normalized_label
    ORDER BY ec.ticker, ec.normalized_label, coverage_pct;
    """
    
    with engine.connect() as conn:
        result = conn.execute(text(query), {
            'companies': all_companies,
            'metrics': all_metrics,
            'years': all_years
        })
        
        rows = result.fetchall()
        df = pd.DataFrame(rows, columns=['company', 'metric', 'years_available', 'years_total', 'coverage_pct'])
        
        return df


def print_summary_report(df, verbose=False):
    """Print comprehensive missing data report"""
    print("\n" + "=" * 120)
    print("MISSING DATA ANALYSIS REPORT")
    print("=" * 120)
    
    total_combinations = len(df)
    complete_data = len(df[df['coverage_pct'] == 100.0])
    partial_data = len(df[(df['coverage_pct'] > 0) & (df['coverage_pct'] < 100.0)])
    missing_data = len(df[df['coverage_pct'] == 0.0])
    
    print(f"\n📊 OVERALL STATISTICS:")
    print(f"   Total combinations: {total_combinations:,}")
    print(f"   ✅ Complete (100%): {complete_data:,} ({100*complete_data/total_combinations:.1f}%)")
    print(f"   ⚠️  Partial (1-99%): {partial_data:,} ({100*partial_data/total_combinations:.1f}%)")
    print(f"   ❌ Missing (0%): {missing_data:,} ({100*missing_data/total_combinations:.1f}%)")
    
    # By company
    print(f"\n📈 BY COMPANY:")
    company_stats = df.groupby('company').agg({
        'coverage_pct': ['mean', 'count'],
        'years_available': 'sum',
        'years_total': 'first'
    }).round(1)
    company_stats.columns = ['avg_coverage_pct', 'metric_count', 'total_years_available', 'total_years_expected']
    company_stats = company_stats.sort_values('avg_coverage_pct', ascending=True)
    print(company_stats.to_string())
    
    # By metric
    print(f"\n📉 BY METRIC (Top 20 most missing):")
    metric_stats = df.groupby('metric').agg({
        'coverage_pct': 'mean',
        'company': 'count'
    }).round(1)
    metric_stats.columns = ['avg_coverage_pct', 'company_count']
    metric_stats = metric_stats.sort_values('avg_coverage_pct', ascending=True).head(20)
    print(metric_stats.to_string())
    
    # Worst combinations
    print(f"\n🔴 WORST 20 COMBINATIONS (Missing Data):")
    worst = df[df['coverage_pct'] == 0.0].head(20)
    if len(worst) > 0:
        print(worst[['company', 'metric', 'years_available', 'years_total', 'coverage_pct']].to_string(index=False))
    else:
        print("   (No completely missing combinations)")
    
    if verbose:
        print(f"\n📋 DETAILED BREAKDOWN:")
        for company in sorted(df['company'].unique()):
            company_df = df[df['company'] == company]
            missing = len(company_df[company_df['coverage_pct'] == 0.0])
            partial = len(company_df[(company_df['coverage_pct'] > 0) & (company_df['coverage_pct'] < 100.0)])
            complete = len(company_df[company_df['coverage_pct'] == 100.0])
            print(f"\n   {company}:")
            print(f"      Complete: {complete}, Partial: {partial}, Missing: {missing}")


def main():
    parser = argparse.ArgumentParser(description='Analyze missing data patterns')
    parser.add_argument('--company', nargs='+', help='Filter by company tickers')
    parser.add_argument('--metric', nargs='+', help='Filter by metrics')
    parser.add_argument('--year', type=int, nargs='+', help='Filter by fiscal years')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed breakdown')
    parser.add_argument('--output', '-o', help='Output CSV file path')
    parser.add_argument('--threshold', type=float, default=0.0, help='Show only combinations with coverage < threshold%')
    
    args = parser.parse_args()
    
    engine = create_engine(DATABASE_URI)
    
    # Convert human-readable metrics back to snake_case if needed
    metrics_raw = None
    if args.metric:
        # Assume metrics are provided in human-readable format, convert back
        from src.ui.data_viewer_v2 import humanize_label
        all_metrics, _ = get_all_combinations(engine)
        metric_map = {humanize_label(m): m for m in all_metrics}
        metrics_raw = [metric_map.get(m, m.replace(' ', '_').lower()) for m in args.metric]
    
    # Analyze
    df = analyze_missing_data(
        engine,
        companies=args.company,
        metrics=metrics_raw or args.metric,
        years=args.year,
        verbose=args.verbose
    )
    
    # Filter by threshold
    if args.threshold > 0:
        df = df[df['coverage_pct'] < args.threshold]
    
    # Print report
    print_summary_report(df, verbose=args.verbose)
    
    # Save if requested
    if args.output:
        df.to_csv(args.output, index=False)
        print(f"\n✅ Saved results to {args.output}")
    
    return df


if __name__ == '__main__':
    main()

