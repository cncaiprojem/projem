"""
Tests for Task 7.4 - Celery Job Orchestration and Lifecycle for Model Flows

Comprehensive test suite for:
- AI-driven model generation (models.prompt)
- Parametric modeling (models.params)
- Upload normalization (models.upload)
- Assembly4 workflows (assemblies.a4)
- FEM/Simulation (sim.fem)

Tests include:
- Task signature validation
- Idempotency checks
- Status transitions
- Error handling and DLQ routing
- Progress updates
- Structured logging
- Turkish terminology
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from datetime import datetime, timezone
from uuid import uuid4

from apps.api.app.tasks.model_flows import (
    generate_model_from_prompt,
    generate_model_from_params,
    normalize_uploaded_model,
    generate_assembly4_workflow,
    update_job_status,
    ensure_idempotency,
    validate_model_inputs,
    TaskResult
)
from apps.api.app.tasks.fem_simulation import (
    run_fem_simulation,
    validate_fem_inputs,
    estimate_analysis_resources,
    FEMTaskResult,
    FEM_ANALYSIS_TYPES,
    DEFAULT_MATERIALS
)
from apps.api.app.models.enums import JobStatus, JobType
from apps.api.app.core.database import SessionLocal


class TestModelFlowTasks:
    """Test suite for model flow tasks."""

    @pytest.fixture
    def sample_job_params(self):
        """Sample job parameters for testing."""
        return {
            "job_id": str(uuid4()),
            "request_id": str(uuid4()),
            "user_id": 1,
            "canonical_params": {
                "prompt": "20mm flanş M8 vida deliği ile",
                "dimensions": {"outer_diameter": 20.0, "thickness": 5.0},
                "materials": {
                    "steel": {
                        "young_modulus": 200000.0,
                        "poisson_ratio": 0.3,
                        "density": 7850.0
                    }
                }
            }
        }

    @pytest.fixture
    def mock_db_session(self):
        """Mock database session."""
        with patch('app.tasks.model_flows.SessionLocal') as mock_session:
            mock_db = Mock()
            mock_session.return_value = mock_db
            mock_job = Mock()
            mock_job.id = "test_job_123"
            mock_job.status = JobStatus.PENDING
            mock_job.progress = 0
            mock_db.query.return_value.filter.return_value.first.return_value = mock_job
            yield mock_db

    @pytest.fixture 
    def mock_document_manager(self):
        """Mock FreeCAD document manager."""
        with patch('app.tasks.model_flows.document_manager') as mock_dm:
            mock_metadata = Mock()
            mock_metadata.document_id = "doc_123"
            mock_dm.create_document.return_value = mock_metadata
            mock_dm.save_document.return_value = "/tmp/test_model.FCStd"
            yield mock_dm

    @pytest.fixture
    def mock_ai_adapter(self):
        """Mock AI adapter."""
        with patch('app.tasks.model_flows.ai_adapter') as mock_ai:
            mock_response = Mock()
            mock_response.script_py = "# FreeCAD script\nimport FreeCAD\n"
            mock_response.parameters = {"diameter": 20.0}
            mock_response.warnings = []
            mock_response.dict.return_value = {
                "script_py": mock_response.script_py,
                "parameters": mock_response.parameters,
                "warnings": mock_response.warnings
            }
            mock_ai.suggest_params = AsyncMock(return_value=mock_response)
            yield mock_ai

    @pytest.fixture
    def mock_s3_service(self):
        """Mock S3 service."""
        with patch('app.tasks.model_flows.s3_service') as mock_s3:
            mock_s3.upload_file.return_value = "https://s3.amazonaws.com/bucket/test.FCStd"
            yield mock_s3

    def test_task_result_creation(self):
        """Test TaskResult creation and serialization."""
        result = TaskResult(
            success=True,
            data={"model_generated": True},
            artefacts=[{"type": "model", "filename": "test.FCStd"}],
            progress=100
        )
        
        result_dict = result.to_dict()
        
        assert result_dict["success"] is True
        assert result_dict["data"]["model_generated"] is True
        assert len(result_dict["artefacts"]) == 1
        assert result_dict["progress"] == 100
        assert "timestamp" in result_dict

    def test_validate_model_inputs(self):
        """Test model input validation."""
        # Valid inputs
        valid_params = {
            "model_type": "flange",
            "dimensions": {"diameter": 20.0, "thickness": 5.0},
            "materials": {
                "steel": {
                    "young_modulus": 200000.0,
                    "density": 7850.0
                }
            }
        }
        
        warnings = validate_model_inputs(valid_params)
        assert isinstance(warnings, list)
        
        # Invalid inputs - missing material properties
        invalid_params = {
            "model_type": "flange",
            "dimensions": {"diameter": -5.0},  # Invalid dimension
            "materials": {
                "unknown_material": {}  # Missing properties
            }
        }
        
        warnings = validate_model_inputs(invalid_params)
        assert len(warnings) > 0
        assert any("Invalid dimension" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_generate_model_from_prompt_success(
        self, 
        sample_job_params,
        mock_db_session,
        mock_document_manager,
        mock_ai_adapter,
        mock_s3_service
    ):
        """Test successful AI-driven model generation."""
        with patch('apps.api.app.tasks.model_flows.security_validator') as mock_validator, \
             patch('apps.api.app.tasks.model_flows.create_span') as mock_span, \
             patch('apps.api.app.tasks.model_flows.set_correlation_id'), \
             patch('apps.api.app.tasks.model_flows.metrics'):
            
            # Mock security validation
            mock_validator.validate_script.return_value = None
            
            # Mock span context manager
            mock_span.return_value.__enter__ = Mock()
            mock_span.return_value.__exit__ = Mock()
            mock_span.return_value.set_attribute = Mock()
            
            # Mock document lock and transaction
            mock_document_manager.document_lock.return_value.__enter__ = Mock()
            mock_document_manager.document_lock.return_value.__exit__ = Mock()
            mock_document_manager.transaction.return_value.__enter__ = Mock()
            mock_document_manager.transaction.return_value.__exit__ = Mock()
            
            # Create mock task with proper binding
            mock_task = Mock()
            mock_task.request.id = "task_123"
            mock_task.request.retries = 0
            
            # Call the task function directly (not through Celery)
            result = await generate_model_from_prompt(
                mock_task,
                **sample_job_params
            )
            
            # Assertions
            assert isinstance(result, dict)
            assert result["success"] is True
            assert result["data"]["model_generated"] is True
            assert len(result["artefacts"]) > 0
            assert result["progress"] == 100
            
            # Verify AI adapter was called
            mock_ai_adapter.suggest_params.assert_called_once()
            
            # Verify document operations
            mock_document_manager.create_document.assert_called_once()
            mock_document_manager.save_document.assert_called_once()
            
            # Verify S3 upload
            mock_s3_service.upload_file.assert_called()

    def test_generate_model_from_prompt_ai_failure(
        self, 
        sample_job_params,
        mock_db_session
    ):
        """Test AI adapter failure handling."""
        from apps.api.app.services.ai_adapter import AIException, AIErrorCode
        
        with patch('app.tasks.model_flows.ai_adapter') as mock_ai, \
             patch('app.tasks.model_flows.create_span') as mock_span, \
             patch('app.tasks.model_flows.set_correlation_id'), \
             patch('app.tasks.model_flows.metrics'):
            
            # Mock AI adapter to raise exception
            mock_ai.suggest_params = AsyncMock(
                side_effect=AIException(
                    "AI service unavailable",
                    AIErrorCode.PROVIDER_ERROR,
                    "AI servisi kullanılamıyor"
                )
            )
            
            # Mock span context manager
            mock_span.return_value.__enter__ = Mock()
            mock_span.return_value.__exit__ = Mock()
            mock_span.return_value.set_attribute = Mock()
            
            # Create mock task
            mock_task = Mock()
            mock_task.request.id = "task_123"
            mock_task.request.retries = 0
            
            # Call the task function
            result = asyncio.run(generate_model_from_prompt(
                mock_task,
                **sample_job_params
            ))
            
            # Assertions
            assert isinstance(result, dict)
            assert result["success"] is False
            assert "AI service unavailable" in result["error"]
            assert result["progress"] == 0

    def test_generate_model_from_params_success(
        self,
        sample_job_params,
        mock_db_session,
        mock_document_manager,
        mock_s3_service
    ):
        """Test successful parametric model generation."""
        # Modify params for parametric modeling
        sample_job_params["canonical_params"] = {
            "model_type": "flange",
            "dimensions": {"outer_diameter": 50.0, "thickness": 8.0},
            "features": [{"type": "hole", "diameter": 8.5}]
        }
        
        with patch('app.tasks.model_flows._generate_parametric_model') as mock_gen, \
             patch('app.tasks.model_flows.create_span') as mock_span, \
             patch('app.tasks.model_flows.set_correlation_id'), \
             patch('app.tasks.model_flows.metrics'), \
             patch('os.path.getsize', return_value=1024):
            
            # Mock parametric model generation
            mock_gen.return_value = {
                "model_created": True,
                "model_type": "flange",
                "dimensions_applied": {"outer_diameter": 50.0, "thickness": 8.0}
            }
            
            # Mock span and document operations
            mock_span.return_value.__enter__ = Mock()
            mock_span.return_value.__exit__ = Mock()
            mock_span.return_value.set_attribute = Mock()
            
            mock_document_manager.document_lock.return_value.__enter__ = Mock()
            mock_document_manager.document_lock.return_value.__exit__ = Mock()
            mock_document_manager.transaction.return_value.__enter__ = Mock()
            mock_document_manager.transaction.return_value.__exit__ = Mock()
            
            # Create mock task
            mock_task = Mock()
            mock_task.request.id = "task_123"
            mock_task.request.retries = 0
            
            # Call the task function
            result = generate_model_from_params(
                mock_task,
                **sample_job_params
            )
            
            # Assertions
            assert isinstance(result, dict)
            assert result["success"] is True
            assert result["data"]["model_generated"] is True
            assert result["data"]["model_type"] == "flange"
            assert len(result["artefacts"]) == 1

    def test_normalize_uploaded_model_success(
        self,
        sample_job_params,
        mock_db_session,
        mock_document_manager,
        mock_s3_service
    ):
        """Test successful upload normalization."""
        # Modify params for upload normalization
        sample_job_params["input_ref"] = "/tmp/test_model.step"
        sample_job_params["canonical_params"] = {
            "target_format": "FCStd",
            "unit_conversion": {"from": "mm", "to": "mm"},
            "validation_rules": ["geometry_valid", "manifold"]
        }
        
        with patch('app.tasks.model_flows._resolve_input_ref') as mock_resolve, \
             patch('app.tasks.model_flows._normalize_cad_file') as mock_normalize, \
             patch('app.tasks.model_flows.create_span') as mock_span, \
             patch('app.tasks.model_flows.set_correlation_id'), \
             patch('app.tasks.model_flows.metrics'), \
             patch('os.path.getsize', return_value=2048), \
             patch('os.path.splitext', return_value=('test_model', '.step')):
            
            # Mock file resolution and normalization
            mock_resolve.return_value = "/tmp/test_model.step"
            mock_normalize.return_value = {
                "normalized": True,
                "geometry_valid": True,
                "fixes_applied": []
            }
            
            # Mock span and document operations
            mock_span.return_value.__enter__ = Mock()
            mock_span.return_value.__exit__ = Mock()
            mock_span.return_value.set_attribute = Mock()
            
            mock_document_manager.document_lock.return_value.__enter__ = Mock()
            mock_document_manager.document_lock.return_value.__exit__ = Mock()
            mock_document_manager.transaction.return_value.__enter__ = Mock()
            mock_document_manager.transaction.return_value.__exit__ = Mock()
            
            # Create mock task
            mock_task = Mock()
            mock_task.request.id = "task_123"
            mock_task.request.retries = 0
            
            # Call the task function
            result = normalize_uploaded_model(
                mock_task,
                **sample_job_params
            )
            
            # Assertions
            assert isinstance(result, dict)
            assert result["success"] is True
            assert result["data"]["model_normalized"] is True
            assert result["data"]["original_format"] == ".step"

    def test_generate_assembly4_workflow_success(
        self,
        sample_job_params,
        mock_db_session,
        mock_document_manager,
        mock_s3_service
    ):
        """Test successful Assembly4 workflow generation."""
        # Modify params for assembly
        sample_job_params["canonical_params"] = {
            "assembly_name": "Test_Assembly",
            "parts": [
                {"name": "part1", "type": "base", "file": "part1.FCStd"},
                {"name": "part2", "type": "component", "file": "part2.FCStd"}
            ],
            "constraints": [
                {"type": "coincident", "parts": ["part1", "part2"]},
                {"type": "parallel", "parts": ["part1", "part2"]}
            ]
        }
        
        with patch('app.tasks.model_flows._create_assembly4_workflow') as mock_asm, \
             patch('app.tasks.model_flows.create_span') as mock_span, \
             patch('app.tasks.model_flows.set_correlation_id'), \
             patch('app.tasks.model_flows.metrics'), \
             patch('os.path.getsize', return_value=4096):
            
            # Mock assembly workflow creation
            mock_asm.return_value = {
                "assembly_created": True,
                "parts_loaded": 2,
                "constraints_applied": 2,
                "assembly_valid": True
            }
            
            # Mock document manager setup
            mock_document_manager.setup_assembly_coordination.return_value = {
                "coordination_id": "coord_123",
                "child_documents": ["doc_1", "doc_2"]
            }
            
            # Mock span and document operations
            mock_span.return_value.__enter__ = Mock()
            mock_span.return_value.__exit__ = Mock()
            mock_span.return_value.set_attribute = Mock()
            
            mock_document_manager.document_lock.return_value.__enter__ = Mock()
            mock_document_manager.document_lock.return_value.__exit__ = Mock()
            mock_document_manager.transaction.return_value.__enter__ = Mock()
            mock_document_manager.transaction.return_value.__exit__ = Mock()
            
            # Create mock task
            mock_task = Mock()
            mock_task.request.id = "task_123"
            mock_task.request.retries = 0
            
            # Call the task function
            result = generate_assembly4_workflow(
                mock_task,
                **sample_job_params
            )
            
            # Assertions
            assert isinstance(result, dict)
            assert result["success"] is True
            assert result["data"]["assembly_generated"] is True
            assert result["data"]["assembly_name"] == "Test_Assembly"
            assert result["data"]["parts_processed"] == 2
            assert result["data"]["constraints_applied"] == 2


class TestFEMSimulationTasks:
    """Test suite for FEM simulation tasks."""

    @pytest.fixture
    def fem_job_params(self):
        """Sample FEM job parameters."""
        return {
            "job_id": str(uuid4()),
            "request_id": str(uuid4()),
            "user_id": 1,
            "model_ref": "s3://bucket/test_model.FCStd",
            "canonical_params": {
                "analysis_type": "static",
                "unit_system": "SI",
                "materials": {
                    "steel": {
                        "young_modulus": 200000.0,
                        "poisson_ratio": 0.3,
                        "density": 7850.0,
                        "yield_strength": 250.0
                    }
                },
                "constraints": [
                    {
                        "type": "fixed",
                        "selection": {"faces": ["Face1"]},
                        "name": "Fixed_Support"
                    }
                ],
                "loads": [
                    {
                        "type": "force", 
                        "magnitude": 1000.0,
                        "direction": [0, 0, -1],
                        "selection": {"faces": ["Face2"]}
                    }
                ],
                "mesh": {
                    "mesher": "gmsh",
                    "global_size": 2.0,
                    "second_order": True
                },
                "solver": {
                    "backend": "calculix",
                    "max_iterations": 1000,
                    "tolerance": 1e-6
                }
            }
        }

    def test_fem_analysis_types_coverage(self):
        """Test that all required FEM analysis types are defined."""
        required_types = [
            "static", "modal", "buckling", 
            "thermal_steady", "thermal_transient", 
            "coupled_thermal_static"
        ]
        
        for analysis_type in required_types:
            assert analysis_type in FEM_ANALYSIS_TYPES
            type_info = FEM_ANALYSIS_TYPES[analysis_type]
            assert "name" in type_info
            assert "turkish" in type_info
            assert "solver" in type_info
            assert "typical_time" in type_info

    def test_default_materials_coverage(self):
        """Test that default materials have required properties."""
        required_props = [
            "young_modulus", "poisson_ratio", "density",
            "thermal_expansion", "thermal_conductivity", 
            "specific_heat", "yield_strength"
        ]
        
        for material_name, properties in DEFAULT_MATERIALS.items():
            for prop in required_props:
                assert prop in properties, f"Missing {prop} in {material_name}"
            
            # Validate property ranges
            assert properties["young_modulus"] > 0
            assert 0.0 <= properties["poisson_ratio"] <= 0.5
            assert properties["density"] > 0

    def test_validate_fem_inputs_valid(self, fem_job_params):
        """Test FEM input validation with valid parameters."""
        is_valid, warnings = validate_fem_inputs(fem_job_params["canonical_params"])
        
        assert is_valid is True
        assert isinstance(warnings, list)

    def test_validate_fem_inputs_invalid(self):
        """Test FEM input validation with invalid parameters."""
        invalid_params = {
            "analysis_type": "invalid_type",  # Invalid analysis type
            "unit_system": "imperial",       # Unsupported unit system
            "materials": {},                 # No materials
            "constraints": [],               # No constraints
            "loads": []                      # No loads for static analysis
        }
        
        is_valid, warnings = validate_fem_inputs(invalid_params)
        
        assert is_valid is False
        assert len(warnings) > 0
        assert any("Geçersiz analiz tipi" in w for w in warnings)

    def test_estimate_analysis_resources(self, fem_job_params):
        """Test analysis resource estimation."""
        # Add geometry info for estimation
        fem_job_params["canonical_params"]["geometry"] = {
            "bounding_box": {"volume": 100000.0}  # mm³
        }
        
        estimate = estimate_analysis_resources(fem_job_params["canonical_params"])
        
        assert isinstance(estimate, dict)
        assert "estimated_elements" in estimate
        assert "estimated_nodes" in estimate
        assert "estimated_time_seconds" in estimate
        assert "estimated_memory_mb" in estimate
        assert "exceeds_limits" in estimate
        assert "complexity_level" in estimate
        
        # Check that estimates are reasonable
        assert estimate["estimated_elements"] > 0
        assert estimate["estimated_nodes"] > estimate["estimated_elements"]
        assert estimate["complexity_level"] in ["low", "medium", "high"]

    def test_fem_task_result_creation(self):
        """Test FEMTaskResult creation and serialization."""
        result = FEMTaskResult(
            success=True,
            analysis_type="static",
            data={"max_stress": 125.6},
            results_summary={
                "max_von_mises_stress": 125.6,
                "max_displacement": 0.234,
                "factor_of_safety": 1.99
            },
            artefacts=[{"type": "fem_results", "filename": "results.frd"}]
        )
        
        result_dict = result.to_dict()
        
        assert result_dict["success"] is True
        assert result_dict["analysis_type"] == "static"
        assert result_dict["turkish_type"] == "Doğrusal Statik"
        assert result_dict["results_summary"]["max_von_mises_stress"] == 125.6
        assert "timestamp" in result_dict

    @pytest.mark.asyncio
    async def test_run_fem_simulation_success(self, fem_job_params):
        """Test successful FEM simulation execution."""
        with patch('app.tasks.fem_simulation.SessionLocal') as mock_session, \
             patch('app.tasks.fem_simulation._resolve_model_reference') as mock_resolve, \
             patch('app.tasks.fem_simulation._create_fem_analysis') as mock_create, \
             patch('app.tasks.fem_simulation._assign_materials') as mock_materials, \
             patch('app.tasks.fem_simulation._apply_boundary_conditions') as mock_bc, \
             patch('app.tasks.fem_simulation._generate_mesh') as mock_mesh, \
             patch('app.tasks.fem_simulation._run_calculix_solver') as mock_solver, \
             patch('app.tasks.fem_simulation._process_fem_results') as mock_results, \
             patch('app.tasks.fem_simulation._create_fem_artefacts') as mock_artefacts, \
             patch('app.tasks.fem_simulation.create_span') as mock_span, \
             patch('app.tasks.fem_simulation.set_correlation_id'), \
             patch('app.tasks.fem_simulation.metrics'), \
             patch('tempfile.mkdtemp', return_value="/tmp/fem_test"), \
             patch('shutil.rmtree'):
            
            # Mock database session
            mock_db = Mock()
            mock_session.return_value = mock_db
            mock_job = Mock()
            mock_job.id = fem_job_params["job_id"]
            mock_job.status = JobStatus.PENDING
            mock_db.query.return_value.filter.return_value.first.return_value = mock_job
            
            # Mock FEM pipeline components
            mock_resolve.return_value = "/tmp/test_model.FCStd"
            mock_create.return_value = {"analysis_type": "static", "temp_dir": "/tmp/fem_test"}
            mock_materials.return_value = {"success": True, "warnings": []}
            mock_bc.return_value = {"success": True, "warnings": []}
            mock_mesh.return_value = {
                "success": True,
                "warnings": [],
                "mesh_info": {"elements": 5000, "nodes": 6500}
            }
            mock_solver.return_value = {
                "success": True,
                "solver_info": {"converged": True, "iterations": 45},
                "output": "CalculiX completed successfully",
                "result_files": ["/tmp/fem_test/results.frd"]
            }
            mock_results.return_value = {
                "summary": {
                    "max_von_mises_stress": 125.6,
                    "max_displacement": 0.234,
                    "factor_of_safety": 1.99
                }
            }
            mock_artefacts.return_value = [
                {"type": "fem_analysis", "filename": "analysis.fcstd"}
            ]
            
            # Mock span context manager
            mock_span.return_value.__enter__ = Mock()
            mock_span.return_value.__exit__ = Mock()
            mock_span.return_value.set_attribute = Mock()
            
            # Create mock task
            mock_task = Mock()
            mock_task.request.id = "task_fem_123"
            mock_task.request.retries = 0
            
            # Call the task function
            result = run_fem_simulation(
                mock_task,
                **fem_job_params
            )
            
            # Assertions
            assert isinstance(result, dict)
            assert result["success"] is True
            assert result["analysis_type"] == "static"
            assert result["turkish_type"] == "Doğrusal Statik"
            assert "results_summary" in result
            assert result["results_summary"]["max_von_mises_stress"] == 125.6

    def test_run_fem_simulation_validation_failure(self, fem_job_params):
        """Test FEM simulation with validation failure."""
        # Make parameters invalid
        fem_job_params["canonical_params"]["analysis_type"] = "invalid_type"
        
        with patch('app.tasks.fem_simulation.SessionLocal') as mock_session, \
             patch('app.tasks.fem_simulation.create_span') as mock_span, \
             patch('app.tasks.fem_simulation.set_correlation_id'), \
             patch('app.tasks.fem_simulation.metrics'):
            
            # Mock database session
            mock_db = Mock()
            mock_session.return_value = mock_db
            mock_job = Mock()
            mock_job.id = fem_job_params["job_id"]
            mock_job.status = JobStatus.PENDING
            mock_db.query.return_value.filter.return_value.first.return_value = mock_job
            
            # Mock span context manager
            mock_span.return_value.__enter__ = Mock()
            mock_span.return_value.__exit__ = Mock()
            mock_span.return_value.set_attribute = Mock()
            
            # Create mock task
            mock_task = Mock()
            mock_task.request.id = "task_fem_123"
            mock_task.request.retries = 0
            
            # Call the task function
            result = run_fem_simulation(
                mock_task,
                **fem_job_params
            )
            
            # Assertions
            assert isinstance(result, dict)
            assert result["success"] is False
            assert "FEM girdi doğrulaması başarısız" in result["error"]
            assert len(result["warnings"]) > 0


class TestTaskOrchestration:
    """Test task orchestration features like idempotency, status updates."""
    
    def test_update_job_status_success(self):
        """Test successful job status update."""
        job_id = "test_job_123"
        
        with patch('app.tasks.model_flows.SessionLocal') as mock_session:
            mock_db = Mock()
            mock_session.return_value = mock_db
            
            mock_job = Mock()
            mock_job.id = job_id
            mock_job.status = JobStatus.PENDING
            mock_db.query.return_value.filter.return_value.first.return_value = mock_job
            
            result = update_job_status(
                job_id,
                JobStatus.RUNNING,
                progress=50,
                output_data={"step": "processing"}
            )
            
            assert result is not None
            assert result.status == JobStatus.RUNNING
            assert result.progress == 50
            mock_db.commit.assert_called_once()

    def test_update_job_status_job_not_found(self):
        """Test job status update when job doesn't exist."""
        job_id = "nonexistent_job"
        
        with patch('app.tasks.model_flows.SessionLocal') as mock_session:
            mock_db = Mock()
            mock_session.return_value = mock_db
            mock_db.query.return_value.filter.return_value.first.return_value = None
            
            result = update_job_status(job_id, JobStatus.RUNNING)
            
            assert result is None

    def test_ensure_idempotency_first_execution(self):
        """Test idempotency check for first execution."""
        job_id = "test_job_123"
        request_id = "req_123"
        
        with patch('app.tasks.model_flows.SessionLocal') as mock_session:
            mock_db = Mock()
            mock_session.return_value = mock_db
            
            mock_job = Mock()
            mock_job.id = job_id
            mock_job.status = JobStatus.PENDING
            mock_db.query.return_value.filter.return_value.first.return_value = mock_job
            
            result = ensure_idempotency(job_id, request_id)
            
            assert result is True
            assert mock_job.status == JobStatus.RUNNING
            mock_db.commit.assert_called_once()

    def test_ensure_idempotency_already_processed(self):
        """Test idempotency check for already processed job."""
        job_id = "test_job_123"
        request_id = "req_123"
        
        with patch('app.tasks.model_flows.SessionLocal') as mock_session:
            mock_db = Mock()
            mock_session.return_value = mock_db
            
            mock_job = Mock()
            mock_job.id = job_id
            mock_job.status = JobStatus.COMPLETED  # Already completed
            mock_db.query.return_value.filter.return_value.first.return_value = mock_job
            
            result = ensure_idempotency(job_id, request_id)
            
            assert result is False  # Should not process again

    def test_turkish_terminology_mapping(self):
        """Test Turkish terminology is correctly applied."""
        from app.tasks.fem_simulation import get_turkish_term
        
        # Test known terms
        assert get_turkish_term("stress") == "gerilme"
        assert get_turkish_term("displacement") == "yer değiştirme"
        assert get_turkish_term("constraint") == "kısıt"
        assert get_turkish_term("buckling") == "burkulma"
        
        # Test unknown term returns original
        assert get_turkish_term("unknown_term") == "unknown_term"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])