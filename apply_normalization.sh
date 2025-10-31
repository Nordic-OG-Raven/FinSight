#!/bin/bash
# Apply taxonomy normalization to all facts in database

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "="
echo "📊 APPLYING TAXONOMY NORMALIZATION"
echo "="*80

# Step 1: Generate normalization mappings from Python
echo "Generating normalization mappings..."
/Users/jonas/Thesis/.venv/bin/python << 'PYTHON'
import sys
sys.path.insert(0, 'src/utils')
from taxonomy_mappings import get_normalized_label

# Get all concepts from database via Docker
import subprocess
import json

result = subprocess.run([
    'docker', 'exec', 'superset_db',
    'psql', '-U', 'superset', '-d', 'finsight', '-t', '-A',
    '-c', "SELECT DISTINCT concept FROM financial_facts WHERE concept IS NOT NULL;"
], capture_output=True, text=True)

concepts = [line.strip() for line in result.stdout.split('\n') if line.strip()]
print(f"Found {len(concepts)} unique concepts")

# Generate UPDATE statements
updates = []
mapped_count = 0
unmapped_concepts = []

for concept in concepts:
    normalized = get_normalized_label(concept)
    if normalized:
        # Escape single quotes in concept names
        safe_concept = concept.replace("'", "''")
        updates.append(f"UPDATE financial_facts SET normalized_label = '{normalized}' WHERE concept = '{safe_concept}';")
        mapped_count += 1
    else:
        unmapped_concepts.append(concept)

print(f"\n✅ Mapped: {mapped_count} concepts")
print(f"⚠️  Unmapped: {len(unmapped_concepts)} concepts")

# Write SQL to file
with open('temp_normalization.sql', 'w') as f:
    f.write("BEGIN;\n")
    for update in updates:
        f.write(update + "\n")
    f.write("COMMIT;\n")

print("\n✅ SQL script generated")

# Show sample unmapped concepts
if unmapped_concepts:
    print(f"\nSample unmapped concepts (first 10):")
    for concept in unmapped_concepts[:10]:
        print(f"  - {concept}")

PYTHON

echo ""
echo "Applying mappings to database..."
docker exec -i superset_db psql -U superset -d finsight < temp_normalization.sql

echo ""
echo "Cleaning up temporary files..."
rm temp_normalization.sql

echo ""
echo "="*80
echo "📊 NORMALIZATION STATISTICS"
echo "="*80

# Verify results
docker exec superset_db psql -U superset -d finsight << 'SQL'
SELECT 
    COUNT(*) as total_facts,
    COUNT(normalized_label) as mapped_facts,
    ROUND(100.0 * COUNT(normalized_label) / COUNT(*), 2) as coverage_pct
FROM financial_facts;

-- Top normalized labels
SELECT '
Top 10 normalized labels:' as info;
SELECT normalized_label, COUNT(*) as fact_count
FROM financial_facts
WHERE normalized_label IS NOT NULL
GROUP BY normalized_label
ORDER BY fact_count DESC
LIMIT 10;
SQL

echo ""
echo "="*80
echo "✅ TAXONOMY NORMALIZATION COMPLETE"
echo "="*80

