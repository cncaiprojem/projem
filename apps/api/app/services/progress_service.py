"""
Task 7.16: Progress Management Service

This module provides centralized progress management for:
- Publishing progress from workers
- Managing progress subscriptions
- Progress event caching and retrieval
- Throttling and deduplication
- Integration with existing worker progress service
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from ..core.logging import get_logger
from ..core.redis_pubsub import redis_progress_pubsub, RedisProgressPubSub
from ..core.telemetry import create_span
from ..core import metrics
from ..models.job import Job
from ..models.enums import JobStatus
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
from .worker_progress_service import worker_progress_service

logger = get_logger(__name__)


class ProgressService:
    """
    Centralized service for managing job progress updates.
    
    Features:
    - Unified progress publishing API
    - FreeCAD 1.1.0-specific progress events
    - Integration with WebSocket and SSE endpoints
    - Progress caching for resumption
    - Metrics and telemetry
    """
    
    def __init__(self):
        """Initialize progress service."""
        self.pubsub = redis_progress_pubsub
        self._operation_contexts: Dict[int, Dict[str, Any]] = {}
    
    async def publish_document_progress(
        self,
        job_id: int,
        phase: DocumentPhase,
        document_id: Optional[str] = None,
        document_label: Optional[str] = None,
        message: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        Publish FreeCAD document lifecycle progress.
        
        Args:
            job_id: Job ID
            phase: Document phase
            document_id: Document identifier
            document_label: Document label
            message: Progress message
            **kwargs: Additional fields
            
        Returns:
            True if published successfully
        """
        with create_span("progress.document") as span:
            span.set_attribute("job_id", job_id)
            span.set_attribute("phase", phase.value)
            
            progress = ProgressMessageV2(
                job_id=job_id,
                event_type=EventType.DOCUMENT,
                operation_group=OperationGroup.DOCUMENT,
                subphase=phase.value,
                document_id=document_id,
                document_label=document_label,
                message=message or f"Document {phase.value}",
                milestone=phase in [DocumentPhase.DOCUMENT_OPEN, DocumentPhase.RECOMPUTE_END],
                freecad_version="1.1.0",
                **kwargs
            )
            
            # Cache and publish
            await self.pubsub.cache_progress_event(job_id, progress)
            success = await self.pubsub.publish_progress(job_id, progress)
            
            # Update metrics
            metrics.job_progress_updates.labels(
                job_type="document",
                status=phase.value
            ).inc()
            
            return success
    
    async def publish_assembly4_progress(
        self,
        job_id: int,
        phase: Assembly4Phase,
        constraints_resolved: Optional[int] = None,
        constraints_total: Optional[int] = None,
        lcs_name: Optional[str] = None,
        iteration: Optional[int] = None,
        residual: Optional[float] = None,
        **kwargs
    ) -> bool:
        """
        Publish Assembly4 solving progress.
        
        Args:
            job_id: Job ID
            phase: Assembly4 phase
            constraints_resolved: Constraints resolved
            constraints_total: Total constraints
            lcs_name: LCS being placed
            iteration: Solver iteration
            residual: Solver residual
            **kwargs: Additional fields
            
        Returns:
            True if published successfully
        """
        with create_span("progress.assembly4") as span:
            span.set_attribute("job_id", job_id)
            span.set_attribute("phase", phase.value)
            
            # Determine phase enum
            phase_enum = Phase.START if "start" in phase.value.lower() else \
                        Phase.END if "end" in phase.value.lower() else \
                        Phase.PROGRESS
            
            progress = ProgressMessageV2(
                job_id=job_id,
                event_type=EventType.ASSEMBLY4,
                operation_group=OperationGroup.ASSEMBLY4,
                phase=phase_enum,
                subphase=phase.value,
                constraints_resolved=constraints_resolved,
                constraints_total=constraints_total,
                lcs_name=lcs_name,
                iteration=iteration,
                residual=residual,
                milestone=phase_enum in [Phase.START, Phase.END],
                freecad_version="1.1.0",
                workbench="Assembly4",
                **kwargs
            )
            
            # Calculate progress percentage
            if constraints_total and constraints_total > 0:
                progress.progress_pct = min(100, int((constraints_resolved or 0) / constraints_total * 100))
            
            # Cache and publish
            await self.pubsub.cache_progress_event(job_id, progress)
            success = await self.pubsub.publish_progress(job_id, progress)
            
            # Update metrics
            metrics.job_progress_updates.labels(
                job_type="assembly4",
                status=phase.value
            ).inc()
            
            return success
    
    async def publish_material_progress(
        self,
        job_id: int,
        phase: MaterialPhase,
        library_name: Optional[str] = None,
        material_key: Optional[str] = None,
        mat_uid: Optional[str] = None,
        objects_done: Optional[int] = None,
        objects_total: Optional[int] = None,
        appearance_bake: Optional[bool] = None,
        **kwargs
    ) -> bool:
        """
        Publish Material Framework progress.
        
        Args:
            job_id: Job ID
            phase: Material phase
            library_name: Material library
            material_key: Material key
            mat_uid: Material UID
            objects_done: Objects processed
            objects_total: Total objects
            appearance_bake: Baking appearance
            **kwargs: Additional fields
            
        Returns:
            True if published successfully
        """
        with create_span("progress.material") as span:
            span.set_attribute("job_id", job_id)
            span.set_attribute("phase", phase.value)
            
            # Determine phase enum
            phase_enum = Phase.START if "start" in phase.value.lower() else \
                        Phase.END if "end" in phase.value.lower() else \
                        Phase.PROGRESS
            
            progress = ProgressMessageV2(
                job_id=job_id,
                event_type=EventType.MATERIAL,
                operation_group=OperationGroup.MATERIAL,
                phase=phase_enum,
                subphase=phase.value,
                library_name=library_name,
                material_key=material_key,
                mat_uid=mat_uid,
                objects_done=objects_done,
                objects_total=objects_total,
                appearance_bake=appearance_bake,
                milestone=phase_enum in [Phase.START, Phase.END],
                freecad_version="1.1.0",
                workbench="Material",
                **kwargs
            )
            
            # Calculate progress percentage
            if objects_total and objects_total > 0:
                progress.progress_pct = min(100, int((objects_done or 0) / objects_total * 100))
            
            # Cache and publish
            await self.pubsub.cache_progress_event(job_id, progress)
            success = await self.pubsub.publish_progress(job_id, progress)
            
            # Update metrics
            metrics.job_progress_updates.labels(
                job_type="material",
                status=phase.value
            ).inc()
            
            return success
    
    async def publish_occt_progress(
        self,
        job_id: int,
        operation: OCCTOperation,
        phase: Phase,
        shapes_done: Optional[int] = None,
        shapes_total: Optional[int] = None,
        edges_done: Optional[int] = None,
        edges_total: Optional[int] = None,
        default_radius: Optional[float] = None,
        **kwargs
    ) -> bool:
        """
        Publish OCCT operation progress.
        
        Args:
            job_id: Job ID
            operation: OCCT operation type
            phase: Operation phase
            shapes_done: Shapes processed
            shapes_total: Total shapes
            edges_done: Edges processed
            edges_total: Total edges
            default_radius: Default radius
            **kwargs: Additional fields
            
        Returns:
            True if published successfully
        """
        with create_span("progress.occt") as span:
            span.set_attribute("job_id", job_id)
            span.set_attribute("operation", operation.value)
            span.set_attribute("phase", phase.value)
            
            progress = ProgressMessageV2(
                job_id=job_id,
                event_type=EventType.OCCT,
                operation_group=OperationGroup.OCCT,
                phase=phase,
                occt_op=operation,
                shapes_done=shapes_done,
                shapes_total=shapes_total,
                edges_done=edges_done,
                edges_total=edges_total,
                default_radius=default_radius,
                milestone=phase in [Phase.START, Phase.END],
                freecad_version="1.1.0",
                occt_version="7.8.1",
                **kwargs
            )
            
            # Calculate progress percentage
            if shapes_total and shapes_total > 0:
                progress.progress_pct = min(100, int((shapes_done or 0) / shapes_total * 100))
            elif edges_total and edges_total > 0:
                progress.progress_pct = min(100, int((edges_done or 0) / edges_total * 100))
            
            # Cache and publish
            await self.pubsub.cache_progress_event(job_id, progress)
            success = await self.pubsub.publish_progress(job_id, progress)
            
            # Update metrics
            metrics.job_progress_updates.labels(
                job_type="occt",
                status=operation.value
            ).inc()
            
            return success
    
    async def publish_topology_progress(
        self,
        job_id: int,
        phase: TopologyPhase,
        faces_done: Optional[int] = None,
        faces_total: Optional[int] = None,
        edges_done: Optional[int] = None,
        edges_total: Optional[int] = None,
        vertices_done: Optional[int] = None,
        vertices_total: Optional[int] = None,
        computed_hash: Optional[str] = None,
        expected_hash: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        Publish topology hash computation progress.
        
        Args:
            job_id: Job ID
            phase: Topology phase
            faces_done: Faces hashed
            faces_total: Total faces
            edges_done: Edges hashed
            edges_total: Total edges
            vertices_done: Vertices hashed
            vertices_total: Total vertices
            computed_hash: Computed hash
            expected_hash: Expected hash
            **kwargs: Additional fields
            
        Returns:
            True if published successfully
        """
        with create_span("progress.topology") as span:
            span.set_attribute("job_id", job_id)
            span.set_attribute("phase", phase.value)
            
            # Determine phase enum
            phase_enum = Phase.START if "start" in phase.value.lower() else \
                        Phase.END if "end" in phase.value.lower() else \
                        Phase.PROGRESS
            
            progress = ProgressMessageV2(
                job_id=job_id,
                event_type=EventType.TOPOLOGY_HASH,
                operation_group=OperationGroup.TOPOLOGY,
                phase=phase_enum,
                subphase=phase.value,
                faces_done=faces_done,
                faces_total=faces_total,
                edges_done=edges_done,
                edges_total=edges_total,
                vertices_done=vertices_done,
                vertices_total=vertices_total,
                computed_hash=computed_hash,
                expected_hash=expected_hash,
                hash_match=computed_hash == expected_hash if computed_hash and expected_hash else None,
                milestone=phase in [TopologyPhase.EXPORT_VALIDATION] or phase_enum in [Phase.START, Phase.END],
                freecad_version="1.1.0",
                **kwargs
            )
            
            # Calculate progress percentage
            total_items = (faces_total or 0) + (edges_total or 0) + (vertices_total or 0)
            done_items = (faces_done or 0) + (edges_done or 0) + (vertices_done or 0)
            if total_items > 0:
                progress.progress_pct = min(100, int(done_items / total_items * 100))
            
            # Cache and publish
            await self.pubsub.cache_progress_event(job_id, progress)
            success = await self.pubsub.publish_progress(job_id, progress)
            
            # Update metrics
            metrics.job_progress_updates.labels(
                job_type="topology",
                status=phase.value
            ).inc()
            
            return success
    
    async def publish_export_progress(
        self,
        job_id: int,
        format: ExportFormat,
        phase: Phase,
        bytes_written: Optional[int] = None,
        bytes_total: Optional[int] = None,
        file_path: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        Publish export progress.
        
        Args:
            job_id: Job ID
            format: Export format
            phase: Export phase
            bytes_written: Bytes written
            bytes_total: Total bytes
            file_path: Export file path
            **kwargs: Additional fields
            
        Returns:
            True if published successfully
        """
        with create_span("progress.export") as span:
            span.set_attribute("job_id", job_id)
            span.set_attribute("format", format.value)
            span.set_attribute("phase", phase.value)
            
            progress = ProgressMessageV2(
                job_id=job_id,
                event_type=EventType.EXPORT,
                operation_group=OperationGroup.EXPORT,
                phase=phase,
                export_format=format,
                bytes_written=bytes_written,
                bytes_total=bytes_total,
                message=f"Exporting to {format.value}",
                milestone=phase in [Phase.START, Phase.END],
                freecad_version="1.1.0",
                operation_metadata={"file_path": file_path} if file_path else None,
                **kwargs
            )
            
            # Calculate progress percentage
            if bytes_total and bytes_total > 0:
                progress.progress_pct = min(100, int((bytes_written or 0) / bytes_total * 100))
            
            # Cache and publish
            await self.pubsub.cache_progress_event(job_id, progress)
            success = await self.pubsub.publish_progress(job_id, progress)
            
            # Update metrics
            metrics.job_progress_updates.labels(
                job_type="export",
                status=format.value
            ).inc()
            
            return success
    
    async def publish_generic_progress(
        self,
        job_id: int,
        progress_pct: int,
        message: str,
        current_step: Optional[str] = None,
        milestone: bool = False,
        **kwargs
    ) -> bool:
        """
        Publish generic progress update (backward compatibility).
        
        Args:
            job_id: Job ID
            progress_pct: Progress percentage
            message: Progress message
            current_step: Current step description
            milestone: Whether this is a milestone
            **kwargs: Additional fields
            
        Returns:
            True if published successfully
        """
        with create_span("progress.generic") as span:
            span.set_attribute("job_id", job_id)
            span.set_attribute("progress_pct", progress_pct)
            
            progress = ProgressMessageV2(
                job_id=job_id,
                event_type=EventType.PROGRESS_UPDATE,
                progress_pct=progress_pct,
                message=message,
                current_step=current_step,
                milestone=milestone,
                **kwargs
            )
            
            # Cache and publish
            await self.pubsub.cache_progress_event(job_id, progress)
            success = await self.pubsub.publish_progress(job_id, progress)
            
            # Update metrics
            metrics.job_progress_updates.labels(
                job_type="generic",
                status="progress"
            ).inc()
            
            return success
    
    async def start_operation(
        self,
        job_id: int,
        operation_name: str,
        operation_group: OperationGroup,
        total_steps: Optional[int] = None
    ) -> UUID:
        """
        Start a new operation and return its ID.
        
        Args:
            job_id: Job ID
            operation_name: Operation name
            operation_group: Operation group
            total_steps: Total steps in operation
            
        Returns:
            Operation ID
        """
        operation_id = uuid4()
        
        # Store operation context
        if job_id not in self._operation_contexts:
            self._operation_contexts[job_id] = {}
        
        self._operation_contexts[job_id][str(operation_id)] = {
            "name": operation_name,
            "group": operation_group,
            "total_steps": total_steps,
            "start_time": time.time(),
            "current_step": 0
        }
        
        # Publish start event
        await self.pubsub.publish_progress(
            job_id,
            ProgressMessageV2(
                job_id=job_id,
                event_type=EventType.PHASE,
                phase=Phase.START,
                operation_id=operation_id,
                operation_name=operation_name,
                operation_group=operation_group,
                step_total=total_steps,
                milestone=True,
                message=f"Starting {operation_name}"
            )
        )
        
        return operation_id
    
    async def update_operation(
        self,
        job_id: int,
        operation_id: UUID,
        current_step: int,
        message: Optional[str] = None
    ) -> bool:
        """
        Update operation progress.
        
        Args:
            job_id: Job ID
            operation_id: Operation ID
            current_step: Current step
            message: Progress message
            
        Returns:
            True if updated successfully
        """
        # Get operation context
        context = self._operation_contexts.get(job_id, {}).get(str(operation_id))
        if not context:
            logger.warning(f"Operation {operation_id} not found for job {job_id}")
            return False
        
        context["current_step"] = current_step
        elapsed_ms = int((time.time() - context["start_time"]) * 1000)
        
        # Calculate ETA
        eta_ms = None
        if context["total_steps"] and current_step > 0:
            avg_time_per_step = elapsed_ms / current_step
            remaining_steps = context["total_steps"] - current_step
            eta_ms = int(avg_time_per_step * remaining_steps)
        
        # Publish progress
        return await self.pubsub.publish_progress(
            job_id,
            ProgressMessageV2(
                job_id=job_id,
                event_type=EventType.PHASE,
                phase=Phase.PROGRESS,
                operation_id=operation_id,
                operation_name=context["name"],
                operation_group=context["group"],
                step_index=current_step,
                step_total=context["total_steps"],
                elapsed_ms=elapsed_ms,
                eta_ms=eta_ms,
                message=message
            )
        )
    
    async def end_operation(
        self,
        job_id: int,
        operation_id: UUID,
        success: bool = True,
        message: Optional[str] = None
    ) -> bool:
        """
        End an operation.
        
        Args:
            job_id: Job ID
            operation_id: Operation ID
            success: Whether operation succeeded
            message: Completion message
            
        Returns:
            True if ended successfully
        """
        # Get operation context
        context = self._operation_contexts.get(job_id, {}).get(str(operation_id))
        if not context:
            logger.warning(f"Operation {operation_id} not found for job {job_id}")
            return False
        
        elapsed_ms = int((time.time() - context["start_time"]) * 1000)
        
        # Publish end event
        result = await self.pubsub.publish_progress(
            job_id,
            ProgressMessageV2(
                job_id=job_id,
                event_type=EventType.PHASE,
                phase=Phase.END,
                operation_id=operation_id,
                operation_name=context["name"],
                operation_group=context["group"],
                step_index=context["total_steps"] if success else context["current_step"],
                step_total=context["total_steps"],
                elapsed_ms=elapsed_ms,
                milestone=True,
                message=message or f"Completed {context['name']}" if success else f"Failed {context['name']}"
            )
        )
        
        # Clean up context
        del self._operation_contexts[job_id][str(operation_id)]
        if not self._operation_contexts[job_id]:
            del self._operation_contexts[job_id]
        
        return result


# Global instance
progress_service = ProgressService()