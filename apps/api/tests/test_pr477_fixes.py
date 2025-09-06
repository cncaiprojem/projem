"""
Test suite for PR #477 review feedback fixes.

Tests cover:
1. Turkish TC Kimlik No validation with checksum
2. Credit card validation with Luhn algorithm
3. Path normalization for metrics
4. ErrorCode passing to exception constructors
5. Error category dictionary lookup
"""

import pytest
import sys
import os
from unittest.mock import Mock, patch

# Add the app directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.exceptions import (
    PIIMasker,
    ValidationException,
    StorageException,
    AIException,
    FreeCADException,
    ErrorCode,
    EnterpriseException
)
from app.middleware.error_handler import ErrorHandlerMiddleware


class TestTurkishTCKimlikNoValidation:
    """Test Turkish TC Kimlik No validation with checksum algorithm."""
    
    def test_valid_tc_kimlik_no(self):
        """Test that valid TC Kimlik No is detected correctly."""
        # Valid test TC numbers (these pass the checksum)
        valid_numbers = [
            "10000000146",  # Test number that passes checksum
            "38246312712",  # Another valid test number
        ]
        
        for number in valid_numbers:
            assert PIIMasker._is_valid_tc_kimlik_no(number) is True
            
    def test_invalid_tc_kimlik_no_checksum(self):
        """Test that TC numbers with invalid checksum are rejected."""
        invalid_numbers = [
            "12345678901",  # Random 11 digits
            "98765432109",  # Random 11 digits
            "11111111111",  # All same digits
        ]
        
        for number in invalid_numbers:
            assert PIIMasker._is_valid_tc_kimlik_no(number) is False
            
    def test_tc_kimlik_no_starting_with_zero(self):
        """Test that TC numbers starting with 0 are invalid."""
        assert PIIMasker._is_valid_tc_kimlik_no("01234567890") is False
        
    def test_tc_kimlik_no_wrong_length(self):
        """Test that TC numbers with wrong length are invalid."""
        assert PIIMasker._is_valid_tc_kimlik_no("123456789") is False  # Too short
        assert PIIMasker._is_valid_tc_kimlik_no("123456789012") is False  # Too long
        
    def test_tc_kimlik_no_non_numeric(self):
        """Test that TC numbers with non-numeric characters are invalid."""
        assert PIIMasker._is_valid_tc_kimlik_no("1234567890a") is False
        assert PIIMasker._is_valid_tc_kimlik_no("abc12345678") is False
        
    def test_tc_kimlik_no_masking(self):
        """Test that only valid TC numbers are masked."""
        # Valid TC number should be masked
        text_with_valid = "My TC number is 10000000146"
        masked = PIIMasker.mask_text(text_with_valid)
        assert "[tc_no redacted]" in masked
        assert "10000000146" not in masked
        
        # Invalid TC number should NOT be masked
        text_with_invalid = "Random number 12345678901"
        masked = PIIMasker.mask_text(text_with_invalid)
        assert "12345678901" in masked  # Should remain unmasked
        assert "[tc_no redacted]" not in masked


class TestCreditCardLuhnValidation:
    """Test credit card validation with Luhn algorithm."""
    
    def test_valid_credit_cards(self):
        """Test that valid credit card numbers pass Luhn check."""
        valid_cards = [
            "4532015112830366",  # Valid Visa
            "5425233430109903",  # Valid Mastercard
            "374245455400126",   # Valid Amex (15 digits)
            "6011000991300009",  # Valid Discover
            "4532 0151 1283 0366",  # With spaces
            "4532-0151-1283-0366",  # With hyphens
        ]
        
        for card in valid_cards:
            assert PIIMasker._is_valid_credit_card(card) is True
            
    def test_invalid_credit_cards(self):
        """Test that invalid credit card numbers fail Luhn check."""
        invalid_cards = [
            "4532015112830367",  # Invalid checksum
            "1234567890123456",  # Random 16 digits
            "0000000000000000",  # All zeros
        ]
        
        for card in invalid_cards:
            assert PIIMasker._is_valid_credit_card(card) is False
            
    def test_credit_card_wrong_length(self):
        """Test that cards with wrong length are invalid."""
        assert PIIMasker._is_valid_credit_card("123456789012") is False  # 12 digits (too short)
        assert PIIMasker._is_valid_credit_card("12345678901234567890") is False  # 20 digits (too long)
        
    def test_credit_card_non_numeric(self):
        """Test that cards with non-numeric characters are invalid."""
        assert PIIMasker._is_valid_credit_card("4532-abcd-1283-0366") is False
        
    def test_credit_card_masking(self):
        """Test that only valid credit cards are masked."""
        # Valid card should be masked
        text_with_valid = "Payment with card 4532015112830366"
        masked = PIIMasker.mask_text(text_with_valid)
        assert "[card redacted]" in masked
        assert "4532015112830366" not in masked
        
        # Invalid card should NOT be masked
        text_with_invalid = "Number 1234567890123456 is not valid"
        masked = PIIMasker.mask_text(text_with_invalid)
        assert "1234567890123456" in masked  # Should remain unmasked
        assert "[card redacted]" not in masked


