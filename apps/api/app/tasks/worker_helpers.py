"""
Worker Helper Functions
Task 6.7: Easy-to-use progress reporting API for Celery workers

This module provides simple helper functions that workers can use
to report progress and handle status updates with automatic throttling
and event publishing.
"""

from __future__ import annotations

import asyncio
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

from ..core.logging import get_logger
from ..models.enums import JobStatus
from ..services.worker_progress_service import worker_progress_service

logger = get_logger(__name__)


def progress(
    db: Session,
    job_id: int,
    percent: int,
    step: Optional[str] = None,
    message: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Update job progress with automatic throttling and event publishing.
    
    This is the primary helper function workers should use to report progress.
    Updates are throttled to at most once per 2s per job to reduce DB load.
    Events are automatically published for status transitions.
    
    Args:
        db: Database session
        job_id: Job ID to update progress for
        percent: Progress percentage (0-100)
        step: Current processing step (e.g., "preprocessing", "processing", "finalizing")
        message: Human-readable progress message (e.g., "Processing frame 10 of 100")
        metrics: Additional metrics to store (e.g., {"frames_processed": 10, "fps": 30})
        
    Returns:
        Dict with update result including success status and details
        
    Example:
        >>> # In a Celery task
        >>> from app.tasks.worker_helpers import progress
        >>> 
        >>> @shared_task(bind=True)
        >>> def process_video_task(self, job_id: int):
        >>>     db = SessionLocal()
        >>>     try:
        >>>         # Report initial progress
        >>>         progress(db, job_id, 0, "initialization", "Starting video processing")
        >>>         
        >>>         # Process frames
        >>>         for i, frame in enumerate(frames):
        >>>             # Process frame...
        >>>             
        >>>             # Report progress (throttled to max once per 2s)
        >>>             progress(
        >>>                 db, job_id,
        >>>                 percent=int((i + 1) / len(frames) * 100),
        >>>                 step="processing",
        >>>                 message=f"Processing frame {i+1} of {len(frames)}",
        >>>                 metrics={"frames_processed": i+1, "fps": calculate_fps()}
        >>>             )
        >>>         
        >>>         # Report completion
        >>>         progress(db, job_id, 100, "completed", "Video processing complete")
        >>>         
        >>>     finally:
        >>>         db.close()
    """
    try:
        # Run async function in sync context (Celery tasks are sync)
        # Use asyncio.run() for better efficiency - creates and properly cleans up event loop
        result = asyncio.run(
            worker_progress_service.update_progress(
                db=db,
                job_id=job_id,
                percent=percent,
                step=step,
                message=message,
                metrics=metrics,
                force=False  # Allow throttling
            )
        )
        return result
            
    except Exception as e:
        logger.error(
            f"Failed to update progress for job {job_id}: {e}",
            extra={
                "job_id": job_id,
                "percent": percent,
                "step": step,
                "error": str(e)
            }
        )
        return {
            "success": False,
            "error": str(e),
            "job_id": job_id
        }


def force_progress(
    db: Session,
    job_id: int,
    percent: int,
    step: Optional[str] = None,
    message: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Force a progress update without throttling.
    
    Use this for critical progress updates that must not be throttled,
    such as final completion or error states.
    
    Args:
        db: Database session
        job_id: Job ID to update progress for
        percent: Progress percentage (0-100)
        step: Current processing step
        message: Human-readable progress message
        metrics: Additional metrics to store
        
    Returns:
        Dict with update result
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                worker_progress_service.update_progress(
                    db=db,
                    job_id=job_id,
                    percent=percent,
                    step=step,
                    message=message,
                    metrics=metrics,
                    force=True  # Bypass throttling
                )
            )
            return result
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(
            f"Failed to force progress update for job {job_id}: {e}",
            extra={
                "job_id": job_id,
                "percent": percent,
                "step": step,
                "error": str(e)
            }
        )
        return {
            "success": False,
            "error": str(e),
            "job_id": job_id
        }


def update_status(
    db: Session,
    job_id: int,
    status: JobStatus,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    output_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Update job status with automatic event publishing.
    
    Use this for explicit status transitions that are not progress-based.
    
    Args:
        db: Database session
        job_id: Job ID to update status for
        status: New job status
        error_code: Error code if failed
        error_message: Error message if failed
        output_data: Output data if completed
        
    Returns:
        Dict with update result
        
    Example:
        >>> # Mark job as running
        >>> update_status(db, job_id, JobStatus.RUNNING)
        >>> 
        >>> # Mark job as failed with error
        >>> update_status(
        >>>     db, job_id, JobStatus.FAILED,
        >>>     error_code="FREECAD_ERROR",
        >>>     error_message="FreeCAD process crashed"
        >>> )
        >>> 
        >>> # Mark job as completed with output
        >>> update_status(
        >>>     db, job_id, JobStatus.COMPLETED,
        >>>     output_data={"file_url": "s3://bucket/output.stl", "size": 1024}
        >>> )
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                worker_progress_service.update_job_status(
                    db=db,
                    job_id=job_id,
                    status=status,
                    error_code=error_code,
                    error_message=error_message,
                    output_data=output_data
                )
            )
            return result
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(
            f"Failed to update status for job {job_id}: {e}",
            extra={
                "job_id": job_id,
                "status": status.value,
                "error": str(e)
            }
        )
        return {
            "success": False,
            "error": str(e),
            "job_id": job_id
        }


def get_progress(
    db: Session,
    job_id: int
) -> Optional[Dict[str, Any]]:
    """
    Get current progress for a job.
    
    Args:
        db: Database session
        job_id: Job ID to get progress for
        
    Returns:
        Dict with progress information or None if not found
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                worker_progress_service.get_progress(db, job_id)
            )
            return result
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(
            f"Failed to get progress for job {job_id}: {e}",
            extra={"job_id": job_id, "error": str(e)}
        )
        return None


