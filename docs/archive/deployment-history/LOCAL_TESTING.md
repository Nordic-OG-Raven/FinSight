# Local Testing Guide

## Prerequisites
- Docker Desktop installed
- Node.js 18+ installed
- Python 3.11+ installed

## Step 1: Start PostgreSQL Database

```bash
cd /Users/jonas/FinSight
docker-compose up postgres -d
```

This will:
- Start PostgreSQL on `localhost:5432`
- Create database `finsight_dev`
- Initialize tables from `init.sql`
- User: `superset`, Password: `superset`

## Step 2: Set Up Python API

```bash
cd api
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
```

## Step 3: Configure Environment

Create `api/.env`:
```
ENVIRONMENT=development
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=superset
POSTGRES_PASSWORD=superset
POSTGRES_DB=finsight_dev
MAX_CUSTOM_REQUESTS_PER_MONTH=10
MAX_DB_SIZE_MB=900
```

## Step 4: Pre-load Sample Data

```bash
cd /Users/jonas/FinSight
python -c "from src.main import run_pipeline; run_pipeline(ticker='NVO', year=2024)"
```

This will take 5-10 minutes to:
1. Fetch Novo Nordisk 10-K from SEC EDGAR
2. Parse XBRL with Arelle
3. Normalize ~30,000 financial facts
4. Validate and store in PostgreSQL

## Step 5: Start Flask API

```bash
cd api
python main.py
```

API will be available at `http://localhost:5000`

Test endpoints:
- `GET /health` - Health check
- `GET /api/companies` - List pre-loaded companies
- `GET /api/analyze/NVO/2024` - Get Novo Nordisk data
- `POST /api/analyze/custom` - Run custom analysis

## Step 6: Start Next.js Frontend

In a new terminal:

```bash
cd /Users/jonas/Website/portfolio
npm install
```

Add to `/Users/jonas/Website/portfolio/.env.local`:
```
NEXT_PUBLIC_FINSIGHT_API=http://localhost:5000
```

Then start dev server:
```bash
npm run dev
```

Frontend will be at `http://localhost:3000/finsight`

## Testing Flow

1. **Pre-loaded company** (instant):
   - Select "Novo Nordisk (NVO)" and year "2024"
   - Click "Analyze Company"
   - Should return results in <1 second

2. **Custom analysis** (5-10 min):
   - Switch to "Custom Analysis"
   - Enter ticker "AAPL" and year "2024"
   - Click "Analyze Company"
   - Watch progress bar (real-time ETL pipeline)
   - Results stored and cached for future instant access

## Cleanup

```bash
docker-compose down -v  # Stop and remove database
deactivate              # Exit Python venv
```

## Troubleshooting

**Database connection failed:**
```bash
docker ps  # Check if postgres is running
docker logs finsight_postgres  # Check logs
```

**API timeout:**
- Increase timeout in `main.py` (currently 600s)
- Some companies have 40k+ facts and take longer

**XBRL parsing errors:**
- Not all companies use standard taxonomies
- Try a different ticker from S&P 500

**Database full:**
- Each company uses ~10-50MB
- Monitor with: `docker exec finsight_postgres psql -U superset -d finsight_dev -c "SELECT pg_size_pretty(pg_database_size('finsight_dev'));"`

