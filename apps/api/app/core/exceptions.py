"""
Ultra-Enterprise Error Taxonomy and Exception Handling for Task 7.12

This module provides comprehensive error handling with:
- Unified error taxonomy mapping worker exceptions to actionable API errors
- FreeCAD-specific error codes and handling
- Bilingual (Turkish/English) error messages
- Actionable suggestions and remediation links
- PII masking for logs
- Request/job correlation IDs
- HTTP status code mapping
- Integration with existing Task 7.x implementations
"""

from __future__ import annotations

import re
import traceback
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field
from fastapi import HTTPException, status

from ..core.logging import get_logger
from ..middleware.correlation_middleware import get_correlation_id
from .pii import PIIMasker
from .error_models import ErrorSuggestion, RemediationLink, ErrorDetails
from .providers import ErrorMessageProvider, SuggestionProvider, RemediationLinkProvider

logger = get_logger(__name__)


class ErrorCategory(str, Enum):
    """High-level error categories for classification."""
    AI = "ai"
    VALIDATION = "validation"
    FREECAD = "freecad"
    STORAGE = "storage"
    NETWORK = "network"
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    SYSTEM = "system"
    BUSINESS = "business"


class ErrorCode(str, Enum):
    """Comprehensive error code taxonomy for Task 7.12."""
    
    # AI-related errors (4xx)
    AI_AMBIGUOUS = "AI_AMBIGUOUS"  # 425 - Too Early
    AI_HINT_REQUIRED = "AI_HINT_REQUIRED"  # 422
    AI_PROMPT_TOO_COMPLEX = "AI_PROMPT_TOO_COMPLEX"  # 422
    AI_UNSUPPORTED_OPERATION = "AI_UNSUPPORTED_OPERATION"  # 422
    
    # Validation errors (4xx)
    VALIDATION_MISSING_FIELD = "VALIDATION_MISSING_FIELD"  # 422
    VALIDATION_UNIT_MISMATCH = "VALIDATION_UNIT_MISMATCH"  # 422
    VALIDATION_RANGE_VIOLATION = "VALIDATION_RANGE_VIOLATION"  # 422
    VALIDATION_UNSUPPORTED_FORMAT = "VALIDATION_UNSUPPORTED_FORMAT"  # 415
    VALIDATION_CONFLICT = "VALIDATION_CONFLICT"  # 409
    VALIDATION_CONSTRAINT_VIOLATION = "VALIDATION_CONSTRAINT_VIOLATION"  # 422
    
    # FreeCAD geometry errors (4xx)
    FC_GEOM_INVALID_SHAPE = "FC_GEOM_INVALID_SHAPE"  # 422
    FC_BOOLEAN_FAILED = "FC_BOOLEAN_FAILED"  # 422
    FC_FILLET_CHAMFER_FAILED = "FC_FILLET_CHAMFER_FAILED"  # 422
    FC_SKETCH_OVERCONSTRAINED = "FC_SKETCH_OVERCONSTRAINED"  # 409
    FC_SKETCH_UNDERCONSTRAINED = "FC_SKETCH_UNDERCONSTRAINED"  # 422
    FC_RECOMPUTE_FAILED = "FC_RECOMPUTE_FAILED"  # 422/500
    FC_TOPONAMING_UNSTABLE = "FC_TOPONAMING_UNSTABLE"  # 409
    FC_MESH_FAILED = "FC_MESH_FAILED"  # 422
    
    # FreeCAD import/export errors
    FC_IMPORT_STEP_FAILED = "FC_IMPORT_STEP_FAILED"  # 422
    FC_IMPORT_IGES_FAILED = "FC_IMPORT_IGES_FAILED"  # 422
    FC_IMPORT_STL_FAILED = "FC_IMPORT_STL_FAILED"  # 422
    FC_EXPORT_STEP_FAILED = "FC_EXPORT_STEP_FAILED"  # 500
    FC_EXPORT_STL_FAILED = "FC_EXPORT_STL_FAILED"  # 500
    FC_EXPORT_GCODE_FAILED = "FC_EXPORT_GCODE_FAILED"  # 500
    
    # Assembly4 errors
    FC_A4_UNSOLVED = "FC_A4_UNSOLVED"  # 409
    FC_A4_LINK_SCOPE = "FC_A4_LINK_SCOPE"  # 409
    FC_A4_CYCLIC_DEPENDENCY = "FC_A4_CYCLIC_DEPENDENCY"  # 409
    
    # Storage errors (5xx)
    STORAGE_WRITE_FAILED = "STORAGE_WRITE_FAILED"  # 503
    STORAGE_READ_FAILED = "STORAGE_READ_FAILED"  # 503
    STORAGE_QUOTA_EXCEEDED = "STORAGE_QUOTA_EXCEEDED"  # 507
    STORAGE_CORRUPT_FILE = "STORAGE_CORRUPT_FILE"  # 500
    
    # System errors
    TIMEOUT_WORKER = "TIMEOUT_WORKER"  # 504
    MEMORY_LIMIT_EXCEEDED = "MEMORY_LIMIT_EXCEEDED"  # 507
    CPU_LIMIT_EXCEEDED = "CPU_LIMIT_EXCEEDED"  # 503
    RATE_LIMITED = "RATE_LIMITED"  # 429
    
    # Auth errors
    AUTH_UNAUTHORIZED = "AUTH_UNAUTHORIZED"  # 401
    AUTH_FORBIDDEN = "AUTH_FORBIDDEN"  # 403
    AUTH_TOKEN_EXPIRED = "AUTH_TOKEN_EXPIRED"  # 401
    
    # Generic errors
    INTERNAL_ERROR = "INTERNAL_ERROR"  # 500
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"  # 503
    NOT_FOUND = "NOT_FOUND"  # 404
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"  # 405


