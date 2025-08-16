# Structured Logging Guide for FreeCAD Production Platform

## Overview

This guide covers the comprehensive structured logging system implemented using `structlog`. The system provides production-ready logging with support for both development (colorful console) and production (JSON) environments, including Turkish language support.

## Features

- **Structured Logging**: All logs are structured with consistent fields
- **Correlation IDs**: Automatic request tracking across services
- **Performance Monitoring**: Automatic timing for requests, queries, and tasks
- **Security Events**: Dedicated security event logging
- **Turkish Support**: Bilingual logging with Turkish translations
- **Sensitive Data Masking**: Automatic masking of passwords, tokens, etc.
- **Context Propagation**: Request ID, User ID, and Task ID tracking

## Installation

Dependencies are already added to `requirements.txt`:
```
structlog==24.4.0
colorama==0.4.6
python-ulid==2.7.0
```

## Configuration

The logging system is configured automatically based on environment variables:

```python
# Environment variables
ENVIRONMENT=development  # or production
LOG_LEVEL=DEBUG         # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

## Basic Usage

### 1. Getting a Logger

```python
from app.core.logging import get_logger

# Get a logger for your module
logger = get_logger(__name__)

# Log with structured data
logger.info("user_registered", user_id=user.id, email=user.email)
logger.warning("rate_limit_approaching", current=45, limit=50)
logger.error("payment_failed", error=str(e), user_id=user.id)
```

### 2. Using the @log_execution Decorator

```python
from app.core.logging import log_execution

@log_execution(level="INFO", include_args=True, include_result=True)
async def process_order(order_id: str, user_id: str) -> dict:
    # Your code here
    return {"status": "completed"}

# This will automatically log:
# - Function entry with arguments
# - Function exit with result and execution time
# - Any exceptions that occur
```

### 3. Request/Response Logging Middleware

The middleware is automatically added in `main.py`:

```python
from app.middleware.logging import LoggingMiddleware

app.add_middleware(
    LoggingMiddleware,
    slow_request_threshold_ms=1000,
    excluded_paths=["/health", "/metrics"],
)
```

This provides:
- Automatic request/response logging
- Correlation ID generation (X-Request-ID header)
- Performance tracking
- Slow request warnings
- Security event detection

### 4. Database Query Logging

```python
from app.core.database_logging import QueryLogger, log_transaction

# Using context manager for operations
with QueryLogger("fetch_users", filter="active") as qlog:
    users = session.query(User).filter_by(active=True).all()
    qlog.log_info(user_count=len(users))

# Using decorator for transactions
@log_transaction("create_order")
def create_order(session, order_data):
    order = Order(**order_data)
    session.add(order)
    session.commit()
    return order
```

### 5. Celery Task Logging

```python
from app.core.celery_logging import log_task_execution, LoggingTask

# Using decorator
@celery_app.task
@log_task_execution(include_args=True)
def process_file(file_id: str):
    # Task code here
    pass

# Using base class
@celery_app.task(base=LoggingTask)
def generate_report(report_id: str):
    # Task code here
    pass
```

### 6. Security Event Logging

```python
from app.core.logging import log_security_event

# Log authentication failures
log_security_event(
    "authentication_failed",
    user_id=attempt.user_id,
    ip_address=request.client.host,
    details={"reason": "invalid_password", "attempts": 3}
)

# Log suspicious activity
log_security_event(
    "suspicious_activity",
    ip_address=request.client.host,
    details={"pattern": "multiple_404_requests", "count": 50}
)
```

### 7. External API Call Logging

```python
from app.core.logging import log_external_api_call
import httpx
import time

async def call_payment_api(data):
    start = time.perf_counter()
    try:
        response = await httpx.post("https://api.payment.com/charge", json=data)
        duration_ms = int((time.perf_counter() - start) * 1000)
        
        log_external_api_call(
            service="payment_gateway",
            method="POST",
            url="https://api.payment.com/charge",
            status_code=response.status_code,
            duration_ms=duration_ms
        )
        
        return response.json()
    except Exception as e:
        duration_ms = int((time.perf_counter() - start) * 1000)
        log_external_api_call(
            service="payment_gateway",
            method="POST",
            url="https://api.payment.com/charge",
            duration_ms=duration_ms,
            error=str(e)
        )
        raise
```

## Log Formats

### Development Environment (Colorful Console)

```
2024-01-15 10:30:45 [INFO] request_started | İstek başlatıldı
    request_id: ulid-123abc
    method: POST
    path: /api/v1/cam/generate
    user_id: user-456
    client_host: 192.168.1.100
```

### Production Environment (JSON)

```json
{
  "timestamp": "2024-01-15T10:30:45.123Z",
  "level": "INFO",
  "event": "request_started",
  "message_tr": "İstek başlatıldı",
  "request_id": "ulid-123abc",
  "method": "POST",
  "path": "/api/v1/cam/generate",
  "user_id": "user-456",
  "client_host": "192.168.1.100",
  "hostname": "prod-api-1",
  "pid": 1234
}
```

## Common Log Events

### HTTP Events
- `request_started` - İstek başlatıldı
- `request_completed` - İstek tamamlandı
- `request_failed` - İstek başarısız oldu
- `slow_request` - Yavaş istek tespit edildi

### Authentication/Authorization
- `authentication_failed` - Kimlik doğrulama başarısız
- `authorization_failed` - Yetkilendirme başarısız
- `rate_limit_exceeded` - Hız limiti aşıldı

### Database Events
- `database_query` - Veritabanı sorgusu
- `slow_database_query` - Yavaş veritabanı sorgusu
- `database_error` - Veritabanı hatası

### Task Events
- `task_started` - Görev başlatıldı
- `task_completed` - Görev tamamlandı
- `task_failed` - Görev başarısız oldu

### File Operations
- `file_upload_started` - Dosya yükleme başladı
- `file_upload_completed` - Dosya yükleme tamamlandı

### Cache Events
- `cache_hit` - Önbellek bulundu
- `cache_miss` - Önbellekte bulunamadı

## Best Practices

### 1. Use Structured Data

```python
# Good - Structured data
logger.info("order_processed", order_id=order.id, total=order.total, items=len(order.items))

