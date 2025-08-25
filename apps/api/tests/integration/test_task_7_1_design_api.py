"""
Integration tests for Task 7.1: Design API v1 endpoints.

Tests cover:
- All four design input types (prompt, params, upload, a4)
- JWT authentication and authorization
- License validation
- Rate limiting
- Idempotency handling
- Turkish error messages
- OpenAPI compliance
"""

import json
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models import User, License, Job
from app.models.enums import UserRole, JobStatus
from app.services.jwt_service import jwt_service
from app.db import get_db


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def db_session():
    """Create database session for tests."""
    db = next(get_db())
    yield db
    db.close()


@pytest.fixture
def test_user(db_session):
    """Create test user with license."""
    user = User(
        id=uuid4(),
        email="test@example.com",
        first_name="Test",
        last_name="User",
        role=UserRole.ENGINEER,
        is_active=True
    )
    db_session.add(user)
    
    # Create license with required features
    license = License(
        id=uuid4(),
        user_id=user.id,
        license_key=f"TEST-{uuid4().hex[:8]}",
        plan_name="enterprise",
        features={
            "ai_generation": True,
            "parametric_design": True,
            "file_import": True,
            "assembly_design": True,
            "model_creation": True
        },
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        is_active=True
    )
    db_session.add(license)
    db_session.commit()
    
    return user, license


@pytest.fixture
def auth_headers(test_user):
    """Create JWT authentication headers."""
    user, license = test_user
    
    # Create JWT claims with required fields for Task 7.1
    claims = {
        "sub": str(user.id),
        "role": user.role.value,
        "scopes": ["models:write", "models:read"],
        "sid": str(uuid4()),
        "license_id": str(license.id),
        "tenant_id": str(uuid4()),
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        "jti": str(uuid4())
    }
    
    token = jwt_service.create_test_token(claims)
    return {"Authorization": f"Bearer {token}"}


