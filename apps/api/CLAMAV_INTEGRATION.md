# ClamAV Integration - Task 5.6

## Overview

This document describes the ClamAV malware scanning integration implemented for Task 5.6. The integration provides enterprise-grade malware protection for file uploads with streaming scan capabilities, comprehensive error handling, and security event logging.

## Features

- **Streaming Scan**: Scans files directly from MinIO without storing to disk
- **TCP/Unix Socket Support**: Connects to ClamAV daemon via TCP or Unix socket
- **Configurable Policies**: Scan only specific file types (non-G-code CAD and videos)
- **Rate Limiting**: Protects resources with concurrent scan limits
- **Fail-Closed Security**: Blocks uploads if scanning is enabled but daemon unreachable
- **Comprehensive Logging**: Security event logging and audit trails
- **Turkish Localization**: Error messages in Turkish and English

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   File Service  │───▶│  ClamAV Service │───▶│   ClamAV Daemon │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│      MinIO      │    │ Security Events │    │  Virus Database │
│   (Streaming)   │    │   & Audit Log   │    │   (Updated)     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Configuration

### Environment Variables

Add these variables to your `.env` file:

```bash
# ClamAV Configuration
CLAMAV_ENABLED=true
CLAMAV_HOST=clamd
CLAMAV_PORT=3310
CLAMAV_TIMEOUT_CONNECT=10.0
CLAMAV_TIMEOUT_SCAN=60.0
CLAMAV_MAX_CONCURRENT_SCANS=3
CLAMAV_SCAN_ENABLED=true
```

### Docker Compose

The integration includes a ClamAV daemon service:

```yaml
clamd:
  build:
    context: ../../infra/docker/clamav
  image: clamav-daemon:dev
  container_name: fc_clamd_dev
  command: ["clamd", "--foreground=yes", "--config-file=/etc/clamav/clamd.conf"]
  ports:
    - "3310:3310"
  networks:
    - freecad_network
```

## Usage

### Starting Services

1. Start with security profile:
```bash
docker compose -f infra/compose/docker-compose.dev.yml --profile security up -d
```

2. Verify ClamAV daemon is running:
```bash
docker logs fc_clamd_dev
```

### File Upload Process

The ClamAV integration is automatically triggered during file upload finalization:

1. **Upload Initialization**: Client gets presigned URL
2. **File Upload**: Client uploads file to MinIO
3. **Upload Finalization**: 
   - SHA256 verification
   - **ClamAV scanning** (Task 5.6)
   - File metadata creation

### Scanning Policies

Files are scanned based on type and extension:

**Scanned File Types:**
- CAD models (`model/*`, `application/sla`, etc.)
- Archives (`application/zip`, `application/gzip`, etc.)
- Executables (`application/x-executable`, etc.)
- Images and videos (can contain embedded malware)

**Skipped File Types:**
- G-code files (`.gcode`, `.nc`, `.txt`)
- Configuration files (`.json`, `.xml`, `.csv`)
- Log files (`.log`)

## Error Handling

### Malware Detection

When malware is detected:

```json
{
  "code": "MALWARE_DETECTED",
  "message": "Malware detected and removed: Eicar-Test-Signature. Please ensure your file is clean and try again.",
  "turkish_message": "Kötü amaçlı yazılım tespit edildi ve kaldırıldı: Eicar-Test-Signature. Lütfen dosyanızın temiz olduğundan emin olun ve tekrar deneyin.",
  "status_code": 422,
  "details": {
    "virus_name": "Eicar-Test-Signature",
    "scan_time_ms": 150.0,
    "remediation": "Scan your file with updated antivirus software before re-uploading"
  }
}
```

### Daemon Unavailable

When scanning is enabled but daemon is unreachable:

```json
{
  "code": "STORAGE_ERROR", 
  "message": "Malware scanning unavailable",
  "turkish_message": "Kötü amaçlı yazılım taraması kullanılamıyor",
  "status_code": 503
}
```

### Scan Timeout

When scan takes too long:

```json
{
  "code": "STORAGE_ERROR",
  "message": "Malware scan failed: Scan timeout after 60s", 
  "status_code": 408
}
```

## Security Features

