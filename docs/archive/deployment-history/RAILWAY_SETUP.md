# Railway Deployment Guide

## Step 1: Create Railway Account & Project

1. Go to [railway.app](https://railway.app)
2. Sign in with GitHub
3. Click **"New Project"**
4. Select **"Deploy from GitHub repo"**
5. Choose **Nordic-OG-Raven/FinSight**
6. Railway will auto-detect the Dockerfile ✅

## Step 2: Add PostgreSQL Database

1. In your Railway project, click **"+ New"**
2. Select **"Database"** → **"Add PostgreSQL"**
3. Railway automatically creates:
   - `RAILWAY_POSTGRES_HOST`
   - `RAILWAY_POSTGRES_PORT`
   - `RAILWAY_POSTGRES_USER`
   - `RAILWAY_POSTGRES_PASSWORD`
   - `RAILWAY_POSTGRES_DB`
4. These are auto-injected into your Flask app ✅

## Step 3: Configure Environment Variables

Railway already has the PostgreSQL vars, but you can add optional ones:

1. Click on your **Flask service** (not the database)
2. Go to **"Variables"** tab
3. Add these (optional):

```
MAX_CUSTOM_REQUESTS_PER_MONTH=10
MAX_DB_SIZE_MB=900
ENVIRONMENT=production
```

## Step 4: Deploy!

1. Railway automatically builds and deploys on push
2. First build takes ~5-10 minutes (installing Arelle, etc.)
3. Watch the **"Deployments"** tab for progress
4. Once deployed, you'll get a URL like: `https://finsight-production-xxxx.up.railway.app`

## Step 5: Initialize Database

Railway's PostgreSQL starts empty. You have two options:

### Option A: Let API create tables on first request (automatic)
- The Flask API will create tables when it first connects
- Just make your first API call

### Option B: Run init.sql manually (recommended)
```bash
# Get Railway PostgreSQL connection string from dashboard
railway login
railway link
railway connect postgres

# Then run:
\i /path/to/FinSight/init.sql
```

## Step 6: Get Your API URL

1. In Railway dashboard, click your **Flask service**
2. Go to **"Settings"** tab
3. Scroll to **"Networking"**
4. Click **"Generate Domain"**
5. Copy the URL (e.g., `https://finsight-production-xxxx.up.railway.app`)

## Step 7: Update Vercel Environment Variable

1. Go to [vercel.com](https://vercel.com) dashboard
2. Select your **portfolio** project
3. Go to **Settings** → **Environment Variables**
4. Add:
   - **Key**: `NEXT_PUBLIC_FINSIGHT_API`
   - **Value**: `https://your-railway-url.up.railway.app`
   - **Environment**: Production, Preview, Development (check all)
5. Click **"Save"**
6. Redeploy your portfolio (automatic or manual trigger)

## Step 8: Test the Live System

1. Visit `https://jonashaahr.com/finsight`
2. Try selecting a pre-loaded company
3. Click "Analyze Company"
4. You should see: "Backend API is not available..." (expected - no data yet)

## Step 9: Pre-load Sample Data (Optional but Recommended)

### Connect to Railway PostgreSQL from your Mac:

```bash
# Install psql if you don't have it
brew install postgresql

# Get connection string from Railway dashboard
# Format: postgresql://user:pass@host:port/database

# Connect
psql "postgresql://postgres:PASSWORD@HOSTNAME.railway.internal:5432/railway"

# Or use Railway CLI
railway login
railway link
railway run python -c "from src.main import run_pipeline; run_pipeline(ticker='NVO', year=2024)"
```

This will populate the database so visitors can see instant results!

## Free Tier Limits

Railway's free tier includes:
- **$5 credit/month** (~500 hours execution time)
- **1GB PostgreSQL storage**
- **100GB bandwidth**

For a portfolio project with low traffic, this should be plenty!

## Monitoring

Watch these in Railway dashboard:
- **Database size**: Keep under 1GB (each company ~30MB)
- **Execution time**: Monitor monthly hours
- **Memory**: Should stay under 512MB

## Troubleshooting

**Build fails?**
- Check Dockerfile syntax
- Make sure all files are committed to GitHub
- Check Railway build logs for specific errors

**Database connection fails?**
- Railway auto-provides connection vars
- Check that PostgreSQL service is running
- Verify `config.py` correctly reads `RAILWAY_POSTGRES_*` vars

**Timeout errors?**
- Custom analysis takes 5-10 minutes
- Railway free tier may timeout on long requests
- Consider pre-loading data instead

**API returns 404?**
- Make sure you generated a domain in Railway
- Check that Flask app is running (port $PORT)
- Verify gunicorn command in Dockerfile

---

Once deployed, your FinSight architecture will be:

```
User (Browser)
    ↓
Vercel (Next.js Frontend)
    ↓
Railway (Flask API + PostgreSQL)
    ↓
SEC EDGAR (Data Source)
```

Ready to rock! 🚀