class TestPathNormalization:
    """Test path normalization for metrics."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.middleware = ErrorHandlerMiddleware(app=Mock())
        
    def test_normalize_numeric_ids(self):
        """Test normalization of numeric IDs."""
        assert self.middleware._normalize_path("/users/123") == "/users/{id}"
        assert self.middleware._normalize_path("/jobs/456789") == "/jobs/{id}"
        assert self.middleware._normalize_path("/items/1/details") == "/items/{id}/details"
        
    def test_normalize_uuid(self):
        """Test normalization of UUIDs."""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        assert self.middleware._normalize_path(f"/jobs/{uuid}") == "/jobs/{id}"
        
    def test_normalize_alphanumeric_ids(self):
        """Test normalization of alphanumeric IDs."""
        assert self.middleware._normalize_path("/jobs/abc123def456") == "/jobs/{id}"
        assert self.middleware._normalize_path("/artefacts/file_name_123") == "/artefacts/{id}"
        
    def test_normalize_queue_names(self):
        """Test normalization of queue names."""
        assert self.middleware._normalize_path("/queues/my_queue/pause") == "/queues/{name}/pause"
        assert self.middleware._normalize_path("/queues/test-queue/resume") == "/queues/{name}/resume"
        
    def test_normalize_user_paths(self):
        """Test normalization of user paths."""
        assert self.middleware._normalize_path("/users/john.doe/profile") == "/users/{username}/profile"
        assert self.middleware._normalize_path("/users/user123/settings") == "/users/{username}/settings"
        
    def test_normalize_project_paths(self):
        """Test normalization of project paths."""
        assert self.middleware._normalize_path("/projects/my-project/files") == "/projects/{name}/files"
        
    def test_preserve_static_paths(self):
        """Test that static paths are preserved."""
        assert self.middleware._normalize_path("/health") == "/health"
        assert self.middleware._normalize_path("/api/v1/status") == "/api/v1/status"
        
    def test_complex_paths(self):
        """Test normalization of complex paths."""
        assert self.middleware._normalize_path("/users/123/jobs/456/artefacts/789") == "/users/{id}/jobs/{id}/artefacts/{id}"


class TestErrorCategoryDictionaryLookup:
    """Test error category determination using dictionary lookup."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.middleware = ErrorHandlerMiddleware(app=Mock())
        
    def test_ai_category(self):
        """Test AI error category detection."""
        assert self.middleware._get_error_category(ErrorCode.AI_AMBIGUOUS) == "ai"
        assert self.middleware._get_error_category(ErrorCode.AI_HINT_REQUIRED) == "ai"
        
    def test_validation_category(self):
        """Test validation error category detection."""
        assert self.middleware._get_error_category(ErrorCode.VALIDATION_MISSING_FIELD) == "validation"
        assert self.middleware._get_error_category(ErrorCode.VALIDATION_CONFLICT) == "validation"
        
    def test_freecad_category(self):
        """Test FreeCAD error category detection."""
        assert self.middleware._get_error_category(ErrorCode.FC_RECOMPUTE_FAILED) == "freecad"
        assert self.middleware._get_error_category(ErrorCode.FC_GEOM_INVALID_SHAPE) == "freecad"
        
    def test_storage_category(self):
        """Test storage error category detection."""
        assert self.middleware._get_error_category(ErrorCode.STORAGE_QUOTA_EXCEEDED) == "storage"
        assert self.middleware._get_error_category(ErrorCode.STORAGE_WRITE_FAILED) == "storage"
        
    def test_auth_category(self):
        """Test auth error category detection."""
        assert self.middleware._get_error_category(ErrorCode.AUTH_UNAUTHORIZED) == "auth"
        assert self.middleware._get_error_category(ErrorCode.AUTH_TOKEN_EXPIRED) == "auth"
        
    def test_special_cases(self):
        """Test special case error categories."""
        assert self.middleware._get_error_category(ErrorCode.RATE_LIMITED) == "rate_limit"
        assert self.middleware._get_error_category(ErrorCode.TIMEOUT_WORKER) == "system"
        assert self.middleware._get_error_category(ErrorCode.MEMORY_LIMIT_EXCEEDED) == "system"
        assert self.middleware._get_error_category(ErrorCode.CPU_LIMIT_EXCEEDED) == "system"
        
    def test_unknown_category(self):
        """Test unknown error category as fallback."""
        # Create a mock error code that doesn't match any pattern
        mock_error = Mock()
        mock_error.value = "UNKNOWN_ERROR"
        assert self.middleware._get_error_category(mock_error) == "unknown"


