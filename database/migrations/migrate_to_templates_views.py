#!/usr/bin/env python3
"""
Migration script to set up template tables and views architecture.

This script:
1. Creates staging tables (if not exist)
2. Creates template tables (if not exist)
3. Creates views (if not exist)
4. Populates templates from existing rel_statement_items
5. Validates the setup

Run this after schema.sql has been updated with the new tables/views.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text, inspect
from config import DATABASE_URI


def check_table_exists(conn, table_name: str) -> bool:
    """Check if a table exists"""
    inspector = inspect(conn)
    return table_name in inspector.get_table_names()


def check_view_exists(conn, view_name: str) -> bool:
    """Check if a view exists"""
    result = conn.execute(text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.views 
            WHERE table_name = :view_name
        )
    """), {"view_name": view_name})
    return result.fetchone()[0]


def populate_templates_from_existing_items(conn):
    """Populate dim_statement_templates from existing rel_statement_items
    
    This creates canonical templates by analyzing common patterns.
    """
    print("Populating templates from existing rel_statement_items...")
    
    # Get all statement items grouped by statement_type and accounting standard
    query = text("""
        SELECT 
            si.statement_type,
            c.accounting_standard,
            si.display_order,
            co.normalized_label,
            co.preferred_label,
            si.is_header,
            si.side,
            COUNT(DISTINCT si.filing_id) as filing_count,
            COUNT(DISTINCT f.company_id) as company_count
        FROM rel_statement_items si
        JOIN dim_filings f ON si.filing_id = f.filing_id
        JOIN dim_companies c ON f.company_id = c.company_id
        LEFT JOIN dim_concepts co ON si.concept_id = co.concept_id
        WHERE si.is_main_item = TRUE
        GROUP BY 
            si.statement_type,
            c.accounting_standard,
            si.display_order,
            co.normalized_label,
            co.preferred_label,
            si.is_header,
            si.side
        ORDER BY si.statement_type, c.accounting_standard, si.display_order
    """)
    
    result = conn.execute(query)
    items = result.fetchall()
    
    if not items:
        print("   ⚠️  No existing rel_statement_items found - templates will be empty")
        return 0
    
    # Get total filing count per (statement_type, format_type)
    count_query = text("""
        SELECT 
            si.statement_type,
            c.accounting_standard,
            COUNT(DISTINCT si.filing_id) as total_filings
        FROM rel_statement_items si
        JOIN dim_filings f ON si.filing_id = f.filing_id
        JOIN dim_companies c ON f.company_id = c.company_id
        WHERE si.is_main_item = TRUE
        GROUP BY si.statement_type, c.accounting_standard
    """)
    
    count_result = conn.execute(count_query)
    filing_counts = {}
    for row in count_result:
        statement_type, accounting_standard, total_filings = row
        format_type = 'ifrs' if accounting_standard == 'IFRS' else 'us_gaap' if accounting_standard == 'US-GAAP' else 'standard'
        key = (statement_type, format_type)
        filing_counts[key] = total_filings
    
    # Create templates for items that appear in >50% of filings (lower threshold for initial population)
    templates_created = 0
    for item in items:
        statement_type, accounting_standard, display_order, normalized_label, preferred_label, is_header, side, filing_count, company_count = item
        
        format_type = 'ifrs' if accounting_standard == 'IFRS' else 'us_gaap' if accounting_standard == 'US-GAAP' else 'standard'
        key = (statement_type, format_type)
        total_filings = filing_counts.get(key, 1)
        
        # Use 50% threshold for initial population (can be refined later)
        threshold = max(1, int(total_filings * 0.5))
        
        if filing_count >= threshold:
            # Standard item - create template
            item_label = preferred_label or normalized_label or ('Header' if is_header else 'Item')
            
            # Determine item_type
            item_type = 'header' if is_header else 'fact'
            if normalized_label and 'space' in normalized_label.lower():
                item_type = 'spacer'
            
            try:
                conn.execute(text("""
                    INSERT INTO dim_statement_templates (
                        statement_type, format_type, item_order,
                        item_label, normalized_label,
                        item_type, is_header, is_spacer, side
                    ) VALUES (:statement_type, :format_type, :item_order, :item_label, :normalized_label,
                              :item_type, :is_header, :is_spacer, :side)
                    ON CONFLICT (statement_type, format_type, item_order) DO UPDATE SET
                        item_label = EXCLUDED.item_label,
                        normalized_label = EXCLUDED.normalized_label,
                        is_header = EXCLUDED.is_header,
                        is_spacer = EXCLUDED.is_spacer,
                        side = EXCLUDED.side,
                        updated_at = CURRENT_TIMESTAMP
                """), {
                    "statement_type": statement_type,
                    "format_type": format_type,
                    "item_order": display_order,
                    "item_label": item_label,
                    "normalized_label": normalized_label,
                    "item_type": item_type,
                    "is_header": is_header,
                    "is_spacer": item_type == 'spacer',
                    "side": side
                })
                templates_created += 1
            except Exception as e:
                print(f"   ⚠️  Failed to create template for {statement_type}/{format_type} order {display_order}: {e}")
                continue
    
    conn.commit()
    print(f"   ✅ Created {templates_created} template items")
    return templates_created


