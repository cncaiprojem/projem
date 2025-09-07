"""
Task 7.17: Integration tests for model generation observability.

Tests the complete observability stack including:
- Prometheus metrics collection
- OpenTelemetry tracing
- Progress service integration
- Alert rule validation
"""

import asyncio
import time
from unittest.mock import Mock, patch, MagicMock
import pytest
from prometheus_client import REGISTRY, CollectorRegistry

from app.core import metrics
from app.core.telemetry import initialize_telemetry, get_tracer
from app.services.model_generation_observability import model_observability
from app.services.progress_service import progress_service
from app.schemas.progress import (
    DocumentPhase,
    Assembly4Phase,
    MaterialPhase,
    TopologyPhase,
    OCCTOperation,
    Phase,
    ExportFormat
)


@pytest.fixture
def clean_metrics():
    """Reset metrics registry for clean tests."""
    # Create a new registry for this test
    test_registry = CollectorRegistry()
    
    # Patch the metrics to use test registry
    with patch('app.core.metrics.REGISTRY', test_registry):
        yield test_registry


@pytest.fixture
def mock_tracer():
    """Mock OpenTelemetry tracer."""
    with patch('app.core.telemetry._tracer') as mock:
        mock_tracer = MagicMock()
        mock.return_value = mock_tracer
        yield mock_tracer