# Error code to HTTP status mapping
ERROR_HTTP_MAPPING: Dict[ErrorCode, int] = {
    # AI errors
    ErrorCode.AI_AMBIGUOUS: 425,  # Too Early
    ErrorCode.AI_HINT_REQUIRED: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.AI_PROMPT_TOO_COMPLEX: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.AI_UNSUPPORTED_OPERATION: status.HTTP_422_UNPROCESSABLE_ENTITY,
    
    # Validation errors
    ErrorCode.VALIDATION_MISSING_FIELD: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.VALIDATION_UNIT_MISMATCH: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.VALIDATION_RANGE_VIOLATION: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.VALIDATION_UNSUPPORTED_FORMAT: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    ErrorCode.VALIDATION_CONFLICT: status.HTTP_409_CONFLICT,
    ErrorCode.VALIDATION_CONSTRAINT_VIOLATION: status.HTTP_422_UNPROCESSABLE_ENTITY,
    
    # FreeCAD geometry errors
    ErrorCode.FC_GEOM_INVALID_SHAPE: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.FC_BOOLEAN_FAILED: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.FC_FILLET_CHAMFER_FAILED: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.FC_SKETCH_OVERCONSTRAINED: status.HTTP_409_CONFLICT,
    ErrorCode.FC_SKETCH_UNDERCONSTRAINED: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.FC_RECOMPUTE_FAILED: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.FC_TOPONAMING_UNSTABLE: status.HTTP_409_CONFLICT,
    ErrorCode.FC_MESH_FAILED: status.HTTP_422_UNPROCESSABLE_ENTITY,
    
    # FreeCAD import/export errors
    ErrorCode.FC_IMPORT_STEP_FAILED: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.FC_IMPORT_IGES_FAILED: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.FC_IMPORT_STL_FAILED: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.FC_EXPORT_STEP_FAILED: status.HTTP_500_INTERNAL_SERVER_ERROR,
    ErrorCode.FC_EXPORT_STL_FAILED: status.HTTP_500_INTERNAL_SERVER_ERROR,
    ErrorCode.FC_EXPORT_GCODE_FAILED: status.HTTP_500_INTERNAL_SERVER_ERROR,
    
    # Assembly4 errors
    ErrorCode.FC_A4_UNSOLVED: status.HTTP_409_CONFLICT,
    ErrorCode.FC_A4_LINK_SCOPE: status.HTTP_409_CONFLICT,
    ErrorCode.FC_A4_CYCLIC_DEPENDENCY: status.HTTP_409_CONFLICT,
    
    # Storage errors
    ErrorCode.STORAGE_WRITE_FAILED: status.HTTP_503_SERVICE_UNAVAILABLE,
    ErrorCode.STORAGE_READ_FAILED: status.HTTP_503_SERVICE_UNAVAILABLE,
    ErrorCode.STORAGE_QUOTA_EXCEEDED: status.HTTP_507_INSUFFICIENT_STORAGE,
    ErrorCode.STORAGE_CORRUPT_FILE: status.HTTP_500_INTERNAL_SERVER_ERROR,
    
    # System errors
    ErrorCode.TIMEOUT_WORKER: status.HTTP_504_GATEWAY_TIMEOUT,
    ErrorCode.MEMORY_LIMIT_EXCEEDED: status.HTTP_507_INSUFFICIENT_STORAGE,
    ErrorCode.CPU_LIMIT_EXCEEDED: status.HTTP_503_SERVICE_UNAVAILABLE,
    ErrorCode.RATE_LIMITED: status.HTTP_429_TOO_MANY_REQUESTS,
    
    # Auth errors
    ErrorCode.AUTH_UNAUTHORIZED: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.AUTH_FORBIDDEN: status.HTTP_403_FORBIDDEN,
    ErrorCode.AUTH_TOKEN_EXPIRED: status.HTTP_401_UNAUTHORIZED,
    
    # Generic errors
    ErrorCode.INTERNAL_ERROR: status.HTTP_500_INTERNAL_SERVER_ERROR,
    ErrorCode.SERVICE_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
    ErrorCode.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.METHOD_NOT_ALLOWED: status.HTTP_405_METHOD_NOT_ALLOWED,
}




