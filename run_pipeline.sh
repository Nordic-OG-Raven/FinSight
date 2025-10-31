#!/bin/bash
#
# FinSight Data Pipeline
# 
# Complete pipeline for extracting financial data from XBRL filings
# and loading into PostgreSQL data warehouse.
#
# Usage:
#   ./run_pipeline.sh                    # Extract NVO (Novo Nordisk)
#   ./run_pipeline.sh AAPL 2023 10-K    # Extract Apple 2023 10-K
#

set -e  # Exit on error

# Configuration
TICKER="${1:-NVO}"
YEAR="${2:-2024}"
FILING_TYPE="${3:-20-F}"
VENV_PATH="/Users/jonas/FinSight/.venv"
PROJECT_ROOT="/Users/jonas/FinSight"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================================================"
echo " FinSight Data Pipeline"
echo "========================================================================"
echo "Company: $TICKER"
echo "Year: $YEAR"
echo "Filing Type: $FILING_TYPE"
echo "========================================================================"
echo ""

# Check virtual environment
if [ ! -d "$VENV_PATH" ]; then
    echo "❌ Virtual environment not found at $VENV_PATH"
    echo "   Please run: python -m venv $VENV_PATH"
    exit 1
fi

# Check Docker
if ! docker ps > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker Desktop."
    exit 1
fi

# Check PostgreSQL container
if ! docker ps | grep -q "superset_db"; then
    echo "❌ Container 'superset_db' not running. Start Superset first."
    exit 1
fi

cd "$PROJECT_ROOT"

# Step 1: Extract data using Python pipeline
echo -e "${BLUE}Step 1/2: Extracting XBRL data...${NC}"
echo "------------------------------------------------------------------------"

"$VENV_PATH/bin/python" src/main.py \
    --ticker "$TICKER" \
    --year "$YEAR" \
    --filing-type "$FILING_TYPE" \
    --skip-download  # Use existing files if available

EXTRACTION_EXIT_CODE=$?

if [ $EXTRACTION_EXIT_CODE -ne 0 ]; then
    echo ""
    echo -e "${YELLOW}Note: If extraction failed due to parsing errors,${NC}"
    echo -e "${YELLOW}the data may already be extracted. Continuing...${NC}"
fi

echo ""

# Step 2: Load to PostgreSQL (using existing JSON)
echo -e "${BLUE}Step 2/2: Loading to PostgreSQL...${NC}"
echo "------------------------------------------------------------------------"

JSON_FILE="data/processed/${TICKER}_${YEAR}_${FILING_TYPE//-/}_facts.json"

if [ ! -f "$JSON_FILE" ]; then
    echo "❌ Extracted data not found: $JSON_FILE"
    exit 1
fi

echo "  → Loading JSON data to PostgreSQL..."
echo "  → File: $JSON_FILE"

# Convert JSON to CSV for easy loading
CSV_FILE="/tmp/finsight_${TICKER}_${YEAR}.csv"

"$VENV_PATH/bin/python" << PYTHON
import json
import pandas as pd

# Load JSON
with open('$JSON_FILE') as f:
    data = json.load(f)

facts = data['facts']
df = pd.DataFrame(facts)

# Select key columns for database
columns = ['concept', 'taxonomy', 'value_text', 'value_numeric', 
           'period_type', 'period_end', 'unit_measure']
df_export = df[[col for col in columns if col in df.columns]]

# Add metadata
df_export.insert(0, 'company', '$TICKER')
df_export.insert(1, 'filing_type', '$FILING_TYPE')  
df_export.insert(2, 'fiscal_year_end', '$YEAR-12-31')

df_export.to_csv('$CSV_FILE', index=False)
print(f"  → Prepared {len(df_export)} facts for loading")
PYTHON

# Copy to Docker and load
echo "  → Copying to Docker container..."
docker cp "$CSV_FILE" superset_db:/tmp/finsight_data.csv

echo "  → Loading to database..."
docker exec superset_db psql -U superset -d finsight << SQL
-- Ensure table exists
CREATE TABLE IF NOT EXISTS financial_facts (
    id SERIAL PRIMARY KEY,
    company VARCHAR(50),
    filing_type VARCHAR(20),
    fiscal_year_end DATE,
    concept TEXT,
    taxonomy VARCHAR(50),
    value_text TEXT,
    value_numeric DOUBLE PRECISION,  -- Changed from DECIMAL(20,4) to handle large numbers
    period_type VARCHAR(20),
    period_end DATE,
    unit_measure VARCHAR(50)
);

-- Load data (delete old data for this company/year first)
DELETE FROM financial_facts 
WHERE company = '$TICKER' 
  AND EXTRACT(YEAR FROM fiscal_year_end) = $YEAR;

-- Copy from CSV
\COPY financial_facts(company, filing_type, fiscal_year_end, concept, taxonomy, value_text, value_numeric, period_type, period_end, unit_measure) FROM '/tmp/finsight_data.csv' WITH CSV HEADER;

-- Show stats
SELECT 
    company,
    filing_type,
    fiscal_year_end,
    COUNT(*) as fact_count
FROM financial_facts
GROUP BY company, filing_type, fiscal_year_end
ORDER BY company, fiscal_year_end DESC;
SQL

# Cleanup
rm -f "$CSV_FILE"

echo ""
echo "========================================================================"
echo -e "${GREEN}✅ Pipeline Complete!${NC}"
echo "========================================================================"
echo ""
echo "📊 Database: finsight"
echo "📊 Table: financial_facts"
echo ""
echo "Next steps:"
echo "  1. Query data:"
echo "     docker exec superset_db psql -U superset -d finsight -c \"SELECT COUNT(*) FROM financial_facts;\""
echo ""
echo "  2. Connect Superset:"
echo "     Host: superset_db"
echo "     Port: 5432"
echo "     Database: finsight"
echo "     Username: superset"
echo "     Password: superset"
echo ""
echo "========================================================================"

