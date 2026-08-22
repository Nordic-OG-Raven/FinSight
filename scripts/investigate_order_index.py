#!/usr/bin/env python3
"""
Investigate order_index values for EPS items vs net income in rel_presentation_hierarchy.

This script analyzes:
1. Actual order_index values for EPS items vs net income
2. Whether EPS items are in different role_uri
3. Whether EPS items are in separate presentation hierarchy branch
4. The root cause of why EPS items have order_index=1-2 but should appear after net income
"""

import sys
from pathlib import Path
from sqlalchemy import create_engine, text
from config import DATABASE_URI

sys.path.insert(0, str(Path(__file__).parent.parent))

def investigate_order_index(ticker: str = "NVO", year: int = 2024):
    """Investigate order_index distribution for income statement items."""
    engine = create_engine(DATABASE_URI)
    
    with engine.connect() as conn:
        # Get filing_id
        filing_query = text("""
            SELECT f.filing_id
            FROM dim_filings f
            JOIN dim_companies c ON f.company_id = c.company_id
            WHERE c.ticker = :ticker
              AND EXTRACT(YEAR FROM f.fiscal_year_end) = :year
            LIMIT 1
        """)
        filing_result = conn.execute(filing_query, {"ticker": ticker, "year": year})
        filing_row = filing_result.fetchone()
        if not filing_row:
            print(f"No filing found for {ticker} {year}")
            return
        filing_id = filing_row[0]
        
        print(f"Investigating order_index for {ticker} {year} (filing_id={filing_id})")
        print("=" * 80)
        
        # Get all income statement items with their order_index, role_uri, and normalized_label
        items_query = text("""
            SELECT 
                ph.order_index,
                ph.role_uri,
                ph.priority,
                co.normalized_label,
                co.concept_name,
                co.is_abstract,
                ph.parent_concept_id,
                ph.child_concept_id,
                ph.statement_type
            FROM rel_presentation_hierarchy ph
            JOIN dim_concepts co ON ph.child_concept_id = co.concept_id
            WHERE ph.filing_id = :filing_id
              AND ph.statement_type = 'income_statement'
              AND ph.order_index < 1000
            ORDER BY ph.order_index, ph.priority, co.normalized_label
        """)
        
        items_result = conn.execute(items_query, {"filing_id": filing_id})
        items = items_result.fetchall()
        
        print(f"\nTotal income statement items: {len(items)}")
        print("\nOrder Index Distribution:")
        print("-" * 80)
        
        # Group by order_index
        order_groups = {}
        for item in items:
            order_idx = item[0]
            if order_idx not in order_groups:
                order_groups[order_idx] = []
            order_groups[order_idx].append(item)
        
        # Print items grouped by order_index
        for order_idx in sorted(order_groups.keys()):
            items_at_order = order_groups[order_idx]
            print(f"\nOrder Index {order_idx} ({len(items_at_order)} items):")
            for item in items_at_order:
                role_uri = item[1] or "NULL"
                priority = item[2] or 0
                normalized_label = item[3]
                concept_name = item[4]
                is_abstract = item[5]
                parent_id = item[6]
                child_id = item[7]
                
                # Highlight EPS and net income items
                is_eps = 'earnings' in normalized_label.lower() and 'share' in normalized_label.lower()
                is_net_income = any(term in normalized_label.lower() for term in ['net_income', 'net_profit', 'profit_loss'])
                
                marker = ""
                if is_eps:
                    marker = " [EPS]"
                elif is_net_income:
                    marker = " [NET INCOME]"
                
                print(f"  - {normalized_label} (concept_id={child_id}, priority={priority}, abstract={is_abstract}, parent={parent_id}){marker}")
                print(f"    Role URI: {role_uri[:80]}..." if len(role_uri) > 80 else f"    Role URI: {role_uri}")
        
        # Check for EPS items specifically
        print("\n" + "=" * 80)
        print("EPS Items Analysis:")
        print("-" * 80)
        
        eps_query = text("""
            SELECT 
                ph.order_index,
                ph.role_uri,
                ph.priority,
                co.normalized_label,
                co.concept_name,
                ph.parent_concept_id,
                parent_co.normalized_label as parent_label
            FROM rel_presentation_hierarchy ph
            JOIN dim_concepts co ON ph.child_concept_id = co.concept_id
            LEFT JOIN dim_concepts parent_co ON ph.parent_concept_id = parent_co.concept_id
            WHERE ph.filing_id = :filing_id
              AND ph.statement_type = 'income_statement'
              AND (
                  co.normalized_label LIKE '%earnings%share%'
                  OR co.normalized_label LIKE '%eps%'
                  OR co.concept_name LIKE '%EarningsPerShare%'
              )
            ORDER BY ph.order_index
        """)
        
        eps_result = conn.execute(eps_query, {"filing_id": filing_id})
        eps_items = eps_result.fetchall()
        
        if eps_items:
            print(f"Found {len(eps_items)} EPS-related items:")
            for item in eps_items:
                order_idx, role_uri, priority, normalized_label, concept_name, parent_id, parent_label = item
                print(f"\n  {normalized_label} (concept_id={item[0] if item else 'N/A'})")
                print(f"    Order Index: {order_idx}")
                print(f"    Priority: {priority}")
                print(f"    Role URI: {role_uri[:100] if role_uri else 'NULL'}...")
                print(f"    Parent: {parent_label} (concept_id={parent_id})")
        else:
            print("No EPS items found in income_statement presentation hierarchy")
        
        # Check for net income items
        print("\n" + "=" * 80)
        print("Net Income Items Analysis:")
        print("-" * 80)
        
        net_income_query = text("""
            SELECT 
                ph.order_index,
                ph.role_uri,
                ph.priority,
                co.normalized_label,
                co.concept_name,
                ph.parent_concept_id,
                parent_co.normalized_label as parent_label
            FROM rel_presentation_hierarchy ph
            JOIN dim_concepts co ON ph.child_concept_id = co.concept_id
            LEFT JOIN dim_concepts parent_co ON ph.parent_concept_id = parent_co.concept_id
            WHERE ph.filing_id = :filing_id
              AND ph.statement_type = 'income_statement'
              AND (
                  co.normalized_label IN ('net_income', 'net_profit', 'net_income_including_noncontrolling_interest')
                  OR co.normalized_label LIKE '%net_income%'
                  OR co.normalized_label LIKE '%net_profit%'
                  OR co.normalized_label LIKE '%profit_loss%'
              )
            ORDER BY ph.order_index
        """)
        
        net_income_result = conn.execute(net_income_query, {"filing_id": filing_id})
        net_income_items = net_income_result.fetchall()
        
        if net_income_items:
            print(f"Found {len(net_income_items)} net income items:")
            for item in net_income_items:
                order_idx, role_uri, priority, normalized_label, concept_name, parent_id, parent_label = item
                print(f"\n  {normalized_label} (concept_id={item[0] if item else 'N/A'})")
                print(f"    Order Index: {order_idx}")
                print(f"    Priority: {priority}")
                print(f"    Role URI: {role_uri[:100] if role_uri else 'NULL'}...")
                print(f"    Parent: {parent_label} (concept_id={parent_id})")
        else:
            print("No net income items found")
        
        # Check if EPS items are in a different role_uri
        print("\n" + "=" * 80)
        print("Role URI Analysis:")
        print("-" * 80)
        
        role_uri_query = text("""
            SELECT DISTINCT
                ph.role_uri,
                COUNT(*) as item_count,
                MIN(ph.order_index) as min_order,
                MAX(ph.order_index) as max_order
            FROM rel_presentation_hierarchy ph
            WHERE ph.filing_id = :filing_id
              AND ph.statement_type = 'income_statement'
              AND ph.order_index < 1000
            GROUP BY ph.role_uri
            ORDER BY min_order
        """)
        
        role_uri_result = conn.execute(role_uri_query, {"filing_id": filing_id})
        role_uris = role_uri_result.fetchall()
        
        print(f"Found {len(role_uris)} distinct role URIs:")
        for role_uri, count, min_order, max_order in role_uris:
            print(f"\n  {role_uri[:100] if role_uri else 'NULL'}...")
            print(f"    Items: {count}, Order range: {min_order} - {max_order}")
            
            # Check if this role_uri contains EPS items
            eps_in_role_query = text("""
                SELECT co.normalized_label
                FROM rel_presentation_hierarchy ph
                JOIN dim_concepts co ON ph.child_concept_id = co.concept_id
                WHERE ph.filing_id = :filing_id
                  AND ph.role_uri = :role_uri
                  AND (
                      co.normalized_label LIKE '%earnings%share%'
                      OR co.normalized_label LIKE '%eps%'
                  )
            """)
            eps_in_role_result = conn.execute(eps_in_role_query, {"filing_id": filing_id, "role_uri": role_uri})
            eps_in_role = eps_in_role_result.fetchall()
            if eps_in_role:
                print(f"    Contains EPS items: {[row[0] for row in eps_in_role]}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Investigate order_index for income statement items")
    parser.add_argument("--ticker", default="NVO", help="Company ticker")
    parser.add_argument("--year", type=int, default=2024, help="Filing year")
    args = parser.parse_args()
    
    investigate_order_index(args.ticker, args.year)