class ErrorResponse(BaseModel):
    """Comprehensive error response model."""
    code: ErrorCode = Field(description="Error code")
    http_status: int = Field(description="HTTP status code")
    message_en: str = Field(description="English error message")
    message_tr: str = Field(description="Turkish error message")
    details: Optional[ErrorDetails] = Field(default=None, description="Error details")
    suggestions: List[ErrorSuggestion] = Field(default_factory=list, description="Actionable suggestions")
    remediation_links: List[RemediationLink] = Field(default_factory=list, description="Help links")
    request_id: Optional[str] = Field(default=None, description="Request correlation ID")
    job_id: Optional[str] = Field(default=None, description="Job ID if applicable")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))



class FreeCADErrorPatternMatcher:
    """Pattern matcher for FreeCAD-specific errors."""
    
    # FreeCAD error patterns mapped to error codes
    PATTERNS = [
        # Part/OCC errors
        (r"Part\.OCCError.*BRep_API.*command not done", ErrorCode.FC_BOOLEAN_FAILED),
        (r"BRep_API.*command not done", ErrorCode.FC_BOOLEAN_FAILED),
        (r"TopoDS.*is null", ErrorCode.FC_GEOM_INVALID_SHAPE),
        (r"Shape is null", ErrorCode.FC_GEOM_INVALID_SHAPE),
        (r"self-intersect", ErrorCode.FC_GEOM_INVALID_SHAPE),
        (r"non-manifold", ErrorCode.FC_GEOM_INVALID_SHAPE),
        
        # Sketch errors
        (r"Sketch.*Over-constrained", ErrorCode.FC_SKETCH_OVERCONSTRAINED),
        (r"Sketch.*Under-constrained", ErrorCode.FC_SKETCH_UNDERCONSTRAINED),
        (r"Conflicting constraints", ErrorCode.FC_SKETCH_OVERCONSTRAINED),
        (r"Solver.*failed", ErrorCode.FC_SKETCH_OVERCONSTRAINED),
        
        # Fillet/Chamfer errors
        (r"Failed to make fillet", ErrorCode.FC_FILLET_CHAMFER_FAILED),
        (r"Failed to make chamfer", ErrorCode.FC_FILLET_CHAMFER_FAILED),
        (r"Fillet.*failed", ErrorCode.FC_FILLET_CHAMFER_FAILED),
        (r"radius.*exceed.*edge", ErrorCode.FC_FILLET_CHAMFER_FAILED),
        
        # Import/Export errors
        (r"Cannot import STEP", ErrorCode.FC_IMPORT_STEP_FAILED),
        (r"STEP.*import.*failed", ErrorCode.FC_IMPORT_STEP_FAILED),
        (r"Cannot import IGES", ErrorCode.FC_IMPORT_IGES_FAILED),
        (r"IGES.*import.*failed", ErrorCode.FC_IMPORT_IGES_FAILED),
        (r"STL.*import.*failed", ErrorCode.FC_IMPORT_STL_FAILED),
        (r"Export.*STEP.*failed", ErrorCode.FC_EXPORT_STEP_FAILED),
        (r"Export.*STL.*failed", ErrorCode.FC_EXPORT_STL_FAILED),
        
        # Assembly4 errors
        (r"Assembly.*solver.*failed", ErrorCode.FC_A4_UNSOLVED),
        (r"Link.*out of scope", ErrorCode.FC_A4_LINK_SCOPE),
        (r"LCS.*missing", ErrorCode.FC_A4_LINK_SCOPE),
        (r"Cyclic.*dependency", ErrorCode.FC_A4_CYCLIC_DEPENDENCY),
        
        # Mesh errors
        (r"Mesh.*failed", ErrorCode.FC_MESH_FAILED),
        (r"triangulation.*failed", ErrorCode.FC_MESH_FAILED),
        (r"Mesher.*error", ErrorCode.FC_MESH_FAILED),
        
        # Recompute errors
        (r"recompute.*failed", ErrorCode.FC_RECOMPUTE_FAILED),
        (r"Document.*recompute.*error", ErrorCode.FC_RECOMPUTE_FAILED),
        
        # TopoNaming errors
        (r"lost.*reference", ErrorCode.FC_TOPONAMING_UNSTABLE),
        (r"toponaming", ErrorCode.FC_TOPONAMING_UNSTABLE),
    ]
    
    @classmethod
    def match_error(cls, error_message: str) -> Optional[ErrorCode]:
        """Match error message to FreeCAD error code."""
        if not error_message:
            return None
        
        for pattern, error_code in cls.PATTERNS:
            if re.search(pattern, error_message, re.IGNORECASE):
                return error_code
        
        return None



