# 🚀 FinSight Deployment Plan

**Project:** FinSight - Financial Analysis Pipeline  
**Date:** October 30, 2025  
**Deployment Target:** jonashaahr.com/finsight  
**Traffic Estimate:** 5 visitors/month  
**Budget:** $0/month (free tier hosting)

---

## 📋 Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Technology Stack](#technology-stack)
3. [Local Development Setup](#local-development-setup)
4. [Backend Deployment (Railway)](#backend-deployment-railway)
5. [Database Setup](#database-setup)
6. [Frontend Integration](#frontend-integration)
7. [Resource Limits & Quotas](#resource-limits--quotas)
8. [Testing Strategy](#testing-strategy)
9. [Monitoring & Maintenance](#monitoring--maintenance)

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     USER INTERFACE                          │
│              jonashaahr.com/finsight (Next.js)             │
└────────────────────────┬────────────────────────────────────┘
                         │
         ┌───────────────┴───────────────┐
         │                               │
    [Pre-loaded]                   [Custom Request]
    13 companies                   User ticker + year
    Instant load                   ~2-5 min processing
         │                               │
         │                    ┌──────────┴──────────┐
         │                    │  Railway Backend    │
         │                    │  Flask/FastAPI API  │
         │                    └──────────┬──────────┘
         │                               │
         │                    ┌──────────┴──────────┐
         │                    │  ETL Pipeline       │
         │                    │  1. Fetch SEC       │
         │                    │  2. Parse XBRL      │
         │                    │  3. Normalize       │
         │                    │  4. Validate        │
         │                    └──────────┬──────────┘
         │                               │
         └───────────────┬───────────────┘
                         │
              ┌──────────┴──────────┐
              │  Railway PostgreSQL │
              │  1GB Free Tier      │
              │  ~25 companies max  │
              └──────────┬──────────┘
                         │
              ┌──────────┴──────────┐
              │   Return JSON       │
              │   Frontend renders  │
              │   Interactive charts│
              └─────────────────────┘

Optional: Link to Superset dashboard at analyses.nordicravensolutions.com
```

---

## 💻 Technology Stack

### **Frontend (Next.js on Vercel)**
- **Framework**: Next.js 16
- **UI**: Tailwind CSS, Recharts for charts
- **Location**: `/Users/jonas/Website/portfolio/app/finsight/page.tsx`
- **Deployment**: Auto-deploy via Vercel (already set up)
- **Cost**: $0/month

### **Backend (Railway)**
- **Framework**: Flask or FastAPI
- **Location**: `/Users/jonas/FinSight/api/` (new)
- **Processing**: Full ETL pipeline (Arelle + normalization)
- **Deployment**: Railway (500 hours/month free tier)
- **Cost**: $0/month (within free tier limits)

### **Database (Railway PostgreSQL)**
- **Type**: PostgreSQL 14+
- **Storage**: 1GB free tier
- **Capacity**: ~20-25 companies with full fact extraction
- **Backup**: Auto-backups on Railway
- **Cost**: $0/month

### **Analytics (Apache Superset)**
- **Hosting**: Local Docker container (already running)
- **Access**: analyses.nordicravensolutions.com (or local only)
- **Integration**: Screenshot + "View Dashboard" link
- **Cost**: $0/month

---

## 🔧 Local Development Setup

### **Separate Development Database**

**Purpose**: Test without consuming production quota

```bash
# 1. Create LOCAL test database (separate from production)
docker exec superset_db psql -U superset -c "CREATE DATABASE finsight_dev;"

# 2. Update config.py with environment detection
```

**config.py:**
```python
import os

ENV = os.getenv('ENVIRONMENT', 'development')

if ENV == 'production':
    POSTGRES_HOST = os.getenv('RAILWAY_POSTGRES_HOST')
    POSTGRES_PORT = os.getenv('RAILWAY_POSTGRES_PORT', '5432')
    POSTGRES_USER = os.getenv('RAILWAY_POSTGRES_USER')
    POSTGRES_PASSWORD = os.getenv('RAILWAY_POSTGRES_PASSWORD')
    POSTGRES_DB = 'finsight'
else:
    # Local development
    POSTGRES_HOST = 'localhost'
    POSTGRES_PORT = '5432'
    POSTGRES_USER = 'superset'
    POSTGRES_PASSWORD = 'superset'
    POSTGRES_DB = 'finsight_dev'  # Separate dev database

DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
```

### **Local Testing Workflow**

```bash
# Test pipeline locally (uses finsight_dev database)
cd /Users/jonas/FinSight
source .venv/bin/activate
python src/main.py --ticker AAPL --year 2024

# Test API locally
cd api
flask run  # or uvicorn main:app --reload

# Test frontend locally
cd /Users/jonas/Website/portfolio
npm run dev
# Visit: http://localhost:3000/finsight
```

**Benefits:**
- ✅ Unlimited local testing
- ✅ No quota consumption
- ✅ Separate from production data
- ✅ Can reset/wipe anytime

---

## 🌐 Backend Deployment (Railway)

### **Step 1: Prepare Backend Code**

**Create `/Users/jonas/FinSight/api/` directory:**

```bash
cd /Users/jonas/FinSight
mkdir -p api
```

**Files to create:**

1. **`api/main.py`** - Flask/FastAPI app
2. **`api/requirements.txt`** - Backend dependencies
3. **`api/Procfile`** - Railway startup command
4. **`api/.env.example`** - Environment template

### **Step 2: Create Railway Project**

1. Go to https://railway.app
2. **New Project** → **Deploy from GitHub repo**
3. Connect **FinSight** repository
4. **Settings:**
   - Root directory: `api/`
   - Build command: `pip install -r requirements.txt`
   - Start command: `python main.py` (or `gunicorn main:app`)

### **Step 3: Add Railway PostgreSQL**

1. In Railway project, click **+ New**
2. Select **Database** → **PostgreSQL**
3. Railway auto-generates connection variables:
   - `RAILWAY_POSTGRES_HOST`
   - `RAILWAY_POSTGRES_PORT`
   - `RAILWAY_POSTGRES_USER`
   - `RAILWAY_POSTGRES_PASSWORD`
   - `RAILWAY_POSTGRES_DB`

### **Step 4: Environment Variables**

Add to Railway:
```
ENVIRONMENT=production
PYTHONUNBUFFERED=1
MAX_CUSTOM_REQUESTS_PER_MONTH=10
ENABLE_CUSTOM_ANALYSIS=true
```

### **Step 5: Deploy**

Push to GitHub → Railway auto-deploys.

You'll get a URL like: `https://finsight-production.up.railway.app`

---

## 🗄️ Database Setup

### **Schema Migration**

```bash
# 1. Connect to Railway PostgreSQL
psql $DATABASE_URL

# 2. Run schema creation
\i database/schema.sql

# 3. Verify tables created
\dt
```

### **Pre-load Companies**

**Option A: From local processed data**
```bash
# Export from local dev DB
pg_dump -U superset -h localhost -d finsight_dev --data-only -t financial_facts > seed_data.sql

# Import to Railway
psql $RAILWAY_DATABASE_URL -f seed_data.sql
```

**Option B: Run ETL directly on Railway**
```bash
# SSH into Railway container (if needed)
railway run python ../src/main.py --ticker NVO --year 2024
```

**Option C: Bulk load script**
```bash
# Run locally, push to Railway DB
ENVIRONMENT=production python src/storage/load_to_db.py
```

### **Database Monitoring**

Check storage usage:
```sql
SELECT 
  pg_size_pretty(pg_database_size('railway')) as db_size,
  COUNT(*) as total_facts
FROM financial_facts;
```

**Alert when >800MB** (80% of 1GB limit)

---

## 🎨 Frontend Integration

### **Create `/Users/jonas/Website/portfolio/app/finsight/page.tsx`**

**Key Features:**

1. **Company Selector**
   - Dropdown with 13 pre-loaded companies
   - OR custom ticker input

2. **Warning Banner (for custom input)**
   ```tsx
   {showCustomInput && (
     <div className="bg-yellow-50 border-l-4 border-yellow-400 p-4 mb-6">
       <div className="flex">
         <div className="flex-shrink-0">
           <svg className="h-5 w-5 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
             <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
           </svg>
         </div>
         <div className="ml-3">
           <p className="text-sm text-yellow-700">
             <strong>Custom analysis takes 5-10 minutes</strong> to extract and process 10,000-40,000 financial facts from SEC filings.
             Limited to 10 custom requests per month due to free tier resources.
           </p>
         </div>
       </div>
     </div>
   )}
   ```

3. **Loading State**
   ```tsx
   {isProcessing && (
     <div className="text-center py-12">
       <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
       <p className="text-lg font-medium text-gray-900">Processing {ticker}...</p>
       <p className="text-sm text-gray-600 mt-2">
         Extracting financial data • Elapsed: {elapsed}s / ~300s
       </p>
       <div className="max-w-md mx-auto mt-4">
         <div className="bg-gray-200 rounded-full h-2">
           <div className="bg-blue-600 h-2 rounded-full transition-all" style={{ width: `${progress}%` }}></div>
         </div>
       </div>
     </div>
   )}
   ```

4. **Results Display**
   - Key metrics cards (Revenue, Net Income, Total Assets, etc.)
   - Interactive charts (Recharts: Line chart for trends)
   - Comparison table if multiple years
   - "View Full Superset Dashboard →" button

5. **Quota Exceeded Message**
   ```tsx
   {quotaExceeded && (
     <div className="bg-red-50 border-l-4 border-red-400 p-4">
       <p className="text-sm text-red-700">
         Monthly quota for custom analyses has been reached. 
         Pre-loaded companies are still available.
         <a href="#contact" className="font-semibold underline ml-1">Contact me</a> for dedicated access.
       </p>
     </div>
   )}
   ```

---

## 🎯 API Endpoints (Railway Backend)

### **`GET /api/companies`**
Returns list of pre-loaded companies

**Response:**
```json
{
  "preloaded": [
    {"ticker": "NVO", "name": "Novo Nordisk", "years": [2024]},
    {"ticker": "NVDA", "name": "NVIDIA", "years": [2023, 2024, 2025]},
    {"ticker": "AAPL", "name": "Apple", "years": [2023]},
    ...
  ],
  "quota": {
    "custom_requests_used": 3,
    "custom_requests_limit": 10,
    "resets_on": "2025-11-01"
  }
}
```

### **`GET /api/analyze/{ticker}/{year}`**
Fetch pre-loaded company data (instant)

**Response:**
```json
{
  "company": "NVO",
  "year": 2024,
  "metrics": {
    "revenue": {"value": 232400000000, "unit": "DKK", "label": "Total Revenue"},
    "net_income": {...},
    ...
  },
  "statements": {
    "income_statement": [...],
    "balance_sheet": [...],
    "cash_flow": [...]
  },
  "processing_time": 0.2,
  "source": "preloaded"
}
```

### **`POST /api/analyze/custom`**
Run full ETL for new company

**Request:**
```json
{
  "ticker": "TSLA",
  "year": 2024
}
```

**Response (async with polling or SSE):**
```json
{
  "status": "processing",
  "job_id": "uuid",
  "estimated_time": 300,
  "progress": {
    "stage": "extracting",
    "percent": 45,
    "message": "Extracting financial facts from XBRL..."
  }
}
```

**Status Endpoint:** `GET /api/analyze/custom/{job_id}`

---

## 📦 Resource Limits & Quotas

### **Database Storage Management**

**Capacity Planning:**
- 1GB free tier
- Each company-year: ~30-50MB (10k-40k facts)
- Pre-loaded (13 companies): ~650MB
- Remaining: ~350MB for custom requests (~7-10 companies)

**Implementation:**

```python
# api/quota.py
import os
from datetime import datetime
from sqlalchemy import func

def check_storage_quota(db):
    """Check if DB storage is under 800MB (80% threshold)"""
    result = db.execute("SELECT pg_database_size('railway') as size;")
    size_bytes = result.fetchone()[0]
    size_mb = size_bytes / (1024 * 1024)
    
    if size_mb > 800:
        return False, f"Storage limit reached ({size_mb:.0f}MB / 1000MB)"
    return True, f"{size_mb:.0f}MB / 1000MB used"

def check_monthly_quota():
    """Check custom analysis quota (10/month)"""
    # Store in Redis or simple JSON file
    current_month = datetime.now().strftime('%Y-%m')
    quota_file = 'data/quota.json'
    
    # Load current count
    if os.path.exists(quota_file):
        with open(quota_file, 'r') as f:
            quota_data = json.load(f)
            if quota_data.get('month') == current_month:
                count = quota_data.get('count', 0)
                if count >= 10:
                    return False, f"Monthly quota exceeded ({count}/10)"
                return True, f"{count}/10 used this month"
    
    return True, "0/10 used this month"

def increment_quota():
    """Increment custom analysis counter"""
    current_month = datetime.now().strftime('%Y-%m')
    quota_file = 'data/quota.json'
    
    if os.path.exists(quota_file):
        with open(quota_file, 'r') as f:
            quota_data = json.load(f)
    else:
        quota_data = {}
    
    if quota_data.get('month') != current_month:
        quota_data = {'month': current_month, 'count': 1}
    else:
        quota_data['count'] = quota_data.get('count', 0) + 1
    
    with open(quota_file, 'w') as f:
        json.dump(quota_data, f)
```

### **Processing Time Limits**

```python
# api/main.py
import signal
from contextlib import contextmanager

@contextmanager
def timeout(seconds):
    """Kill process if it exceeds time limit"""
    def timeout_handler(signum, frame):
        raise TimeoutError(f"Processing exceeded {seconds}s limit")
    
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)

# Usage
@app.post('/api/analyze/custom')
def analyze_custom(ticker: str, year: int):
    try:
        with timeout(600):  # 10 minute max
            result = run_full_pipeline(ticker, year)
            return result
    except TimeoutError:
        return {"error": "Processing timeout - company data too large"}, 504
```

---

## 🧪 Testing Strategy

### **Local Testing (Unlimited)**

**Development environment** - separate database:

```bash
# Set environment
export ENVIRONMENT=development

# Test full pipeline
python src/main.py --ticker AAPL --year 2024

# Test API locally
cd api
flask run

# Test frontend locally
cd /Users/jonas/Website/portfolio
npm run dev
# Visit: http://localhost:3000/finsight
```

**No quota limits** - test as much as you want.

### **Production Testing (Limited)**

Only test on Railway when:
- Final deployment verification
- Testing quota enforcement
- Load testing (use test ticker that doesn't consume quota)

**Test Mode Feature:**
```python
# api/main.py
TEST_TICKERS = ['TEST', 'DEMO']  # Don't count against quota

@app.post('/api/analyze/custom')
def analyze_custom(ticker: str, year: int):
    if ticker.upper() in TEST_TICKERS:
        # Return mock data, don't run pipeline, don't increment quota
        return generate_mock_response(ticker, year)
    
    # Real processing...
```

---

## 📝 Step-by-Step Deployment Checklist

### **Phase 1: Backend Setup (2-3 hours)**

- [ ] **1.1** Create `/Users/jonas/FinSight/api/` directory
- [ ] **1.2** Create Flask API with endpoints (see above)
- [ ] **1.3** Create `api/requirements.txt`:
  ```
  flask==3.0.0
  flask-cors==4.0.0
  gunicorn==21.2.0
  arelle-release
  pandas>=2.0.0
  sqlalchemy>=2.0.0
  psycopg2-binary>=2.9.0
  pydantic>=2.0.0
  python-dotenv>=1.0.0
  ```
- [ ] **1.4** Create `api/Procfile`:
  ```
  web: gunicorn main:app --bind 0.0.0.0:$PORT --timeout 600
  ```
- [ ] **1.5** Test API locally
- [ ] **1.6** Create Railway project
- [ ] **1.7** Connect GitHub repo (FinSight)
- [ ] **1.8** Configure root directory: `api/`
- [ ] **1.9** Add PostgreSQL database to Railway
- [ ] **1.10** Set environment variables
- [ ] **1.11** Deploy and verify

### **Phase 2: Database Migration (1 hour)**

- [ ] **2.1** Connect to Railway PostgreSQL:
  ```bash
  railway link  # Link to project
  railway connect postgres  # Get connection string
  ```
- [ ] **2.2** Run schema creation:
  ```bash
  psql $RAILWAY_DATABASE_URL -f database/schema.sql
  ```
- [ ] **2.3** Load pre-processed data:
  ```bash
  # Export from local
  python src/storage/export_to_json.py --output preload.json
  
  # Import to Railway
  ENVIRONMENT=production python src/storage/load_from_json.py --input preload.json
  ```
- [ ] **2.4** Verify data:
  ```sql
  SELECT company, fiscal_year_end, COUNT(*) as facts
  FROM financial_facts
  GROUP BY company, fiscal_year_end
  ORDER BY company, fiscal_year_end;
  ```

### **Phase 3: Frontend Development (3-4 hours)**

- [ ] **3.1** Create `/Users/jonas/Website/portfolio/app/finsight/page.tsx`
- [ ] **3.2** Add company selector dropdown
- [ ] **3.3** Add custom ticker input with warning banner
- [ ] **3.4** Implement API calls to Railway backend
- [ ] **3.5** Build results display:
  - [ ] Key metrics cards
  - [ ] Interactive charts (Recharts)
  - [ ] Download CSV button
  - [ ] Link to Superset dashboard
- [ ] **3.6** Add loading states and error handling
- [ ] **3.7** Test locally at `localhost:3000/finsight`
- [ ] **3.8** Update Projects.tsx to link to `/finsight`

### **Phase 4: Production Deployment (30 min)**

- [ ] **4.1** Push frontend to GitHub
- [ ] **4.2** Vercel auto-deploys (or manual deploy)
- [ ] **4.3** Test live site: `jonashaahr.com/finsight`
- [ ] **4.4** Verify Railway API connection
- [ ] **4.5** Test pre-loaded company (instant)
- [ ] **4.6** Test custom company (wait 5-10 min)
- [ ] **4.7** Verify quota enforcement

### **Phase 5: Monitoring Setup (1 hour)**

- [ ] **5.1** Set up Railway usage alerts
- [ ] **5.2** Create quota monitoring dashboard (simple JSON file)
- [ ] **5.3** Add analytics to track which companies are popular
- [ ] **5.4** Document API usage in README

---

## 🔒 Security & Rate Limiting

### **API Rate Limiting**

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["10 per hour"]  # Prevent abuse
)

@app.post('/api/analyze/custom')
@limiter.limit("2 per hour")  # Only 2 custom requests per IP per hour
def analyze_custom():
    ...
```

### **Input Validation**

```python
ALLOWED_TICKERS = set([
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 
    'NVO', 'LLY', 'JNJ', 'PFE', 'MRNA',
    # Add ~200 major tickers
])

def validate_ticker(ticker: str):
    if ticker.upper() not in ALLOWED_TICKERS:
        raise ValueError(f"Ticker {ticker} not supported")
```

---

## 📊 Monitoring & Maintenance

### **Weekly Checks**

1. **Database size**: `SELECT pg_database_size('railway');`
2. **Quota usage**: Check `data/quota.json`
3. **Error logs**: Railway dashboard
4. **API uptime**: Railway metrics

### **Monthly Tasks**

1. **Reset quota counter** (automatic on first request of month)
2. **Review popular companies** - pre-load if requested often
3. **Database cleanup** - Delete old custom analyses if storage >90%

### **Alerts to Set Up**

- Railway email alert when app crashes
- Database >900MB (approaching limit)
- More than 8 custom requests in a month (approaching quota)

---

## 🚨 Quota Exceeded Scenarios

### **Storage Quota (>900MB)**

**Backend response:**
```json
{
  "error": "storage_quota_exceeded",
  "message": "Database storage limit reached. Pre-loaded companies still available.",
  "contact": "jonas.haahr@aol.com"
}
```

**Frontend display:**
```tsx
<div className="bg-red-50 p-4 rounded-lg">
  <p className="text-red-800">
    Storage quota exceeded. Pre-loaded companies are still available.
    For dedicated analysis, <a href="mailto:jonas.haahr@aol.com">contact me</a>.
  </p>
</div>
```

### **Monthly Request Quota (>10)**

**Backend response:**
```json
{
  "error": "monthly_quota_exceeded",
  "message": "10 custom analyses this month. Quota resets Nov 1.",
  "next_reset": "2025-11-01T00:00:00Z"
}
```

---

## 🎬 Deployment Timeline

| Phase | Duration | Tasks |
|-------|----------|-------|
| Backend API | 3 hours | Flask app, Railway setup, DB migration |
| Frontend | 4 hours | Next.js page, charts, warning banners |
| Testing | 2 hours | Local + production smoke tests |
| Documentation | 1 hour | Update README, add usage examples |
| **Total** | **~10 hours** | End-to-end deployment |

---

## ✅ Success Criteria

- [ ] Pre-loaded companies load instantly (<1s)
- [ ] Custom analysis completes in 2-5 minutes
- [ ] Quota enforcement works (stops at 10/month)
- [ ] Storage monitoring alerts when >800MB
- [ ] Local dev environment works independently
- [ ] Frontend gracefully handles all error states
- [ ] Link to Superset dashboard works
- [ ] Mobile-responsive UI

---

## 🔗 External Links

- **Railway Dashboard**: https://railway.app/dashboard
- **Backend API**: `https://finsight-production.up.railway.app` (after deployment)
- **Frontend**: `https://jonashaahr.com/finsight`
- **Superset**: `analyses.nordicravensolutions.com` (or localhost)
- **GitHub Repo**: https://github.com/Nordic-OG-Raven/FinSight

---

## 📝 Notes

- **No Cloudflare for this project** - Railway better suited for Python backend
- **Pre-loading is key** - Most visitors will use pre-loaded data (instant)
- **Custom analysis is premium feature** - Showcases capability, limited to prevent abuse
- **Local testing unlimited** - Separate dev database ensures no quota consumption
- **Graceful degradation** - When quota hit, pre-loaded companies still work

---

**Status:** Ready to implement  
**Next Step:** Create Flask API in `/Users/jonas/FinSight/api/`

