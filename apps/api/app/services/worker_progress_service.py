"""
Ultra-Enterprise Worker Progress Service
Task 6.7: Worker progress update conventions and status change events

This service provides:
- Progress reporting API for workers with throttling
- Monotonic progress validation
- Status change event publishing
- Coalescing for rapid updates (max once per 2s per job)
- Integration with RabbitMQ event topology
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from sqlalchemy.orm import Session
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError
import redis.exceptions

from ..core.logging import get_logger
from ..core.redis_config import get_redis_client
from ..models.job import Job
from ..models.enums import JobStatus
from .event_publisher_service import EventPublisherService
from .job_audit_service import job_audit_service

logger = get_logger(__name__)


class ProgressValidationError(Exception):
    """Exception raised when progress validation fails."""
    pass


class WorkerProgressService:
    """Service for managing worker progress updates with throttling and event publishing."""
    
    # Redis key patterns for throttling
    PROGRESS_THROTTLE_KEY = "job:progress:throttle:{job_id}"
    PROGRESS_THROTTLE_TTL = 2  # 2 seconds throttle window
    
    # Redis key for coalesced updates
    PROGRESS_COALESCE_KEY = "job:progress:coalesce:{job_id}"
    PROGRESS_COALESCE_TTL = 3  # Slightly longer than throttle window
    
    def __init__(self):
        """Initialize worker progress service."""
        self.event_publisher = EventPublisherService()
        self._redis_client = None
    
    @property
    def redis_client(self):
        """Lazy load Redis client."""
        if self._redis_client is None:
            try:
                self._redis_client = get_redis_client()
                # Test connection
                self._redis_client.ping()
            except redis.exceptions.RedisError as e:
                logger.warning(f"Redis unavailable for progress service: {e}")
                self._redis_client = None
        return self._redis_client
    
    def _validate_monotonic_progress(
        self,
        current_progress: int,
        new_progress: int,
        job_id: int
    ) -> None:
        """
        Validate that progress is monotonic (never decreases).
        
        Args:
            current_progress: Current progress value (0-100)
            new_progress: New progress value (0-100)
            job_id: Job ID for logging
            
        Raises:
            ProgressValidationError: If progress would decrease
        """
        if new_progress < current_progress:
            raise ProgressValidationError(
                f"Progress cannot decrease for job {job_id}: "
                f"current={current_progress}, new={new_progress}"
            )
    
    def _should_throttle(self, job_id: int) -> bool:
        """
        Check if update should be throttled based on 2s window.
        
        Args:
            job_id: Job ID to check throttling for
            
        Returns:
            True if update should be throttled (skipped)
        """
        if not self.redis_client:
            # No Redis, no throttling
            return False
        
        try:
            throttle_key = self.PROGRESS_THROTTLE_KEY.format(job_id=job_id)
            
            # Try to set with NX (only if not exists) and EX (expiry)
            # Returns True if key was set (no throttle), None if exists (throttle)
            result = self.redis_client.set(
                throttle_key,
                time.time(),
                nx=True,
                ex=self.PROGRESS_THROTTLE_TTL
            )
            
            # If result is None, key exists = throttle
            return result is None
            
        except Exception as e:
            logger.debug(f"Redis throttle check failed for job {job_id}: {e}")
            # On Redis error, don't throttle
            return False
    
    def _coalesce_update(
        self,
        job_id: int,
        percent: int,
        step: Optional[str] = None,
        message: Optional[str] = None,
        metrics: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Store update for coalescing if within throttle window.
        
        Args:
            job_id: Job ID
            percent: Progress percentage (0-100)
            step: Current step/phase
            message: Progress message
            metrics: Additional metrics
        """
        if not self.redis_client:
            return
        
        try:
            coalesce_key = self.PROGRESS_COALESCE_KEY.format(job_id=job_id)
            
            # Store the latest update data
            update_data = {
                "percent": percent,
                "step": step,
                "message": message,
                "metrics": metrics,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            self.redis_client.setex(
                coalesce_key,
                self.PROGRESS_COALESCE_TTL,
                json.dumps(update_data)
            )
            
            logger.debug(f"Coalesced progress update for job {job_id}: {percent}%")
            
        except Exception as e:
            logger.debug(f"Failed to coalesce update for job {job_id}: {e}")
    
    async def update_progress(
        self,
        db: Session,
        job_id: int,
        percent: int,
        step: Optional[str] = None,
        message: Optional[str] = None,
        metrics: Optional[Dict[str, Any]] = None,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Update job progress with throttling and event publishing.
        
        Throttles updates to at most once per 2s per job to reduce DB load.
        Publishes job.status.changed events on state transitions.
        
        Args:
            db: Database session
            job_id: Job ID to update
            percent: Progress percentage (0-100)
            step: Current step/phase (e.g., "preprocessing", "processing")
            message: Human-readable progress message
            metrics: Additional metrics to store
            force: Force update even if throttled (for critical updates)
            
        Returns:
            Dict with update status and details
        """
        try:
            # Validate percent range
            percent = max(0, min(100, percent))
            
            # Check throttling unless forced
            if not force and self._should_throttle(job_id):
                # Store for coalescing
                self._coalesce_update(job_id, percent, step, message, metrics)
                
                logger.debug(
                    f"Progress update throttled for job {job_id}: {percent}% "
                    f"(will be coalesced)"
                )
                
                return {
                    "success": True,
                    "throttled": True,
                    "job_id": job_id,
                    "percent": percent,
                    "message": "Update coalesced (throttled)"
                }
            
            # Get job with lock for atomic update
            stmt = select(Job).where(Job.id == job_id).with_for_update()
            job = db.execute(stmt).scalar_one_or_none()
            
            if not job:
                return {
                    "success": False,
                    "error": "Job not found",
                    "job_id": job_id
                }
            
            # Store previous state for event publishing
            previous_status = job.status
            previous_progress = job.progress
            
            # Validate monotonic progress
            try:
                self._validate_monotonic_progress(
                    previous_progress,
                    percent,
                    job_id
                )
            except ProgressValidationError as e:
                logger.warning(str(e))
                # Don't update if validation fails
                return {
                    "success": False,
                    "error": str(e),
                    "job_id": job_id,
                    "current_progress": previous_progress,
                    "requested_progress": percent
                }
            
            # Check for any coalesced updates to merge
            coalesced_data = None
            if self.redis_client and not force:
                try:
                    coalesce_key = self.PROGRESS_COALESCE_KEY.format(job_id=job_id)
                    coalesced_json = self.redis_client.get(coalesce_key)
                    
                    if coalesced_json:
                        coalesced_data = json.loads(coalesced_json)
                        # Use the max progress from coalesced updates
                        if coalesced_data.get("percent", 0) > percent:
                            percent = coalesced_data["percent"]
                            step = coalesced_data.get("step") or step
                            message = coalesced_data.get("message") or message
                            if coalesced_data.get("metrics"):
                                metrics = {**(metrics or {}), **coalesced_data["metrics"]}
                        
                        # Clear coalesced data
                        self.redis_client.delete(coalesce_key)
                        
                except Exception as e:
                    logger.debug(f"Failed to retrieve coalesced data for job {job_id}: {e}")
            
            # Update job progress
            job.progress = percent
            
            # Update metrics
            if not job.metrics:
                job.metrics = {}
            
            # Store progress details in metrics
            progress_update = {
                "last_progress_update": datetime.now(timezone.utc).isoformat(),
                "progress_percent": percent,
                "progress_step": step,
                "progress_message": message,
            }
            
            # Merge additional metrics if provided
            if metrics:
                progress_update.update(metrics)
            
            job.metrics.update(progress_update)
            
            # Determine if status should change based on progress
            new_status = None
            if percent == 0 and job.status == JobStatus.PENDING:
                new_status = JobStatus.QUEUED
            elif percent > 0 and percent < 100 and job.status in [JobStatus.PENDING, JobStatus.QUEUED]:
                new_status = JobStatus.RUNNING
            elif percent == 100 and job.status == JobStatus.RUNNING:
                # Note: Workers should explicitly call set_completed() for proper completion
                # This is just a safeguard
                pass
            
            # Update status if changed
            if new_status and new_status != job.status:
                job.status = new_status
                if new_status == JobStatus.RUNNING and not job.started_at:
                    job.started_at = datetime.now(timezone.utc)
            
            # Commit database changes
            db.commit()
            
            # Create audit log for significant progress updates (Task 6.8)
            if percent in [25, 50, 75, 100] or new_status != previous_status:
                try:
                    await job_audit_service.audit_job_progress(
                        db=db,
                        job_id=job_id,
                        progress=percent,
                        message=message,
                        metadata={
                            "step": step,
                            "previous_progress": previous_progress,
                            "status_changed": new_status != previous_status,
                            "metrics": metrics
                        }
                    )
                    db.commit()
                except Exception as audit_error:
                    logger.error(
                        f"Failed to create audit log for job {job_id} progress update",
                        extra={
                            "job_id": job_id,
                            "percent": percent,
                            "error": str(audit_error)
                        }
                    )
            
            # Publish event if status changed or significant progress change
            should_publish_event = (
                new_status != previous_status or
                abs(percent - previous_progress) >= 10 or  # 10% change threshold
                percent in [0, 25, 50, 75, 100]  # Milestone percentages
            )
            
            if should_publish_event:
                # Publish job.status.changed event
                await self.event_publisher.publish_job_status_changed(
                    job_id=job_id,
                    status=str(job.status.value),
                    progress=percent,
                    attempt=job.attempts,
                    previous_status=str(previous_status.value) if previous_status else None,
                    previous_progress=previous_progress,
                    step=step,
                    message=message
                )
            
            logger.info(
                f"Progress updated for job {job_id}: {percent}% "
                f"(step: {step}, status: {job.status.value})",
                extra={
                    "job_id": job_id,
                    "percent": percent,
                    "step": step,
                    "status": job.status.value,
                    "previous_progress": previous_progress,
                    "coalesced": bool(coalesced_data)
                }
            )
            
            return {
                "success": True,
                "job_id": job_id,
                "percent": percent,
                "status": job.status.value,
                "previous_progress": previous_progress,
                "event_published": should_publish_event,
                "coalesced": bool(coalesced_data)
            }
            
        except (IntegrityError, OperationalError) as e:
            db.rollback()
            logger.error(
                f"Database error updating progress for job {job_id}: {e}",
                extra={
                    "job_id": job_id,
                    "percent": percent,
                    "error": str(e)
                }
            )
            
            return {
                "success": False,
                "error": str(e),
                "job_id": job_id
            }
        except redis.exceptions.RedisError as e:
            db.rollback()
            logger.error(
                f"Redis error updating progress for job {job_id}: {e}",
                extra={
                    "job_id": job_id,
                    "percent": percent,
                    "error": str(e)
                }
            )
            
            return {
                "success": False,
                "error": str(e),
                "job_id": job_id
            }
    
    async def update_job_status(
        self,
        db: Session,
        job_id: int,
        status: JobStatus,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        output_data: Optional[Dict[str, Any]] = None,
        worker_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update job status and publish status change event.
        
        This is used for explicit status transitions (not progress-based).
        
        Args:
            db: Database session
            job_id: Job ID to update
            status: New job status
            error_code: Error code if failed
            error_message: Error message if failed
            output_data: Output data if completed
            worker_id: Worker process/thread ID processing the job
            
        Returns:
            Dict with update status and details
        """
        try:
            # Get job with lock
            stmt = select(Job).where(Job.id == job_id).with_for_update()
            job = db.execute(stmt).scalar_one_or_none()
            
            if not job:
                return {
                    "success": False,
                    "error": "Job not found",
                    "job_id": job_id
                }
            
            # Store previous state
            previous_status = job.status
            previous_progress = job.progress
            
            # Don't allow status regression (except for retry scenarios)
            terminal_states = [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.TIMEOUT]
            if job.status in terminal_states and status not in [JobStatus.PENDING, JobStatus.QUEUED]:
                logger.warning(
                    f"Cannot change job {job_id} status from terminal state "
                    f"{job.status.value} to {status.value}"
                )
                return {
                    "success": False,
                    "error": f"Job already in terminal state: {job.status.value}",
                    "job_id": job_id,
                    "current_status": job.status.value,
                    "requested_status": status.value
                }
            
            # Update job status
            job.status = status
            
            # Update timestamps based on status
            now = datetime.now(timezone.utc)
            if status == JobStatus.RUNNING and not job.started_at:
                job.started_at = now
            elif status in terminal_states:
                job.finished_at = now
            
            # Update progress based on status
            if status == JobStatus.COMPLETED:
                job.progress = 100
            elif status in [JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.TIMEOUT]:
                # Keep current progress for failed/cancelled jobs
                pass
            elif status == JobStatus.RUNNING and job.progress == 0:
                job.progress = 1  # Indicate started
            
            # Handle error information
            if error_code:
                job.error_code = error_code
            if error_message:
                job.error_message = error_message
            
            # Handle output data
            if output_data:
                job.output_data = output_data
            
            # Update metrics
            if not job.metrics:
                job.metrics = {}
            
            job.metrics["last_status_change"] = {
                "timestamp": now.isoformat(),
                "from_status": previous_status.value if previous_status else None,
                "to_status": status.value,
                "error_code": error_code,
                "error_message": error_message[:100] if error_message else None  # Truncate for metrics
            }
            
            # Handle retry scenarios
            if status == JobStatus.RETRYING:
                # Only increment retry_count for RETRYING status
                # attempts is already incremented when job is initially processed
                job.retry_count = (job.retry_count or 0) + 1
            
            # Commit changes
            db.commit()
            
            # Create audit log for job state transition (Task 6.8)
            try:
                if status == JobStatus.RUNNING:
                    await job_audit_service.audit_job_started(
                        db=db,
                        job_id=job_id,
                        worker_id=worker_id,  # Now passed from caller context
                        task_id=job.task_id,
                        metadata={"previous_status": previous_status.value if previous_status else None}
                    )
                elif status == JobStatus.COMPLETED:
                    duration_ms = None
                    if job.started_at and job.finished_at:
                        duration_ms = int((job.finished_at - job.started_at).total_seconds() * 1000)
                    await job_audit_service.audit_job_succeeded(
                        db=db,
                        job_id=job_id,
                        output_data=output_data,
                        duration_ms=duration_ms,
                        metadata={"previous_status": previous_status.value if previous_status else None}
                    )
                elif status == JobStatus.FAILED:
                    await job_audit_service.audit_job_failed(
                        db=db,
                        job_id=job_id,
                        error_code=error_code or "UNKNOWN",
                        error_message=error_message or "Unknown error",
                        metadata={"previous_status": previous_status.value if previous_status else None}
                    )
                elif status == JobStatus.RETRYING:
                    await job_audit_service.audit_job_retrying(
                        db=db,
                        job_id=job_id,
                        retry_count=job.retry_count,
                        error_code=error_code,
                        error_message=error_message,
                        metadata={"previous_status": previous_status.value if previous_status else None}
                    )
                db.commit()
            except Exception as audit_error:
                # Log but don't fail the status update if audit fails
                logger.error(
                    f"Failed to create audit log for job {job_id} status change to {status.value}",
                    extra={
                        "job_id": job_id,
                        "status": status.value,
                        "error": str(audit_error)
                    }
                )
            
            # Always publish event for status changes
            await self.event_publisher.publish_job_status_changed(
                job_id=job_id,
                status=status.value,
                progress=job.progress,
                attempt=job.attempts,
                previous_status=previous_status.value if previous_status else None,
                previous_progress=previous_progress,
                error_code=error_code,
                error_message=error_message
            )
            
            logger.info(
                f"Status updated for job {job_id}: {previous_status.value if previous_status else 'None'} -> {status.value}",
                extra={
                    "job_id": job_id,
                    "status": status.value,
                    "previous_status": previous_status.value if previous_status else None,
                    "progress": job.progress,
                    "attempts": job.attempts
                }
            )
            
            return {
                "success": True,
                "job_id": job_id,
                "status": status.value,
                "previous_status": previous_status.value if previous_status else None,
                "progress": job.progress,
                "event_published": True
            }
            
        except (IntegrityError, OperationalError) as e:
            db.rollback()
            logger.error(
                f"Database error updating status for job {job_id}: {e}",
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
    
    async def get_progress(
        self,
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
            stmt = select(Job).where(Job.id == job_id)
            job = db.execute(stmt).scalar_one_or_none()
            
            if not job:
                return None
            
            # Extract progress information from metrics
            progress_info = {
                "job_id": job_id,
                "percent": job.progress,
                "status": job.status.value,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            }
            
            # Add progress details from metrics if available
            if job.metrics:
                if "progress_step" in job.metrics:
                    progress_info["step"] = job.metrics["progress_step"]
                if "progress_message" in job.metrics:
                    progress_info["message"] = job.metrics["progress_message"]
                if "last_progress_update" in job.metrics:
                    progress_info["last_update"] = job.metrics["last_progress_update"]
            
            return progress_info
            
        except (IntegrityError, OperationalError) as e:
            logger.error(
                f"Database error getting progress for job {job_id}: {e}",
                extra={"job_id": job_id, "error": str(e)}
            )
            return None


# Global service instance
worker_progress_service = WorkerProgressService()