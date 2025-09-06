"""
Comprehensive test suite for Task 7.12 - Error handling, code mapping, and user suggestions

Tests cover:
- Error code to HTTP status mapping
- FreeCAD error pattern matching
- Bilingual error messages (Turkish/English)
- Actionable suggestions and remediation links
- PII masking in logs and error messages
- Request/job correlation IDs
- Error handler middleware
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core.exceptions import (
    ErrorCode,
    ErrorResponse,
    ErrorSuggestion,
    RemediationLink,
    ErrorDetails,
    EnterpriseException,
    FreeCADException,
    ValidationException,
    StorageException,
    AIException,
    PIIMasker,
    FreeCADErrorPatternMatcher,
    ErrorMessageProvider,
    SuggestionProvider,
    RemediationLinkProvider,
    ERROR_HTTP_MAPPING,
    map_exception_to_error_response,
    log_error_with_masking,
)
from app.middleware.error_handler import ErrorHandlerMiddleware, create_error_handlers


class TestErrorCodeMapping:
    """Test error code to HTTP status mapping."""
    
    def test_ai_error_codes(self):
        """Test AI-related error codes map to correct HTTP status."""
        assert ERROR_HTTP_MAPPING[ErrorCode.AI_AMBIGUOUS] == 425  # Too Early
        assert ERROR_HTTP_MAPPING[ErrorCode.AI_HINT_REQUIRED] == 422
        assert ERROR_HTTP_MAPPING[ErrorCode.AI_PROMPT_TOO_COMPLEX] == 422
        assert ERROR_HTTP_MAPPING[ErrorCode.AI_UNSUPPORTED_OPERATION] == 422
    
    def test_validation_error_codes(self):
        """Test validation error codes map to correct HTTP status."""
        assert ERROR_HTTP_MAPPING[ErrorCode.VALIDATION_MISSING_FIELD] == 422
        assert ERROR_HTTP_MAPPING[ErrorCode.VALIDATION_UNIT_MISMATCH] == 422
        assert ERROR_HTTP_MAPPING[ErrorCode.VALIDATION_RANGE_VIOLATION] == 422
        assert ERROR_HTTP_MAPPING[ErrorCode.VALIDATION_UNSUPPORTED_FORMAT] == 415
        assert ERROR_HTTP_MAPPING[ErrorCode.VALIDATION_CONFLICT] == 409
    
    def test_freecad_geometry_error_codes(self):
        """Test FreeCAD geometry error codes map to correct HTTP status."""
        assert ERROR_HTTP_MAPPING[ErrorCode.FC_GEOM_INVALID_SHAPE] == 422
        assert ERROR_HTTP_MAPPING[ErrorCode.FC_BOOLEAN_FAILED] == 422
        assert ERROR_HTTP_MAPPING[ErrorCode.FC_FILLET_CHAMFER_FAILED] == 422
        assert ERROR_HTTP_MAPPING[ErrorCode.FC_SKETCH_OVERCONSTRAINED] == 409
        assert ERROR_HTTP_MAPPING[ErrorCode.FC_SKETCH_UNDERCONSTRAINED] == 422
        assert ERROR_HTTP_MAPPING[ErrorCode.FC_RECOMPUTE_FAILED] == 422
        assert ERROR_HTTP_MAPPING[ErrorCode.FC_TOPONAMING_UNSTABLE] == 409
        assert ERROR_HTTP_MAPPING[ErrorCode.FC_MESH_FAILED] == 422
    
    def test_freecad_import_export_error_codes(self):
        """Test FreeCAD import/export error codes map to correct HTTP status."""
        assert ERROR_HTTP_MAPPING[ErrorCode.FC_IMPORT_STEP_FAILED] == 422
        assert ERROR_HTTP_MAPPING[ErrorCode.FC_IMPORT_IGES_FAILED] == 422
        assert ERROR_HTTP_MAPPING[ErrorCode.FC_IMPORT_STL_FAILED] == 422
        assert ERROR_HTTP_MAPPING[ErrorCode.FC_EXPORT_STEP_FAILED] == 500
        assert ERROR_HTTP_MAPPING[ErrorCode.FC_EXPORT_STL_FAILED] == 500
        assert ERROR_HTTP_MAPPING[ErrorCode.FC_EXPORT_GCODE_FAILED] == 500
    
    def test_assembly4_error_codes(self):
        """Test Assembly4 error codes map to correct HTTP status."""
        assert ERROR_HTTP_MAPPING[ErrorCode.FC_A4_UNSOLVED] == 409
        assert ERROR_HTTP_MAPPING[ErrorCode.FC_A4_LINK_SCOPE] == 409
        assert ERROR_HTTP_MAPPING[ErrorCode.FC_A4_CYCLIC_DEPENDENCY] == 409
    
    def test_storage_error_codes(self):
        """Test storage error codes map to correct HTTP status."""
        assert ERROR_HTTP_MAPPING[ErrorCode.STORAGE_WRITE_FAILED] == 503
        assert ERROR_HTTP_MAPPING[ErrorCode.STORAGE_READ_FAILED] == 503
        assert ERROR_HTTP_MAPPING[ErrorCode.STORAGE_QUOTA_EXCEEDED] == 507
        assert ERROR_HTTP_MAPPING[ErrorCode.STORAGE_CORRUPT_FILE] == 500
    
    def test_system_error_codes(self):
        """Test system error codes map to correct HTTP status."""
        assert ERROR_HTTP_MAPPING[ErrorCode.TIMEOUT_WORKER] == 504
        assert ERROR_HTTP_MAPPING[ErrorCode.MEMORY_LIMIT_EXCEEDED] == 507
        assert ERROR_HTTP_MAPPING[ErrorCode.CPU_LIMIT_EXCEEDED] == 503
        assert ERROR_HTTP_MAPPING[ErrorCode.RATE_LIMITED] == 429


class TestFreeCADErrorPatternMatching:
    """Test FreeCAD error pattern matching."""
    
    def test_part_occ_errors(self):
        """Test Part/OCC error pattern matching."""
        assert FreeCADErrorPatternMatcher.match_error(
            "Part.OCCError: BRep_API: command not done"
        ) == ErrorCode.FC_BOOLEAN_FAILED
        
        assert FreeCADErrorPatternMatcher.match_error(
            "TopoDS::Face is null"
        ) == ErrorCode.FC_GEOM_INVALID_SHAPE
        
        assert FreeCADErrorPatternMatcher.match_error(
            "Shape is null, cannot process"
        ) == ErrorCode.FC_GEOM_INVALID_SHAPE
        
        assert FreeCADErrorPatternMatcher.match_error(
            "Geometry has self-intersections"
        ) == ErrorCode.FC_GEOM_INVALID_SHAPE
        
        assert FreeCADErrorPatternMatcher.match_error(
            "Non-manifold edge detected"
        ) == ErrorCode.FC_GEOM_INVALID_SHAPE
    
    def test_sketch_errors(self):
        """Test Sketcher error pattern matching."""
        assert FreeCADErrorPatternMatcher.match_error(
            "Sketch is Over-constrained"
        ) == ErrorCode.FC_SKETCH_OVERCONSTRAINED
        
        assert FreeCADErrorPatternMatcher.match_error(
            "Sketch is Under-constrained"
        ) == ErrorCode.FC_SKETCH_UNDERCONSTRAINED
        
        assert FreeCADErrorPatternMatcher.match_error(
            "Conflicting constraints detected"
        ) == ErrorCode.FC_SKETCH_OVERCONSTRAINED
        
        assert FreeCADErrorPatternMatcher.match_error(
            "Solver failed to find solution"
        ) == ErrorCode.FC_SKETCH_OVERCONSTRAINED
    
    def test_fillet_chamfer_errors(self):
        """Test fillet/chamfer error pattern matching."""
        assert FreeCADErrorPatternMatcher.match_error(
            "Failed to make fillet"
        ) == ErrorCode.FC_FILLET_CHAMFER_FAILED
        
        assert FreeCADErrorPatternMatcher.match_error(
            "Failed to make chamfer"
        ) == ErrorCode.FC_FILLET_CHAMFER_FAILED
        
        assert FreeCADErrorPatternMatcher.match_error(
            "Fillet operation failed"
        ) == ErrorCode.FC_FILLET_CHAMFER_FAILED
        
        assert FreeCADErrorPatternMatcher.match_error(
            "Radius exceeds edge length"
        ) == ErrorCode.FC_FILLET_CHAMFER_FAILED
    
    def test_import_export_errors(self):
        """Test import/export error pattern matching."""
        assert FreeCADErrorPatternMatcher.match_error(
            "Cannot import STEP file"
        ) == ErrorCode.FC_IMPORT_STEP_FAILED
        
        assert FreeCADErrorPatternMatcher.match_error(
            "STEP import failed"
        ) == ErrorCode.FC_IMPORT_STEP_FAILED
        
        assert FreeCADErrorPatternMatcher.match_error(
            "Cannot import IGES file"
        ) == ErrorCode.FC_IMPORT_IGES_FAILED
        
        assert FreeCADErrorPatternMatcher.match_error(
            "STL import failed"
        ) == ErrorCode.FC_IMPORT_STL_FAILED
        
        assert FreeCADErrorPatternMatcher.match_error(
            "Export to STEP failed"
        ) == ErrorCode.FC_EXPORT_STEP_FAILED
    
    def test_assembly4_errors(self):
        """Test Assembly4 error pattern matching."""
        assert FreeCADErrorPatternMatcher.match_error(
            "Assembly solver failed"
        ) == ErrorCode.FC_A4_UNSOLVED
        
        assert FreeCADErrorPatternMatcher.match_error(
            "Link out of scope"
        ) == ErrorCode.FC_A4_LINK_SCOPE
        
        assert FreeCADErrorPatternMatcher.match_error(
            "LCS missing"
        ) == ErrorCode.FC_A4_LINK_SCOPE
        
        assert FreeCADErrorPatternMatcher.match_error(
            "Cyclic dependency detected"
        ) == ErrorCode.FC_A4_CYCLIC_DEPENDENCY
    
    def test_no_match(self):
        """Test that unmatched errors return None."""
        assert FreeCADErrorPatternMatcher.match_error("Random error message") is None
        assert FreeCADErrorPatternMatcher.match_error("") is None
        assert FreeCADErrorPatternMatcher.match_error(None) is None


class TestBilingualErrorMessages:
    """Test bilingual error message support."""
    
    def test_freecad_error_messages(self):
        """Test FreeCAD error messages in both languages."""
        en, tr = ErrorMessageProvider.get_message(ErrorCode.FC_GEOM_INVALID_SHAPE)
        assert "invalid" in en.lower()
        assert "non-manifold" in en.lower()
        assert "geçersiz" in tr.lower()
        assert "manifold" in tr.lower()
        
        en, tr = ErrorMessageProvider.get_message(ErrorCode.FC_SKETCH_OVERCONSTRAINED)
        assert "over-constrained" in en.lower()
        assert "aşırı kısıtlanmış" in tr.lower()
        
        en, tr = ErrorMessageProvider.get_message(ErrorCode.FC_IMPORT_STEP_FAILED)
        assert "STEP" in en
        assert "import" in en.lower()
        assert "STEP" in tr
        assert "aktarılamadı" in tr.lower()
    
    def test_system_error_messages(self):
        """Test system error messages in both languages."""
        en, tr = ErrorMessageProvider.get_message(ErrorCode.TIMEOUT_WORKER)
        assert "timed out" in en.lower()
        assert "zaman aşımı" in tr.lower()
        
        en, tr = ErrorMessageProvider.get_message(ErrorCode.STORAGE_QUOTA_EXCEEDED)
        assert "quota exceeded" in en.lower()
        assert "kota" in tr.lower()
        assert "aşıldı" in tr.lower()
    
    def test_fallback_for_unmapped_codes(self):
        """Test fallback message for unmapped error codes."""
        # Create a mock error code that's not in the messages
        en, tr = ErrorMessageProvider.get_message(ErrorCode.INTERNAL_ERROR)
        # Should return a fallback message with the error code
        assert ErrorCode.INTERNAL_ERROR.value in en or "Error" in en


class TestErrorSuggestions:
    """Test actionable error suggestions."""
    
    def test_freecad_geometry_suggestions(self):
        """Test suggestions for FreeCAD geometry errors."""
        suggestions = SuggestionProvider.get_suggestions(ErrorCode.FC_GEOM_INVALID_SHAPE)
        assert len(suggestions) > 0
        
        # Check suggestions are bilingual
        for suggestion in suggestions:
            assert suggestion.en
            assert suggestion.tr
            assert "heal" in suggestion.en.lower() or "refine" in suggestion.en.lower()
    
    def test_fillet_chamfer_suggestions(self):
        """Test suggestions for fillet/chamfer errors."""
        suggestions = SuggestionProvider.get_suggestions(ErrorCode.FC_FILLET_CHAMFER_FAILED)
        assert len(suggestions) > 0
        
        # Check for specific advice
        suggestion_texts = [s.en.lower() for s in suggestions]
        assert any("radius" in text for text in suggestion_texts)
        assert any("thickness" in text for text in suggestion_texts)
    
    def test_sketch_overconstrained_suggestions(self):
        """Test suggestions for overconstrained sketch errors."""
        suggestions = SuggestionProvider.get_suggestions(ErrorCode.FC_SKETCH_OVERCONSTRAINED)
        assert len(suggestions) > 0
        
        # Check for specific advice
        suggestion_texts = [s.en.lower() for s in suggestions]
        assert any("redundant" in text for text in suggestion_texts)
        assert any("constraint" in text for text in suggestion_texts)
    
    def test_no_suggestions_for_unmapped_codes(self):
        """Test that unmapped codes return empty suggestions."""
        suggestions = SuggestionProvider.get_suggestions(ErrorCode.INTERNAL_ERROR)
        assert isinstance(suggestions, list)  # Should return empty list, not None


class TestRemediationLinks:
    """Test remediation documentation links."""
    
    def test_freecad_remediation_links(self):
        """Test FreeCAD-related remediation links."""
        links = RemediationLinkProvider.get_links(ErrorCode.FC_GEOM_INVALID_SHAPE)
        assert len(links) > 0
        
        for link in links:
            assert link.title
            assert link.url
            assert link.url.startswith("http")
            assert "freecad" in link.url.lower() or "wiki" in link.url.lower()
    
    def test_assembly4_remediation_links(self):
        """Test Assembly4 remediation links."""
        links = RemediationLinkProvider.get_links(ErrorCode.FC_A4_UNSOLVED)
        assert len(links) > 0
        
        for link in links:
            assert "Assembly4" in link.title or "assembly" in link.url.lower()
    
    def test_no_links_for_unmapped_codes(self):
        """Test that unmapped codes return empty links."""
        links = RemediationLinkProvider.get_links(ErrorCode.INTERNAL_ERROR)
        assert isinstance(links, list)  # Should return empty list, not None


class TestPIIMasking:
    """Test PII masking functionality."""
    
    def test_email_masking(self):
        """Test email address masking."""
        text = "Contact user@example.com for details"
        masked = PIIMasker.mask_text(text)
        assert "[email redacted]" in masked
        assert "user@example.com" not in masked
    
    def test_phone_masking(self):
        """Test phone number masking."""
        # Turkish phone numbers
        text = "Call +90 555 123 4567 or 0555-123-4567"
        masked = PIIMasker.mask_text(text)
        assert "[phone redacted]" in masked
        assert "555" not in masked
    
    def test_jwt_masking(self):
        """Test JWT token masking."""
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        masked = PIIMasker.mask_text(text)
        assert "[token redacted]" in masked
        assert "eyJ" not in masked
    
    def test_api_key_masking(self):
        """Test API key masking."""
        text = 'api_key="sk-1234567890abcdefghijklmnopqrstuvwxyz"'
        masked = PIIMasker.mask_text(text)
        assert "[api_key redacted]" in masked
        assert "sk-1234567890" not in masked
    
    def test_ip_address_masking(self):
        """Test IP address masking."""
        text = "Connection from 192.168.1.100"
        masked = PIIMasker.mask_text(text)
        assert "[ip redacted]" in masked
        assert "192.168" not in masked
    
    def test_home_directory_masking(self):
        """Test home directory path masking."""
        text = "File at /home/user/documents/file.txt or C:\\Users\\John\\Desktop\\file.txt"
        masked = PIIMasker.mask_text(text)
        assert "[path redacted]" in masked
        assert "/home/user" not in masked
        assert "C:\\Users\\John" not in masked
    
    def test_turkish_tc_no_masking(self):
        """Test Turkish TC Kimlik No masking."""
        text = "TC No: 12345678901"
        masked = PIIMasker.mask_text(text)
        assert "[tc_no redacted]" in masked
        assert "12345678901" not in masked
    
    def test_dict_masking(self):
        """Test dictionary PII masking."""
        data = {
            "email": "user@example.com",
            "password": "secret123",
            "auth_token": "Bearer eyJhbGciOiJIUzI1NiIs...",
            "user_data": {
                "phone": "+90 555 123 4567",
                "address": "/home/user/documents"
            }
        }
        
        masked = PIIMasker.mask_dict(data)
        assert masked["email"] == "[email redacted]"
        assert masked["password"] == "[redacted]"  # Sensitive key
        assert masked["auth_token"] == "[redacted]"  # Sensitive key
        assert "[phone redacted]" in masked["user_data"]["phone"]
        assert "[path redacted]" in masked["user_data"]["address"]
    
    def test_empty_input_handling(self):
        """Test handling of empty inputs."""
        assert PIIMasker.mask_text(None) is None
        assert PIIMasker.mask_text("") == ""
        assert PIIMasker.mask_dict(None) is None
        assert PIIMasker.mask_dict({}) == {}


class TestEnterpriseException:
    """Test EnterpriseException class."""
    
    @patch('app.core.exceptions.get_correlation_id')
    def test_exception_creation(self, mock_correlation_id):
        """Test creating an EnterpriseException."""
        mock_correlation_id.return_value = "test-correlation-id"
        
        exc = EnterpriseException(
            error_code=ErrorCode.FC_GEOM_INVALID_SHAPE,
            message="Custom error message",
            details={"component": "freecad", "phase": "modeling"},
            job_id="job-123",
            phase="geometry_creation"
        )
        
        assert exc.error_code == ErrorCode.FC_GEOM_INVALID_SHAPE
        assert exc.message_en == "Custom error message"
        assert exc.message_tr  # Should have Turkish message
        assert exc.http_status == 422
        assert exc.request_id == "test-correlation-id"
        assert exc.job_id == "job-123"
        assert exc.phase == "geometry_creation"
    
    @patch('app.core.exceptions.get_correlation_id')
    def test_exception_to_error_response(self, mock_correlation_id):
        """Test converting exception to error response."""
        mock_correlation_id.return_value = "test-correlation-id"
        
        exc = EnterpriseException(
            error_code=ErrorCode.FC_FILLET_CHAMFER_FAILED,
            details={"radius": "5mm", "edge_length": "3mm"},
            job_id="job-456"
        )
        
        response = exc.to_error_response()
        
        assert isinstance(response, ErrorResponse)
        assert response.code == ErrorCode.FC_FILLET_CHAMFER_FAILED
        assert response.http_status == 422
        assert response.message_en
        assert response.message_tr
        assert len(response.suggestions) > 0  # Should have suggestions
        assert len(response.remediation_links) > 0  # Should have links
        assert response.request_id == "test-correlation-id"
        assert response.job_id == "job-456"
    
    def test_exception_pii_masking(self):
        """Test that PII is masked in exception details."""
        exc = EnterpriseException(
            error_code=ErrorCode.VALIDATION_MISSING_FIELD,
            details={
                "user_email": "user@example.com",
                "file_path": "/home/user/document.fcstd"
            }
        )
        
        # Details should be masked
        assert "[email redacted]" in str(exc.details.get("user_email", ""))
        assert "[path redacted]" in str(exc.details.get("file_path", ""))
    
    def test_exception_to_http_exception(self):
        """Test converting to FastAPI HTTPException."""
        exc = EnterpriseException(
            error_code=ErrorCode.FC_IMPORT_STEP_FAILED
        )
        
        http_exc = exc.to_http_exception()
        
        assert isinstance(http_exc, HTTPException)
        assert http_exc.status_code == 422
        assert isinstance(http_exc.detail, dict)
        assert http_exc.detail["code"] == ErrorCode.FC_IMPORT_STEP_FAILED


class TestSpecificExceptions:
    """Test specific exception classes."""
    
    def test_freecad_exception(self):
        """Test FreeCADException with pattern matching."""
        exc = FreeCADException(
            "Part.OCCError: BRep_API: command not done",
            job_id="job-789"
        )
        
        assert exc.error_code == ErrorCode.FC_BOOLEAN_FAILED
        assert exc.job_id == "job-789"
    
    def test_freecad_exception_fallback(self):
        """Test FreeCADException with unmatched error."""
        exc = FreeCADException(
            "Unknown FreeCAD error",
            job_id="job-000"
        )
        
        assert exc.error_code == ErrorCode.FC_RECOMPUTE_FAILED  # Default
    
    def test_validation_exception_missing_field(self):
        """Test ValidationException for missing field."""
        exc = ValidationException(
            "Field 'radius' is missing",
            field="radius"
        )
        
        assert exc.error_code == ErrorCode.VALIDATION_MISSING_FIELD
        assert exc.details.get("field") == "radius"
    
    def test_validation_exception_range(self):
        """Test ValidationException for range violation."""
        exc = ValidationException(
            "Value out of range: 0-100",
            field="percentage"
        )
        
        assert exc.error_code == ErrorCode.VALIDATION_RANGE_VIOLATION
    
    def test_validation_exception_conflict(self):
        """Test ValidationException for conflict."""
        exc = ValidationException(
            "Conflicting parameters detected"
        )
        
        assert exc.error_code == ErrorCode.VALIDATION_CONFLICT
    
    def test_storage_exception_quota(self):
        """Test StorageException for quota exceeded."""
        exc = StorageException(
            "Storage quota exceeded",
            operation="write"
        )
        
        assert exc.error_code == ErrorCode.STORAGE_QUOTA_EXCEEDED
    
    def test_storage_exception_write(self):
        """Test StorageException for write failure."""
        exc = StorageException(
            "Failed to save file",
            operation="write"
        )
        
        assert exc.error_code == ErrorCode.STORAGE_WRITE_FAILED
    
    def test_storage_exception_read(self):
        """Test StorageException for read failure."""
        exc = StorageException(
            "Failed to load file",
            operation="read"
        )
        
        assert exc.error_code == ErrorCode.STORAGE_READ_FAILED
    
    def test_ai_exception_ambiguous(self):
        """Test AIException for ambiguous prompt."""
        exc = AIException(
            "Prompt is ambiguous"
        )
        
        assert exc.error_code == ErrorCode.AI_AMBIGUOUS
    
    def test_ai_exception_hint_required(self):
        """Test AIException for hint required."""
        exc = AIException(
            "Additional hint required"
        )
        
        assert exc.error_code == ErrorCode.AI_HINT_REQUIRED
    
    def test_ai_exception_complex(self):
        """Test AIException for complex prompt."""
        exc = AIException(
            "Prompt too complex to process"
        )
        
        assert exc.error_code == ErrorCode.AI_PROMPT_TOO_COMPLEX


class TestExceptionMapping:
    """Test mapping of standard exceptions to error responses."""
    
    @patch('app.core.exceptions.get_correlation_id')
    def test_map_value_error(self, mock_correlation_id):
        """Test mapping ValueError to error response."""
        mock_correlation_id.return_value = "test-id"
        
        exc = ValueError("Invalid value")
        response = map_exception_to_error_response(exc, job_id="job-111")
        
        assert response.code == ErrorCode.VALIDATION_CONSTRAINT_VIOLATION
        assert response.http_status == 422
        assert response.job_id == "job-111"
    
    @patch('app.core.exceptions.get_correlation_id')
    def test_map_timeout_error(self, mock_correlation_id):
        """Test mapping TimeoutError to error response."""
        mock_correlation_id.return_value = "test-id"
        
        exc = TimeoutError("Operation timed out")
        response = map_exception_to_error_response(exc)
        
        assert response.code == ErrorCode.TIMEOUT_WORKER
        assert response.http_status == 504
    
    @patch('app.core.exceptions.get_correlation_id')
    def test_map_memory_error(self, mock_correlation_id):
        """Test mapping MemoryError to error response."""
        mock_correlation_id.return_value = "test-id"
        
        exc = MemoryError("Out of memory")
        response = map_exception_to_error_response(exc)
        
        assert response.code == ErrorCode.MEMORY_LIMIT_EXCEEDED
        assert response.http_status == 507
    
    @patch('app.core.exceptions.get_correlation_id')
    def test_map_permission_error(self, mock_correlation_id):
        """Test mapping PermissionError to error response."""
        mock_correlation_id.return_value = "test-id"
        
        exc = PermissionError("Access denied")
        response = map_exception_to_error_response(exc)
        
        assert response.code == ErrorCode.AUTH_FORBIDDEN
        assert response.http_status == 403
    
    @patch('app.core.exceptions.get_correlation_id')
    def test_map_file_not_found(self, mock_correlation_id):
        """Test mapping FileNotFoundError to error response."""
        mock_correlation_id.return_value = "test-id"
        
        exc = FileNotFoundError("File not found")
        response = map_exception_to_error_response(exc)
        
        assert response.code == ErrorCode.NOT_FOUND
        assert response.http_status == 404
    
    @patch('app.core.exceptions.get_correlation_id')
    def test_map_os_error_space(self, mock_correlation_id):
        """Test mapping OSError with space issue to error response."""
        mock_correlation_id.return_value = "test-id"
        
        exc = OSError("No space left on device")
        response = map_exception_to_error_response(exc, phase="storage")
        
        assert response.code == ErrorCode.STORAGE_QUOTA_EXCEEDED
        assert response.http_status == 507
        assert response.details.phase == "storage"
    
    @patch('app.core.exceptions.get_correlation_id')
    def test_map_generic_exception(self, mock_correlation_id):
        """Test mapping generic exception to error response."""
        mock_correlation_id.return_value = "test-id"
        
        exc = Exception("Something went wrong")
        response = map_exception_to_error_response(exc)
        
        assert response.code == ErrorCode.INTERNAL_ERROR
        assert response.http_status == 500
    
    @patch('app.core.exceptions.get_correlation_id')
    def test_map_freecad_pattern_in_generic(self, mock_correlation_id):
        """Test that FreeCAD patterns are detected in generic exceptions."""
        mock_correlation_id.return_value = "test-id"
        
        exc = RuntimeError("Failed to make fillet on edge")
        response = map_exception_to_error_response(exc)
        
        assert response.code == ErrorCode.FC_FILLET_CHAMFER_FAILED
        assert response.http_status == 422


class TestErrorLogging:
    """Test error logging with PII masking."""
    
    def test_log_error_with_masking(self):
        """Test that error logging masks PII."""
        mock_logger = Mock()
        
        log_error_with_masking(
            mock_logger,
            "Error processing user@example.com",
            user_email="user@example.com",
            file_path="/home/user/document.fcstd"
        )
        
        # Check that the logger was called
        mock_logger.error.assert_called_once()
        
        # Get the call arguments
        call_args = mock_logger.error.call_args
        message = call_args[0][0]
        kwargs = call_args[1]
        
        # Check PII is masked
        assert "[email redacted]" in message
        assert "[email redacted]" in kwargs["user_email"]
        assert "[path redacted]" in kwargs["file_path"]
    
    def test_log_error_with_exception(self):
        """Test logging with exception information."""
        mock_logger = Mock()
        
        try:
            raise ValueError("Test error with user@example.com")
        except ValueError as e:
            log_error_with_masking(
                mock_logger,
                "Processing failed",
                exception=e
            )
        
        # Check that exception info was logged
        call_kwargs = mock_logger.error.call_args[1]
        assert "exception_class" in call_kwargs
        assert call_kwargs["exception_class"] == "ValueError"
        assert "[email redacted]" in call_kwargs["exception_message"]
        assert "traceback_sanitized" in call_kwargs


if __name__ == "__main__":
    pytest.main([__file__, "-v"])