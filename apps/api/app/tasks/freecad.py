from __future__ import annotations

from datetime import datetime, timezone

from celery import shared_task
from ..freecad.service import detect_freecad
from ..services.freecad_service import freecad_service
from ..core.database import SessionLocal
from ..core.logging import get_logger

logger = get_logger(__name__)


@shared_task(name="freecad.detect", queue="freecad")
def freecad_detect_task() -> dict:
    """Legacy FreeCAD detection task for backward compatibility."""
    res = detect_freecad()
    return res.model_dump()


@shared_task(name="freecad.execute_operation", queue="model", bind=True)
def freecad_execute_operation_task(
    self,
    user_id: int,
    operation_type: str,
    script_content: str,
    parameters: dict,
    output_formats: list,
    correlation_id: str = None
) -> dict:
    """
    Ultra-enterprise FreeCAD operation execution task.
    
    Args:
        user_id: User ID for license checking
        operation_type: Type of operation (modeling, analysis, etc.)
        script_content: FreeCAD Python script to execute
        parameters: Operation parameters
        output_formats: Desired output file formats
        correlation_id: Request correlation ID
        
    Returns:
        Dict containing execution results
    """
    db = None
    try:
        # Create database session
        db = SessionLocal()
        
        logger.info("freecad_task_started",
                   task_id=self.request.id,
                   user_id=user_id,
                   operation_type=operation_type,
                   correlation_id=correlation_id)
        
        # Execute operation using ultra-enterprise service
        result = freecad_service.execute_freecad_operation(
            db=db,
            user_id=user_id,
            operation_type=operation_type,
            script_content=script_content,
            parameters=parameters,
            output_formats=output_formats,
            correlation_id=correlation_id or self.request.id
        )
        
        # Use the serialize_for_celery method for cleaner serialization
        result_dict = result.serialize_for_celery()
        
        logger.info("freecad_task_completed",
                   task_id=self.request.id,
                   user_id=user_id,
                   operation_type=operation_type,
                   success=result.success,
                   output_files_count=len(result.output_files),
                   correlation_id=correlation_id)
        
        return result_dict
        
    except Exception as e:
        logger.error("freecad_task_failed",
                    task_id=self.request.id,
                    user_id=user_id,
                    operation_type=operation_type,
                    error=str(e),
                    correlation_id=correlation_id,
                    exc_info=True)
        
        # Note: Double retry mechanism - service handles application-level retries,
        # Celery handles infrastructure-level retries (network, temporary failures)
        # Service retries: 3 attempts with exponential backoff
        # Celery retries: 3 attempts with 60s countdown
        # Max theoretical attempts: 3 service * 3 Celery = 9 (by design for resilience)
        raise self.retry(exc=e, countdown=60, max_retries=3)
    
    finally:
        # Clean up database session
        if db:
            db.close()


@shared_task(name="freecad.health_check", queue="default")
def freecad_health_check_task() -> dict:
    """FreeCAD service health check task."""
    try:
        health_status = freecad_service.health_check()
        
        logger.info("freecad_health_check_completed",
                   healthy=health_status.healthy,
                   circuit_breaker_state=health_status.checks.circuit_breaker.state)
        
        return health_status.model_dump()
        
    except Exception as e:
        logger.error("freecad_health_check_failed",
                    error=str(e),
                    exc_info=True)
        
        return {
            'healthy': False,
            'error': str(e),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }


