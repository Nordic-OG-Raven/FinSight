#!/usr/bin/env python3
"""
Populate statement templates from existing rel_statement_items.

This script:
1. Analyzes existing rel_statement_items to identify common patterns (80-90% standard items)
2. Creates canonical templates for:
   - IFRS Income Statement
   - US-GAAP Income Statement
   - IFRS Balance Sheet
   - US-GAAP Balance Sheet
   - IFRS Cash Flow
   - US-GAAP Cash Flow
   - IFRS Comprehensive Income
   - IFRS Equity Statement
3. Migrates existing rel_statement_items to:
   - dim_statement_templates (if standard item)
   - rel_statement_overrides (if custom item)

Key Principle: Headers and spacers go in templates, NOT in fact tables.
"""
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import psycopg2

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB


def analyze_existing_items(conn) -> Dict[str, List[Dict]]:
    """Analyze existing rel_statement_items to identify common patterns
    
    Returns:
        Dictionary mapping (statement_type, format_type) -> list of items
    """
    cur = conn.cursor()
    
    # Get all statement items grouped by statement_type and accounting standard
    cur.execute("""
        SELECT 
            si.statement_type,
            c.accounting_standard,
            si.display_order,
            co.normalized_label,
            si.is_header,
            si.side,
            COUNT(DISTINCT si.filing_id) as filing_count
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
            si.is_header,
            si.side
        ORDER BY si.statement_type, c.accounting_standard, si.display_order
    """)
    
    items_by_template = {}
    for row in cur.fetchall():
        statement_type, accounting_standard, display_order, normalized_label, is_header, side, filing_count = row
        
        # Map accounting standard to format_type
        format_type = 'ifrs' if accounting_standard == 'IFRS' else 'us_gaap' if accounting_standard == 'US-GAAP' else 'standard'
        key = (statement_type, format_type)
        
        if key not in items_by_template:
            items_by_template[key] = []
        
        items_by_template[key].append({
            'display_order': display_order,
            'normalized_label': normalized_label,
            'is_header': is_header,
            'side': side,
            'filing_count': filing_count
        })
    
    return items_by_template


