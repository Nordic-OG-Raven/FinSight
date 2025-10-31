#!/bin/bash
# Start FinSight Streamlit Data Viewer

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "🚀 Starting FinSight Data Viewer"
echo "=========================================="
echo ""

# Activate venv and run streamlit
/Users/jonas/Thesis/.venv/bin/streamlit run src/ui/data_viewer.py \
  --server.port 8502 \
  --server.headless true \
  --browser.gatherUsageStats false

