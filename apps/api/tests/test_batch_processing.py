"""
Comprehensive tests for batch processing functionality.

Tests cover:
- Batch job creation and management
- Quality check execution
- Workflow automation
- Retry logic and error recovery
- Circuit breaker functionality
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from sqlalchemy.orm import Session

from app.api.v2.batch_processing import router
from app.models.batch_processing import (
    BatchJob,
    BatchJobStatus,
    BatchOperationType,
    QualityCheck,
    QualityCheckType,
    WorkflowExecution,
    WorkflowStepStatus,
)
from app.models.model import Model
from app.models.user import User
from app.services.batch_operations import BatchOperationsService
from app.services.batch_processing_engine import (
    BatchProcessingEngine,
    CircuitBreaker,
    CircuitBreakerState,
    RetryStrategy,
)
from app.services.workflow_automation import (
    WorkflowAutomation,
    WorkflowStep,
    WorkflowStepType,
    WorkflowTemplate,
)


@pytest.fixture
def test_user(db: Session) -> User:
    """Create a test user."""
    user = User(
        email="test@example.com",
        full_name="Test User",
        role="user",
        is_active=True
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def test_models(db: Session, test_user: User) -> list[Model]:
    """Create test models."""
    models = []
    for i in range(5):
        model = Model(
            user_id=test_user.id,
            name=f"Test Model {i}",
            description=f"Test model {i} description",
            file_path=f"/models/test_{i}.step"
        )
        db.add(model)
        models.append(model)
    db.commit()
    return models


@pytest.fixture
def batch_job(db: Session, test_user: User, test_models: list[Model]) -> BatchJob:
    """Create a test batch job."""
    job = BatchJob(
        user_id=test_user.id,
        name="Test Batch Job",
        description="Test batch job description",
        operation_type=BatchOperationType.QUALITY_CHECK,
        input_models=[m.id for m in test_models],
        total_items=len(test_models)
    )
    db.add(job)
    db.commit()
    return job


@pytest.fixture
def batch_engine(db: Session) -> BatchProcessingEngine:
    """Create batch processing engine."""
    return BatchProcessingEngine(db)


@pytest.fixture
def workflow_automation(db: Session) -> WorkflowAutomation:
    """Create workflow automation service."""
    return WorkflowAutomation(db)


class TestBatchJobManagement:
    """Test batch job creation and management."""
    
    def test_create_batch_job(self, db: Session, test_user: User, test_models: list[Model]):
        """Test creating a new batch job."""
        job = BatchJob(
            user_id=test_user.id,
            name="Quality Check Job",
            operation_type=BatchOperationType.QUALITY_CHECK,
            input_models=[m.id for m in test_models],
            config={"check_types": ["geometry_validation"]},
            max_retries=3,
            retry_delay_seconds=60
        )
        db.add(job)
        db.commit()
        
        assert job.id is not None
        assert job.status == BatchJobStatus.PENDING
        assert job.total_items == len(test_models)
        assert job.processed_items == 0
        assert job.retry_count == 0
    
    def test_update_batch_job_status(self, db: Session, batch_job: BatchJob):
        """Test updating batch job status."""
        batch_job.status = BatchJobStatus.RUNNING
        batch_job.processed_items = 2
        batch_job.failed_items = 1
        db.commit()
        
        assert batch_job.status == BatchJobStatus.RUNNING
        assert batch_job.processed_items == 2
        assert batch_job.failed_items == 1
        assert batch_job.success_rate == 50.0  # 1 success out of 2 processed
    
    def test_batch_job_progress_calculation(self, batch_job: BatchJob):
        """Test progress percentage calculation."""
        assert batch_job.progress_percentage == 0.0
        
        batch_job.processed_items = 2
        batch_job.total_items = 5
        assert batch_job.progress_percentage == 40.0
        
        batch_job.processed_items = 5
        assert batch_job.progress_percentage == 100.0
    
    def test_batch_job_duration_calculation(self, db: Session, batch_job: BatchJob):
        """Test automatic duration calculation."""
        batch_job.start_time = datetime.now(timezone.utc)
        batch_job.end_time = batch_job.start_time + timedelta(seconds=120)
        db.commit()
        
        assert batch_job.duration_seconds is not None
        assert float(batch_job.duration_seconds) == pytest.approx(120.0, rel=0.1)


class TestQualityChecks:
    """Test quality check functionality."""
    
    @pytest.mark.asyncio
    async def test_execute_quality_check(
        self,
        db: Session,
        batch_job: BatchJob,
        test_models: list[Model]
    ):
        """Test executing quality checks."""
        service = BatchOperationsService(db)
        
        # Mock the FreeCAD service
        with patch.object(service, '_download_model_file') as mock_download:
            mock_download.return_value = "/tmp/test_model.step"
            
            with patch.object(service.freecad_service, 'execute_script') as mock_execute:
                mock_execute.return_value = {
                    "passed": True,
                    "score": 95,
                    "findings": [],
                    "metrics": {"valid_objects": 10}
                }
                
                quality_check = QualityCheck(
                    batch_job_id=batch_job.id,
                    model_id=test_models[0].id,
                    check_type=QualityCheckType.GEOMETRY_VALIDATION
                )
                db.add(quality_check)
                db.commit()
                
                result = await service.execute_quality_check(
                    quality_check,
                    test_models[0],
                    QualityCheckType.GEOMETRY_VALIDATION
                )
                
                assert result["passed"] is True
                assert result["score"] == 95
                assert len(result["findings"]) == 0
    
    def test_quality_check_results_aggregation(
        self,
        db: Session,
        batch_job: BatchJob,
        test_models: list[Model]
    ):
        """Test aggregating quality check results."""
        # Create quality checks with varied results
        checks = []
        for i, model in enumerate(test_models):
            check = QualityCheck(
                batch_job_id=batch_job.id,
                model_id=model.id,
                check_type=QualityCheckType.GEOMETRY_VALIDATION,
                status=BatchJobStatus.COMPLETED,
                passed=(i % 2 == 0),  # Alternate pass/fail
                score=80 + i * 5,
                issues_found=i,
                issues_fixed=i // 2
            )
            checks.append(check)
        
        db.add_all(checks)
        db.commit()
        
        # Query and verify results
        passed_checks = db.query(QualityCheck).filter(
            QualityCheck.batch_job_id == batch_job.id,
            QualityCheck.passed == True
        ).count()
        
        assert passed_checks == 3  # Models 0, 2, 4 passed
        
        avg_score = db.query(QualityCheck).filter(
            QualityCheck.batch_job_id == batch_job.id
        ).with_entities(db.func.avg(QualityCheck.score)).scalar()
        
        assert float(avg_score) == pytest.approx(90.0, rel=0.1)


class TestBatchProcessingEngine:
    """Test batch processing engine functionality."""
    
    def test_circuit_breaker_functionality(self):
        """Test circuit breaker state transitions."""
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        
        assert breaker.state == CircuitBreakerState.CLOSED
        
        # Simulate failures
        for i in range(3):
            try:
                breaker.call(lambda: (_ for _ in ()).throw(Exception("Test failure")))
            except Exception:
                pass
        
        assert breaker.state == CircuitBreakerState.OPEN
        assert breaker.failure_count == 3
        
        # Try calling when open
        with pytest.raises(Exception, match="Circuit breaker is OPEN"):
            breaker.call(lambda: "test")
        
        # Simulate recovery after timeout
        breaker.last_failure_time = datetime.now(timezone.utc) - timedelta(seconds=61)
        breaker.call(lambda: "success")
        
        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.failure_count == 0
    
    def test_retry_delay_calculation(self, batch_engine: BatchProcessingEngine):
        """Test retry delay calculation with different strategies."""
        # Exponential backoff
        delay = batch_engine._calculate_retry_delay(2, RetryStrategy.EXPONENTIAL_BACKOFF, 10)
        assert 30 <= delay <= 50  # 10 * 2^2 * jitter (0.75-1.25)
        
        # Linear backoff
        delay = batch_engine._calculate_retry_delay(2, RetryStrategy.LINEAR_BACKOFF, 10)
        assert 22.5 <= delay <= 37.5  # 10 * 3 * jitter
        
        # Fixed delay
        delay = batch_engine._calculate_retry_delay(5, RetryStrategy.FIXED_DELAY, 10)
        assert 7.5 <= delay <= 12.5  # 10 * jitter
    
    @pytest.mark.asyncio
    async def test_execute_batch_job_with_retry(
        self,
        db: Session,
        batch_engine: BatchProcessingEngine,
        batch_job: BatchJob,
        test_user: User
    ):
        """Test batch job execution with retry logic."""
        batch_job.max_retries = 2
        
        with patch.object(batch_engine.batch_operations, 'execute_batch_operation') as mock_execute:
            # First two calls fail, third succeeds
            mock_execute.side_effect = [
                Exception("First failure"),
                Exception("Second failure"),
                {"status": "success", "processed": 5}
            ]
            
            result = await batch_engine._execute_with_retry(
                batch_job, test_user, {"retry_strategy": RetryStrategy.FIXED_DELAY}
            )
            
            assert result["status"] == "success"
            assert batch_job.retry_count == 2
            assert mock_execute.call_count == 3
    
    @pytest.mark.asyncio
    async def test_parallel_batch_execution(
        self,
        db: Session,
        batch_engine: BatchProcessingEngine,
        test_user: User
    ):
        """Test parallel execution of multiple batch jobs."""
        jobs = []
        for i in range(3):
            job = BatchJob(
                user_id=test_user.id,
                name=f"Parallel Job {i}",
                operation_type=BatchOperationType.MESH_OPTIMIZATION,
                input_models=[i],
                total_items=1
            )
            db.add(job)
            jobs.append(job)
        db.commit()
        
        with patch.object(batch_engine, 'execute_batch_job') as mock_execute:
            mock_execute.return_value = {"status": "success"}
            
            results = await batch_engine.execute_parallel_batch(jobs, test_user, max_concurrent=2)
            
            assert len(results) == 3
            assert all(r["status"] == "success" for r in results)
    
    def test_batch_job_cancellation(
        self,
        db: Session,
        batch_engine: BatchProcessingEngine,
        batch_job: BatchJob
    ):
        """Test cancelling a batch job."""
        batch_job.config["celery_task_id"] = "test-task-123"
        batch_job.status = BatchJobStatus.RUNNING
        db.commit()
        
        with patch('app.core.celery_app.celery_app.control.revoke') as mock_revoke:
            success = batch_engine.cancel_batch_job(batch_job)
            
            assert success is True
            assert batch_job.status == BatchJobStatus.CANCELLED
            assert batch_job.end_time is not None
            mock_revoke.assert_called_once_with("test-task-123", terminate=True)


class TestWorkflowAutomation:
    """Test workflow automation functionality."""
    
    def test_workflow_template_instantiation(self, workflow_automation: WorkflowAutomation):
        """Test creating workflow instance from template."""
        template = workflow_automation.templates["quality_assurance"]
        
        steps = template.instantiate({"threshold": 80})
        
        assert len(steps) == 4
        assert steps[0].name == "geometry_check"
        assert steps[0].action == "quality_check"
        assert steps[2].step_type == WorkflowStepType.CONDITIONAL
    
    @pytest.mark.asyncio
    async def test_workflow_execution(
        self,
        db: Session,
        workflow_automation: WorkflowAutomation,
        batch_job: BatchJob,
        test_user: User
    ):
        """Test executing a workflow."""
        workflow_execution = WorkflowExecution(
            batch_job_id=batch_job.id,
            workflow_name="Test Workflow",
            workflow_version="1.0",
            parameters={"test_param": "value"}
        )
        db.add(workflow_execution)
        db.commit()
        
        custom_steps = [
            {
                "name": "step1",
                "type": "sequential",
                "action": "quality_check",
                "parameters": {"check_type": "geometry_validation"}
            },
            {
                "name": "step2",
                "type": "sequential",
                "action": "validate_model",
                "parameters": {"validation_type": "final"}
            }
        ]
        
        with patch.object(workflow_automation, '_execute_quality_check') as mock_qc:
            mock_qc.return_value = {"passed": True, "score": 90}
            
            with patch.object(workflow_automation, '_execute_model_validation') as mock_validate:
                mock_validate.return_value = {"status": "passed"}
                
                result = await workflow_automation.execute_workflow(
                    workflow_execution,
                    batch_job,
                    test_user,
                    custom_steps=custom_steps
                )
                
                assert result["status"] == "completed"
                assert result["completed_steps"] == 2
                assert result["failed_steps"] == 0
                assert workflow_execution.status == WorkflowStepStatus.COMPLETED
    
    @pytest.mark.asyncio
    async def test_parallel_workflow_steps(
        self,
        db: Session,
        workflow_automation: WorkflowAutomation,
        batch_job: BatchJob,
        test_user: User
    ):
        """Test parallel execution of workflow steps."""
        step = WorkflowStep(
            name="parallel_operations",
            step_type=WorkflowStepType.PARALLEL,
            parameters={
                "steps": [
                    {"action": "mesh_optimization", "config": {}},
                    {"action": "feature_cleanup", "config": {}},
                    {"action": "compress_model", "config": {}}
                ],
                "parallel_limit": 2,
                "timeout": 60
            }
        )
        
        context = {
            "batch_job": batch_job,
            "user": test_user,
            "results": {}
        }
        
        with patch.object(workflow_automation, '_execute_sequential_step') as mock_execute:
            mock_execute.return_value = {"status": "success"}
            
            result = await workflow_automation._execute_parallel_step(step, context)
            
            assert result["parallel_execution"] is True
            assert len(result["successful"]) == 3
            assert len(result["failed"]) == 0
            assert result["total"] == 3
    
    def test_workflow_condition_evaluation(self, workflow_automation: WorkflowAutomation):
        """Test workflow condition evaluation."""
        step = WorkflowStep(
            name="conditional_step",
            step_type=WorkflowStepType.CONDITIONAL,
            condition={
                "field": "results.quality_check.score",
                "operator": "greater_than",
                "value": 80
            }
        )
        
        context = {
            "results": {
                "quality_check": {"score": 85}
            }
        }
        
        should_execute = workflow_automation._should_execute_step(step, context)
        assert should_execute is True
        
        context["results"]["quality_check"]["score"] = 75
        should_execute = workflow_automation._should_execute_step(step, context)
        assert should_execute is False


class TestBatchProcessingAPI:
    """Test batch processing API endpoints."""
    
    @pytest.mark.asyncio
    async def test_create_batch_job_endpoint(
        self,
        client,
        test_user: User,
        test_models: list[Model],
        db: Session
    ):
        """Test creating a batch job via API."""
        with patch('app.api.v2.batch_processing.get_current_user', return_value=test_user):
            response = client.post(
                "/api/v2/batch/jobs",
                json={
                    "name": "API Test Job",
                    "description": "Test job from API",
                    "operation_type": "quality_check",
                    "input_models": [m.id for m in test_models],
                    "config": {"check_types": ["geometry_validation"]},
                    "max_retries": 3
                }
            )
        
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == "API Test Job"
        assert data["status"] == "pending"
        assert data["total_items"] == len(test_models)
    
    @pytest.mark.asyncio
    async def test_list_batch_jobs_endpoint(
        self,
        client,
        test_user: User,
        batch_job: BatchJob,
        db: Session
    ):
        """Test listing batch jobs via API."""
        with patch('app.api.v2.batch_processing.get_current_user', return_value=test_user):
            response = client.get("/api/v2/batch/jobs")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) >= 1
        assert any(job["id"] == batch_job.id for job in data)
    
    @pytest.mark.asyncio
    async def test_cancel_batch_job_endpoint(
        self,
        client,
        test_user: User,
        batch_job: BatchJob,
        db: Session
    ):
        """Test cancelling a batch job via API."""
        batch_job.status = BatchJobStatus.RUNNING
        batch_job.config["celery_task_id"] = "test-task"
        db.commit()
        
        with patch('app.api.v2.batch_processing.get_current_user', return_value=test_user):
            with patch('app.core.celery_app.celery_app.control.revoke'):
                response = client.post(f"/api/v2/batch/jobs/{batch_job.id}/cancel")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "iptal edildi" in data["message"]
    
    @pytest.mark.asyncio
    async def test_create_quality_checks_endpoint(
        self,
        client,
        test_user: User,
        test_models: list[Model],
        db: Session
    ):
        """Test creating quality checks via API."""
        with patch('app.api.v2.batch_processing.get_current_user', return_value=test_user):
            response = client.post(
                "/api/v2/batch/quality-checks",
                json={
                    "model_ids": [m.id for m in test_models[:2]],
                    "check_types": ["geometry_validation", "topology_check"],
                    "auto_fix": True,
                    "config": {"threshold": 80}
                }
            )
        
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert "Kalite Kontrolleri" in data["name"]
        assert data["operation_type"] == "quality_check"
    
    @pytest.mark.asyncio
    async def test_create_workflow_execution_endpoint(
        self,
        client,
        test_user: User,
        test_models: list[Model],
        db: Session
    ):
        """Test creating a workflow execution via API."""
        with patch('app.api.v2.batch_processing.get_current_user', return_value=test_user):
            with patch('app.services.workflow_automation.execute_workflow_async.apply_async') as mock_task:
                mock_task.return_value.id = "workflow-task-123"
                
                response = client.post(
                    "/api/v2/batch/workflows",
                    json={
                        "workflow_name": "Quality Assurance",
                        "template_name": "quality_assurance",
                        "input_models": [test_models[0].id],
                        "parameters": {"threshold": 85}
                    }
                )
        
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["workflow_name"] == "Quality Assurance"
        assert data["status"] == "pending"


class TestErrorRecovery:
    """Test error recovery and resilience features."""
    
    @pytest.mark.asyncio
    async def test_recover_failed_jobs(
        self,
        db: Session,
        batch_engine: BatchProcessingEngine,
        test_user: User
    ):
        """Test recovering failed batch jobs."""
        # Create failed jobs
        failed_jobs = []
        for i in range(3):
            job = BatchJob(
                user_id=test_user.id,
                name=f"Failed Job {i}",
                operation_type=BatchOperationType.QUALITY_CHECK,
                status=BatchJobStatus.FAILED,
                input_models=[i],
                retry_count=1,
                max_retries=3,
                created_at=datetime.now(timezone.utc) - timedelta(hours=i)
            )
            db.add(job)
            failed_jobs.append(job)
        db.commit()
        
        with patch.object(batch_engine, 'schedule_batch_job') as mock_schedule:
            mock_schedule.return_value = "recovery-task-123"
            
            recovered = await batch_engine.recover_failed_jobs(
                time_window_hours=24,
                max_jobs=2
            )
            
            assert len(recovered) == 2
            assert all(j.status == BatchJobStatus.PENDING for j in recovered)
            assert mock_schedule.call_count == 2
    
    def test_batch_job_pause_resume(
        self,
        db: Session,
        batch_engine: BatchProcessingEngine,
        batch_job: BatchJob,
        test_user: User
    ):
        """Test pausing and resuming batch jobs."""
        batch_job.status = BatchJobStatus.RUNNING
        db.commit()
        
        # Pause the job
        success = batch_engine.pause_batch_job(batch_job)
        assert success is True
        assert batch_job.status == BatchJobStatus.PAUSED
        assert "paused_at" in batch_job.config
        
        # Resume the job
        with patch.object(batch_engine, 'schedule_batch_job') as mock_schedule:
            mock_schedule.return_value = "resumed-task-123"
            
            task_id = batch_engine.resume_batch_job(batch_job, test_user)
            
            assert task_id == "resumed-task-123"
            assert batch_job.status == BatchJobStatus.PENDING
            assert "paused_at" not in batch_job.config