#!/usr/bin/env bash
# FastAPI startup script with security hardening and proper error handling
set -euo pipefail

# Set environment variables
export PYTHONPATH=/app:${PYTHONPATH:-}
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1

# Configuration variables
ENV=${ENV:-production}
PORT=${PORT:-8000}
HOST=${HOST:-0.0.0.0}
WORKERS=${WORKERS:-2}
LOG_LEVEL=${LOG_LEVEL:-info}

echo "[API] Starting FreeCAD Platform API..."
echo "[API] Environment: $ENV"
echo "[API] Port: $PORT"
echo "[API] Workers: $WORKERS"
echo "[API] Log Level: $LOG_LEVEL"

# Wait for database to be ready
echo "[API] Waiting for database connection..."
for i in {1..30}; do
    if python3 -c "import psycopg2; psycopg2.connect('$DATABASE_URL')" 2>/dev/null; then
        echo "[API] Database connection successful"
        break
    fi
    echo "[API] Waiting for database... ($i/30)"
    sleep 2
done

# Run database migrations
if command -v alembic >/dev/null 2>&1; then
    echo "[API] Running Alembic migrations..."
    alembic upgrade head || {
        echo "[API] Migration failed, but continuing startup"
    }
else
    echo "[API] Alembic not found, skipping migrations"
fi

# Prepare Uvicorn arguments
UVICORN_ARGS=(
    "app.main:app"
    "--host" "$HOST"
    "--port" "$PORT"
    "--workers" "$WORKERS"
    "--log-level" "$LOG_LEVEL"
    "--proxy-headers"
    "--forwarded-allow-ips" "*"
    "--access-log"
)

# Add reload only in development
if [ "$ENV" = "development" ]; then
    echo "[API] Development mode: enabling auto-reload"
    UVICORN_ARGS+=("--reload")
    # Reduce workers to 1 in development for reload to work
    UVICORN_ARGS[5]="1"
else
    echo "[API] Production mode: optimizing for performance"
fi

echo "[API] Starting Uvicorn with command: uvicorn ${UVICORN_ARGS[*]}"
exec uvicorn "${UVICORN_ARGS[@]}"


