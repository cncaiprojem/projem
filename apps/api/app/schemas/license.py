"""
Task 4.2: License API Schemas
Ultra-enterprise banking grade schemas with Turkish KVKV compliance.
"""

from datetime import datetime
from typing import Optional, Dict, Any
from decimal import Decimal

from pydantic import BaseModel, Field, validator
import uuid
from uuid import UUID


# Request Schemas
class LicenseAssignRequest(BaseModel):
    """Request schema for POST /license/assign"""
    
    user_id: Optional[UUID] = Field(
        None, 
        description="Target user ID (admin only, auto-filled for self-assignment)"
    )
    type: str = Field(
        ..., 
        description="License duration type",
        regex="^(3m|6m|12m)$"
    )
    scope: Dict[str, Any] = Field(
        ...,
        description="License scope configuration (features, limits)"
    )
    starts_at: Optional[datetime] = Field(
        None,
        description="License start time (RFC3339, defaults to now())"
    )
    
    @validator('scope')
    def validate_scope(cls, v):
        """Validate scope contains required fields."""
        if not isinstance(v, dict):
            raise ValueError("Scope must be a dictionary")
        
        # Ensure scope has required structure
        if 'features' not in v:
            raise ValueError("Scope must contain 'features' key")
        if 'limits' not in v:
            raise ValueError("Scope must contain 'limits' key")
        
        # Validate features is a dict
        if not isinstance(v['features'], dict):
            raise ValueError("Scope 'features' must be a dictionary")
        
        # Validate limits is a dict
        if not isinstance(v['limits'], dict):
            raise ValueError("Scope 'limits' must be a dictionary")
        
        # Optional: validate specific feature/limit keys if needed
        # Example structure validation:
        # Expected features: {'cam_generation': bool, 'gcode_export': bool, etc.}
        # Expected limits: {'max_jobs': int, 'storage_gb': int, etc.}
        
        return v


class LicenseExtendRequest(BaseModel):
    """Request schema for POST /license/extend"""
    
    user_id: Optional[UUID] = Field(
        None,
        description="Target user ID (admin only, auto-filled for self-service)"
    )
    license_id: Optional[UUID] = Field(
        None,
        description="Specific license ID to extend (optional, uses active if not specified)"
    )
    type: str = Field(
        ...,
        description="Extension duration type",
        regex="^(3m|6m|12m)$"
    )


class LicenseCancelRequest(BaseModel):
    """Request schema for POST /license/cancel"""
    
    user_id: Optional[UUID] = Field(
        None,
        description="Target user ID (admin only, auto-filled for self-service)"
    )
    license_id: Optional[UUID] = Field(
        None,
        description="Specific license ID to cancel (optional, uses active if not specified)"
    )
    reason: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Cancellation reason"
    )


# Response Schemas
class LicenseResponse(BaseModel):
    """Standard license response schema"""
    
    id: UUID = Field(..., description="License unique identifier")
    type: str = Field(..., description="License type (3m, 6m, 12m)")
    scope: Dict[str, Any] = Field(..., description="License scope and features")
    status: str = Field(..., description="License status (active, expired, canceled)")
    starts_at: datetime = Field(..., description="License start timestamp")
    ends_at: datetime = Field(..., description="License end timestamp")
    
    class Config:
        orm_mode = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            Decimal: str
        }


class LicenseAssignResponse(BaseModel):
    """Response schema for POST /license/assign"""
    
    license: LicenseResponse = Field(..., description="Created license details")
    
    # Turkish localization
    message: str = Field(..., description="Success message")
    message_tr: str = Field(..., description="Success message in Turkish")


