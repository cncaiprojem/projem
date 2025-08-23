"""
Job validation and task publishing logic - Task 6.3.
İş doğrulama ve görev yayınlama mantığı.

Handles:
- Job type validation
- Payload validation with Pydantic
- Error code generation (ERR-JOB-422, ERR-JOB-400)
- Task publishing with proper routing
"""

import json
from typing import Any, Dict, Optional, Tuple
from uuid import UUID
import structlog

from pydantic import ValidationError

from ..core.celery_app import celery_app
from ..core.job_routing import (
    JobType,
    get_queue_for_job_type,
    get_routing_key_for_job_type,
    get_routing_config_for_job_type,
    validate_job_type,
)
from ..schemas.job_payload import (
    TaskPayload,
    TaskPayloadResponse,
    MAX_PAYLOAD_SIZE_BYTES,
)


logger = structlog.get_logger(__name__)

# Compression threshold for payload size (1KB)
COMPRESSION_THRESHOLD_BYTES = 1024


class JobValidationError(Exception):
    """
    İş doğrulama hatası.
    Job validation error with error code.
    """
    
    def __init__(self, message: str, error_code: str, details: Optional[Dict] = None):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(message)


def validate_job_payload(
    job_data: Dict[str, Any]
) -> Tuple[TaskPayload, Dict[str, str]]:
    """
    İş yükünü doğrula ve routing bilgilerini döndür.
    Validate job payload and return routing information.
    
    Args:
        job_data: Raw job data dictionary
        
    Returns:
        Tuple of (validated TaskPayload, routing config dict)
        
    Raises:
        JobValidationError: If validation fails with appropriate error code
    """
    # First check if job type is provided and valid
    job_type_str = job_data.get("type")
    if not job_type_str:
        raise JobValidationError(
            message="Job type is required",
            error_code="ERR-JOB-400",
            details={"field": "type", "reason": "missing"},
        )
    
    # Validate job type
    job_type = validate_job_type(job_type_str)
    if not job_type:
        raise JobValidationError(
            message=f"Invalid job type: {job_type_str}",
            error_code="ERR-JOB-400",
            details={
                "field": "type",
                "value": job_type_str,
                "valid_types": [t.value for t in JobType],
            },
        )
    
    # Validate payload with Pydantic
    try:
        task_payload = TaskPayload(**job_data)
    except ValidationError as e:
        # Convert Pydantic validation errors to our error format
        error_details = []
        for error in e.errors():
            error_details.append({
                "field": ".".join(str(loc) for loc in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            })
        
        raise JobValidationError(
            message="Job payload validation failed",
            error_code="ERR-JOB-422",
            details={"validation_errors": error_details},
        )
    except (TypeError, AttributeError, ValueError) as e:
        # Catches validation errors from custom validators or unexpected type issues.
        logger.warning(
            "Job validation failed",
            error=str(e),
            job_type=job_type_str,
        )
        raise JobValidationError(
            message=f"Job payload validation error: {e}",
            error_code="ERR-JOB-422",
            details={"error": type(e).__name__, "reason": str(e)},
        ) from e
    
    # Get routing configuration
    try:
        routing_config = get_routing_config_for_job_type(task_payload.type)
    except ValueError as e:
        raise JobValidationError(
            message=f"No routing configuration found for job type: {task_payload.type.value}",
            error_code="ERR-JOB-400",
            details={"job_type": task_payload.type.value},
        ) from e
    
    logger.info(
        "Job payload validated successfully",
        job_id=str(task_payload.job_id),
        job_type=task_payload.type.value,
        queue=routing_config["queue"],
        routing_key=routing_config["routing_key"],
    )
    
    return task_payload, routing_config


def publish_job_task(
    task_payload: TaskPayload,
    routing_config: Optional[Dict[str, str]] = None,
    task_name: str = "process_job",
) -> TaskPayloadResponse:
    """
    Doğrulanmış iş görevini kuyruğa yayınla.
    Publish validated job task to appropriate queue.
    
    Args:
        task_payload: Validated TaskPayload object
        routing_config: Optional routing configuration override
        task_name: Celery task name to execute
        
    Returns:
        TaskPayloadResponse with job status
        
    Raises:
        Exception: If publishing fails
    """
    # Get routing config if not provided
    if not routing_config:
        try:
            routing_config = get_routing_config_for_job_type(task_payload.type)
        except ValueError as e:
            raise RuntimeError(
                f"No routing configuration found for job type: {task_payload.type.value}"
            ) from e
    
    # Prepare task arguments
    task_args = {
        "job_id": str(task_payload.job_id),
        "job_type": task_payload.type.value,
        "params": task_payload.params,
        "submitted_by": task_payload.submitted_by,
        "attempt": task_payload.attempt,
        "created_at": task_payload.created_at.isoformat(),
    }
    
    try:
        # Determine payload size for conditional compression
        try:
            payload_json = json.dumps(task_args)
        except (TypeError, ValueError) as json_err:
            logger.error(
                "Failed to serialize task_args to JSON",
                job_id=str(task_payload.job_id),
                error=str(json_err),
                task_args=task_args,
            )
            raise RuntimeError(f"Task arguments could not be serialized to JSON: {json_err}") from json_err
        payload_size = len(payload_json.encode("utf-8"))
        
        # Prepare send_task kwargs
        send_task_kwargs = {
            "args": [task_args],
            "queue": routing_config["queue"],
            "routing_key": routing_config["routing_key"],
            "exchange": routing_config["exchange"],
            "exchange_type": routing_config["exchange_type"],
            "serializer": "json",
            "retry": True,
            "retry_policy": {
                "max_retries": 3,
                "interval_start": 0,
                "interval_step": 0.2,
                "interval_max": 0.2,
            },
        }
        
        # Only compress payloads larger than threshold
        if payload_size > COMPRESSION_THRESHOLD_BYTES:
            send_task_kwargs["compression"] = "gzip"
        
        # Send task to Celery with proper routing
        result = celery_app.send_task(
            task_name,
            **send_task_kwargs
        )
        
        logger.info(
            "Job task published successfully",
            job_id=str(task_payload.job_id),
            task_id=result.id,
            queue=routing_config["queue"],
            routing_key=routing_config["routing_key"],
        )
        
        return TaskPayloadResponse(
            job_id=task_payload.job_id,
            status="queued",
            queue=routing_config["queue"],
            routing_key=routing_config["routing_key"],
            message=f"Task successfully queued to {routing_config['queue']}",
        )
        
    except Exception as e:
        logger.error(
            "Failed to publish job task",
            job_id=str(task_payload.job_id),
            error=str(e),
            queue=routing_config["queue"],
        )
        raise


def validate_and_publish_job(
    job_data: Dict[str, Any],
    task_name: str = "process_job",
) -> TaskPayloadResponse:
    """
    İşi doğrula ve kuyruğa yayınla - tek adımda.
    Validate and publish job in one step.
    
    Args:
        job_data: Raw job data dictionary
        task_name: Celery task name to execute
        
    Returns:
        TaskPayloadResponse with job status
        
    Raises:
        JobValidationError: If validation fails
        Exception: If publishing fails
    """
    # Validate payload
    task_payload, routing_config = validate_job_payload(job_data)
    
    # Publish to queue
    return publish_job_task(task_payload, routing_config, task_name)


def check_payload_size(data: Any) -> bool:
    """
    Yük boyutunu kontrol et.
    Check if payload size is within limits.
    
    Args:
        data: Data to check (will be JSON serialized)
        
    Returns:
        True if within size limits, False otherwise
    """
    try:
        json_str = json.dumps(data)
        size_bytes = len(json_str.encode("utf-8"))
        return size_bytes <= MAX_PAYLOAD_SIZE_BYTES
    except (TypeError, ValueError) as exc:
        logger.error("Failed to check payload size due to exception", exc_info=True, data=data)
        # If we can't serialize to JSON, consider it too large
        return False


def get_job_error_response(error: JobValidationError) -> Dict[str, Any]:
    """
    Hata için standart yanıt formatı oluştur.
    Create standard error response format.
    
    Args:
        error: JobValidationError instance
        
    Returns:
        Dictionary with error details
    """
    return {
        "error": error.error_code,
        "message": error.message,
        "details": error.details,
        "retryable": error.error_code != "ERR-JOB-422",  # Validation errors are not retryable
    }


# Export all public symbols
__all__ = [
    "JobValidationError",
    "validate_job_payload",
    "publish_job_task",
    "validate_and_publish_job",
    "check_payload_size",
    "get_job_error_response",
]