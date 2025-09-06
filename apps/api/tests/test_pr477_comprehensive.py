"""
Comprehensive test suite for PR #477 fixes.

This file consolidates all tests from:
- test_pr477_fixes.py
- test_pr477_exception_fixes.py
- test_pr477_validation_fixes.py

Tests cover:
1. Turkish TC Kimlik No validation with checksum algorithm
2. Credit card validation with Luhn algorithm
3. Path normalization for metrics
4. ErrorCode passing to exception constructors
5. Error category dictionary lookup
6. Recursive PII masking for nested data structures
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
            "12345678950",  # Another valid test number with proper checksum
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
            "4532015112830367",  # Invalid checksum (last digit should be 6, not 7)
            "1234567890123456",  # Random 16 digits
            "1111111111111111",  # All ones (invalid checksum)
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


class TestRecursivePIIMasking:
    """Test recursive PII masking for nested data structures."""
    
    def test_mask_nested_dict(self):
        """Test masking of nested dictionaries."""
        data = {
            "user": {
                "email": "test@example.com",
                "profile": {
                    "tc_no": "10000000146",  # Valid TC, should be masked
                    "phone": "+90 555 123 4567"
                }
            },
            "payment": {
                "card": "4532015112830366"  # Valid card, should be masked
            }
        }
        
        masked = PIIMasker.mask_dict(data)
        
        # Check nested email is masked
        assert "[email redacted]" in masked["user"]["email"]
        assert "test@example.com" not in str(masked)
        
        # Check nested TC is masked
        assert "[tc_no redacted]" in masked["user"]["profile"]["tc_no"]
        assert "10000000146" not in str(masked)
        
        # Check nested card is masked
        assert "[card redacted]" in masked["payment"]["card"]
        assert "4532015112830366" not in str(masked)
        
    def test_mask_list_with_dicts(self):
        """Test masking of lists containing dictionaries."""
        data = {
            "users": [
                {"email": "user1@example.com", "tc": "10000000146"},
                {"email": "user2@example.com", "tc": "12345678901"},  # Invalid TC
            ],
            "cards": ["4532015112830366", "1234567890123456"]  # One valid, one invalid
        }
        
        masked = PIIMasker.mask_dict(data)
        
        # First user's email should be masked
        assert "[email redacted]" in masked["users"][0]["email"]
        assert "user1@example.com" not in str(masked)
        
        # First user's valid TC should be masked
        assert "[tc_no redacted]" in masked["users"][0]["tc"]
        
        # Second user's invalid TC should NOT be masked
        assert "12345678901" in masked["users"][1]["tc"]
        
        # Valid card should be masked
        assert "[card redacted]" in masked["cards"][0]
        
        # Invalid card should NOT be masked
        assert "1234567890123456" in masked["cards"][1]
        
    def test_mask_deeply_nested_structures(self):
        """Test masking of deeply nested mixed structures."""
        data = {
            "level1": {
                "level2": [
                    {
                        "level3": {
                            "emails": ["test@example.com", "user@domain.org"],
                            "data": [
                                {"card": "4532015112830366"},
                                {"password": "secret123"}
                            ]
                        }
                    }
                ]
            }
        }
        
        masked = PIIMasker.mask_dict(data)
        
        # Check deeply nested emails are masked
        emails = masked["level1"]["level2"][0]["level3"]["emails"]
        assert all("[email redacted]" in email for email in emails)
        
        # Check nested card is masked
        assert "[card redacted]" in masked["level1"]["level2"][0]["level3"]["data"][0]["card"]
        
        # Check password field is completely redacted
        assert masked["level1"]["level2"][0]["level3"]["data"][1]["password"] == "[redacted]"
        
    def test_mask_sensitive_keys(self):
        """Test that sensitive keys are always redacted regardless of value."""
        data = {
            "password": "just_a_number_12345",
            "secret_key": "not_really_secret",
            "auth_token": "bearer_abc123",
            "api_key": "key_12345",
            "nested": {
                "db_password": "postgres123",
                "jwt_secret": "my_jwt_secret"
            }
        }
        
        masked = PIIMasker.mask_dict(data)
        
        # All sensitive keys should be redacted
        assert masked["password"] == "[redacted]"
        assert masked["secret_key"] == "[redacted]"
        assert masked["auth_token"] == "[redacted]"
        assert masked["api_key"] == "[redacted]"
        assert masked["nested"]["db_password"] == "[redacted]"
        assert masked["nested"]["jwt_secret"] == "[redacted]"


class TestPathNormalization:
    """Test path normalization for metrics."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.middleware = ErrorHandlerMiddleware(app=Mock())
        
    def test_normalize_numeric_ids(self):
        """Test normalization of numeric IDs."""
        # Test with trailing slash (original tests)
        assert self.middleware._normalize_path("/users/123/") == "/users/{username}/"
        assert self.middleware._normalize_path("/jobs/456789/") == "/jobs/{id}/"
        assert self.middleware._normalize_path("/items/1/details") == "/items/{id}/details"
        
        # Test without trailing slash (new requirement)
        assert self.middleware._normalize_path("/users/123") == "/users/{username}"
        assert self.middleware._normalize_path("/jobs/456789") == "/jobs/{id}"
        assert self.middleware._normalize_path("/artefacts/1234") == "/artefacts/{id}"
        
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
        # Test with action after queue name  
        assert self.middleware._normalize_path("/queues/my_queue/pause") == "/queues/{name}/pause"
        assert self.middleware._normalize_path("/queues/test-queue/resume") == "/queues/{name}/resume"
        
        # Test without trailing slash (important edge case)
        assert self.middleware._normalize_path("/queues/my-queue") == "/queues/{name}"
        assert self.middleware._normalize_path("/queues/default") == "/queues/{name}"
        
    def test_normalize_user_paths(self):
        """Test normalization of user paths."""
        # Test with actions after username
        assert self.middleware._normalize_path("/users/john.doe/profile") == "/users/{username}/profile"
        assert self.middleware._normalize_path("/users/user123/settings") == "/users/{username}/settings"
        
        # Test without trailing slash
        assert self.middleware._normalize_path("/users/john") == "/users/{username}"
        assert self.middleware._normalize_path("/users/admin") == "/users/{username}"
        
    def test_normalize_project_paths(self):
        """Test normalization of project paths."""
        # Test with action after project name
        assert self.middleware._normalize_path("/projects/my-project/files") == "/projects/{name}/files"
        
        # Test without trailing slash
        assert self.middleware._normalize_path("/projects/my-project") == "/projects/{name}"
        assert self.middleware._normalize_path("/projects/test") == "/projects/{name}"
        
    def test_preserve_static_paths(self):
        """Test that static paths are preserved."""
        assert self.middleware._normalize_path("/health") == "/health"
        assert self.middleware._normalize_path("/api/v1/status") == "/api/v1/status"
        
    def test_complex_paths(self):
        """Test normalization of complex paths."""
        assert self.middleware._normalize_path("/users/123/jobs/456/artefacts/789") == "/users/{id}/jobs/{id}/artefacts/{id}"
        
    def test_pattern_ordering(self):
        """Test that specific patterns are matched before generic ones."""
        # These should match specific patterns, not generic alphanumeric
        assert self.middleware._normalize_path("/queues/my-special-queue/status") == "/queues/{name}/status"
        assert self.middleware._normalize_path("/users/john-doe-123/profile") == "/users/{username}/profile"
        
        # These should match generic patterns
        assert self.middleware._normalize_path("/random/abc123def456") == "/random/{id}"
    
    def test_edge_cases_without_trailing_slash(self):
        """Test edge cases for paths without trailing slash."""
        # Test all specific patterns without trailing slash
        assert self.middleware._normalize_path("/queues/my-queue") == "/queues/{name}"
        assert self.middleware._normalize_path("/users/john123") == "/users/{username}"
        assert self.middleware._normalize_path("/projects/proj-1") == "/projects/{name}"
        assert self.middleware._normalize_path("/artefacts/art123") == "/artefacts/{id}"
        assert self.middleware._normalize_path("/jobs/job-abc-123") == "/jobs/{id}"
        
        # Test that paths with trailing slash still work
        assert self.middleware._normalize_path("/queues/my-queue/") == "/queues/{name}/"
        assert self.middleware._normalize_path("/users/john123/") == "/users/{username}/"
        
        # Test mixed paths (some with slash, some without)
        assert self.middleware._normalize_path("/users/123/jobs/456") == "/users/{username}/jobs/{id}"
        assert self.middleware._normalize_path("/projects/proj1/artefacts/123/download") == "/projects/{name}/artefacts/{id}/download"


