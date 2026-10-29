#!/usr/bin/env bash
# Run dbt against Neon with credentials parsed from $DATABASE_URL (or ../.env).
#
# Why a wrapper: the Neon DATABASE_URL contains "&channel_binding=require", which breaks a
# naive `source .env`, and dbt needs the DIRECT (non-pooler) endpoint for DDL. We parse the URL
# in Python (robust) and inject discrete DBT_PG_* env vars that profiles.yml reads.
#
# Works locally (uses ../.venv + ../.env) and in CI (uses $DATABASE_URL + PATH `dbt`).
#
# Usage: ./run_dbt.sh debug|run|test|seed|build|docs ... [dbt args]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$HERE/../.env"

# Python + dbt: prefer the local venv, fall back to PATH (CI installs into system python).
if [ -x "$HERE/../.venv/bin/python" ]; then PY="$HERE/../.venv/bin/python"; else PY="$(command -v python3)"; fi
if [ -x "$HERE/../.venv/bin/dbt" ]; then DBT="$HERE/../.venv/bin/dbt"; else DBT="$(command -v dbt)"; fi

eval "$("$PY" - "$ENV_FILE" <<'PY'
import os, shlex, sys
from urllib.parse import urlparse

# DATABASE_URL from the environment (CI) takes precedence; otherwise read it from ../.env (local).
url = os.environ.get("DATABASE_URL")
if not url:
    from dotenv import dotenv_values
    url = dotenv_values(sys.argv[1])["DATABASE_URL"]
u = urlparse(url)
host = (u.hostname or "").replace("-pooler", "")  # DIRECT endpoint: DDL cannot use the pooler
emit = {
    "DBT_PG_HOST": host,
    "DBT_PG_PORT": str(u.port or 5432),
    "DBT_PG_USER": u.username or "",
    "DBT_PG_PASSWORD": u.password or "",
    "DBT_PG_DBNAME": (u.path or "/neondb").lstrip("/"),
}
for k, v in emit.items():
    print(f"export {k}={shlex.quote(v)}")
PY
)"

export DBT_PROFILES_DIR="$HERE"
cd "$HERE"
exec "$DBT" "$@"
