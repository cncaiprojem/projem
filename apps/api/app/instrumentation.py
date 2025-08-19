from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased, ALWAYS_ON
from prometheus_fastapi_instrumentator import Instrumentator

try:
    from opentelemetry.instrumentation.celery import CeleryInstrumentor
except Exception:  # pragma: no cover
    CeleryInstrumentor = None  # type: ignore

from .config import settings


def setup_tracing() -> None:
    # Sampler: dev %100, prod %10
    resource = Resource(attributes={SERVICE_NAME: settings.otel_service_name})
    sampler = ALWAYS_ON if settings.env != "production" else TraceIdRatioBased(0.1)
    tracer_provider = TracerProvider(resource=resource, sampler=sampler)
    if settings.otel_exporter_otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
        tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(tracer_provider)


def setup_metrics(app) -> None:
    Instrumentator().instrument(app).expose(app, include_in_schema=False, should_gzip=True)


def setup_celery_instrumentation() -> None:
    if CeleryInstrumentor is None:
        return
    try:
        CeleryInstrumentor().instrument()
    except Exception:
        pass