# Bad - String formatting
logger.info(f"Order {order.id} processed with total {order.total}")
```

### 2. Choose Appropriate Log Levels

```python
logger.debug("cache_check", key=cache_key)  # Detailed debugging
logger.info("user_login", user_id=user.id)  # Normal operations
logger.warning("disk_space_low", available_gb=2.5)  # Warnings
logger.error("payment_failed", error=str(e))  # Errors
logger.critical("database_connection_lost")  # Critical issues
```

### 3. Include Context

```python
# Always include relevant context
logger.info(
    "file_processed",
    file_id=file.id,
    size_bytes=file.size,
    processing_time_ms=elapsed_ms,
    user_id=user.id,
    queue="freecad"
)
```

### 4. Use Consistent Event Names

```python
# Use snake_case and be descriptive
"user_registered"
"payment_processed"
"file_upload_started"
"cache_invalidated"
```

### 5. Handle Sensitive Data

```python
# The system automatically masks sensitive fields
logger.info(
    "user_authenticated",
    user_id=user.id,
    email=user.email,  # OK
    password=password,  # Will be masked automatically
    token=token,  # Will be masked automatically
)
```

## Integration with Existing Code

### Replacing Old Logging

```python
# Old logging
from app.logging_setup import get_logger
logger = get_logger(__name__)
logger.info(f"Processing job {job_id}")

# New structured logging
from app.core.logging import get_logger
logger = get_logger(__name__)
logger.info("job_processing", job_id=job_id)
```

### Adding to Services

```python
from app.core.logging import get_logger, log_execution

class CAMService:
    def __init__(self):
        self.logger = get_logger(__name__)
    
    @log_execution(include_result=True)
    async def generate_toolpath(self, model_id: str, parameters: dict):
        self.logger.info("toolpath_generation_started", model_id=model_id)
        
        # Your code here
        
        self.logger.info("toolpath_generation_completed", model_id=model_id)
        return result
```

### Adding to Routers

```python
from fastapi import APIRouter, Request
from app.core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)

@router.post("/process")
async def process_request(request: Request, data: ProcessData):
    logger.info(
        "process_request_received",
        endpoint="/process",
        data_type=data.type,
        user_id=request.state.user.id if hasattr(request.state, "user") else None
    )
    
    # Process the request
    
    return result
```

## Monitoring and Analysis

### Searching Logs

```bash
# Development - Search for specific events
grep "request_failed" logs.txt

# Production - Parse JSON and filter
cat logs.json | jq 'select(.event == "request_failed")'

# Find slow requests
cat logs.json | jq 'select(.elapsed_ms > 1000)'

# Get all errors for a specific request
cat logs.json | jq 'select(.request_id == "ulid-123abc" and .level == "ERROR")'
```

### Common Queries

```bash
# Count requests by status code
cat logs.json | jq -r '.status_code' | sort | uniq -c

# Average response time
cat logs.json | jq '.elapsed_ms' | awk '{sum+=$1} END {print sum/NR}'

# Find failed authentications
cat logs.json | jq 'select(.event == "authentication_failed")'

# Track a specific user's actions
cat logs.json | jq 'select(.user_id == "user-123")'
```

## Troubleshooting

### Issue: Logs not appearing

```python
# Check log level
import os
print(os.environ.get("LOG_LEVEL", "INFO"))

# Ensure logging is configured
from app.core.logging import configure_structlog
configure_structlog()
```

### Issue: Too many logs

```python
# Adjust log level
os.environ["LOG_LEVEL"] = "WARNING"

# Or exclude noisy paths
app.add_middleware(
    LoggingMiddleware,
    excluded_paths=["/health", "/metrics", "/docs"]
)
```

### Issue: Performance impact

```python
# Disable query logging in production
setup_database_logging(
    engine,
    log_queries=False,  # Only log slow queries
    slow_query_threshold_ms=1000
)

# Use sampling for high-volume endpoints
import random
if random.random() < 0.1:  # Log 10% of requests
    logger.info("high_volume_endpoint", ...)
```

## Migration from Old Logging

1. **Update imports**: Replace `app.logging_setup` with `app.core.logging`
2. **Convert string formatting**: Change f-strings to structured data
3. **Add context**: Include request_id, user_id where available
4. **Use decorators**: Add `@log_execution` to service methods
5. **Test thoroughly**: Ensure logs are properly formatted

## Support

For questions or issues with the logging system:
1. Check this guide first
2. Review the test files for examples
3. Check the source code in `app/core/logging.py`
4. Ask the team for help

Remember: Good logging is crucial for debugging production issues. Take time to add meaningful, structured logs to your code!