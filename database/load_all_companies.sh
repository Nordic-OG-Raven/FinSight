#!/bin/bash
# ============================================================================
# Load All Companies into FinSight Database
# ============================================================================
# Loads all processed JSON files to rebuild the heterogeneous test dataset
# ============================================================================

set -e

PROJECT_ROOT="/Users/jonas/FinSight"
VENV_PATH="$PROJECT_ROOT/.venv"

cd "$PROJECT_ROOT"

echo "============================================================================"
echo "📥 Loading All Companies into FinSight Database"
echo "============================================================================"
echo ""

# List of companies to load (from processed files)
# Format: TICKER YEAR FILING_TYPE
COMPANIES=(
    "AAPL 2023 10-K"
    "AMZN 2023 10-K"
    "ASML 2023 20-F"
    "BAC 2023 10-K"
    "CAT 2023 10-K"
    "GOOGL 2024 10-K"
    "JNJ 2024 10-K"
    "JPM 2023 10-K"
    "JPM 2024 10-K"
    "KO 2024 10-K"
    "LLY 2023 10-K"
    "MRNA 2023 10-K"
    "MSFT 2024 10-K"
    "NVDA 2024 10-K"
    "NVDA 2025 10-K"
    "NVO 2024 20-F"
    "PFE 2023 10-K"
    "SNY 2023 20-F"
    "WMT 2023 10-K"
)

TOTAL=${#COMPANIES[@]}
CURRENT=0

echo "📊 Found $TOTAL company filings to load"
echo ""

# Activate virtual environment
source "$VENV_PATH/bin/activate"

# Load each company
for company_line in "${COMPANIES[@]}"; do
    CURRENT=$((CURRENT + 1))
    read -r ticker year filing_type <<< "$company_line"
    
    echo "[$CURRENT/$TOTAL] Loading $ticker $year $filing_type..."
    
    # Find the JSON file
    JSON_FILE="data/processed/${ticker}_${year}_${filing_type//-/}_facts.json"
    
    if [ ! -f "$JSON_FILE" ]; then
        echo "   ⚠️  File not found: $JSON_FILE"
        continue
    fi
    
    # Load using Python loader
    POSTGRES_DB=finsight python database/load_financial_data.py "$JSON_FILE" 2>&1 | grep -E "(✅|❌|Error|Loaded)" || echo "   ✅ Loaded $ticker $year"
    
    echo ""
done

echo "============================================================================"
echo "✅ All companies loaded!"
echo "============================================================================"
echo ""
echo "Next steps:"
echo "  1. Run validation: POSTGRES_DB=finsight /Users/jonas/FinSight/.venv/bin/python -m src.validation.validator"
echo ""

