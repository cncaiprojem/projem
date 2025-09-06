"""
Garbage collection tasks for Task 7.11.

Handles async deletion of artefacts from object storage
with retry logic and error handling.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

import structlog
from celery import Task
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.celery_app import celery_app
from app.core.config import settings
from app.models.artefact import Artefact
from app.services.storage_client import StorageClient, StorageClientError

logger = structlog.get_logger(__name__)

# Database session for Celery tasks
engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class ArtefactGarbageCollectionTask(Task):
    """Base task class for artefact garbage collection."""

    autoretry_for = (StorageClientError,)
    retry_kwargs = {"max_retries": 3, "countdown": 60}
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True

    def __init__(self):
        super().__init__()
        self.storage_client = None

    def get_storage_client(self) -> StorageClient:
        """Get or create storage client."""
        if self.storage_client is None:
            self.storage_client = StorageClient()
        return self.storage_client


@celery_app.task(
    bind=True,
    base=ArtefactGarbageCollectionTask,
    name="artefact_gc",
    queue="default",
    routing_key="jobs.maintenance",
)
def schedule_artefact_gc(
    self,
    artefact_id: int,
    bucket: str,
    key: str,
    version_id: Optional[str] = None,
    delete_all_versions: bool = True,
) -> dict:
    """
    Garbage collect artefact from object storage.
    
    This task is idempotent and can be safely retried.
    
    Args:
        artefact_id: Database artefact ID
        bucket: S3 bucket name
        key: S3 object key
        version_id: Specific version to delete
        delete_all_versions: Delete all versions of the object
        
    Returns:
        Dict with deletion results
    """
    start_time = time.time()
    db = SessionLocal()
    storage_client = self.get_storage_client()

    try:
        # Get artefact record
        artefact = db.query(Artefact).filter_by(id=artefact_id).first()

        if not artefact:
            logger.warning(
                "Artefact not found in database, proceeding with storage deletion",
                artefact_id=artefact_id,
                bucket=bucket,
                key=key,
            )
        else:
            # Update deletion status
            artefact.set_meta("deletion_started_at", datetime.now(timezone.utc).isoformat())

        # Delete from storage
        deleted_count = 0
        errors = []

        try:
            if delete_all_versions:
                # Delete all versions (including delete markers)
                deleted_count = storage_client.delete_all_versions(
                    bucket=bucket,
                    prefix=key,  # Use key as prefix to get all versions
                )
            else:
                # Delete specific version
                success = storage_client.delete_object(
                    bucket=bucket,
                    key=key,
                    version_id=version_id,
                )
                deleted_count = 1 if success else 0

            logger.info(
                "Storage deletion successful",
                artefact_id=artefact_id,
                bucket=bucket,
                key=key,
                deleted_count=deleted_count,
            )

            # Update artefact record if it exists
            if artefact:
                artefact.deletion_pending = False
                artefact.last_error = None
                artefact.set_meta("deletion_completed_at", datetime.now(timezone.utc).isoformat())
                artefact.set_meta("deleted_versions", deleted_count)
                db.commit()

        except StorageClientError as e:
            error_msg = f"Storage deletion failed: {str(e)}"
            errors.append(error_msg)
            logger.error(
                error_msg,
                artefact_id=artefact_id,
                bucket=bucket,
                key=key,
                error=str(e),
            )

            # Update error status
            if artefact:
                artefact.last_error = error_msg
                artefact.set_meta("last_deletion_attempt", datetime.now(timezone.utc).isoformat())
                db.commit()

            # Re-raise for retry
            raise

        elapsed_time = time.time() - start_time

        result = {
            "artefact_id": artefact_id,
            "bucket": bucket,
            "key": key,
            "deleted_count": deleted_count,
            "errors": errors,
            "elapsed_time": elapsed_time,
            "success": len(errors) == 0,
        }

        logger.info(
            "Garbage collection completed",
            **result,
        )

        return result

    except Exception as e:
        logger.error(
            "Garbage collection failed",
            artefact_id=artefact_id,
            bucket=bucket,
            key=key,
            error=str(e),
            exc_info=True,
        )

        # Update error status if artefact exists
        if db:
            try:
                artefact = db.query(Artefact).filter_by(id=artefact_id).first()
                if artefact:
                    artefact.last_error = f"GC failed: {str(e)}"
                    artefact.set_meta("last_gc_error", str(e))
                    artefact.set_meta("last_gc_attempt", datetime.now(timezone.utc).isoformat())
                    db.commit()
            except Exception as db_error:
                logger.error("Failed to update error status", error=str(db_error))

        raise

    finally:
        if db:
            db.close()


@celery_app.task(
    name="bulk_artefact_gc",
    queue="default",
    routing_key="jobs.maintenance",
)
def bulk_artefact_gc(job_id: int) -> dict:
    """
    Bulk garbage collect all artefacts for a job.
    
    Args:
        job_id: Job ID to clean up
        
    Returns:
        Dict with bulk deletion results
    """
    db = SessionLocal()
    storage_client = StorageClient()
    
    try:
        # Get all artefacts for the job
        artefacts = db.query(Artefact).filter_by(job_id=job_id).all()
        
        total_count = len(artefacts)
        deleted_count = 0
        failed_count = 0
        errors = []
        
        for artefact in artefacts:
            try:
                # Schedule individual GC task
                schedule_artefact_gc.delay(
                    artefact_id=artefact.id,
                    bucket=artefact.s3_bucket,
                    key=artefact.s3_key,
                    version_id=artefact.version_id,
                    delete_all_versions=True,
                )
                deleted_count += 1
                
            except Exception as e:
                failed_count += 1
                error_msg = f"Failed to schedule GC for artefact {artefact.id}: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg, artefact_id=artefact.id, job_id=job_id)
        
        result = {
            "job_id": job_id,
            "total_artefacts": total_count,
            "scheduled_for_deletion": deleted_count,
            "failed_to_schedule": failed_count,
            "errors": errors,
            "success": failed_count == 0,
        }
        
        logger.info(
            "Bulk garbage collection scheduled",
            **result,
        )
        
        return result
        
    except Exception as e:
        logger.error(
            "Bulk garbage collection failed",
            job_id=job_id,
            error=str(e),
            exc_info=True,
        )
        raise
        
    finally:
        if db:
            db.close()


@celery_app.task(
    name="periodic_gc_retry",
    queue="default",
    routing_key="jobs.maintenance",
)
def periodic_gc_retry() -> dict:
    """
    Periodic task to retry failed garbage collections.
    
    This should be scheduled to run periodically (e.g., every hour).
    
    Returns:
        Dict with retry results
    """
    db = SessionLocal()
    
    try:
        # Find artefacts with pending deletion and errors
        failed_artefacts = (
            db.query(Artefact)
            .filter(
                Artefact.deletion_pending == True,
                Artefact.last_error.isnot(None),
            )
            .all()
        )
        
        total_count = len(failed_artefacts)
        retry_count = 0
        skip_count = 0
        
        for artefact in failed_artefacts:
            # Check if it's been too long (e.g., > 7 days)
            deletion_requested = artefact.get_meta("deletion_requested_at")
            if deletion_requested:
                from datetime import datetime, timedelta
                requested_time = datetime.fromisoformat(deletion_requested.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) - requested_time > timedelta(days=7):
                    logger.warning(
                        "Skipping old failed deletion",
                        artefact_id=artefact.id,
                        requested_at=deletion_requested,
                    )
                    skip_count += 1
                    continue
            
            # Retry the deletion
            try:
                schedule_artefact_gc.delay(
                    artefact_id=artefact.id,
                    bucket=artefact.s3_bucket,
                    key=artefact.s3_key,
                    version_id=artefact.version_id,
                    delete_all_versions=True,
                )
                retry_count += 1
                
                # Clear error for retry
                artefact.last_error = None
                artefact.set_meta("gc_retry_at", datetime.now(timezone.utc).isoformat())
                
            except Exception as e:
                logger.error(
                    "Failed to retry GC",
                    artefact_id=artefact.id,
                    error=str(e),
                )
        
        db.commit()
        
        result = {
            "total_failed": total_count,
            "retried": retry_count,
            "skipped": skip_count,
            "success": True,
        }
        
        logger.info(
            "Periodic GC retry completed",
            **result,
        )
        
        return result
        
    except Exception as e:
        logger.error(
            "Periodic GC retry failed",
            error=str(e),
            exc_info=True,
        )
        raise
        
    finally:
        if db:
            db.close()


# Export tasks
__all__ = [
    "schedule_artefact_gc",
    "bulk_artefact_gc",
    "periodic_gc_retry",
]