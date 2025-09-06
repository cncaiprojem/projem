"""
Task 7.16: Worker Progress Reporter

This module provides progress reporting utilities for Celery workers:
- Integration with Celery task update_state()
- Progress publishing to Redis pub/sub
- FreeCAD 1.1.0-specific progress events
- Automatic context tracking
- Error handling and retry logic
"""

from __future__ import annotations

import asyncio
import functools
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional
from uuid import UUID, uuid4

from celery import Task, current_task
from celery.exceptions import Ignore

from ..core.logging import get_logger
from ..core.redis_pubsub import redis_progress_pubsub
from ..schemas.progress import (
    ProgressMessageV2,
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


class WorkerProgressReporter:
    """
    Progress reporter for Celery workers.
    
    Features:
    - Seamless integration with Celery tasks
    - Automatic progress tracking
    - FreeCAD-specific progress events
    - Context managers for operations
    """
    
    def __init__(self, task: Optional[Task] = None):
        """
        Initialize progress reporter.
        
        Args:
            task: Celery task instance (defaults to current_task)
        """
        self.task = task or current_task
        self._operation_stack = []
        self._event_counter = 0
        self._last_publish_time = 0
        self._throttle_interval = 0.5  # 500ms
    
    def _get_job_id(self) -> Optional[int]:
        """Get job ID from task context."""
        if not self.task:
            return None
        
        # Try to get from task kwargs
        if hasattr(self.task, "request") and self.task.request.kwargs:
            return self.task.request.kwargs.get("job_id")
        
        # Try to get from task args
        if hasattr(self.task, "request") and self.task.request.args:
            # Assume job_id is first argument
            return self.task.request.args[0] if self.task.request.args else None
        
        return None
    
    def _get_next_event_id(self) -> int:
        """Get next monotonic event ID."""
        self._event_counter += 1
        return self._event_counter
    
    def _should_throttle(self, milestone: bool = False) -> bool:
        """Check if update should be throttled."""
        if milestone:
            return False
        
        now = time.time()
        if now - self._last_publish_time < self._throttle_interval:
            return True
        
        self._last_publish_time = now
        return False
    
    def update_celery_state(
        self,
        state: str = "PROGRESS",
        meta: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Update Celery task state.
        
        Args:
            state: Task state
            meta: Task metadata
        """
        if self.task:
            self.task.update_state(state=state, meta=meta or {})
    
    def report_progress(
        self,
        progress_pct: int,
        message: str,
        current_step: Optional[str] = None,
        milestone: bool = False,
        **kwargs
    ) -> None:
        """
        Report generic progress update.
        
        Args:
            progress_pct: Progress percentage (0-100)
            message: Progress message
            current_step: Current step description
            milestone: Whether this is a milestone
            **kwargs: Additional progress fields
        """
        job_id = self._get_job_id()
        if not job_id:
            logger.warning("Cannot report progress: job_id not found")
            return
        
        # Check throttling
        if self._should_throttle(milestone):
            return
        
        # Create progress message
        progress = ProgressMessageV2(
            job_id=job_id,
            event_id=self._get_next_event_id(),
            event_type=EventType.PROGRESS_UPDATE,
            progress_pct=progress_pct,
            message=message,
            current_step=current_step,
            milestone=milestone,
            timestamp=datetime.now(timezone.utc),
            **kwargs
        )
        
        # Update Celery state
        self.update_celery_state(
            state="PROGRESS",
            meta=progress.model_dump()
        )
        
        # Publish to Redis (sync wrapper for async)
        try:
            # Try to get existing event loop first
            try:
                loop = asyncio.get_running_loop()
                # If we have a running loop, schedule the coroutine
                asyncio.ensure_future(
                    redis_progress_pubsub.publish_progress(job_id, progress)
                )
            except RuntimeError:
                # No running loop, use asyncio.run()
                asyncio.run(
                    redis_progress_pubsub.publish_progress(job_id, progress)
                )
        except Exception as e:
            logger.warning(f"Failed to publish progress to Redis: {e}")
    
    @contextmanager
    def operation(
        self,
        name: str,
        group: OperationGroup = OperationGroup.GENERAL,
        total_steps: Optional[int] = None
    ):
        """
        Context manager for tracking an operation.
        
        Args:
            name: Operation name
            group: Operation group
            total_steps: Total steps in operation
            
        Yields:
            Operation context with update methods
        """
        job_id = self._get_job_id()
        if not job_id:
            # Return dummy context if no job_id
            yield OperationContext(None, None, self)
            return
        
        operation_id = uuid4()
        context = OperationContext(job_id, operation_id, self)
        context.name = name
        context.group = group
        context.total_steps = total_steps
        context.current_step = 0
        context.start_time = time.time()
        
        # Push to stack
        self._operation_stack.append(context)
        
        # Report operation start
        self.report_operation_phase(
            operation_id=operation_id,
            operation_name=name,
            operation_group=group,
            phase=Phase.START,
            step_total=total_steps,
            milestone=True,
            message=f"Starting {name}"
        )
        
        try:
            yield context
            
            # Report operation end (success)
            elapsed_ms = int((time.time() - context.start_time) * 1000)
            self.report_operation_phase(
                operation_id=operation_id,
                operation_name=name,
                operation_group=group,
                phase=Phase.END,
                step_index=total_steps,
                step_total=total_steps,
                elapsed_ms=elapsed_ms,
                milestone=True,
                message=f"Completed {name}"
            )
        
        except Exception as e:
            # Report operation end (failure)
            elapsed_ms = int((time.time() - context.start_time) * 1000)
            self.report_operation_phase(
                operation_id=operation_id,
                operation_name=name,
                operation_group=group,
                phase=Phase.END,
                step_index=context.current_step,
                step_total=total_steps,
                elapsed_ms=elapsed_ms,
                milestone=True,
                message=f"Failed {name}: {str(e)}",
                error_code=type(e).__name__
            )
            raise
        
        finally:
            # Pop from stack
            self._operation_stack.pop()
    
    def report_operation_phase(
        self,
        operation_id: UUID,
        operation_name: str,
        operation_group: OperationGroup,
        phase: Phase,
        **kwargs
    ) -> None:
        """Report operation phase progress."""
        job_id = self._get_job_id()
        if not job_id:
            return
        
        progress = ProgressMessageV2(
            job_id=job_id,
            event_id=self._get_next_event_id(),
            event_type=EventType.PHASE,
            operation_id=operation_id,
            operation_name=operation_name,
            operation_group=operation_group,
            phase=phase,
            timestamp=datetime.now(timezone.utc),
            **kwargs
        )
        
        # Update Celery state
        self.update_celery_state(
            state="PROGRESS",
            meta=progress.model_dump()
        )
        
        # Publish to Redis
        try:
            # Try to get existing event loop first
            try:
                loop = asyncio.get_running_loop()
                # If we have a running loop, schedule the coroutine
                asyncio.ensure_future(
                    redis_progress_pubsub.publish_progress(job_id, progress, force=kwargs.get("milestone", False))
                )
            except RuntimeError:
                # No running loop, use asyncio.run()
                asyncio.run(
                    redis_progress_pubsub.publish_progress(job_id, progress, force=kwargs.get("milestone", False))
                )
        except Exception as e:
            logger.warning(f"Failed to publish operation phase: {e}")
    
    def report_freecad_document(
        self,
        phase: DocumentPhase,
        document_id: Optional[str] = None,
        document_label: Optional[str] = None,
        **kwargs
    ) -> None:
        """Report FreeCAD document progress."""
        job_id = self._get_job_id()
        if not job_id:
            return
        
        progress = ProgressMessageV2(
            job_id=job_id,
            event_id=self._get_next_event_id(),
            event_type=EventType.DOCUMENT,
            operation_group=OperationGroup.DOCUMENT,
            subphase=phase.value,
            document_id=document_id,
            document_label=document_label,
            milestone=phase in [DocumentPhase.DOCUMENT_OPEN, DocumentPhase.RECOMPUTE_END],
            freecad_version="1.1.0",
            timestamp=datetime.now(timezone.utc),
            **kwargs
        )
        
        self.update_celery_state("PROGRESS", progress.model_dump())
        self._publish_async(job_id, progress)
    
    def report_assembly4(
        self,
        phase: Assembly4Phase,
        constraints_resolved: Optional[int] = None,
        constraints_total: Optional[int] = None,
        **kwargs
    ) -> None:
        """Report Assembly4 progress."""
        job_id = self._get_job_id()
        if not job_id:
            return
        
        # Determine phase enum
        phase_enum = Phase.START if "start" in phase.value.lower() else \
                    Phase.END if "end" in phase.value.lower() else \
                    Phase.PROGRESS
        
        progress = ProgressMessageV2(
            job_id=job_id,
            event_id=self._get_next_event_id(),
            event_type=EventType.ASSEMBLY4,
            operation_group=OperationGroup.ASSEMBLY4,
            phase=phase_enum,
            subphase=phase.value,
            constraints_resolved=constraints_resolved,
            constraints_total=constraints_total,
            milestone=phase_enum in [Phase.START, Phase.END],
            freecad_version="1.1.0",
            workbench="Assembly4",
            timestamp=datetime.now(timezone.utc),
            **kwargs
        )
        
        # Calculate progress percentage
        if constraints_total and constraints_total > 0:
            progress.progress_pct = min(100, int((constraints_resolved or 0) / constraints_total * 100))
        
        self.update_celery_state("PROGRESS", progress.model_dump())
        self._publish_async(job_id, progress)
    
    def report_occt(
        self,
        operation: OCCTOperation,
        phase: Phase,
        shapes_done: Optional[int] = None,
        shapes_total: Optional[int] = None,
        **kwargs
    ) -> None:
        """Report OCCT operation progress."""
        job_id = self._get_job_id()
        if not job_id:
            return
        
        progress = ProgressMessageV2(
            job_id=job_id,
            event_id=self._get_next_event_id(),
            event_type=EventType.OCCT,
            operation_group=OperationGroup.OCCT,
            phase=phase,
            occt_op=operation,
            shapes_done=shapes_done,
            shapes_total=shapes_total,
            milestone=phase in [Phase.START, Phase.END],
            freecad_version="1.1.0",
            occt_version="7.8.1",
            timestamp=datetime.now(timezone.utc),
            **kwargs
        )
        
        # Calculate progress percentage
        if shapes_total and shapes_total > 0:
            progress.progress_pct = min(100, int((shapes_done or 0) / shapes_total * 100))
        
        self.update_celery_state("PROGRESS", progress.model_dump())
        self._publish_async(job_id, progress)
    
    def report_export(
        self,
        format: ExportFormat,
        phase: Phase,
        bytes_written: Optional[int] = None,
        bytes_total: Optional[int] = None,
        **kwargs
    ) -> None:
        """Report export progress."""
        job_id = self._get_job_id()
        if not job_id:
            return
        
        progress = ProgressMessageV2(
            job_id=job_id,
            event_id=self._get_next_event_id(),
            event_type=EventType.EXPORT,
            operation_group=OperationGroup.EXPORT,
            phase=phase,
            export_format=format,
            bytes_written=bytes_written,
            bytes_total=bytes_total,
            milestone=phase in [Phase.START, Phase.END],
            freecad_version="1.1.0",
            timestamp=datetime.now(timezone.utc),
            **kwargs
        )
        
        # Calculate progress percentage
        if bytes_total and bytes_total > 0:
            progress.progress_pct = min(100, int((bytes_written or 0) / bytes_total * 100))
        
        self.update_celery_state("PROGRESS", progress.model_dump())
        self._publish_async(job_id, progress)
    
    def _publish_async(self, job_id: int, progress: ProgressMessageV2) -> None:
        """Publish progress asynchronously."""
        try:
            # Try to get existing event loop first
            try:
                loop = asyncio.get_running_loop()
                # If we have a running loop, schedule the coroutine
                asyncio.ensure_future(
                    redis_progress_pubsub.publish_progress(
                        job_id,
                        progress,
                        force=progress.milestone
                    )
                )
            except RuntimeError:
                # No running loop, use asyncio.run()
                asyncio.run(
                    redis_progress_pubsub.publish_progress(
                        job_id,
                        progress,
                        force=progress.milestone
                    )
                )
        except Exception as e:
            logger.warning(f"Failed to publish progress: {e}")


class OperationContext:
    """Context for operation tracking."""
    
    def __init__(
        self,
        job_id: Optional[int],
        operation_id: Optional[UUID],
        reporter: WorkerProgressReporter
    ):
        self.job_id = job_id
        self.operation_id = operation_id
        self.reporter = reporter
        self.name = ""
        self.group = OperationGroup.GENERAL
        self.total_steps = None
        self.current_step = 0
        self.start_time = 0
    
    def update(self, step: int, message: Optional[str] = None) -> None:
        """Update operation progress."""
        if not self.job_id or not self.operation_id:
            return
        
        self.current_step = step
        elapsed_ms = int((time.time() - self.start_time) * 1000)
        
        # Calculate ETA
        eta_ms = None
        if self.total_steps and step > 0:
            avg_time_per_step = elapsed_ms / step
            remaining_steps = self.total_steps - step
            eta_ms = int(avg_time_per_step * remaining_steps)
        
        # Calculate progress percentage
        progress_pct = None
        if self.total_steps:
            progress_pct = min(100, int(step / self.total_steps * 100))
        
        self.reporter.report_operation_phase(
            operation_id=self.operation_id,
            operation_name=self.name,
            operation_group=self.group,
            phase=Phase.PROGRESS,
            step_index=step,
            step_total=self.total_steps,
            elapsed_ms=elapsed_ms,
            eta_ms=eta_ms,
            progress_pct=progress_pct,
            message=message
        )
    
    def add_metadata(self, **kwargs) -> None:
        """Add metadata to current operation."""
        if not self.job_id or not self.operation_id:
            return
        
        self.reporter.report_operation_phase(
            operation_id=self.operation_id,
            operation_name=self.name,
            operation_group=self.group,
            phase=Phase.PROGRESS,
            step_index=self.current_step,
            step_total=self.total_steps,
            operation_metadata=kwargs
        )


# Helper decorator for progress tracking
def with_progress(
    operation_name: str,
    operation_group: OperationGroup = OperationGroup.GENERAL
):
    """
    Decorator for automatic progress tracking.
    
    Args:
        operation_name: Name of the operation
        operation_group: Operation group category
        
    Returns:
        Decorated function with progress tracking
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            reporter = WorkerProgressReporter()
            
            with reporter.operation(operation_name, operation_group) as op:
                # Inject operation context as kwarg
                kwargs["_progress_op"] = op
                return func(*args, **kwargs)
        
        return wrapper
    return decorator