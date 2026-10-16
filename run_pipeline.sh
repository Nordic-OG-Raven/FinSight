#!/bin/bash
#
# FinSight Data Pipeline (edgartools path)
#
# Extract → validate → load one filing into the PostgreSQL star schema, start the API, and
# smoke-test it. Extraction/validation/loading all run in src/main.py (which reuses the
# StarSchemaLoader); the retired Arelle pipeline is gone — see docs/REARCHITECTURE.md.
#
# Usage:
#   ./run_pipeline.sh                 # AVGO (the dashboard demo company)
#   ./run_pipeline.sh NVO 20-F        # a specific ticker + filing form
#   ./run_pipeline.sh AAPL            # form auto-detected
#
# (A second argument that looks like a year is accepted and ignored — the edgartools path
#  always loads the latest annual filing.)

TICKER="${1:-AVGO}"
ARG2="${2:-}"
# Back-compat: old callers passed YEAR as $2 and FILING_TYPE as $3. If $2 is a 4-digit year,
# treat $3 as the filing type; otherwise $2 itself is the filing type.
if [[ "$ARG2" =~ ^[0-9]{4}$ ]]; then
    FILING_TYPE="${3:-}"
else
    FILING_TYPE="$ARG2"
fi

VENV_PATH="/Users/jonas/FinSight/.venv"
PROJECT_ROOT="/Users/jonas/FinSight"
FLASK_PORT=5001
API_LOG="/Users/jonas/FinSight/api.log"

GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

echo "========================================================================"
echo " FinSight Data Pipeline (edgartools path)"
echo "========================================================================"
echo "Company: $TICKER${FILING_TYPE:+   Filing: $FILING_TYPE}"
echo "========================================================================"
echo ""

# --- preflight ----------------------------------------------------------------
if [ ! -d "$VENV_PATH" ]; then
    echo -e "${RED}❌ Virtual environment not found at $VENV_PATH${NC}"
    echo "   Please run: python3 -m venv $VENV_PATH && $VENV_PATH/bin/pip install -r requirements.txt"
    exit 1
fi
if ! docker ps > /dev/null 2>&1; then
    echo -e "${RED}❌ Docker is not running. Please start Docker Desktop.${NC}"; exit 1
fi
if ! docker ps | grep -q "superset_db"; then
    echo -e "${RED}❌ Container 'superset_db' not running. Start Superset first.${NC}"; exit 1
fi

cd "$PROJECT_ROOT"
export PYTHONUNBUFFERED=1

# --- Step 1: extract + validate + load ---------------------------------------
echo -e "${BLUE}Step 1/3: Extract + validate + load...${NC}"
echo "------------------------------------------------------------------------"
"$VENV_PATH/bin/python" -u src/main.py --ticker "$TICKER" ${FILING_TYPE:+--filing-type "$FILING_TYPE"}
LOAD_EXIT_CODE=$?
if [ $LOAD_EXIT_CODE -ne 0 ]; then
    echo -e "${RED}❌ Load failed the validation gate — data not persisted. See above.${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Loaded; quality report in data/quality_reports/${NC}"
echo ""

# --- Step 2: start API (if not already up) -----------------------------------
echo -e "${BLUE}Step 2/3: Starting API...${NC}"
echo "------------------------------------------------------------------------"
check_api_status() { curl -s "http://localhost:$FLASK_PORT/health" > /dev/null 2>&1; }

if check_api_status; then
    echo -e "${GREEN}✅ API already running on http://localhost:$FLASK_PORT${NC}"
else
    echo "   Starting API on port $FLASK_PORT..."
    pids=$(lsof -ti:$FLASK_PORT 2>/dev/null || true)
    [ -n "$pids" ] && echo "$pids" | xargs kill -9 2>/dev/null || true
    cd "$PROJECT_ROOT/api"
    source "$VENV_PATH/bin/activate"
    nohup python main.py > "$API_LOG" 2>&1 &
    FLASK_PID=$!
    echo $FLASK_PID > /tmp/flask_finsight.pid
    cd "$PROJECT_ROOT"
    API_READY=false
    for i in {1..30}; do
        if check_api_status; then
            echo -e "${GREEN}✅ API running on http://localhost:$FLASK_PORT${NC}"; API_READY=true; break
        fi
        sleep 1
    done
    if [ "$API_READY" = false ]; then
        echo -e "${RED}❌ API not responding after 30s. Check $API_LOG${NC}"; tail -20 "$API_LOG"; exit 1
    fi
fi
echo ""

# --- Step 3: smoke-test the warehouse-direct endpoint ------------------------
echo -e "${BLUE}Step 3/3: Smoke-testing /api/financials/$TICKER...${NC}"
echo "------------------------------------------------------------------------"
"$VENV_PATH/bin/python" - "$TICKER" "$FLASK_PORT" <<'PY'
import sys, json, urllib.request
ticker, port = sys.argv[1], sys.argv[2]
try:
    with urllib.request.urlopen(f"http://localhost:{port}/api/financials/{ticker}", timeout=10) as r:
        d = json.load(r)
    years, cur, fye = d.get("years"), d.get("currency"), d.get("fiscal_year_end")
    if not years:
        print(f"❌ no years returned for {ticker}"); sys.exit(1)
    print(f"✅ {ticker}: {cur}, FYE {fye}, years {years}")
except Exception as e:
    print(f"❌ smoke test failed: {type(e).__name__}: {e}"); sys.exit(1)
PY
SMOKE=$?

echo ""
echo "========================================================================"
if [ $SMOKE -eq 0 ]; then
    echo -e "${GREEN}✅ Pipeline Complete — $TICKER extracted, validated, loaded, and served.${NC}"
else
    echo -e "${YELLOW}⚠️  Loaded, but the API smoke test did not pass. Check above.${NC}"
fi
echo "========================================================================"
echo "📊 Database: finsight · fact_financial_metrics (star schema)"
echo "🌐 API: http://localhost:$FLASK_PORT   (health: /health, data: /api/financials/$TICKER)"
echo "📝 Quality report: data/quality_reports/"
echo "========================================================================"
exit $SMOKE
