# Docker Setup Guide

This document explains the secure, multi-stage Docker setup for the FreeCAD Platform API and Celery workers.

## Dockerfiles Overview

### 1. `Dockerfile` - FastAPI API Server
- **Purpose**: Serves the main FastAPI application with Uvicorn
- **Base**: python:3.11-slim-bookworm
- **Security**: Non-root user, minimal dependencies, multi-stage build
- **Health Check**: `/api/v1/healthz` endpoint

### 2. `Dockerfile.workers` - Celery Workers and Beat
- **Purpose**: Runs Celery workers and beat scheduler
- **Base**: python:3.11-slim-bookworm  
- **Security**: Non-root user, optimized for background processing
- **Health Check**: Celery ping command

## Security Features

### Multi-stage Builds
- **Builder stage**: Compiles dependencies and prepares wheels
- **Runtime stage**: Minimal production image with only runtime dependencies

### Security Hardening
- Non-root user (`app:app` with UID/GID 10001)
- Minimal base image (slim-bookworm)
- Only essential runtime dependencies
- Build cache optimization with BuildKit
- Comprehensive .dockerignore for minimal build context

### BuildKit Features
- Pip cache mounts for faster builds
- Optimized layer caching
- Parallel build stages

## Building Images

### API Server
```bash
# Build API image
docker build -f Dockerfile -t freecad-platform-api:latest .

# Build with BuildKit (recommended)
DOCKER_BUILDKIT=1 docker build -f Dockerfile -t freecad-platform-api:latest .
```

### Workers
```bash
# Build workers image
docker build -f Dockerfile.workers -t freecad-platform-workers:latest .

# Build with BuildKit (recommended)  
DOCKER_BUILDKIT=1 docker build -f Dockerfile.workers -t freecad-platform-workers:latest .
```

## Running Containers

### API Server
```bash
# Basic run
docker run -p 8000:8000 freecad-platform-api:latest

# With environment variables
docker run -p 8000:8000 \
  -e DATABASE_URL=postgresql://user:pass@host:5432/db \
  -e REDIS_URL=redis://host:6379/0 \
  freecad-platform-api:latest

# Development mode with reload
docker run -p 8000:8000 \
  -e ENV=development \
  -v $(pwd):/app \
  freecad-platform-api:latest
```

### Celery Workers
```bash
# Default worker (generic queues)
docker run freecad-platform-workers:latest

# Custom worker configuration
docker run \
  -e WORKER_QUEUES=freecad,sim \
  -e WORKER_CONCURRENCY=1 \
  -e WORKER_NAME=freecad-worker \
  freecad-platform-workers:latest

# Using startup script
docker run freecad-platform-workers:latest ./start-worker.sh

# Beat scheduler
docker run freecad-platform-workers:latest ./start-beat.sh
```

## Startup Scripts

### `/app/start.sh` - API Server
- Database connection waiting
- Alembic migrations
- Uvicorn configuration
- Development/production mode detection

### `/app/start-worker.sh` - Celery Worker
- Broker connection waiting
- Queue configuration
- Worker optimization settings
- Resource limits

### `/app/start-beat.sh` - Beat Scheduler
- Broker connection waiting
- Schedule file management
- PID file cleanup
- Beat configuration

## Environment Variables

### API Server
| Variable | Default | Description |
|----------|---------|-------------|
| `ENV` | `production` | Environment mode |
| `PORT` | `8000` | Server port |
| `HOST` | `0.0.0.0` | Server host |
| `WORKERS` | `2` | Uvicorn workers |
| `LOG_LEVEL` | `info` | Log level |
| `DATABASE_URL` | - | PostgreSQL connection |

### Workers
| Variable | Default | Description |
|----------|---------|-------------|
| `WORKER_QUEUES` | `freecad,sim,cpu,postproc` | Celery queues |
| `WORKER_CONCURRENCY` | `2` | Worker processes |
| `WORKER_LOGLEVEL` | `INFO` | Log level |
| `WORKER_OPTIMIZATION` | `fair` | Queue optimization |
| `WORKER_NAME` | `worker` | Worker hostname |

### Beat Scheduler
| Variable | Default | Description |
|----------|---------|-------------|
| `BEAT_LOGLEVEL` | `INFO` | Log level |
| `BEAT_SCHEDULE_FILE` | `/app/celery_beat/celerybeat-schedule` | Schedule file |
| `BEAT_PID_FILE` | `/app/celery_beat/celerybeat.pid` | PID file |

## Health Checks

### API Server
- **Endpoint**: `GET /api/v1/healthz`
- **Interval**: 30s
- **Timeout**: 10s
- **Retries**: 3
- **Start Period**: 40s

### Workers
- **Command**: `celery -A app.tasks.worker inspect ping`
- **Interval**: 30s
- **Timeout**: 10s  
- **Retries**: 3
- **Start Period**: 60s

## Production Deployment

### Docker Compose Updates
Update your `infra/compose/docker-compose.dev.yml` to use the new Dockerfiles:

```yaml
services:
  api:
    build:
      context: ./apps/api
      dockerfile: Dockerfile
    # ... rest of configuration

  worker:
    build:
      context: ./apps/api
      dockerfile: Dockerfile.workers
    command: ["./start-worker.sh"]
    environment:
      WORKER_QUEUES: "cpu,postproc"
      WORKER_CONCURRENCY: "4"
    # ... rest of configuration

  worker-freecad:
    build:
      context: ./apps/api
      dockerfile: Dockerfile.workers
    command: ["./start-worker.sh"]
    environment:
      WORKER_QUEUES: "freecad"
      WORKER_CONCURRENCY: "1"
      WORKER_NAME: "freecad-worker"
    # ... rest of configuration

  beat:
    build:
      context: ./apps/api
      dockerfile: Dockerfile.workers
    command: ["./start-beat.sh"]
    # ... rest of configuration
```

### Kubernetes Deployment
Update your Kubernetes manifests to use the new images and health checks.

## Troubleshooting

### Build Issues
1. **Permission denied**: Ensure Docker daemon is running
2. **Build context too large**: Check .dockerignore file
3. **Dependency conflicts**: Clear Docker build cache

### Runtime Issues
1. **Health check failures**: Check service dependencies
2. **Permission errors**: Verify non-root user setup
3. **Connection timeouts**: Increase startup wait times

### Worker Issues
1. **Broker connection failed**: Check RabbitMQ availability
2. **Task failures**: Review worker logs and resource limits
3. **Beat scheduling issues**: Verify PID file permissions

## Best Practices

1. **Always use BuildKit** for faster builds and better caching
2. **Pin dependency versions** in requirements.txt
3. **Use specific image tags** in production, not `latest`
4. **Monitor container resources** and adjust limits accordingly
5. **Regularly update base images** for security patches
6. **Use health checks** in all deployments
7. **Implement proper logging** and monitoring
8. **Test images locally** before production deployment

## Security Considerations

1. **Non-root execution**: All containers run as non-root user
2. **Minimal attack surface**: Only essential packages installed
3. **No secrets in images**: Use environment variables or secret management
4. **Regular security scans**: Scan images for vulnerabilities
5. **Network isolation**: Use proper Docker networks
6. **Resource limits**: Set CPU and memory limits
7. **Read-only filesystem**: Where possible, mount filesystems as read-only
