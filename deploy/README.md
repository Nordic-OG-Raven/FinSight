# Deploying FinSight (free stack)

The warehouse is small and read-mostly, so FinSight runs comfortably on free, non-expiring
tiers. Recommended layout:

```
Neon (Postgres)  ←  Fly.io (Flask API)  ←  Vercel (Next.js frontend)
       ↑                   ↑
  Modal (weekly   ────────┘   Groq (NP2SQL, already wired via GROQ_API_KEY)
  SEC ingestion)
```

Everything integrates through **one env var — `DATABASE_URL`** — which `config.py` reads, so
each layer just points at the same Neon connection string.

| Layer | Service | Notes |
|---|---|---|
| Database | **Neon** | Serverless Postgres, scale-to-zero, non-expiring. Create a DB, copy its `DATABASE_URL`. |
| API | **Fly.io** | `fly launch` against the existing Docker/Flask app; set `DATABASE_URL` (+ `GROQ_API_KEY`) as secrets. |
| Frontend | **Vercel** | Deploy `Website/portfolio`; point it at the Fly API URL. |
| NL→SQL | **Groq** | Already wired — set `GROQ_API_KEY` in the API's env. |
| Ingestion | **Modal** | Weekly SEC pull — see below. Chosen over GitHub Actions to avoid competing for Actions minutes. |

## API on Fly.io

The repo ships a `Dockerfile` (gunicorn + the Flask app) and `fly.toml` (Frankfurt region,
nearest to Neon's eu-central-1; scales to zero when idle). Deploy:

```bash
fly launch --no-deploy                 # first time — creates the app, keeps the existing fly.toml
fly secrets set \
  DATABASE_URL="<neon POOLED url>" \
  GROQ_API_KEY="<groq key>"            # secrets — never in fly.toml or git
fly deploy
fly open                               # or: curl https://<app>.fly.dev/health
```

The image installs `api/requirements.txt` and runs `gunicorn api.main:app` on `$PORT`. The DB
and LLM key come from Fly secrets (the app reads `DATABASE_URL` / `GROQ_API_KEY` from the env),
so no `.env` is baked into the image.

## Scheduled ingestion — Modal

`modal_ingest.py` runs the idempotent edgartools loader on a weekly cron (Mondays 06:00 UTC)
against the hosted warehouse. One-time setup:

```bash
pip install modal
modal token new                                   # authenticate (opens browser)
modal secret create finsight DATABASE_URL="<your Neon connection string>"
modal deploy deploy/modal_ingest.py               # deploy + schedule
modal run deploy/modal_ingest.py                  # (optional) trigger one run now
```

Tune the ticker set with a `FINSIGHT_TICKERS` env var on the secret (space-separated); it
defaults to the 8-filer reference set. The loader reuses existing filing rows, so re-runs that
find no new annual report are safe no-ops.

**One-platform alternative:** if you'd rather not add Modal, Fly.io scheduled Machines can run
the same loader on a cron — keeps DB, API, and ingestion on Fly.

## First load

After the DB exists and `DATABASE_URL` points at it, apply the schema and do an initial load:

```bash
psql "$DATABASE_URL" -f database/schema.sql          # (+ migrations/*.sql)
python database/load_from_edgartools.py              # extract → validate → load the reference set
```