class TestDesignPromptEndpoint:
    """Test POST /api/v1/designs/prompt endpoint."""
    
    def test_create_design_from_prompt_success(self, client, auth_headers):
        """Test successful AI prompt design creation."""
        request_body = {
            "design": {
                "type": "prompt",
                "prompt": "10mm çapında 50mm uzunluğunda paslanmaz çelik mil tasarla",
                "context": "CNC torna için",
                "max_iterations": 3,
                "temperature": 0.7
            },
            "priority": 5,
            "chain_cam": False,
            "chain_sim": False
        }
        
        response = client.post(
            "/api/v1/designs/prompt",
            json=request_body,
            headers=auth_headers
        )
        
        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "accepted"
        assert data["queue"] == "model"
        assert response.headers.get("API-Version") == "1"
    
    def test_prompt_without_auth_fails(self, client):
        """Test that prompt endpoint requires authentication."""
        request_body = {
            "design": {
                "type": "prompt",
                "prompt": "Test prompt"
            }
        }
        
        response = client.post(
            "/api/v1/designs/prompt",
            json=request_body
        )
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_prompt_rate_limiting(self, client, auth_headers, monkeypatch):
        """Test prompt-specific rate limiting (30/min)."""
        from ...core.rate_limiter import RateLimiter
        
        # Mock the rate limiter to simulate rate limit exceeded
        def mock_check_rate_limit(self, key):
            # Return False on the second call to simulate rate limit
            if not hasattr(self, '_call_count'):
                self._call_count = 0
            self._call_count += 1
            return self._call_count <= 1
        
        def mock_get_remaining(self, key):
            return 0, 45  # 0 remaining, reset in 45 seconds
        
        monkeypatch.setattr(RateLimiter, "check_rate_limit", mock_check_rate_limit)
        monkeypatch.setattr(RateLimiter, "get_remaining", mock_get_remaining)
        
        request_body = {
            "design": {
                "type": "prompt",
                "prompt": "Test prompt for rate limiting"
            }
        }
        
        # First request should succeed
        response1 = client.post(
            "/api/v1/designs/prompt",
            json=request_body,
            headers=auth_headers
        )
        assert response1.status_code == status.HTTP_202_ACCEPTED
        
        # Second request should be rate limited
        response2 = client.post(
            "/api/v1/designs/prompt",
            json=request_body,
            headers=auth_headers
        )
        assert response2.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "retry_after" in response2.json()["detail"]
    
    def test_prompt_idempotency(self, client, auth_headers):
        """Test idempotency key handling."""
        idempotency_key = f"test-{uuid4()}"
        request_body = {
            "design": {
                "type": "prompt",
                "prompt": "Test prompt for idempotency"
            }
        }
        
        headers = {**auth_headers, "Idempotency-Key": idempotency_key}
        
        # First request
        response1 = client.post(
            "/api/v1/designs/prompt",
            json=request_body,
            headers=headers
        )
        assert response1.status_code == status.HTTP_202_ACCEPTED
        data1 = response1.json()
        
        # Second request with same idempotency key
        response2 = client.post(
            "/api/v1/designs/prompt",
            json=request_body,
            headers=headers
        )
        assert response2.status_code == status.HTTP_202_ACCEPTED
        data2 = response2.json()
        
        # Should return same job
        assert data2["job_id"] == data1["job_id"]
        assert data2["status"] == "duplicate"
    
    def test_prompt_validation_errors(self, client, auth_headers):
        """Test validation errors with Turkish messages."""
        # Prompt too short
        request_body = {
            "design": {
                "type": "prompt",
                "prompt": "ab"  # Less than 10 characters
            }
        }
        
        response = client.post(
            "/api/v1/designs/prompt",
            json=request_body,
            headers=auth_headers
        )
        
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestDesignParametricEndpoint:
    """Test POST /api/v1/designs/params endpoint."""
    
    def test_create_design_from_params_success(self, client, auth_headers):
        """Test successful parametric design creation."""
        request_body = {
            "design": {
                "type": "params",
                "template_id": "shaft_template_v1",
                "dimensions": {
                    "diameter": {
                        "value": 10.0,
                        "unit": "mm",
                        "tolerance": 0.1
                    },
                    "length": {
                        "value": 50.0,
                        "unit": "mm"
                    }
                },
                "material": {
                    "type": "steel",
                    "grade": "316L"
                },
                "process": "cnc_turning",
                "quantity": 10
            },
            "priority": 5
        }
        
        response = client.post(
            "/api/v1/designs/params",
            json=request_body,
            headers=auth_headers
        )
        
        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert "job_id" in data
        assert data["queue"] == "model"
    
    def test_params_material_process_incompatibility(self, client, auth_headers):
        """Test material-process compatibility validation."""
        request_body = {
            "design": {
                "type": "params",
                "template_id": "test_template",
                "dimensions": {
                    "width": {"value": 100, "unit": "mm"}
                },
                "material": {
                    "type": "plastic_abs"  # ABS plastic
                },
                "process": "cnc_turning"  # Incompatible with ABS
            }
        }
        
        response = client.post(
            "/api/v1/designs/params",
            json=request_body,
            headers=auth_headers
        )
        
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "uyumlu değil" in response.json().get("detail", "").lower()
    
    def test_params_dimension_validation(self, client, auth_headers):
        """Test dimension validation."""
        request_body = {
            "design": {
                "type": "params",
                "template_id": "test_template",
                "dimensions": {
                    "width": {"value": -10, "unit": "mm"}  # Negative dimension
                },
                "material": {"type": "steel"},
                "process": "cnc_milling"
            }
        }
        
        response = client.post(
            "/api/v1/designs/params",
            json=request_body,
            headers=auth_headers
        )
        
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestDesignUploadEndpoint:
    """Test POST /api/v1/designs/upload endpoint."""
    
    def test_create_design_from_upload_success(self, client, auth_headers, monkeypatch):
        """Test successful file upload processing."""
        # Mock S3 service to always return True for object existence
        from ...storage import s3_service
        
        def mock_object_exists(key):
            return True
        
        monkeypatch.setattr(s3_service, "object_exists", mock_object_exists)
        
        request_body = {
            "design": {
                "type": "upload",
                "s3_key": "uploads/test-model.step",
                "file_format": ".step",
                "file_size": 1024000,  # 1MB
                "sha256": "a" * 64,  # Mock SHA256
                "conversion_target": ".stl"
            },
            "priority": 3
        }
        
        response = client.post(
            "/api/v1/designs/upload",
            json=request_body,
            headers=auth_headers
        )
        
        # With mocked S3, should always succeed
        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "accepted"
    
    def test_upload_file_size_limit(self, client, auth_headers):
        """Test file size limit validation (100MB)."""
        request_body = {
            "design": {
                "type": "upload",
                "s3_key": "uploads/huge-file.step",
                "file_format": ".step",
                "file_size": 200 * 1024 * 1024,  # 200MB - over limit
                "sha256": "a" * 64
            }
        }
        
        response = client.post(
            "/api/v1/designs/upload",
            json=request_body,
            headers=auth_headers
        )
        
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    
    def test_upload_invalid_format(self, client, auth_headers):
        """Test invalid file format validation."""
        request_body = {
            "design": {
                "type": "upload",
                "s3_key": "uploads/test.txt",
                "file_format": ".txt",  # Invalid format
                "file_size": 1024,
                "sha256": "a" * 64
            }
        }
        
        response = client.post(
            "/api/v1/designs/upload",
            json=request_body,
            headers=auth_headers
        )
        
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestAssembly4Endpoint:
    """Test POST /api/v1/assemblies/a4 endpoint."""
    
    def test_create_assembly4_success(self, client, auth_headers):
        """Test successful Assembly4 creation."""
        request_body = {
            "design": {
                "type": "a4",
                "parts": [
                    {
                        "name": "shaft",
                        "part_type": "cylinder",
                        "radius": 5,
                        "height": 50
                    },
                    {
                        "name": "base_plate",
                        "part_type": "box",
                        "width": 30,
                        "height": 5,
                        "depth": 30
                    }
                ],
                "constraints": [
                    {
                        "type": "coincident",
                        "part1": "shaft",
                        "part2": "base_plate",
                        "feature1": "BottomFace",
                        "feature2": "TopFace"
                    }
                ],
                "validate_assembly": True,
                "generate_bom": True
            },
            "priority": 7
        }
        
        response = client.post(
            "/api/v1/assemblies/a4",
            json=request_body,
            headers=auth_headers
        )
        
        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert "job_id" in data
        assert data["queue"] == "model"
    
    def test_assembly4_constraint_validation(self, client, auth_headers):
        """Test Assembly4 constraint validation."""
        request_body = {
            "design": {
                "type": "a4",
                "parts": [
                    {
                        "name": "part1",
                        "type": "cylinder",
                        "dimensions": {"radius": 10, "height": 50}
                    },
                    {
                        "name": "part2",
                        "type": "box",
                        "dimensions": {"width": 20, "length": 30, "height": 15}
                    }
                ],
                "constraints": [
                    {
                        "type": "distance",
                        "part1": "part1",
                        "part2": "part2",
                        # Missing required 'value' for distance constraint
                    }
                ]
            }
        }
        
        response = client.post(
            "/api/v1/assemblies/a4",
            json=request_body,
            headers=auth_headers
        )
        
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "değer gerekli" in response.json().get("detail", "").lower()
    
    def test_assembly4_minimum_parts(self, client, auth_headers):
        """Test minimum parts requirement for assembly."""
        request_body = {
            "design": {
                "type": "a4",
                "parts": [
                    {
                        "name": "single_part",
                        "path": "models/single_part.FCStd"
                    }
                ],  # Only one part
                "constraints": []
            }
        }
        
        response = client.post(
            "/api/v1/assemblies/a4",
            json=request_body,
            headers=auth_headers
        )
        
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestCrossEndpointValidation:
    """Test cross-endpoint validation and type checking."""
    
    def test_wrong_input_type_for_prompt_endpoint(self, client, auth_headers):
        """Test sending params input to prompt endpoint."""
        request_body = {
            "design": {
                "type": "params",  # Wrong type for prompt endpoint
                "template_id": "test"
            }
        }
        
        response = client.post(
            "/api/v1/designs/prompt",
            json=request_body,
            headers=auth_headers
        )
        
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "prompt" in response.json().get("detail", "").lower()
    
    def test_api_versioning_headers(self, client, auth_headers):
        """Test API versioning headers."""
        endpoints = [
            "/api/v1/designs/prompt",
            "/api/v1/designs/params",
            "/api/v1/designs/upload",
            "/api/v1/assemblies/a4"
        ]
        
        for endpoint in endpoints:
            # Create appropriate request body based on endpoint
            if "prompt" in endpoint:
                body = {"design": {"type": "prompt", "prompt": "Test prompt"}}
            elif "params" in endpoint:
                body = {
                    "design": {
                        "type": "params",
                        "template_id": "test",
                        "dimensions": {"w": {"value": 10, "unit": "mm"}},
                        "material": {"type": "steel"},
                        "process": "cnc_milling"
                    }
                }
            elif "upload" in endpoint:
                body = {
                    "design": {
                        "type": "upload",
                        "s3_key": "test.step",
                        "file_format": ".step",
                        "file_size": 1024,
                        "sha256": "a" * 64
                    }
                }
            else:  # a4
                body = {
                    "design": {
                        "type": "a4",
                        "parts": [
                            {
                                "name": "p1",
                                "part_type": "cylinder",
                                "radius": 5,
                                "height": 20
                            },
                            {
                                "name": "p2",
                                "part_type": "box",
                                "width": 10,
                                "depth": 10,
                                "height": 10
                            }
                        ],
                        "constraints": [
                            {"type": "parallel", "part1": "p1", "part2": "p2"}
                        ]
                    }
                }
            
            response = client.post(endpoint, json=body, headers=auth_headers)
            
            # Check API version headers
            assert response.headers.get("API-Version") == "1"
            assert response.headers.get("X-API-Version") == "1"


