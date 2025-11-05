"""
Apply taxonomy normalization to existing data in PostgreSQL star schema.

This script updates the normalized_label column in dim_concepts table.
"""
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import psycopg2
from src.utils.taxonomy_mappings import get_normalized_label
import os


def apply_normalization_to_db():
    """Apply normalization mappings to dim_concepts in star schema."""
    
    # Use environment variables or defaults
    conn = psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', '127.0.0.1'),
        port=os.getenv('POSTGRES_PORT', '5432'),
        user=os.getenv('POSTGRES_USER', 'superset'),
        password=os.getenv('POSTGRES_PASSWORD', 'superset'),
        database=os.getenv('POSTGRES_DB', 'finsight')
    )
    
    cur = conn.cursor()
    
    # Get all concepts from dim_concepts
    print("Fetching all concepts from dim_concepts...")
    cur.execute("SELECT concept_id, concept_name, taxonomy FROM dim_concepts;")
    concepts = cur.fetchall()
    print(f"Found {len(concepts)} concepts")
    
    # Apply normalization
    print("\nApplying taxonomy mappings to dim_concepts...")
    mapped_count = 0
    unmapped_count = 0
    unmapped_concepts = []
    
    for concept_id, concept_name, taxonomy in concepts:
        normalized = get_normalized_label(concept_name)
        
        if normalized:
            cur.execute(
                "UPDATE dim_concepts SET normalized_label = %s WHERE concept_id = %s;",
                (normalized, concept_id)
            )
            mapped_count += 1
            
            if mapped_count % 50 == 0:
                sys.stdout.write(f"\r  Mapped: {mapped_count}/{len(concepts)}")
                sys.stdout.flush()
        else:
            unmapped_count += 1
            unmapped_concepts.append(concept_name)
    
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
            COUNT(*) as total_concepts,
            COUNT(*) FILTER (WHERE normalized_label IS NOT NULL) as normalized_concepts,
            ROUND(100.0 * COUNT(*) FILTER (WHERE normalized_label IS NOT NULL) / COUNT(*), 1) as coverage_pct
        FROM dim_concepts;
    """)
    
    total, mapped, coverage = cur.fetchone()
    print(f"  Total concepts: {total:,}")
    print(f"  Normalized concepts: {mapped:,}")
    print(f"  Coverage: {coverage}%")
    
    # Show top normalized labels by fact count
    print("\nTop 10 normalized labels by fact count:")
    cur.execute("""
        SELECT co.normalized_label, COUNT(*) as fact_count
        FROM fact_financial_metrics f
        JOIN dim_concepts co ON f.concept_id = co.concept_id
        WHERE co.normalized_label IS NOT NULL
        GROUP BY co.normalized_label
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