def validate_setup(conn):
    """Validate that the new architecture is set up correctly"""
    print("\nValidating setup...")
    
    issues = []
    
    # Check staging table
    if not check_table_exists(conn, 'staging_facts'):
        issues.append("❌ staging_facts table does not exist")
    else:
        result = conn.execute(text("SELECT COUNT(*) FROM staging_facts"))
        count = result.fetchone()[0]
        print(f"   ✅ staging_facts: {count} rows")
    
    # Check template tables
    if not check_table_exists(conn, 'dim_statement_templates'):
        issues.append("❌ dim_statement_templates table does not exist")
    else:
        result = conn.execute(text("SELECT COUNT(*) FROM dim_statement_templates"))
        count = result.fetchone()[0]
        print(f"   ✅ dim_statement_templates: {count} rows")
    
    if not check_table_exists(conn, 'rel_statement_overrides'):
        issues.append("❌ rel_statement_overrides table does not exist")
    else:
        result = conn.execute(text("SELECT COUNT(*) FROM rel_statement_overrides"))
        count = result.fetchone()[0]
        print(f"   ✅ rel_statement_overrides: {count} rows")
    
    # Check views
    views_to_check = [
        'v_staging_to_facts',
        'v_income_statement',
        'v_balance_sheet',
        'v_cash_flow',
        'v_comprehensive_income',
        'v_equity_statement'
    ]
    
    for view_name in views_to_check:
        if not check_view_exists(conn, view_name):
            issues.append(f"❌ {view_name} view does not exist")
        else:
            print(f"   ✅ {view_name} view exists")
    
    if issues:
        print("\n⚠️  Issues found:")
        for issue in issues:
            print(f"   {issue}")
        return False
    else:
        print("\n✅ All checks passed!")
        return True


def main():
    """Main migration function"""
    print("=" * 70)
    print("Migration: Template Tables + Views + ELT Architecture")
    print("=" * 70)
    
    engine = create_engine(DATABASE_URI)
    
    with engine.connect() as conn:
        # Check if tables/views exist (they should be created by schema.sql)
        print("\n1. Checking schema...")
        if not check_table_exists(conn, 'staging_facts'):
            print("   ⚠️  staging_facts table not found - make sure schema.sql has been run")
            return
        
        if not check_table_exists(conn, 'dim_statement_templates'):
            print("   ⚠️  dim_statement_templates table not found - make sure schema.sql has been run")
            return
        
        # Populate templates from existing data
        print("\n2. Populating templates...")
        if check_table_exists(conn, 'rel_statement_items'):
            templates_created = populate_templates_from_existing_items(conn)
            if templates_created == 0:
                print("   ⚠️  No templates created - rel_statement_items may be empty")
        else:
            print("   ⚠️  rel_statement_items table not found - skipping template population")
        
        # Validate setup
        print("\n3. Validating setup...")
        is_valid = validate_setup(conn)
        
        if is_valid:
            print("\n" + "=" * 70)
            print("✅ Migration complete!")
            print("=" * 70)
            print("\nNext steps:")
            print("1. Test views with: SELECT * FROM v_income_statement WHERE filing_id = X AND period_id = Y")
            print("2. Update API to use views instead of denormalized tables")
            print("3. Test UI with new views")
            print("4. Once validated, deprecate denormalized fact tables")
        else:
            print("\n" + "=" * 70)
            print("⚠️  Migration incomplete - please fix issues above")
            print("=" * 70)


if __name__ == '__main__':
    main()

