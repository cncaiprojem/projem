#!/bin/sh
# MinIO Bucket Bootstrap Script
# Creates required buckets for FreeCAD CNC/CAM platform
# Supports idempotent execution - safe to run multiple times

set -e

# Wait for MinIO to be ready
echo "Waiting for MinIO to be ready..."
until mc alias set local http://minio:9000 "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}"; do
    echo "MinIO not ready, waiting 5 seconds..."
    sleep 5
done

echo "MinIO is ready. Setting up buckets and policies..."

# Define buckets to create
BUCKETS="artefacts logs reports invoices"

# Create buckets (idempotent - ignore if exists)
for bucket in $BUCKETS; do
    echo "Creating bucket: $bucket"
    mc mb --ignore-existing "local/$bucket" || {
        echo "Warning: Failed to create bucket $bucket, but continuing..."
    }
done

# Enable versioning on artefacts bucket
echo "Enabling versioning on artefacts bucket..."
mc version enable "local/artefacts" || {
    echo "Warning: Failed to enable versioning on artefacts bucket"
}

# Set bucket policies for controlled access
echo "Setting bucket policies..."

# Artefacts bucket - private access only (for STL, STEP, G-code files)
mc anonymous set none "local/artefacts" 2>/dev/null || echo "Artefacts bucket policy already set or failed"

# Logs bucket - private access only  
mc anonymous set none "local/logs" 2>/dev/null || echo "Logs bucket policy already set or failed"

# Reports bucket - private access only (for generated reports)
mc anonymous set none "local/reports" 2>/dev/null || echo "Reports bucket policy already set or failed"

# Invoices bucket - private access only (for billing and invoices)
mc anonymous set none "local/invoices" 2>/dev/null || echo "Invoices bucket policy already set or failed"

# Create notification targets if needed (for future webhook integration)
echo "Setting up notification configurations..."

# Optional: Set lifecycle policies for cleanup
echo "Setting lifecycle policies..."

# Example: Delete incomplete multipart uploads after 7 days in artefacts bucket
mc ilm add --expiry-days 7 --incomplete-upload-expiry-days 1 "local/artefacts" 2>/dev/null || echo "Lifecycle policy already exists or failed"

# Example: Transition old log files to IA storage after 30 days (if supported)
# mc ilm add --transition-days 30 --storage-class IA "local/logs" 2>/dev/null || echo "Lifecycle policy for logs already exists or failed"

echo "Bucket setup complete!"
echo "Created buckets:"
for bucket in $BUCKETS; do
    mc ls "local/$bucket" >/dev/null 2>&1 && echo "  ✓ $bucket" || echo "  ✗ $bucket (failed)"
done

# Verify versioning status
echo ""
echo "Versioning status:"
mc version info "local/artefacts" 2>/dev/null || echo "  ✗ artefacts versioning check failed"

echo ""
echo "Bucket policies:"
for bucket in $BUCKETS; do
    policy=$(mc anonymous get "local/$bucket" 2>/dev/null || echo "none/private")
    echo "  $bucket: $policy"
done

echo ""
echo "MinIO bucket bootstrap completed successfully!"