# Fly.io Migration Guide for FinSight

## Why Fly.io?

- ✅ **Free tier**: 3 shared CPUs, 256MB RAM, free PostgreSQL (3GB)
- ✅ **Docker support**: Your existing Dockerfile works
- ✅ **PostgreSQL included**: Free managed database
- ✅ **Similar to Railway**: Easy migration path
- ✅ **Global edge**: Fast response times

## Current Status

- **Railway**: Working but credits will run out
- **Storage**: 26MB / 1000MB (2.6% used)
- **Fly.io limit**: 3GB PostgreSQL (plenty of room!)

## Migration Steps

### 1. Install Fly.io CLI

```bash
# macOS
curl -L https://fly.io/install.sh | sh

# Or via Homebrew
brew install flyctl
```

### 2. Login to Fly.io

```bash
fly auth login
```

### 3. Create Fly.io App

```bash
cd /Users/jonas/FinSight
fly launch
```

This will:
- Detect your Dockerfile
- Ask for app name (e.g., `finsight-api`)
- Create `fly.toml` configuration

### 4. Create PostgreSQL Database

```bash
fly postgres create --name finsight-db
# Choose: Development (free tier)
```

This creates a free PostgreSQL database.

### 5. Attach Database to App

```bash
fly postgres attach finsight-db --app finsight-api
```

This automatically sets environment variables:
- `DATABASE_URL`
- `POSTGRES_HOST`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`

### 6. Update config.py (if needed)

Your `config.py` already checks for `DATABASE_URL` first, so it should work automatically!

### 7. Set Environment Variables

```bash
fly secrets set MAX_CUSTOM_REQUESTS_PER_MONTH=10
fly secrets set MAX_DB_SIZE_MB=900
fly secrets set ENVIRONMENT=production
```

### 8. Deploy

```bash
fly deploy
```

### 9. Get Your URL

```bash
fly status
# Will show: https://finsight-api.fly.dev
```

### 10. Migrate Database Data

**Option A: Export from Railway, Import to Fly.io**

```bash
# Export from Railway
railway connect postgres
pg_dump $DATABASE_URL > finsight_backup.sql

# Import to Fly.io
fly postgres connect -a finsight-db < finsight_backup.sql
```

**Option B: Re-run pipeline (if data is reproducible)**

```bash
fly ssh console -a finsight-api
python -c "from src.main import run_pipeline; run_pipeline(ticker='NVO', year=2024)"
# Repeat for all companies
```

### 11. Update Vercel Environment Variable

1. Go to Vercel dashboard
2. Update `NEXT_PUBLIC_FINSIGHT_API` to: `https://finsight-api.fly.dev`
3. Redeploy

## Fly.io Configuration File

Create `fly.toml` (or let `fly launch` create it):

```toml
app = "finsight-api"
primary_region = "iad"  # Choose closest region

[build]

[env]
  PORT = "8080"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = true
  auto_start_machines = true
  min_machines_running = 0
  processes = ["app"]

[[services]]
  protocol = "tcp"
  internal_port = 8080

  [[services.ports]]
    port = 80
    handlers = ["http"]
    force_https = true

  [[services.ports]]
    port = 443
    handlers = ["tls", "http"]
```

## Cost Comparison

| Platform | Monthly Cost | PostgreSQL | Limits |
|----------|-------------|------------|--------|
| Railway | $0 (until credits run out) | 1GB free | Credits expire |
| Fly.io | $0 | 3GB free | 3 VMs, 160GB transfer |
| Render | $0 | 90-day expiration | Sleeps after inactivity |

## Monitoring

```bash
# Check app status
fly status

# View logs
fly logs

# SSH into app
fly ssh console -a finsight-api

# Check database
fly postgres connect -a finsight-db
```

## Troubleshooting

**App won't start?**
- Check logs: `fly logs`
- Verify DATABASE_URL is set: `fly secrets list`

**Database connection fails?**
- Verify database is attached: `fly postgres list`
- Check connection: `fly postgres connect -a finsight-db`

**Out of memory?**
- Free tier: 256MB RAM
- Your app should be fine (Flask + PostgreSQL client)

## Next Steps

1. ✅ Test Railway migration (export data)
2. ✅ Set up Fly.io account
3. ✅ Deploy to Fly.io
4. ✅ Migrate database
5. ✅ Update Vercel environment variable
6. ✅ Test live deployment
7. ✅ Monitor for a few days
8. ✅ Shut down Railway (after confirming Fly.io works)

---

**Estimated migration time**: 30-60 minutes  
**Downtime**: Minimal (can run both in parallel during migration)

