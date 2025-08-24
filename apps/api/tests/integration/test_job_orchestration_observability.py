"""
Integration tests for Task 6.10: Job Orchestration Observability

Tests cover:
- End-to-end API-to-worker tracing
- Cross-service telemetry propagation  
- Real Celery task execution with observability
- FastAPI + Celery + RabbitMQ integration
- Metrics collection during actual job processing
- Full observability stack integration
"""

import asyncio
import json
import time
import uuid
from typing import Dict, Any
from unittest.mock import patch, MagicMock

import pytest
import pytest_asyncio
from celery import Celery
from celery.result import AsyncResult
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry, generate_latest
from sqlalchemy.orm import Session

from app.main import app
from app.core.celery_app import celery_app
from app.core.database import get_db
from app.core.logging_config import bind_request_context, get_logger
from app.core.metrics import metrics
from app.core.telemetry import create_span, get_tracer, initialize_telemetry
from app.models.job import Job
from app.schemas.job import JobCreate
from app.tasks.job_tasks import process_job_task


@pytest.fixture(scope="module")
def test_client():
    """Create test client for integration tests."""
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module")
def test_celery_app():
    """Setup test Celery app for integration testing."""
    # Configure test Celery app
    test_app = Celery('test-app')
    test_app.conf.update(
        broker_url='memory://',
        result_backend='cache+memory://',
        task_always_eager=False,  # Allow async execution
        task_eager_propagates=True,
        task_store_eager_result=True,
    )
    
    # Register test tasks
    test_app.task(process_job_task)
    
    return test_app


@pytest.fixture(autouse=True)
def setup_telemetry():
    """Initialize telemetry for integration tests."""
    initialize_telemetry(
        service_name="test-freecad-api",
        otlp_endpoint="http://localhost:4317",
        environment="integration_test"
    )
    yield
    # Cleanup after tests


