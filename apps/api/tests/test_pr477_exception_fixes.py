"""
Test suite for PR #477 exception error code fixes.

Tests focus on allowing ErrorCode to be passed directly to exception constructors.
"""

import pytest
import sys
import os

# Add the app directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.exceptions import (
    ValidationException,
    StorageException,
    AIException,
    FreeCADException,
    ErrorCode
)


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])