"""
Task 7.17: Model Generation Observability Service

This module provides centralized observability for model generation flows,
integrating metrics, tracing, and logging for FreeCAD 1.1.0/OCCT 7.8.x operations.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union
from datetime import datetime, timezone

from ..core.logging import get_logger
from ..core.constants import (
    DEFAULT_OCCT_MEMORY_THRESHOLD,
    OCCT_HIGH_MEMORY_THRESHOLD_BYTES,
    ASSEMBLY4_SOLVER_SLOW_THRESHOLD_SECONDS,
    ASSEMBLY4_EXCESSIVE_ITERATIONS_THRESHOLD,
    FREECAD_VERSION,
    OCCT_VERSION,
)
from ..core.telemetry import (
    create_span,
    trace_freecad_document,
    trace_occt_operation,
    trace_assembly4_solver,
    trace_material_operation,
    trace_topology_hash,
    trace_export_validation,
    trace_model_generation_flow
)
from ..core import metrics

logger = get_logger(__name__)


@dataclass
class Assembly4SolverContext:
    """
    Context for Assembly4 solver observation.
    
    GEMINI MEDIUM SEVERITY: Using dataclass for type safety
    instead of plain dict for solver context.
    """
    iterations: int = 0
    convergence_error: Optional[float] = None
    solver_status: str = "pending"
    constraints_satisfied: int = 0
    lcs_processed: int = 0


class ModelGenerationObservability:
    """
    Observability helper for model generation flows.
    
    Provides unified metrics and tracing for:
    - Model generation flows (AI prompt, parametric, upload, Assembly4)
    - FreeCAD document operations
    - OCCT boolean and feature operations
    - Assembly4 constraint solving
    - Material Framework operations
    - Topology hash computation
    - Export validation
    """
    
    # GEMINI MEDIUM SEVERITY: Version constants now imported from constants.py
    # OCCT memory threshold is now handled by safe_parse_int in constants.py
    # No additional error handling needed as safe_parse_int ensures valid positive values
    
    @staticmethod
    def _get_solids_range(solids_count: int) -> str:
        """Determine solids range for metric labels.
        
        Args:
            solids_count: Number of solids
            
        Returns:
            Range string for metric label
        """
        if solids_count <= 10:
            return "1-10"
        elif solids_count <= 50:
            return "11-50"
        elif solids_count <= 100:
            return "51-100"
        else:
            return "100+"
    
    @staticmethod
    def _get_lcs_range(lcs_count: int) -> str:
        """Determine LCS count range for metric labels.
        
        Args:
            lcs_count: Number of LCS elements
            
        Returns:
            Range string for metric label
        """
        if lcs_count <= 10:
            return "1-10"
        elif lcs_count <= 50:
            return "11-50"
        elif lcs_count <= 100:
            return "51-100"
        else:
            return "100+"
    
    @staticmethod
    def _get_file_size_range(file_size: int) -> str:
        """Determine file size range for metric labels.
        
        Args:
            file_size: File size in bytes
            
        Returns:
            Range string for metric label
        """
        if file_size < 1024 * 1024:  # < 1MB
            return "small"
        elif file_size < 10 * 1024 * 1024:  # < 10MB
            return "medium"
        elif file_size < 100 * 1024 * 1024:  # < 100MB
            return "large"
        else:
            return "xlarge"
    
    @contextmanager
    def observe_model_generation(
        self,
        flow_type: str,
        job_id: str,
        user_id: Optional[int] = None,
        **attributes
    ):
        """
        Observe a complete model generation flow.
        
        Args:
            flow_type: Type of flow (ai_prompt, parametric, upload, assembly4)
            job_id: Job identifier
            user_id: User identifier
            **attributes: Additional attributes
        """
        start_time = time.time()
        
        # Record flow start
        metrics.model_generation_started_total.labels(
            flow_type=flow_type,
            freecad_version=FREECAD_VERSION,
            occt_version=OCCT_VERSION
        ).inc()
        
        # Start root span for the flow
        with trace_model_generation_flow(
            flow_type=flow_type,
            job_id=job_id,
            freecad_version=FREECAD_VERSION,
            occt_version=OCCT_VERSION,
            user_id=str(user_id) if user_id else None,
            **attributes
        ) as span:
            try:
                yield span
                
                # Record successful completion
                duration = time.time() - start_time
                metrics.model_generation_completed_total.labels(
                    flow_type=flow_type,
                    status="success",
                    freecad_version=FREECAD_VERSION,
                    occt_version=OCCT_VERSION
                ).inc()
                
                logger.info(
                    "model_generation_completed",
                    flow_type=flow_type,
                    job_id=job_id,
                    duration_seconds=duration,
                    status="success"
                )
                
            except Exception as e:
                # Record failure
                duration = time.time() - start_time
                metrics.model_generation_completed_total.labels(
                    flow_type=flow_type,
                    status="error",
                    freecad_version=FREECAD_VERSION,
                    occt_version=OCCT_VERSION
                ).inc()
                
                logger.error(
                    "model_generation_failed",
                    flow_type=flow_type,
                    job_id=job_id,
                    duration_seconds=duration,
                    error=str(e),
                    exc_info=True
                )
                raise
    
    @contextmanager
    def observe_stage(
        self,
        flow_type: str,
        stage: str,
        **attributes
    ):
        """
        Observe a specific stage within a model generation flow.
        
        Args:
            flow_type: Type of flow
            stage: Stage name (validation, normalization, execution, export)
            **attributes: Additional attributes
        """
        start_time = time.time()
        
        with create_span(
            name=f"model_generation.{flow_type}.{stage}",
            operation_type="model_generation_stage",
            attributes={
                "stage": stage,
                "flow_type": flow_type,
                **attributes
            }
        ) as span:
            try:
                yield span
                
            except Exception:
                raise
            finally:
                # Record duration metrics in finally block (GEMINI HIGH SEVERITY fix)
                duration = time.time() - start_time
                metrics.model_generation_stage_duration_seconds.labels(
                    flow_type=flow_type,
                    stage=stage,
                    freecad_version=FREECAD_VERSION,
                    occt_version=OCCT_VERSION  # Added for consistency
                ).observe(duration)
    
    def record_ai_provider_latency(
        self,
        provider: str,
        model: str,
        operation: str,
        latency_seconds: float
    ):
        """
        Record AI provider response latency.
        
        Args:
            provider: AI provider name
            model: Model name
            operation: Operation type (prompt_to_script, parameter_generation)
            latency_seconds: Response latency in seconds
        """
        metrics.ai_provider_latency_seconds.labels(
            provider=provider,
            model=model,
            operation=operation
        ).observe(latency_seconds)
        
        logger.info(
            "ai_provider_latency",
            provider=provider,
            model=model,
            operation=operation,
            latency_seconds=latency_seconds
        )
    
    @contextmanager
    def observe_document_operation(
        self,
        document_id: str,
        operation: str,
        workbench: Optional[str] = None,
        source: Optional[str] = None,
        **attributes
    ):
        """
        Observe FreeCAD document operations.
        
        Args:
            document_id: Document identifier
            operation: Operation type (load, recompute, save)
            workbench: FreeCAD workbench
            source: Document source
            **attributes: Additional attributes
        """
        start_time = time.time()
        
        with trace_freecad_document(
            document_id=document_id,
            operation=operation,
            workbench=workbench,
            freecad_version=FREECAD_VERSION,
            occt_version=OCCT_VERSION,
            **attributes
        ) as span:
            try:
                yield span
                
                
            except Exception:
                raise
            finally:
                # Record duration in finally block (GEMINI HIGH SEVERITY fix)
                duration = time.time() - start_time
                if operation == "load":
                    metrics.freecad_document_load_seconds.labels(
                        source=source or "unknown",
                        workbench=workbench or "unknown",
                        freecad_version=FREECAD_VERSION,
                        occt_version=OCCT_VERSION
                    ).observe(duration)
                
                elif operation == "recompute":
                    doc_complexity = attributes.get("doc_complexity", "medium")
                    metrics.freecad_recompute_duration_seconds.labels(
                        workbench=workbench or "unknown",
                        doc_complexity=doc_complexity
                    ).observe(duration)
    
    def record_object_creation(
        self,
        object_class: str,
        workbench: Optional[str] = None,
        count: int = 1
    ):
        """
        Record FreeCAD object creation.
        
        Args:
            object_class: Object class name
            workbench: Workbench used
            count: Number of objects created
        """
        # Use inc(count) instead of loop (GEMINI MEDIUM SEVERITY fix)
        metrics.freecad_object_created_total.labels(
            **{"class": object_class},  # Use dict unpacking to avoid keyword conflict
            workbench=workbench or "unknown"
        ).inc(count)
    
    @contextmanager
    def observe_occt_boolean(
        self,
        operation: str,
        solids_count: int,
        **attributes
    ):
        """
        Observe OCCT boolean operations.
        
        Args:
            operation: Operation type (union, cut, common)
            solids_count: Number of solids involved
            **attributes: Additional attributes
        """
        start_time = time.time()
        
        # Determine solids range using utility method (PR #503 feedback)
        solids_range = self._get_solids_range(solids_count)
        
        with trace_occt_operation(
            operation_type=f"boolean_{operation}",
            solids_count=solids_count,
            occt_version=OCCT_VERSION,  # Pass version as parameter
            **attributes
        ) as span:
            try:
                yield span
                
                
            except Exception:
                raise
            finally:
                # Record duration in finally block (GEMINI HIGH SEVERITY fix)
                duration = time.time() - start_time
                metrics.occt_boolean_duration_seconds.labels(
                    operation=operation,
                    solids_range=solids_range
                ).observe(duration)
    
    @contextmanager
    def observe_occt_feature(
        self,
        feature: str,
        edges_count: Optional[int] = None,
        faces_count: Optional[int] = None,
        **attributes
    ):
        """
        Observe OCCT feature operations.
        
        Args:
            feature: Feature type (fillet, chamfer)
            edges_count: Number of edges
            faces_count: Number of faces
            **attributes: Additional attributes
        """
        start_time = time.time()
        
        with trace_occt_operation(
            operation_type=feature,
            edges_count=edges_count,
            faces_count=faces_count,
            occt_version=OCCT_VERSION,  # Pass version as parameter
            **attributes
        ) as span:
            try:
                yield span
                
                
            except Exception:
                raise
            finally:
                # Record duration in finally block (GEMINI HIGH SEVERITY fix)
                duration = time.time() - start_time
                metrics.occt_feature_duration_seconds.labels(
                    feature=feature
                ).observe(duration)
    
    def record_occt_memory(
        self,
        operation: str,
        memory_bytes: int
    ):
        """
        Record OCCT operation memory usage.
        
        Args:
            operation: Operation type
            memory_bytes: Memory used in bytes
        """
        metrics.occt_operation_memory_bytes.labels(
            operation=operation
        ).set(memory_bytes)
        
        # Alert if memory usage is high (directly use constant as it's validated by safe_parse_int)
        if memory_bytes > OCCT_HIGH_MEMORY_THRESHOLD_BYTES:
            logger.warning(
                "occt_high_memory_usage",
                extra={
                    "operation": operation,
                    "memory_bytes": memory_bytes,
                    "memory_gb": memory_bytes / (1024**3)
                }
            )
    
    @contextmanager
    def observe_assembly4_solver(
        self,
        solver_type: str,
        constraints_count: int,
        lcs_count: Optional[int] = None,
        **attributes
    ):
        """
        Observe Assembly4 constraint solving.
        
        Args:
            solver_type: Solver type
            constraints_count: Number of constraints
            lcs_count: Number of LCS elements
            **attributes: Additional attributes
        """
        start_time = time.time()
        iterations = 0
        
        with trace_assembly4_solver(
            solver_type=solver_type,
            constraints_count=constraints_count,
            lcs_count=lcs_count,
            **attributes
        ) as span:
            try:
                # GEMINI MEDIUM SEVERITY: Use dataclass instead of plain dict
                context = Assembly4SolverContext()
                yield context
                
            except Exception:
                raise
            finally:
                # Record metrics in finally block to ensure they're always recorded (GEMINI HIGH SEVERITY fix)
                iterations = context.iterations
                duration = time.time() - start_time
                
                metrics.a4_constraint_solve_duration_seconds.labels(
                    solver=solver_type
                ).observe(duration)
                
                if iterations > 0:
                    metrics.a4_solver_iterations_total.labels(
                        solver=solver_type
                    ).observe(iterations)
                
                # Alert if solver is slow or requires many iterations (use imported constants)
                if duration > ASSEMBLY4_SOLVER_SLOW_THRESHOLD_SECONDS:
                    logger.warning(
                        "assembly4_solver_slow",
                        extra={
                            "solver": solver_type,
                            "duration_seconds": duration,
                            "constraints_count": constraints_count
                        }
                    )
                
                if iterations > ASSEMBLY4_EXCESSIVE_ITERATIONS_THRESHOLD:
                    logger.warning(
                        "assembly4_excessive_iterations",
                        extra={
                            "solver": solver_type,
                            "iterations": iterations,
                            "constraints_count": constraints_count
                        }
                    )
    
    def record_lcs_resolution(
        self,
        lcs_count: int,
        duration_seconds: float
    ):
        """
        Record LCS resolution time.
        
        Args:
            lcs_count: Number of LCS elements
            duration_seconds: Resolution duration
        """
        # Determine LCS count range using utility method (PR #503 feedback)
        lcs_range = self._get_lcs_range(lcs_count)
        
        metrics.a4_lcs_resolution_duration_seconds.labels(
            lcs_count_range=lcs_range
        ).observe(duration_seconds)
    
    def record_material_library_access(
        self,
        library: str,
        result: str  # hit, miss, error
    ):
        """
        Record material library access.
        
        Args:
            library: Library name
            result: Access result (hit, miss, error)
        """
        metrics.material_library_access_total.labels(
            library=library,
            result=result
        ).inc()
        
        # Alert on high error rate
        if result == "error":
            logger.warning(
                "material_library_error",
                extra={"library": library}
            )
    
    @contextmanager
    def observe_material_property_application(
        self,
        property_type: str,
        material_count: int,
        **attributes
    ):
        """
        Observe material property application.
        
        Args:
            property_type: Property type being applied
            material_count: Number of materials
            **attributes: Additional attributes
        """
        start_time = time.time()
        
        with trace_material_operation(
            operation="apply_properties",
            library_name=attributes.get("library", "unknown"),
            material_count=material_count,
            property_type=property_type,
            **attributes
        ) as span:
            try:
                yield span
                
                
            except Exception:
                raise
            finally:
                # Record duration in finally block (GEMINI HIGH SEVERITY fix)
                duration = time.time() - start_time
                metrics.material_property_apply_duration_seconds.labels(
                    property=property_type
                ).observe(duration)
    
    @contextmanager
    def observe_topology_hash(
        self,
        scope: str,
        entity_count: int,
        **attributes
    ):
        """
        Observe topology hash computation.
        
        Args:
            scope: Scope (part, assembly)
            entity_count: Number of entities
            **attributes: Additional attributes
        """
        start_time = time.time()
        
        with trace_topology_hash(
            scope=scope,
            entity_count=entity_count,
            **attributes
        ) as span:
            try:
                yield span
                
                
            except Exception:
                raise
            finally:
                # Record duration in finally block (GEMINI HIGH SEVERITY fix)
                duration = time.time() - start_time
                metrics.topology_hash_compute_duration_seconds.labels(
                    scope=scope
                ).observe(duration)
    
    def record_export_validation(
        self,
        format: str,
        result: str,  # pass, fail
        file_size: Optional[int] = None
    ):
        """
        Record deterministic export validation result.
        
        Args:
            format: Export format (STEP, STL, GLB)
            result: Validation result (pass, fail)
            file_size: File size in bytes
        """
        metrics.deterministic_export_validation_total.labels(
            format=format,
            result=result
        ).inc()
        
        # Alert on validation failure
        if result == "fail":
            logger.warning(
                "export_validation_failed",
                extra={
                    "format": format,
                    "file_size": file_size
                }
            )
    
    @contextmanager
    def observe_export(
        self,
        format: str,
        file_size: int,
        **attributes
    ):
        """
        Observe file export operation.
        
        Args:
            format: Export format
            file_size: File size in bytes
            **attributes: Additional attributes
        """
        start_time = time.time()
        
        # Determine file size range using utility method (PR #503 feedback)
        size_range = self._get_file_size_range(file_size)
        
        with trace_export_validation(
            format=format,
            file_size=file_size,
            **attributes
        ) as span:
            try:
                yield span
                
                
            except Exception:
                raise
            finally:
                # Record duration in finally block (GEMINI HIGH SEVERITY fix)
                duration = time.time() - start_time
                metrics.export_duration_seconds.labels(
                    format=format,
                    file_size_range=size_range,
                    freecad_version=FREECAD_VERSION
                ).observe(duration)
    
    def record_workbench_invocation(
        self,
        workbench: str,
        compatible: bool = True
    ):
        """
        Record workbench invocation and compatibility.
        
        Args:
            workbench: Workbench name
            compatible: Whether workbench is compatible
        """
        metrics.freecad_workbench_invocations_total.labels(
            workbench=workbench
        ).inc()
        
        metrics.freecad_workbench_compatibility_total.labels(
            workbench=workbench,
            compatible=str(compatible).lower()
        ).inc()
        
        if not compatible:
            logger.warning(
                "workbench_compatibility_issue",
                extra={
                    "workbench": workbench,
                    "freecad_version": FREECAD_VERSION
                }
            )
    
    def record_worker_operation(
        self,
        operation: str,
        workbench: Optional[str] = None,
        duration_seconds: float = None
    ):
        """
        Record FreeCAD worker operation.
        
        Args:
            operation: Operation type
            workbench: Workbench used
            duration_seconds: Operation duration
        """
        if duration_seconds is not None:
            metrics.freecad_worker_duration_seconds.labels(
                operation=operation,
                workbench=workbench or "unknown",
                freecad_version=FREECAD_VERSION
            ).observe(duration_seconds)


# Global instance
model_observability = ModelGenerationObservability()