# Convenience functions with common patterns

def start_job(
    db: Session,
    job_id: int,
    message: Optional[str] = None
) -> Dict[str, Any]:
    """
    Mark a job as started (0% progress, RUNNING status).
    
    Args:
        db: Database session
        job_id: Job ID
        message: Optional startup message
        
    Returns:
        Dict with update result
    """
    return progress(
        db, job_id,
        percent=0,
        step="startup",
        message=message or "Job started"
    )


def complete_job(
    db: Session,
    job_id: int,
    output_data: Optional[Dict[str, Any]] = None,
    message: Optional[str] = None
) -> Dict[str, Any]:
    """
    Mark a job as completed (100% progress, COMPLETED status).
    
    Args:
        db: Database session
        job_id: Job ID
        output_data: Output data from job
        message: Optional completion message
        
    Returns:
        Dict with update result
    """
    # First update progress to 100%
    force_progress(
        db, job_id,
        percent=100,
        step="completed",
        message=message or "Job completed successfully"
    )
    
    # Then update status to completed
    return update_status(
        db, job_id,
        JobStatus.COMPLETED,
        output_data=output_data
    )


def fail_job(
    db: Session,
    job_id: int,
    error_code: str,
    error_message: str,
    progress_percent: Optional[int] = None
) -> Dict[str, Any]:
    """
    Mark a job as failed with error information.
    
    Args:
        db: Database session
        job_id: Job ID
        error_code: Error code
        error_message: Error message
        progress_percent: Progress at time of failure
        
    Returns:
        Dict with update result
    """
    # Update progress if provided
    if progress_percent is not None:
        force_progress(
            db, job_id,
            percent=progress_percent,
            step="failed",
            message=f"Job failed: {error_message}"
        )
    
    # Update status to failed
    return update_status(
        db, job_id,
        JobStatus.FAILED,
        error_code=error_code,
        error_message=error_message
    )