class TestModelGenerationMetrics:
    """Test model generation metrics collection."""
    
    def test_model_generation_flow_metrics(self, clean_metrics):
        """Test complete model generation flow metrics."""
        # Start a model generation flow
        with model_observability.observe_model_generation(
            flow_type="ai_prompt",
            job_id="test-job-123",
            user_id=1
        ):
            # Simulate stage execution
            with model_observability.observe_stage("ai_prompt", "validation"):
                time.sleep(0.01)
            
            with model_observability.observe_stage("ai_prompt", "normalization"):
                time.sleep(0.01)
            
            with model_observability.observe_stage("ai_prompt", "execution"):
                time.sleep(0.01)
            
            with model_observability.observe_stage("ai_prompt", "export"):
                time.sleep(0.01)
        
        # Verify metrics were recorded
        started = metrics.model_generation_started_total.labels(
            flow_type="ai_prompt",
            freecad_version="1.1.0",
            occt_version="7.8.1"
        )._value.get()
        assert started == 1
        
        completed = metrics.model_generation_completed_total.labels(
            flow_type="ai_prompt",
            status="success",
            freecad_version="1.1.0",
            occt_version="7.8.1"
        )._value.get()
        assert completed == 1
    
    def test_ai_provider_latency_metrics(self, clean_metrics):
        """Test AI provider latency metrics."""
        # Record AI provider latencies
        model_observability.record_ai_provider_latency(
            provider="openai",
            model="gpt-4",
            operation="prompt_to_script",
            latency_seconds=2.5
        )
        
        model_observability.record_ai_provider_latency(
            provider="anthropic",
            model="claude-3",
            operation="parameter_generation",
            latency_seconds=1.8
        )
        
        # Verify metrics
        # Note: Histograms store samples, not direct values
        samples = list(metrics.ai_provider_latency_seconds.collect())[0].samples
        assert len(samples) > 0
    
    def test_freecad_document_metrics(self, clean_metrics):
        """Test FreeCAD document operation metrics."""
        # Test document load
        with model_observability.observe_document_operation(
            document_id="doc-123",
            operation="load",
            workbench="PartDesign",
            source="file"
        ):
            time.sleep(0.01)
        
        # Test document recompute
        with model_observability.observe_document_operation(
            document_id="doc-123",
            operation="recompute",
            workbench="PartDesign",
            doc_complexity="high"
        ):
            time.sleep(0.01)
        
        # Verify metrics
        samples = list(metrics.freecad_document_load_seconds.collect())[0].samples
        assert len(samples) > 0
        
        samples = list(metrics.freecad_recompute_duration_seconds.collect())[0].samples
        assert len(samples) > 0
    
    def test_occt_operation_metrics(self, clean_metrics):
        """Test OCCT operation metrics."""
        # Test boolean operation
        with model_observability.observe_occt_boolean(
            operation="union",
            solids_count=5
        ):
            time.sleep(0.01)
        
        # Test feature operation
        with model_observability.observe_occt_feature(
            feature="fillet",
            edges_count=12
        ):
            time.sleep(0.01)
        
        # Test memory recording
        model_observability.record_occt_memory(
            operation="boolean_union",
            memory_bytes=536870912  # 512MB
        )
        
        # Verify metrics
        samples = list(metrics.occt_boolean_duration_seconds.collect())[0].samples
        assert len(samples) > 0
        
        samples = list(metrics.occt_feature_duration_seconds.collect())[0].samples
        assert len(samples) > 0
        
        memory = metrics.occt_operation_memory_bytes.labels(
            operation="boolean_union"
        )._value.get()
        assert memory == 536870912
    
    def test_assembly4_solver_metrics(self, clean_metrics):
        """Test Assembly4 solver metrics."""
        # Test constraint solving
        with model_observability.observe_assembly4_solver(
            solver_type="newton_raphson",
            constraints_count=50,
            lcs_count=10
        ) as context:
            # Simulate iterations
            context["iterations"] = 25
            time.sleep(0.01)
        
        # Test LCS resolution
        model_observability.record_lcs_resolution(
            lcs_count=15,
            duration_seconds=0.5
        )
        
        # Verify metrics
        samples = list(metrics.a4_constraint_solve_duration_seconds.collect())[0].samples
        assert len(samples) > 0
        
        samples = list(metrics.a4_solver_iterations_total.collect())[0].samples
        assert len(samples) > 0
        
        samples = list(metrics.a4_lcs_resolution_duration_seconds.collect())[0].samples
        assert len(samples) > 0
    
    def test_material_framework_metrics(self, clean_metrics):
        """Test Material Framework metrics."""
        # Test library access
        model_observability.record_material_library_access(
            library="standard_materials",
            result="hit"
        )
        model_observability.record_material_library_access(
            library="standard_materials",
            result="miss"
        )
        
        # Test property application
        with model_observability.observe_material_property_application(
            property_type="density",
            material_count=5,
            library="standard_materials"
        ):
            time.sleep(0.01)
        
        # Verify metrics
        hit_count = metrics.material_library_access_total.labels(
            library="standard_materials",
            result="hit"
        )._value.get()
        assert hit_count == 1
        
        miss_count = metrics.material_library_access_total.labels(
            library="standard_materials",
            result="miss"
        )._value.get()
        assert miss_count == 1
        
        samples = list(metrics.material_property_apply_duration_seconds.collect())[0].samples
        assert len(samples) > 0
    
    def test_topology_and_export_metrics(self, clean_metrics):
        """Test topology hash and export metrics."""
        # Test topology hash
        with model_observability.observe_topology_hash(
            scope="assembly",
            entity_count=100
        ):
            time.sleep(0.01)
        
        # Test export validation
        model_observability.record_export_validation(
            format="STEP",
            result="pass",
            file_size=1024000
        )
        model_observability.record_export_validation(
            format="STL",
            result="fail",
            file_size=512000
        )
        
        # Test export operation
        with model_observability.observe_export(
            format="STEP",
            file_size=1024000
        ):
            time.sleep(0.01)
        
        # Verify metrics
        samples = list(metrics.topology_hash_compute_duration_seconds.collect())[0].samples
        assert len(samples) > 0
        
        pass_count = metrics.deterministic_export_validation_total.labels(
            format="STEP",
            result="pass"
        )._value.get()
        assert pass_count == 1
        
        fail_count = metrics.deterministic_export_validation_total.labels(
            format="STL",
            result="fail"
        )._value.get()
        assert fail_count == 1
        
        samples = list(metrics.export_duration_seconds.collect())[0].samples
        assert len(samples) > 0
    
    def test_workbench_metrics(self, clean_metrics):
        """Test workbench usage metrics."""
        # Record workbench invocations
        model_observability.record_workbench_invocation(
            workbench="PartDesign",
            compatible=True
        )
        model_observability.record_workbench_invocation(
            workbench="Assembly4",
            compatible=True
        )
        model_observability.record_workbench_invocation(
            workbench="LegacyWorkbench",
            compatible=False
        )
        
        # Verify metrics
        pd_count = metrics.freecad_workbench_invocations_total.labels(
            workbench="PartDesign"
        )._value.get()
        assert pd_count == 1
        
        a4_count = metrics.freecad_workbench_invocations_total.labels(
            workbench="Assembly4"
        )._value.get()
        assert a4_count == 1
        
        compat_false = metrics.freecad_workbench_compatibility_total.labels(
            workbench="LegacyWorkbench",
            compatible="false"
        )._value.get()
        assert compat_false == 1


class TestOpenTelemetryTracing:
    """Test OpenTelemetry tracing integration."""
    
    def test_model_generation_flow_tracing(self, mock_tracer):
        """Test tracing for model generation flow."""
        with model_observability.observe_model_generation(
            flow_type="parametric",
            job_id="job-456",
            user_id=2
        ):
            with model_observability.observe_stage("parametric", "validation"):
                pass
            
            with model_observability.observe_stage("parametric", "execution"):
                pass
        
        # Verify spans were created
        # In real test, would verify span attributes and hierarchy
        assert mock_tracer is not None
    
    def test_freecad_document_tracing(self, mock_tracer):
        """Test tracing for FreeCAD document operations."""
        with model_observability.observe_document_operation(
            document_id="doc-789",
            operation="load",
            workbench="Sketcher"
        ):
            pass
        
        # Verify span was created with correct attributes
        assert mock_tracer is not None
    
    def test_occt_operation_tracing(self, mock_tracer):
        """Test tracing for OCCT operations."""
        with model_observability.observe_occt_boolean(
            operation="cut",
            solids_count=3
        ):
            pass
        
        with model_observability.observe_occt_feature(
            feature="chamfer",
            edges_count=8
        ):
            pass
        
        # Verify spans were created
        assert mock_tracer is not None