class TestErrorCategoryDictionaryLookup:
    """Test error category determination using dictionary lookup."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.middleware = ErrorHandlerMiddleware(app=Mock())
        
    def test_ai_category(self):
        """Test AI error category detection."""
        assert self.middleware._get_error_category(ErrorCode.AI_AMBIGUOUS) == "ai"
        assert self.middleware._get_error_category(ErrorCode.AI_HINT_REQUIRED) == "ai"
        assert self.middleware._get_error_category(ErrorCode.AI_PROMPT_TOO_COMPLEX) == "ai"
        assert self.middleware._get_error_category(ErrorCode.AI_UNSUPPORTED_OPERATION) == "ai"
        
    def test_validation_category(self):
        """Test validation error category detection."""
        assert self.middleware._get_error_category(ErrorCode.VALIDATION_MISSING_FIELD) == "validation"
        assert self.middleware._get_error_category(ErrorCode.VALIDATION_CONFLICT) == "validation"
        assert self.middleware._get_error_category(ErrorCode.VALIDATION_RANGE_VIOLATION) == "validation"
        assert self.middleware._get_error_category(ErrorCode.VALIDATION_CONSTRAINT_VIOLATION) == "validation"
        
    def test_freecad_category(self):
        """Test FreeCAD error category detection."""
        assert self.middleware._get_error_category(ErrorCode.FC_RECOMPUTE_FAILED) == "freecad"
        assert self.middleware._get_error_category(ErrorCode.FC_GEOM_INVALID_SHAPE) == "freecad"
        assert self.middleware._get_error_category(ErrorCode.FC_BOOLEAN_FAILED) == "freecad"
        assert self.middleware._get_error_category(ErrorCode.FC_SKETCH_OVERCONSTRAINED) == "freecad"
        
    def test_storage_category(self):
        """Test storage error category detection."""
        assert self.middleware._get_error_category(ErrorCode.STORAGE_QUOTA_EXCEEDED) == "storage"
        assert self.middleware._get_error_category(ErrorCode.STORAGE_WRITE_FAILED) == "storage"
        assert self.middleware._get_error_category(ErrorCode.STORAGE_READ_FAILED) == "storage"
        assert self.middleware._get_error_category(ErrorCode.STORAGE_CORRUPT_FILE) == "storage"
        
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
            error_code=ErrorCode.FC_BOOLEAN_FAILED
        )
        assert exc.error_code == ErrorCode.FC_BOOLEAN_FAILED
        
        exc = FreeCADException(
            "FreeCAD error",
            error_code=ErrorCode.FC_GEOM_INVALID_SHAPE
        )
        assert exc.error_code == ErrorCode.FC_GEOM_INVALID_SHAPE
        
    def test_backward_compatibility_validation(self):
        """Test ValidationException backward compatibility."""
        # Test message-based detection still works
        exc = ValidationException("Field is missing")
        assert exc.error_code == ErrorCode.VALIDATION_MISSING_FIELD
        
        exc = ValidationException("Value out of range")
        assert exc.error_code == ErrorCode.VALIDATION_RANGE_VIOLATION
        
        exc = ValidationException("Conflict detected")
        assert exc.error_code == ErrorCode.VALIDATION_CONFLICT
        
        exc = ValidationException("Some other error")
        assert exc.error_code == ErrorCode.VALIDATION_CONSTRAINT_VIOLATION
        
    def test_backward_compatibility_storage(self):
        """Test StorageException backward compatibility."""
        # Test operation-based detection still works
        exc = StorageException("Error", operation="write")
        assert exc.error_code == ErrorCode.STORAGE_WRITE_FAILED
        
        exc = StorageException("Error", operation="read")
        assert exc.error_code == ErrorCode.STORAGE_READ_FAILED
        
        exc = StorageException("Quota exceeded")
        assert exc.error_code == ErrorCode.STORAGE_QUOTA_EXCEEDED
        
        exc = StorageException("Some error", operation="unknown")
        assert exc.error_code == ErrorCode.STORAGE_CORRUPT_FILE
        
    def test_backward_compatibility_ai(self):
        """Test AIException backward compatibility."""
        # Test message-based detection still works
        exc = AIException("Request is ambiguous")
        assert exc.error_code == ErrorCode.AI_AMBIGUOUS
        
        exc = AIException("Need additional hint")
        assert exc.error_code == ErrorCode.AI_HINT_REQUIRED
        
        exc = AIException("Too complex to process")
        assert exc.error_code == ErrorCode.AI_PROMPT_TOO_COMPLEX
        
        exc = AIException("Some other error")
        assert exc.error_code == ErrorCode.AI_UNSUPPORTED_OPERATION
        
    def test_backward_compatibility_freecad(self):
        """Test FreeCADException backward compatibility."""
        # Without explicit error_code, it should use pattern matching or default
        exc = FreeCADException("Some FreeCAD error")
        # Should default to FC_RECOMPUTE_FAILED if no pattern matches
        assert exc.error_code == ErrorCode.FC_RECOMPUTE_FAILED
        
    def test_field_parameter_validation_exception(self):
        """Test that field parameter still works with ValidationException."""
        exc = ValidationException(
            "Field required",
            field="username",
            error_code=ErrorCode.VALIDATION_MISSING_FIELD
        )
        assert exc.error_code == ErrorCode.VALIDATION_MISSING_FIELD
        assert exc.details.get("field") == "username"
        
    def test_mixed_parameters(self):
        """Test that all exceptions work with mixed parameters."""
        # ValidationException with all parameters
        exc = ValidationException(
            "Error message",
            field="email",
            error_code=ErrorCode.VALIDATION_CONFLICT,
            details={"extra": "info"}
        )
        assert exc.error_code == ErrorCode.VALIDATION_CONFLICT
        assert exc.details["field"] == "email"
        assert exc.details["extra"] == "info"
        
        # StorageException with all parameters
        exc = StorageException(
            "Storage failed",
            operation="delete",
            error_code=ErrorCode.STORAGE_QUOTA_EXCEEDED,
            details={"bucket": "test"}
        )
        assert exc.error_code == ErrorCode.STORAGE_QUOTA_EXCEEDED
        assert exc.details["bucket"] == "test"


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