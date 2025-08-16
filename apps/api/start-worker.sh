#!/usr/bin/env bash
# Celery worker startup script with security hardening and proper error handling
set -euo pipefail

# Set environment variables
export PYTHONPATH=/app:${PYTHONPATH:-}
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1

# Configuration variables
WORKER_QUEUES=${WORKER_QUEUES:-"freecad,sim,cpu,postproc"}
WORKER_CONCURRENCY=${WORKER_CONCURRENCY:-2}
WORKER_LOGLEVEL=${WORKER_LOGLEVEL:-INFO}
WORKER_OPTIMIZATION=${WORKER_OPTIMIZATION:-fair}
WORKER_NAME=${WORKER_NAME:-worker}

echo "[WORKER] Starting Celery Worker..."
echo "[WORKER] Name: $WORKER_NAME"
echo "[WORKER] Queues: $WORKER_QUEUES"
echo "[WORKER] Concurrency: $WORKER_CONCURRENCY"
echo "[WORKER] Log Level: $WORKER_LOGLEVEL"
echo "[WORKER] Optimization: $WORKER_OPTIMIZATION"

# Wait for broker to be ready
echo "[WORKER] Waiting for RabbitMQ broker..."
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
        echo "[WORKER] Broker connection successful"
        break
    fi
    echo "[WORKER] Waiting for broker... ($i/30)"
    sleep 2
done

# Prepare Celery worker arguments
CELERY_ARGS=(
    "-A" "app.tasks.worker"
    "worker"
    "-Q" "$WORKER_QUEUES"
    "-O" "$WORKER_OPTIMIZATION"
    "--loglevel=$WORKER_LOGLEVEL"
    "--concurrency=$WORKER_CONCURRENCY"
    "--hostname=$WORKER_NAME@%h"
    "--time-limit=7200"      # 2 hours max task time
    "--soft-time-limit=3600" # 1 hour soft limit
    "--max-tasks-per-child=100"  # Restart worker after 100 tasks
    "--prefetch-multiplier=1"    # Fair scheduling
)

echo "[WORKER] Starting Celery with command: celery ${CELERY_ARGS[*]}"
exec celery "${CELERY_ARGS[@]}"