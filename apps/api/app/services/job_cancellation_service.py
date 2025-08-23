"""
Ultra-Enterprise Job Cancellation Service
Task 6.6: Cooperative worker cancellation with Redis caching

This service provides:
- Job cancellation request management
- Redis-backed cancellation flag caching
- Cooperative cancellation checks for workers
- Audit trail for cancellation events
- Idempotent cancellation operations
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import select, update

from ..core.logging import get_logger
from ..core.redis_config import get_redis_client
from ..models.job import Job
from ..services.audit_service import AuditService
from .pii_masking_service import DataClassification

logger = get_logger(__name__)


class JobCancelledError(Exception):
    """Exception raised when a job has been cancelled."""
    
    def __init__(self, job_id: int, message: str = None):
        self.job_id = job_id
        self.message = message or f"Job {job_id} has been cancelled"
        super().__init__(self.message)


class JobCancellationService:
    """Service for managing job cancellation with Redis caching."""
    
    # Redis key patterns
    CANCEL_FLAG_KEY = "job:cancel:{job_id}"
    CANCEL_FLAG_TTL = 3600  # 1 hour TTL for cancel flags
    
    def __init__(self):
        """Initialize cancellation service."""
        self.audit_service = AuditService()
        self._redis_client = None
    
    @property
    def redis_client(self):
        """Lazy load Redis client."""
        if self._redis_client is None:
            try:
                self._redis_client = get_redis_client()
                # Test connection
                self._redis_client.ping()
            except Exception as e:
                logger.warning(f"Redis unavailable for cancellation service: {e}")
                self._redis_client = None
        return self._redis_client
    
    def _extract_progress_value(self, progress_data: Optional[Dict[str, Any]]) -> Optional[int]:
        """
        Extract progress value from a dict containing 'percent' or 'progress' keys.
        
        This helper method consolidates the logic for extracting progress values
        from various dict formats, ensuring consistency and avoiding duplication.
        
        Args:
            progress_data: Dict that may contain 'percent' or 'progress' keys
            
        Returns:
            Clamped progress value (0-100) or None if no valid key found
        """
        if not progress_data:
            return None
        
        raw_value = progress_data.get("percent", progress_data.get("progress"))
        
        if raw_value is None or isinstance(raw_value, bool):
            return None
        
        try:
            # Convert to float first to handle various numeric string formats like "50.0"
            # Note: For progress values (0-100 range), float conversion is sufficient
            # and doesn't require decimal.Decimal precision
            progress = int(float(raw_value))
            return max(0, min(100, progress))
        except (ValueError, TypeError):
            logger.warning(
                "Could not parse progress value to integer",
                value=raw_value,
                data=progress_data,
            )
            return None
    
    async def request_cancellation(
        self,
        db: Session,
        job_id: int,
        user_id: Optional[int] = None,
        reason: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Request cancellation of a job.
        
        This operation is idempotent - calling it multiple times on the same
        job will return success without error.
        
        Args:
            db: Database session
            job_id: ID of job to cancel
            user_id: ID of user requesting cancellation
            reason: Optional cancellation reason
            ip_address: Client IP address
            user_agent: Client user agent
            
        Returns:
            Dict with cancellation status and details
        """
        try:
            # Get job with lock to prevent race conditions
            stmt = select(Job).where(Job.id == job_id).with_for_update()
            job = db.execute(stmt).scalar_one_or_none()
            
            if not job:
                return {
                    "success": False,
                    "error": "Job not found",
                    "job_id": job_id
                }
            
            # Check if already cancelled or finished
            if job.status in ["cancelled", "completed", "failed"]:
                # Idempotent response - already in terminal state
                logger.info(
                    f"Job {job_id} already in terminal state: {job.status}",
                    extra={
                        "job_id": job_id,
                        "status": job.status,
                        "cancel_requested": job.cancel_requested
                    }
                )
                
                # Still log audit for tracking
                await self._create_cancellation_audit(
                    db=db,
                    job_id=job_id,
                    user_id=user_id,
                    action="cancel_request_ignored",
                    reason=f"Job already {job.status}",
                    ip_address=ip_address,
                    user_agent=user_agent,
                    metadata={
                        "job_status": job.status,
                        "already_cancelled": job.cancel_requested
                    }
                )
                db.commit()  # Commit audit entry to database
                
                return {
                    "success": True,
                    "status": job.status,
                    "already_cancelled": job.cancel_requested,
                    "message": f"İş zaten {job.status} durumunda / Job already {job.status}"
                }
            
            # Set cancellation flag in database
            was_already_requested = job.cancel_requested
            job.cancel_requested = True
            
            # Update cancellation metrics (using metrics field, not metadata)
            if not job.metrics:
                job.metrics = {}
            
            # Generate timestamp once for consistency
            requested_at = datetime.now(timezone.utc)
            job.metrics["cancellation"] = {
                "requested_at": requested_at.isoformat(),
                "requested_by": user_id,
                "reason": reason,
                "previous_status": job.status
            }
            
            # Set Redis cache flag for fast worker checks
            if self.redis_client:
                try:
                    cache_key = self.CANCEL_FLAG_KEY.format(job_id=job_id)
                    self.redis_client.setex(
                        cache_key,
                        self.CANCEL_FLAG_TTL,
                        json.dumps({
                            "cancelled": True,
                            "requested_at": requested_at.isoformat(),
                            "requested_by": user_id,
                            "reason": reason
                        })
                    )
                    logger.debug(f"Set Redis cancel flag for job {job_id}")
                except Exception as e:
                    # Redis failure is non-fatal - DB is source of truth
                    logger.warning(f"Failed to set Redis cancel flag for job {job_id}: {e}")
            
            # Create audit log BEFORE committing for atomic transaction
            await self._create_cancellation_audit(
                db=db,
                job_id=job_id,
                user_id=user_id,
                action="cancel_requested",
                reason=reason,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={
                    "job_status": job.status,
                    "job_type": job.type,
                    "was_already_requested": was_already_requested,
                    "task_id": job.task_id
                }
            )
            
            # Single atomic commit for both job update and audit entry
            # This ensures data consistency - either both succeed or both fail
            db.commit()
            
            logger.info(
                f"Cancellation requested for job {job_id}",
                extra={
                    "job_id": job_id,
                    "user_id": user_id,
                    "status": job.status,
                    "was_already_requested": was_already_requested
                }
            )
            
            return {
                "success": True,
                "job_id": job_id,
                "status": job.status,
                "cancel_requested": True,
                "was_already_requested": was_already_requested,
                "message": "İptal isteği alındı / Cancellation requested" if not was_already_requested else "İptal zaten istenmişti / Cancellation already requested"
            }
            
        except Exception as e:
            db.rollback()  # Task 6.6: Critical fix from PR #231 - prevent broken session state
            logger.error(
                f"Failed to request cancellation for job {job_id}: {e}",
                extra={
                    "job_id": job_id,
                    "user_id": user_id,
                    "error": str(e)
                }
            )
            
            # Attempt to create error audit
            try:
                await self._create_cancellation_audit(
                    db=db,
                    job_id=job_id,
                    user_id=user_id,
                    action="cancel_request_failed",
                    reason=str(e),
                    ip_address=ip_address,
                    user_agent=user_agent,
                    metadata={"error": str(e)}
                )
                db.commit()  # Commit audit entry to database
            except Exception as audit_error:
                logger.error(f"Failed to create error audit: {audit_error}")
                db.rollback()  # Rollback if audit commit fails
            
            return {
                "success": False,
                "error": str(e),
                "job_id": job_id
            }
    
    def check_cancellation(self, db: Session, job_id: int) -> bool:
        """
        Check if a job has been cancelled.
        
        This is the primary method workers should call to check for cancellation.
        Uses Redis cache for performance, falls back to database.
        
        Args:
            db: Database session
            job_id: ID of job to check
            
        Returns:
            True if job is cancelled, False otherwise
            
        Raises:
            JobCancelledError: If job has been cancelled (for cooperative cancellation)
        """
        try:
            # Check Redis cache first for performance
            if self.redis_client:
                try:
                    cache_key = self.CANCEL_FLAG_KEY.format(job_id=job_id)
                    cached_value = self.redis_client.get(cache_key)
                    
                    if cached_value:
                        try:
                            cancel_data = json.loads(cached_value)
                        except json.JSONDecodeError as e:
                            # Handle corrupted cache data
                            logger.warning(
                                f"Corrupted cache data for job {job_id}, clearing cache",
                                error=str(e),
                                cached_value=cached_value[:100]  # Log first 100 chars for debugging
                            )
                            # Clear corrupted cache entry
                            self.redis_client.delete(cache_key)
                            cancel_data = {}
                        
                        if cancel_data.get("cancelled"):
                            logger.debug(f"Job {job_id} cancellation detected from Redis cache")
                            raise JobCancelledError(
                                job_id=job_id,
                                message=f"Job {job_id} was cancelled at {cancel_data.get('requested_at')}"
                            )
                except JobCancelledError:
                    # Re-raise cancellation errors
                    raise
                except Exception as e:
                    # Redis errors are non-fatal - fall through to DB check
                    logger.debug(f"Redis cache check failed for job {job_id}: {e}")
            
            # Check database as source of truth
            stmt = select(Job.cancel_requested, Job.status).where(Job.id == job_id)
            result = db.execute(stmt).first()
            
            if not result:
                logger.warning(f"Job {job_id} not found during cancellation check")
                return False
            
            cancel_requested, status = result
            
            # Check if cancelled or in terminal state
            if status == "cancelled":
                raise JobCancelledError(
                    job_id=job_id,
                    message=f"Job {job_id} has been cancelled"
                )
            
            if cancel_requested:
                # Update Redis cache for next check
                if self.redis_client:
                    try:
                        cache_key = self.CANCEL_FLAG_KEY.format(job_id=job_id)
                        self.redis_client.setex(
                            cache_key,
                            self.CANCEL_FLAG_TTL,
                            json.dumps({
                                "cancelled": True,
                                "requested_at": datetime.now(timezone.utc).isoformat()
                            })
                        )
                    except Exception as e:
                        logger.debug(f"Failed to update Redis cache for job {job_id}: {e}")
                
                raise JobCancelledError(
                    job_id=job_id,
                    message=f"Job {job_id} cancellation has been requested"
                )
            
            return False
            
        except JobCancelledError:
            # Re-raise cancellation errors for workers to handle
            raise
        except Exception as e:
            logger.error(
                f"Error checking cancellation for job {job_id}: {e}",
                extra={"job_id": job_id, "error": str(e)}
            )
            # On error, conservatively return False (don't cancel)
            return False
    
    def mark_job_cancelled(
        self,
        db: Session,
        job_id: int,
        final_progress: Optional[Dict[str, Any]] = None,
        cancellation_point: Optional[str] = None
    ) -> bool:
        """
        Mark a job as cancelled and persist final state.
        
        This should be called by workers when they detect cancellation
        and need to clean up.
        
        Args:
            db: Database session
            job_id: ID of job to mark as cancelled
            final_progress: Final progress data to persist
            cancellation_point: Where in the process cancellation occurred
            
        Returns:
            True if successfully marked as cancelled
        """
        try:
            # Get job with lock
            stmt = select(Job).where(Job.id == job_id).with_for_update()
            job = db.execute(stmt).scalar_one_or_none()
            
            if not job:
                logger.error(f"Job {job_id} not found when marking as cancelled")
                return False
            
            # Update job status and metrics
            # Generate timestamp once for consistency
            completed_at = datetime.now(timezone.utc)
            job.status = "cancelled"
            job.finished_at = completed_at
            
            if not job.metrics:
                job.metrics = {}
            
            job.metrics["cancellation_completed"] = {
                "completed_at": completed_at.isoformat(),
                "cancellation_point": cancellation_point,
                "final_progress": final_progress
            }
            
            # Persist final progress if provided
            # CRITICAL FIX: job.progress is an integer (0-100), not a dict!
            # Update both the integer progress field and metrics dict
            if final_progress:
                # Update metrics with all progress data
                if not job.metrics:
                    job.metrics = {}
                job.metrics.update(final_progress)
                
                # Use helper to extract progress value from final_progress dict
                progress_value = self._extract_progress_value(final_progress)
                if progress_value is not None:
                    job.progress = progress_value
            
            # Clear Redis cache
            if self.redis_client:
                try:
                    cache_key = self.CANCEL_FLAG_KEY.format(job_id=job_id)
                    self.redis_client.delete(cache_key)
                except Exception as e:
                    logger.debug(f"Failed to clear Redis cache for job {job_id}: {e}")
            
            db.commit()
            
            # Create completion audit (synchronous context - log instead of audit)
            # Task 6.6: In sync context, use logging instead of async audit service
            logger.info(
                f"Job {job_id} cancellation completed",
                extra={
                    "job_id": job_id,
                    "action": "cancel_completed",
                    "cancellation_point": cancellation_point,
                    "had_final_progress": bool(final_progress)
                }
            )
            
            logger.info(
                f"Job {job_id} marked as cancelled",
                extra={
                    "job_id": job_id,
                    "cancellation_point": cancellation_point
                }
            )
            
            return True
            
        except Exception as e:
            db.rollback()  # Task 6.6: Ensure clean session state
            logger.error(
                f"Failed to mark job {job_id} as cancelled: {e}",
                extra={
                    "job_id": job_id,
                    "error": str(e)
                }
            )
            return False
    
    async def _create_cancellation_audit(
        self,
        db: Session,
        job_id: int,
        action: str,
        user_id: Optional[int] = None,
        reason: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Create audit log entry for cancellation event."""
        try:
            await self.audit_service.create_audit_entry(
                db=db,
                event_type=f"job.cancellation.{action}",
                user_id=user_id,
                scope_type="job",
                scope_id=job_id,
                resource=f"job/{job_id}",
                ip_address=ip_address,
                user_agent=user_agent,
                payload={
                    "action": action,
                    "reason": reason,
                    **(metadata or {})
                },
                classification=DataClassification.INTERNAL
            )
        except Exception as e:
            logger.error(
                f"Failed to create cancellation audit for job {job_id}: {e}",
                extra={
                    "job_id": job_id,
                    "action": action,
                    "error": str(e)
                }
            )


# Global service instance
job_cancellation_service = JobCancellationService()


# Convenience functions for workers
def check_cancel(db: Session, job_id: int):
    """
    Check if a job has been cancelled.
    
    This is a convenience function for workers to check cancellation.
    Raises JobCancelledError if the job has been cancelled.
    
    Args:
        db: Database session
        job_id: ID of job to check
        
    Raises:
        JobCancelledError: If job has been cancelled
    """
    job_cancellation_service.check_cancellation(db, job_id)


def mark_cancelled(
    db: Session,
    job_id: int,
    final_progress: Optional[Dict[str, Any]] = None,
    cancellation_point: Optional[str] = None
) -> bool:
    """
    Mark a job as cancelled.
    
    Convenience function for workers to mark a job as cancelled.
    Task 6.6: Made synchronous for use in Celery tasks.
    
    Args:
        db: Database session
        job_id: ID of job to mark as cancelled
        final_progress: Final progress data to persist
        cancellation_point: Where in the process cancellation occurred
        
    Returns:
        True if successfully marked as cancelled
    """
    return job_cancellation_service.mark_job_cancelled(
        db, job_id, final_progress, cancellation_point
    )