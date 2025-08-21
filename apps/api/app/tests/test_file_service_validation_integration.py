"""
Integration tests for Task 5.4 - File Service with Validation

Tests the complete integration of file upload/download with validation:
- Upload initialization with validation
- Upload finalization with content verification
- Error handling for various attack vectors
"""

import hashlib
import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch

import pytest
from minio.error import S3Error

from app.services.file_service import FileService, FileServiceError
from app.services.file_validation import FileValidationService
from app.schemas.file_upload import (
    UploadInitRequest,
    UploadFinalizeRequest,
    FileUploadType,
    UploadErrorCode,
)


class TestFileServiceValidationIntegration:
    """Integration tests for file service with validation."""
    
    @pytest.fixture
    def mock_minio_client(self):
        """Create mock MinIO client."""
        client = Mock()
        client.presigned_post_policy = Mock(return_value={
            "url": "https://minio.example.com/upload",
            "fields": {
                "key": "test-key",
                "Policy": "test-policy",
                "X-Amz-Signature": "test-signature",
            }
        })
        client.stat_object = Mock(return_value=Mock(
            size=1024,
            etag="test-etag",
            version_id="v1",
            last_modified=datetime.now(timezone.utc),
            content_type="model/stl",
        ))
        client.get_object = Mock()
        client.remove_object = Mock()
        return client
    
    @pytest.fixture
    def mock_db_session(self):
        """Create mock database session."""
        session = Mock()
        session.add = Mock()
        session.commit = Mock()
        session.query = Mock()
        return session
    
    @pytest.fixture
    def file_service(self, mock_minio_client, mock_db_session):
        """Create file service with validation."""
        return FileService(
            client=mock_minio_client,
            db=mock_db_session,
            validation_service=FileValidationService(),
        )
    
    # ========================================================================
    # SUCCESSFUL UPLOAD TESTS
    # ========================================================================
    
    def test_valid_stl_upload_success(self, file_service, mock_db_session):
        """Test successful upload of valid STL file."""
        # Prepare request
        request = UploadInitRequest(
            type=FileUploadType.MODEL,
            size=1024,
            sha256="a" * 64,
            mime_type="model/stl",
            job_id="job-001",
            filename="part.stl",
        )
        
        # Initialize upload
        response = file_service.init_upload(request, user_id="user-123")
        
        assert response.upload_url is not None
        assert response.key.endswith(".stl")
        assert response.upload_id is not None
        assert response.expires_in > 0
        
        # Verify session was created
        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_called()
    
    def test_valid_gcode_upload_success(self, file_service):
        """Test successful upload of valid G-code file."""
        request = UploadInitRequest(
            type=FileUploadType.GCODE,
            size=2048,
            sha256="b" * 64,
            mime_type="text/plain",
            job_id="job-002",
            filename="program.gcode",
        )
        
        response = file_service.init_upload(request)
        
        assert response.upload_url is not None
        assert response.key.endswith(".gcode")
    
    def test_valid_mp4_upload_success(self, file_service):
        """Test successful upload of valid MP4 video."""
        request = UploadInitRequest(
            type=FileUploadType.MODEL,
            size=50 * 1024 * 1024,  # 50MB
            sha256="c" * 64,
            mime_type="video/mp4",
            job_id="job-003",
            filename="simulation.mp4",
        )
        
        response = file_service.init_upload(request)
        
        assert response.upload_url is not None
        assert response.key.endswith(".mp4")
    
    # ========================================================================
    # EXTENSION VALIDATION TESTS
    # ========================================================================
    
    def test_invalid_extension_rejected(self, file_service):
        """Test that files with invalid extensions are rejected."""
        request = UploadInitRequest(
            type=FileUploadType.MODEL,
            size=1024,
            sha256="d" * 64,
            mime_type="application/x-msdownload",
            job_id="job-004",
            filename="malware.exe",
        )
        
        with pytest.raises(FileServiceError) as exc_info:
            file_service.init_upload(request)
        
        assert exc_info.value.status_code == 415  # Unsupported Media Type
        assert exc_info.value.code == UploadErrorCode.UNSUPPORTED_MEDIA_TYPE
        assert "not allowed" in exc_info.value.message.lower()
    
    def test_multiple_invalid_extensions_rejected(self, file_service):
        """Test various invalid extensions are all rejected."""
        invalid_files = [
            ("script.js", "application/javascript"),
            ("archive.zip", "application/zip"),
            ("installer.msi", "application/x-msi"),
            ("document.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ]
        
        for filename, mime_type in invalid_files:
            request = UploadInitRequest(
                type=FileUploadType.TEMP,
                size=1024,
                sha256="e" * 64,
                mime_type=mime_type,
                job_id="job-005",
                filename=filename,
            )
            
            with pytest.raises(FileServiceError) as exc_info:
                file_service.init_upload(request)
            
            assert exc_info.value.status_code == 415
    
    # ========================================================================
    # MIME TYPE VALIDATION TESTS
    # ========================================================================
    
    def test_mime_type_mismatch_rejected(self, file_service):
        """Test that MIME type mismatches are rejected per Task 5.4."""
        request = UploadInitRequest(
            type=FileUploadType.MODEL,
            size=1024,
            sha256="f" * 64,
            mime_type="video/mp4",  # Wrong MIME for STL
            job_id="job-006",
            filename="model.stl",
        )
        
        with pytest.raises(FileServiceError) as exc_info:
            file_service.init_upload(request)
        
        assert exc_info.value.status_code == 415
        assert "mismatch" in exc_info.value.message.lower()
    
    # ========================================================================
    # SIZE VALIDATION TESTS
    # ========================================================================
    
    def test_oversized_file_rejected(self, file_service):
        """Test that files over 200MB are rejected with 413 error."""
        request = UploadInitRequest(
            type=FileUploadType.MODEL,
            size=201 * 1024 * 1024,  # 201MB
            sha256="g" * 64,
            mime_type="model/stl",
            job_id="job-007",
            filename="huge.stl",
        )
        
        with pytest.raises(FileServiceError) as exc_info:
            file_service.init_upload(request)
        
        assert exc_info.value.status_code == 413  # Payload Too Large
        assert exc_info.value.code == UploadErrorCode.PAYLOAD_TOO_LARGE
        assert "exceeds maximum" in exc_info.value.message.lower()
    
    def test_empty_file_rejected(self, file_service):
        """Test that empty files are rejected."""
        request = UploadInitRequest(
            type=FileUploadType.MODEL,
            size=0,
            sha256="h" * 64,
            mime_type="model/stl",
            job_id="job-008",
            filename="empty.stl",
        )
        
        with pytest.raises(FileServiceError) as exc_info:
            file_service.init_upload(request)
        
        assert exc_info.value.status_code == 400
        assert "empty" in exc_info.value.message.lower()
    
    def test_max_size_file_accepted(self, file_service):
        """Test that 200MB file (exact limit) is accepted."""
        request = UploadInitRequest(
            type=FileUploadType.MODEL,
            size=200 * 1024 * 1024,  # Exactly 200MB
            sha256="i" * 64,
            mime_type="model/stl",
            job_id="job-009",
            filename="max.stl",
        )
        
        response = file_service.init_upload(request)
        assert response.upload_url is not None
    
    # ========================================================================
    # DOUBLE-EXTENSION ATTACK TESTS
    # ========================================================================
    
    def test_double_extension_exe_stl_rejected(self, file_service):
        """Test that .exe.stl double extension is rejected per Task 5.4."""
        request = UploadInitRequest(
            type=FileUploadType.MODEL,
            size=1024,
            sha256="j" * 64,
            mime_type="model/stl",
            job_id="job-010",
            filename="malware.exe.stl",
        )
        
        with pytest.raises(FileServiceError) as exc_info:
            file_service.init_upload(request)
        
        assert exc_info.value.status_code == 400
        assert "double extension" in exc_info.value.message.lower()
    
    def test_stl_exe_rejected(self, file_service):
        """Test that .stl.exe is rejected (wrong final extension)."""
        request = UploadInitRequest(
            type=FileUploadType.MODEL,
            size=1024,
            sha256="k" * 64,
            mime_type="application/x-msdownload",
            job_id="job-011",
            filename="model.stl.exe",
        )
        
        with pytest.raises(FileServiceError) as exc_info:
            file_service.init_upload(request)
        
        assert exc_info.value.status_code == 415  # Invalid extension
    
    def test_benign_double_extension_accepted(self, file_service):
        """Test that benign double extensions like .v2.stl are accepted."""
        request = UploadInitRequest(
            type=FileUploadType.MODEL,
            size=1024,
            sha256="l" * 64,
            mime_type="model/stl",
            job_id="job-012",
            filename="model.v2.stl",
        )
        
        response = file_service.init_upload(request)
        assert response.upload_url is not None
    
    # ========================================================================
    # FILENAME SANITIZATION TESTS
    # ========================================================================
    
    def test_filename_sanitized_to_uuid(self, file_service):
        """Test that filenames are sanitized to UUID format."""
        request = UploadInitRequest(
            type=FileUploadType.MODEL,
            size=1024,
            sha256="m" * 64,
            mime_type="model/stl",
            job_id="job-013",
            filename="../../etc/passwd.stl",  # Path traversal attempt
        )
        
        response = file_service.init_upload(request)
        
        # Extract filename from key
        filename = response.key.split("/")[-1]
        
        # Should be UUID format
        import re
        uuid_pattern = r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\.[a-z]+$'
        assert re.match(uuid_pattern, filename)
    
    def test_utf8_tricks_prevented(self, file_service):
        """Test that UTF-8 encoding tricks are prevented."""
        request = UploadInitRequest(
            type=FileUploadType.MODEL,
            size=1024,
            sha256="n" * 64,
            mime_type="model/stl",
            job_id="job-014",
            filename="mo\u202edel.stl",  # UTF-8 direction override character
        )
        
        response = file_service.init_upload(request)
        
        # Should generate safe UUID filename
        filename = response.key.split("/")[-1]
        assert "\u202e" not in filename
    
    # ========================================================================
    # FINALIZATION VALIDATION TESTS
    # ========================================================================
    
    def test_finalize_with_size_mismatch_rejected(self, file_service, mock_minio_client, mock_db_session):
        """Test that finalization with size mismatch is rejected."""
        # Setup mock session
        mock_session = Mock()
        mock_session.upload_id = "upload-123"
        mock_session.object_key = "artefacts/job-001/file.stl"
        mock_session.expected_size = 1024
        mock_session.expected_sha256 = "a" * 64
        mock_session.is_expired = False
        mock_session.mime_type = "model/stl"
        mock_session.metadata = {"type": "model"}
        
        mock_db_session.query().filter_by().first.return_value = mock_session
        
        # Mock stat_object to return wrong size
        mock_minio_client.stat_object.return_value = Mock(
            size=2048,  # Wrong size
            etag="test-etag",
        )
        
        request = UploadFinalizeRequest(
            key="artefacts/job-001/file.stl",
            upload_id="upload-123",
        )
        
        with pytest.raises(FileServiceError) as exc_info:
            file_service.finalize_upload(request)
        
        assert exc_info.value.status_code == 413
        assert "size mismatch" in exc_info.value.message.lower()
    
    @patch("app.services.file_service.hashlib")
    def test_finalize_with_content_validation(self, mock_hashlib, file_service, mock_minio_client, mock_db_session):
        """Test that content is validated during finalization."""
        # Setup mock session
        mock_session = Mock()
        mock_session.upload_id = "upload-123"
        mock_session.object_key = "artefacts/job-001/file.stl"
        mock_session.expected_size = 1024
        mock_session.expected_sha256 = "a" * 64
        mock_session.is_expired = False
        mock_session.mime_type = "model/stl"
        mock_session.metadata = {"type": "model", "filename": "model.stl"}
        mock_session.job_id = "job-001"
        mock_session.client_ip = "127.0.0.1"
        
        mock_db_session.query().filter_by().first.return_value = mock_session
        
        # Mock stat_object
        mock_minio_client.stat_object.return_value = Mock(
            size=1024,
            etag="test-etag",
            version_id="v1",
        )
        
        # Mock get_object to return wrong content (not STL)
        mock_stream = Mock()
        mock_stream.stream = Mock(return_value=[
            b"This is not an STL file",  # Wrong magic bytes
        ])
        mock_stream.close = Mock()
        mock_stream.release_conn = Mock()
        mock_minio_client.get_object.return_value = mock_stream
        
        # Mock hashlib
        mock_hasher = Mock()
        mock_hasher.hexdigest.return_value = "a" * 64  # Correct hash
        mock_hashlib.sha256.return_value = mock_hasher
        
        request = UploadFinalizeRequest(
            key="artefacts/job-001/file.stl",
            upload_id="upload-123",
        )
        
        with pytest.raises(FileServiceError) as exc_info:
            file_service.finalize_upload(request)
        
        # Should fail content validation
        assert exc_info.value.status_code == 415
        assert "content does not match" in exc_info.value.message.lower()
        
        # Should have tried to delete the invalid file
        mock_minio_client.remove_object.assert_called()
    
    # ========================================================================
    # ACCEPTANCE TESTS FROM TASK 5.4
    # ========================================================================
    
    def test_acceptance_exe_or_stl_exe_rejected(self, file_service):
        """Acceptance test: .exe or .stl.exe rejected with 415."""
        # Test .exe
        request = UploadInitRequest(
            type=FileUploadType.TEMP,
            size=1024,
            sha256="o" * 64,
            mime_type="application/x-msdownload",
            job_id="job-015",
            filename="virus.exe",
        )
        
        with pytest.raises(FileServiceError) as exc_info:
            file_service.init_upload(request)
        assert exc_info.value.status_code == 415
        
        # Test .stl.exe
        request.filename = "model.stl.exe"
        with pytest.raises(FileServiceError) as exc_info:
            file_service.init_upload(request)
        assert exc_info.value.status_code == 415
    
    def test_acceptance_mime_mismatch_rejected(self, file_service):
        """Acceptance test: MIME mismatch rejected with 415."""
        request = UploadInitRequest(
            type=FileUploadType.MODEL,
            size=1024,
            sha256="p" * 64,
            mime_type="video/mp4",  # Wrong MIME for STL
            job_id="job-016",
            filename="model.stl",
        )
        
        with pytest.raises(FileServiceError) as exc_info:
            file_service.init_upload(request)
        
        assert exc_info.value.status_code == 415
        assert "mismatch" in exc_info.value.message.lower()
    
    def test_acceptance_over_200mb_rejected_at_init(self, file_service):
        """Acceptance test: >200MB rejected at init with 413."""
        request = UploadInitRequest(
            type=FileUploadType.MODEL,
            size=250 * 1024 * 1024,  # 250MB
            sha256="q" * 64,
            mime_type="model/stl",
            job_id="job-017",
            filename="huge.stl",
        )
        
        with pytest.raises(FileServiceError) as exc_info:
            file_service.init_upload(request)
        
        assert exc_info.value.status_code == 413
    
    def test_acceptance_over_200mb_rejected_at_finalize(self, file_service, mock_minio_client, mock_db_session):
        """Acceptance test: >200MB rejected at finalize with 413."""
        # Setup mock session
        mock_session = Mock()
        mock_session.upload_id = "upload-124"
        mock_session.object_key = "artefacts/job-017/huge.stl"
        mock_session.expected_size = 100 * 1024 * 1024  # Expected 100MB
        mock_session.expected_sha256 = "r" * 64
        mock_session.is_expired = False
        mock_session.mime_type = "model/stl"
        mock_session.metadata = {"type": "model"}
        
        mock_db_session.query().filter_by().first.return_value = mock_session
        
        # Mock stat_object to return oversized file
        mock_minio_client.stat_object.return_value = Mock(
            size=250 * 1024 * 1024,  # Actual 250MB
            etag="test-etag",
        )
        
        request = UploadFinalizeRequest(
            key="artefacts/job-017/huge.stl",
            upload_id="upload-124",
        )
        
        with pytest.raises(FileServiceError) as exc_info:
            file_service.finalize_upload(request)
        
        # Should fail with size error
        assert exc_info.value.status_code in [413, 400]  # Size mismatch or too large
    
    # ========================================================================
    # ERROR MESSAGE TESTS
    # ========================================================================
    
    def test_error_messages_bilingual(self, file_service):
        """Test that errors include both English and Turkish messages."""
        request = UploadInitRequest(
            type=FileUploadType.MODEL,
            size=1024,
            sha256="s" * 64,
            mime_type="application/x-msdownload",
            job_id="job-018",
            filename="virus.exe",
        )
        
        with pytest.raises(FileServiceError) as exc_info:
            file_service.init_upload(request)
        
        # Should have both messages
        assert exc_info.value.message is not None  # English
        assert exc_info.value.turkish_message is not None  # Turkish
        assert exc_info.value.message != exc_info.value.turkish_message