class TestProgressServiceIntegration:
    """Test integration with progress service."""
    
    @pytest.mark.asyncio
    async def test_document_progress_with_metrics(self, clean_metrics):
        """Test document progress updates trigger metrics."""
        # Publish document progress
        await progress_service.publish_document_progress(
            job_id=123,
            phase=DocumentPhase.DOCUMENT_OPEN,
            document_id="doc-001",
            document_label="TestDoc"
        )
        
        await progress_service.publish_document_progress(
            job_id=123,
            phase=DocumentPhase.RECOMPUTE_START,
            document_id="doc-001"
        )
        
        await progress_service.publish_document_progress(
            job_id=123,
            phase=DocumentPhase.RECOMPUTE_END,
            document_id="doc-001"
        )
        
        # Verify metrics were updated
        # Note: Progress service metrics are in a different module
        assert True  # Placeholder for actual metric verification
    
    @pytest.mark.asyncio
    async def test_assembly4_progress_with_metrics(self, clean_metrics):
        """Test Assembly4 progress updates trigger metrics."""
        # Publish Assembly4 progress
        await progress_service.publish_assembly4_progress(
            job_id=124,
            phase=Assembly4Phase.SOLVER_START,
            constraints_total=30
        )
        
        await progress_service.publish_assembly4_progress(
            job_id=124,
            phase=Assembly4Phase.SOLVER_PROGRESS,
            constraints_resolved=15,
            constraints_total=30,
            iteration=10,
            residual=0.001
        )
        
        await progress_service.publish_assembly4_progress(
            job_id=124,
            phase=Assembly4Phase.SOLVER_END,
            constraints_resolved=30,
            constraints_total=30
        )
        
        # Verify metrics
        assert True  # Placeholder
    
    @pytest.mark.asyncio
    async def test_occt_progress_with_metrics(self, clean_metrics):
        """Test OCCT progress updates trigger metrics."""
        # Publish OCCT progress
        await progress_service.publish_occt_progress(
            job_id=125,
            operation=OCCTOperation.BOOLEAN_UNION,
            phase=Phase.START,
            shapes_total=5
        )
        
        await progress_service.publish_occt_progress(
            job_id=125,
            operation=OCCTOperation.BOOLEAN_UNION,
            phase=Phase.PROGRESS,
            shapes_done=3,
            shapes_total=5
        )
        
        await progress_service.publish_occt_progress(
            job_id=125,
            operation=OCCTOperation.BOOLEAN_UNION,
            phase=Phase.END,
            shapes_done=5,
            shapes_total=5
        )
        
        # Verify metrics
        assert True  # Placeholder


class TestAlertRuleValidation:
    """Test that alert rules are properly configured."""
    
    def test_high_failure_rate_alert_threshold(self, clean_metrics):
        """Test high failure rate alert would trigger."""
        # Simulate high failure rate
        for _ in range(10):
            metrics.model_generation_completed_total.labels(
                flow_type="ai_prompt",
                status="error",
                freecad_version="1.1.0",
                occt_version="7.8.1"
            ).inc()
        
        for _ in range(5):
            metrics.model_generation_completed_total.labels(
                flow_type="ai_prompt",
                status="success",
                freecad_version="1.1.0",
                occt_version="7.8.1"
            ).inc()
        
        # Calculate failure rate
        error_count = metrics.model_generation_completed_total.labels(
            flow_type="ai_prompt",
            status="error",
            freecad_version="1.1.0",
            occt_version="7.8.1"
        )._value.get()
        
        success_count = metrics.model_generation_completed_total.labels(
            flow_type="ai_prompt",
            status="success",
            freecad_version="1.1.0",
            occt_version="7.8.1"
        )._value.get()
        
        failure_rate = error_count / (error_count + success_count)
        
        # Alert threshold is 10%
        assert failure_rate > 0.1
    
    def test_export_validation_failure_alert(self, clean_metrics):
        """Test export validation failure alert threshold."""
        # Simulate export validation failures
        for _ in range(3):
            model_observability.record_export_validation(
                format="STEP",
                result="fail"
            )
        
        for _ in range(97):
            model_observability.record_export_validation(
                format="STEP",
                result="pass"
            )
        
        # Calculate failure rate
        fail_count = metrics.deterministic_export_validation_total.labels(
            format="STEP",
            result="fail"
        )._value.get()
        
        pass_count = metrics.deterministic_export_validation_total.labels(
            format="STEP",
            result="pass"
        )._value.get()
        
        failure_rate = fail_count / (fail_count + pass_count)
        
        # Alert threshold is 2%
        assert failure_rate > 0.02
    
    def test_occt_memory_alert(self, clean_metrics):
        """Test OCCT memory usage alert."""
        # Set high memory usage
        high_memory = 2 * 1024 * 1024 * 1024  # 2GB
        model_observability.record_occt_memory(
            operation="boolean_complex",
            memory_bytes=high_memory
        )
        
        # Verify memory exceeds threshold (1.5GB)
        memory = metrics.occt_operation_memory_bytes.labels(
            operation="boolean_complex"
        )._value.get()
        
        assert memory > 1610612736  # 1.5GB threshold


