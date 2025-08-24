# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FreeCAD-based CNC/CAM/CAD production platform with Turkish UI/UX. Users generate 3D models and CAM simulations through prompts/parameters, create G-code, and manage manufacturing jobs via scalable queue system.

**Tech Stack**: FastAPI + Celery + Next.js + PostgreSQL + Redis + MinIO + RabbitMQ + FreeCAD  
**Repository**: https://github.com/cncaiprojem/projem  
**Development**: Docker Compose orchestration with hot-reload  
**Current Branch Strategy**: Feature branches from main, PRs always created with `--base main`

## Commands

### Quick Start
```bash
# Initial setup
make init          # Copy .env.example to .env
make dev          # Start full stack (all services)

# Individual services
docker compose -f infra/compose/docker-compose.dev.yml up api web
docker compose -f infra/compose/docker-compose.dev.yml up postgres redis minio rabbitmq
```

### Testing & Quality
```bash
# Run tests
make test                                    # All tests
pytest apps/api/tests -v                    # API tests verbose
pytest apps/api/tests/test_file.py::test_name  # Single test
pytest apps/api/tests/integration -v        # Integration tests
pytest apps/api/tests/performance -v        # Performance tests
cd apps/web && pnpm test                    # Web unit tests
cd apps/web && pnpm test:e2e               # Web E2E tests

# Code quality
make lint                                    # Run all linters
make fmt                                     # Auto-format all code
ruff check apps/api --fix                   # Fix Python linting issues
cd apps/web && pnpm typecheck              # TypeScript type checking

# Smoke tests
make run-freecad-smoke                      # Test FreeCAD integration
make run-s3-smoke                          # Test MinIO/S3 functionality
make test-celery-rabbitmq                   # Test queue configuration

# Task 6.10 Observability tests
python apps/api/scripts/test_task_6_10_coverage.py  # Verify observability coverage
```

### Database Operations
```bash
# Migrations
make migrate                                 # Apply migrations
alembic revision --autogenerate -m "desc"   # Create new migration
alembic downgrade -1                        # Rollback one migration
alembic history                             # View migration history

# Data management
make seed                                    # Full seed data
make seed-basics                           # Basic seed data only
docker exec -it fc_postgres_dev psql -U freecad -d freecad  # Direct DB access

# Migration integrity tests (Task 2.9)
make test-migration-integrity               # Complete migration test suite
make test-migration-safety                  # Upgrade/downgrade safety tests
make test-constraints                       # Database constraint validation
make test-audit-integrity                   # Audit chain cryptographic tests
make test-performance                       # Query performance tests
make test-turkish-compliance                # Turkish KVKK/GDPR compliance
```

### Development Utilities
```bash
# Service management
docker compose -f infra/compose/docker-compose.dev.yml logs -f api  # Follow logs
docker compose -f infra/compose/docker-compose.dev.yml restart api   # Restart service
docker compose -f infra/compose/docker-compose.dev.yml exec api bash # Shell access

# RabbitMQ management
make rabbitmq-setup                         # Initialize queues and DLX
make rabbitmq-status                        # Check cluster status
make dlq-status                            # Check Dead Letter Queue
make rabbitmq-ui                           # Open management UI (localhost:15672)

# Task 6.1 Queue Topology
./scripts/init-task-6.1-topology.sh         # Initialize new queue topology
python infra/rabbitmq/init_queues.py        # Direct topology initialization
python apps/api/app/scripts/test_dlx_dlq_topology.py  # Test topology

# Pre-commit hooks
make pre-commit-install                     # Install git hooks
make pre-commit-run                        # Run hooks on all files
```

## Architecture