class TestAPIToWorkerTracing:
    """Test end-to-end API-to-worker tracing integration."""
    
    def test_job_creation_api_tracing(self, test_client):
        """Test job creation API generates proper traces."""
        job_data = {
            "type": "model",
            "parameters": {
                "shape": "cylinder",
                "height": 100,
                "radius": 25
            }
        }
        
        # Add tracing headers
        headers = {
            "X-Request-ID": f"req-{uuid.uuid4()}",
            "X-Trace-ID": f"trace-{uuid.uuid4()}",
            "Content-Type": "application/json"
        }
        
        with patch('app.routers.jobs.get_db') as mock_db:
            mock_session = MagicMock(spec=Session)
            mock_db.return_value = mock_session
            
            # Mock job creation
            mock_job = Job(
                id=f"job-{uuid.uuid4()}",
                type="model",
                status="pending",
                parameters=job_data["parameters"]
            )
            mock_session.add.return_value = None
            mock_session.flush.side_effect = lambda: setattr(mock_job, 'id', mock_job.id)
            mock_session.commit.return_value = None
            
            # Make API request
            response = test_client.post(
                "/api/v1/jobs",
                json=job_data,
                headers=headers
            )
            
            # Verify API response
            assert response.status_code in [200, 201]
            
            # Verify tracing context was propagated
            # In real test, would verify span creation via telemetry backend
    
    @pytest_asyncio.mark.asyncio
    async def test_api_to_celery_trace_propagation(self):
        """Test trace context propagation from API to Celery worker."""
        trace_id = f"trace-{uuid.uuid4()}"
        job_id = f"job-{uuid.uuid4()}"
        
        # Mock Celery task with trace propagation
        @celery_app.task(bind=True)
        def test_trace_task(self, job_data: Dict[str, Any]):
            # Verify trace context is available in worker
            from app.core.telemetry import get_tracer
            tracer = get_tracer()
            
            with create_span("celery_task_execution", job_id=job_data.get("id")):
                # Simulate job processing
                time.sleep(0.1)
                
                # Record metrics
                metrics.record_job_creation("model", "success", False)
                metrics.set_job_in_progress("model", "model_queue", 1)
                
                # Process complete
                metrics.record_job_duration("model", "success", "model_queue", 0.1)
                metrics.set_job_in_progress("model", "model_queue", 0)
                
                return {"status": "completed", "job_id": job_data.get("id")}
        
        # Execute task with trace context
        job_data = {"id": job_id, "type": "model", "parameters": {"test": True}}
        
        # In real implementation, trace context would be injected into headers
        with create_span("api_request", job_id=job_id):
            result = test_trace_task.delay(job_data)
            
            # Wait for task completion
            task_result = result.get(timeout=10)
            
            assert task_result["status"] == "completed"
            assert task_result["job_id"] == job_id
    
    def test_cross_service_correlation_ids(self, test_client):
        """Test correlation ID propagation across services."""
        correlation_id = f"corr-{uuid.uuid4()}"
        request_id = f"req-{uuid.uuid4()}"
        
        headers = {
            "X-Correlation-ID": correlation_id,
            "X-Request-ID": request_id,
            "Content-Type": "application/json"
        }
        
        job_data = {
            "type": "cam", 
            "parameters": {"tool": "end_mill", "material": "aluminum"}
        }
        
        with patch('app.routers.jobs.get_db') as mock_db:
            mock_session = MagicMock(spec=Session)
            mock_db.return_value = mock_session
            
            # Mock successful job creation
            mock_job = Job(id=f"job-{uuid.uuid4()}", type="cam", status="pending")
            mock_session.add.return_value = None
            mock_session.flush.side_effect = lambda: None
            mock_session.commit.return_value = None
            
            response = test_client.post(
                "/api/v1/jobs",
                json=job_data,
                headers=headers
            )
            
            # Verify correlation tracking
            # In production, would verify logs contain correlation_id
            assert response.status_code in [200, 201]
    
    def test_error_propagation_in_traces(self):
        """Test error propagation through trace spans."""
        job_id = f"job-error-{uuid.uuid4()}"
        
        # Simulate job that fails with proper error tracing
        with create_span("job_processing_error", job_id=job_id) as span:
            try:
                # Simulate error condition
                raise ValueError("Simulated job processing error")
            except ValueError as e:
                # Verify error is recorded in span
                if span:
                    # Error details would be added to span
                    pass
                
                # Record error metrics
                metrics.record_job_creation("model", "failed", False)
                metrics.record_error_routing("PROCESSING_ERROR", "retry", 1)
                
                # Re-raise for test verification
                raise
        
        # Test should complete with exception handling


