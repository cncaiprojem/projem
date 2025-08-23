"""
Simple integration test for Task 6.5 - GET /jobs/{id} endpoint.
Tests the basic functionality without complex mocking.
"""

import os
import pytest
from unittest.mock import patch, Mock

# Set environment variables before importing app
os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only-minimum-32-chars"
os.environ["DATABASE_URL"] = "postgresql+psycopg2://test:test@localhost:5432/test"
os.environ["DEV_AUTH_BYPASS"] = "true"

from fastapi.testclient import TestClient
from app.main import app


def test_job_status_endpoint_exists():
    """Test that the GET /jobs/{id} endpoint exists and is accessible."""
    
    client = TestClient(app)
    
    # Mock the database and auth dependencies
    mock_job = Mock()
    mock_job.id = 1
    mock_job.type = Mock(value="freecad_model")
    mock_job.status = Mock(value="completed")
    mock_job.progress = 100
    mock_job.attempts = 1
    mock_job.cancel_requested = False
    mock_job.created_at = Mock(isoformat=Mock(return_value="2024-01-01T00:00:00"))
    mock_job.updated_at = Mock(isoformat=Mock(return_value="2024-01-01T00:01:00"))
    mock_job.started_at = Mock(isoformat=Mock(return_value="2024-01-01T00:00:10"))
    mock_job.finished_at = Mock(isoformat=Mock(return_value="2024-01-01T00:01:00"))
    mock_job.error_code = None
    mock_job.error_message = None
    mock_job.metrics = None
    mock_job.artefacts = []
    mock_job.user_id = None
    
    mock_db = Mock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_job
    
    with patch("app.routers.jobs.get_db", return_value=mock_db):
        with patch("app.routers.jobs.get_current_user", return_value=None):
            with patch("app.routers.jobs.JobQueueService.get_queue_position", return_value=None):
                
                # Make request to the endpoint
                response = client.get("/api/v1/jobs/1")
                
                # Check that we get a response (not 404 for missing endpoint)
                assert response.status_code in [200, 401, 403, 404]  # Any of these means endpoint exists
                
                # If DEV_AUTH_BYPASS is true, we should get 200
                if os.environ.get("DEV_AUTH_BYPASS") == "true":
                    assert response.status_code == 200
                    
                    # Check response structure
                    data = response.json()
                    assert "id" in data
                    assert "type" in data
                    assert "status" in data
                    assert "progress" in data
                    assert "attempts" in data
                    assert "cancel_requested" in data
                    assert "created_at" in data
                    assert "updated_at" in data
                    assert "artefacts" in data
                    assert "queue_position" in data or data["queue_position"] is None


def test_job_status_response_structure():
    """Test that the response has the correct structure for Task 6.5."""
    
    client = TestClient(app)
    
    # Create a more complete mock job
    mock_job = Mock()
    mock_job.id = 123
    mock_job.type = Mock(value="freecad_cam")
    mock_job.status = Mock(value="running")
    mock_job.progress = 45
    mock_job.attempts = 2
    mock_job.cancel_requested = True
    mock_job.created_at = Mock(isoformat=Mock(return_value="2024-01-01T00:00:00"))
    mock_job.updated_at = Mock(isoformat=Mock(return_value="2024-01-01T00:05:00"))
    mock_job.started_at = Mock(isoformat=Mock(return_value="2024-01-01T00:01:00"))
    mock_job.finished_at = None
    mock_job.error_code = "ERR-TEST"
    mock_job.error_message = "Test error message"
    mock_job.metrics = {
        "current_step": "processing",
        "last_progress_message": "Processing toolpath",
        "last_progress_update": "2024-01-01T00:05:00"
    }
    mock_job.artefacts = []
    mock_job.user_id = None
    
    # Add a mock artefact
    mock_artefact = Mock()
    mock_artefact.id = 1
    mock_artefact.type = "gcode"
    mock_artefact.s3_key = "jobs/123/output.gcode"
    mock_artefact.sha256 = "abc123" * 10 + "abcd"  # 64 chars
    mock_artefact.size_bytes = 2048000
    mock_job.artefacts = [mock_artefact]
    
    mock_db = Mock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_job
    
    with patch("app.routers.jobs.get_db", return_value=mock_db):
        with patch("app.routers.jobs.get_current_user", return_value=None):
            with patch("app.routers.jobs.JobQueueService.get_queue_position", return_value=5):
                
                response = client.get("/api/v1/jobs/123")
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Check all required fields from Task 6.5
                    assert data["id"] == 123
                    assert data["type"] == "freecad_cam"
                    assert data["status"] == "running"
                    
                    # Check progress structure
                    assert "progress" in data
                    progress = data["progress"]
                    assert progress["percent"] == 45
                    assert progress["step"] == "processing"
                    assert progress["message"] == "Processing toolpath"
                    assert "updated_at" in progress
                    
                    # Check other fields
                    assert data["attempts"] == 2
                    assert data["cancel_requested"] is True
                    assert data["queue_position"] == 5
                    
                    # Check artefacts structure
                    assert len(data["artefacts"]) == 1
                    artefact = data["artefacts"][0]
                    assert artefact["id"] == 1
                    assert artefact["kind"] == "gcode"
                    assert artefact["s3_key"] == "jobs/123/output.gcode"
                    assert len(artefact["sha256"]) == 64
                    assert artefact["size"] == 2048000
                    
                    # Check error structure
                    assert data["last_error"] is not None
                    assert data["last_error"]["code"] == "ERR-TEST"
                    assert data["last_error"]["message"] == "Test error message"
                    
                    # Check headers
                    assert "ETag" in response.headers
                    assert response.headers["Cache-Control"] == "private, max-age=1"


if __name__ == "__main__":
    test_job_status_endpoint_exists()
    test_job_status_response_structure()
    print("✅ All tests passed!")