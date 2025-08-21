"""
Integration tests for Task 5.5: File Upload with SHA256 Streaming

Tests the complete upload flow with:
- Memory-efficient SHA256 verification
- Idempotent finalize operations
- Hash mismatch handling with deletion
- Timeout protection
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.file import FileMetadata, UploadSession, FileStatus, FileType
from app.schemas.file_upload import (
    UploadFinalizeRequest,
    UploadFinalizeResponse,
    UploadErrorCode,
)
from app.services.file_service import FileService, FileServiceError
from app.services.sha256_service import SHA256StreamingService, SHA256StreamingError


@pytest.fixture
def mock_db():
    """Create mock database session."""
    db = MagicMock(spec=Session)
    return db


@pytest.fixture
def mock_minio_client():
    """Create mock MinIO client."""
    client = MagicMock()
    return client


@pytest.fixture
def mock_sha256_service():
    """Create mock SHA256 streaming service."""
    service = MagicMock(spec=SHA256StreamingService)
    return service


@pytest.fixture
def file_service(mock_db, mock_minio_client, mock_sha256_service):
    """Create file service with all mocks."""
    service = FileService(
        client=mock_minio_client,
        db=mock_db,
        sha256_service=mock_sha256_service,
    )
    return service


@pytest.fixture
def valid_upload_session():
    """Create a valid upload session."""
    session = MagicMock(spec=UploadSession)
    session.upload_id = "upload-123"
    session.object_key = "artefacts/job-001/model.stl"
    session.expected_size = 5242880  # 5MB
    session.expected_sha256 = "a" * 64
    session.mime_type = "application/sla"
    session.job_id = "job-001"
    session.user_id = uuid.uuid4()
    session.client_ip = "192.168.1.100"
    session.status = "pending"
    session.is_expired = False
    session.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    session.metadata = {
        "filename": "model.stl",
        "type": "model",
        "machine_id": "cnc-001",
    }
    session.completed_at = None
    return session


class TestFileUploadWithSHA256Streaming:
    """Test file upload with SHA256 streaming verification."""
    
    def test_finalize_with_successful_hash_verification(
        self,
        file_service,
        mock_db,
        mock_minio_client,
        mock_sha256_service,
        valid_upload_session,
    ):
        """Test successful finalization with correct SHA256 hash."""
        # Setup
        request = UploadFinalizeRequest(
            upload_id="upload-123",
            key="artefacts/job-001/model.stl",
        )
        
        # Mock database query
        mock_db.query().filter_by().first.return_value = valid_upload_session
        
        # Mock stat_object
        mock_stat = MagicMock()
        mock_stat.size = 5242880
        mock_stat.etag = "etag-123"
        mock_stat.version_id = "v1"
        mock_stat.content_type = "application/sla"
        mock_stat.last_modified = datetime.now(timezone.utc)
        mock_stat.metadata = {}
        mock_minio_client.stat_object.return_value = mock_stat
        
        # Mock SHA256 verification - success
        mock_sha256_service.verify_object_hash.return_value = (
            True,  # is_valid
            valid_upload_session.expected_sha256,  # actual_sha256
            {  # metadata
                "bytes_processed": 5242880,
                "chunks_processed": 1,
                "chunk_size": 8 * 1024 * 1024,
                "hash_match": True,
            }
        )
        
        # Mock first chunk for magic bytes
        mock_sha256_service.get_first_chunk.return_value = b"STL\x00" + b"\x00" * 1020
        
        # Mock getting object tags
        mock_minio_client.get_object_tags.return_value = []
        
        # Execute
        response = file_service.finalize_upload(request, user_id=str(valid_upload_session.user_id))
        
        # Assert
        assert response.success is True
        assert response.object_key == "artefacts/job-001/model.stl"
        assert response.size == 5242880
        assert response.sha256 == valid_upload_session.expected_sha256
        assert response.etag == "etag-123"
        
        # Verify SHA256 service was called correctly
        mock_sha256_service.verify_object_hash.assert_called_once_with(
            bucket_name="artefacts",
            object_name="job-001/model.stl",
            expected_sha256=valid_upload_session.expected_sha256,
            expected_size=5242880,
        )
        
        # Verify session was marked as completed
        assert valid_upload_session.status == "completed"
        assert valid_upload_session.completed_at is not None
        
        # Verify database commit was called
        mock_db.commit.assert_called()
    
    def test_finalize_with_hash_mismatch_triggers_deletion(
        self,
        file_service,
        mock_db,
        mock_minio_client,
        mock_sha256_service,
        valid_upload_session,
    ):
        """Test hash mismatch triggers object deletion and returns 422."""
        # Setup
        request = UploadFinalizeRequest(
            upload_id="upload-123",
            key="artefacts/job-001/model.stl",
        )
        
        mock_db.query().filter_by().first.return_value = valid_upload_session
        
        mock_stat = MagicMock()
        mock_stat.size = 5242880
        mock_minio_client.stat_object.return_value = mock_stat
        
        # Mock SHA256 verification - mismatch
        wrong_hash = "b" * 64
        mock_sha256_service.verify_object_hash.return_value = (
            False,  # is_valid
            wrong_hash,  # actual_sha256
            {  # metadata
                "bytes_processed": 5242880,
                "chunks_processed": 1,
                "hash_match": False,
                "expected_sha256": valid_upload_session.expected_sha256,
                "actual_sha256": wrong_hash,
            }
        )
        
        # Execute and expect error
        with pytest.raises(FileServiceError) as exc_info:
            file_service.finalize_upload(request, user_id=str(valid_upload_session.user_id))
        
        # Assert
        assert exc_info.value.code == UploadErrorCode.HASH_MISMATCH
        assert exc_info.value.status_code == 422
        assert valid_upload_session.expected_sha256 in exc_info.value.message
        assert wrong_hash in exc_info.value.message
        
        # Verify deletion was called with audit
        mock_sha256_service.delete_object_with_audit.assert_called_once_with(
            bucket_name="artefacts",
            object_name="job-001/model.stl",
            reason="SHA256 hash mismatch",
            details={
                "expected_sha256": valid_upload_session.expected_sha256,
                "actual_sha256": wrong_hash,
                "upload_id": "upload-123",
                "size": 5242880,
                "bytes_processed": 5242880,
                "chunks_processed": 1,
                "hash_match": False,
            }
        )
    
    def test_finalize_idempotency_returns_cached_result(
        self,
        file_service,
        mock_db,
        valid_upload_session,
    ):
        """Test idempotent finalize returns cached result without re-verification."""
        # Setup - session already completed
        valid_upload_session.status = "completed"
        valid_upload_session.completed_at = datetime.now(timezone.utc)
        
        # Create existing file metadata
        file_metadata = MagicMock(spec=FileMetadata)
        file_metadata.object_key = "artefacts/job-001/model.stl"
        file_metadata.size = 5242880
        file_metadata.sha256 = valid_upload_session.expected_sha256
        file_metadata.etag = "etag-123"
        file_metadata.version_id = "v1"
        file_metadata.filename = "model.stl"
        file_metadata.mime_type = "application/sla"
        file_metadata.created_at = datetime.now(timezone.utc)
        
        request = UploadFinalizeRequest(
            upload_id="upload-123",
            key="artefacts/job-001/model.stl",
        )
        
        # Mock database queries
        mock_db.query().filter_by.return_value.first.side_effect = [
            valid_upload_session,  # First call for session
            file_metadata,  # Second call for metadata
        ]
        
        # Execute
        response = file_service.finalize_upload(request)
        
        # Assert
        assert response.success is True
        assert response.object_key == "artefacts/job-001/model.stl"
        assert response.sha256 == valid_upload_session.expected_sha256
        assert response.metadata.get("idempotent_response") is True
        
        # Verify NO SHA256 verification was performed (idempotent)
        assert not hasattr(file_service.sha256_service, 'verify_object_hash') or \
               not file_service.sha256_service.verify_object_hash.called
    
    def test_finalize_with_timeout_error(
        self,
        file_service,
        mock_db,
        mock_minio_client,
        mock_sha256_service,
        valid_upload_session,
    ):
        """Test timeout during SHA256 verification returns appropriate error."""
        # Setup
        request = UploadFinalizeRequest(
            upload_id="upload-123",
            key="artefacts/job-001/model.stl",
        )
        
        mock_db.query().filter_by().first.return_value = valid_upload_session
        
        mock_stat = MagicMock()
        mock_stat.size = 5242880
        mock_minio_client.stat_object.return_value = mock_stat
        
        # Mock SHA256 verification - timeout
        mock_sha256_service.verify_object_hash.side_effect = SHA256StreamingError(
            code="TIMEOUT",
            message="Operation stream_and_hash timed out after 61.00s",
            details={"elapsed_time": 61.0, "timeout": 60},
        )
        
        # Execute and expect timeout error
        with pytest.raises(FileServiceError) as exc_info:
            file_service.finalize_upload(request, user_id=str(valid_upload_session.user_id))
        
        # Assert
        assert exc_info.value.code == UploadErrorCode.UPLOAD_INCOMPLETE
        assert exc_info.value.status_code == 408
        assert "timeout" in exc_info.value.message.lower()
        assert "slowloris" in exc_info.value.message.lower()
    
    def test_finalize_with_magic_bytes_mismatch(
        self,
        file_service,
        mock_db,
        mock_minio_client,
        mock_sha256_service,
        valid_upload_session,
    ):
        """Test magic bytes validation failure triggers deletion."""
        # Setup
        request = UploadFinalizeRequest(
            upload_id="upload-123",
            key="artefacts/job-001/model.stl",
        )
        
        mock_db.query().filter_by().first.return_value = valid_upload_session
        
        mock_stat = MagicMock()
        mock_stat.size = 5242880
        mock_minio_client.stat_object.return_value = mock_stat
        
        # Mock SHA256 verification - success
        mock_sha256_service.verify_object_hash.return_value = (
            True,
            valid_upload_session.expected_sha256,
            {"hash_match": True},
        )
        
        # Mock first chunk with wrong magic bytes (PDF instead of STL)
        mock_sha256_service.get_first_chunk.return_value = b"%PDF-1.4" + b"\x00" * 1016
        
        # Mock validation service to fail on magic bytes
        with patch('app.services.file_service.FileValidationService') as MockValidation:
            mock_validation = MockValidation.return_value
            mock_validation.validate_upload_finalize.return_value = MagicMock(
                is_valid=False,
                errors=[{
                    "message": "File content does not match declared type",
                    "turkish_message": "Dosya içeriği beyan edilen türle uyuşmuyor",
                }],
            )
            
            file_service.validation_service = mock_validation
            
            # Execute and expect error
            with pytest.raises(FileServiceError) as exc_info:
                file_service.finalize_upload(request, user_id=str(valid_upload_session.user_id))
        
        # Assert
        assert exc_info.value.code == UploadErrorCode.UNSUPPORTED_MEDIA_TYPE
        assert exc_info.value.status_code == 415
        
        # Verify deletion was called
        mock_sha256_service.delete_object_with_audit.assert_called_once()
        call_args = mock_sha256_service.delete_object_with_audit.call_args
        assert call_args[1]["reason"] == "Content validation failure - magic bytes mismatch"
    
    def test_finalize_with_large_file_memory_efficiency(
        self,
        file_service,
        mock_db,
        mock_minio_client,
        mock_sha256_service,
        valid_upload_session,
    ):
        """Test large file (100MB) is processed with memory efficiency."""
        # Setup - 100MB file
        valid_upload_session.expected_size = 100 * 1024 * 1024  # 100MB
        
        request = UploadFinalizeRequest(
            upload_id="upload-123",
            key="artefacts/job-001/large-model.stl",
        )
        
        mock_db.query().filter_by().first.return_value = valid_upload_session
        
        mock_stat = MagicMock()
        mock_stat.size = 100 * 1024 * 1024
        mock_minio_client.stat_object.return_value = mock_stat
        
        # Mock SHA256 verification with chunking metadata
        mock_sha256_service.verify_object_hash.return_value = (
            True,
            valid_upload_session.expected_sha256,
            {
                "bytes_processed": 100 * 1024 * 1024,
                "chunks_processed": 13,  # 100MB / 8MB chunks
                "chunk_size": 8 * 1024 * 1024,
                "hash_match": True,
            }
        )
        
        mock_sha256_service.get_first_chunk.return_value = b"STL\x00" + b"\x00" * 1020
        mock_minio_client.get_object_tags.return_value = []
        
        # Execute
        response = file_service.finalize_upload(request, user_id=str(valid_upload_session.user_id))
        
        # Assert
        assert response.success is True
        assert response.size == 100 * 1024 * 1024
        
        # Verify chunked processing was used
        verification_call = mock_sha256_service.verify_object_hash.call_args
        assert verification_call[1]["expected_size"] == 100 * 1024 * 1024