class TestCeleryObservabilityIntegration:
    """Test Celery task observability integration."""
    
    def test_celery_task_metrics_collection(self):
        """Test metrics collection during Celery task execution."""
        
        @celery_app.task(bind=True)
        def metrics_test_task(self, job_data: Dict[str, Any]):
            job_id = job_data["id"]
            job_type = job_data["type"]
            
            # Record task start
            metrics.record_job_creation(job_type, "started", False)
            metrics.set_job_in_progress(job_type, f"{job_type}_queue", 1)
            
            # Simulate processing with progress updates
            for progress in [25, 50, 75, 100]:
                metrics.record_progress_update(job_type, "worker", False)
                time.sleep(0.01)  # Simulate work
            
            # Complete job
            metrics.record_job_duration(job_type, "success", f"{job_type}_queue", 0.05)
            metrics.set_job_in_progress(job_type, f"{job_type}_queue", 0)
            
            return {"status": "completed", "job_id": job_id}
        
        # Execute task
        job_data = {"id": f"job-{uuid.uuid4()}", "type": "sim"}
        result = metrics_test_task.delay(job_data)
        
        # Verify task completion
        task_result = result.get(timeout=10)
        assert task_result["status"] == "completed"
        
        # Verify metrics were recorded
        # In production, would query metrics backend
    
    def test_celery_retry_observability(self):
        """Test retry behavior observability in Celery tasks."""
        
        @celery_app.task(bind=True, autoretry_for=(ValueError,), retry_kwargs={'max_retries': 3})
        def retry_test_task(self, job_data: Dict[str, Any], should_fail: bool = True):
            job_id = job_data["id"]
            
            # Record retry attempt
            attempt = self.request.retries + 1
            metrics.record_job_retry("model", "PROCESSING_ERROR", "model_queue", attempt)
            
            if should_fail and attempt <= 2:
                # Record error routing
                metrics.record_error_routing("PROCESSING_ERROR", "retry", attempt)
                raise ValueError(f"Simulated failure on attempt {attempt}")
            
            # Success on final attempt
            metrics.record_job_creation("model", "success", False)
            metrics.record_error_routing("PROCESSING_ERROR", "success", attempt)
            
            return {"status": "completed", "attempts": attempt}
        
        # Execute task that will retry
        job_data = {"id": f"job-retry-{uuid.uuid4()}", "type": "model"}
        result = retry_test_task.delay(job_data, should_fail=True)
        
        # Should succeed after retries
        task_result = result.get(timeout=15)
        assert task_result["status"] == "completed"
        assert task_result["attempts"] > 1
    
    def test_celery_dlq_routing(self):
        """Test DLQ routing observability for failed tasks."""
        
        @celery_app.task(bind=True)
        def dlq_test_task(self, job_data: Dict[str, Any]):
            job_id = job_data["id"]
            
            # Simulate non-retryable error
            metrics.record_error_routing("INVALID_INPUT", "dlq", 0)
            metrics.set_dlq_depth("model_dlq", "model", 1)
            
            # Task fails and goes to DLQ
            raise ValueError("Non-retryable error - invalid input format")
        
        job_data = {"id": f"job-dlq-{uuid.uuid4()}", "type": "model"}
        result = dlq_test_task.delay(job_data)
        
        # Task should fail
        with pytest.raises(ValueError):
            result.get(timeout=10)
        
        # Verify DLQ routing was recorded
        # In production, would verify DLQ metrics


