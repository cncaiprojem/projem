"""
Tests for Batch Processing and Automation Framework (Task 7.23)

Tests cover:
- Batch processing engine
- Workflow automation
- Scheduled operations
- Batch operations library
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from freezegun import freeze_time

from app.models.batch_processing import (
    BatchJob,
    BatchJobItem,
    WorkflowDefinition,
    WorkflowExecution,
    ScheduledJob
)
from app.services.batch_processing_engine import (
    BatchItem,
    BatchOptions,
    BatchProcessingEngine,
    BatchStatus,
    ProcessingStrategy
)
from app.services.workflow_automation import (
    Workflow,
    WorkflowEngine,
    WorkflowStep,
    StepType,
    ErrorHandling,
    ExecutionOptions,
    WorkflowStatus
)
from app.services.scheduled_operations import (
    ScheduledOperations,
    ScheduledJobConfig,
    JobTriggerType,
    OptimizationType
)
from app.services.batch_operations import (
    BatchOperations,
    ParameterSet,
    QualityCheck,
    QualityCheckType
)


class TestBatchProcessingEngine:
    """Test batch processing engine functionality."""
    
    @pytest.fixture
    def batch_engine(self):
        """Create batch processing engine instance."""
        return BatchProcessingEngine()
    
    @pytest.mark.asyncio
    async def test_process_batch_sequential(self, batch_engine):
        """Test sequential batch processing."""
        # Prepare test items
        items = [
            BatchItem(data={"value": i}) for i in range(5)
        ]
        
        # Define processing operation
        async def process_item(data: Dict[str, Any]) -> Dict[str, Any]:
            await asyncio.sleep(0.01)  # Simulate work
            return {"result": data["value"] * 2}
        
        # Process batch
        options = BatchOptions(strategy=ProcessingStrategy.SEQUENTIAL)
        result = await batch_engine.process_batch(items, process_item, options)
        
        # Verify results
        assert result.status == BatchStatus.COMPLETED
        assert result.total_items == 5
        assert result.successful_items == 5
        assert result.failed_items == 0
        assert len(result.results) == 5
        assert all(r["result"] == i * 2 for i, r in enumerate(result.results))
    
    @pytest.mark.asyncio
    async def test_process_batch_parallel(self, batch_engine):
        """Test parallel batch processing."""
        # Prepare test items
        items = [
            BatchItem(data={"value": i}) for i in range(10)
        ]
        
        # Define processing operation
        async def process_item(data: Dict[str, Any]) -> Dict[str, Any]:
            await asyncio.sleep(0.01)
            return {"result": data["value"] ** 2}
        
        # Process batch
        options = BatchOptions(
            strategy=ProcessingStrategy.PARALLEL,
            max_workers=4
        )
        result = await batch_engine.process_batch(items, process_item, options)
        
        # Verify results
        assert result.status == BatchStatus.COMPLETED
        assert result.total_items == 10
        assert result.successful_items == 10
        assert result.failed_items == 0
        
        # Check parallelism by verifying duration
        # Parallel should be faster than sequential
        assert result.duration_ms < 100  # Should complete in less than 100ms
    
    @pytest.mark.asyncio
    async def test_process_batch_with_errors(self, batch_engine):
        """Test batch processing with error handling."""
        # Prepare test items
        items = [
            BatchItem(data={"value": i}) for i in range(5)
        ]
        
        # Define operation that fails on even numbers
        async def process_item(data: Dict[str, Any]) -> Dict[str, Any]:
            if data["value"] % 2 == 0:
                raise ValueError(f"Çift sayı hatası: {data['value']}")
            return {"result": data["value"] * 2}
        
        # Process batch with continue_on_error
        options = BatchOptions(
            strategy=ProcessingStrategy.SEQUENTIAL,
            continue_on_error=True
        )
        result = await batch_engine.process_batch(items, process_item, options)
        
        # Verify results
        assert result.status == BatchStatus.COMPLETED
        assert result.total_items == 5
        assert result.successful_items == 2  # Only odd numbers succeed (1, 3)
        assert result.failed_items == 3  # Even numbers fail (0, 2, 4)
        assert len(result.errors) > 0
    
    @pytest.mark.asyncio
    async def test_process_batch_with_retry(self, batch_engine):
        """Test batch processing with retry logic."""
        attempt_counts = {}
        
        # Define operation that fails first time
        async def process_item(data: Dict[str, Any]) -> Dict[str, Any]:
            item_id = data["value"]
            attempt_counts[item_id] = attempt_counts.get(item_id, 0) + 1
            
            if attempt_counts[item_id] < 2:
                raise ValueError(f"İlk deneme başarısız: {item_id}")
            
            return {"result": item_id * 2, "attempts": attempt_counts[item_id]}
        
        # Prepare test items
        items = [
            BatchItem(data={"value": i}) for i in range(3)
        ]
        
        # Process batch with retry
        options = BatchOptions(
            strategy=ProcessingStrategy.SEQUENTIAL,
            max_retries=2,
            retry_delay_ms=10
        )
        result = await batch_engine.process_batch(items, process_item, options)
        
        # Verify results
        assert result.status == BatchStatus.COMPLETED
        assert result.successful_items == 3
        assert result.failed_items == 0
        # Each item should have been attempted twice
        assert all(r["attempts"] == 2 for r in result.results)
    
    @pytest.mark.asyncio
    async def test_process_batch_chunked(self, batch_engine):
        """Test chunked batch processing."""
        # Prepare test items
        items = [
            BatchItem(data={"value": i}) for i in range(20)
        ]
        
        # Define processing operation
        async def process_item(data: Dict[str, Any]) -> Dict[str, Any]:
            return {"result": data["value"] + 100}
        
        # Process batch in chunks
        options = BatchOptions(
            strategy=ProcessingStrategy.CHUNKED,
            chunk_size=5,
            max_workers=2
        )
        result = await batch_engine.process_batch(items, process_item, options)
        
        # Verify results
        assert result.status == BatchStatus.COMPLETED
        assert result.total_items == 20
        assert result.successful_items == 20
        assert len(result.results) == 20
        assert all(r["result"] == i + 100 for i, r in enumerate(result.results))
    
    @pytest.mark.asyncio
    async def test_process_batch_adaptive(self, batch_engine):
        """Test adaptive batch processing."""
        # Prepare test items
        items = [
            BatchItem(data={"value": i}) for i in range(8)
        ]
        
        # Define processing operation
        async def process_item(data: Dict[str, Any]) -> Dict[str, Any]:
            return {"result": data["value"] * 3}
        
        # Process batch with adaptive strategy
        options = BatchOptions(
            strategy=ProcessingStrategy.ADAPTIVE
        )
        result = await batch_engine.process_batch(items, process_item, options)
        
        # Verify results
        assert result.status == BatchStatus.COMPLETED
        assert result.total_items == 8
        assert result.successful_items == 8
        # Adaptive should automatically determine optimal workers


class TestWorkflowAutomation:
    """Test workflow automation functionality."""
    
    @pytest.fixture
    def workflow_engine(self):
        """Create workflow engine instance."""
        engine = WorkflowEngine()
        
        # Register test actions
        async def process_data(params: Dict[str, Any]) -> Dict[str, Any]:
            return {"processed": params.get("input", 0) * 2}
        
        async def validate_data(params: Dict[str, Any]) -> bool:
            return params.get("value", 0) > 0
        
        engine.step_executor.register_action("process_data", process_data)
        engine.step_executor.register_action("validate_data", validate_data)
        
        return engine
    
    @pytest.mark.asyncio
    async def test_define_workflow(self, workflow_engine):
        """Test workflow definition and validation."""
        # Define workflow
        workflow = Workflow(
            name="Test İş Akışı",
            description="Test için basit iş akışı",
            steps=[
                WorkflowStep(
                    id="step1",
                    name="Veri İşleme",
                    type=StepType.ACTION,
                    action="process_data",
                    parameters={"input": 5}
                ),
                WorkflowStep(
                    id="step2",
                    name="Doğrulama",
                    type=StepType.ACTION,
                    action="validate_data",
                    dependencies=["step1"]
                )
            ]
        )
        
        # Define workflow
        result = await workflow_engine.define_workflow(workflow)
        
        # Verify
        assert result.id == workflow.id
        assert result.name == workflow.name
        assert len(result.steps) == 2
        assert workflow.id in workflow_engine.workflows
    
    @pytest.mark.asyncio
    async def test_execute_workflow(self, workflow_engine):
        """Test workflow execution."""
        # Define workflow
        workflow = Workflow(
            name="Yürütme Test İş Akışı",
            steps=[
                WorkflowStep(
                    id="step1",
                    name="İşlem 1",
                    type=StepType.ACTION,
                    action="process_data",
                    parameters={"input": 10}
                ),
                WorkflowStep(
                    id="step2",
                    name="İşlem 2",
                    type=StepType.ACTION,
                    action="process_data",
                    parameters={"input": 20},
                    dependencies=["step1"]
                )
            ]
        )
        
        await workflow_engine.define_workflow(workflow)
        
        # Execute workflow
        execution = await workflow_engine.execute_workflow(
            workflow.id,
            {"initial_value": 100},
            ExecutionOptions()
        )
        
        # Verify execution
        assert execution.status == WorkflowStatus.COMPLETED
        assert execution.workflow_id == workflow.id
        assert len(execution.step_results) == 2
        assert execution.step_results["step1"].status.value == "completed"
        assert execution.step_results["step2"].status.value == "completed"
    
    @pytest.mark.asyncio
    async def test_workflow_with_conditions(self, workflow_engine):
        """Test workflow with conditional steps."""
        # Define workflow with conditions
        workflow = Workflow(
            name="Koşullu İş Akışı",
            steps=[
                WorkflowStep(
                    id="step1",
                    name="Değer Ayarla",
                    type=StepType.ACTION,
                    action="process_data",
                    parameters={"input": 5}
                ),
                WorkflowStep(
                    id="step2",
                    name="Koşullu İşlem",
                    type=StepType.ACTION,
                    action="process_data",
                    conditions=[
                        {"field": "value", "operator": "gt", "value": 10}
                    ],
                    dependencies=["step1"]
                )
            ]
        )
        
        await workflow_engine.define_workflow(workflow)
        
        # Execute with low value (condition not met)
        execution = await workflow_engine.execute_workflow(
            workflow.id,
            {"value": 5},
            ExecutionOptions()
        )
        
        # Step 2 should be skipped
        assert execution.status == WorkflowStatus.COMPLETED
        assert execution.step_results["step1"].status.value == "completed"
        assert execution.step_results["step2"].status.value == "skipped"
    
    @pytest.mark.asyncio
    async def test_workflow_error_handling(self, workflow_engine):
        """Test workflow error handling."""
        # Register failing action
        async def failing_action(params: Dict[str, Any]) -> None:
            raise ValueError("İşlem başarısız")
        
        workflow_engine.step_executor.register_action("failing_action", failing_action)
        
        # Define workflow with error handling
        workflow = Workflow(
            name="Hata Yönetimi İş Akışı",
            steps=[
                WorkflowStep(
                    id="step1",
                    name="Başarısız İşlem",
                    type=StepType.ACTION,
                    action="failing_action",
                    error_handling=ErrorHandling.SKIP
                ),
                WorkflowStep(
                    id="step2",
                    name="Sonraki İşlem",
                    type=StepType.ACTION,
                    action="process_data",
                    parameters={"input": 10}
                )
            ]
        )
        
        await workflow_engine.define_workflow(workflow)
        
        # Execute workflow
        execution = await workflow_engine.execute_workflow(
            workflow.id,
            {},
            ExecutionOptions()
        )
        
        # Workflow should complete despite error
        assert execution.status == WorkflowStatus.COMPLETED
        assert execution.step_results["step1"].status.value == "skipped"
        assert execution.step_results["step2"].status.value == "completed"
    
    @pytest.mark.asyncio
    async def test_workflow_dag_validation(self, workflow_engine):
        """Test workflow DAG validation for cycles."""
        # Define workflow with cycle
        workflow = Workflow(
            name="Döngülü İş Akışı",
            steps=[
                WorkflowStep(
                    id="step1",
                    name="Adım 1",
                    dependencies=["step3"]
                ),
                WorkflowStep(
                    id="step2",
                    name="Adım 2",
                    dependencies=["step1"]
                ),
                WorkflowStep(
                    id="step3",
                    name="Adım 3",
                    dependencies=["step2"]
                )
            ]
        )
        
        # Should raise validation error
        with pytest.raises(Exception, match="döngü"):
            await workflow_engine.define_workflow(workflow)


class TestScheduledOperations:
    """Test scheduled operations functionality."""
    
    @pytest.fixture
    def scheduler(self):
        """Create scheduler instance."""
        scheduler = ScheduledOperations()
        scheduler.start()
        yield scheduler
        scheduler.shutdown(wait=False)
    
    def test_schedule_job(self, scheduler):
        """Test job scheduling."""
        # Create job config
        config = ScheduledJobConfig(
            name="Test İşi",
            description="Test için zamanlanmış iş",
            trigger_type=JobTriggerType.INTERVAL,
            trigger_args={"seconds": 60},
            function="optimize_all_models"
        )
        
        # Schedule job
        job_id = scheduler.schedule_job(config)
        
        # Verify job was scheduled
        assert job_id is not None
        jobs = scheduler.get_jobs()
        assert any(j["id"] == job_id for j in jobs)
    
    def test_schedule_cron_job(self, scheduler):
        """Test cron job scheduling."""
        # Create cron job
        config = ScheduledJobConfig(
            job_id="daily_report",
            name="Günlük Rapor",
            trigger_type=JobTriggerType.CRON,
            trigger_args={"hour": 6, "minute": 0},
            function="generate_daily_report"
        )
        
        # Schedule job
        job_id = scheduler.schedule_job(config)
        
        # Verify
        assert job_id == "daily_report"
        jobs = scheduler.get_jobs()
        job = next((j for j in jobs if j["id"] == job_id), None)
        assert job is not None
        assert "cron" in job["trigger"].lower()
    
    def test_pause_resume_job(self, scheduler):
        """Test pausing and resuming jobs."""
        # Schedule a job
        config = ScheduledJobConfig(
            job_id="test_pause",
            name="Duraklatma Testi",
            trigger_type=JobTriggerType.INTERVAL,
            trigger_args={"minutes": 5},
            function="cleanup_old_files"
        )
        
        job_id = scheduler.schedule_job(config)
        
        # Pause job
        assert scheduler.pause_job(job_id) is True
        
        # Resume job
        assert scheduler.resume_job(job_id) is True
    
    def test_remove_job(self, scheduler):
        """Test job removal."""
        # Schedule a job
        config = ScheduledJobConfig(
            job_id="test_remove",
            name="Kaldırma Testi",
            trigger_type=JobTriggerType.INTERVAL,
            trigger_args={"hours": 1},
            function="backup_database"
        )
        
        job_id = scheduler.schedule_job(config)
        
        # Remove job
        assert scheduler.remove_job(job_id) is True
        
        # Verify job was removed
        jobs = scheduler.get_jobs()
        assert not any(j["id"] == job_id for j in jobs)
    
    @pytest.mark.asyncio
    async def test_optimize_all_models(self, scheduler):
        """Test model optimization job."""
        result = await scheduler.optimize_all_models(OptimizationType.ALL)
        
        # Verify result structure
        assert "total_models" in result
        assert "optimized" in result
        assert "failed" in result
        assert "optimizations" in result
        assert isinstance(result["optimizations"], list)
    
    @pytest.mark.asyncio
    async def test_cleanup_old_files(self, scheduler):
        """Test file cleanup job."""
        result = await scheduler.cleanup_old_files(days_old=30)
        
        # Verify result structure
        assert "files_checked" in result
        assert "files_deleted" in result
        assert "space_freed_mb" in result
        assert result["files_checked"] >= 0
        assert result["files_deleted"] >= 0
        assert result["space_freed_mb"] >= 0


class TestBatchOperations:
    """Test batch operations library."""
    
    @pytest.fixture
    def batch_ops(self):
        """Create batch operations instance."""
        return BatchOperations()
    
    @pytest.mark.asyncio
    async def test_batch_convert_format(self, batch_ops, tmp_path):
        """Test batch format conversion."""
        # Create test files
        test_files = []
        for i in range(3):
            file_path = tmp_path / f"model_{i}.step"
            file_path.write_text(f"STEP model {i}")
            test_files.append(file_path)
        
        # Mock converter
        with patch.object(batch_ops.converter, 'convert') as mock_convert:
            mock_convert.return_value = MagicMock(
                success=True,
                errors=[]
            )
            
            # Convert to STL
            results = await batch_ops.batch_convert_format(
                test_files,
                "stl",
                BatchOptions(strategy=ProcessingStrategy.PARALLEL)
            )
            
            # Verify results
            assert len(results) == 3
            assert all(r.target_format == "stl" for r in results)
    
    @pytest.mark.asyncio
    async def test_batch_generate_variants(self, batch_ops, tmp_path):
        """Test batch variant generation."""
        # Create base model
        base_model = tmp_path / "base_model.FCStd"
        base_model.write_text("FreeCAD model")
        
        # Define parameter sets
        param_sets = [
            ParameterSet(
                name="small",
                parameters={"width": 100, "height": 50}
            ),
            ParameterSet(
                name="medium",
                parameters={"width": 200, "height": 100}
            ),
            ParameterSet(
                name="large",
                parameters={"width": 300, "height": 150}
            )
        ]
        
        # Mock document manager
        with patch.object(batch_ops.document_manager, 'open_document') as mock_open:
            with patch.object(batch_ops.document_manager, 'copy_document') as mock_copy:
                with patch.object(batch_ops.document_manager, 'save_document_as') as mock_save:
                    mock_open.return_value = MagicMock(id="base_doc")
                    mock_copy.return_value = MagicMock(id="variant_doc")
                    
                    # Generate variants
                    variants = await batch_ops.batch_generate_variants(
                        base_model,
                        param_sets,
                        output_dir=tmp_path / "variants"
                    )
                    
                    # Verify results
                    assert len(variants) == 3
                    assert variants[0].parameters == param_sets[0].parameters
                    assert variants[1].parameters == param_sets[1].parameters
                    assert variants[2].parameters == param_sets[2].parameters
    
    @pytest.mark.asyncio
    async def test_batch_quality_check(self, batch_ops, tmp_path):
        """Test batch quality checking."""
        # Create test models
        test_models = []
        for i in range(2):
            model_path = tmp_path / f"model_{i}.FCStd"
            model_path.write_text(f"Model {i}")
            test_models.append(model_path)
        
        # Define quality checks
        checks = [
            QualityCheck(
                name="Geometri Kontrolü",
                type=QualityCheckType.GEOMETRY,
                criteria={"max_faces": 10000}
            ),
            QualityCheck(
                name="Topoloji Kontrolü",
                type=QualityCheckType.TOPOLOGY,
                criteria={}
            )
        ]
        
        # Mock document manager
        with patch.object(batch_ops.document_manager, 'open_document') as mock_open:
            with patch.object(batch_ops.document_manager, 'close_document') as mock_close:
                mock_open.return_value = MagicMock(id="test_doc")
                
                # Run quality checks
                reports = await batch_ops.batch_quality_check(
                    test_models,
                    checks
                )
                
                # Verify results
                assert len(reports) == 2
                for report in reports:
                    assert len(report.check_results) == 2
                    assert report.overall_passed is True


@pytest.mark.integration
class TestBatchProcessingIntegration:
    """Integration tests for batch processing system."""
    
    @pytest.mark.asyncio
    async def test_end_to_end_batch_workflow(self):
        """Test complete batch processing workflow."""
        # Initialize components
        batch_engine = BatchProcessingEngine()
        workflow_engine = WorkflowEngine()
        batch_ops = BatchOperations()
        
        # Define a complete workflow
        workflow = Workflow(
            name="Komple İşlem Akışı",
            steps=[
                WorkflowStep(
                    id="import",
                    name="Modelleri İçe Aktar",
                    type=StepType.ACTION,
                    action="import_models"
                ),
                WorkflowStep(
                    id="validate",
                    name="Doğrulama",
                    type=StepType.ACTION,
                    action="validate_models",
                    dependencies=["import"]
                ),
                WorkflowStep(
                    id="optimize",
                    name="Optimizasyon",
                    type=StepType.ACTION,
                    action="optimize_models",
                    dependencies=["validate"]
                ),
                WorkflowStep(
                    id="export",
                    name="Dışa Aktar",
                    type=StepType.ACTION,
                    action="export_models",
                    dependencies=["optimize"]
                )
            ]
        )
        
        # Register workflow actions
        async def import_models(params):
            return {"imported": 5}
        
        async def validate_models(params):
            return {"valid": 5, "invalid": 0}
        
        async def optimize_models(params):
            return {"optimized": 5}
        
        async def export_models(params):
            return {"exported": 5}
        
        workflow_engine.step_executor.register_action("import_models", import_models)
        workflow_engine.step_executor.register_action("validate_models", validate_models)
        workflow_engine.step_executor.register_action("optimize_models", optimize_models)
        workflow_engine.step_executor.register_action("export_models", export_models)
        
        # Define and execute workflow
        await workflow_engine.define_workflow(workflow)
        execution = await workflow_engine.execute_workflow(
            workflow.id,
            {"models": ["model1.step", "model2.step"]},
            ExecutionOptions()
        )
        
        # Verify complete execution
        assert execution.status == WorkflowStatus.COMPLETED
        assert len(execution.step_results) == 4
        assert all(r.status.value == "completed" for r in execution.step_results.values())
    
    @pytest.mark.asyncio
    async def test_performance_large_batch(self):
        """Test performance with large batch."""
        batch_engine = BatchProcessingEngine()
        
        # Create large batch
        items = [
            BatchItem(data={"id": i, "value": i * 2})
            for i in range(1000)
        ]
        
        # Simple processing function
        async def process(data):
            return {"id": data["id"], "result": data["value"] ** 2}
        
        # Process with parallel strategy
        start_time = datetime.now(UTC)
        result = await batch_engine.process_batch(
            items,
            process,
            BatchOptions(
                strategy=ProcessingStrategy.PARALLEL,
                max_workers=10
            )
        )
        end_time = datetime.now(UTC)
        
        # Verify performance
        assert result.successful_items == 1000
        assert result.failed_items == 0
        
        # Should complete reasonably fast
        duration = (end_time - start_time).total_seconds()
        assert duration < 10  # Should complete within 10 seconds
        
        # Verify correctness
        for i, r in enumerate(result.results):
            assert r["id"] == i
            assert r["result"] == (i * 2) ** 2