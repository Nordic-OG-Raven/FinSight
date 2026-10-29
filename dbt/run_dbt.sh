#!/usr/bin/env bash
# Run dbt against Neon with credentials parsed from ../.env.
#
# Why a wrapper: the Neon DATABASE_URL contains "&channel_binding=require", which breaks a
# naive `source .env`, and dbt needs the DIRECT (non-pooler) endpoint for DDL. We parse the URL
# in Python (robust) and inject discrete DBT_PG_* env vars that profiles.yml reads.
#
# Usage: ./run_dbt.sh debug|run|test|seed|build|docs ... [dbt args]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/../.venv/bin/python"
ENV_FILE="$HERE/../.env"

eval "$("$PY" - "$ENV_FILE" <<'PY'
import shlex, sys
from urllib.parse import urlparse
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
exec "$HERE/../.venv/bin/dbt" "$@"
