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

# Don't use set -e because we want to continue even if UI tests fail
# set -e  # Exit on error

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
RED='\033[0;31m'
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

# Enable unbuffered Python output for real-time progress bars
export PYTHONUNBUFFERED=1

# Step 1: Extract data using Python pipeline
echo -e "${BLUE}Step 1/3: Extracting XBRL data...${NC}"
echo "------------------------------------------------------------------------"

"$VENV_PATH/bin/python" -u src/main.py \
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

# Step 2: Load to PostgreSQL using proper ETL loader (star schema)
echo -e "${BLUE}Step 2/3: Loading to PostgreSQL (star schema)...${NC}"
echo "------------------------------------------------------------------------"

JSON_FILE="data/processed/${TICKER}_${YEAR}_${FILING_TYPE//-/}_facts.json"

if [ ! -f "$JSON_FILE" ]; then
    echo "❌ Extracted data not found: $JSON_FILE"
    exit 1
fi

echo "  → Loading JSON data to PostgreSQL using StarSchemaLoader..."
echo "  → File: $JSON_FILE"
echo "  → This applies normalization, validation, and loads into star schema"

# Use the proper ETL loader (database/load_financial_data.py)
# This loads into fact_financial_metrics (star schema), not financial_facts (old flat schema)
# Load only the specific file we just extracted
"$VENV_PATH/bin/python" -u database/load_financial_data.py "$JSON_FILE"

LOAD_EXIT_CODE=$?

if [ $LOAD_EXIT_CODE -ne 0 ]; then
    echo ""
    echo -e "${YELLOW}⚠️  Data loading failed. Check output above for details.${NC}"
    echo ""
fi

echo ""

# Step 3: Start API (if not already running)
echo -e "${BLUE}Step 3/4: Starting API...${NC}"
echo "------------------------------------------------------------------------"

FINSIGHT_API="/Users/jonas/FinSight/api"
FLASK_PORT=5001
API_LOG="/Users/jonas/FinSight/api.log"

# Function to check if API is running
check_api_status() {
    curl -s "http://localhost:$FLASK_PORT/health" > /dev/null 2>&1
}

# Function to kill process on port
kill_port() {
    local port=$1
    local pids=$(lsof -ti:$port 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo -e "${YELLOW}Killing existing processes on port $port...${NC}"
        echo "$pids" | xargs kill -9 2>/dev/null || true
        sleep 1
    fi
}

# Check if API is already running
if check_api_status; then
    echo -e "${GREEN}✅ API is already running on http://localhost:$FLASK_PORT${NC}"
else
    echo -e "${YELLOW}⚠️  API is not running at http://localhost:$FLASK_PORT${NC}"
    echo "   Starting API on port $FLASK_PORT..."
    
    # Kill any existing processes on the port
    kill_port $FLASK_PORT
    
    # Start Flask API
    cd "$FINSIGHT_API"
    source "$VENV_PATH/bin/activate"
    nohup python main.py > "$API_LOG" 2>&1 &
    FLASK_PID=$!
    echo $FLASK_PID > /tmp/flask_finsight.pid
    sleep 3
    
    # Verify Flask started
    if ! kill -0 $FLASK_PID 2>/dev/null; then
        echo -e "${RED}❌ Flask failed to start. Check $API_LOG${NC}"
        tail -20 "$API_LOG"
        exit 1
    fi
    
    # Wait for Flask to be ready
    API_READY=false
    for i in {1..30}; do
        if check_api_status; then
            echo -e "${GREEN}✅ Flask API running on http://localhost:$FLASK_PORT${NC}"
            API_READY=true
            break
        fi
        if [ $i -eq 30 ]; then
            echo -e "${RED}❌ Flask API not responding after 30s${NC}"
            tail -20 "$API_LOG"
            exit 1
        fi
        sleep 1
    done
    
    if [ "$API_READY" = false ]; then
        echo -e "${RED}❌ Failed to start API. Exiting.${NC}"
        exit 1
    fi
fi

cd "$PROJECT_ROOT"
echo ""

# Step 4: Run UI tests
echo -e "${BLUE}Step 4/4: Running UI tests...${NC}"
echo "------------------------------------------------------------------------"

"$VENV_PATH/bin/python" -u UITest.py \
    --ticker "$TICKER" \
    --year "$YEAR" \
    --test all \
    --api-base "http://localhost:$FLASK_PORT"

UI_TEST_EXIT_CODE=$?

if [ $UI_TEST_EXIT_CODE -ne 0 ]; then
    echo ""
    echo -e "${YELLOW}⚠️  UI tests failed. Check output above for details.${NC}"
    echo ""
fi

echo ""
echo "========================================================================"
if [ $UI_TEST_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✅ Pipeline Complete!${NC}"
else
    echo -e "${YELLOW}⚠️  Pipeline Complete with Warnings${NC}"
fi
echo "========================================================================"
echo ""
echo "📊 Database: finsight"
echo "📊 Tables: fact_financial_metrics (star schema)"
echo ""
echo "🌐 API: http://localhost:$FLASK_PORT/api/finsight"
echo "   Log file: $API_LOG"
if [ -f /tmp/flask_finsight.pid ]; then
    FLASK_PID=$(cat /tmp/flask_finsight.pid)
    echo "   Process ID: $FLASK_PID"
    echo "   To stop: kill $FLASK_PID"
fi
echo ""
echo "Next steps:"
echo "  1. Query data:"
echo "     docker exec superset_db psql -U superset -d finsight -c \"SELECT COUNT(*) FROM fact_financial_metrics;\""
echo ""
echo "  2. Connect Superset:"
echo "     Host: superset_db"
echo "     Port: 5432"
echo "     Database: finsight"
echo "     Username: superset"
echo "     Password: superset"
echo ""
echo "  3. Test API:"
echo "     curl http://localhost:$FLASK_PORT/health"
echo ""
echo "========================================================================"

