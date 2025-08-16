#!/usr/bin/env bash
# Celery beat scheduler startup script with security hardening and proper error handling
set -euo pipefail

# Set environment variables
export PYTHONPATH=/app:${PYTHONPATH:-}
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1

# Configuration variables
BEAT_LOGLEVEL=${BEAT_LOGLEVEL:-INFO}
BEAT_SCHEDULE_FILE=${BEAT_SCHEDULE_FILE:-/app/celery_beat/celerybeat-schedule}
BEAT_PID_FILE=${BEAT_PID_FILE:-/app/celery_beat/celerybeat.pid}

echo "[BEAT] Starting Celery Beat Scheduler..."
echo "[BEAT] Log Level: $BEAT_LOGLEVEL"
echo "[BEAT] Schedule File: $BEAT_SCHEDULE_FILE"
echo "[BEAT] PID File: $BEAT_PID_FILE"

# Wait for broker to be ready
echo "[BEAT] Waiting for RabbitMQ broker..."
for i in {1..30}; do
    if python3 -c "
import celery
from app.tasks.worker import celery_app
try:
    celery_app.control.inspect().stats()
    print('Broker connection successful')
    exit(0)
except Exception as e:
    print(f'Broker check failed: {e}')
    exit(1)
" 2>/dev/null; then
        echo "[BEAT] Broker connection successful"
        break
    fi
    echo "[BEAT] Waiting for broker... ($i/30)"
    sleep 2
done

# Ensure beat directories exist
mkdir -p "$(dirname "$BEAT_SCHEDULE_FILE")"
mkdir -p "$(dirname "$BEAT_PID_FILE")"

# Clean up any existing PID file
if [ -f "$BEAT_PID_FILE" ]; then
    echo "[BEAT] Removing stale PID file: $BEAT_PID_FILE"
    rm -f "$BEAT_PID_FILE"
fi

# Prepare Celery beat arguments
CELERY_ARGS=(
    "-A" "app.tasks.worker"
    "beat"
    "--loglevel=$BEAT_LOGLEVEL"
    "--schedule=$BEAT_SCHEDULE_FILE"
    "--pidfile=$BEAT_PID_FILE"
    "--max-interval=60"    # Max sleep interval between checks
)

echo "[BEAT] Starting Celery Beat with command: celery ${CELERY_ARGS[*]}"
exec celery "${CELERY_ARGS[@]}"