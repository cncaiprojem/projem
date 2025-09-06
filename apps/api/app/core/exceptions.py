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
from decimal import Decimal

from pydantic import BaseModel, Field
from fastapi import HTTPException, status

from ..core.logging import get_logger
from ..middleware.correlation_middleware import get_correlation_id

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


class ErrorSuggestion(BaseModel):
    """Actionable suggestion for error remediation."""
    en: str = Field(description="English suggestion text")
    tr: str = Field(description="Turkish suggestion text")


class RemediationLink(BaseModel):
    """Documentation or resource link for error remediation."""
    title: str = Field(description="Link title")
    url: str = Field(description="Link URL")


class ErrorDetails(BaseModel):
    """Detailed error information."""
    component: Optional[str] = Field(default=None, description="Component where error occurred")
    exception_class: Optional[str] = Field(default=None, description="Exception class name")
    phase: Optional[str] = Field(default=None, description="Processing phase")
    file_format: Optional[str] = Field(default=None, description="File format if relevant")
    param: Optional[Dict[str, Any]] = Field(default=None, description="Sanitized parameters")


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


class PIIMasker:
    """Utility class for masking PII in logs and error messages."""
    
    @staticmethod
    def _is_valid_tc_kimlik_no(number: str) -> bool:
        """Validate Turkish TC Kimlik No with checksum algorithm.
        
        TC Kimlik No validation rules:
        - Must be 11 digits
        - First digit cannot be 0
        - 10th digit = ((sum of odd positions * 7) - sum of even positions) mod 10
        - 11th digit = sum of first 10 digits mod 10
        """
        if not number.isdigit() or len(number) != 11 or number[0] == '0':
            return False
        
        digits = [int(d) for d in number]
        
        # Calculate 10th digit checksum
        odd_sum = sum(digits[i] for i in range(0, 9, 2))  # positions 1,3,5,7,9
        even_sum = sum(digits[i] for i in range(1, 8, 2))  # positions 2,4,6,8
        tenth_digit = (odd_sum * 7 - even_sum) % 10
        
        if digits[9] != tenth_digit:
            return False
        
        # Calculate 11th digit checksum
        eleventh_digit = sum(digits[:10]) % 10
        
        return digits[10] == eleventh_digit
    
    @staticmethod
    def _is_valid_credit_card(number: str) -> bool:
        """Validate credit card number using Luhn algorithm.
        
        Luhn algorithm:
        1. Double every second digit from right to left
        2. If doubling results in a number > 9, sum the digits
        3. Sum all digits
        4. Valid if sum mod 10 == 0
        """
        # Remove spaces and hyphens
        cleaned = re.sub(r'[\s-]', '', number)
        
        if not cleaned.isdigit() or len(cleaned) < 13 or len(cleaned) > 19:
            return False
        
        def luhn_checksum(card_number: str) -> int:
            digits = [int(d) for d in card_number]
            # Reverse for easier processing
            digits.reverse()
            
            total = 0
            for i, digit in enumerate(digits):
                if i % 2 == 1:  # Every second digit (from right)
                    doubled = digit * 2
                    if doubled > 9:
                        # Sum the digits (e.g., 16 -> 1 + 6 = 7)
                        total += doubled // 10 + doubled % 10
                    else:
                        total += doubled
                else:
                    total += digit
            
            return total % 10
        
        return luhn_checksum(cleaned) == 0
    
    @classmethod
    def _mask_tc_kimlik_no(cls, match):
        """Mask Turkish TC Kimlik No only if valid."""
        number = match.group(0)
        if cls._is_valid_tc_kimlik_no(number):
            return '[tc_no redacted]'
        return number
    
    @classmethod
    def _mask_credit_card(cls, match):
        """Mask credit card only if valid according to Luhn algorithm."""
        number = match.group(0)
        if cls._is_valid_credit_card(number):
            return '[card redacted]'
        return number
    
    # PII patterns for masking
    PATTERNS = {
        'email': (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[email redacted]'),
        'phone': (r'\b(?:\+?90|0)?(?:\s*\(?5\d{2}\)?[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}|\d{3}[\s.-]?\d{3}[\s.-]?\d{4})\b', '[phone redacted]'),
        'jwt': (r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[token redacted]'),
        'api_key': (r'\b(?:api[_-]?key|apikey|token)["\']?\s*[:=]\s*["\']?([A-Za-z0-9_-]{20,})["\']?', '[api_key redacted]'),
        'ip_address': (r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '[ip redacted]'),
        'home_dir': (r'(?:/home/[^/\s]+|/Users/[^/\s]+|C:\\Users\\[^\\]+)', '[path redacted]'),
    }
    
    # Special patterns that require validation
    VALIDATION_PATTERNS = {
        'credit_card': (r'\b(?:\d{4}[\s-]?){3,4}\d{1,4}\b', _mask_credit_card),
        'tc_kimlik_no': (r'\b\d{11}\b', _mask_tc_kimlik_no),
    }
    
    @classmethod
    def mask_text(cls, text: str) -> str:
        """Mask PII in text."""
        if not text:
            return text
        
        masked = text
        
        # Apply simple patterns first
        for pattern_name, (pattern, replacement) in cls.PATTERNS.items():
            masked = re.sub(pattern, replacement, masked, flags=re.IGNORECASE)
        
        # Apply validation-based patterns
        for pattern_name, (pattern, validator_func) in cls.VALIDATION_PATTERNS.items():
            # Pass the class method with cls bound
            masked = re.sub(pattern, lambda m: validator_func.__func__(cls, m), masked)
        
        return masked
    
    @classmethod
    def mask_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively mask PII in dictionary."""
        if not data:
            return data
        
        masked = {}
        for key, value in data.items():
            # Mask sensitive keys entirely
            if any(sensitive in key.lower() for sensitive in ['password', 'secret', 'token', 'key', 'auth']):
                masked[key] = '[redacted]'
            elif isinstance(value, str):
                masked[key] = cls.mask_text(value)
            elif isinstance(value, dict):
                masked[key] = cls.mask_dict(value)
            elif isinstance(value, list):
                masked[key] = [cls.mask_text(item) if isinstance(item, str) else item for item in value]
            else:
                masked[key] = value
        
        return masked


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


class ErrorMessageProvider:
    """Provider for bilingual error messages."""
    
    MESSAGES = {
        ErrorCode.AI_AMBIGUOUS: {
            "en": "The prompt is ambiguous and requires clarification.",
            "tr": "İstem belirsiz ve açıklama gerektiriyor."
        },
        ErrorCode.AI_HINT_REQUIRED: {
            "en": "Additional information is required to process this request.",
            "tr": "Bu isteği işlemek için ek bilgi gerekiyor."
        },
        ErrorCode.FC_GEOM_INVALID_SHAPE: {
            "en": "The model geometry is invalid (non-manifold or self-intersecting) and cannot be processed.",
            "tr": "Model geometrisi geçersiz (manifold değil veya kendisiyle kesişiyor) ve işlenemiyor."
        },
        ErrorCode.FC_BOOLEAN_FAILED: {
            "en": "Boolean operation failed due to invalid geometry or coplanar surfaces.",
            "tr": "Boolean işlemi geçersiz geometri veya eş düzlemli yüzeyler nedeniyle başarısız oldu."
        },
        ErrorCode.FC_FILLET_CHAMFER_FAILED: {
            "en": "Fillet/Chamfer operation failed; radius may exceed adjacent edge limits.",
            "tr": "Kordon/Pah işlemi başarısız oldu; yarıçap komşu kenar sınırlarını aşmış olabilir."
        },
        ErrorCode.FC_SKETCH_OVERCONSTRAINED: {
            "en": "Sketch is over-constrained; some constraints conflict.",
            "tr": "Eskiz aşırı kısıtlanmış; bazı kısıtlar birbiriyle çakışıyor."
        },
        ErrorCode.FC_SKETCH_UNDERCONSTRAINED: {
            "en": "Sketch is under-constrained and has degrees of freedom.",
            "tr": "Eskiz yetersiz kısıtlanmış ve serbestlik dereceleri var."
        },
        ErrorCode.FC_IMPORT_STEP_FAILED: {
            "en": "Failed to import the STEP file. The file may be corrupted or use unsupported entities.",
            "tr": "STEP dosyası içe aktarılamadı. Dosya bozuk olabilir veya desteklenmeyen varlıklar içeriyor olabilir."
        },
        ErrorCode.FC_EXPORT_STL_FAILED: {
            "en": "Failed to export STL file. The model may have invalid geometry.",
            "tr": "STL dosyası dışa aktarılamadı. Model geçersiz geometriye sahip olabilir."
        },
        ErrorCode.FC_A4_UNSOLVED: {
            "en": "Assembly constraints cannot be solved; check LCS alignment and cyclic dependencies.",
            "tr": "Montaj kısıtları çözülemedi; LCS hizalamasını ve döngüsel bağımlılıkları kontrol edin."
        },
        ErrorCode.FC_A4_LINK_SCOPE: {
            "en": "Assembly links are out of scope or LCS is missing.",
            "tr": "Montaj bağlantıları kapsam dışında veya LCS eksik."
        },
        ErrorCode.FC_MESH_FAILED: {
            "en": "Mesh generation failed due to invalid geometry or non-manifold edges.",
            "tr": "Ağ oluşturma geçersiz geometri veya manifold olmayan kenarlar nedeniyle başarısız oldu."
        },
        ErrorCode.FC_RECOMPUTE_FAILED: {
            "en": "Document recompute failed due to cyclic dependencies or invalid operations.",
            "tr": "Belge yeniden hesaplama döngüsel bağımlılıklar veya geçersiz işlemler nedeniyle başarısız oldu."
        },
        ErrorCode.FC_TOPONAMING_UNSTABLE: {
            "en": "Topological references were lost after model changes.",
            "tr": "Model değişikliklerinden sonra topolojik referanslar kayboldu."
        },
        ErrorCode.TIMEOUT_WORKER: {
            "en": "Processing timed out. The model is too complex or system is overloaded.",
            "tr": "İşleme zaman aşımına uğradı. Model çok karmaşık veya sistem aşırı yük altında."
        },
        ErrorCode.STORAGE_QUOTA_EXCEEDED: {
            "en": "Storage quota exceeded. Please free up space or upgrade your plan.",
            "tr": "Depolama kotası aşıldı. Lütfen alan boşaltın veya planınızı yükseltin."
        },
        ErrorCode.VALIDATION_RANGE_VIOLATION: {
            "en": "Value is outside the acceptable range.",
            "tr": "Değer kabul edilebilir aralığın dışında."
        },
        ErrorCode.VALIDATION_CONFLICT: {
            "en": "Conflicting parameters detected.",
            "tr": "Çakışan parametreler tespit edildi."
        },
    }
    
    @classmethod
    def get_message(cls, error_code: ErrorCode) -> Tuple[str, str]:
        """Get bilingual error message for error code."""
        messages = cls.MESSAGES.get(error_code, {})
        return (
            messages.get("en", f"Error: {error_code.value}"),
            messages.get("tr", f"Hata: {error_code.value}")
        )


class SuggestionProvider:
    """Provider for actionable error suggestions."""
    
    SUGGESTIONS = {
        ErrorCode.FC_GEOM_INVALID_SHAPE: [
            ErrorSuggestion(
                en="Heal geometry and remove self-intersections; ensure solids are closed/manifold.",
                tr="Geometriyi iyileştirin ve kendi kendini kesişmeleri kaldırın; katıların kapalı/manifold olduğundan emin olun."
            ),
            ErrorSuggestion(
                en="Use 'Refine shape' after boolean operations.",
                tr="Boolean işlemlerden sonra 'Refine shape' kullanın."
            ),
        ],
        ErrorCode.FC_FILLET_CHAMFER_FAILED: [
            ErrorSuggestion(
                en="Reduce fillet radius below the smallest adjacent edge length.",
                tr="Kordon yarıçapını en küçük komşu kenar uzunluğunun altına indirin."
            ),
            ErrorSuggestion(
                en="Increase wall thickness to accommodate larger fillets.",
                tr="Daha büyük kordonları barındırmak için duvar kalınlığını artırın."
            ),
        ],
        ErrorCode.FC_SKETCH_OVERCONSTRAINED: [
            ErrorSuggestion(
                en="Remove redundant constraints and apply dimensional constraints incrementally.",
                tr="Gereksiz kısıtları kaldırın ve boyutsal kısıtları kademeli uygulayın."
            ),
            ErrorSuggestion(
                en="Check for conflicting dimensional and geometric constraints.",
                tr="Çakışan boyutsal ve geometrik kısıtları kontrol edin."
            ),
        ],
        ErrorCode.FC_IMPORT_STEP_FAILED: [
            ErrorSuggestion(
                en="Export STEP as AP214/AP242 format for better compatibility.",
                tr="Daha iyi uyumluluk için STEP'i AP214/AP242 formatında dışa aktarın."
            ),
            ErrorSuggestion(
                en="Ensure units are set to millimeters and run a CAD repair tool before upload.",
                tr="Birimlerin milimetre olarak ayarlandığından emin olun ve yüklemeden önce CAD onarım aracı çalıştırın."
            ),
        ],
        ErrorCode.FC_MESH_FAILED: [
            ErrorSuggestion(
                en="Enable mesh refinement and reduce feature complexity.",
                tr="Ağ iyileştirmeyi etkinleştirin ve özellik karmaşıklığını azaltın."
            ),
            ErrorSuggestion(
                en="Fix non-manifold edges and ensure watertight geometry.",
                tr="Manifold olmayan kenarları düzeltin ve su geçirmez geometri sağlayın."
            ),
        ],
        ErrorCode.FC_A4_UNSOLVED: [
            ErrorSuggestion(
                en="Ensure each part has an LCS (Local Coordinate System).",
                tr="Her parçanın bir LCS'si (Yerel Koordinat Sistemi) olduğundan emin olun."
            ),
            ErrorSuggestion(
                en="Solve constraints stepwise and avoid circular dependencies.",
                tr="Kısıtları adım adım çözün ve döngüsel bağımlılıklardan kaçının."
            ),
        ],
        ErrorCode.TIMEOUT_WORKER: [
            ErrorSuggestion(
                en="Simplify model by reducing feature count or fillet complexity.",
                tr="Özellik sayısını veya kordon karmaşıklığını azaltarak modeli basitleştirin."
            ),
            ErrorSuggestion(
                en="Split complex assemblies into smaller subassemblies.",
                tr="Karmaşık montajları daha küçük alt montajlara bölün."
            ),
        ],
        ErrorCode.VALIDATION_RANGE_VIOLATION: [
            ErrorSuggestion(
                en="Check minimum and maximum values for this parameter.",
                tr="Bu parametre için minimum ve maksimum değerleri kontrol edin."
            ),
            ErrorSuggestion(
                en="Ensure values meet manufacturing constraints (e.g., minimum wall thickness >= 1.5mm).",
                tr="Değerlerin üretim kısıtlarını karşıladığından emin olun (örn. minimum duvar kalınlığı >= 1.5mm)."
            ),
        ],
    }
    
    @classmethod
    def get_suggestions(cls, error_code: ErrorCode) -> List[ErrorSuggestion]:
        """Get suggestions for error code."""
        return cls.SUGGESTIONS.get(error_code, [])


class RemediationLinkProvider:
    """Provider for remediation documentation links."""
    
    LINKS = {
        ErrorCode.FC_GEOM_INVALID_SHAPE: [
            RemediationLink(
                title="FreeCAD Geometry Cleanup",
                url="https://wiki.freecad.org/Part_RefineShape"
            ),
            RemediationLink(
                title="BRep Validity and Healing",
                url="https://wiki.freecad.org/Part_Workbench"
            ),
        ],
        ErrorCode.FC_FILLET_CHAMFER_FAILED: [
            RemediationLink(
                title="Fillet Best Practices",
                url="https://wiki.freecad.org/PartDesign_Fillet"
            ),
        ],
        ErrorCode.FC_SKETCH_OVERCONSTRAINED: [
            RemediationLink(
                title="Sketcher Constraints Guide",
                url="https://wiki.freecad.org/Sketcher_Workbench"
            ),
        ],
        ErrorCode.FC_IMPORT_STEP_FAILED: [
            RemediationLink(
                title="STEP Import Tips",
                url="https://wiki.freecad.org/Import_Export"
            ),
        ],
        ErrorCode.FC_MESH_FAILED: [
            RemediationLink(
                title="Mesh Best Practices",
                url="https://wiki.freecad.org/Mesh_Workbench"
            ),
        ],
        ErrorCode.FC_A4_UNSOLVED: [
            RemediationLink(
                title="Assembly4 Documentation",
                url="https://wiki.freecad.org/Assembly4_Workbench"
            ),
        ],
        ErrorCode.TIMEOUT_WORKER: [
            RemediationLink(
                title="Performance Optimization Tips",
                url="https://wiki.freecad.org/Performance_tips"
            ),
        ],
    }
    
    @classmethod
    def get_links(cls, error_code: ErrorCode) -> List[RemediationLink]:
        """Get remediation links for error code."""
        return cls.LINKS.get(error_code, [])


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
            if "missing" in message.lower():
                error_code = ErrorCode.VALIDATION_MISSING_FIELD
            elif "range" in message.lower():
                error_code = ErrorCode.VALIDATION_RANGE_VIOLATION
            elif "conflict" in message.lower():
                error_code = ErrorCode.VALIDATION_CONFLICT
            else:
                error_code = ErrorCode.VALIDATION_CONSTRAINT_VIOLATION
        
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
            if "quota" in message.lower():
                error_code = ErrorCode.STORAGE_QUOTA_EXCEEDED
            elif "write" in operation.lower():
                error_code = ErrorCode.STORAGE_WRITE_FAILED
            elif "read" in operation.lower():
                error_code = ErrorCode.STORAGE_READ_FAILED
            else:
                error_code = ErrorCode.STORAGE_CORRUPT_FILE
        
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
            if "ambiguous" in message.lower():
                error_code = ErrorCode.AI_AMBIGUOUS
            elif "hint" in message.lower() or "additional" in message.lower():
                error_code = ErrorCode.AI_HINT_REQUIRED
            elif "complex" in message.lower():
                error_code = ErrorCode.AI_PROMPT_TOO_COMPLEX
            else:
                error_code = ErrorCode.AI_UNSUPPORTED_OPERATION
        
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