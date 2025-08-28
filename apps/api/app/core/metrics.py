"""
Task 6.10: Prometheus metrics for job orchestration observability.

Implements the required metrics:
- job_create_total (labels: type, status)
- job_in_progress (gauge) 
- job_duration_seconds (histogram)
- retries_total (labels: type, error_code)
- dlq_depth (gauge per queue)
- dlq_replay_total
- cancellation_total
- progress_update_total
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry, REGISTRY
from typing import Optional

# Job creation metrics
job_create_total = Counter(
    'job_create_total',
    'Total number of job creation attempts',
    ['type', 'status', 'idempotency_key_reused'],
    registry=REGISTRY
)

# Job status tracking
job_in_progress = Gauge(
    'job_in_progress', 
    'Number of jobs currently in progress',
    ['type', 'queue'],
    registry=REGISTRY
)

# Job completion metrics
job_duration_seconds = Histogram(
    'job_duration_seconds',
    'Time taken to complete jobs from creation to finish',
    ['type', 'status', 'queue'],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, float('inf')),
    registry=REGISTRY
)

# Retry tracking
retries_total = Counter(
    'retries_total',
    'Total number of job retries',
    ['type', 'error_code', 'queue', 'attempt'],
    registry=REGISTRY
)

# DLQ monitoring
dlq_depth = Gauge(
    'dlq_depth',
    'Number of messages in Dead Letter Queue',
    ['queue', 'original_queue'],
    registry=REGISTRY
)

dlq_replay_total = Counter(
    'dlq_replay_total',
    'Total number of DLQ message replay attempts', 
    ['queue', 'status', 'replay_strategy'],
    registry=REGISTRY
)

# Cancellation tracking
cancellation_total = Counter(
    'cancellation_total',
    'Total number of job cancellations',
    ['type', 'initiator', 'reason', 'job_status'],
    registry=REGISTRY
)

# Progress update tracking
progress_update_total = Counter(
    'progress_update_total',
    'Total number of progress updates',
    ['type', 'update_source', 'throttled'],
    registry=REGISTRY
)

# Queue depth monitoring
queue_depth = Gauge(
    'queue_depth',
    'Number of messages in queue',
    ['queue', 'queue_type'],
    registry=REGISTRY
)

# Worker metrics
active_workers = Gauge(
    'active_workers',
    'Number of active workers',
    ['queue', 'worker_type'],
    registry=REGISTRY
)

# Audit chain metrics
audit_chain_operations_total = Counter(
    'audit_chain_operations_total',
    'Total number of audit chain operations',
    ['operation_type', 'status', 'tamper_detected'],
    registry=REGISTRY
)

# Idempotency tracking
idempotency_operations_total = Counter(
    'idempotency_operations_total', 
    'Total number of idempotency operations',
    ['operation', 'key_exists', 'race_condition_detected'],
    registry=REGISTRY
)

# Error taxonomy routing
error_routing_total = Counter(
    'error_routing_total',
    'Total number of errors routed to retry vs DLQ',
    ['error_type', 'routing_decision', 'retry_count'],
    registry=REGISTRY
)

# Performance metrics
request_duration_seconds = Histogram(
    'request_duration_seconds',
    'Time taken to process requests',
    ['endpoint', 'method', 'status_code'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float('inf')),
    registry=REGISTRY
)

# Tracing integration metrics
trace_spans_total = Counter(
    'trace_spans_total',
    'Total number of trace spans created',
    ['operation_type', 'service', 'linked_to_job'],
    registry=REGISTRY
)

# FreeCAD-specific metrics
freecad_operations_total = Counter(
    'freecad_operations_total',
    'Total number of FreeCAD operations',
    ['operation_type', 'license_tier', 'status'],
    registry=REGISTRY
)

freecad_operation_duration_seconds = Histogram(
    'freecad_operation_duration_seconds',
    'Time taken to complete FreeCAD operations',
    ['operation_type', 'license_tier', 'status'],
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1200.0, 1800.0, 3600.0, float('inf')),
    registry=REGISTRY
)

freecad_memory_peak_mb = Gauge(
    'freecad_memory_peak_mb',
    'Peak memory usage during FreeCAD operations',
    ['operation_type', 'license_tier'],
    registry=REGISTRY
)

freecad_cpu_average_percent = Gauge(
    'freecad_cpu_average_percent',
    'Average CPU usage during FreeCAD operations',
    ['operation_type', 'license_tier'],
    registry=REGISTRY
)

freecad_circuit_breaker_state = Gauge(
    'freecad_circuit_breaker_state',
    'Circuit breaker state (0=closed, 1=open, 2=half-open)',
    registry=REGISTRY
)

freecad_active_processes = Gauge(
    'freecad_active_processes',
    'Number of active FreeCAD processes',
    registry=REGISTRY
)

# FreeCAD Document Lifecycle Metrics for Task 7.19
freecad_documents_total = Counter(
    'freecad_documents_total',
    'Total number of document operations',
    ['operation'],  # create, open, close, save
    registry=REGISTRY
)

freecad_document_locks_active = Gauge(
    'freecad_document_locks_active',
    'Number of active document locks',
    registry=REGISTRY
)

freecad_transactions_total = Counter(
    'freecad_transactions_total',
    'Total number of document transactions',
    ['operation'],  # start, commit, abort
    registry=REGISTRY
)

freecad_document_saves_total = Counter(
    'freecad_document_saves_total',
    'Total number of document saves',
    ['compressed'],  # true, false
    registry=REGISTRY
)

freecad_backups_total = Counter(
    'freecad_backups_total',
    'Total number of document backups created',
    registry=REGISTRY
)

freecad_backup_restores_total = Counter(
    'freecad_backup_restores_total',
    'Total number of backup restores',
    ['status'],  # success, failed
    registry=REGISTRY
)

freecad_document_migrations_total = Counter(
    'freecad_document_migrations_total',
    'Total number of document migrations',
    ['status'],  # success, failed
    registry=REGISTRY
)

# License-specific metrics
license_operations_total = Counter(
    'license_operations_total',
    'Total number of license operations',
    ['operation', 'license_type', 'status', 'user_type'],
    registry=REGISTRY
)

license_assignment_duration_seconds = Histogram(
    'license_assignment_duration_seconds',
    'Time taken to assign licenses',
    ['license_type', 'status'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, float('inf')),
    registry=REGISTRY
)

licenses_active_total = Gauge(
    'licenses_active_total',
    'Total number of active licenses',
    ['license_type', 'environment'],
    registry=REGISTRY
)

# Task 7.4: Model Flow and FEM Simulation Metrics
freecad_model_generations_total = Counter(
    'freecad_model_generations_total',
    'Total number of FreeCAD model generations',
    ['type', 'status'],  # type: ai_prompt, parametric, upload_normalization, assembly4
    registry=REGISTRY
)

freecad_model_generation_duration = Histogram(
    'freecad_model_generation_duration',
    'Time taken to generate FreeCAD models',
    ['type'],  # type: ai_prompt, parametric, upload_normalization, assembly4
    buckets=(5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1200.0, 1800.0, 3600.0, float('inf')),
    registry=REGISTRY
)

fem_simulations_total = Counter(
    'fem_simulations_total',
    'Total number of FEM simulations',
    ['analysis_type', 'status'],  # analysis_type: static, modal, buckling, thermal_steady, thermal_transient, coupled_thermal_static
    registry=REGISTRY
)

fem_simulation_duration = Histogram(
    'fem_simulation_duration',
    'Time taken to complete FEM simulations',
    ['analysis_type'],
    buckets=(60.0, 300.0, 600.0, 1200.0, 1800.0, 3600.0, 7200.0, 14400.0, float('inf')),
    registry=REGISTRY
)

fem_mesh_elements_total = Histogram(
    'fem_mesh_elements_total',
    'Number of mesh elements in FEM simulations',
    ['analysis_type'],
    buckets=(1000, 5000, 10000, 25000, 50000, 100000, 250000, 500000, float('inf')),
    registry=REGISTRY
)

ai_adapter_requests_total = Counter(
    'ai_adapter_requests_total',
    'Total number of AI adapter requests',
    ['provider', 'status'],
    registry=REGISTRY
)

ai_adapter_request_duration = Histogram(
    'ai_adapter_request_duration',
    'Time taken for AI adapter requests',
    ['provider'],
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0, float('inf')),
    registry=REGISTRY
)


class MetricsCollector:
    """
    Helper class for collecting and updating metrics with consistent labeling.
    """
    
    @staticmethod
    def record_job_creation(
        job_type: str,
        status: str,
        idempotency_key_reused: bool = False
    ):
        """Record job creation metrics."""
        job_create_total.labels(
            type=job_type,
            status=status,
            idempotency_key_reused=str(idempotency_key_reused).lower()
        ).inc()
    
    @staticmethod
    def set_job_in_progress(job_type: str, queue: str, count: int):
        """Set number of jobs in progress."""
        job_in_progress.labels(type=job_type, queue=queue).set(count)
    
    @staticmethod
    def record_job_duration(
        job_type: str, 
        status: str, 
        queue: str, 
        duration_seconds: float
    ):
        """Record job completion duration."""
        job_duration_seconds.labels(
            type=job_type, 
            status=status, 
            queue=queue
        ).observe(duration_seconds)
    
    @staticmethod
    def record_job_retry(
        job_type: str,
        error_code: str,
        queue: str,
        attempt: int
    ):
        """Record job retry attempt."""
        retries_total.labels(
            type=job_type,
            error_code=error_code,
            queue=queue,
            attempt=str(attempt)
        ).inc()
    
    @staticmethod
    def set_dlq_depth(queue: str, original_queue: str, depth: int):
        """Set DLQ depth."""
        dlq_depth.labels(queue=queue, original_queue=original_queue).set(depth)
    
    @staticmethod
    def record_dlq_replay(
        queue: str,
        status: str,
        replay_strategy: str = "manual"
    ):
        """Record DLQ replay attempt."""
        dlq_replay_total.labels(
            queue=queue,
            status=status,
            replay_strategy=replay_strategy
        ).inc()
    
    @staticmethod
    def record_job_cancellation(
        job_type: str,
        initiator: str,
        reason: str,
        job_status: str
    ):
        """Record job cancellation."""
        cancellation_total.labels(
            type=job_type,
            initiator=initiator,
            reason=reason,
            job_status=job_status
        ).inc()
    
    @staticmethod
    def record_progress_update(
        job_type: str,
        update_source: str,
        throttled: bool = False
    ):
        """Record progress update."""
        progress_update_total.labels(
            type=job_type,
            update_source=update_source,
            throttled=str(throttled).lower()
        ).inc()
    
    @staticmethod
    def set_queue_depth(queue: str, queue_type: str, depth: int):
        """Set queue depth."""
        queue_depth.labels(queue=queue, queue_type=queue_type).set(depth)
    
    @staticmethod
    def set_active_workers(queue: str, worker_type: str, count: int):
        """Set active worker count."""
        active_workers.labels(queue=queue, worker_type=worker_type).set(count)
    
    @staticmethod
    def record_audit_chain_operation(
        operation_type: str,
        status: str,
        tamper_detected: bool = False
    ):
        """Record audit chain operation."""
        audit_chain_operations_total.labels(
            operation_type=operation_type,
            status=status,
            tamper_detected=str(tamper_detected).lower()
        ).inc()
    
    @staticmethod
    def record_idempotency_operation(
        operation: str,
        key_exists: bool,
        race_condition_detected: bool = False
    ):
        """Record idempotency operation."""
        idempotency_operations_total.labels(
            operation=operation,
            key_exists=str(key_exists).lower(),
            race_condition_detected=str(race_condition_detected).lower()
        ).inc()
    
    @staticmethod
    def record_error_routing(
        error_type: str,
        routing_decision: str,
        retry_count: int
    ):
        """Record error routing decision."""
        error_routing_total.labels(
            error_type=error_type,
            routing_decision=routing_decision,
            retry_count=str(retry_count)
        ).inc()
    
    @staticmethod
    def record_request_duration(
        endpoint: str,
        method: str,
        status_code: str,
        duration_seconds: float
    ):
        """Record request duration."""
        request_duration_seconds.labels(
            endpoint=endpoint,
            method=method,
            status_code=status_code
        ).observe(duration_seconds)
    
    @staticmethod
    def record_trace_span(
        operation_type: str,
        service: str,
        linked_to_job: bool = False
    ):
        """Record trace span creation."""
        trace_spans_total.labels(
            operation_type=operation_type,
            service=service,
            linked_to_job=str(linked_to_job).lower()
        ).inc()


# Export collector instance for easy use
metrics = MetricsCollector()

# Export all metrics for direct access if needed
__all__ = [
    'job_create_total',
    'job_in_progress', 
    'job_duration_seconds',
    'retries_total',
    'dlq_depth',
    'dlq_replay_total',
    'cancellation_total',
    'progress_update_total',
    'queue_depth',
    'active_workers',
    'audit_chain_operations_total',
    'idempotency_operations_total',
    'error_routing_total',
    'request_duration_seconds',
    'trace_spans_total',
    'freecad_operations_total',
    'freecad_operation_duration_seconds',
    'freecad_memory_peak_mb',
    'freecad_cpu_average_percent',
    'freecad_circuit_breaker_state',
    'freecad_active_processes',
    'license_operations_total',
    'license_assignment_duration_seconds',
    'licenses_active_total',
    # Task 7.4: New model flow and FEM metrics
    'freecad_model_generations_total',
    'freecad_model_generation_duration',
    'fem_simulations_total',
    'fem_simulation_duration',
    'fem_mesh_elements_total',
    'ai_adapter_requests_total',
    'ai_adapter_request_duration',
    'MetricsCollector',
    'metrics'
]