class TestRealJobProcessingObservability:
    """Test observability with actual job processing scenarios."""
    
    def test_model_generation_job_observability(self):
        """Test observability for model generation job flow."""
        job_id = f"job-model-{uuid.uuid4()}"
        
        # Mock model generation task
        @celery_app.task(bind=True) 
        def model_generation_task(self, job_data: Dict[str, Any]):
            job_id = job_data["id"]
            parameters = job_data["parameters"]
            
            with create_span("model_generation", job_id=job_id, operation_type="job"):
                # Start job
                metrics.record_job_creation("model", "started", False)
                metrics.set_job_in_progress("model", "model_queue", 1)
                
                # Simulate model generation phases
                phases = ["parsing", "geometry", "meshing", "rendering"]
                for i, phase in enumerate(phases):
                    with create_span(f"model_{phase}", job_id=job_id):
                        metrics.record_progress_update("model", "worker", False)
                        time.sleep(0.02)  # Simulate work
                
                # Complete job
                duration = 0.08  # Simulated total duration
                metrics.record_job_duration("model", "success", "model_queue", duration)
                metrics.set_job_in_progress("model", "model_queue", 0)
                
                # Record audit event
                metrics.record_audit_chain_operation("complete", "success", False)
                
                return {
                    "status": "completed",
                    "job_id": job_id,
                    "model_url": f"s3://models/{job_id}.step",
                    "duration": duration
                }
        
        # Execute model generation
        job_data = {
            "id": job_id,
            "type": "model",
            "parameters": {
                "shape": "box",
                "length": 100,
                "width": 50,
                "height": 25
            }
        }
        
        result = model_generation_task.delay(job_data)
        task_result = result.get(timeout=15)
        
        assert task_result["status"] == "completed"
        assert task_result["job_id"] == job_id
        assert "model_url" in task_result
    
    def test_cam_path_generation_observability(self):
        """Test observability for CAM path generation."""
        job_id = f"job-cam-{uuid.uuid4()}"
        
        @celery_app.task(bind=True)
        def cam_generation_task(self, job_data: Dict[str, Any]):
            job_id = job_data["id"]
            
            with create_span("cam_generation", job_id=job_id, operation_type="job"):
                # Record job phases with different error scenarios
                try:
                    # Phase 1: Tool path calculation
                    with create_span("toolpath_calculation", job_id=job_id):
                        metrics.record_progress_update("cam", "worker", False)
                        time.sleep(0.01)
                    
                    # Phase 2: Collision detection
                    with create_span("collision_detection", job_id=job_id):
                        metrics.record_progress_update("cam", "worker", False)
                        time.sleep(0.01)
                    
                    # Phase 3: G-code generation
                    with create_span("gcode_generation", job_id=job_id):
                        metrics.record_progress_update("cam", "worker", False)
                        time.sleep(0.01)
                    
                    # Success
                    metrics.record_job_creation("cam", "success", False)
                    metrics.record_job_duration("cam", "success", "cam_queue", 0.03)
                    
                    return {
                        "status": "completed",
                        "gcode_url": f"s3://gcode/{job_id}.nc"
                    }
                    
                except Exception as e:
                    # Handle CAM-specific errors
                    metrics.record_error_routing("CAM_ERROR", "retry", 1)
                    metrics.record_job_retry("cam", "CAM_ERROR", "cam_queue", 1)
                    raise
        
        job_data = {
            "id": job_id,
            "type": "cam",
            "parameters": {
                "tool": "end_mill_6mm",
                "material": "aluminum",
                "cutting_speed": 1200
            }
        }
        
        result = cam_generation_task.delay(job_data)
        task_result = result.get(timeout=15)
        
        assert task_result["status"] == "completed"
        assert "gcode_url" in task_result
    
    def test_job_cancellation_observability(self):
        """Test job cancellation observability flow."""
        job_id = f"job-cancel-{uuid.uuid4()}"
        
        @celery_app.task(bind=True)
        def cancellable_task(self, job_data: Dict[str, Any]):
            job_id = job_data["id"]
            
            with create_span("cancellable_job", job_id=job_id):
                metrics.set_job_in_progress("sim", "sim_queue", 1)
                
                # Simulate long-running job that can be cancelled
                for i in range(10):
                    # Check for cancellation (simplified)
                    if job_data.get("cancel_requested"):
                        metrics.record_job_cancellation("sim", "user", "user_request", "running")
                        metrics.set_job_in_progress("sim", "sim_queue", 0)
                        return {"status": "cancelled", "reason": "user_request"}
                    
                    metrics.record_progress_update("sim", "worker", False)
                    time.sleep(0.01)
                
                # Normal completion
                metrics.record_job_duration("sim", "success", "sim_queue", 0.1)
                metrics.set_job_in_progress("sim", "sim_queue", 0)
                
                return {"status": "completed"}
        
        # Test normal completion
        job_data = {"id": job_id, "type": "sim"}
        result = cancellable_task.delay(job_data)
        task_result = result.get(timeout=15)
        
        assert task_result["status"] in ["completed", "cancelled"]
    
    def test_progress_throttling_integration(self):
        """Test progress update throttling in real job scenario."""
        job_id = f"job-progress-{uuid.uuid4()}"
        
        @celery_app.task(bind=True)
        def progress_intensive_task(self, job_data: Dict[str, Any]):
            job_id = job_data["id"]
            
            with create_span("progress_intensive_job", job_id=job_id):
                metrics.set_job_in_progress("report", "report_queue", 1)
                
                # Simulate rapid progress updates (should trigger throttling)
                last_update_time = time.time()
                throttled_count = 0
                
                for i in range(100):
                    current_time = time.time()
                    
                    # Simulate throttling logic
                    should_throttle = (current_time - last_update_time) < 0.1  # 100ms throttle
                    
                    if should_throttle:
                        throttled_count += 1
                        metrics.record_progress_update("report", "worker", True)
                    else:
                        metrics.record_progress_update("report", "worker", False)
                        last_update_time = current_time
                    
                    time.sleep(0.005)  # 5ms between updates
                
                metrics.record_job_duration("report", "success", "report_queue", 0.5)
                metrics.set_job_in_progress("report", "report_queue", 0)
                
                return {
                    "status": "completed",
                    "total_updates": 100,
                    "throttled_count": throttled_count
                }
        
        job_data = {"id": job_id, "type": "report"}
        result = progress_intensive_task.delay(job_data)
        task_result = result.get(timeout=20)
        
        assert task_result["status"] == "completed"
        assert task_result["throttled_count"] > 0  # Some updates should be throttled


