#!/bin/bash
# ============================================================================
# Load Financial Data into Star Schema Warehouse
# ============================================================================

set -e

PROJECT_ROOT="/Users/jonas/FinSight"
VENV_PATH="$PROJECT_ROOT/.venv"

cd "$PROJECT_ROOT"

echo "============================================================================"
echo "📥 Loading Financial Data"
echo "============================================================================"
echo ""

# Activate virtual environment and run loader
source "$VENV_PATH/bin/activate"
python database/load_financial_data.py

echo ""
echo "============================================================================"
echo "✅ Data loading complete!"
echo "============================================================================"

