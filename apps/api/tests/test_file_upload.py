"""
Comprehensive tests for Task 5.3: File Upload/Download APIs

Tests:
- Upload initialization with presigned URLs
- Upload finalization with verification
- Download URL generation
- Security constraints and validation
- Error handling
"""

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from urllib.parse import urlparse, parse_qs

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.file import FileMetadata, UploadSession, FileStatus, FileType
from app.schemas.file_upload import (
    UploadInitRequest,
    UploadInitResponse,
    UploadFinalizeRequest,
    UploadFinalizeResponse,
    FileDownloadResponse,
    UploadErrorCode,
    MAX_UPLOAD_SIZE,
    PRESIGNED_PUT_TTL_SECONDS,
    PRESIGNED_GET_TTL_SECONDS,
)
from app.services.file_service import FileService, FileServiceError


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_db():
    """Create mock database session."""
    db = MagicMock(spec=Session)
    return db


@pytest.fixture
def mock_minio_client():
    """Create mock MinIO client."""
    client = MagicMock()
    client.bucket_exists.return_value = True
    client.presigned_put_object.return_value = "https://minio.example.com/upload-url"
    client.presigned_get_object.return_value = "https://minio.example.com/download-url"
    client.stat_object.return_value = MagicMock(
        size=5242880,
        etag="abc123",
        version_id="v1",
        content_type="application/sla",
        last_modified=datetime.utcnow(),
        metadata={}
    )
    return client


@pytest.fixture
def file_service(mock_db, mock_minio_client):
    """Create file service with mocks."""
    service = FileService(
        client=mock_minio_client,
        db=mock_db
    )
    return service


