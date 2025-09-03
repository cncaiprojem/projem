"""
Assembly4 Celery Tasks for Task 7.8

This module implements asynchronous task processing for Assembly4 operations.

Features:
- Assembly processing with OndselSolver
- CAM generation via Path Workbench
- Collision detection and DOF analysis
- Export to multiple formats
- Progress tracking and notifications
- Error handling with DLQ support
"""

from __future__ import annotations

import json
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

from celery import Task
from sqlalchemy.orm import Session

from ..core.celery_app import celery_app
from ..core.database import SessionLocal
from ..core.logging import get_logger
from ..core import metrics
from ..models.job import Job
from ..schemas.assembly4 import (
    Assembly4Input,
    CAMJobParameters,
    ExportOptions,
)
from ..services.assembly4_service import assembly4_service, Assembly4Exception
from ..services.s3_service import s3_service
from ..services.dlq import push_to_dlq

logger = get_logger(__name__)


class Assembly4Task(Task):
    """Base class for Assembly4 tasks with error handling."""
    
    autoretry_for = (Exception,)
    retry_kwargs = {
        "max_retries": 3,
        "countdown": 60,  # Wait 60 seconds before retry
    }
    retry_backoff = True
    retry_jitter = True
    acks_late = True
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Handle task failure."""
        job_id = kwargs.get("job_id") or (args[0] if args else None)
        
        if job_id:
            try:
                with SessionLocal() as db:
                    job = db.query(Job).filter_by(id=job_id).first()
                    if job:
                        job.status = "failed"
                        job.error_message = str(exc)
                        job.finished_at = datetime.utcnow()
                        db.commit()
                        
                        # Push to DLQ
                        push_to_dlq(
                            job_id=job_id,
                            task_name="assembly4.process",
                            error=str(exc),
                            traceback=str(einfo)
                        )
                        
                        metrics.assembly_task_failures.labels(
                            error_type=type(exc).__name__
                        ).inc()
                        
            except Exception as e:
                logger.error(f"Failed to update job on failure: {e}")
    
    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Handle task retry."""
        job_id = kwargs.get("job_id") or (args[0] if args else None)
        
        if job_id:
            metrics.assembly_task_retries.inc()
            logger.warning(f"Retrying assembly task for job {job_id}: {exc}")
    
    def on_success(self, retval, task_id, args, kwargs):
        """Handle task success."""
        job_id = kwargs.get("job_id") or (args[0] if args else None)
        
        if job_id:
            metrics.assembly_task_successes.inc()
            logger.info(f"Assembly task completed successfully for job {job_id}")


