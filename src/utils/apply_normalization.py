"""
Apply taxonomy normalization to existing data in PostgreSQL.

This script updates the normalized_label column for all facts in the database.
"""

import psycopg2
from taxonomy_mappings import get_normalized_label
import sys


def apply_normalization_to_db():
    """Apply normalization mappings to all facts in database."""
    
    conn = psycopg2.connect(
        host='localhost',
        port='5432',
        user='superset',
        password='superset',
        database='finsight'
    )
    
    cur = conn.cursor()
    
    # Get all distinct concepts
    print("Fetching all concepts from database...")
    cur.execute("SELECT DISTINCT concept FROM financial_facts WHERE concept IS NOT NULL;")
    concepts = [row[0] for row in cur.fetchall()]
    print(f"Found {len(concepts)} unique concepts")
    
    # Apply normalization
    print("\nApplying taxonomy mappings...")
    mapped_count = 0
    unmapped_count = 0
    unmapped_concepts = []
    
    for concept in concepts:
        normalized = get_normalized_label(concept)
        
        if normalized:
            cur.execute(
                "UPDATE financial_facts SET normalized_label = %s WHERE concept = %s;",
                (normalized, concept)
            )
            mapped_count += 1
            
            if mapped_count % 10 == 0:
                sys.stdout.write(f"\r  Mapped: {mapped_count}/{len(concepts)}")
                sys.stdout.flush()
        else:
            unmapped_count += 1
            unmapped_concepts.append(concept)
    
    print(f"\n\n✅ Mapped: {mapped_count} concepts")
    print(f"⚠️  Unmapped: {unmapped_count} concepts")
    
    if unmapped_concepts:
        print(f"\nTop 20 unmapped concepts:")
        for concept in unmapped_concepts[:20]:
            print(f"  - {concept}")
    
    # Commit changes
    conn.commit()
    print("\n✅ Changes committed to database")
    
    # Verify results
    print("\nVerifying normalization coverage...")
    cur.execute("""
        SELECT 
            COUNT(*) as total_facts,
            COUNT(normalized_label) as mapped_facts,
            ROUND(100.0 * COUNT(normalized_label) / COUNT(*), 2) as coverage_pct
        FROM financial_facts;
    """)
    
    total, mapped, coverage = cur.fetchone()
    print(f"  Total facts: {total:,}")
    print(f"  Mapped facts: {mapped:,}")
    print(f"  Coverage: {coverage}%")
    
    # Show top normalized labels
    print("\nTop 10 normalized labels by fact count:")
    cur.execute("""
        SELECT normalized_label, COUNT(*) as fact_count
        FROM financial_facts
        WHERE normalized_label IS NOT NULL
        GROUP BY normalized_label
        ORDER BY fact_count DESC
        LIMIT 10;
    """)
    
    for label, count in cur.fetchall():
        print(f"  {label}: {count:,}")
    
    cur.close()
    conn.close()
    
    print("\n" + "="*80)
    print("✅ Taxonomy normalization complete")


if __name__ == "__main__":
    apply_normalization_to_db()

