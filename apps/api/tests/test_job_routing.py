"""
Comprehensive tests for Task 6.3 - Job type routing and payload validation.
İş türü yönlendirmesi ve yük doğrulama için kapsamlı testler.
"""

import json
from datetime import datetime
from uuid import uuid4, UUID
import pytest
from unittest.mock import Mock, patch, MagicMock
from pydantic import ValidationError

from app.core.job_routing import (
    JobType,
    JOB_TYPE_TO_QUEUE,
    JOB_TYPE_TO_ROUTING_KEY,
    get_queue_for_job_type,
    get_routing_key_for_job_type,
    get_routing_config_for_job_type,
    validate_job_type,
)
from app.schemas.job_payload import (
    TaskPayload,
    TaskPayloadResponse,
    AIJobParams,
    ModelJobParams,
    CAMJobParams,
    SimJobParams,
    ReportJobParams,
    ERPJobParams,
    MAX_PAYLOAD_SIZE_BYTES,
)
from app.core.job_validator import (
    JobValidationError,
    validate_job_payload,
    publish_job_task,
    validate_and_publish_job,
    check_payload_size,
    get_job_error_response,
)


class TestJobRouting:
    """Test job type routing functionality."""
    
    def test_job_type_enum_values(self):
        """Test that JobType enum has correct values per Task 6.3."""
        assert JobType.AI.value == "ai"
        assert JobType.MODEL.value == "model"
        assert JobType.CAM.value == "cam"
        assert JobType.SIM.value == "sim"
        assert JobType.REPORT.value == "report"
        assert JobType.ERP.value == "erp"
    
    def test_job_type_to_queue_mapping(self):
        """Test job type to queue mapping per Task 6.3 specification."""
        assert JOB_TYPE_TO_QUEUE[JobType.AI] == "default"
        assert JOB_TYPE_TO_QUEUE[JobType.MODEL] == "model"
        assert JOB_TYPE_TO_QUEUE[JobType.CAM] == "cam"
        assert JOB_TYPE_TO_QUEUE[JobType.SIM] == "sim"
        assert JOB_TYPE_TO_QUEUE[JobType.REPORT] == "report"
        assert JOB_TYPE_TO_QUEUE[JobType.ERP] == "erp"
    
    def test_job_type_to_routing_key_mapping(self):
        """Test job type to routing key mapping (jobs.<type>)."""
        assert JOB_TYPE_TO_ROUTING_KEY[JobType.AI] == "jobs.ai"
        assert JOB_TYPE_TO_ROUTING_KEY[JobType.MODEL] == "jobs.model"
        assert JOB_TYPE_TO_ROUTING_KEY[JobType.CAM] == "jobs.cam"
        assert JOB_TYPE_TO_ROUTING_KEY[JobType.SIM] == "jobs.sim"
        assert JOB_TYPE_TO_ROUTING_KEY[JobType.REPORT] == "jobs.report"
        assert JOB_TYPE_TO_ROUTING_KEY[JobType.ERP] == "jobs.erp"
    
    def test_get_queue_for_job_type(self):
        """Test queue retrieval for job types."""
        assert get_queue_for_job_type(JobType.AI) == "default"
        assert get_queue_for_job_type(JobType.MODEL) == "model"
        assert get_queue_for_job_type(JobType.CAM) == "cam"
    
    def test_get_queue_for_invalid_job_type(self):
        """Test that invalid job type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown job type"):
            get_queue_for_job_type("invalid")  # type: ignore[arg-type]
    
    def test_get_routing_key_for_job_type(self):
        """Test routing key retrieval for job types."""
        assert get_routing_key_for_job_type(JobType.AI) == "jobs.ai"
        assert get_routing_key_for_job_type(JobType.MODEL) == "jobs.model"
        assert get_routing_key_for_job_type(JobType.SIM) == "jobs.sim"
    
    def test_get_routing_config_for_job_type(self):
        """Test complete routing configuration retrieval."""
        config = get_routing_config_for_job_type(JobType.MODEL)
        
        assert config["queue"] == "model"
        assert config["routing_key"] == "jobs.model"
        assert config["exchange"] == "jobs.direct"
        assert config["exchange_type"] == "direct"
    
    def test_validate_job_type_valid(self):
        """Test validation of valid job type strings."""
        assert validate_job_type("ai") == JobType.AI
        assert validate_job_type("AI") == JobType.AI
        assert validate_job_type("model") == JobType.MODEL
        assert validate_job_type("MODEL") == JobType.MODEL
    
    def test_validate_job_type_invalid(self):
        """Test validation of invalid job type strings."""
        assert validate_job_type("invalid") is None
        assert validate_job_type("") is None
        assert validate_job_type("123") is None


class TestJobPayloadSchemas:
    """Test Pydantic schemas for job payloads."""
    
    def test_task_payload_basic_validation(self):
        """Test basic TaskPayload validation."""
        payload = TaskPayload(
            job_id=uuid4(),
            type=JobType.AI,
            params={"prompt": "Generate a 3D model"},
            submitted_by=1,
            attempt=1,
        )
        
        assert payload.type == JobType.AI
        assert payload.submitted_by == 1
        assert payload.attempt == 1
        assert isinstance(payload.job_id, UUID)
    
    def test_task_payload_with_ai_params(self):
        """Test TaskPayload with AI job parameters."""
        job_id = uuid4()
        payload_data = {
            "job_id": str(job_id),
            "type": "ai",
            "params": {
                "prompt": "Generate a parametric box model",
                "ai_model_config": {"temperature": 0.7},
            },
            "submitted_by": 123,
        }
        
        payload = TaskPayload(**payload_data)
        assert payload.type == JobType.AI
        assert payload.params["prompt"] == "Generate a parametric box model"
    
    def test_task_payload_with_model_params(self):
        """Test TaskPayload with model job parameters."""
        job_id = uuid4()
        payload_data = {
            "job_id": str(job_id),
            "type": "model",
            "params": {
                "model_type": "parametric",
                "dimensions": {"x": 100.0, "y": 50.0, "z": 25.0},
                "file_keys": ["models/base.fcstd"],
            },
            "submitted_by": 456,
        }
        
        payload = TaskPayload(**payload_data)
        assert payload.type == JobType.MODEL
        assert payload.params["dimensions"]["x"] == 100.0
    
    def test_task_payload_with_cam_params(self):
        """Test TaskPayload with CAM job parameters."""
        job_id = uuid4()
        payload_data = {
            "job_id": str(job_id),
            "type": "cam",
            "params": {
                "model_key": "models/part.stl",
                "tool_config": {"diameter": 6.0, "type": "endmill"},
                "strategy": "adaptive_clear",
            },
            "submitted_by": 789,
        }
        
        payload = TaskPayload(**payload_data)
        assert payload.type == JobType.CAM
        assert payload.params["strategy"] == "adaptive_clear"
    
    def test_task_payload_invalid_params_for_job_type(self):
        """Test that invalid params for job type raise ValidationError."""
        job_id = uuid4()
        
        # AI job with model params should fail
        payload_data = {
            "job_id": str(job_id),
            "type": "ai",
            "params": {
                "model_type": "parametric",  # This is for MODEL type, not AI
                "dimensions": {"x": 100.0, "y": 50.0, "z": 25.0},
            },
            "submitted_by": 1,
        }
        
        with pytest.raises(ValidationError):
            TaskPayload(**payload_data)
    
    def test_task_payload_empty_params_rejected(self):
        """Test that empty params dictionary is rejected."""
        job_id = uuid4()
        payload_data = {
            "job_id": str(job_id),
            "type": "ai",
            "params": {},
            "submitted_by": 1,
        }
        
        with pytest.raises(ValueError, match="params cannot be empty"):
            TaskPayload(**payload_data)
    
    def test_task_payload_max_attempts(self):
        """Test attempt field validation (max 10)."""
        job_id = uuid4()
        
        # Valid attempt
        payload_data = {
            "job_id": str(job_id),
            "type": "ai",
            "params": {"prompt": "test"},
            "submitted_by": 1,
            "attempt": 10,
        }
        payload = TaskPayload(**payload_data)
        assert payload.attempt == 10
        
        # Invalid attempt (>10)
        payload_data["attempt"] = 11
        with pytest.raises(ValueError):
            TaskPayload(**payload_data)
    
    def test_task_payload_size_validation(self):
        """Test payload size validation (max 256KB)."""
        job_id = uuid4()
        
        # Create a large params object that exceeds 256KB
        # Use metadata field to avoid prompt length validation
        large_data = "x" * (MAX_PAYLOAD_SIZE_BYTES // 2)
        
        payload_data = {
            "job_id": str(job_id),
            "type": "ai",
            "params": {
                "prompt": "Test prompt",
                "metadata": {
                    "large_data_1": large_data,
                    "large_data_2": large_data,  # This will push us over the limit
                },
            },
            "submitted_by": 1,
        }
        
        with pytest.raises(ValueError, match="exceeds maximum allowed size"):
            TaskPayload(**payload_data)
    
    def test_task_payload_with_file_keys(self):
        """Test that large artifacts use file keys instead of embedding."""
        job_id = uuid4()
        
        payload_data = {
            "job_id": str(job_id),
            "type": "report",
            "params": {
                "report_type": "analysis",
                "data_keys": ["reports/data1.json", "reports/data2.csv"],
                "format": "pdf",
                "file_keys": ["reports/large_dataset.parquet"],
            },
            "submitted_by": 1,
        }
        
        payload = TaskPayload(**payload_data)
        assert "file_keys" in payload.params
        assert len(payload.params["data_keys"]) == 2


class TestJobValidator:
    """Test job validation and publishing logic."""
    
    def test_validate_job_payload_success(self):
        """Test successful job payload validation."""
        job_data = {
            "job_id": str(uuid4()),
            "type": "model",
            "params": {
                "model_type": "parametric",
                "dimensions": {"x": 100.0, "y": 50.0, "z": 25.0},
            },
            "submitted_by": 1,
        }
        
        payload, routing = validate_job_payload(job_data)
        
        assert isinstance(payload, TaskPayload)
        assert payload.type == JobType.MODEL
        assert routing["queue"] == "model"
        assert routing["routing_key"] == "jobs.model"
    
    def test_validate_job_payload_missing_type(self):
        """Test validation with missing job type (ERR-JOB-400)."""
        job_data = {
            "job_id": str(uuid4()),
            "params": {"prompt": "test"},
            "submitted_by": 1,
        }
        
        with pytest.raises(JobValidationError) as exc_info:
            validate_job_payload(job_data)
        
        assert exc_info.value.error_code == "ERR-JOB-400"
        assert "type is required" in exc_info.value.message
    
    def test_validate_job_payload_invalid_type(self):
        """Test validation with invalid job type (ERR-JOB-400)."""
        job_data = {
            "job_id": str(uuid4()),
            "type": "invalid_type",
            "params": {"prompt": "test"},
            "submitted_by": 1,
        }
        
        with pytest.raises(JobValidationError) as exc_info:
            validate_job_payload(job_data)
        
        assert exc_info.value.error_code == "ERR-JOB-400"
        assert "Invalid job type" in exc_info.value.message
        assert "valid_types" in exc_info.value.details
    
    def test_validate_job_payload_invalid_params(self):
        """Test validation with invalid params (ERR-JOB-422)."""
        job_data = {
            "job_id": str(uuid4()),
            "type": "ai",
            "params": {
                # Missing required 'prompt' field for AI job
                "invalid_field": "test",
            },
            "submitted_by": 1,
        }
        
        with pytest.raises(JobValidationError) as exc_info:
            validate_job_payload(job_data)
        
        assert exc_info.value.error_code == "ERR-JOB-422"
        assert "validation failed" in exc_info.value.message
        assert "validation_errors" in exc_info.value.details
    
    @patch("app.core.job_validator.celery_app")
    def test_publish_job_task_success(self, mock_celery):
        """Test successful job task publishing."""
        mock_result = Mock()
        mock_result.id = "task-123"
        mock_celery.send_task.return_value = mock_result
        
        payload = TaskPayload(
            job_id=uuid4(),
            type=JobType.CAM,
            params={
                "model_key": "models/part.stl",
                "tool_config": {"diameter": 6.0},
                "strategy": "adaptive",
            },
            submitted_by=1,
        )
        
        response = publish_job_task(payload)
        
        assert isinstance(response, TaskPayloadResponse)
        assert response.status == "queued"
        assert response.queue == "cam"
        assert response.routing_key == "jobs.cam"
        
        # Verify Celery was called correctly
        mock_celery.send_task.assert_called_once()
        call_args = mock_celery.send_task.call_args
        assert call_args[1]["queue"] == "cam"
        assert call_args[1]["routing_key"] == "jobs.cam"
    
    @patch("app.core.job_validator.celery_app")
    def test_validate_and_publish_job_success(self, mock_celery):
        """Test validate and publish in one step."""
        mock_result = Mock()
        mock_result.id = "task-456"
        mock_celery.send_task.return_value = mock_result
        
        job_data = {
            "job_id": str(uuid4()),
            "type": "sim",
            "params": {
                "simulation_type": "collision",
                "model_key": "models/assembly.fcstd",
                "simulation_params": {"speed": 1000},
            },
            "submitted_by": 42,
        }
        
        response = validate_and_publish_job(job_data)
        
        assert response.status == "queued"
        assert response.queue == "sim"
        assert response.routing_key == "jobs.sim"
    
    def test_check_payload_size_within_limit(self):
        """Test payload size check for data within limits."""
        small_data = {"key": "value" * 100}
        assert check_payload_size(small_data) is True
    
    def test_check_payload_size_exceeds_limit(self):
        """Test payload size check for data exceeding limits."""
        large_data = {"key": "x" * MAX_PAYLOAD_SIZE_BYTES}
        assert check_payload_size(large_data) is False
    
    def test_get_job_error_response(self):
        """Test error response formatting."""
        error = JobValidationError(
            message="Test error",
            error_code="ERR-JOB-422",
            details={"field": "test"},
        )
        
        response = get_job_error_response(error)
        
        assert response["error"] == "ERR-JOB-422"
        assert response["message"] == "Test error"
        assert response["details"]["field"] == "test"
        assert response["retryable"] is False  # 422 errors are not retryable
        
        # Test with 400 error (retryable)
        error_400 = JobValidationError(
            message="Invalid type",
            error_code="ERR-JOB-400",
        )
        response_400 = get_job_error_response(error_400)
        assert response_400["retryable"] is True


class TestIntegrationScenarios:
    """Integration tests for complete job routing scenarios."""
    
    @patch("app.core.job_validator.celery_app")
    def test_ai_job_routing_to_default_queue(self, mock_celery):
        """Test that AI jobs route to default queue."""
        mock_result = Mock()
        mock_result.id = "ai-task-1"
        mock_celery.send_task.return_value = mock_result
        
        job_data = {
            "job_id": str(uuid4()),
            "type": "ai",
            "params": {
                "prompt": "Generate optimized toolpath",
                "ai_model_config": {"temperature": 0.8},
            },
            "submitted_by": 100,
        }
        
        response = validate_and_publish_job(job_data)
        
        assert response.queue == "default"
        assert response.routing_key == "jobs.ai"
    
    @patch("app.core.job_validator.celery_app")
    def test_erp_job_routing_to_erp_queue(self, mock_celery):
        """Test that ERP jobs route to erp queue."""
        mock_result = Mock()
        mock_result.id = "erp-task-1"
        mock_celery.send_task.return_value = mock_result
        
        job_data = {
            "job_id": str(uuid4()),
            "type": "erp",
            "params": {
                "operation": "sync_invoice",
                "entity_type": "invoice",
                "data": {"invoice_id": 12345},
            },
            "submitted_by": 200,
        }
        
        response = validate_and_publish_job(job_data)
        
        assert response.queue == "erp"
        assert response.routing_key == "jobs.erp"
    
    def test_all_job_types_have_unique_queues(self):
        """Test that each job type maps to the correct queue."""
        expected_mappings = {
            JobType.AI: "default",
            JobType.MODEL: "model",
            JobType.CAM: "cam",
            JobType.SIM: "sim",
            JobType.REPORT: "report",
            JobType.ERP: "erp",
        }
        
        for job_type, expected_queue in expected_mappings.items():
            assert get_queue_for_job_type(job_type) == expected_queue
            
            # Also verify routing key format
            routing_key = get_routing_key_for_job_type(job_type)
            assert routing_key.startswith("jobs.")
    
    def test_error_codes_are_correct(self):
        """Test that error codes match Task 6.3 specification."""
        # Test ERR-JOB-400 for invalid type
        with pytest.raises(JobValidationError) as exc:
            validate_job_payload({"type": "invalid", "params": {}})
        assert exc.value.error_code == "ERR-JOB-400"
        
        # Test ERR-JOB-422 for validation errors
        with pytest.raises(JobValidationError) as exc:
            validate_job_payload({
                "job_id": "not-a-uuid",
                "type": "ai",
                "params": {"prompt": "test"},
                "submitted_by": 1,
            })
        assert exc.value.error_code == "ERR-JOB-422"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])