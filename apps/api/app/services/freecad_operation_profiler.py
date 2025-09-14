"""
FreeCAD Operation Profiler for Task 7.25

This module provides specialized profiling for FreeCAD document operations with:
- Operation-level performance tracking
- Bottleneck identification in FreeCAD workflows
- Document lifecycle profiling
- Geometry operation analysis
- CAM path generation profiling
- Integration with FreeCADDocumentManager (Task 7.19)
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import uuid

from ..core.logging import get_logger
from ..core.telemetry import create_span
from ..core import metrics
from ..middleware.correlation_middleware import get_correlation_id
from .performance_profiler import PerformanceProfiler, performance_profiler
from .freecad_document_manager import FreeCADDocumentManager, document_manager

logger = get_logger(__name__)


class FreeCADOperationType(str, Enum):
    """FreeCAD operation types for profiling."""
    DOCUMENT_CREATE = "document_create"
    DOCUMENT_OPEN = "document_open"
    DOCUMENT_SAVE = "document_save"
    DOCUMENT_CLOSE = "document_close"
    GEOMETRY_CREATE = "geometry_create"
    GEOMETRY_MODIFY = "geometry_modify"
    GEOMETRY_BOOLEAN = "geometry_boolean"
    MESH_GENERATION = "mesh_generation"
    CAM_PATH_GENERATION = "cam_path_generation"
    ASSEMBLY_OPERATION = "assembly_operation"
    RENDERING = "rendering"
    IMPORT_OPERATION = "import_operation"
    EXPORT_OPERATION = "export_operation"
    ANALYSIS_OPERATION = "analysis_operation"
    CONSTRAINT_SOLVING = "constraint_solving"


@dataclass
class OperationMetrics:
    """Metrics for a single FreeCAD operation."""
    operation_id: str
    operation_type: FreeCADOperationType
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_seconds: float = 0.0
    cpu_time_seconds: float = 0.0
    memory_used_mb: float = 0.0
    memory_peak_mb: float = 0.0
    object_count: int = 0
    vertex_count: int = 0
    face_count: int = 0
    success: bool = True
    error_message: Optional[str] = None
    sub_operations: List[OperationMetrics] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type.value,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "cpu_time_seconds": self.cpu_time_seconds,
            "memory_used_mb": self.memory_used_mb,
            "memory_peak_mb": self.memory_peak_mb,
            "object_count": self.object_count,
            "vertex_count": self.vertex_count,
            "face_count": self.face_count,
            "success": self.success,
            "error_message": self.error_message,
            "sub_operations": [op.to_dict() for op in self.sub_operations],
            "metadata": self.metadata
        }


@dataclass
class WorkflowProfile:
    """Profile for a complete FreeCAD workflow."""
    workflow_id: str
    workflow_name: str
    start_time: datetime
    end_time: Optional[datetime] = None
    total_duration_seconds: float = 0.0
    operations: List[OperationMetrics] = field(default_factory=list)
    bottlenecks: List[Dict[str, Any]] = field(default_factory=list)
    optimization_suggestions: List[Dict[str, Any]] = field(default_factory=list)
    resource_usage: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "total_duration_seconds": self.total_duration_seconds,
            "operations": [op.to_dict() for op in self.operations],
            "bottlenecks": self.bottlenecks,
            "optimization_suggestions": self.optimization_suggestions,
            "resource_usage": self.resource_usage
        }


class FreeCADOperationProfiler:
    """
    Specialized profiler for FreeCAD operations.

    Tracks performance of FreeCAD-specific operations and identifies
    bottlenecks in document and geometry workflows.
    """

    def __init__(self,
                 document_manager: Optional[FreeCADDocumentManager] = None,
                 base_profiler: Optional[PerformanceProfiler] = None):
        """
        Initialize FreeCAD operation profiler.

        Args:
            document_manager: FreeCAD document manager instance
            base_profiler: Base performance profiler for low-level metrics
        """
        self.document_manager = document_manager or document_manager
        self.base_profiler = base_profiler or performance_profiler

        # Operation tracking
        self.active_operations: Dict[str, OperationMetrics] = {}
        self.completed_operations: List[OperationMetrics] = []
        self.active_workflows: Dict[str, WorkflowProfile] = {}
        self.completed_workflows: List[WorkflowProfile] = []

        # Performance baselines per operation type
        self.operation_baselines: Dict[FreeCADOperationType, Dict[str, float]] = {}

        # Bottleneck detection thresholds
        self.bottleneck_thresholds = {
            "duration_multiplier": 2.0,  # Operation takes 2x longer than baseline
            "memory_spike_mb": 500.0,  # Memory spike > 500MB
            "object_count_threshold": 10000,  # Large number of objects
            "vertex_count_threshold": 1000000,  # Large number of vertices
        }

        logger.info("FreeCADOperationProfiler initialized")

    @contextmanager
    def profile_operation(self,
                         operation_type: FreeCADOperationType,
                         operation_name: Optional[str] = None,
                         metadata: Optional[Dict[str, Any]] = None):
        """
        Profile a FreeCAD operation.

        Usage:
            with profiler.profile_operation(FreeCADOperationType.GEOMETRY_CREATE, "create_box"):
                # FreeCAD operation code
                pass
        """
        correlation_id = get_correlation_id()
        operation_id = f"{operation_type.value}_{uuid.uuid4().hex[:8]}"
        operation_name = operation_name or operation_type.value

        with create_span(f"freecad_operation_{operation_name}",
                        correlation_id=correlation_id) as span:
            span.set_attribute("operation.id", operation_id)
            span.set_attribute("operation.type", operation_type.value)

            # Create operation metrics
            operation = OperationMetrics(
                operation_id=operation_id,
                operation_type=operation_type,
                start_time=datetime.now(timezone.utc),
                metadata=metadata or {}
            )

            # Store active operation
            self.active_operations[operation_id] = operation

            # Get initial resource state
            import psutil
            process = psutil.Process()
            initial_memory = process.memory_info().rss / (1024 * 1024)  # MB
            initial_cpu_time = process.cpu_times().user + process.cpu_times().system

            try:
                # Profile with base profiler
                with self.base_profiler.profile_cpu(operation_name):
                    with self.base_profiler.profile_memory(operation_name, trace_allocations=False):
                        yield operation

                operation.success = True

            except Exception as e:
                operation.success = False
                operation.error_message = str(e)
                logger.error(f"Operation failed: {operation_name}",
                           operation_id=operation_id,
                           error=str(e),
                           correlation_id=correlation_id)
                raise

            finally:
                # Calculate final metrics
                operation.end_time = datetime.now(timezone.utc)
                operation.duration_seconds = (
                    operation.end_time - operation.start_time
                ).total_seconds()

                # Resource usage
                final_memory = process.memory_info().rss / (1024 * 1024)  # MB
                peak_memory = process.memory_info().rss / (1024 * 1024)  # Simplified
                final_cpu_time = process.cpu_times().user + process.cpu_times().system

                operation.memory_used_mb = final_memory - initial_memory
                operation.memory_peak_mb = peak_memory
                operation.cpu_time_seconds = final_cpu_time - initial_cpu_time

                # Get geometry statistics if available
                if operation_type in [
                    FreeCADOperationType.GEOMETRY_CREATE,
                    FreeCADOperationType.GEOMETRY_MODIFY,
                    FreeCADOperationType.GEOMETRY_BOOLEAN
                ]:
                    operation.metadata.update(self._get_geometry_statistics())

                # Remove from active and add to completed
                self.active_operations.pop(operation_id, None)
                self.completed_operations.append(operation)

                # Check for bottlenecks
                self._check_for_bottlenecks(operation)

                # Log summary
                logger.info("FreeCAD operation completed",
                          operation_id=operation_id,
                          operation_type=operation_type.value,
                          duration_seconds=operation.duration_seconds,
                          memory_used_mb=operation.memory_used_mb,
                          success=operation.success,
                          correlation_id=correlation_id)

                # Update metrics
                metrics.freecad_operation_duration_seconds.labels(
                    operation_type=operation_type.value,
                    success=str(operation.success)
                ).observe(operation.duration_seconds)

    @contextmanager
    def profile_workflow(self, workflow_name: str):
        """
        Profile a complete FreeCAD workflow.

        Usage:
            with profiler.profile_workflow("create_cam_path"):
                # Multiple FreeCAD operations
                pass
        """
        correlation_id = get_correlation_id()
        workflow_id = f"workflow_{uuid.uuid4().hex[:8]}"

        with create_span(f"freecad_workflow_{workflow_name}",
                        correlation_id=correlation_id) as span:
            span.set_attribute("workflow.id", workflow_id)
            span.set_attribute("workflow.name", workflow_name)

            # Create workflow profile
            workflow = WorkflowProfile(
                workflow_id=workflow_id,
                workflow_name=workflow_name,
                start_time=datetime.now(timezone.utc)
            )

            # Store active workflow
            self.active_workflows[workflow_id] = workflow

            # Track operations during workflow
            initial_operation_count = len(self.completed_operations)

            try:
                yield workflow

            finally:
                # Collect workflow operations
                workflow.end_time = datetime.now(timezone.utc)
                workflow.total_duration_seconds = (
                    workflow.end_time - workflow.start_time
                ).total_seconds()

                # Get operations that were part of this workflow
                workflow.operations = self.completed_operations[initial_operation_count:]

                # Analyze workflow
                workflow.bottlenecks = self._identify_workflow_bottlenecks(workflow)
                workflow.optimization_suggestions = self._generate_workflow_optimizations(workflow)
                workflow.resource_usage = self._calculate_workflow_resources(workflow)

                # Remove from active and add to completed
                self.active_workflows.pop(workflow_id, None)
                self.completed_workflows.append(workflow)

                # Log summary
                logger.info("FreeCAD workflow completed",
                          workflow_id=workflow_id,
                          workflow_name=workflow_name,
                          duration_seconds=workflow.total_duration_seconds,
                          operation_count=len(workflow.operations),
                          bottleneck_count=len(workflow.bottlenecks),
                          correlation_id=correlation_id)

    async def profile_async_operation(self,
                                     coroutine,
                                     operation_type: FreeCADOperationType,
                                     operation_name: Optional[str] = None):
        """
        Profile an async FreeCAD operation.

        Args:
            coroutine: Async function to profile
            operation_type: Type of FreeCAD operation
            operation_name: Optional operation name

        Returns:
            Coroutine result
        """
        with self.profile_operation(operation_type, operation_name):
            return await coroutine

    def analyze_document_operations(self, document_id: str) -> Dict[str, Any]:
        """
        Analyze performance of operations on a specific document.

        Args:
            document_id: Document ID to analyze

        Returns:
            Analysis results
        """
        # Filter operations related to this document
        doc_operations = [
            op for op in self.completed_operations
            if op.metadata.get("document_id") == document_id
        ]

        if not doc_operations:
            return {"document_id": document_id, "operations": [], "analysis": "No operations found"}

        # Calculate statistics
        total_time = sum(op.duration_seconds for op in doc_operations)
        total_memory = sum(op.memory_used_mb for op in doc_operations)

        # Group by operation type
        operations_by_type = defaultdict(list)
        for op in doc_operations:
            operations_by_type[op.operation_type.value].append(op)

        # Find slowest operations
        slowest_ops = sorted(doc_operations, key=lambda x: x.duration_seconds, reverse=True)[:5]

        analysis = {
            "document_id": document_id,
            "total_operations": len(doc_operations),
            "total_time_seconds": total_time,
            "total_memory_mb": total_memory,
            "operations_by_type": {
                op_type: {
                    "count": len(ops),
                    "total_time": sum(op.duration_seconds for op in ops),
                    "avg_time": sum(op.duration_seconds for op in ops) / len(ops)
                }
                for op_type, ops in operations_by_type.items()
            },
            "slowest_operations": [
                {
                    "operation_id": op.operation_id,
                    "type": op.operation_type.value,
                    "duration": op.duration_seconds,
                    "memory": op.memory_used_mb
                }
                for op in slowest_ops
            ],
            "recommendations": self._generate_document_recommendations(doc_operations)
        }

        return analysis

    def get_operation_statistics(self,
                                operation_type: Optional[FreeCADOperationType] = None) -> Dict[str, Any]:
        """
        Get statistics for FreeCAD operations.

        Args:
            operation_type: Filter by operation type

        Returns:
            Operation statistics
        """
        # Filter operations
        operations = self.completed_operations
        if operation_type:
            operations = [op for op in operations if op.operation_type == operation_type]

        if not operations:
            return {"message": "No operations found"}

        # Calculate statistics
        durations = [op.duration_seconds for op in operations]
        memory_usage = [op.memory_used_mb for op in operations]
        success_rate = sum(1 for op in operations if op.success) / len(operations) * 100

        stats = {
            "operation_count": len(operations),
            "success_rate": success_rate,
            "duration": {
                "min": min(durations),
                "max": max(durations),
                "avg": sum(durations) / len(durations),
                "total": sum(durations)
            },
            "memory": {
                "min": min(memory_usage) if memory_usage else 0,
                "max": max(memory_usage) if memory_usage else 0,
                "avg": sum(memory_usage) / len(memory_usage) if memory_usage else 0,
                "total": sum(memory_usage)
            }
        }

        # Add operation type breakdown if not filtered
        if not operation_type:
            type_breakdown = defaultdict(int)
            for op in operations:
                type_breakdown[op.operation_type.value] += 1
            stats["operation_types"] = dict(type_breakdown)

        return stats

    def set_operation_baseline(self,
                              operation_type: FreeCADOperationType,
                              force: bool = False):
        """
        Set performance baseline for an operation type.

        Args:
            operation_type: Operation type to baseline
            force: Force update even if baseline exists
        """
        # Get operations of this type
        operations = [
            op for op in self.completed_operations
            if op.operation_type == operation_type and op.success
        ]

        if not operations:
            logger.warning(f"No successful operations found for baseline: {operation_type.value}")
            return

        # Calculate baseline metrics
        durations = [op.duration_seconds for op in operations]
        memory_usage = [op.memory_used_mb for op in operations]

        baseline = {
            "avg_duration": sum(durations) / len(durations),
            "max_duration": max(durations),
            "avg_memory": sum(memory_usage) / len(memory_usage) if memory_usage else 0,
            "max_memory": max(memory_usage) if memory_usage else 0,
            "sample_count": len(operations),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Check if baseline exists
        if operation_type in self.operation_baselines and not force:
            logger.info(f"Baseline already exists for {operation_type.value}, use force=True to update")
            return

        self.operation_baselines[operation_type] = baseline

        logger.info(f"Operation baseline set",
                   operation_type=operation_type.value,
                   avg_duration=baseline["avg_duration"],
                   sample_count=baseline["sample_count"])

    def compare_with_baseline(self, operation: OperationMetrics) -> Dict[str, Any]:
        """
        Compare operation performance with baseline.

        Args:
            operation: Operation to compare

        Returns:
            Comparison results
        """
        if operation.operation_type not in self.operation_baselines:
            return {"status": "no_baseline", "operation_type": operation.operation_type.value}

        baseline = self.operation_baselines[operation.operation_type]

        # Calculate deviations
        duration_deviation = (
            (operation.duration_seconds - baseline["avg_duration"]) / baseline["avg_duration"] * 100
        )
        memory_deviation = (
            (operation.memory_used_mb - baseline["avg_memory"]) / baseline["avg_memory"] * 100
            if baseline["avg_memory"] > 0 else 0
        )

        comparison = {
            "operation_id": operation.operation_id,
            "operation_type": operation.operation_type.value,
            "duration": {
                "actual": operation.duration_seconds,
                "baseline": baseline["avg_duration"],
                "deviation_percent": duration_deviation,
                "status": "slower" if duration_deviation > 10 else "normal"
            },
            "memory": {
                "actual": operation.memory_used_mb,
                "baseline": baseline["avg_memory"],
                "deviation_percent": memory_deviation,
                "status": "higher" if memory_deviation > 20 else "normal"
            },
            "recommendations": []
        }

        # Generate recommendations
        if duration_deviation > 50:
            comparison["recommendations"].append({
                "issue": "Significant performance degradation",
                "issue_tr": "Önemli performans düşüşü",
                "suggestion": "Investigate recent changes or resource constraints",
                "suggestion_tr": "Son değişiklikleri veya kaynak kısıtlamalarını araştırın"
            })

        if memory_deviation > 100:
            comparison["recommendations"].append({
                "issue": "Excessive memory usage",
                "issue_tr": "Aşırı bellek kullanımı",
                "suggestion": "Check for memory leaks or large data structures",
                "suggestion_tr": "Bellek sızıntılarını veya büyük veri yapılarını kontrol edin"
            })

        return comparison

    # Private helper methods

    def _get_geometry_statistics(self) -> Dict[str, Any]:
        """Get geometry statistics from current document."""
        # This would integrate with FreeCAD to get actual geometry stats
        # For now, return placeholder data
        return {
            "object_count": 0,
            "vertex_count": 0,
            "face_count": 0,
            "edge_count": 0
        }

    def _check_for_bottlenecks(self, operation: OperationMetrics):
        """Check if operation is a bottleneck."""
        bottlenecks = []

        # Check against baseline
        if operation.operation_type in self.operation_baselines:
            baseline = self.operation_baselines[operation.operation_type]
            if operation.duration_seconds > baseline["avg_duration"] * self.bottleneck_thresholds["duration_multiplier"]:
                bottlenecks.append({
                    "type": "slow_operation",
                    "description": f"Operation {operation.operation_id} is {operation.duration_seconds / baseline['avg_duration']:.1f}x slower than baseline"
                })

        # Check memory spike
        if operation.memory_used_mb > self.bottleneck_thresholds["memory_spike_mb"]:
            bottlenecks.append({
                "type": "memory_spike",
                "description": f"Operation {operation.operation_id} used {operation.memory_used_mb:.1f}MB of memory"
            })

        # Check object count
        if operation.object_count > self.bottleneck_thresholds["object_count_threshold"]:
            bottlenecks.append({
                "type": "high_object_count",
                "description": f"Operation {operation.operation_id} created {operation.object_count} objects"
            })

        if bottlenecks:
            logger.warning("Bottlenecks detected",
                         operation_id=operation.operation_id,
                         bottleneck_count=len(bottlenecks),
                         bottlenecks=bottlenecks)

    def _identify_workflow_bottlenecks(self, workflow: WorkflowProfile) -> List[Dict[str, Any]]:
        """Identify bottlenecks in a workflow."""
        if not workflow.operations:
            return []

        bottlenecks = []

        # Find operations that take disproportionate time
        total_time = workflow.total_duration_seconds
        for op in workflow.operations:
            time_percentage = (op.duration_seconds / total_time * 100) if total_time > 0 else 0
            if time_percentage > 30:  # Operation takes > 30% of total time
                bottlenecks.append({
                    "operation_id": op.operation_id,
                    "operation_type": op.operation_type.value,
                    "time_percentage": time_percentage,
                    "duration": op.duration_seconds,
                    "description": f"Operation takes {time_percentage:.1f}% of workflow time"
                })

        # Sort by impact
        bottlenecks.sort(key=lambda x: x["time_percentage"], reverse=True)

        return bottlenecks[:5]  # Top 5 bottlenecks

    def _generate_workflow_optimizations(self, workflow: WorkflowProfile) -> List[Dict[str, Any]]:
        """Generate optimization suggestions for workflow."""
        suggestions = []

        # Check for sequential operations that could be parallelized
        if len(workflow.operations) > 3:
            suggestions.append({
                "type": "parallelization",
                "description": "Consider parallelizing independent operations",
                "description_tr": "Bağımsız işlemleri paralel hale getirmeyi düşünün",
                "potential_improvement": "20-40%"
            })

        # Check for repeated similar operations
        op_types = [op.operation_type for op in workflow.operations]
        for op_type in set(op_types):
            if op_types.count(op_type) > 3:
                suggestions.append({
                    "type": "batching",
                    "description": f"Consider batching {op_type.value} operations",
                    "description_tr": f"{op_type.value} işlemlerini toplu hale getirmeyi düşünün",
                    "potential_improvement": "10-30%"
                })

        return suggestions

    def _calculate_workflow_resources(self, workflow: WorkflowProfile) -> Dict[str, Any]:
        """Calculate total resource usage for workflow."""
        if not workflow.operations:
            return {}

        return {
            "total_cpu_time": sum(op.cpu_time_seconds for op in workflow.operations),
            "peak_memory_mb": max(op.memory_peak_mb for op in workflow.operations),
            "total_memory_mb": sum(op.memory_used_mb for op in workflow.operations),
            "total_objects": sum(op.object_count for op in workflow.operations),
            "total_vertices": sum(op.vertex_count for op in workflow.operations)
        }

    def _generate_document_recommendations(self, operations: List[OperationMetrics]) -> List[Dict[str, Any]]:
        """Generate recommendations for document operations."""
        recommendations = []

        # Check for frequent saves
        save_ops = [op for op in operations if op.operation_type == FreeCADOperationType.DOCUMENT_SAVE]
        if len(save_ops) > 10:
            recommendations.append({
                "type": "reduce_saves",
                "description": "Reduce save frequency to improve performance",
                "description_tr": "Performansı artırmak için kaydetme sıklığını azaltın"
            })

        # Check for memory-intensive operations
        high_memory_ops = [op for op in operations if op.memory_used_mb > 100]
        if high_memory_ops:
            recommendations.append({
                "type": "optimize_memory",
                "description": "Optimize memory-intensive operations",
                "description_tr": "Bellek yoğun işlemleri optimize edin"
            })

        return recommendations


# Global FreeCAD operation profiler instance
freecad_operation_profiler = FreeCADOperationProfiler()