### Rate Limiting

Concurrent scans are limited to protect system resources:

```python
CLAMAV_MAX_CONCURRENT_SCANS=3  # Maximum concurrent scans
```

### Security Event Logging

All security events are logged to database and structured logs:

```python
SecurityEvent(
    event_type=SecurityEventType.MALWARE_DETECTED,
    description="Malware detected in uploaded file: Eicar-Test-Signature",
    severity=SeverityLevel.CRITICAL,
    details={
        "object_key": "temp/job123/infected.exe",
        "virus_name": "Eicar-Test-Signature",
        "scan_time_ms": 150.0
    }
)
```

### Audit Trail

All file deletions due to malware detection are logged via SHA256 service:

```python
sha256_service.delete_object_with_audit(
    bucket_name="temp",
    object_name="job123/infected.exe",
    reason="Malware detected: Eicar-Test-Signature",
    details={
        "virus_name": "Eicar-Test-Signature",
        "upload_id": "upload-123",
        "scan_metadata": {...}
    }
)
```

## Testing

### EICAR Test

To test malware detection, upload the EICAR test string:

```
X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*
```

This should trigger a `422 MALWARE_DETECTED` response.

### Unit Tests

Run the comprehensive test suite:

```bash
# ClamAV service tests
pytest apps/api/tests/test_clamav_service.py -v

# File service integration tests  
pytest apps/api/tests/test_clamav_file_service_integration.py -v
```

### Manual Testing

1. **Test daemon connectivity:**
```bash
docker exec fc_clamd_dev clamdscan --version
```

2. **Test EICAR detection:**
```bash
echo 'X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*' > /tmp/eicar.txt
docker exec fc_clamd_dev clamdscan /tmp/eicar.txt
```

## Troubleshooting

### Common Issues

**1. ClamAV daemon not starting:**
```bash
# Check daemon logs
docker logs fc_clamd_dev

# Verify virus database
docker exec fc_clamd_dev ls -la /var/lib/clamav/
```

**2. Connection refused errors:**
```bash
# Verify daemon is listening
docker exec fc_clamd_dev netstat -tlnp | grep 3310

# Check firewall/networking
docker exec fc_clamd_dev ping clamd
```

**3. Scan timeouts:**
```bash
# Increase timeout in environment
CLAMAV_TIMEOUT_SCAN=120.0

# Check daemon performance
docker stats fc_clamd_dev
```

**4. False positives:**
```bash
# Check virus database version
docker exec fc_clamd_dev freshclam --version

# Update virus database
docker exec fc_clamd_dev freshclam --no-warnings
```

### Performance Tuning

**Memory Usage:**
- ClamAV daemon uses ~1-2GB RAM
- Increase memory limits for large file scanning

**CPU Usage:**
- Limit concurrent scans: `CLAMAV_MAX_CONCURRENT_SCANS=2`
- Adjust daemon threads in clamd.conf: `MaxThreads=6`

**Network Timeouts:**
- Connection: `CLAMAV_TIMEOUT_CONNECT=15.0`
- Scan: `CLAMAV_TIMEOUT_SCAN=90.0`

## Production Deployment

### Security Hardening

1. **Use Unix sockets** instead of TCP when possible
2. **Enable all scan types** in clamd.conf
3. **Regular database updates** via freshclam
4. **Monitor security events** and set up alerts
5. **Log rotation** for ClamAV logs

### High Availability

1. **Multiple ClamAV instances** behind load balancer
2. **Health checks** and automatic restart
3. **Shared virus database** storage
4. **Monitoring and alerting** integration

### Compliance

- **Audit logging** for regulatory compliance
- **Data retention** policies for security events  
- **Incident response** procedures for malware detection
- **Regular security** assessments and penetration testing

## API Documentation

The ClamAV integration is transparent to API clients. Malware scanning occurs automatically during upload finalization with appropriate error responses for detection scenarios.

## Support

For issues or questions regarding ClamAV integration:

1. Check logs: `docker logs fc_clamd_dev`
2. Run tests: `pytest apps/api/tests/test_clamav*.py -v`
3. Verify configuration: Review environment variables
4. Monitor security events: Check database security_events table