class TestLicenseValidation:
    """Test license validation for design endpoints."""
    
    def test_expired_license_rejected(self, client, db_session):
        """Test that expired license is rejected."""
        # Create user with expired license
        user = User(
            id=uuid4(),
            email="expired@example.com",
            role=UserRole.ENGINEER,
            is_active=True
        )
        db_session.add(user)
        
        license = License(
            id=uuid4(),
            user_id=user.id,
            license_key="EXPIRED-123",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),  # Expired
            is_active=True
        )
        db_session.add(license)
        db_session.commit()
        
        # Create JWT with expired license
        claims = {
            "sub": str(user.id),
            "role": user.role.value,
            "scopes": ["models:write"],
            "sid": str(uuid4()),
            "license_id": str(license.id),
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
            "jti": str(uuid4())
        }
        
        token = jwt_service.create_test_token(claims)
        headers = {"Authorization": f"Bearer {token}"}
        
        request_body = {
            "design": {
                "type": "prompt",
                "prompt": "Test with expired license"
            }
        }
        
        response = client.post(
            "/api/v1/designs/prompt",
            json=request_body,
            headers=headers
        )
        
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "lisans" in response.json().get("detail", "").lower()
    
    def test_missing_license_feature(self, client, db_session):
        """Test that missing license feature is rejected."""
        # Create user with limited license
        user = User(
            id=uuid4(),
            email="limited@example.com",
            role=UserRole.ENGINEER,
            is_active=True
        )
        db_session.add(user)
        
        license = License(
            id=uuid4(),
            user_id=user.id,
            license_key="LIMITED-123",
            features={
                "model_creation": True,
                # Missing "ai_generation" feature
            },
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            is_active=True
        )
        db_session.add(license)
        db_session.commit()
        
        # Create JWT
        claims = {
            "sub": str(user.id),
            "role": user.role.value,
            "scopes": ["models:write"],
            "sid": str(uuid4()),
            "license_id": str(license.id),
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
            "jti": str(uuid4())
        }
        
        token = jwt_service.create_test_token(claims)
        headers = {"Authorization": f"Bearer {token}"}
        
        request_body = {
            "design": {
                "type": "prompt",
                "prompt": "Test without AI feature"
            }
        }
        
        response = client.post(
            "/api/v1/designs/prompt",
            json=request_body,
            headers=headers
        )
        
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "ai_generation" in response.json().get("detail", "").lower()