class TestExceptionErrorCodeParameter:
    """Test that exceptions accept ErrorCode parameter directly."""
    
    def test_validation_exception_with_error_code(self):
        """Test ValidationException with explicit error_code."""
        exc = ValidationException(
            "Field is required",
            error_code=ErrorCode.VALIDATION_MISSING_FIELD
        )
        assert exc.error_code == ErrorCode.VALIDATION_MISSING_FIELD
        
        # Test that explicit code overrides message-based detection
        exc = ValidationException(
            "Field is missing",  # Would normally trigger MISSING_FIELD
            error_code=ErrorCode.VALIDATION_CONFLICT  # Explicit override
        )
        assert exc.error_code == ErrorCode.VALIDATION_CONFLICT
        
    def test_storage_exception_with_error_code(self):
        """Test StorageException with explicit error_code."""
        exc = StorageException(
            "Storage error",
            error_code=ErrorCode.STORAGE_QUOTA_EXCEEDED
        )
        assert exc.error_code == ErrorCode.STORAGE_QUOTA_EXCEEDED
        
        # Test that explicit code overrides operation-based detection
        exc = StorageException(
            "Error occurred",
            operation="write",  # Would normally trigger WRITE_FAILED
            error_code=ErrorCode.STORAGE_READ_FAILED  # Explicit override
        )
        assert exc.error_code == ErrorCode.STORAGE_READ_FAILED
        
    def test_ai_exception_with_error_code(self):
        """Test AIException with explicit error_code."""
        exc = AIException(
            "AI processing error",
            error_code=ErrorCode.AI_PROMPT_TOO_COMPLEX
        )
        assert exc.error_code == ErrorCode.AI_PROMPT_TOO_COMPLEX
        
        # Test that explicit code overrides message-based detection
        exc = AIException(
            "Too complex",  # Would normally trigger PROMPT_TOO_COMPLEX
            error_code=ErrorCode.AI_AMBIGUOUS  # Explicit override
        )
        assert exc.error_code == ErrorCode.AI_AMBIGUOUS
        
    def test_freecad_exception_with_error_code(self):
        """Test FreeCADException with explicit error_code."""
        exc = FreeCADException(
            "FreeCAD error",
            error_code=ErrorCode.FC_GEOM_INVALID_SHAPE
        )
        assert exc.error_code == ErrorCode.FC_GEOM_INVALID_SHAPE
        
    def test_backward_compatibility(self):
        """Test that old usage without error_code still works."""
        # ValidationException
        exc = ValidationException("Field is missing")
        assert exc.error_code == ErrorCode.VALIDATION_MISSING_FIELD
        
        # StorageException
        exc = StorageException("Error", operation="write")
        assert exc.error_code == ErrorCode.STORAGE_WRITE_FAILED
        
        # AIException
        exc = AIException("Too complex to process")
        assert exc.error_code == ErrorCode.AI_PROMPT_TOO_COMPLEX
        
        # FreeCADException (uses pattern matcher or default)
        exc = FreeCADException("Some FreeCAD error")
        assert exc.error_code == ErrorCode.FC_RECOMPUTE_FAILED  # Default


class TestIntegration:
    """Integration tests for all changes together."""
    
    def test_pii_masking_with_validation(self):
        """Test that PII masking only masks valid patterns."""
        text = """
        User info:
        - TC No: 10000000146 (valid, should be masked)
        - Random: 12345678901 (invalid TC, should NOT be masked)
        - Card: 4532015112830366 (valid, should be masked)
        - Number: 1234567890123456 (invalid card, should NOT be masked)
        - Email: user@example.com (should be masked)
        """
        
        masked = PIIMasker.mask_text(text)
        
        # Valid patterns should be masked
        assert "10000000146" not in masked
        assert "[tc_no redacted]" in masked
        assert "4532015112830366" not in masked
        assert "[card redacted]" in masked
        assert "user@example.com" not in masked
        assert "[email redacted]" in masked
        
        # Invalid patterns should remain
        assert "12345678901" in masked
        assert "1234567890123456" in masked
        
    def test_error_handling_with_normalized_paths(self):
        """Test error handling with path normalization."""
        middleware = ErrorHandlerMiddleware(app=Mock())
        
        # Mock request with dynamic path
        request = Mock()
        request.method = "GET"
        request.url.path = "/users/12345/jobs/abc-def-123"
        
        # The normalized path should be used in metrics
        normalized = middleware._normalize_path(request.url.path)
        assert normalized == "/users/{id}/jobs/{id}"
        
    def test_exception_creation_with_explicit_codes(self):
        """Test creating exceptions with explicit error codes."""
        exceptions = [
            ValidationException("Error", error_code=ErrorCode.VALIDATION_RANGE_VIOLATION),
            StorageException("Error", error_code=ErrorCode.STORAGE_CORRUPT_FILE),
            AIException("Error", error_code=ErrorCode.AI_HINT_REQUIRED),
            FreeCADException("Error", error_code=ErrorCode.FC_SKETCH_OVERCONSTRAINED),
        ]
        
        expected_codes = [
            ErrorCode.VALIDATION_RANGE_VIOLATION,
            ErrorCode.STORAGE_CORRUPT_FILE,
            ErrorCode.AI_HINT_REQUIRED,
            ErrorCode.FC_SKETCH_OVERCONSTRAINED,
        ]
        
        for exc, expected_code in zip(exceptions, expected_codes):
            assert exc.error_code == expected_code


if __name__ == "__main__":
    pytest.main([__file__, "-v"])