"""
Ultra Enterprise RBAC Schemas for Task 3.4

Pydantic schemas for RBAC-related data validation and API responses with:
- Role and permission validation
- Security event schemas
- Error response schemas with Turkish localization
- Performance-optimized validation
- KVKV compliance considerations
"""

from typing import Optional, List, Dict, Any, Set
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, validator, root_validator
from pydantic.config import ConfigDict

from ..models.enums import UserRole


class RBACErrorCode(str, Enum):
    """RBAC error codes for API responses."""
    
    AUTH_REQUIRED = "ERR-AUTH-REQUIRED"
    RBAC_FORBIDDEN = "ERR-RBAC-FORBIDDEN"
    ADMIN_REQUIRED = "ERR-ADMIN-REQUIRED"
    INSUFFICIENT_SCOPES = "ERR-INSUFFICIENT-SCOPES"
    ROLE_REQUIRED = "ERR-ROLE-REQUIRED"
    ACCOUNT_INACTIVE = "ERR-ACCOUNT-INACTIVE"


class RBACErrorResponse(BaseModel):
    """Standard RBAC error response schema."""
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error_code": "ERR-RBAC-FORBIDDEN",
                "message": "Yetersiz yetki",
                "details": {
                    "required_role": "admin",
                    "user_role": "engineer"
                },
                "timestamp": "2024-01-15T10:30:00Z"
            }
        }
    )
    
    error_code: RBACErrorCode = Field(
        ...,
        description="Specific RBAC error code"
    )
    message: str = Field(
        ...,
        description="Turkish localized error message",
        min_length=1,
        max_length=500
    )
    details: Optional[Dict[str, Any]] = Field(
        None,
        description="Additional error details"
    )
    timestamp: datetime = Field(
        ...,
        description="Error occurrence timestamp (UTC)"
    )


class PermissionScope(BaseModel):
    """Permission scope definition."""
    
    scope: str = Field(
        ...,
        description="Permission scope identifier",
        regex=r"^[a-z]+:[a-z]+$",
        example="models:create"
    )
    description: str = Field(
        ...,
        description="Human-readable scope description",
        min_length=1,
        max_length=200
    )
    resource: str = Field(
        ...,
        description="Resource this scope applies to",
        min_length=1,
        max_length=50
    )
    action: str = Field(
        ...,
        description="Action this scope allows",
        min_length=1,
        max_length=50
    )
    
    @validator('scope')
    def validate_scope_format(cls, v):
        """Validate scope follows resource:action format."""
        if ':' not in v:
            raise ValueError("Scope must follow 'resource:action' format")
        
        resource, action = v.split(':', 1)
        if not resource or not action:
            raise ValueError("Both resource and action must be non-empty")
        
        return v


class RolePermissions(BaseModel):
    """Role permission definition."""
    
    role: UserRole = Field(
        ...,
        description="User role"
    )
    scopes: Set[str] = Field(
        ...,
        description="Set of permission scopes for this role"
    )
    hierarchy_level: int = Field(
        ...,
        description="Role hierarchy level (higher = more permissions)",
        ge=1,
        le=10
    )
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "role": "engineer",
                "scopes": ["models:create", "models:read", "models:write"],
                "hierarchy_level": 3
            }
        }
    )


class UserPermissionSummary(BaseModel):
    """User permission summary for API responses."""
    
    user_id: int = Field(
        ...,
        description="User identifier",
        gt=0
    )
    role: UserRole = Field(
        ...,
        description="User's current role"
    )
    scopes: List[str] = Field(
        ...,
        description="List of permission scopes user has"
    )
    is_admin: bool = Field(
        ...,
        description="Whether user has admin privileges"
    )
    is_active: bool = Field(
        ...,
        description="Whether user account is active"
    )
    last_permission_check: Optional[datetime] = Field(
        None,
        description="Last time permissions were checked"
    )
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": 123,
                "role": "engineer",
                "scopes": ["models:create", "models:read", "models:write"],
                "is_admin": False,
                "is_active": True,
                "last_permission_check": "2024-01-15T10:30:00Z"
            }
        }
    )


class SecurityEventRequest(BaseModel):
    """Request schema for creating security events."""
    
    event_type: str = Field(
        ...,
        description="Type of security event",
        min_length=1,
        max_length=100
    )
    user_id: Optional[int] = Field(
        None,
        description="Associated user ID",
        gt=0
    )
    ip_address: Optional[str] = Field(
        None,
        description="Source IP address",
        max_length=45
    )
    user_agent: Optional[str] = Field(
        None,
        description="User agent string",
        max_length=1000
    )
    additional_data: Optional[Dict[str, Any]] = Field(
        None,
        description="Additional event data"
    )


class SecurityEventResponse(BaseModel):
    """Response schema for security events."""
    
    id: int = Field(
        ...,
        description="Security event ID",
        gt=0
    )
    event_type: str = Field(
        ...,
        description="Type of security event"
    )
    user_id: Optional[int] = Field(
        None,
        description="Associated user ID"
    )
    ip_address: Optional[str] = Field(
        None,
        description="Source IP address"
    )
    created_at: datetime = Field(
        ...,
        description="Event timestamp (UTC)"
    )
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 12345,
                "event_type": "ACCESS_DENIED",
                "user_id": 123,
                "ip_address": "192.168.1.100",
                "created_at": "2024-01-15T10:30:00Z"
            }
        }
    )


