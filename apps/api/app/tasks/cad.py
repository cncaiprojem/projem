from __future__ import annotations

import logging
import tempfile
from celery import shared_task

from ..db import SessionLocal
# from ..models_project import Project, ProjectFile, FileKind, ProjectStatus  # Module not found
# Temporary stub for missing models
class Project: pass
class ProjectFile: pass  
class FileKind: pass
class ProjectStatus: pass
from ..storage import upload_and_sign
from ..freecad.cad_build import build_from_plan

# Task 6.2: Import retry strategy components
from ..core.retry_config import MODEL_TASK_RETRY_KWARGS, create_task_headers_with_retry_info
from ..core.error_taxonomy import (
    TransientExternalError, 
    NetworkError, 
    ValidationError,
    get_error_metadata
)
from ..core.dlq_handler import handle_task_failure

# Task 6.6: Import cancellation support
from ..services.job_cancellation_service import check_cancel, mark_cancelled, JobCancelledError

# Task 6.7: Import progress helpers
from .worker_helpers import progress, start_job, complete_job, fail_job

logger = logging.getLogger(__name__)


# Task 6.2: Add failure callback for additional observability
def cad_build_task_on_failure(self, exc, task_id, args, kwargs, einfo):
    """
    Callback for when CAD build task fails permanently.
    This provides additional logging and potential cleanup.
    """
    project_id = args[0] if args else "unknown"
    error_metadata = get_error_metadata(exc)
    
    logger.error(
        f"CAD build task {task_id} failed permanently for project {project_id}. "
        f"Error type: {error_metadata['error_type']}, "
        f"Classification: {error_metadata['error_classification']}"
    )


def _handle_cancellation_check(db, job_id: int, task_id: str, cancellation_point: str, final_progress: dict):
    """
    Helper function to handle job cancellation checks.
    
    Encapsulates the try/except logic for checking and handling job cancellation,
    reducing code duplication in the main task function.
    
    Args:
        db: Database session
        job_id: The job ID to check
        task_id: Task ID for logging
        cancellation_point: Where the cancellation was detected (e.g., "start", "after_freecad")
        final_progress: Progress information to record when marking as cancelled
        
    Returns:
        dict: Cancellation result if job was cancelled, None otherwise
    """
    try:
        check_cancel(db, job_id)
    except JobCancelledError as e:
        logger.info(f"CAD build task {task_id} cancelled at {cancellation_point} for project {job_id}")
        # Task 6.6 fix from PR #231: Use centralized mark_cancelled function
        # Now synchronous - no need for asyncio.run
        mark_cancelled(
            db=db,
            job_id=job_id,
            cancellation_point=cancellation_point,
            final_progress=final_progress
        )
        return {"status": "cancelled", "project_id": job_id}
    return None


