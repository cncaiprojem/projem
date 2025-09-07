"""
Task 7.16: Example FreeCAD Task with Real-time Progress Reporting

This module shows how to integrate progress reporting into Celery tasks:
- Using WorkerProgressReporter for structured progress
- Reporting FreeCAD 1.1.0-specific events
- Operation context managers
- Milestone events for important phases
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from celery import shared_task
from sqlalchemy.orm import Session

from ..core.database import SessionLocal
from ..core.logging import get_logger
from ..core.constants import FORMAT_MAP
from ..services.freecad_service import freecad_service
from ..workers.progress_reporter import WorkerProgressReporter, with_progress
from ..schemas.progress import (
    EventType,
    Phase,
    OperationGroup,
    DocumentPhase,
    Assembly4Phase,
    MaterialPhase,
    OCCTOperation,
    TopologyPhase,
    ExportFormat
)

logger = get_logger(__name__)


@shared_task(name="freecad.execute_with_progress", queue="model", bind=True)
def freecad_execute_with_progress_task(
    self,
    job_id: int,
    user_id: int,
    operation_type: str,
    script_content: str,
    parameters: dict,
    output_formats: list,
    correlation_id: str = None
) -> dict:
    """
    FreeCAD operation execution with real-time progress reporting.
    
    This example shows how to integrate progress reporting into existing tasks.
    
    Args:
        job_id: Job ID for progress tracking
        user_id: User ID for license checking
        operation_type: Type of operation
        script_content: FreeCAD Python script
        parameters: Operation parameters
        output_formats: Output file formats
        correlation_id: Request correlation ID
        
    Returns:
        Execution results with progress tracking
    """
    # Initialize progress reporter
    reporter = WorkerProgressReporter(self)
    
    db = None
    try:
        # Report task start
        reporter.report_progress(
            progress_pct=0,
            message="Başlatılıyor / Starting FreeCAD operation",
            current_step="Initialization",
            milestone=True,
            freecad_version="1.1.0",
            operation_type=operation_type
        )
        
        # Create database session
        db = SessionLocal()
        
        # Use operation context for structured tracking
        with reporter.operation(
            "FreeCAD Operation",
            OperationGroup.GENERAL,
            total_steps=5
        ) as op:
            
            # Step 1: Document creation
            op.update(1, "FreeCAD belgesi oluşturuluyor / Creating FreeCAD document")
            reporter.report_freecad_document(
                phase=DocumentPhase.DOCUMENT_OPEN,
                document_id=f"job_{job_id}",
                document_label=f"Job {job_id} Document"
            )
            
            # Step 2: Execute script
            op.update(2, "Script çalıştırılıyor / Executing script")
            
            # Simulate FreeCAD operations based on operation_type
            if "assembly" in operation_type.lower():
                _report_assembly_progress(reporter, job_id)
            elif "boolean" in operation_type.lower():
                _report_occt_progress(reporter, job_id)
            elif "material" in operation_type.lower():
                _report_material_progress(reporter, job_id)
            
            # Step 3: Execute actual operation
            op.update(3, "İşlem yürütülüyor / Processing operation")
            result = freecad_service.execute_freecad_operation(
                db=db,
                user_id=user_id,
                operation_type=operation_type,
                script_content=script_content,
                parameters=parameters,
                output_formats=output_formats,
                job_id=str(job_id),
                correlation_id=correlation_id or self.request.id
            )
            
            # Step 4: Recompute document
            op.update(4, "Belge yeniden hesaplanıyor / Recomputing document")
            reporter.report_freecad_document(
                phase=DocumentPhase.RECOMPUTE_START,
                document_id=f"job_{job_id}"
            )
            
            # Simulate recompute progress
            reporter.report_progress(
                progress_pct=80,
                message="Recompute işlemi devam ediyor / Recompute in progress",
                current_step="Document recompute"
            )
            
            reporter.report_freecad_document(
                phase=DocumentPhase.RECOMPUTE_END,
                document_id=f"job_{job_id}"
            )
            
            # Step 5: Export results
            op.update(5, "Sonuçlar dışa aktarılıyor / Exporting results")
            _report_export_progress(reporter, job_id, output_formats)
        
        # Report completion
        reporter.report_progress(
            progress_pct=100,
            message="İşlem tamamlandı / Operation completed successfully",
            current_step="Complete",
            milestone=True,
            status="completed"
        )
        
        return result.serialize_for_celery()
        
    except Exception as e:
        # Report error
        reporter.report_progress(
            progress_pct=reporter._operation_stack[-1].current_step * 20 if reporter._operation_stack else 0,
            message=f"Hata oluştu / Error occurred: {str(e)}",
            current_step="Error",
            milestone=True,
            status="failed",
            error_code=type(e).__name__
        )
        
        logger.error(
            "FreeCAD task with progress failed",
            task_id=self.request.id,
            job_id=job_id,
            error=str(e),
            exc_info=True
        )
        
        raise self.retry(exc=e, countdown=60, max_retries=3)
    
    finally:
        if db:
            db.close()


def _report_assembly_progress(reporter: WorkerProgressReporter, job_id: int):
    """Report Assembly4-specific progress."""
    # Solver start
    reporter.report_assembly4(
        phase=Assembly4Phase.SOLVER_START,
        constraints_total=10
    )
    
    # Solver progress
    for i in range(1, 11):
        reporter.report_assembly4(
            phase=Assembly4Phase.SOLVER_PROGRESS,
            constraints_resolved=i,
            constraints_total=10,
            iteration=i,
            residual=1.0 / (i + 1)
        )
    
    # Solver end
    reporter.report_assembly4(
        phase=Assembly4Phase.SOLVER_END,
        constraints_resolved=10,
        constraints_total=10
    )
    
    # LCS placement
    reporter.report_assembly4(
        phase=Assembly4Phase.LCS_PLACEMENT_START,
        placements_total=5
    )
    
    for i in range(1, 6):
        reporter.report_assembly4(
            phase=Assembly4Phase.LCS_PLACEMENT_PROGRESS,
            lcs_name=f"LCS_{i}",
            placements_done=i,
            placements_total=5
        )
    
    reporter.report_assembly4(
        phase=Assembly4Phase.LCS_PLACEMENT_END,
        placements_done=5,
        placements_total=5
    )


def _report_occt_progress(reporter: WorkerProgressReporter, job_id: int):
    """Report OCCT operation progress."""
    # Boolean operation
    reporter.report_occt(
        operation=OCCTOperation.BOOLEAN_FUSE,
        phase=Phase.START,
        shapes_total=3
    )
    
    for i in range(1, 4):
        reporter.report_occt(
            operation=OCCTOperation.BOOLEAN_FUSE,
            phase=Phase.PROGRESS,
            shapes_done=i,
            shapes_total=3,
            solids_in=i * 2,
            solids_out=1
        )
    
    reporter.report_occt(
        operation=OCCTOperation.BOOLEAN_FUSE,
        phase=Phase.END,
        shapes_done=3,
        shapes_total=3,
        solids_out=1
    )
    
    # Fillet operation
    reporter.report_occt(
        operation=OCCTOperation.FILLET,
        phase=Phase.START,
        edges_total=12,
        default_radius=2.0
    )
    
    for i in range(1, 13):
        reporter.report_occt(
            operation=OCCTOperation.FILLET,
            phase=Phase.PROGRESS,
            edges_done=i,
            edges_total=12,
            default_radius=2.0
        )
    
    reporter.report_occt(
        operation=OCCTOperation.FILLET,
        phase=Phase.END,
        edges_done=12,
        edges_total=12
    )


def _report_material_progress(reporter: WorkerProgressReporter, job_id: int):
    """Report Material Framework progress."""
    # Resolve material library
    reporter.report_progress(
        progress_pct=30,
        message="Malzeme kütüphanesi çözümleniyor / Resolving material library",
        current_step="Material resolution",
        library_name="StandardMaterials",
        material_key="Steel_1045"
    )
    
    # Apply materials
    total_objects = 5
    for i in range(1, total_objects + 1):
        reporter.report_progress(
            progress_pct=30 + (i * 10),
            message=f"Malzeme uygulanıyor {i}/{total_objects} / Applying material {i}/{total_objects}",
            current_step="Material application",
            objects_done=i,
            objects_total=total_objects,
            mat_uid="mat_steel_1045",
            appearance_bake=True
        )


def _report_export_progress(
    reporter: WorkerProgressReporter,
    job_id: int,
    output_formats: List[str]
):
    """Report export progress."""
    for format_str in output_formats:
        # Clean approach: exact match → partial match → default
        format_lower = format_str.lower()
        
        # Step 1: Try exact match
        format_enum = FORMAT_MAP.get(format_lower)
        
        # Step 2: If no exact match, try partial match
        if format_enum is None:
            for key, value in FORMAT_MAP.items():
                if key in format_lower or format_lower in key:
                    format_enum = value
                    break
        
        # Step 3: Default to FCSTD if no match found
        if format_enum is None:
            format_enum = ExportFormat.FCSTD
        
        reporter.report_export(
            format=format_enum,
            phase=Phase.START,
            bytes_total=1000000  # 1MB estimate
        )
        
        # Simulate export progress
        for i in range(1, 11):
            reporter.report_export(
                format=format_enum,
                phase=Phase.PROGRESS,
                bytes_written=i * 100000,
                bytes_total=1000000
            )
        
        reporter.report_export(
            format=format_enum,
            phase=Phase.END,
            bytes_written=1000000,
            bytes_total=1000000
        )


@shared_task(name="freecad.simple_with_progress", queue="model", bind=True)
@with_progress("Simple FreeCAD Operation", OperationGroup.GENERAL)
def simple_freecad_task(self, job_id: int, **kwargs):
    """
    Simple example using the @with_progress decorator.
    
    The decorator automatically creates an operation context.
    """
    # Get the injected operation context
    op = kwargs.get("_progress_op")
    
    if op:
        # Update progress through the operation context
        op.update(1, "Starting simple operation")
        
        # Do some work...
        import time
        time.sleep(1)
        
        op.update(2, "Processing...")
        time.sleep(1)
        
        op.update(3, "Finalizing...")
        time.sleep(1)
        
        # Add metadata
        op.add_metadata(
            result="success",
            items_processed=10
        )
    
    return {"status": "completed", "job_id": job_id}