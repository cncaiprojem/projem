"""
Job cancellation service for handling license expiry and graceful job termination.

Task 4.9: Edge-case handling for running jobs on license expiry.
"""

from datetime import timezone, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..core.exceptions import ServiceError
from ..core.logging import get_logger
from ..models.enums import JobStatus
from ..models.job import Job
from ..models.license import License
from ..services.audit_service import audit_service
from ..tasks.celery_app import celery_app

logger = get_logger(__name__)


class JobCancellationService:
    """Service for handling job cancellation on license expiry."""

    def __init__(self):
        """Initialize job cancellation service."""
        self.logger = logger.bind(service="job_cancellation")

    async def cancel_jobs_for_expired_license(
        self,
        db: Session,
        license_id: int,
        user_id: int,
        reason: str = "license_expired"
    ) -> dict[str, Any]:
        """
        Cancel all running and pending jobs for a user when their license expires.
        
        Args:
            db: Database session
            license_id: ID of the expired license
            user_id: ID of the user whose license expired
            reason: Cancellation reason (default: license_expired)
            
        Returns:
            Dictionary with cancellation results
        """
        try:
            # Start transaction with savepoint for rollback capability
            with db.begin_nested():
                # Find all active jobs for the user
                active_jobs = db.execute(
                    select(Job).where(
                        and_(
                            Job.user_id == user_id,
                            Job.status.in_([JobStatus.RUNNING, JobStatus.PENDING, JobStatus.QUEUED])
                        )
                    )
                ).scalars().all()

                affected_job_ids = []
                cancelled_count = 0

                for job in active_jobs:
                    # Set cancel_requested flag
                    job.cancel_requested = True
                    job.cancellation_reason = reason
                    if not job.metrics:
                        job.metrics = {}
                    job.metrics["cancel_requested_time"] = datetime.now(timezone.utc).isoformat()
                    affected_job_ids.append(job.id)

                    # If job is pending or queued, cancel immediately
                    if job.status in [JobStatus.PENDING, JobStatus.QUEUED]:
                        job.set_cancelled(reason)
                        cancelled_count += 1

                        self.logger.info(
                            "Job cancelled immediately",
                            job_id=job.id,
                            previous_status=job.status.value,
                            reason=reason
                        )
                    else:
                        # For running jobs, just set the flag - workers will handle it
                        self.logger.info(
                            "Cancel requested for running job",
                            job_id=job.id,
                            reason=reason
                        )

                # Create audit event for the cancellation request
                if affected_job_ids:
                    await audit_service.create_audit_entry(
                        db=db,
                        event_type="LICENSE_EXPIRED_JOBS_CANCEL",
                        user_id=user_id,
                        scope_type="license",
                        scope_id=license_id,
                        details={
                            "affected_job_ids": affected_job_ids,
                            "immediately_cancelled": cancelled_count,
                            "cancel_requested": len(affected_job_ids) - cancelled_count,
                            "reason": reason,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        },
                        ip_address="system",
                        user_agent="job_cancellation_service"
                    )

                    # Send lightweight cancellation signals to workers
                    await self._send_cancellation_signals(affected_job_ids)

                db.commit()

                self.logger.info(
                    "Jobs cancelled for expired license",
                    license_id=license_id,
                    user_id=user_id,
                    total_affected=len(affected_job_ids),
                    immediately_cancelled=cancelled_count
                )

                return {
                    "success": True,
                    "affected_jobs": affected_job_ids,
                    "immediately_cancelled": cancelled_count,
                    "cancel_requested": len(affected_job_ids) - cancelled_count
                }

        except SQLAlchemyError as e:
            db.rollback()
            self.logger.error(
                "Database error during job cancellation",
                license_id=license_id,
                user_id=user_id,
                error=str(e)
            )
            raise ServiceError(
                code="JOB_CANCELLATION_ERROR",
                message="İş iptali sırasında hata oluştu",
                details={"error": str(e)}
            ) from e
        except Exception as e:
            db.rollback()
            self.logger.error(
                "Unexpected error during job cancellation",
                license_id=license_id,
                user_id=user_id,
                error=str(e)
            )
            raise

    async def _send_cancellation_signals(self, job_ids: list[int]) -> None:
        """
        Send lightweight cancellation signals to workers.
        
        Args:
            job_ids: List of job IDs to signal for cancellation
        """
        try:
            for job_id in job_ids:
                # Send a lightweight signal via Celery
                celery_app.send_task(
                    "check_job_cancellation",
                    args=[job_id],
                    queue="default",
                    priority=9  # High priority
                )

            self.logger.info(
                "Cancellation signals sent",
                job_count=len(job_ids)
            )
        except Exception as e:
            # Don't fail the whole operation if signaling fails
            self.logger.warning(
                "Failed to send cancellation signals",
                job_ids=job_ids,
                error=str(e)
            )

    def check_cancel_requested(self, db: Session, job_id: int) -> bool:
        """
        Check if cancellation has been requested for a job.
        Used by workers to check if they should stop.
        
        Args:
            db: Database session
            job_id: Job ID to check
            
        Returns:
            True if cancellation requested, False otherwise
        """
        try:
            job = db.get(Job, job_id)
            if not job:
                return False

            return job.cancel_requested

        except Exception as e:
            self.logger.error(
                "Error checking cancel request",
                job_id=job_id,
                error=str(e)
            )
            return False

    def get_impacted_jobs_for_license(
        self,
        db: Session,
        license_id: int
    ) -> list[dict[str, Any]]:
        """
        Get all jobs impacted by a license expiry.
        
        Args:
            db: Database session
            license_id: License ID to check
            
        Returns:
            List of impacted jobs with details
        """
        try:
            # Get the license to find the user
            license = db.get(License, license_id)
            if not license:
                return []

            # Find all jobs for this user that were cancelled due to license expiry
            impacted_jobs = db.execute(
                select(Job).where(
                    and_(
                        Job.user_id == license.user_id,
                        or_(
                            Job.cancellation_reason == "license_expired",
                            and_(
                                Job.cancel_requested.is_(True),
                                Job.status.in_([JobStatus.RUNNING, JobStatus.PENDING, JobStatus.QUEUED])
                            )
                        )
                    )
                )
            ).scalars().all()

            result = []
            for job in impacted_jobs:
                result.append({
                    "id": job.id,
                    "type": job.type.value,
                    "status": job.status.value,
                    "cancel_requested": job.cancel_requested,
                    "cancellation_reason": job.cancellation_reason,
                    "created_at": job.created_at.isoformat() if job.created_at else None,
                    "started_at": job.started_at.isoformat() if job.started_at else None,
                    "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                    "progress": job.progress
                })

            return result

        except Exception as e:
            self.logger.error(
                "Error getting impacted jobs",
                license_id=license_id,
                error=str(e)
            )
            raise ServiceError(
                code="GET_IMPACTED_JOBS_ERROR",
                message="Etkilenen işler alınırken hata oluştu",
                details={"error": str(e)}
            ) from e

    def _process_checkpoint_sync(
        self,
        db: Session,
        job_id: int,
        checkpoint_data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Private synchronous method to process checkpoint logic.
        This is shared between async handle_checkpoint and Celery worker_checkpoint_task.
        
        Args:
            db: Database session
            job_id: Job ID being processed
            checkpoint_data: Optional checkpoint data to save
            
        Returns:
            Dictionary with continue flag and reason
        """
        try:
            job = db.get(Job, job_id)
            if not job:
                return {"continue": False, "reason": "job_not_found"}

            # Check if job is already in terminal state
            if job.is_complete:
                return {"continue": False, "reason": "job_complete"}

            # Check if cancellation requested
            if job.cancel_requested:
                # Save checkpoint data if provided
                if checkpoint_data:
                    if not job.metrics:
                        job.metrics = {}
                    job.metrics["last_checkpoint"] = checkpoint_data
                    job.metrics["checkpoint_time"] = datetime.now(timezone.utc).isoformat()

                # Mark job as cancelled
                job.set_cancelled(job.cancellation_reason or "license_expired")
                
                self.logger.info(
                    "Job cancelled at checkpoint",
                    job_id=job_id,
                    reason=job.cancellation_reason
                )

                return {
                    "continue": False,
                    "reason": job.cancellation_reason or "license_expired"
                }

            # Update last checkpoint time if not cancelling
            if not job.metrics:
                job.metrics = {}
            job.metrics["last_checkpoint_time"] = datetime.now(timezone.utc).isoformat()

            # Save checkpoint data if provided
            if checkpoint_data:
                job.metrics["checkpoint_data"] = checkpoint_data

            return {"continue": True, "reason": None}

        except Exception as e:
            self.logger.error(
                "Error processing checkpoint",
                job_id=job_id,
                error=str(e)
            )
            # On error, allow job to continue
            return {"continue": True, "reason": "checkpoint_error"}

    async def handle_checkpoint(
        self,
        db: Session,
        job_id: int,
        checkpoint_data: dict[str, Any] | None = None
    ) -> bool:
        """
        Handle a worker checkpoint - check if job should be cancelled.
        
        Args:
            db: Database session
            job_id: Job ID being processed
            checkpoint_data: Optional checkpoint data to save
            
        Returns:
            True if job should continue, False if it should stop
        """
        result = self._process_checkpoint_sync(db, job_id, checkpoint_data)
        
        # Commit changes if checkpoint processing succeeded
        if result["reason"] != "checkpoint_error":
            try:
                db.commit()
            except Exception as e:
                self.logger.error(
                    "Error committing checkpoint changes",
                    job_id=job_id,
                    error=str(e)
                )
                return True  # Allow job to continue on commit error

        return result["continue"]


# Singleton instance
job_cancellation_service = JobCancellationService()
