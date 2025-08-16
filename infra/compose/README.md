# FreeCAD Platform Development Docker Compose

Comprehensive development environment setup for the FreeCAD-based CNC/CAM/CAD production platform.

## Overview

The `docker-compose.dev.yml` file provides a complete development stack including:

- **Database Tier**: PostgreSQL 16, Redis 7.2
- **Message Queue**: RabbitMQ 3.13 with management interface
- **Object Storage**: MinIO with bucket bootstrapping
- **Application Tier**: FastAPI backend, Celery workers, Next.js frontend
- **Utility Services**: FreeCAD, CAMotics, FFmpeg, ClamAV (optional)

## Quick Start

1. **Start the complete stack:**
   ```bash
   cd /path/to/project
   docker-compose -f infra/compose/docker-compose.dev.yml up -d
   ```

2. **Run smoke tests:**
   ```bash
   ./scripts/smoke.sh
   ```

3. **Access services:**
   - Web Application: http://localhost:3000
   - API Documentation: http://localhost:8000/docs
   - MinIO Console: http://localhost:9001
   - RabbitMQ Management: http://localhost:15672

## Service Configuration

### Core Services

| Service    | Port  | Health Check | Purpose |
|------------|-------|--------------|---------|
| postgres   | 5432  | pg_isready   | Primary database |
| redis      | 6379  | redis ping   | Cache & sessions |
| rabbitmq   | 5672/15672 | rabbitmq-diagnostics | Message broker |
| minio      | 9000/9001 | HTTP health | Object storage |
| api        | 8000  | /api/v1/healthz | Backend API |
| web        | 3000  | /healthz | Frontend app |

### Worker Services

- **workers**: General purpose Celery workers (cpu, postproc queues)
- **beat**: Celery scheduler for periodic tasks

### Utility Services

- **freecad**: CAD/CAM processing utility
- **camotics**: G-code simulation utility  
- **ffmpeg**: Video processing utility
- **clamav**: Antivirus scanning (optional, security profile)

## Networks

- **backend**: Internal services communication (172.20.0.0/16)
- **frontend**: Web tier communication (172.21.0.0/16)

## Volumes & Data Persistence

Data is persisted in `./data/` subdirectories:

```
data/
├── postgres-dev/    # PostgreSQL data
├── redis-dev/       # Redis persistence
├── rabbitmq-dev/    # RabbitMQ data
├── minio-dev/       # MinIO object storage
├── api-logs/        # Application logs
├── worker-logs/     # Worker logs
├── beat-logs/       # Scheduler logs
├── freecad-temp/    # FreeCAD temporary files
└── clamav-db/       # ClamAV virus database
```

## Security Features

- Non-root users where applicable
- Read-only filesystems for utility services
- Security options (no-new-privileges)
- Resource limits and reservations
- Network isolation between tiers

## Development Features

- **Hot Reload**: API and web services support code changes
- **Debug Logging**: Verbose logging enabled for all services
- **Port Exposure**: All services exposed for debugging
- **Volume Mounts**: Source code mounted for development

## Common Commands

### Service Management

```bash
# Start all services
docker-compose -f infra/compose/docker-compose.dev.yml up -d

# Start with security services
docker-compose -f infra/compose/docker-compose.dev.yml --profile security up -d

# Start specific service
docker-compose -f infra/compose/docker-compose.dev.yml up -d api

# View logs
docker-compose -f infra/compose/docker-compose.dev.yml logs -f api

# Scale workers
docker-compose -f infra/compose/docker-compose.dev.yml up -d --scale workers=3

# Check service health
docker-compose -f infra/compose/docker-compose.dev.yml ps

# Stop services
docker-compose -f infra/compose/docker-compose.dev.yml down

# Stop and remove volumes
docker-compose -f infra/compose/docker-compose.dev.yml down -v
```

### Rebuild and Restart

```bash
# Rebuild specific service
docker-compose -f infra/compose/docker-compose.dev.yml build api

# Rebuild and restart
docker-compose -f infra/compose/docker-compose.dev.yml up -d --build --force-recreate
```

### Debugging

```bash
# Execute command in service
docker-compose -f infra/compose/docker-compose.dev.yml exec api bash

# View service configuration
docker-compose -f infra/compose/docker-compose.dev.yml config

# Check resource usage
docker stats $(docker-compose -f infra/compose/docker-compose.dev.yml ps -q)
```

## Smoke Testing

The included smoke test script (`scripts/smoke.sh`) provides comprehensive testing:

```bash
# Basic smoke test
./scripts/smoke.sh

# Extended timeout and verbose output
./scripts/smoke.sh --timeout=600 --verbose

# Skip utility services
./scripts/smoke.sh --skip-utilities

# Show help
./scripts/smoke.sh --help
```

### Test Categories

1. **Service Health Checks**: Verify all services are healthy
2. **Connectivity Tests**: Test database, cache, and broker connections
3. **HTTP Endpoint Tests**: Verify web endpoints respond correctly
4. **Version Checks**: Ensure services report expected versions
5. **Functional Tests**: Test key functionality like bucket creation

## Environment Variables

Key environment variables (configure in `.env`):

```env
# Database
POSTGRES_USER=freecad
POSTGRES_PASSWORD=freecad_dev_pass
POSTGRES_DB=freecad

# Message Broker
RABBITMQ_USER=freecad
RABBITMQ_PASS=freecad_dev_pass

# Object Storage
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin_dev_pass

# API Keys
OPENAI_API_KEY=your_openai_key_here

# Ports (optional)
API_PORT=8000
WEB_PORT=3000
POSTGRES_PORT=5432
REDIS_PORT=6379
```

## Troubleshooting

### Common Issues

1. **Service won't start**: Check logs and dependencies
2. **Health checks failing**: Verify service configuration
3. **Port conflicts**: Adjust port mappings in environment
4. **Volume permissions**: Ensure data directories are writable
5. **Memory issues**: Reduce resource limits for development

### Diagnostic Commands

```bash
# Check service status
docker-compose -f infra/compose/docker-compose.dev.yml ps

# View service logs
docker-compose -f infra/compose/docker-compose.dev.yml logs service_name

# Check resource usage
docker stats

# Inspect service configuration
docker-compose -f infra/compose/docker-compose.dev.yml config service_name

# Debug networking
docker network ls
docker network inspect freecad-platform-dev_backend
```

### Performance Tuning

For development workstations with limited resources:

1. **Reduce worker concurrency** in worker services
2. **Lower resource limits** in deploy sections
3. **Disable unused utility services** 
4. **Use smaller database shared_buffers**
5. **Reduce health check frequency**

## Integration with Project

This compose file integrates with:

- **Makefile targets**: `make dev`, `make build`, etc.
- **Development scripts**: Hot reload, testing, debugging
- **CI/CD pipelines**: Automated testing and deployment
- **Production deployment**: Helm charts in `/charts`

## Security Considerations

- Default passwords are for development only
- Use proper secrets management in production
- Network isolation prevents unauthorized access
- Read-only filesystems limit attack surface
- Regular security scanning with ClamAV (optional)

For production deployment, see `/charts/cnc/` Helm charts.