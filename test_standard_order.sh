#!/bin/bash
#
# Test Standard Presentation Order Population
# Runs the new populate_standard_presentation_order.py script locally
#

set -e

PROJECT_ROOT="/Users/jonas/FinSight"
VENV_PATH="/Users/jonas/FinSight/.venv"

echo "========================================================================"
echo " Testing Standard Presentation Order Population"
echo "========================================================================"
echo ""

# Check virtual environment
if [ ! -d "$VENV_PATH" ]; then
    echo "❌ Virtual environment not found at $VENV_PATH"
    echo "   Please run: python -m venv $VENV_PATH"
    exit 1
fi

cd "$PROJECT_ROOT"

# Activate venv and run the script
echo "Running populate_standard_presentation_order.py..."
echo ""

"$VENV_PATH/bin/python" src/utils/populate_standard_presentation_order.py

echo ""
echo "✅ Test complete!"
echo ""
echo "To verify, check the database:"
echo "  SELECT source, COUNT(*) FROM rel_presentation_hierarchy GROUP BY source;"