class TestCrossEndpointIdempotency:
    """Test that idempotency keys are properly scoped by job type."""
    
    def test_same_idempotency_key_different_endpoints(self, client, auth_headers, db_session):
        """
        Test that the same idempotency key can be used across different endpoints.
        This verifies the fix for HIGH severity feedback where idempotency was not
        properly scoped by job type.
        """
        idempotency_key = str(uuid4())
        headers = {**auth_headers, "Idempotency-Key": idempotency_key}
        
        # 1. Create a job via prompt endpoint (JobType.MODEL)
        prompt_body = {
            "design": {
                "type": "prompt",
                "prompt": "Create a simple cube"
            },
            "priority": 5
        }
        
        prompt_response = client.post(
            "/api/v1/designs/prompt",
            json=prompt_body,
            headers=headers
        )
        assert prompt_response.status_code == status.HTTP_202_ACCEPTED
        prompt_job_id = prompt_response.json()["job_id"]
        
        # 2. Use the SAME idempotency key for assembly endpoint (JobType.ASSEMBLY)
        assembly_body = {
            "design": {
                "type": "a4",
                "parts": [
                    {
                        "name": "part1",
                        "part_type": "existing",
                        "path": "models/part1.FCStd"
                    },
                    {
                        "name": "part2", 
                        "part_type": "existing",
                        "path": "models/part2.FCStd"
                    }
                ],
                "constraints": [
                    {
                        "type": "concentric",
                        "part1": "part1",
                        "part2": "part2",
                        "feature1": "Edge1",
                        "feature2": "Edge1"
                    }
                ]
            },
            "priority": 5
        }
        
        assembly_response = client.post(
            "/api/v1/assemblies/a4",
            json=assembly_body,
            headers=headers
        )
        
        # Should succeed because it's a different job type (ASSEMBLY vs MODEL)
        assert assembly_response.status_code == status.HTTP_202_ACCEPTED
        assembly_job_id = assembly_response.json()["job_id"]
        
        # Verify they created different jobs
        assert prompt_job_id != assembly_job_id
        
        # 3. Verify idempotency still works within same endpoint
        prompt_retry = client.post(
            "/api/v1/designs/prompt",
            json=prompt_body,
            headers=headers
        )
        assert prompt_retry.status_code == status.HTTP_202_ACCEPTED
        assert prompt_retry.json()["job_id"] == prompt_job_id
        assert prompt_retry.json()["status"] == "duplicate"
        
        assembly_retry = client.post(
            "/api/v1/assemblies/a4",
            json=assembly_body,
            headers=headers
        )
        assert assembly_retry.status_code == status.HTTP_202_ACCEPTED
        assert assembly_retry.json()["job_id"] == assembly_job_id
        assert assembly_retry.json()["status"] == "duplicate"
        
        # 4. Verify database has correct job types
        from ..models import Job
        prompt_job = db_session.query(Job).filter_by(id=prompt_job_id).first()
        assert prompt_job.type == JobType.MODEL
        
        assembly_job = db_session.query(Job).filter_by(id=assembly_job_id).first()
        assert assembly_job.type == JobType.ASSEMBLY
    
    def test_upload_endpoint_uses_correct_job_type(self, client, auth_headers, db_session):
        """Test that upload endpoint uses CAD_IMPORT job type."""
        idempotency_key = str(uuid4())
        headers = {**auth_headers, "Idempotency-Key": idempotency_key}
        
        upload_body = {
            "design": {
                "type": "upload",
                "s3_key": "uploads/test.step",
                "file_format": ".step",
                "file_size": 12345,
                "sha256": "a" * 64  # Valid 64-character SHA256 hash
            },
            "priority": 5
        }
        
        response = client.post(
            "/api/v1/designs/upload",
            json=upload_body,
            headers=headers
        )
        
        assert response.status_code == status.HTTP_202_ACCEPTED
        job_id = response.json()["job_id"]
        
        # Verify job type in database
        from ..models import Job
        job = db_session.query(Job).filter_by(id=job_id).first()
        assert job.type == JobType.CAD_IMPORT


if __name__ == "__main__":
    pytest.main([__file__, "-v"])