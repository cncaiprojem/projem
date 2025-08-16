# MinIO Setup and Configuration

This directory contains MinIO setup scripts and configuration for the FreeCAD CNC/CAM platform.

## Overview

MinIO provides S3-compatible object storage for the platform with the following buckets:

- **artefacts**: Stores STL, STEP, G-code files and other CAD/CAM outputs (versioned)
- **logs**: Application and system logs
- **reports**: Generated reports and documentation
- **invoices**: Billing and invoice documents

## Bootstrap Process

The `createbuckets.sh` script automatically creates required buckets and configures policies when the MinIO service starts.

### Features

- **Idempotent execution**: Safe to run multiple times
- **Bucket versioning**: Enabled on artefacts bucket for file history
- **Security policies**: Private access by default, controlled via presigned URLs
- **Lifecycle management**: Automatic cleanup of incomplete uploads

## Docker Compose Integration

The bootstrap script runs automatically via the `minio-bootstrap` service:

```yaml
minio-bootstrap:
  image: minio/mc:RELEASE.2024-01-05T05-04-32Z
  container_name: fc_minio_bootstrap
  depends_on:
    minio:
      condition: service_healthy
  environment:
    MINIO_ROOT_USER: ${MINIO_ROOT_USER}
    MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
  volumes:
    - ./infra/minio/createbuckets.sh:/scripts/createbuckets.sh:ro
  entrypoint: ["/bin/sh", "/scripts/createbuckets.sh"]
  networks:
    - app-net
  restart: "no"
```

## Manual Bucket Management

You can manually run bucket operations using the MinIO client:

```bash
# Access MinIO container
docker exec -it fc_minio_bootstrap mc --help

# List buckets
docker exec -it fc_minio_bootstrap mc ls local/

# Check bucket versioning
docker exec -it fc_minio_bootstrap mc version info local/artefacts

# View bucket policies
docker exec -it fc_minio_bootstrap mc anonymous get local/artefacts
```

## Python S3 Service

The platform includes a comprehensive S3 service wrapper at `apps/api/app/services/s3.py` with:

- Presigned URL generation for secure uploads/downloads
- File operations (upload, download, delete, copy)
- Object listing and metadata retrieval
- Error handling and logging
- Content type detection

### Usage Example

```python
from app.services.s3 import get_s3_service

s3 = get_s3_service()

# Upload file
s3.upload_file(
    local_path="./model.stl",
    bucket="artefacts",
    object_key="models/part_001.stl"
)

# Generate download URL
url = s3.generate_presigned_download_url(
    bucket="artefacts",
    object_key="models/part_001.stl",
    expiry=timedelta(hours=1)
)
```

## Testing

Run the S3 functionality smoke test:

```bash
make run-s3-smoke
```

This tests:
- S3 connectivity
- Bucket availability
- File upload/download operations
- Presigned URL generation
- Object listing and metadata

## Environment Variables

Configure MinIO via environment variables in `.env`:

```env
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin
MINIO_PORT=9000
MINIO_CONSOLE_PORT=9001

# S3/MinIO Configuration
S3_BUCKET_ARTEFACTS=artefacts
S3_BUCKET_LOGS=logs
S3_BUCKET_REPORTS=reports
S3_BUCKET_INVOICES=invoices
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin
AWS_S3_ENDPOINT=http://minio:9000
AWS_S3_REGION=us-east-1
AWS_S3_SECURE=false
```

## Health Monitoring

The health check endpoint at `/api/v1/healthz` includes MinIO and bucket status:

```json
{
  "status": "ok",
  "dependencies": {
    "postgres": "ok",
    "redis": "ok",
    "s3": "ok",
    "s3_bucket_artefacts": "ok",
    "s3_bucket_logs": "ok",
    "s3_bucket_reports": "ok",
    "s3_bucket_invoices": "ok"
  }
}
```

## Security Considerations

- All buckets use private access by default
- File access is controlled via presigned URLs with configurable expiration
- No public read/write access is granted
- MinIO runs with security constraints (`no-new-privileges`)
- Credentials are managed via environment variables

## File Organization

Files are organized with consistent prefixes:

- `artefacts/models/` - STL and STEP files
- `artefacts/gcode/` - Generated G-code files
- `artefacts/toolpaths/` - CAM toolpath data
- `logs/api/` - API application logs
- `logs/workers/` - Worker process logs
- `reports/jobs/` - Job completion reports
- `invoices/monthly/` - Monthly billing data