class EnterpriseException(Exception):
    """Base exception class with enterprise features."""
    
    def __init__(
        self,
        error_code: ErrorCode,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        job_id: Optional[str] = None,
        phase: Optional[str] = None,
        suggestions: Optional[List[ErrorSuggestion]] = None,
        remediation_links: Optional[List[RemediationLink]] = None,
    ):
        self.error_code = error_code
        self.details = details or {}
        self.job_id = job_id
        self.phase = phase
        self.suggestions = suggestions or []
        self.remediation_links = remediation_links or []
        
        # Get messages
        message_en, message_tr = ErrorMessageProvider.get_message(error_code)
        self.message_en = message or message_en
        self.message_tr = message_tr
        
        # Get HTTP status
        self.http_status = ERROR_HTTP_MAPPING.get(error_code, 500)
        
        # Get correlation ID
        self.request_id = get_correlation_id()
        
        # Mask PII in details
        if self.details:
            self.details = PIIMasker.mask_dict(self.details)
        
        super().__init__(self.message_en)
    
    def to_error_response(self) -> ErrorResponse:
        """Convert exception to error response."""
        # Get suggestions if not provided
        if not self.suggestions:
            self.suggestions = SuggestionProvider.get_suggestions(self.error_code)
        
        # Get remediation links if not provided
        if not self.remediation_links:
            self.remediation_links = RemediationLinkProvider.get_links(self.error_code)
        
        # Build error details
        error_details = ErrorDetails(
            component=self.details.get("component"),
            exception_class=self.__class__.__name__,
            phase=self.phase,
            file_format=self.details.get("file_format"),
            param=self.details.get("param")
        )
        
        return ErrorResponse(
            code=self.error_code,
            http_status=self.http_status,
            message_en=self.message_en,
            message_tr=self.message_tr,
            details=error_details,
            suggestions=self.suggestions,
            remediation_links=self.remediation_links,
            request_id=self.request_id,
            job_id=self.job_id
        )
    
    def to_http_exception(self) -> HTTPException:
        """Convert to FastAPI HTTPException."""
        response = self.to_error_response()
        return HTTPException(
            status_code=self.http_status,
            detail=response.dict()
        )


