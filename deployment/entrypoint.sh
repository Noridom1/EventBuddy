#!/usr/bin/env bash
# Container entrypoint. Datastores (Postgres/Supabase + Redis) are reached directly
# over the public internet, so there is no overlay-network step. We apply database
# migrations on boot (best-effort — a transient DB hiccup must not stop the app from
# serving; the app already degrades gracefully when tables are missing), then exec
# the API server.
set -euo pipefail

echo "[entrypoint] applying database migrations (alembic upgrade head) ..."
if alembic upgrade head; then
  echo "[entrypoint] migrations applied (schema at head)."
else
  echo "[entrypoint] WARNING: alembic upgrade failed — continuing; memory features may degrade until the DB is reachable and migrated."
fi

exec uvicorn eventbuddy.main:app --host 0.0.0.0 --port "${PORT:-8080}"
