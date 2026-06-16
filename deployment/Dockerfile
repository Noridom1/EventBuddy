FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080
WORKDIR /app
# ca-certificates is needed for TLS to the cloud datastores (Supabase, Redis) and
# the MaaS endpoint. psycopg[binary] ships its own libpq, so no compiler is required.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
# src layout: the package build (egg_info) needs src/, so copy it before install.
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .
COPY alembic/ ./alembic/
COPY alembic.ini ./
# Landing page served at "/" and the installable Teams package at "/download/eventbuddy.zip"
# (Impl 11). Resolved CWD-relative (from /app) at request time; missing files degrade to 404.
COPY landing_page/ ./landing_page/
COPY teams-app/eventbuddy.zip ./teams-app/eventbuddy.zip
COPY deployment/entrypoint.sh ./deployment/
RUN chmod +x ./deployment/entrypoint.sh
EXPOSE 8080
# Entrypoint applies DB migrations (best-effort) then execs uvicorn. Datastores are
# reached directly over the public internet — no overlay network.
CMD ["./deployment/entrypoint.sh"]
