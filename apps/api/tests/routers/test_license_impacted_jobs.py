"""
Tests for license impacted jobs endpoint (Task 4.9).
"""

import pytest
from unittest.mock import Mock, patch
import uuid

from fastapi import status
from sqlalchemy.orm import Session

from app.models.license import License
from app.models.enums import UserRole


@pytest.fixture
def admin_user():
    """Create an admin user."""
    from app.middleware.jwt_middleware import AuthenticatedUser
    user = AuthenticatedUser(
        id=1,
        email="admin@example.com",
        role=UserRole.ADMIN
    )
    return user


@pytest.fixture
def regular_user():
    """Create a regular user."""
    from app.middleware.jwt_middleware import AuthenticatedUser
    user = AuthenticatedUser(
        id=2,
        email="user@example.com",
        role=UserRole.OPERATOR
    )
    return user


@pytest.fixture
def sample_license():
    """Create a sample license."""
    license = Mock(spec=License)
    license.id = 1
    license.user_id = 2
    license.status = "expired"
    return license


@pytest.fixture
def impacted_jobs_data():
    """Sample impacted jobs data."""
    return [
        {
            "id": 1,
            "type": "cad_generate",
            "status": "cancelled",
            "cancel_requested": True,
            "cancellation_reason": "license_expired",
            "created_at": "2024-01-01T10:00:00Z",
            "started_at": "2024-01-01T10:05:00Z",
            "finished_at": "2024-01-01T10:10:00Z",
            "progress": 50
        },
        {
            "id": 2,
            "type": "cam_process",
            "status": "running",
            "cancel_requested": True,
            "cancellation_reason": "license_expired",
            "created_at": "2024-01-01T10:00:00Z",
            "started_at": "2024-01-01T10:05:00Z",
            "finished_at": None,
            "progress": 30
        }
    ]


def test_get_impacted_jobs_success(
    client, admin_user, sample_license, impacted_jobs_data, db_session
):
    """Test successful retrieval of impacted jobs by admin."""
    
    with patch('app.routers.license_impacted_jobs.get_current_user', return_value=admin_user):
        with patch('app.routers.license_impacted_jobs.get_db', return_value=db_session):
            with patch('app.routers.license_impacted_jobs.rbac_business_service') as mock_rbac:
                mock_rbac.has_any_role.return_value = True
                
                # Mock database query
                db_session.query().filter().first.return_value = sample_license
                
                # Mock job cancellation service
                with patch('app.routers.license_impacted_jobs.job_cancellation_service') as mock_service:
                    mock_service.get_impacted_jobs_for_license.return_value = impacted_jobs_data
                    
                    # Make request
                    response = client.get("/api/v1/licenses/1/impacted-jobs")
    
    # Verify response
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["license_id"] == 1
    assert data["user_id"] == 2
    assert data["license_status"] == "expired"
    assert len(data["impacted_jobs"]) == 2
    assert data["total_count"] == 2
    assert data["message"] == "Impacted jobs retrieved successfully"
    assert data["message_tr"] == "Etkilenen işler başarıyla alındı"


def test_get_impacted_jobs_forbidden_non_admin(
    client, regular_user, db_session
):
    """Test that non-admin users cannot access impacted jobs."""
    
    with patch('app.routers.license_impacted_jobs.get_current_user', return_value=regular_user):
        with patch('app.routers.license_impacted_jobs.get_db', return_value=db_session):
            with patch('app.routers.license_impacted_jobs.rbac_business_service') as mock_rbac:
                mock_rbac.has_any_role.return_value = False
                
                # Make request
                response = client.get("/api/v1/licenses/1/impacted-jobs")
    
    # Verify response
    assert response.status_code == status.HTTP_403_FORBIDDEN
    data = response.json()
    assert data["detail"]["error"] == "FORBIDDEN"
    assert data["detail"]["message"] == "Admin access required"
    assert data["detail"]["message_tr"] == "Yönetici erişimi gerekli"


def test_get_impacted_jobs_license_not_found(
    client, admin_user, db_session
):
    """Test retrieving impacted jobs for non-existent license."""
    
    with patch('app.routers.license_impacted_jobs.get_current_user', return_value=admin_user):
        with patch('app.routers.license_impacted_jobs.get_db', return_value=db_session):
            with patch('app.routers.license_impacted_jobs.rbac_business_service') as mock_rbac:
                mock_rbac.has_any_role.return_value = True
                
                # Mock database query - license not found
                db_session.query().filter().first.return_value = None
                
                # Make request
                response = client.get("/api/v1/licenses/999/impacted-jobs")
    
    # Verify response
    assert response.status_code == status.HTTP_404_NOT_FOUND
    data = response.json()
    assert data["detail"]["error"] == "NOT_FOUND"
    assert data["detail"]["message"] == "License not found"
    assert data["detail"]["message_tr"] == "Lisans bulunamadı"


def test_get_impacted_jobs_no_impacted_jobs(
    client, admin_user, sample_license, db_session
):
    """Test retrieving impacted jobs when there are none."""
    
    with patch('app.routers.license_impacted_jobs.get_current_user', return_value=admin_user):
        with patch('app.routers.license_impacted_jobs.get_db', return_value=db_session):
            with patch('app.routers.license_impacted_jobs.rbac_business_service') as mock_rbac:
                mock_rbac.has_any_role.return_value = True
                
                # Mock database query
                db_session.query().filter().first.return_value = sample_license
                
                # Mock job cancellation service - no impacted jobs
                with patch('app.routers.license_impacted_jobs.job_cancellation_service') as mock_service:
                    mock_service.get_impacted_jobs_for_license.return_value = []
                    
                    # Make request
                    response = client.get("/api/v1/licenses/1/impacted-jobs")
    
    # Verify response
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["license_id"] == 1
    assert data["impacted_jobs"] == []
    assert data["total_count"] == 0


def test_get_impacted_jobs_service_error(
    client, admin_user, sample_license, db_session
):
    """Test handling of service errors."""
    
    with patch('app.routers.license_impacted_jobs.get_current_user', return_value=admin_user):
        with patch('app.routers.license_impacted_jobs.get_db', return_value=db_session):
            with patch('app.routers.license_impacted_jobs.rbac_business_service') as mock_rbac:
                mock_rbac.has_any_role.return_value = True
                
                # Mock database query
                db_session.query().filter().first.return_value = sample_license
                
                # Mock job cancellation service - raise error
                with patch('app.routers.license_impacted_jobs.job_cancellation_service') as mock_service:
                    mock_service.get_impacted_jobs_for_license.side_effect = Exception("Service error")
                    
                    # Make request
                    response = client.get("/api/v1/licenses/1/impacted-jobs")
    
    # Verify response
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    data = response.json()
    assert data["detail"]["error"] == "INTERNAL_ERROR"
    assert data["detail"]["message"] == "Failed to retrieve impacted jobs"
    assert data["detail"]["message_tr"] == "Etkilenen işler alınamadı"