# Specific exception classes for common scenarios
class FreeCADException(EnterpriseException):
    """FreeCAD-specific exception."""
    
    def __init__(
        self,
        message: str,
        error_code: Optional[ErrorCode] = None,
        **kwargs
    ):
        # Allow explicit error_code to be passed, otherwise match from pattern
        if error_code is None:
            error_code = FreeCADErrorPatternMatcher.match_error(message)
            if not error_code:
                error_code = ErrorCode.FC_RECOMPUTE_FAILED  # Default FreeCAD error
        
        super().__init__(
            error_code=error_code,
            message=message,
            **kwargs
        )


class ValidationException(EnterpriseException):
    """Validation exception."""
    
    def __init__(
        self, 
        message: str, 
        field: Optional[str] = None,
        error_code: Optional[ErrorCode] = None,
        **kwargs
    ):
        # Allow explicit error_code to be passed, otherwise determine from message
        if error_code is None:
            # Dictionary-based lookup for cleaner code
            error_map = {
                "missing": ErrorCode.VALIDATION_MISSING_FIELD,
                "range": ErrorCode.VALIDATION_RANGE_VIOLATION,
                "conflict": ErrorCode.VALIDATION_CONFLICT,
            }
            
            message_lower = message.lower()
            error_code = ErrorCode.VALIDATION_CONSTRAINT_VIOLATION  # Default
            
            for keyword, code in error_map.items():
                if keyword in message_lower:
                    error_code = code
                    break
        
        details = kwargs.pop("details", {})  # Remove details from kwargs
        if field:
            details["field"] = field
        
        super().__init__(
            error_code=error_code,
            message=message,
            details=details,
            **kwargs
        )


class StorageException(EnterpriseException):
    """Storage-related exception."""
    
    def __init__(
        self,
        message: str,
        operation: str = "unknown",
        error_code: Optional[ErrorCode] = None,
        **kwargs
    ):
        # Allow explicit error_code to be passed, otherwise determine from message/operation
        if error_code is None:
            # Dictionary-based lookup for cleaner code
            message_map = {
                "quota": ErrorCode.STORAGE_QUOTA_EXCEEDED,
            }
            
            operation_map = {
                "write": ErrorCode.STORAGE_WRITE_FAILED,
                "read": ErrorCode.STORAGE_READ_FAILED,
            }
            
            message_lower = message.lower()
            operation_lower = operation.lower()
            error_code = ErrorCode.STORAGE_CORRUPT_FILE  # Default
            
            # Check message first
            for keyword, code in message_map.items():
                if keyword in message_lower:
                    error_code = code
                    break
            else:
                # Check operation if no message match
                for keyword, code in operation_map.items():
                    if keyword in operation_lower:
                        error_code = code
                        break
        
        super().__init__(
            error_code=error_code,
            message=message,
            **kwargs
        )


