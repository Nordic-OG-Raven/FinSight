#!/usr/bin/env python3
"""
Database-level validation for FinSight financial data warehouse.

Validates user-facing data quality issues that can only be detected after
normalization and database loading.

Run this AFTER the full ETL pipeline to ensure data quality.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from config import DATABASE_URI
from datetime import datetime


class DatabaseValidator:
    """Validates database-level data quality"""
    
    def __init__(self):
        self.engine = create_engine(DATABASE_URI)
        self.issues = []
        self.warnings = []
        self.info = []
    
    def validate_all(self):
        """Run all validation checks"""
        print("=" * 80)
        print(f"DATABASE VALIDATION - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)
        print()
        
        self.check_normalization_conflicts()
        self.check_user_facing_duplicates()
        self.check_missing_companies()
        self.check_data_completeness()
        
        self.print_summary()
    
    def check_normalization_conflicts(self):
        """Check for multiple concepts mapped to same normalized label"""
        print("1. Checking Normalization Conflicts...")
        print("-" * 80)
        
        with self.engine.connect() as conn:
            result = conn.execute(text("""
            SELECT 
                normalized_label,
                COUNT(DISTINCT concept_id) as concept_count,
                STRING_AGG(DISTINCT concept_name, ' | ') as concepts
            FROM dim_concepts
            GROUP BY normalized_label
            HAVING COUNT(DISTINCT concept_id) > 1
            ORDER BY concept_count DESC, normalized_label;
            """))
            
            rows = result.fetchall()
            
            if len(rows) == 0:
                self.info.append("✅ No normalization conflicts")
                print("  ✅ PASS: All concepts have unique normalized labels")
            else:
                # Some conflicts are intentional (e.g., net_income variants for comparability)
                # Flag as WARNING if > 100 conflicts, ERROR if any high-impact metrics
                if len(rows) > 100:
                    self.issues.append(f"❌ {len(rows)} normalization conflicts (too many)")
                    print(f"  ❌ FAIL: {len(rows)} normalization conflicts")
                else:
                    self.warnings.append(f"⚠️  {len(rows)} normalization conflicts")
                    print(f"  ⚠️  WARNING: {len(rows)} normalization conflicts")
                
                # Show top 5
                print()
                print("  Top 5 conflicts:")
                for i, row in enumerate(rows[:5], 1):
                    print(f"    {i}. '{row[0]}' ← {row[1]} concepts")
                    concepts = row[2].split(' | ')[:3]
                    for c in concepts:
                        print(f"       - {c}")
                    if row[1] > 3:
                        print(f"       ... and {row[1] - 3} more")
        print()
    
    def check_user_facing_duplicates(self):
        """
        Check for user-facing duplicates:
        Multiple facts with same (company, normalized_label, fiscal_year, dimension)
        but different concept_ids
        
        This is what the visualization shows as "duplicates"
        """
        print("2. Checking User-Facing Duplicates...")
        print("-" * 80)
        
        with self.engine.connect() as conn:
            result = conn.execute(text("""
            SELECT 
                c.ticker,
                dc.normalized_label,
                dt.fiscal_year,
                COUNT(DISTINCT f.concept_id) as concept_count,
                STRING_AGG(DISTINCT dc.concept_name, ' | ') as concepts,
                STRING_AGG(DISTINCT f.value_numeric::text, ' | ') as values
            FROM fact_financial_metrics f
            JOIN dim_companies c ON f.company_id = c.company_id
            JOIN dim_concepts dc ON f.concept_id = dc.concept_id
            JOIN dim_time_periods dt ON f.period_id = dt.period_id
            WHERE f.dimension_id IS NULL  -- Consolidated only
              AND dc.normalized_label NOT LIKE '%_note'
              AND dc.normalized_label NOT LIKE '%_disclosure%'
            GROUP BY c.ticker, dc.normalized_label, dt.fiscal_year
            HAVING COUNT(DISTINCT f.concept_id) > 1
            ORDER BY concept_count DESC, c.ticker, dc.normalized_label, dt.fiscal_year;
            """))
            
            rows = result.fetchall()
            
            if len(rows) == 0:
                self.info.append("✅ No user-facing duplicates")
                print("  ✅ PASS: No duplicate metrics visible to users")
            else:
                self.issues.append(f"❌ {len(rows)} user-facing duplicates")
                print(f"  ❌ FAIL: {len(rows)} cases where users see duplicate metrics")
                print()
                print("  Examples (top 10):")
                for i, row in enumerate(rows[:10], 1):
                    print(f"    {i}. {row[0]} - {row[1]} (FY{row[2]}): {row[3]} different concepts")
                    concepts = row[4].split(' | ')
                    values = row[5].split(' | ')
                    for c, v in zip(concepts, values):
                        print(f"       - {c}: ${float(v):,.0f}")
                if len(rows) > 10:
                    print(f"    ... and {len(rows) - 10} more")
        print()
    
    def check_missing_companies(self):
        """Check if all expected companies have data"""
        print("3. Checking Company Data...")
        print("-" * 80)
        
        with self.engine.connect() as conn:
            result = conn.execute(text("""
            SELECT 
                c.ticker,
                c.company_name,
                COUNT(DISTINCT f.filing_id) as filings,
                COUNT(f.fact_id) as facts,
                MIN(dt.fiscal_year) as min_year,
                MAX(dt.fiscal_year) as max_year
            FROM dim_companies c
            LEFT JOIN fact_financial_metrics f ON c.company_id = f.company_id
            LEFT JOIN dim_time_periods dt ON f.period_id = dt.period_id
            GROUP BY c.company_id, c.ticker, c.company_name
            ORDER BY c.ticker;
            """))
            
            rows = result.fetchall()
            
            print(f"  Total companies: {len(rows)}")
            print()
            
            missing_data = []
            low_data = []
            
            for row in rows:
                if row[2] == 0:  # No filings
                    missing_data.append(row[0])
                elif row[3] < 100:  # < 100 facts (very low)
                    low_data.append(f"{row[0]} ({row[3]} facts)")
            
            if missing_data:
                self.issues.append(f"❌ {len(missing_data)} companies with no data")
                print(f"  ❌ FAIL: {len(missing_data)} companies with no data: {', '.join(missing_data)}")
            
            if low_data:
                self.warnings.append(f"⚠️  {len(low_data)} companies with very little data")
                print(f"  ⚠️  WARNING: {len(low_data)} companies with < 100 facts: {', '.join(low_data)}")
            
            if not missing_data and not low_data:
                self.info.append("✅ All companies have adequate data")
                print("  ✅ PASS: All companies have adequate data")
            
            print()
            print("  Company summary:")
            for row in rows:
                years = f"{row[4]}-{row[5]}" if row[4] and row[5] else "N/A"
                print(f"    {row[0]:<6} {row[1]:<30} | Filings: {row[2]:>3} | Facts: {row[3]:>7,} | Years: {years}")
        print()
    
    def check_data_completeness(self):
        """Check for completeness of critical metrics"""
        print("4. Checking Data Completeness (Critical Metrics)...")
        print("-" * 80)
        
        critical_metrics = [
            'revenue',
            'net_income',
            'total_assets',
            'stockholders_equity',
            'operating_cash_flow',
        ]
        
        with self.engine.connect() as conn:
            result = conn.execute(text("""
            SELECT 
                c.ticker,
                COUNT(DISTINCT CASE WHEN dc.normalized_label = 'revenue' THEN f.fact_id END) as has_revenue,
                COUNT(DISTINCT CASE WHEN dc.normalized_label = 'net_income' THEN f.fact_id END) as has_net_income,
                COUNT(DISTINCT CASE WHEN dc.normalized_label = 'total_assets' THEN f.fact_id END) as has_assets,
                COUNT(DISTINCT CASE WHEN dc.normalized_label = 'stockholders_equity' THEN f.fact_id END) as has_equity,
                COUNT(DISTINCT CASE WHEN dc.normalized_label = 'operating_cash_flow' THEN f.fact_id END) as has_ocf
            FROM dim_companies c
            LEFT JOIN fact_financial_metrics f ON c.company_id = f.company_id
            LEFT JOIN dim_concepts dc ON f.concept_id = dc.concept_id
            GROUP BY c.company_id, c.ticker
            ORDER BY c.ticker;
            """))
            
            rows = result.fetchall()
            
            incomplete = []
            for row in rows:
                missing = []
                if row[1] == 0:
                    missing.append('revenue')
                if row[2] == 0:
                    missing.append('net_income')
                if row[3] == 0:
                    missing.append('total_assets')
                if row[4] == 0:
                    missing.append('stockholders_equity')
                if row[5] == 0:
                    missing.append('operating_cash_flow')
                
                if missing:
                    incomplete.append(f"{row[0]} (missing: {', '.join(missing)})")
            
            if incomplete:
                self.warnings.append(f"⚠️  {len(incomplete)} companies missing critical metrics")
                print(f"  ⚠️  WARNING: {len(incomplete)} companies missing critical metrics:")
                for item in incomplete:
                    print(f"    - {item}")
            else:
                self.info.append("✅ All companies have critical metrics")
                print("  ✅ PASS: All companies have critical metrics")
        print()
    
    def print_summary(self):
        """Print validation summary"""
        print("=" * 80)
        print("VALIDATION SUMMARY")
        print("=" * 80)
        
        if self.issues:
            print()
            print("❌ CRITICAL ISSUES:")
            for issue in self.issues:
                print(f"  {issue}")
        
        if self.warnings:
            print()
            print("⚠️  WARNINGS:")
            for warning in self.warnings:
                print(f"  {warning}")
        
        if self.info:
            print()
            print("✅ PASSED:")
            for item in self.info:
                print(f"  {item}")
        
        print()
        print("=" * 80)
        
        if self.issues:
            print("STATUS: FAILED ❌")
            print("=" * 80)
            sys.exit(1)
        elif self.warnings:
            print("STATUS: PASSED WITH WARNINGS ⚠️")
            print("=" * 80)
            sys.exit(0)
        else:
            print("STATUS: ALL CHECKS PASSED ✅")
            print("=" * 80)
            sys.exit(0)


def main():
    """Run database validation"""
    validator = DatabaseValidator()
    validator.validate_all()


if __name__ == '__main__':
    main()