@celery_app.task(
    base=Assembly4Task,
    bind=True,
    name="assembly4.process",
    queue="assembly",
    soft_time_limit=1800,  # 30 minutes soft limit
    time_limit=2100,  # 35 minutes hard limit
)
def process_assembly4_task(
    self,
    job_id: str,
    assembly_input: Dict[str, Any],
    generate_cam: bool = False,
    cam_parameters: Optional[Dict[str, Any]] = None,
    export_options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Process Assembly4 task asynchronously.
    
    Args:
        job_id: Unique job identifier
        assembly_input: Assembly4 input data
        generate_cam: Whether to generate CAM paths
        cam_parameters: CAM generation parameters
        export_options: Export options
        
    Returns:
        Processing results including assembly and CAM outputs
    """
    start_time = time.time()
    
    try:
        with SessionLocal() as db:
            # Get job record
            job = db.query(Job).filter_by(id=job_id).first()
            if not job:
                raise ValueError(f"Job not found: {job_id}")
            
            # Update job status to running
            job.status = "running"
            job.started_at = datetime.utcnow()
            job.task_id = self.request.id
            db.commit()
            
            # Update progress
            self.update_state(
                state="PROGRESS",
                meta={
                    "current": 10,
                    "total": 100,
                    "status": "Parsing assembly input..."
                }
            )
            
            # Parse input schemas
            assembly_input_obj = Assembly4Input(**assembly_input)
            cam_params_obj = None
            if cam_parameters:
                cam_params_obj = CAMJobParameters(**cam_parameters)
            
            export_opts_obj = None
            if export_options:
                export_opts_obj = ExportOptions(**export_options)
            else:
                # Default export options
                export_opts_obj = ExportOptions(
                    formats=["FCStd", "STEP", "BOM_JSON"],
                    generate_exploded=False
                )
            
            # Update progress
            self.update_state(
                state="PROGRESS",
                meta={
                    "current": 20,
                    "total": 100,
                    "status": "Processing assembly..."
                }
            )
            
            # Process assembly
            result = assembly4_service.process_assembly(
                job_id=job_id,
                assembly_input=assembly_input_obj,
                generate_cam=generate_cam,
                cam_parameters=cam_params_obj,
                export_options=export_opts_obj
            )
            
            # Update progress
            self.update_state(
                state="PROGRESS",
                meta={
                    "current": 80,
                    "total": 100,
                    "status": "Uploading results to S3..."
                }
            )
            
            # Upload results to S3
            artifacts = []
            
            # Upload assembly file
            if result.assembly_file:
                s3_key = f"assembly4/{job_id}/assembly.FCStd"
                s3_service.upload_file(result.assembly_file, s3_key)
                artifacts.append({
                    "type": "assembly",
                    "s3_key": s3_key,
                    "size": s3_service.get_file_size(s3_key)
                })
            
            # Upload STEP file
            if result.step_file:
                s3_key = f"assembly4/{job_id}/assembly.step"
                s3_service.upload_file(result.step_file, s3_key)
                artifacts.append({
                    "type": "step",
                    "s3_key": s3_key,
                    "size": s3_service.get_file_size(s3_key)
                })
            
            # Upload exploded view
            if result.exploded_file:
                s3_key = f"assembly4/{job_id}/exploded.FCStd"
                s3_service.upload_file(result.exploded_file, s3_key)
                artifacts.append({
                    "type": "exploded",
                    "s3_key": s3_key,
                    "size": s3_service.get_file_size(s3_key)
                })
            
            # Upload BOM
            if result.bom:
                # Use model_dump() directly for more efficient serialization
                s3_key = f"assembly4/{job_id}/bom.json"
                bom_data = result.bom.model_dump()
                s3_service.upload_json(bom_data, s3_key)
                artifacts.append({
                    "type": "bom",
                    "s3_key": s3_key,
                    "size": s3_service.get_file_size(s3_key)
                })
            
            # Upload CAM files
            if result.cam_files:
                for i, cam_file in enumerate(result.cam_files):
                    file_ext = cam_file.split(".")[-1]
                    s3_key = f"assembly4/{job_id}/cam_{i}.{file_ext}"
                    s3_service.upload_file(cam_file, s3_key)
                    artifacts.append({
                        "type": f"cam_{file_ext}",
                        "s3_key": s3_key,
                        "size": s3_service.get_file_size(s3_key)
                    })
            
            # Update progress
            self.update_state(
                state="PROGRESS",
                meta={
                    "current": 95,
                    "total": 100,
                    "status": "Finalizing..."
                }
            )
            
            # Update job with results
            job.status = "succeeded"
            job.finished_at = datetime.utcnow()
            job.result = {
                "assembly_result": result.model_dump(exclude_none=True),
                "artifacts": artifacts
            }
            job.artefacts = artifacts
            
            # Add metrics
            if not job.metrics:
                job.metrics = {}
            
            job.metrics.update({
                "processing_time_ms": result.computation_time_ms,
                "total_time_ms": (time.time() - start_time) * 1000,
                "collisions_found": len(result.collision_report.collisions) if result.collision_report else 0,
                "is_fully_constrained": result.dof_analysis.is_fully_constrained if result.dof_analysis else None
            })
            
            db.commit()
            
            # Record metrics
            metrics.assembly_processing_duration.observe(result.computation_time_ms / 1000)
            metrics.assembly_jobs_completed.labels(
                status="success",
                solver_type=assembly_input_obj.solver_type
            ).inc()
            
            # Log warnings if any
            if result.warnings:
                for warning in result.warnings:
                    logger.warning(f"Assembly warning for job {job_id}: {warning}")
            
            return {
                "job_id": job_id,
                "status": "success",
                "artifacts": artifacts,
                "processing_time_ms": result.computation_time_ms
            }
            
    except Assembly4Exception as e:
        logger.error(f"Assembly4 error for job {job_id}: {e}")
        
        with SessionLocal() as db:
            job = db.query(Job).filter_by(id=job_id).first()
            if job:
                job.status = "failed"
                job.error_message = e.turkish_message
                job.error_code = e.error_code.value
                job.finished_at = datetime.utcnow()
                db.commit()
        
        metrics.assembly_jobs_completed.labels(
            status="failed",
            solver_type=assembly_input.get("solver_type", "unknown")
        ).inc()
        
        raise
        
    except Exception as e:
        logger.error(f"Unexpected error for job {job_id}: {e}\n{traceback.format_exc()}")
        
        with SessionLocal() as db:
            job = db.query(Job).filter_by(id=job_id).first()
            if job:
                job.status = "failed"
                job.error_message = str(e)
                job.finished_at = datetime.utcnow()
                db.commit()
        
        metrics.assembly_jobs_completed.labels(
            status="failed",
            solver_type=assembly_input.get("solver_type", "unknown")
        ).inc()
        
        raise


@celery_app.task(
    bind=True,
    name="assembly4.cleanup",
    queue="maintenance",
    soft_time_limit=300,
    time_limit=360
)
def cleanup_assembly_files(self, job_id: str, age_days: int = 7) -> Dict[str, Any]:
    """
    Clean up old assembly files from S3.
    
    Args:
        job_id: Job ID to clean up
        age_days: Age threshold in days
        
    Returns:
        Cleanup results
    """
    try:
        with SessionLocal() as db:
            # Get job
            job = db.query(Job).filter_by(id=job_id).first()
            if not job:
                return {"error": "Job not found"}
            
            # Check age
            age = (datetime.utcnow() - job.created_at).days
            if age < age_days:
                return {"skipped": f"Job is only {age} days old"}
            
            # Delete S3 files
            deleted_files = []
            if job.artefacts:
                for artifact in job.artefacts:
                    s3_key = artifact.get("s3_key")
                    if s3_key:
                        try:
                            s3_service.delete_file(s3_key)
                            deleted_files.append(s3_key)
                        except Exception as e:
                            logger.warning(f"Failed to delete {s3_key}: {e}")
            
            # Clear artifacts from job
            job.artefacts = None
            db.commit()
            
            metrics.assembly_files_cleaned.inc()
            
            return {
                "job_id": job_id,
                "deleted_files": deleted_files,
                "count": len(deleted_files)
            }
            
    except Exception as e:
        logger.error(f"Cleanup failed for job {job_id}: {e}")
        return {"error": str(e)}


@celery_app.task(
    bind=True,
    name="assembly4.validate_batch",
    queue="assembly",
    soft_time_limit=600,
    time_limit=720
)
def validate_batch_assemblies(
    self,
    assembly_inputs: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Validate a batch of assembly inputs.
    
    Args:
        assembly_inputs: List of assembly inputs to validate
        
    Returns:
        Validation results for each input
    """
    results = []
    
    for i, assembly_input in enumerate(assembly_inputs):
        # Update progress
        self.update_state(
            state="PROGRESS",
            meta={
                "current": i + 1,
                "total": len(assembly_inputs),
                "status": f"Validating assembly {i + 1}/{len(assembly_inputs)}"
            }
        )
        
        try:
            # Parse and validate
            assembly_obj = Assembly4Input(**assembly_input)
            
            # Perform DOF analysis
            from ..services.assembly4_service import DOFAnalyzer
            analyzer = DOFAnalyzer()
            dof_result = analyzer.analyze(assembly_obj.parts, assembly_obj.constraints)
            
            results.append({
                "index": i,
                "valid": True,
                "name": assembly_obj.name,
                "parts_count": len(assembly_obj.parts),
                "constraints_count": len(assembly_obj.constraints),
                "is_fully_constrained": dof_result.is_fully_constrained,
                "is_over_constrained": dof_result.is_over_constrained,
                "remaining_dof": dof_result.remaining_dof
            })
            
        except Exception as e:
            results.append({
                "index": i,
                "valid": False,
                "error": str(e)
            })
    
    # Summary statistics
    valid_count = sum(1 for r in results if r.get("valid"))
    fully_constrained = sum(1 for r in results if r.get("is_fully_constrained"))
    
    return {
        "total": len(assembly_inputs),
        "valid": valid_count,
        "invalid": len(assembly_inputs) - valid_count,
        "fully_constrained": fully_constrained,
        "results": results
    }