class AIException(EnterpriseException):
    """AI-related exception."""
    
    def __init__(
        self,
        message: str,
        error_code: Optional[ErrorCode] = None,
        **kwargs
    ):
        # Allow explicit error_code to be passed, otherwise determine from message
        if error_code is None:
            # Dictionary-based lookup for cleaner code
            error_map = {
                "ambiguous": ErrorCode.AI_AMBIGUOUS,
                "hint": ErrorCode.AI_HINT_REQUIRED,
                "additional": ErrorCode.AI_HINT_REQUIRED,
                "complex": ErrorCode.AI_PROMPT_TOO_COMPLEX,
            }
            
            message_lower = message.lower()
            error_code = ErrorCode.AI_UNSUPPORTED_OPERATION  # Default
            
            for keyword, code in error_map.items():
                if keyword in message_lower:
                    error_code = code
                    break
        
        super().__init__(
            error_code=error_code,
            message=message,
            **kwargs
        )


def map_exception_to_error_response(
    exception: Exception,
    job_id: Optional[str] = None,
    phase: Optional[str] = None
) -> ErrorResponse:
    """Map any exception to error response."""
    
    # If already an EnterpriseException, use its response
    if isinstance(exception, EnterpriseException):
        return exception.to_error_response()
    
    # Try to match FreeCAD patterns
    error_message = str(exception)
    error_code = FreeCADErrorPatternMatcher.match_error(error_message)
    
    # Map common Python exceptions
    if not error_code:
        if isinstance(exception, ValueError):
            error_code = ErrorCode.VALIDATION_CONSTRAINT_VIOLATION
        elif isinstance(exception, TypeError):
            error_code = ErrorCode.VALIDATION_UNSUPPORTED_FORMAT
        elif isinstance(exception, TimeoutError):
            error_code = ErrorCode.TIMEOUT_WORKER
        elif isinstance(exception, MemoryError):
            error_code = ErrorCode.MEMORY_LIMIT_EXCEEDED
        elif isinstance(exception, PermissionError):
            error_code = ErrorCode.AUTH_FORBIDDEN
        elif isinstance(exception, FileNotFoundError):
            error_code = ErrorCode.NOT_FOUND
        elif isinstance(exception, OSError):
            if "space" in error_message.lower():
                error_code = ErrorCode.STORAGE_QUOTA_EXCEEDED
            else:
                error_code = ErrorCode.STORAGE_WRITE_FAILED
        else:
            error_code = ErrorCode.INTERNAL_ERROR
    
    # Create error response
    message_en, message_tr = ErrorMessageProvider.get_message(error_code)
    
    # Mask PII in error message
    masked_message = PIIMasker.mask_text(error_message)
    
    return ErrorResponse(
        code=error_code,
        http_status=ERROR_HTTP_MAPPING.get(error_code, 500),
        message_en=message_en,
        message_tr=message_tr,
        details=ErrorDetails(
            component="unknown",
            exception_class=exception.__class__.__name__,
            phase=phase,
            param={"original_error": masked_message}
        ),
        suggestions=SuggestionProvider.get_suggestions(error_code),
        remediation_links=RemediationLinkProvider.get_links(error_code),
        request_id=get_correlation_id(),
        job_id=job_id
    )


def log_error_with_masking(
    logger_instance,
    message: str,
    exception: Optional[Exception] = None,
    **kwargs
) -> None:
    """Log error with PII masking."""
    
    # Mask message
    masked_message = PIIMasker.mask_text(message)
    
    # Mask kwargs
    masked_kwargs = PIIMasker.mask_dict(kwargs) if kwargs else {}
    
    # Add exception info if present
    if exception:
        masked_kwargs["exception_class"] = exception.__class__.__name__
        masked_kwargs["exception_message"] = PIIMasker.mask_text(str(exception))
        
        # Add sanitized traceback
        if hasattr(exception, "__traceback__"):
            tb_lines = traceback.format_tb(exception.__traceback__)
            # Mask file paths in traceback
            masked_tb = [PIIMasker.mask_text(line) for line in tb_lines]
            masked_kwargs["traceback_sanitized"] = masked_tb
    
    # Add correlation ID
    masked_kwargs["request_id"] = get_correlation_id()
    
    # Log with masked data
    logger_instance.error(masked_message, **masked_kwargs)