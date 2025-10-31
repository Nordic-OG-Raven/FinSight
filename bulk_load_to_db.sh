#!/bin/bash
#
# Bulk load all extracted companies to Star Schema PostgreSQL Warehouse
# This is now a wrapper around database/load_financial_data.py
#

set -e

VENV_PATH="/Users/jonas/FinSight/.venv"
PROJECT_ROOT="/Users/jonas/FinSight"

cd "$PROJECT_ROOT"

echo "========================================================================"
echo "📥 Bulk Loading Financial Data to Star Schema Warehouse"
echo "========================================================================"
echo ""

echo "This script now uses the Star Schema warehouse loader."
echo "Calling database/load_financial_data.py..."
echo ""

# Simply call the proper star schema loader
"$VENV_PATH/bin/python" database/load_financial_data.py

echo ""
echo "========================================================================"
echo "✅ Bulk Load Complete!"
echo "========================================================================"
echo ""
echo "Note: This script is now a wrapper around database/load_financial_data.py"
echo "      which loads data into the proper star schema warehouse."
echo ""
echo "For more control, you can run directly:"
echo "  ./database/load_financial_data.sh"
echo ""