class LicenseExtendResponse(BaseModel):
    """Response schema for POST /license/extend"""
    
    license_id: UUID = Field(..., description="Extended license ID")
    previous_ends_at: datetime = Field(..., description="Previous expiry date")
    new_ends_at: datetime = Field(..., description="New expiry date") 
    added_months: int = Field(..., description="Months added to license")
    
    # Turkish localization
    message: str = Field(..., description="Success message")
    message_tr: str = Field(..., description="Success message in Turkish")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class LicenseCancelResponse(BaseModel):
    """Response schema for POST /license/cancel"""
    
    license_id: UUID = Field(..., description="Canceled license ID")
    status: str = Field(..., description="New status (always 'canceled')")
    canceled_at: datetime = Field(..., description="Cancellation timestamp")
    reason: str = Field(..., description="Cancellation reason")
    
    # Turkish localization
    message: str = Field(..., description="Success message")
    message_tr: str = Field(..., description="Success message in Turkish")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class LicenseMeResponse(BaseModel):
    """Response schema for GET /license/me"""
    
    status: str = Field(..., description="License status (active, expired, trial, none)")
    type: Optional[str] = Field(None, description="License type if active")
    ends_at: Optional[datetime] = Field(None, description="Expiry date if active")
    remaining_days: Optional[int] = Field(None, description="Days remaining (0 if expired)")
    scope: Optional[Dict[str, Any]] = Field(None, description="License scope if active")
    
    # Turkish localization
    status_tr: str = Field(..., description="Status in Turkish")
    warning_message_tr: Optional[str] = Field(None, description="Warning message in Turkish")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


# Error Response Schemas
class LicenseErrorResponse(BaseModel):
    """Standard error response for license operations"""
    
    code: str = Field(..., description="Error code")
    message: str = Field(..., description="Error message in English")
    message_tr: str = Field(..., description="Error message in Turkish")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")


# Common validators and utilities
class LicenseTypeValidator:
    """Utility class for license type validation"""
    
    VALID_TYPES = ['3m', '6m', '12m']
    TYPE_MONTHS = {'3m': 3, '6m': 6, '12m': 12}
    
    @classmethod
    def validate_type(cls, license_type: str) -> bool:
        """Validate license type."""
        return license_type in cls.VALID_TYPES
    
    @classmethod
    def get_months(cls, license_type: str) -> int:
        """Get months for license type."""
        if not cls.validate_type(license_type):
            raise ValueError(f"Invalid license type: {license_type}")
        return cls.TYPE_MONTHS[license_type]


class LicenseErrorCodes:
    """Standard error codes for license operations"""
    
    # Business logic errors
    ACTIVE_LICENSE_EXISTS = "ACTIVE_LICENSE_EXISTS"
    INVALID_TYPE = "INVALID_TYPE"
    FORBIDDEN = "FORBIDDEN"
    LIC_NOT_ACTIVE = "LIC_NOT_ACTIVE"
    NOT_FOUND = "NOT_FOUND"
    ALREADY_CANCELED = "ALREADY_CANCELED"
    
    # System errors
    VALIDATION_ERROR = "VALIDATION_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    
    # Turkish translations
    ERROR_MESSAGES = {
        ACTIVE_LICENSE_EXISTS: {
            "en": "User already has an active license",
            "tr": "Kullanıcının zaten aktif bir lisansı var"
        },
        INVALID_TYPE: {
            "en": "Invalid license type specified",
            "tr": "Geçersiz lisans türü belirtildi"
        },
        FORBIDDEN: {
            "en": "Insufficient permissions for this operation",
            "tr": "Bu işlem için yeterli yetki yok"
        },
        LIC_NOT_ACTIVE: {
            "en": "License is not active or has expired",
            "tr": "Lisans aktif değil veya süresi dolmuş"
        },
        NOT_FOUND: {
            "en": "License not found",
            "tr": "Lisans bulunamadı"
        },
        ALREADY_CANCELED: {
            "en": "License is already canceled",
            "tr": "Lisans zaten iptal edilmiş"
        },
        VALIDATION_ERROR: {
            "en": "Request validation failed",
            "tr": "İstek doğrulama başarısız"
        },
        DATABASE_ERROR: {
            "en": "Database operation failed",
            "tr": "Veritabanı işlemi başarısız"
        },
        INTERNAL_ERROR: {
            "en": "Internal server error",
            "tr": "Sunucu iç hatası"
        }
    }
    
    @classmethod
    def get_error_response(cls, code: str, details: Optional[Dict[str, Any]] = None) -> LicenseErrorResponse:
        """Create standardized error response."""
        messages = cls.ERROR_MESSAGES.get(code, {
            "en": "Unknown error",
            "tr": "Bilinmeyen hata"
        })
        
        return LicenseErrorResponse(
            code=code,
            message=messages["en"],
            message_tr=messages["tr"],
            details=details
        )