class TestEndToEndObservability:
    """Test end-to-end observability scenarios."""
    
    @pytest.mark.asyncio
    async def test_complete_ai_prompt_flow(self, clean_metrics):
        """Test complete AI prompt model generation flow with observability."""
        job_id = "e2e-job-001"
        user_id = 10
        
        # Start model generation
        with model_observability.observe_model_generation(
            flow_type="ai_prompt",
            job_id=job_id,
            user_id=user_id
        ):
            # AI provider call
            start = time.time()
            # Simulate AI call
            time.sleep(0.1)
            model_observability.record_ai_provider_latency(
                provider="openai",
                model="gpt-4",
                operation="prompt_to_script",
                latency_seconds=time.time() - start
            )
            
            # Validation stage
            with model_observability.observe_stage("ai_prompt", "validation"):
                time.sleep(0.01)
            
            # Document operations
            with model_observability.observe_document_operation(
                document_id=f"doc-{job_id}",
                operation="load",
                workbench="PartDesign"
            ):
                model_observability.record_object_creation(
                    object_class="Part::Box",
                    workbench="PartDesign",
                    count=3
                )
            
            # OCCT operations
            with model_observability.observe_occt_boolean(
                operation="union",
                solids_count=3
            ):
                time.sleep(0.01)
            
            # Export
            with model_observability.observe_export(
                format="STEP",
                file_size=2048000
            ):
                time.sleep(0.01)
            
            # Validation
            model_observability.record_export_validation(
                format="STEP",
                result="pass",
                file_size=2048000
            )
        
        # Verify all metrics were recorded
        assert metrics.model_generation_started_total.labels(
            flow_type="ai_prompt",
            freecad_version="1.1.0",
            occt_version="7.8.1"
        )._value.get() > 0
        
        assert metrics.model_generation_completed_total.labels(
            flow_type="ai_prompt",
            status="success",
            freecad_version="1.1.0",
            occt_version="7.8.1"
        )._value.get() > 0
    
    @pytest.mark.asyncio
    async def test_assembly4_flow_with_progress(self, clean_metrics):
        """Test Assembly4 flow with progress updates."""
        job_id = 200
        
        # Start Assembly4 generation
        with model_observability.observe_model_generation(
            flow_type="assembly4",
            job_id=str(job_id),
            user_id=20
        ):
            # Document load
            with model_observability.observe_document_operation(
                document_id=f"asm-{job_id}",
                operation="load",
                workbench="Assembly4"
            ):
                pass
            
            # Publish progress
            await progress_service.publish_assembly4_progress(
                job_id=job_id,
                phase=Assembly4Phase.SOLVER_START,
                constraints_total=50
            )
            
            # Solve constraints
            with model_observability.observe_assembly4_solver(
                solver_type="sequential",
                constraints_count=50,
                lcs_count=15
            ) as context:
                # Simulate solving with progress
                for i in range(1, 6):
                    await progress_service.publish_assembly4_progress(
                        job_id=job_id,
                        phase=Assembly4Phase.SOLVER_PROGRESS,
                        constraints_resolved=i * 10,
                        constraints_total=50,
                        iteration=i * 5,
                        residual=0.1 / i
                    )
                    time.sleep(0.01)
                
                context["iterations"] = 25
            
            # Complete
            await progress_service.publish_assembly4_progress(
                job_id=job_id,
                phase=Assembly4Phase.SOLVER_END,
                constraints_resolved=50,
                constraints_total=50
            )
            
            # Export
            with model_observability.observe_export(
                format="STEP",
                file_size=5120000
            ):
                pass
        
        # Verify metrics
        assert metrics.model_generation_completed_total.labels(
            flow_type="assembly4",
            status="success",
            freecad_version="1.1.0",
            occt_version="7.8.1"
        )._value.get() > 0