def create_templates(conn, items_by_template: Dict[Tuple[str, str], List[Dict]]):
    """Create canonical templates from analyzed items
    
    Logic:
    - Items that appear in >80% of filings are considered "standard" → dim_statement_templates
    - Items that appear in <80% are considered "custom" → rel_statement_overrides (per filing)
    """
    cur = conn.cursor()
    
    # Get total filing count per (statement_type, format_type)
    cur.execute("""
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
    
    filing_counts = {}
    for row in cur.fetchall():
        statement_type, accounting_standard, total_filings = row
        format_type = 'ifrs' if accounting_standard == 'IFRS' else 'us_gaap' if accounting_standard == 'US-GAAP' else 'standard'
        key = (statement_type, format_type)
        filing_counts[key] = total_filings
    
    # Create templates for items that appear in >80% of filings
    templates_created = 0
    for (statement_type, format_type), items in items_by_template.items():
        total_filings = filing_counts.get((statement_type, format_type), 1)
        threshold = max(1, int(total_filings * 0.8))  # 80% threshold
        
        for item in items:
            if item['filing_count'] >= threshold:
                # Standard item - create template
                # Extract item_label from dim_concepts.preferred_label or concept_name
                item_label = None
                if item['normalized_label']:
                    # Try to get preferred_label from dim_concepts
                    cur.execute("""
                        SELECT preferred_label, concept_name
                        FROM dim_concepts
                        WHERE normalized_label = %s
                        ORDER BY concept_id
                        LIMIT 1
                    """, (item['normalized_label'],))
                    label_result = cur.fetchone()
                    if label_result:
                        preferred_label, concept_name = label_result
                        # Prefer preferred_label, fallback to concept_name converted to readable format
                        if preferred_label:
                            item_label = preferred_label
                        elif concept_name:
                            # Convert CamelCase to readable format
                            import re
                            item_label = re.sub(r'(?<!^)(?=[A-Z])', ' ', concept_name).strip()
                
                # Final fallback
                if not item_label:
                    if item['is_header']:
                        item_label = 'Header'
                    else:
                        # Convert normalized_label to readable format
                        item_label = (item['normalized_label'] or 'Item').replace('_', ' ').title()
                
                cur.execute("""
                    INSERT INTO dim_statement_templates (
                        statement_type, format_type, item_order,
                        item_label, normalized_label,
                        is_header, is_spacer, side
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (statement_type, format_type, item_order) DO NOTHING
                """, (
                    statement_type, format_type, item['display_order'],
                    item_label, item['normalized_label'],
                    item['is_header'], False, item['side']
                ))
                templates_created += 1
    
    conn.commit()
    print(f"Created {templates_created} template items")
    
    return templates_created


def migrate_overrides(conn):
    """Migrate custom items (not in templates) to rel_statement_overrides"""
    cur = conn.cursor()
    
    # For each filing, find items that don't match templates
    # Get all filings with their accounting standard
    cur.execute("""
        SELECT DISTINCT f.filing_id, c.accounting_standard
        FROM dim_filings f
        JOIN dim_companies c ON f.company_id = c.company_id
    """)
    
    filings = cur.fetchall()
    overrides_created = 0
    
    for filing_id, accounting_standard in filings:
        format_type = 'ifrs' if accounting_standard == 'IFRS' else 'us_gaap' if accounting_standard == 'US-GAAP' else 'standard'
        
        # For each statement type, find items that don't match templates
        for statement_type in ['income_statement', 'balance_sheet', 'cash_flow', 'comprehensive_income', 'equity_statement']:
            # Get items from rel_statement_items for this filing
            cur.execute("""
                SELECT 
                    si.concept_id,
                    si.display_order,
                    si.is_header,
                    si.side,
                    co.normalized_label,
                    co.preferred_label,
                    co.concept_name
                FROM rel_statement_items si
                JOIN dim_concepts co ON si.concept_id = co.concept_id
                WHERE si.filing_id = %s
                  AND si.statement_type = %s
                  AND si.is_main_item = TRUE
                ORDER BY si.display_order
            """, (filing_id, statement_type))
            
            filing_items = cur.fetchall()
            
            # Get template items for this statement_type and format_type
            cur.execute("""
                SELECT normalized_label, item_order
                FROM dim_statement_templates
                WHERE statement_type = %s
                  AND format_type = %s
            """, (statement_type, format_type))
            
            template_items = {row[0]: row[1] for row in cur.fetchall() if row[0]}
            
            # Find items that don't match templates (custom items)
            for concept_id, display_order, is_header, side, normalized_label, preferred_label, concept_name in filing_items:
                # Check if this item exists in template
                if normalized_label not in template_items:
                    # Custom item - add to rel_statement_overrides
                    # Get item_label from preferred_label or concept_name
                    item_label = preferred_label
                    if not item_label and concept_name:
                        import re
                        item_label = re.sub(r'(?<!^)(?=[A-Z])', ' ', concept_name).strip()
                    if not item_label:
                        item_label = (normalized_label or 'Item').replace('_', ' ').title() if normalized_label else 'Item'
                    
                    # Check if override already exists
                    cur.execute("""
                        SELECT override_id FROM rel_statement_overrides
                        WHERE filing_id = %s AND item_order = %s
                    """, (filing_id, int(display_order)))
                    
                    if not cur.fetchone():
                        cur.execute("""
                            INSERT INTO rel_statement_overrides (
                                filing_id, item_order, item_label, normalized_label,
                                is_header, is_spacer, side, is_custom
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            filing_id, int(display_order), item_label, normalized_label,
                            is_header, False, side, True
                        ))
                        overrides_created += 1
    
    conn.commit()
    print(f"Created {overrides_created} override items")
    
    return overrides_created


def main():
    """Main function to populate templates"""
    print("Populating statement templates from existing rel_statement_items...")
    
    conn = psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        database=POSTGRES_DB
    )
    
    try:
        # Analyze existing items
        print("Analyzing existing statement items...")
        items_by_template = analyze_existing_items(conn)
        print(f"Found {len(items_by_template)} template combinations")
        
        # Create templates
        print("Creating canonical templates...")
        templates_created = create_templates(conn, items_by_template)
        
        # Migrate overrides
        print("Migrating custom items to rel_statement_overrides...")
        overrides_created = migrate_overrides(conn)
        
        print("✅ Template population complete")
        
    finally:
        conn.close()


if __name__ == '__main__':
    main()