class PermissionCheckRequest(BaseModel):
    """Request schema for permission checks."""
    
    user_id: int = Field(
        ...,
        description="User ID to check permissions for",
        gt=0
    )
    resource: str = Field(
        ...,
        description="Resource to check access for",
        min_length=1,
        max_length=100
    )
    action: str = Field(
        ...,
        description="Action to check permission for",
        min_length=1,
        max_length=50
    )
    context: Optional[Dict[str, Any]] = Field(
        None,
        description="Additional context for permission check"
    )


class PermissionCheckResponse(BaseModel):
    """Response schema for permission checks."""
    
    user_id: int = Field(
        ...,
        description="User ID that was checked"
    )
    resource: str = Field(
        ...,
        description="Resource that was checked"
    )
    action: str = Field(
        ...,
        description="Action that was checked"
    )
    allowed: bool = Field(
        ...,
        description="Whether permission is granted"
    )
    reason: Optional[str] = Field(
        None,
        description="Reason for permission decision"
    )
    user_role: UserRole = Field(
        ...,
        description="User's current role"
    )
    required_scope: Optional[str] = Field(
        None,
        description="Required scope for this permission"
    )
    check_timestamp: datetime = Field(
        ...,
        description="When permission check was performed"
    )
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": 123,
                "resource": "models",
                "action": "create",
                "allowed": True,
                "reason": "User has models:create scope",
                "user_role": "engineer",
                "required_scope": "models:create",
                "check_timestamp": "2024-01-15T10:30:00Z"
            }
        }
    )


class RoleUpdateRequest(BaseModel):
    """Request schema for updating user roles."""
    
    user_id: int = Field(
        ...,
        description="User ID to update role for",
        gt=0
    )
    new_role: UserRole = Field(
        ...,
        description="New role to assign"
    )
    reason: str = Field(
        ...,
        description="Reason for role change",
        min_length=10,
        max_length=500
    )
    effective_date: Optional[datetime] = Field(
        None,
        description="When role change should take effect (default: immediately)"
    )


class RoleUpdateResponse(BaseModel):
    """Response schema for role updates."""
    
    user_id: int = Field(
        ...,
        description="User ID that was updated"
    )
    old_role: UserRole = Field(
        ...,
        description="Previous user role"
    )
    new_role: UserRole = Field(
        ...,
        description="New user role"
    )
    updated_by: int = Field(
        ...,
        description="Admin user ID who made the change"
    )
    updated_at: datetime = Field(
        ...,
        description="When role was updated"
    )
    reason: str = Field(
        ...,
        description="Reason for role change"
    )


class SystemPermissionsResponse(BaseModel):
    """Response schema for system-wide permission information."""
    
    available_roles: List[RolePermissions] = Field(
        ...,
        description="All available roles and their permissions"
    )
    available_scopes: List[PermissionScope] = Field(
        ...,
        description="All available permission scopes"
    )
    role_hierarchy: Dict[str, int] = Field(
        ...,
        description="Role hierarchy levels"
    )
    total_users_by_role: Dict[str, int] = Field(
        ...,
        description="Count of users by role"
    )
    last_updated: datetime = Field(
        ...,
        description="Last time permission system was updated"
    )


# Validation helpers

class ScopeValidator:
    """Utility class for validating permission scopes."""
    
    VALID_RESOURCES = {
        'admin', 'designs', 'models', 'jobs', 'cam', 
        'simulations', 'files', 'reports', 'profile'
    }
    
    VALID_ACTIONS = {
        'read', 'write', 'create', 'delete', 'upload', 
        'users', 'system', 'billing'
    }
    
    @classmethod
    def is_valid_scope(cls, scope: str) -> bool:
        """Check if scope format and content is valid."""
        if ':' not in scope:
            return False
        
        resource, action = scope.split(':', 1)
        return (resource.lower() in cls.VALID_RESOURCES and 
                action.lower() in cls.VALID_ACTIONS)
    
    @classmethod
    def validate_scope_list(cls, scopes: List[str]) -> List[str]:
        """Validate and filter list of scopes."""
        valid_scopes = []
        for scope in scopes:
            if cls.is_valid_scope(scope):
                valid_scopes.append(scope.lower())
        return valid_scopes


# Turkish error message templates
RBAC_ERROR_MESSAGES = {
    RBACErrorCode.AUTH_REQUIRED: "Kimlik doğrulama gerekli",
    RBACErrorCode.RBAC_FORBIDDEN: "Yetersiz yetki",
    RBACErrorCode.ADMIN_REQUIRED: "Admin yetkisi gerekli",
    RBACErrorCode.INSUFFICIENT_SCOPES: "Yetersiz izin kapsamı",
    RBACErrorCode.ROLE_REQUIRED: "Gerekli rol yetkisi yok",
    RBACErrorCode.ACCOUNT_INACTIVE: "Hesap aktif değil"
}