### Service Ports
- **API**: http://localhost:8000 (FastAPI with Swagger at /docs)
- **Web**: http://localhost:3000 (Next.js)
- **PostgreSQL**: localhost:5432
- **Redis**: localhost:6379
- **MinIO**: http://localhost:9000 (Console: 9001, User: minioadmin, Pass: minioadmin)
- **RabbitMQ**: localhost:5672 (Management: http://localhost:15672, User: freecad, Pass: freecad_dev_pass)

### Project Structure
```
apps/
├── api/                    # FastAPI backend
│   ├── app/
│   │   ├── routers/       # API endpoints (auth, jobs, models, files)
│   │   ├── models/        # SQLAlchemy ORM models
│   │   ├── schemas/       # Pydantic validation schemas
│   │   ├── services/      # Business logic (freecad_service, s3, auth)
│   │   ├── tasks/         # Celery async tasks
│   │   ├── core/          # Settings, logging, database, security
│   │   └── scripts/       # Utility scripts (smoke tests, seeds)
│   └── alembic/           # Database migrations
│
└── web/                    # Next.js frontend
    ├── src/
    │   ├── app/           # App Router pages (Turkish UI)
    │   ├── components/    # React components (3D viewer, forms)
    │   ├── lib/          # API clients, utilities
    │   └── hooks/        # Custom React hooks
    └── public/           # Static assets

infra/
├── compose/               # Docker Compose configs
├── docker/               # Dockerfiles
├── minio/               # MinIO bootstrap scripts
└── rabbitmq/            # RabbitMQ init scripts
```

### Key Services & Queues

**Primary Queues (Task 6.1 Quorum Type)**:
- `default`: General AI tasks, maintenance (routing key: `jobs.ai`)
- `model`: FreeCAD model generation (routing key: `jobs.model`)
- `cam`: CAM path generation (routing key: `jobs.cam`)
- `sim`: Process simulation (routing key: `jobs.sim`)
- `report`: Report generation (routing key: `jobs.report`)
- `erp`: ERP integration (routing key: `jobs.erp`)

**Dead Letter Topology**:
- Each queue has its own DLX: `{queue}.dlx`
- Each DLX routes to a DLQ: `{queue}_dlq`
- DLQs use classic lazy queues for efficient storage
- Retry configuration: exponential backoff with jitter, queue-specific retry limits

**MinIO Buckets**:
- `artefacts`: CAD models, G-code files (versioned)
- `logs`: Application logs
- `reports`: Analysis reports
- `invoices`: Generated invoices

## Development Patterns

### API Development
```python
# Router pattern (apps/api/app/routers/jobs.py)
@router.post("/jobs", response_model=JobResponse)
async def create_job(
    job: JobCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Business logic in service layer
    return await job_service.create_job(db, job, current_user)

# Celery task pattern (apps/api/app/tasks/freecad_tasks.py)
@celery_app.task(bind=True, name="generate_model", queue="freecad")
def generate_model_task(self, job_id: str, params: dict):
    try:
        result = freecad_service.generate_model(params)
        s3_service.upload_file(result.file_path, f"models/{job_id}")
        return {"status": "success", "url": presigned_url}
    except Exception as e:
        self.retry(exc=e, countdown=60, max_retries=3)
```

### Frontend Development
```typescript
// API client pattern (apps/web/src/lib/api/jobs.ts)
export const jobsApi = {
  list: (params?: JobParams) => 
    apiClient.get<JobList>('/jobs', { params }),
  
  create: (data: JobCreate) =>
    apiClient.post<Job>('/jobs', data),
    
  getStatus: (id: string) =>
    apiClient.get<JobStatus>(`/jobs/${id}/status`)
}

// Component pattern with Turkish UI
export function JobList() {
  const { data, isLoading } = useQuery({
    queryKey: ['jobs'],
    queryFn: jobsApi.list
  })
  
  return (
    <div>
      <h1>İş Listesi</h1>
      {/* Turkish UI elements */}
    </div>
  )
}
```

### FreeCAD Integration
```python
# FreeCAD subprocess execution (apps/api/app/services/freecad_service.py)
def execute_freecad_script(script_path: str, params: dict) -> dict:
    cmd = [
        FREECADCMD_PATH,
        "-M", "/usr/share/freecad/Mod",
        "-c", script_path,
        "--", json.dumps(params)
    ]
    
    result = subprocess.run(
        cmd,
        capture_output=True,
        timeout=FREECAD_TIMEOUT,
        check=True
    )
    return json.loads(result.stdout)
```

## Environment Configuration

### Critical Environment Variables
```bash
# Authentication & Security
DEV_AUTH_BYPASS=true                       # Skip auth in dev (NEVER in prod)
SECRET_KEY=dev-secret-key-minimum-32-chars # Change in production
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com

# Database
DATABASE_URL=postgresql+psycopg2://freecad:password@postgres:5432/freecad

# Storage
AWS_S3_ENDPOINT=http://minio:9000
S3_BUCKET_NAME=artefacts

# Message Queue (Task 6.1)
RABBITMQ_URL=amqp://freecad:freecad_dev_pass@rabbitmq:5672/
RABBITMQ_USER=freecad
RABBITMQ_PASS=freecad_dev_pass

# FreeCAD
FREECADCMD_PATH=/usr/bin/FreeCADCmd       # Path to FreeCAD binary

# Frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

## Turkish Localization

All UI text must be in Turkish. Common terms:
- İş = Job
- Model = Model  
- Simülasyon = Simulation
- G-kodu = G-code
- Dosya = File
- Kullanıcı = User
- Ayarlar = Settings
- Rapor = Report
- Analiz = Analysis
- İşlem = Process/Operation

## Debugging

### Check Service Health
```bash
# Service status
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# API health
curl http://localhost:8000/healthz

# View logs
docker logs fc_api_dev --tail 50 -f

# Celery task monitoring (Task 6.1)
docker exec fc_worker_dev celery -A app.core.celery_app inspect active
docker exec fc_worker_dev celery -A app.core.celery_app inspect reserved
docker exec fc_worker_priority_dev celery -A app.core.celery_app inspect active_queues
```

### Common Issues & Solutions

**Database connection failed**:
```bash
docker exec fc_postgres_dev pg_isready
# If fails: docker compose -f infra/compose/docker-compose.dev.yml restart postgres
```

**MinIO access denied**:
```bash
# Check credentials match .env
docker exec fc_minio_dev mc admin info minio
```

**Celery tasks not processing**:
```bash
# Check worker status
docker logs fc_worker_dev --tail 100
docker logs fc_worker_priority_dev --tail 100  # Priority worker
# Check RabbitMQ connection
docker exec fc_rabbitmq_dev rabbitmqctl status
# Check queue bindings
curl -u freecad:freecad_dev_pass http://localhost:15672/api/bindings
```

**FreeCAD not found**:
```bash
# Verify FreeCAD installation in container
docker exec fc_freecad_dev FreeCADCmd --version
```

## Security Notes

- Never commit `.env` files (only `.env.example`)
- All file uploads go through MinIO/S3, never local filesystem
- Use presigned URLs for file access (expire in 1 hour)
- Input validation with Pydantic schemas
- SQL injection prevention via SQLAlchemy ORM
- Rate limiting on API endpoints
- CORS configured for frontend origin only

## Financial System Guidelines

### Enterprise Financial Precision Standards

Following Gemini Code Assist feedback, all financial operations must maintain the highest precision standards:

**1. Decimal-Only Financial Calculations**
```python
# ✅ CORRECT: Use Decimal for all monetary calculations
from decimal import Decimal, ROUND_HALF_UP

amount_decimal = Decimal(amount_cents) / Decimal('100')
tax_amount = (base_amount * tax_rate / Decimal('100')).quantize(
    Decimal('1'), rounding=ROUND_HALF_UP
)

# ❌ WRONG: Never use float for financial calculations
amount_float = amount_cents / 100.0  # Precision loss risk
```

**2. Enhanced Migration Safety**
```python
# ✅ CORRECT: Use enhanced enum creation
from alembic.migration_helpers import create_enum_type_safe

create_enum_type_safe('payment_status', ['pending', 'completed', 'failed'])

# ❌ WRONG: Direct enum creation without safety checks
op.execute("CREATE TYPE payment_status AS ENUM ('pending', 'completed', 'failed')")
```

**3. Import Organization Best Practices**
```python
# ✅ CORRECT: Organized imports with TYPE_CHECKING
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import BigInteger, CheckConstraint, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from .payment import Payment

# ❌ WRONG: Disorganized imports causing circular dependencies
from .payment import Payment  # Can cause circular import
```

**4. Financial Schema Validation**
```python
# ✅ CORRECT: Pydantic schemas with Decimal validation
class MonetaryAmount(BaseModel):
    amount_cents: PositiveInt
    
    @property
    def amount_decimal(self) -> Decimal:
        return Decimal(self.amount_cents) / Decimal('100')

# ❌ WRONG: Float-based financial schemas
class MonetaryAmount(BaseModel):
    amount_float: float  # Precision loss risk
```

**5. Turkish Financial Compliance**
- All monetary calculations use Turkish KDV standards (20% default)
- Currency constraints support TRY-first with multi-currency options
- Financial precision maintained for regulatory compliance
- Tax calculations use Decimal with ROUND_HALF_UP for consistency

## Git Workflow & PR Strategy

**IMPORTANT**: Follow this exact workflow for all changes:
1. All git operations handled by main agent, code changes by subagents
2. Always checkout from main: `git checkout main && git pull && git checkout -b fix/issue-name`
3. PRs must be created with `--base main` to ensure proper merging
4. Subagents MUST read ALL feedback using `gh api --paginate` before making fixes
5. Use context7 MCP for searching latest examples when stuck

## Task Management Integration

This project uses Task Master for task tracking. Common commands:
```bash
# View current tasks
mcp__task-master__get_tasks --projectRoot "$(pwd)"

# Get next task to work on
mcp__task-master__next_task --projectRoot "$(pwd)"

# Update task status
mcp__task-master__set_task_status --id "1.10" --status "done" --projectRoot "$(pwd)"

# Expand task into subtasks
mcp__task-master__expand_task --id "7" --projectRoot "$(pwd)"
```

### Observability Stack (Task 6.10)

**Structured Logging** (`app/core/logging_config.py`):
- TurkishCompliantFormatter with PII masking
- Request context binding
- Performance log filtering

**Prometheus Metrics** (`app/core/metrics.py`):
- Job orchestration metrics: creation, progress, duration
- Queue depth and DLQ monitoring
- Idempotency and audit chain tracking

**OpenTelemetry Tracing** (`app/core/telemetry.py`):
- Span creation with job context
- FastAPI and Celery instrumentation
- Job lifecycle tracing

**Grafana Dashboard** (`infra/grafana/task-6-10-job-orchestration-dashboard.json`):
- 16 panels for comprehensive monitoring
- Queue depths, job rates, error distributions
- DLQ replay and cancellation tracking

## Important Instruction Reminders

- Do what has been asked; nothing more, nothing less
- NEVER create files unless they're absolutely necessary for achieving your goal
- ALWAYS prefer editing an existing file to creating a new one
- NEVER proactively create documentation files (*.md) or README files unless explicitly requested