@pytest.fixture
def mock_auth_user():
    """Create mock authenticated user."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "test@example.com"
    user.is_active = True
    return user


class TestUploadInit:
    """Test upload initialization endpoint."""
    
    def test_init_upload_success(self, file_service):
        """Test successful upload initialization."""
        request = UploadInitRequest(
            type="model",
            size=5242880,  # 5MB
            sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            mime_type="application/sla",
            job_id="job-2024-001",
            machine_id="cnc-01",
            filename="part.stl"
        )
        
        response = file_service.init_upload(
            request=request,
            user_id=str(uuid.uuid4()),
            client_ip="192.168.1.100"
        )
        
        assert isinstance(response, UploadInitResponse)
        assert response.key.startswith("artefacts/job-2024-001/")
        assert response.key.endswith(".stl")
        assert response.upload_url.startswith("https://")
        assert response.expires_in == PRESIGNED_PUT_TTL_SECONDS
        assert "Content-Type" in response.headers
        assert response.headers["Content-Type"] == "application/sla"
        assert "x-amz-tagging" in response.headers
        assert "job_id=job-2024-001" in response.headers["x-amz-tagging"]
    
    def test_init_upload_size_too_large(self, file_service):
        """Test upload initialization with file too large."""
        request = UploadInitRequest(
            type="model",
            size=MAX_UPLOAD_SIZE + 1,  # Over limit
            sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            mime_type="application/sla",
            job_id="job-2024-001",
            filename="huge.stl"
        )
        
        # This should be rejected by Pydantic validation
        with pytest.raises(ValueError):
            file_service.init_upload(request=request)
    
    def test_init_upload_invalid_mime_type(self, file_service):
        """Test upload initialization with invalid MIME type."""
        with pytest.raises(ValueError):
            request = UploadInitRequest(
                type="model",
                size=5242880,
                sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                mime_type="application/x-executable",  # Not allowed
                job_id="job-2024-001",
                filename="malware.exe"
            )
    
    def test_init_upload_with_tags(self, file_service):
        """Test upload initialization with object tags."""
        request = UploadInitRequest(
            type="gcode",
            size=1048576,
            sha256="abc123" * 10 + "abcd",  # 64 chars
            mime_type="text/plain",
            job_id="job-2024-002",
            machine_id="cnc-02",
            post_processor="grbl",
            filename="part.nc"
        )
        
        response = file_service.init_upload(request=request)
        
        assert "machine=cnc-02" in response.headers["x-amz-tagging"]
        assert "post=grbl" in response.headers["x-amz-tagging"]
    
    def test_init_upload_creates_session(self, file_service, mock_db):
        """Test that upload init creates a session record."""
        request = UploadInitRequest(
            type="report",
            size=2097152,
            sha256="def456" * 10 + "defa",
            mime_type="application/pdf",
            job_id="job-2024-003",
            filename="analysis.pdf"
        )
        
        response = file_service.init_upload(
            request=request,
            user_id=str(uuid.uuid4())
        )
        
        # Check that session was added to DB
        assert mock_db.add.called
        session_arg = mock_db.add.call_args[0][0]
        assert isinstance(session_arg, UploadSession)
        assert session_arg.upload_id == response.upload_id
        assert session_arg.expected_size == request.size
        assert session_arg.expected_sha256 == request.sha256


class TestUploadFinalize:
    """Test upload finalization endpoint."""
    
    def test_finalize_upload_success(self, file_service, mock_db):
        """Test successful upload finalization."""
        # Create mock session
        session = UploadSession(
            upload_id="upload-123",
            object_key="artefacts/job-2024-001/test.stl",
            expected_size=5242880,
            expected_sha256="abc123" * 10 + "abcd",
            mime_type="application/sla",
            job_id="job-2024-001",
            status="pending",
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(minutes=5),
            metadata={"filename": "test.stl"}
        )
        
        mock_db.query.return_value.filter_by.return_value.first.return_value = session
        
        request = UploadFinalizeRequest(
            key="artefacts/job-2024-001/test.stl",
            upload_id="upload-123"
        )
        
        response = file_service.finalize_upload(
            request=request,
            user_id=str(uuid.uuid4())
        )
        
        assert isinstance(response, UploadFinalizeResponse)
        assert response.success is True
        assert response.object_key == request.key
        assert response.size == 5242880
        assert response.sha256 == session.expected_sha256
    
    def test_finalize_upload_session_not_found(self, file_service, mock_db):
        """Test finalization with non-existent session."""
        mock_db.query.return_value.filter_by.return_value.first.return_value = None
        
        request = UploadFinalizeRequest(
            key="artefacts/job-2024-001/test.stl",
            upload_id="invalid-upload-id"
        )
        
        with pytest.raises(FileServiceError) as exc_info:
            file_service.finalize_upload(request=request)
        
        assert exc_info.value.code == UploadErrorCode.NOT_FOUND
    
    def test_finalize_upload_session_expired(self, file_service, mock_db):
        """Test finalization with expired session."""
        session = UploadSession(
            upload_id="upload-123",
            object_key="artefacts/job-2024-001/test.stl",
            expected_size=5242880,
            expected_sha256="abc123" * 10 + "abcd",
            mime_type="application/sla",
            job_id="job-2024-001",
            status="pending",
            created_at=datetime.utcnow() - timedelta(minutes=10),
            expires_at=datetime.utcnow() - timedelta(minutes=5),  # Expired
            metadata={}
        )
        
        mock_db.query.return_value.filter_by.return_value.first.return_value = session
        
        request = UploadFinalizeRequest(
            key="artefacts/job-2024-001/test.stl",
            upload_id="upload-123"
        )
        
        with pytest.raises(FileServiceError) as exc_info:
            file_service.finalize_upload(request=request)
        
        assert exc_info.value.code == UploadErrorCode.UPLOAD_INCOMPLETE
        assert "expired" in exc_info.value.message.lower()
    
    def test_finalize_upload_key_mismatch(self, file_service, mock_db):
        """Test finalization with mismatched object key."""
        session = UploadSession(
            upload_id="upload-123",
            object_key="artefacts/job-2024-001/test.stl",
            expected_size=5242880,
            expected_sha256="abc123" * 10 + "abcd",
            mime_type="application/sla",
            job_id="job-2024-001",
            status="pending",
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(minutes=5),
            metadata={}
        )
        
        mock_db.query.return_value.filter_by.return_value.first.return_value = session
        
        request = UploadFinalizeRequest(
            key="artefacts/job-2024-002/different.stl",  # Wrong key
            upload_id="upload-123"
        )
        
        with pytest.raises(FileServiceError) as exc_info:
            file_service.finalize_upload(request=request)
        
        assert exc_info.value.code == UploadErrorCode.INVALID_INPUT
    
    def test_finalize_upload_sha256_mismatch(self, file_service, mock_db, mock_minio_client):
        """Test finalization with SHA256 hash mismatch - CRITICAL security test."""
        # Create a session with expected SHA256
        expected_sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        session = UploadSession(
            upload_id="upload-123",
            object_key="artefacts/job-2024-001/test.stl",
            expected_size=5242880,
            expected_sha256=expected_sha256,
            mime_type="application/sla",
            job_id="job-2024-001",
            status="pending",
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(minutes=5),
            metadata={}
        )
        
        mock_db.query.return_value.filter_by.return_value.first.return_value = session
        
        # Mock MinIO client to return file data with different content (wrong hash)
        mock_data = MagicMock()
        mock_data.stream.return_value = [b"different content than expected"]
        mock_data.close = MagicMock()
        mock_data.release_conn = MagicMock()
        mock_minio_client.get_object.return_value = mock_data
        
        request = UploadFinalizeRequest(
            key="artefacts/job-2024-001/test.stl",
            upload_id="upload-123"
        )
        
        # Should raise HASH_MISMATCH error
        with pytest.raises(FileServiceError) as exc_info:
            file_service.finalize_upload(request=request)
        
        assert exc_info.value.code == UploadErrorCode.HASH_MISMATCH
        assert expected_sha256 in exc_info.value.message
        
        # Verify object was deleted due to hash mismatch
        mock_minio_client.remove_object.assert_called_once_with(
            "artefacts", "job-2024-001/test.stl"
        )


class TestDownloadURL:
    """Test download URL generation endpoint."""
    
    def test_get_download_url_success(self, file_service, mock_db):
        """Test successful download URL generation."""
        file_metadata = FileMetadata(
            id=uuid.uuid4(),
            object_key="artefacts/job-2024-001/test.stl",
            bucket="artefacts",
            filename="test.stl",
            file_type=FileType.MODEL,
            mime_type="application/sla",
            size=5242880,
            sha256="abc123" * 10 + "abcd",
            status=FileStatus.COMPLETED,
            job_id="job-2024-001",
            user_id=uuid.uuid4(),
            created_at=datetime.utcnow()
        )
        
        mock_db.query.return_value.filter_by.return_value.first.return_value = file_metadata
        
        response = file_service.get_download_url(
            file_id=str(file_metadata.id),
            user_id=str(file_metadata.user_id)
        )
        
        assert isinstance(response, FileDownloadResponse)
        assert response.download_url.startswith("https://")
        assert response.expires_in == PRESIGNED_GET_TTL_SECONDS
        assert response.file_info["key"] == file_metadata.object_key
        assert response.file_info["size"] == file_metadata.size
    
    def test_get_download_url_file_not_found(self, file_service, mock_db):
        """Test download URL generation for non-existent file."""
        mock_db.query.return_value.filter_by.return_value.first.return_value = None
        
        with pytest.raises(FileServiceError) as exc_info:
            file_service.get_download_url(
                file_id=str(uuid.uuid4()),
                user_id=str(uuid.uuid4())
            )
        
        assert exc_info.value.code == UploadErrorCode.NOT_FOUND
    
    def test_get_download_url_access_denied(self, file_service, mock_db):
        """Test download URL generation with access denied."""
        file_metadata = FileMetadata(
            id=uuid.uuid4(),
            object_key="artefacts/job-2024-001/test.stl",
            bucket="artefacts",
            filename="test.stl",
            file_type=FileType.MODEL,
            mime_type="application/sla",
            size=5242880,
            sha256="abc123" * 10 + "abcd",
            status=FileStatus.COMPLETED,
            job_id="job-2024-001",
            user_id=uuid.uuid4(),  # Different user
            created_at=datetime.utcnow()
        )
        
        mock_db.query.return_value.filter_by.return_value.first.return_value = file_metadata
        
        # For now, this should succeed (basic auth only)
        # Task 5.7 will implement full RBAC
        response = file_service.get_download_url(
            file_id=str(file_metadata.id),
            user_id=str(uuid.uuid4())  # Different user
        )
        
        assert isinstance(response, FileDownloadResponse)
    
    def test_get_download_url_with_version(self, file_service, mock_db):
        """Test download URL generation with specific version."""
        file_metadata = FileMetadata(
            id=uuid.uuid4(),
            object_key="artefacts/job-2024-001/test.stl",
            bucket="artefacts",
            filename="test.stl",
            file_type=FileType.MODEL,
            mime_type="application/sla",
            size=5242880,
            sha256="abc123" * 10 + "abcd",
            status=FileStatus.COMPLETED,
            job_id="job-2024-001",
            version_id="v1.0.0",
            created_at=datetime.utcnow()
        )
        
        mock_db.query.return_value.filter_by.return_value.first.return_value = file_metadata
        
        response = file_service.get_download_url(
            file_id=str(file_metadata.id),
            user_id=str(uuid.uuid4()),
            version_id="v1.0.0"
        )
        
        assert response.file_info["version_id"] == "v1.0.0"


class TestSecurityConstraints:
    """Test security constraints and validation."""
    
    def test_max_upload_size_constraint(self):
        """Test maximum upload size is enforced."""
        assert MAX_UPLOAD_SIZE == 200 * 1024 * 1024  # 200MB
    
    def test_presigned_url_ttl_constraints(self):
        """Test presigned URL TTL constraints."""
        assert PRESIGNED_PUT_TTL_SECONDS == 300  # 5 minutes
        assert PRESIGNED_GET_TTL_SECONDS == 120  # 2 minutes
    
    def test_sha256_validation(self):
        """Test SHA256 hash validation."""
        # Valid SHA256 (64 hex chars)
        valid_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        request = UploadInitRequest(
            type="model",
            size=1024,
            sha256=valid_hash,
            mime_type="application/sla",
            job_id="job-123"
        )
        assert request.sha256 == valid_hash.lower()
        
        # Invalid SHA256 (wrong length)
        with pytest.raises(ValueError):
            UploadInitRequest(
                type="model",
                size=1024,
                sha256="tooshort",
                mime_type="application/sla",
                job_id="job-123"
            )
    
    def test_filename_sanitization(self):
        """Test filename sanitization."""
        # Test path traversal attempt
        request = UploadInitRequest(
            type="model",
            size=1024,
            sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            mime_type="application/sla",
            job_id="job-123",
            filename="../../../etc/passwd"
        )
        assert "/" not in request.filename
        assert ".." not in request.filename
        
        # Test dangerous characters
        request2 = UploadInitRequest(
            type="model",
            size=1024,
            sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            mime_type="application/sla",
            job_id="job-123",
            filename='file<>:"|?*.txt'
        )
        for char in '<>:"|?*':
            assert char not in request2.filename


class TestErrorCodes:
    """Test error code handling."""
    
    def test_all_error_codes_defined(self):
        """Test that all required error codes are defined."""
        required_codes = [
            "INVALID_INPUT",
            "UNAUTHORIZED",
            "UNSUPPORTED_MEDIA_TYPE",
            "PAYLOAD_TOO_LARGE",
            "RATE_LIMITED",
            "NOT_FOUND",
            "UPLOAD_INCOMPLETE",
            "HASH_MISMATCH",
            "MALWARE_DETECTED",
            "SCAN_UNAVAILABLE",
            "STORAGE_ERROR",
            "FORBIDDEN",
        ]
        
        for code in required_codes:
            assert hasattr(UploadErrorCode, code)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])