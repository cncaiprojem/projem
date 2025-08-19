"""
Celery tasks for job cancellation and checkpoint monitoring.

Task 4.9: Worker checkpoint checking and graceful cancellation.
"""

from datetime import timezone, datetime
from typing import Any

from ..core.database import get_db_sync
from ..core.logging import get_logger
from ..models.enums import JobStatus
from ..models.job import Job
from ..services.job_cancellation_service import job_cancellation_service
from .celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(
    bind=True,
    name="check_job_cancellation",
    queue="default",
    max_retries=3,
    default_retry_delay=5
)
def check_job_cancellation_task(self, job_id: int) -> dict[str, Any]:
    """
    Check if a job has been requested for cancellation.
    This is a lightweight task that workers can call periodically.
    
    Args:
        job_id: ID of the job to check
        
    Returns:
        Dictionary with cancellation status
    """
    logger.info("Checking job cancellation status", job_id=job_id)

    try:
        with next(get_db_sync()) as db:
            job = db.get(Job, job_id)

            if not job:
                logger.warning("Job not found for cancellation check", job_id=job_id)
                return {"cancelled": False, "reason": "job_not_found"}

            if job.cancel_requested:
                logger.info(
                    "Job cancellation requested",
                    job_id=job_id,
                    reason=job.cancellation_reason
                )
                return {
                    "cancelled": True,
                    "reason": job.cancellation_reason or "unknown"
                }

            return {"cancelled": False, "reason": None}

    except Exception as e:
        logger.error(
            "Error checking job cancellation",
            job_id=job_id,
            error=str(e)
        )
        # Retry on error
        raise self.retry(exc=e) from e


@celery_app.task(
    bind=True,
    name="worker_checkpoint",
    queue="default",
    max_retries=1
)
def worker_checkpoint_task(
    self,
    job_id: int,
    checkpoint_data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    Worker checkpoint - check if job should continue or stop.
    Workers should call this at safe checkpoint locations.
    
    Args:
        job_id: ID of the job being processed
        checkpoint_data: Optional data to save at checkpoint
        
    Returns:
        Dictionary indicating whether to continue
    """
    logger.info(
        "Worker checkpoint",
        job_id=job_id,
        has_data=checkpoint_data is not None
    )

    try:
        with next(get_db_sync()) as db:
            # Use shared checkpoint logic from service
            result = job_cancellation_service._process_checkpoint_sync(
                db, job_id, checkpoint_data
            )
            
            # Commit changes if checkpoint processing succeeded
            if result["reason"] != "checkpoint_error":
                db.commit()
            
            return result

    except Exception as e:
        logger.error(
            "Error at worker checkpoint",
            job_id=job_id,
            error=str(e)
        )
        # Allow job to continue on error
        return {"continue": True, "reason": "checkpoint_error"}


@celery_app.task(
    bind=True,
    name="scan_jobs_for_cancellation",
    queue="default"
)
def scan_jobs_for_cancellation_task(self) -> dict[str, Any]:
    """
    Periodic task to scan for jobs that need cancellation.
    This is a safety net in case direct cancellation signals fail.
    
    Returns:
        Summary of cancelled jobs
    """
    logger.info("Starting periodic job cancellation scan")

    try:
        with next(get_db_sync()) as db:
            # Find jobs with cancel_requested but still running
            jobs_to_cancel = db.query(Job).filter(
                Job.cancel_requested.is_(True),
                Job.status == JobStatus.RUNNING
            ).all()

            cancelled_count = 0
            failed_count = 0

            for job in jobs_to_cancel:
                try:
                    # Check if job has been running too long since cancel requested
                    if job.metrics and "cancel_requested_time" in job.metrics:
                        cancel_time = datetime.fromisoformat(
                            job.metrics["cancel_requested_time"]
                        )
                        elapsed = (datetime.now(timezone.utc) - cancel_time).total_seconds()

                        # Force cancel if it's been more than 5 minutes
                        if elapsed > 300:
                            job.set_cancelled(
                                job.cancellation_reason or "forced_timeout"
                            )
                            db.commit()
                            cancelled_count += 1

                            logger.warning(
                                "Force cancelled job after timeout",
                                job_id=job.id,
                                elapsed_seconds=elapsed
                            )
                except Exception as e:
                    logger.error(
                        "Failed to process job in cancellation scan",
                        job_id=job.id,
                        error=str(e)
                    )
                    failed_count += 1

            logger.info(
                "Job cancellation scan complete",
                total_found=len(jobs_to_cancel),
                cancelled=cancelled_count,
                failed=failed_count
            )

            return {
                "scanned": len(jobs_to_cancel),
                "cancelled": cancelled_count,
                "failed": failed_count
            }

    except Exception as e:
        logger.error(
            "Error in job cancellation scan",
            error=str(e)
        )
        raise self.retry(exc=e)


# Helper function for workers to check cancellation
def should_cancel_job(job_id: int) -> bool:
    """
    Quick check if a job should be cancelled.
    Workers can call this function directly.
    
    Args:
        job_id: ID of the job to check
        
    Returns:
        True if job should be cancelled
    """
    try:
        result = check_job_cancellation_task.apply_async(
            args=[job_id],
            queue="default",
            priority=9
        ).get(timeout=5)

        return result.get("cancelled", False)
    except Exception as e:
        logger.error(
            "Error checking job cancellation",
            job_id=job_id,
            error=str(e)
        )
        return False