@shared_task(bind=True, on_failure=cad_build_task_on_failure, queue='model', **MODEL_TASK_RETRY_KWARGS)
def cad_build_task(self, project_id: int):
    """
    CAD build task with Task 6.2 retry strategy.
    
    Uses model queue configuration: 5 retries, 60s cap, 15min time limit.
    Implements proper error classification and DLQ handling.
    """
    task_id = self.request.id
    attempt_count = getattr(self.request, 'retries', 0) + 1
    
    # Task 6.2: Log retry attempt for observability
    if attempt_count > 1:
        logger.info(f"CAD build task {task_id} retry attempt {attempt_count} for project {project_id}")
    
    db = SessionLocal()
    try:
        # Task 6.7: Report job starting with progress helper
        start_job(db, project_id, f"Starting CAD build task {task_id}")
        
        # Task 6.6: Check for cancellation at start
        cancellation_result = _handle_cancellation_check(
            db, project_id, task_id, "start", 
            {"step": "startup", "percent": 0}
        )
        if cancellation_result:
            return cancellation_result
        
        # Task 6.2: Input validation - non-retryable error
        if not isinstance(project_id, int) or project_id <= 0:
            raise ValidationError(f"Invalid project_id: {project_id}")
        
        p = db.query(Project).get(project_id)
        if not p:
            raise ValidationError(f"Project {project_id} not found")
        
        if not p.summary_json:
            raise ValidationError(f"Project {project_id} has no plan data")
        
        plan = (p.summary_json or {}).get("plan") or {}
        if not plan:
            raise ValidationError(f"Project {project_id} has empty plan")
        
        # Task 6.7: Report progress before FreeCAD processing
        progress(db, project_id, 10, "preprocessing", "Preparing FreeCAD environment")
        
        # CAD processing with proper error classification
        with tempfile.TemporaryDirectory() as d:
            try:
                # Task 6.7: Report progress before building
                progress(db, project_id, 20, "building", "Building CAD model from plan")
                
                paths, stats = build_from_plan(plan, d)
                
                # Task 6.7: Report progress after successful build
                progress(db, project_id, 50, "build_complete", f"CAD model built successfully")
                
            except ConnectionError as e:
                # Network issues with FreeCAD subprocess - retryable
                raise NetworkError(f"FreeCAD connection failed: {str(e)}") from e
            except OSError as e:
                # File I/O issues - retryable
                raise TransientExternalError(f"File system error: {str(e)}") from e
            except Exception as e:
                # Unknown errors from FreeCAD - treat as retryable initially
                if "memory" in str(e).lower() or "timeout" in str(e).lower():
                    raise TransientExternalError(f"FreeCAD processing error: {str(e)}") from e
                else:
                    # Re-raise for normal handling
                    raise
            
            # Task 6.6: Check for cancellation after FreeCAD processing
            cancellation_result = _handle_cancellation_check(
                db, project_id, task_id, "after_freecad",
                {"step": "freecad_complete", "percent": 50}
            )
            if cancellation_result:
                return cancellation_result
            
            # Task 6.7: Report progress for file processing
            progress(db, project_id, 60, "uploading", "Uploading CAD artifacts to storage")
            
            # Process results
            out = {}
            total_files = len([p for p in paths.values() if p])
            processed_files = 0
            
            for kind, path in paths.items():
                if not path:
                    continue
                
                try:
                    # Task 6.7: Report progress for each file
                    processed_files += 1
                    # Check for zero division before calculating progress
                    if total_files > 0:
                        file_progress = 60 + int((processed_files / total_files) * 30)  # 60-90% range
                    else:
                        file_progress = 90  # Default to 90% if no files to process
                    progress(
                        db, project_id, file_progress, 
                        "uploading", 
                        f"Uploading {kind} file ({processed_files}/{total_files})"
                    )
                    
                    art = upload_and_sign(path, type=f"cad/{kind}")
                except ConnectionError as e:
                    # S3 upload network issues - retryable
                    raise NetworkError(f"S3 upload failed: {str(e)}") from e
                except Exception as e:
                    if "timeout" in str(e).lower():
                        raise TransientExternalError(f"Storage upload timeout: {str(e)}") from e
                    else:
                        raise
                
                # Database operations
                try:
                    f = ProjectFile(
                        project_id=p.id,
                        kind=FileKind.cad,
                        s3_key=art["s3_key"],
                        size=art["size"],
                        sha256=art["sha256"],
                        version=(plan or {}).get("rev") or "v1",
                        notes=kind,
                    )
                    db.add(f)
                    db.commit()
                except Exception as e:
                    db.rollback()
                    if "integrity" in str(e).lower() or "constraint" in str(e).lower():
                        # Database integrity errors - usually not retryable
                        raise ValidationError(f"Database constraint violation: {str(e)}") from e
                    else:
                        # Other DB errors might be retryable (connection issues)
                        raise TransientExternalError(f"Database error: {str(e)}") from e
                
                out[kind] = art.get("signed_url")
            
            # Task 6.7: Report finalizing progress
            progress(db, project_id, 95, "finalizing", "Finalizing CAD build results")
            
            # Update project status
            try:
                p.status = ProjectStatus.cad_ready if stats.get("ok") else ProjectStatus.error
                p.summary_json = {**(p.summary_json or {}), "cad_stats": stats, "cad_artifacts": out}
                db.commit()
            except Exception as e:
                db.rollback()
                raise TransientExternalError(f"Failed to update project status: {str(e)}") from e
            
            # Task 6.7: Mark job as completed with output data
            output_data = {"artifacts": out, "stats": stats}
            complete_job(db, project_id, output_data, "CAD build completed successfully")
            
            # Task 6.2: Log successful completion
            logger.info(f"CAD build task {task_id} completed successfully for project {project_id} after {attempt_count} attempts")
            
            return {"project_id": p.id, "artifacts": out, "stats": stats}
            
    except Exception as exc:
        # Task 6.2: Enhanced error handling with retry strategy
        logger.error(f"CAD build task {task_id} failed (attempt {attempt_count}): {exc}", exc_info=True)
        
        # Task 6.7: Report failure with progress helper
        error_metadata = get_error_metadata(exc)
        fail_job(
            db, project_id,
            error_code=error_metadata.get("error_type", "UNKNOWN_ERROR"),
            error_message=str(exc)[:500],  # Truncate long error messages
            progress_percent=None  # Keep current progress
        )
        
        # Let the handle_task_failure function decide retry vs DLQ
        handle_task_failure(
            self, exc, task_id, 
            args=(project_id,), 
            kwargs={}, 
            einfo=None
        )
        
        # Re-raise to let Celery handle the retry/failure
        raise
        
    finally:
        db.close()