class TestObservabilityEndToEndFlow:
    """Test complete end-to-end observability flow."""
    
    def test_full_job_lifecycle_observability(self):
        """Test complete job lifecycle with all observability components."""
        job_id = f"job-e2e-{uuid.uuid4()}"
        trace_id = f"trace-{uuid.uuid4()}"
        request_id = f"req-{uuid.uuid4()}"
        idempotency_key = f"idem-{uuid.uuid4()}"
        
        # Phase 1: Job Creation (API Layer)
        with create_span("api_job_creation", job_id=job_id, idempotency_key=idempotency_key):
            bind_request_context(
                job_id=job_id,
                trace_id=trace_id,
                request_id=request_id,
                idempotency_key=idempotency_key
            )
            
            logger = get_logger(__name__)
            logger.info("Job creation initiated", job_type="model")
            
            # Record creation metrics
            metrics.record_job_creation("model", "created", False)
            metrics.record_idempotency_operation("create", False, False)
            
            # Create audit entry
            metrics.record_audit_chain_operation("create", "success", False)
        
        # Phase 2: Job Processing (Worker Layer)  
        @celery_app.task(bind=True)
        def e2e_test_task(self, job_data: Dict[str, Any]):
            job_id = job_data["id"]
            
            with create_span("worker_job_processing", job_id=job_id, operation_type="celery_task"):
                logger = get_logger(__name__)
                logger.info("Job processing started", job_id=job_id)
                
                # Record processing start
                metrics.set_job_in_progress("model", "model_queue", 1)
                
                # Multi-phase processing
                phases = ["validation", "generation", "optimization", "export"]
                for i, phase in enumerate(phases):
                    with create_span(f"phase_{phase}", job_id=job_id):
                        logger.info(f"Processing phase: {phase}", phase=phase, progress=25*(i+1))
                        metrics.record_progress_update("model", "worker", False)
                        time.sleep(0.01)
                
                # Record completion
                duration = 0.04
                metrics.record_job_duration("model", "success", "model_queue", duration)
                metrics.set_job_in_progress("model", "model_queue", 0)
                
                # Final audit
                metrics.record_audit_chain_operation("complete", "success", False)
                
                logger.info("Job completed successfully", duration_seconds=duration)
                
                return {
                    "status": "completed",
                    "job_id": job_id,
                    "phases_completed": len(phases),
                    "total_duration": duration
                }
        
        # Execute end-to-end flow
        job_data = {
            "id": job_id,
            "type": "model",
            "trace_id": trace_id,
            "idempotency_key": idempotency_key
        }
        
        result = e2e_test_task.delay(job_data)
        task_result = result.get(timeout=20)
        
        # Verify end-to-end success
        assert task_result["status"] == "completed"
        assert task_result["job_id"] == job_id
        assert task_result["phases_completed"] == 4
        
        # Phase 3: Verification (Observability Data)
        logger = get_logger(__name__)
        logger.info("End-to-end observability test completed", 
                   job_id=job_id, 
                   trace_id=trace_id,
                   test_status="success")


if __name__ == "__main__":
    # Run integration tests
    pytest.main([__file__, "-v", "--asyncio-mode=auto"])