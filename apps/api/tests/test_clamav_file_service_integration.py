"""
Integration tests for ClamAV with File Service (Task 5.6)

Tests the complete integration of ClamAV scanning within file upload finalization:
- EICAR string upload triggers 422 MALWARE_DETECTED and object removal
- clamd down → finalize returns 503 SCAN_UNAVAILABLE when scan_enabled
- scan_enabled=false → finalize succeeds without scan
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, UTC
import uuid
from io import BytesIO

from minio import Minio
from minio.error import S3Error
from sqlalchemy.orm import Session

from app.services.file_service import FileService, FileServiceError
from app.services.clamav_service import ClamAVService, ClamAVError, EICAR_TEST_STRING
from app.schemas.file_upload import UploadFinalizeRequest, UploadErrorCode
from app.models.file import UploadSession, FileMetadata, FileStatus, FileType


class TestClamAVFileServiceIntegration:
    """Integration tests for ClamAV with File Service."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_db = Mock(spec=Session)
        self.mock_minio = Mock(spec=Minio)
        
        # Create mock upload session
        self.upload_session = Mock()
        self.upload_session.upload_id = "test-upload-123"
        self.upload_session.object_key = "temp/job123/test-file.exe"
        self.upload_session.expected_size = 1024
        self.upload_session.expected_sha256 = "abc123"
        self.upload_session.mime_type = "application/x-executable"
        self.upload_session.job_id = "job123"
        self.upload_session.user_id = uuid.uuid4()
        self.upload_session.client_ip = "192.168.1.100"
        self.upload_session.status = "pending"
        self.upload_session.is_expired = False
        self.upload_session.metadata = {
            "filename": "test-file.exe",
            "type": "temp",
            "machine_id": "machine1",
        }
        
        # Mock successful SHA256 verification
        self.mock_sha256_service = Mock()
        self.mock_sha256_service.verify_object_hash.return_value = (
            True,  # is_hash_valid
            "abc123",  # actual_sha256
            {"bytes_processed": 1024, "chunks_processed": 1},  # metadata
            b"test file content",  # first_chunk
        )
        
        # Mock file validation service
        self.mock_validation_service = Mock()
        self.mock_validation_service.validate_upload_finalize.return_value = Mock(
            is_valid=True,
            errors=[],
            warnings=[],
        )

    def create_file_service(self, clamav_service=None):
        """Create FileService with mocked dependencies."""
        return FileService(
            client=self.mock_minio,
            config=None,
            db=self.mock_db,
            validation_service=self.mock_validation_service,
            sha256_service=self.mock_sha256_service,
            clamav_service=clamav_service,
        )

    def test_eicar_upload_triggers_malware_detection(self):
        """Test that EICAR string upload triggers 422 MALWARE_DETECTED and object removal."""
        # Mock database query to return upload session
        self.mock_db.query.return_value.filter_by.return_value.first.return_value = self.upload_session
        
        # Mock MinIO stat_object to return file exists
        mock_stat = Mock()
        mock_stat.size = 1024
        mock_stat.etag = "etag123"
        mock_stat.version_id = "version123"
        self.mock_minio.stat_object.return_value = mock_stat
        
        # Create ClamAV service that detects EICAR as malware
        mock_clamav_service = Mock(spec=ClamAVService)
        
        # Mock async scan_object_stream method
        async def mock_scan_result():
            from app.services.clamav_service import ClamAVScanResult
            return ClamAVScanResult(
                is_clean=False,
                scan_time_ms=150.0,
                virus_name="Eicar-Test-Signature",
                scan_metadata={"scan_method": "instream", "bytes_scanned": 68},
            )
        
        mock_clamav_service.scan_object_stream.return_value = mock_scan_result()
        
        # Create file service
        file_service = self.create_file_service(clamav_service=mock_clamav_service)
        
        # Create finalize request
        finalize_request = UploadFinalizeRequest(
            upload_id="test-upload-123",
            key="temp/job123/test-file.exe",
        )
        
        # Test that malware detection raises 422 error
        with pytest.raises(FileServiceError) as exc_info:
            file_service.finalize_upload(finalize_request, user_id=str(self.upload_session.user_id))
        
        # Verify error details
        error = exc_info.value
        assert error.code == "MALWARE_DETECTED"
        assert error.status_code == 422
        assert "Eicar-Test-Signature" in error.message
        assert "removed" in error.message.lower()
        assert "remediation" in error.details
        
        # Verify ClamAV scan was called
        mock_clamav_service.scan_object_stream.assert_called_once()
        scan_call_args = mock_clamav_service.scan_object_stream.call_args[1]
        assert scan_call_args["bucket_name"] == "temp"
        assert scan_call_args["object_name"] == "job123/test-file.exe"
        assert scan_call_args["mime_type"] == "application/x-executable"
        assert scan_call_args["file_type"] == "temp"
        
        # Verify object was deleted via SHA256 service audit
        self.mock_sha256_service.delete_object_with_audit.assert_called_once()
        delete_call_args = self.mock_sha256_service.delete_object_with_audit.call_args[1]
        assert delete_call_args["bucket_name"] == "temp"
        assert delete_call_args["object_name"] == "job123/test-file.exe"
        assert "Malware detected: Eicar-Test-Signature" in delete_call_args["reason"]

    def test_clamd_down_scan_enabled_returns_503(self):
        """Test that clamd down with scan_enabled=true returns 503 SCAN_UNAVAILABLE."""
        # Mock database query to return upload session
        self.mock_db.query.return_value.filter_by.return_value.first.return_value = self.upload_session
        
        # Mock MinIO stat_object to return file exists
        mock_stat = Mock()
        mock_stat.size = 1024
        mock_stat.etag = "etag123"
        mock_stat.version_id = "version123"
        self.mock_minio.stat_object.return_value = mock_stat
        
        # Create ClamAV service that fails with SCAN_UNAVAILABLE
        mock_clamav_service = Mock(spec=ClamAVService)
        
        # Mock async scan_object_stream to raise SCAN_UNAVAILABLE
        async def mock_scan_error():
            from app.services.clamav_service import ClamAVError
            raise ClamAVError(
                code="SCAN_UNAVAILABLE",
                message="Malware scanning unavailable",
                turkish_message="Kötü amaçlı yazılım taraması kullanılamıyor",
                details={"daemon_status": "unreachable"},
                status_code=503,
            )
        
        mock_clamav_service.scan_object_stream.side_effect = mock_scan_error
        
        # Create file service
        file_service = self.create_file_service(clamav_service=mock_clamav_service)
        
        # Create finalize request
        finalize_request = UploadFinalizeRequest(
            upload_id="test-upload-123",
            key="temp/job123/test-file.exe",
        )
        
        # Test that scan unavailable raises 503 error
        with pytest.raises(FileServiceError) as exc_info:
            file_service.finalize_upload(finalize_request, user_id=str(self.upload_session.user_id))
        
        # Verify error mapping
        error = exc_info.value
        assert error.status_code == 503
        assert "unavailable" in error.message.lower() or "scan" in error.message.lower()
        
        # Verify ClamAV scan was attempted
        mock_clamav_service.scan_object_stream.assert_called_once()

    def test_scan_disabled_finalize_succeeds(self):
        """Test that scan_enabled=false allows finalize to succeed without scan."""
        # Mock database query to return upload session
        self.mock_db.query.return_value.filter_by.return_value.first.return_value = self.upload_session
        
        # Mock MinIO stat_object to return file exists
        mock_stat = Mock()
        mock_stat.size = 1024
        mock_stat.etag = "etag123"
        mock_stat.version_id = "version123"
        self.mock_minio.stat_object.return_value = mock_stat
        
        # Create ClamAV service with scanning disabled
        mock_clamav_service = Mock(spec=ClamAVService)
        
        # Mock async scan_object_stream to return "scan skipped"
        async def mock_scan_skipped():
            from app.services.clamav_service import ClamAVScanResult
            return ClamAVScanResult(
                is_clean=True,
                scan_time_ms=0.0,
                scan_metadata={"scan_skipped": True, "reason": "policy"},
            )
        
        mock_clamav_service.scan_object_stream.return_value = mock_scan_skipped()
        
        # Create file service
        file_service = self.create_file_service(clamav_service=mock_clamav_service)
        
        # Create finalize request
        finalize_request = UploadFinalizeRequest(
            upload_id="test-upload-123",
            key="temp/job123/test-file.exe",
        )
        
        # Mock additional file service dependencies
        with patch.object(file_service, '_get_object_tags', return_value={}):
            with patch.object(file_service, '_get_object_metadata', return_value={}):
                # Test that finalize succeeds when scan is skipped
                result = file_service.finalize_upload(
                    finalize_request,
                    user_id=str(self.upload_session.user_id)
                )
        
        # Verify successful response
        assert result.success is True
        assert result.object_key == "temp/job123/test-file.exe"
        assert result.size == 1024
        assert result.sha256 == "abc123"
        
        # Verify ClamAV scan was called but skipped
        mock_clamav_service.scan_object_stream.assert_called_once()
        
        # Verify database operations completed
        self.mock_db.add.assert_called()
        self.mock_db.commit.assert_called()

    def test_clean_file_scan_success(self):
        """Test that clean file passes scan and upload completes successfully."""
        # Mock database query to return upload session
        self.mock_db.query.return_value.filter_by.return_value.first.return_value = self.upload_session
        
        # Mock MinIO stat_object to return file exists
        mock_stat = Mock()
        mock_stat.size = 1024
        mock_stat.etag = "etag123"
        mock_stat.version_id = "version123"
        self.mock_minio.stat_object.return_value = mock_stat
        
        # Create ClamAV service that scans as clean
        mock_clamav_service = Mock(spec=ClamAVService)
        
        # Mock async scan_object_stream to return clean result
        async def mock_scan_clean():
            from app.services.clamav_service import ClamAVScanResult
            return ClamAVScanResult(
                is_clean=True,
                scan_time_ms=245.0,
                virus_name=None,
                scan_metadata={
                    "scan_method": "instream",
                    "bytes_scanned": 1024,
                    "object_size": 1024,
                    "mime_type": "application/x-executable",
                    "file_type": "temp",
                },
            )
        
        mock_clamav_service.scan_object_stream.return_value = mock_scan_clean()
        
        # Create file service
        file_service = self.create_file_service(clamav_service=mock_clamav_service)
        
        # Create finalize request
        finalize_request = UploadFinalizeRequest(
            upload_id="test-upload-123",
            key="temp/job123/test-file.exe",
        )
        
        # Mock additional file service dependencies
        with patch.object(file_service, '_get_object_tags', return_value={}):
            with patch.object(file_service, '_get_object_metadata', return_value={}):
                # Test successful finalize with clean scan
                result = file_service.finalize_upload(
                    finalize_request,
                    user_id=str(self.upload_session.user_id)
                )
        
        # Verify successful response
        assert result.success is True
        assert result.object_key == "temp/job123/test-file.exe"
        assert result.size == 1024
        assert result.sha256 == "abc123"
        
        # Verify ClamAV scan was performed
        mock_clamav_service.scan_object_stream.assert_called_once()
        
        # Verify no deletion occurred
        self.mock_sha256_service.delete_object_with_audit.assert_not_called()
        
        # Verify file metadata was created
        self.mock_db.add.assert_called()
        file_metadata_call = self.mock_db.add.call_args[0][0]
        assert isinstance(file_metadata_call, FileMetadata)
        assert file_metadata_call.object_key == "temp/job123/test-file.exe"
        assert file_metadata_call.status == FileStatus.COMPLETED

    def test_gcode_file_skips_scan(self):
        """Test that G-code files skip ClamAV scanning per policy."""
        # Update upload session for G-code file
        self.upload_session.object_key = "artefacts/job123/part.gcode"
        self.upload_session.mime_type = "text/plain"
        self.upload_session.metadata = {
            "filename": "part.gcode",
            "type": "gcode",
            "machine_id": "machine1",
        }
        
        # Mock database query to return upload session
        self.mock_db.query.return_value.filter_by.return_value.first.return_value = self.upload_session
        
        # Mock MinIO stat_object to return file exists
        mock_stat = Mock()
        mock_stat.size = 2048
        mock_stat.etag = "etag456"
        mock_stat.version_id = "version456"
        self.mock_minio.stat_object.return_value = mock_stat
        
        # Create ClamAV service
        mock_clamav_service = Mock(spec=ClamAVService)
        
        # Mock async scan_object_stream to return skipped scan
        async def mock_scan_skipped():
            from app.services.clamav_service import ClamAVScanResult
            return ClamAVScanResult(
                is_clean=True,
                scan_time_ms=0.0,
                scan_metadata={"scan_skipped": True, "reason": "policy"},
            )
        
        mock_clamav_service.scan_object_stream.return_value = mock_scan_skipped()
        
        # Create file service
        file_service = self.create_file_service(clamav_service=mock_clamav_service)
        
        # Create finalize request for G-code file
        finalize_request = UploadFinalizeRequest(
            upload_id="test-upload-123",
            key="artefacts/job123/part.gcode",
        )
        
        # Mock additional file service dependencies
        with patch.object(file_service, '_get_object_tags', return_value={}):
            with patch.object(file_service, '_get_object_metadata', return_value={}):
                # Test that G-code upload succeeds without actual scan
                result = file_service.finalize_upload(
                    finalize_request,
                    user_id=str(self.upload_session.user_id)
                )
        
        # Verify successful response
        assert result.success is True
        assert result.object_key == "artefacts/job123/part.gcode"
        
        # Verify ClamAV scan was called but returned skipped result
        mock_clamav_service.scan_object_stream.assert_called_once()
        scan_call_args = mock_clamav_service.scan_object_stream.call_args[1]
        assert scan_call_args["bucket_name"] == "artefacts"
        assert scan_call_args["object_name"] == "job123/part.gcode"
        assert scan_call_args["file_type"] == "gcode"

    def test_clamav_connection_error_handling(self):
        """Test handling of ClamAV connection errors."""
        # Mock database query to return upload session
        self.mock_db.query.return_value.filter_by.return_value.first.return_value = self.upload_session
        
        # Mock MinIO stat_object to return file exists
        mock_stat = Mock()
        mock_stat.size = 1024
        mock_stat.etag = "etag123"
        mock_stat.version_id = "version123"
        self.mock_minio.stat_object.return_value = mock_stat
        
        # Create ClamAV service that fails with connection error
        mock_clamav_service = Mock(spec=ClamAVService)
        
        # Mock async scan_object_stream to raise connection error
        async def mock_connection_error():
            from app.services.clamav_service import ClamAVError
            raise ClamAVError(
                code="CLAMD_CONNECTION_ERROR",
                message="ClamAV daemon connection failed",
                turkish_message="ClamAV daemon bağlantısı başarısız",
                details={"connection_error": "Connection refused"},
                status_code=503,
            )
        
        mock_clamav_service.scan_object_stream.side_effect = mock_connection_error
        
        # Create file service
        file_service = self.create_file_service(clamav_service=mock_clamav_service)
        
        # Create finalize request
        finalize_request = UploadFinalizeRequest(
            upload_id="test-upload-123",
            key="temp/job123/test-file.exe",
        )
        
        # Test that connection error is handled appropriately
        with pytest.raises(FileServiceError) as exc_info:
            file_service.finalize_upload(finalize_request, user_id=str(self.upload_session.user_id))
        
        # Verify error is properly mapped
        error = exc_info.value
        assert error.status_code == 503
        assert "scan failed" in error.message.lower() or "malware" in error.message.lower()
        
        # Verify ClamAV scan was attempted
        mock_clamav_service.scan_object_stream.assert_called_once()

    def test_scan_timeout_handling(self):
        """Test handling of ClamAV scan timeouts."""
        # Mock database query to return upload session
        self.mock_db.query.return_value.filter_by.return_value.first.return_value = self.upload_session
        
        # Mock MinIO stat_object to return file exists
        mock_stat = Mock()
        mock_stat.size = 1024
        mock_stat.etag = "etag123"
        mock_stat.version_id = "version123"
        self.mock_minio.stat_object.return_value = mock_stat
        
        # Create ClamAV service that times out
        mock_clamav_service = Mock(spec=ClamAVService)
        
        # Mock async scan_object_stream to raise timeout error
        async def mock_timeout_error():
            from app.services.clamav_service import ClamAVError
            raise ClamAVError(
                code="SCAN_TIMEOUT",
                message="Scan timeout after 60s",
                turkish_message="60s sonra tarama zaman aşımı",
                details={"timeout_seconds": 60},
                status_code=408,
            )
        
        mock_clamav_service.scan_object_stream.side_effect = mock_timeout_error
        
        # Create file service
        file_service = self.create_file_service(clamav_service=mock_clamav_service)
        
        # Create finalize request
        finalize_request = UploadFinalizeRequest(
            upload_id="test-upload-123",
            key="temp/job123/large-archive.zip",
        )
        
        # Test that timeout error is handled appropriately
        with pytest.raises(FileServiceError) as exc_info:
            file_service.finalize_upload(finalize_request, user_id=str(self.upload_session.user_id))
        
        # Verify error is properly mapped
        error = exc_info.value
        assert error.status_code == 408
        assert "timeout" in error.message.lower() or "scan failed" in error.message.lower()
        
        # Verify ClamAV scan was attempted
        mock_clamav_service.scan_object_stream.assert_called_once()