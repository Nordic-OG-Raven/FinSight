#!/usr/bin/env python3
"""
Migration script for ERD enhancements.

This script:
1. Populates dim_reporting_frameworks from existing accounting_standard values
2. Populates dim_taxonomies from existing dim_concepts.taxonomy
3. Links dim_companies to frameworks
4. Links dim_concepts to taxonomies
5. Migrates taxonomy_mappings to rel_concept_mappings (if applicable)
6. Links templates to frameworks
7. Populates fiscal periods from existing filings
8. Populates currencies from existing fact_financial_metrics.unit_measure
9. Sets reporting_frequency on filings based on filing_type
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text, inspect
from config import DATABASE_URI


def main():
    """Main migration function"""
    print("=" * 70)
    print("Migration: ERD Enhancements")
    print("=" * 70)
    
    engine = create_engine(DATABASE_URI)
    
    with engine.connect() as conn:
        conn.execute(text("BEGIN"))
        
        try:
            # 1. Populate dim_reporting_frameworks
            print("\n1. Populating dim_reporting_frameworks...")
            frameworks = [
                ('IFRS', 'IFRS', 'IASB', 'EU', None),
                ('US-GAAP', 'USGAAP', 'FASB', 'US', None),
                ('UK-GAAP', 'UKGAAP', 'FRC', 'GB', None),
            ]
            
            for framework_name, framework_code, standard_setter, jurisdiction, effective_date in frameworks:
                conn.execute(text("""
                    INSERT INTO dim_reporting_frameworks 
                    (framework_name, framework_code, standard_setter, jurisdiction, effective_date, is_active)
                    VALUES (:name, :code, :setter, :jurisdiction, :effective, TRUE)
                    ON CONFLICT (framework_name) DO NOTHING
                """), {
                    "name": framework_name,
                    "code": framework_code,
                    "setter": standard_setter,
                    "jurisdiction": jurisdiction,
                    "effective": effective_date
                })
            
            result = conn.execute(text("SELECT COUNT(*) FROM dim_reporting_frameworks"))
            count = result.fetchone()[0]
            print(f"   ✅ Populated {count} reporting frameworks")
            
            # 2. Link companies to frameworks
            print("\n2. Linking companies to frameworks...")
            conn.execute(text("""
                UPDATE dim_companies c
                SET framework_id = rf.framework_id
                FROM dim_reporting_frameworks rf
                WHERE c.accounting_standard = rf.framework_name
                  AND c.framework_id IS NULL
            """))
            result = conn.execute(text("SELECT COUNT(*) FROM dim_companies WHERE framework_id IS NOT NULL"))
            count = result.fetchone()[0]
            print(f"   ✅ Linked {count} companies to frameworks")
            
            # 3. Populate dim_taxonomies
            print("\n3. Populating dim_taxonomies...")
            # Get unique taxonomies from dim_concepts
            result = conn.execute(text("""
                SELECT DISTINCT taxonomy, COUNT(*) as concept_count
                FROM dim_concepts
                GROUP BY taxonomy
                ORDER BY concept_count DESC
            """))
            taxonomies = result.fetchall()
            
            # Map taxonomy names to frameworks
            taxonomy_framework_map = {
                'us-gaap': 'US-GAAP',
                'ifrs-full': 'IFRS',
                'ifrs': 'IFRS',
                'ifrs-eu': 'IFRS',
                'custom': None,
                'dei': None,
            }
            
            taxonomy_count = 0
            for taxonomy_name, concept_count in taxonomies:
                framework_name = taxonomy_framework_map.get(taxonomy_name.lower(), None)
                framework_id = None
                if framework_name:
                    result = conn.execute(text("""
                        SELECT framework_id FROM dim_reporting_frameworks 
                        WHERE framework_name = :name
                    """), {"name": framework_name})
                    row = result.fetchone()
                    if row:
                        framework_id = row[0]
                
                # Extract version if present (e.g., 'us-gaap-2024' -> '2024')
                taxonomy_version = None
                if '-' in taxonomy_name:
                    parts = taxonomy_name.split('-')
                    if parts[-1].isdigit():
                        taxonomy_version = parts[-1]
                        taxonomy_base = '-'.join(parts[:-1])
                    else:
                        taxonomy_base = taxonomy_name
                else:
                    taxonomy_base = taxonomy_name
                
                conn.execute(text("""
                    INSERT INTO dim_taxonomies 
                    (taxonomy_name, taxonomy_version, reporting_framework_id, is_active)
                    VALUES (:name, :version, :framework_id, TRUE)
                    ON CONFLICT (taxonomy_name) DO NOTHING
                """), {
                    "name": taxonomy_base,
                    "version": taxonomy_version,
                    "framework_id": framework_id
                })
                taxonomy_count += 1
            
            print(f"   ✅ Populated {taxonomy_count} taxonomies")
            
            # 4. Link concepts to taxonomies
            print("\n4. Linking concepts to taxonomies...")
            conn.execute(text("""
                UPDATE dim_concepts dc
                SET taxonomy_id = dt.taxonomy_id
                FROM dim_taxonomies dt
                WHERE dc.taxonomy = dt.taxonomy_name
                  AND dc.taxonomy_id IS NULL
            """))
            result = conn.execute(text("SELECT COUNT(*) FROM dim_concepts WHERE taxonomy_id IS NOT NULL"))
            count = result.fetchone()[0]
            print(f"   ✅ Linked {count} concepts to taxonomies")
            
            # 5. Link templates to frameworks
            print("\n5. Linking templates to frameworks...")
            conn.execute(text("""
                UPDATE dim_statement_templates dst
                SET framework_id = rf.framework_id
                FROM dim_reporting_frameworks rf
                WHERE dst.format_type = CASE 
                    WHEN rf.framework_code = 'IFRS' THEN 'ifrs'
                    WHEN rf.framework_code = 'USGAAP' THEN 'us_gaap'
                    ELSE 'standard'
                END
                AND dst.framework_id IS NULL
            """))
            result = conn.execute(text("SELECT COUNT(*) FROM dim_statement_templates WHERE framework_id IS NOT NULL"))
            count = result.fetchone()[0]
            print(f"   ✅ Linked {count} templates to frameworks")
            
            # 6. Populate fiscal periods
            print("\n6. Populating fiscal periods...")
            conn.execute(text("""
                INSERT INTO dim_fiscal_periods 
                (company_id, fiscal_year, fiscal_year_end_month, fiscal_year_end_day, 
                 calendar_year, is_calendar_year)
                SELECT DISTINCT
                    f.company_id,
                    EXTRACT(YEAR FROM f.fiscal_year_end)::INTEGER as fiscal_year,
                    EXTRACT(MONTH FROM f.fiscal_year_end)::INTEGER as fiscal_year_end_month,
                    EXTRACT(DAY FROM f.fiscal_year_end)::INTEGER as fiscal_year_end_day,
                    EXTRACT(YEAR FROM f.fiscal_year_end)::INTEGER as calendar_year,
                    CASE 
                        WHEN EXTRACT(MONTH FROM f.fiscal_year_end) = 12 
                         AND EXTRACT(DAY FROM f.fiscal_year_end) = 31 
                        THEN TRUE 
                        ELSE FALSE 
                    END as is_calendar_year
                FROM dim_filings f
                WHERE NOT EXISTS (
                    SELECT 1 FROM dim_fiscal_periods dfp
                    WHERE dfp.company_id = f.company_id
                      AND dfp.fiscal_year = EXTRACT(YEAR FROM f.fiscal_year_end)::INTEGER
                )
            """))
            result = conn.execute(text("SELECT COUNT(*) FROM dim_fiscal_periods"))
            count = result.fetchone()[0]
            print(f"   ✅ Populated {count} fiscal periods")
            
            # 7. Populate currencies
            print("\n7. Populating currencies...")
            result = conn.execute(text("""
                SELECT DISTINCT unit_measure
                FROM fact_financial_metrics
                WHERE unit_measure IS NOT NULL
                  AND unit_measure ~ '^[A-Z]{3}$'  -- 3-letter currency codes
                ORDER BY unit_measure
            """))
            currencies = result.fetchall()
            
            currency_count = 0
            for (currency_code,) in currencies:
                currency_name_map = {
                    'USD': 'US Dollar',
                    'EUR': 'Euro',
                    'GBP': 'British Pound',
                    'DKK': 'Danish Krone',
                    'JPY': 'Japanese Yen',
                    'CNY': 'Chinese Yuan',
                }
                currency_name = currency_name_map.get(currency_code, currency_code)
                is_base = (currency_code == 'USD')  # USD as default base
                
                conn.execute(text("""
                    INSERT INTO dim_currencies (currency_code, currency_name, is_base_currency)
                    VALUES (:code, :name, :is_base)
                    ON CONFLICT (currency_code) DO NOTHING
                """), {
                    "code": currency_code,
                    "name": currency_name,
                    "is_base": is_base
                })
                currency_count += 1
            
            print(f"   ✅ Populated {currency_count} currencies")
            
            # 8. Link facts to currencies
            print("\n8. Linking facts to currencies...")
            conn.execute(text("""
                UPDATE fact_financial_metrics fm
                SET currency_id = dc.currency_id
                FROM dim_currencies dc
                WHERE fm.unit_measure = dc.currency_code
                  AND fm.currency_id IS NULL
            """))
            result = conn.execute(text("SELECT COUNT(*) FROM fact_financial_metrics WHERE currency_id IS NOT NULL"))
            count = result.fetchone()[0]
            print(f"   ✅ Linked {count} facts to currencies")
            
            # 9. Set reporting frequency on filings
            print("\n9. Setting reporting frequency on filings...")
            conn.execute(text("""
                UPDATE dim_filings
                SET reporting_frequency = CASE 
                    WHEN filing_type LIKE '%10-K%' THEN 'annual'
                    WHEN filing_type LIKE '%10-Q%' THEN 'quarterly'
                    WHEN filing_type LIKE '%20-F%' THEN 'annual'
                    ELSE 'annual'
                END
                WHERE reporting_frequency IS NULL
            """))
            result = conn.execute(text("SELECT COUNT(*) FROM dim_filings WHERE reporting_frequency IS NOT NULL"))
            count = result.fetchone()[0]
            print(f"   ✅ Set reporting frequency for {count} filings")
            
            # 10. Set default reporting frequency on companies
            print("\n10. Setting default reporting frequency on companies...")
            conn.execute(text("""
                UPDATE dim_companies c
                SET default_reporting_frequency = (
                    SELECT MODE() WITHIN GROUP (ORDER BY f.reporting_frequency)
                    FROM dim_filings f
                    WHERE f.company_id = c.company_id
                      AND f.reporting_frequency IS NOT NULL
                )
                WHERE default_reporting_frequency IS NULL
            """))
            result = conn.execute(text("SELECT COUNT(*) FROM dim_companies WHERE default_reporting_frequency IS NOT NULL"))
            count = result.fetchone()[0]
            print(f"   ✅ Set default reporting frequency for {count} companies")
            
            conn.execute(text("COMMIT"))
            print("\n" + "=" * 70)
            print("✅ Migration complete!")
            print("=" * 70)
            
        except Exception as e:
            conn.execute(text("ROLLBACK"))
            print(f"\n❌ Migration failed: {e}")
            raise


if __name__ == '__main__':
    main()

