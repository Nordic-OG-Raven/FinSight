# FinSight Deployment Status & Next Steps

**Last Updated**: November 5, 2025  
**Status**: ✅ Backend deployed, frontend working, needs sync

## Current Architecture

### ✅ What's Working

1. **Railway Backend API**: `https://finsight-production-d5c1.up.railway.app`
   - Flask API running
   - PostgreSQL database initialized (25.9MB / 1000MB = 2.6% used)
   - Star schema tables created
   - Data loaded for 11 companies

2. **Vercel Frontend**: `https://www.jonashaahr.com/finsight`
   - Next.js page working
   - Environment variable configured (`NEXT_PUBLIC_FINSIGHT_API`)
   - Successfully connecting to Railway backend
   - UI matches current production site

3. **Database**: Railway PostgreSQL
   - Storage: 25.9MB / 1000MB (97.4% free)
   - Quota: 0/10 custom requests used
   - **Capacity**: Can add ~35-40 more company-years (at ~25MB each)

### ⚠️ Issues Fixed

1. **Removed hardcoded fallback URL**: API route now requires environment variable
2. **Dynamic company list**: API now queries database instead of hardcoded list
3. **Better error handling**: Clear error messages if env var missing

### 📋 Streamlit vs Next.js (Important!)

**Streamlit (`src/ui/data_viewer_v2.py`)**: 
- Local development tool only
- Runs on `localhost:8502` for exploring the database
- **NOT used in production** - completely separate from website
- Safe to modify without affecting website

**Next.js (`Website/portfolio/app/finsight/page.tsx`)**:
- Production website UI
- **DO NOT break this** - keep current functionality
- Connects to Railway API via `/api/finsight` route

## Uncommitted Changes

**Status**: 40 commits ahead of origin/main, many uncommitted files

**Why website hasn't updated**: 
- Railway auto-deploys from GitHub
- Changes haven't been pushed, so Railway is running old code
- Vercel also auto-deploys from GitHub, so website is on old code too

## Next Steps

### 1. Add Missing Companies to Railway Database

**Available in processed files but not loaded**:
- AMZN 2023
- ASML 2023
- BAC 2023
- CAT 2023
- JPM 2023, 2024 (JPM 2024 not showing in API)
- WMT 2023

**Missing years** (already have company, need additional year):
- NVDA 2023 (currently shows 2023, 2024, 2025 - verify)
- NVDA 2025 (currently shows 2023, 2024, 2025 - verify)

**Storage calculation**:
- Current: 25.9MB for 11 companies
- Average: ~2.4MB per company-year
- Can add: ~400 more company-years (way more than needed!)
- **Recommendation**: Load all 6 missing companies + missing years = ~8-10 more company-years = ~20MB additional = **Still only 45MB total (4.5% of limit)**

### 2. Load Missing Data to Railway

**Option A: Use existing load script** (if it works with Railway):
```bash
cd /Users/jonas/FinSight
# Update database connection to point to Railway
# Then run:
./database/load_all_companies.sh
```

**Option B: Manual load via Railway CLI**:
```bash
# Connect to Railway
railway login
railway link

# Load each company
railway run python -c "from src.main import run_pipeline; run_pipeline(ticker='AMZN', year=2023)"
railway run python -c "from src.main import run_pipeline; run_pipeline(ticker='ASML', year=2023)"
# ... etc
```

**Option C: Export from local, import to Railway**:
```bash
# Export from local database
pg_dump local_db > export.sql

# Import to Railway
railway connect postgres
psql < export.sql
```

### 3. Commit and Push Changes

**Before pushing**:
1. Review all uncommitted changes
2. Test API changes locally if possible
3. Verify Railway database has all data

**Then push**:
```bash
cd /Users/jonas/FinSight
git add .
git commit -m "Update API to dynamically query companies from database"
git push origin main
# Railway will auto-deploy

cd /Users/jonas/Website/portfolio
git add .
git commit -m "Fix API route to require environment variable"
git push origin main
# Vercel will auto-deploy
```

### 4. Verify Deployment

After pushing:
1. Check Railway logs: Railway dashboard → Deployments
2. Test API: `curl https://finsight-production-d5c1.up.railway.app/api/companies`
3. Test website: Visit `https://www.jonashaahr.com/finsight`
4. Verify companies list shows all loaded companies

## Railway Configuration

**We ARE using Railway** - confirmed by:
- API URL: `https://finsight-production-d5c1.up.railway.app`
- Environment variable in Vercel points to Railway URL
- Railway auto-provides PostgreSQL connection vars

**No fallback needed** - if env var is missing, that's a configuration error that should fail fast.

## Storage Capacity

**Current**: 25.9MB / 1000MB (2.6%)  
**After adding 10 more company-years**: ~45MB / 1000MB (4.5%)  
**Remaining capacity**: ~955MB = ~400 more company-years possible

**Conclusion**: You have plenty of space. Load all available companies and years.

## Streamlit Development Tool

**Keep Streamlit separate** - it's a development tool:
- Located: `/Users/jonas/FinSight/src/ui/data_viewer_v2.py`
- Purpose: Local database exploration
- Run with: `./start_viewer.sh` or `streamlit run src/ui/data_viewer_v2.py`
- **Does NOT affect website** - modify freely for local dev work

## Summary

1. ✅ Backend deployed and working
2. ✅ Frontend deployed and working
3. ✅ API now dynamically queries database (no hardcoded list)
4. ✅ Environment variable properly configured (no fallback)
5. ⏳ Need to: Load missing companies, commit changes, push to GitHub

**Safe to modify**: Streamlit UI (local dev only)  
**Do NOT modify without testing**: Next.js frontend (production website)

