"""
Comprehensive unit tests for RBAC middleware (Task 3.4)

Tests ultra enterprise RBAC enforcement with:
- Role-based access control validation
- Scope-based permission checking
- Security event logging verification
- Performance requirements (<10ms authorization)
- Error handling with Turkish localization
- Zero false positives/negatives testing
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone, timedelta
from fastapi import Request, HTTPException, status

from app.middleware.rbac_middleware import (
    RBACError,
    RBACErrorCode,
    RolePermissions,
    RBACService,
    rbac_service,
    create_security_event_in_db,
    extract_request_metadata
)
from app.models.user import User
from app.models.enums import UserRole
from app.models.security_event import SecurityEvent


class TestRolePermissions:
    """Test role permission definitions and hierarchy."""
    
    def test_role_hierarchy(self):
        """Test role hierarchy levels are correct."""
        permissions = RolePermissions()
        
        assert permissions.ROLE_HIERARCHY[UserRole.VIEWER] == 1
        assert permissions.ROLE_HIERARCHY[UserRole.OPERATOR] == 2
        assert permissions.ROLE_HIERARCHY[UserRole.ENGINEER] == 3
        assert permissions.ROLE_HIERARCHY[UserRole.ADMIN] == 4
    
    def test_admin_has_all_scopes(self):
        """Test admin role has comprehensive permissions."""
        permissions = RolePermissions()
        admin_scopes = permissions.get_scopes_for_role(UserRole.ADMIN)
        
        # Admin should have all critical scopes
        expected_scopes = {
            'admin:users', 'admin:system', 'models:create', 'models:delete',
            'designs:write', 'jobs:create', 'files:upload'
        }
        assert expected_scopes.issubset(admin_scopes)
    
    def test_viewer_limited_scopes(self):
        """Test viewer role has only read permissions."""
        permissions = RolePermissions()
        viewer_scopes = permissions.get_scopes_for_role(UserRole.VIEWER)
        
        # Viewer should only have read scopes
        for scope in viewer_scopes:
            assert 'read' in scope or scope == 'profile:read'
        
        # Viewer should not have write/delete/admin scopes
        assert 'models:delete' not in viewer_scopes
        assert 'admin:users' not in viewer_scopes
        assert 'files:upload' not in viewer_scopes
    
    def test_engineer_permissions(self):
        """Test engineer role has appropriate permissions."""
        permissions = RolePermissions()
        engineer_scopes = permissions.get_scopes_for_role(UserRole.ENGINEER)
        
        # Engineer should have model and design permissions
        assert 'models:create' in engineer_scopes
        assert 'models:write' in engineer_scopes
        assert 'designs:write' in engineer_scopes
        assert 'cam:create' in engineer_scopes
        
        # But not admin permissions
        assert 'admin:users' not in engineer_scopes
        assert 'admin:system' not in engineer_scopes
    
    def test_role_hierarchy_comparison(self):
        """Test role hierarchy comparison logic."""
        permissions = RolePermissions()
        
        # Admin >= Engineer
        assert permissions.is_role_higher_or_equal(UserRole.ADMIN, UserRole.ENGINEER)
        
        # Engineer >= Operator
        assert permissions.is_role_higher_or_equal(UserRole.ENGINEER, UserRole.OPERATOR)
        
        # Operator >= Viewer
        assert permissions.is_role_higher_or_equal(UserRole.OPERATOR, UserRole.VIEWER)
        
        # Viewer < Engineer
        assert not permissions.is_role_higher_or_equal(UserRole.VIEWER, UserRole.ENGINEER)
        
        # Same role equals itself
        assert permissions.is_role_higher_or_equal(UserRole.ENGINEER, UserRole.ENGINEER)
    
    def test_scope_checking_methods(self):
        """Test scope checking utility methods."""
        permissions = RolePermissions()
        
        # Test has_scope
        assert permissions.role_has_scope(UserRole.ADMIN, 'models:create')
        assert permissions.role_has_scope(UserRole.ENGINEER, 'models:create')
        assert not permissions.role_has_scope(UserRole.VIEWER, 'models:create')
        
        # Test has_any_scope
        assert permissions.role_has_any_scope(UserRole.ENGINEER, ['models:create', 'admin:users'])
        assert not permissions.role_has_any_scope(UserRole.VIEWER, ['models:create', 'admin:users'])
        
        # Test has_all_scopes
        assert permissions.role_has_all_scopes(UserRole.ADMIN, ['models:read', 'models:write'])
        assert not permissions.role_has_all_scopes(UserRole.VIEWER, ['models:read', 'models:write'])


class TestRBACService:
    """Test RBAC service business logic."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.rbac_service = RBACService()
        self.mock_request = Mock(spec=Request)
        self.mock_request.client.host = "192.168.1.100"
        self.mock_request.method = "GET"
        self.mock_request.url.path = "/api/v1/test"
    
    def create_mock_user(self, role: UserRole, is_active: bool = True, is_locked: bool = False):
        """Create mock user for testing."""
        user = Mock(spec=User)
        user.id = 123
        user.role = role
        user.is_active = is_active
        user.account_locked_until = datetime.now(timezone.utc) + timedelta(minutes=15) if is_locked else None
        user.failed_login_attempts = 10 if is_locked else 0
        user.account_status = 'active' if is_active else 'suspended'
        
        # Mock the is_account_locked method
        user.is_account_locked.return_value = is_locked
        
        return user
    
    def test_check_user_active_success(self):
        """Test successful user active check."""
        user = self.create_mock_user(UserRole.ENGINEER, is_active=True, is_locked=False)
        
        # Should not raise exception
        self.rbac_service.check_user_active(user, self.mock_request)
    
    def test_check_user_active_inactive_user(self):
        """Test user active check with inactive user."""
        user = self.create_mock_user(UserRole.ENGINEER, is_active=False, is_locked=False)
        
        with pytest.raises(RBACError) as exc_info:
            self.rbac_service.check_user_active(user, self.mock_request)
        
        assert exc_info.value.code == RBACErrorCode.ACCOUNT_INACTIVE
        assert "aktif değil" in exc_info.value.detail['message']
    
    def test_check_user_active_locked_user(self):
        """Test user active check with locked user."""
        user = self.create_mock_user(UserRole.ENGINEER, is_active=True, is_locked=True)
        
        with pytest.raises(RBACError) as exc_info:
            self.rbac_service.check_user_active(user, self.mock_request)
        
        assert exc_info.value.code == RBACErrorCode.ACCOUNT_INACTIVE
        assert "kilitli" in exc_info.value.detail['message']
    
    def test_check_role_permission_success(self):
        """Test successful role permission check."""
        # Engineer accessing engineer-level resource
        self.rbac_service.check_role_permission(
            user_role=UserRole.ENGINEER,
            required_role=UserRole.OPERATOR,
            user_id=123,
            request=self.mock_request
        )
        
        # Admin accessing any resource
        self.rbac_service.check_role_permission(
            user_role=UserRole.ADMIN,
            required_role=UserRole.ENGINEER,
            user_id=123,
            request=self.mock_request
        )
    
    def test_check_role_permission_insufficient(self):
        """Test role permission check with insufficient role."""
        with pytest.raises(RBACError) as exc_info:
            self.rbac_service.check_role_permission(
                user_role=UserRole.VIEWER,
                required_role=UserRole.ENGINEER,
                user_id=123,
                request=self.mock_request
            )
        
        assert exc_info.value.code == RBACErrorCode.ROLE_REQUIRED
        assert "engineer" in exc_info.value.detail['message']
        assert exc_info.value.detail['details']['user_role'] == 'viewer'
        assert exc_info.value.detail['details']['required_role'] == 'engineer'
    
    def test_check_scope_permission_success(self):
        """Test successful scope permission check."""
        # Engineer with models:create scope
        self.rbac_service.check_scope_permission(
            user_role=UserRole.ENGINEER,
            required_scopes=['models:create'],
            user_id=123,
            request=self.mock_request
        )
        
        # Admin with any scope
        self.rbac_service.check_scope_permission(
            user_role=UserRole.ADMIN,
            required_scopes=['admin:system'],
            user_id=123,
            request=self.mock_request
        )
    
    def test_check_scope_permission_insufficient(self):
        """Test scope permission check with insufficient scopes."""
        with pytest.raises(RBACError) as exc_info:
            self.rbac_service.check_scope_permission(
                user_role=UserRole.VIEWER,
                required_scopes=['models:create'],
                user_id=123,
                request=self.mock_request
            )
        
        assert exc_info.value.code == RBACErrorCode.INSUFFICIENT_SCOPES
        assert "models:create" in exc_info.value.detail['message']
        assert exc_info.value.detail['details']['required_scopes'] == ['models:create']
    
    def test_check_scope_permission_require_any(self):
        """Test scope permission check with require_any=False."""
        # Viewer has designs:read but not models:create
        self.rbac_service.check_scope_permission(
            user_role=UserRole.VIEWER,
            required_scopes=['models:create', 'designs:read'],
            user_id=123,
            request=self.mock_request,
            require_all=False  # Only needs one of the scopes
        )
    
    def test_check_admin_permission_success(self):
        """Test successful admin permission check."""
        self.rbac_service.check_admin_permission(
            user_role=UserRole.ADMIN,
            user_id=123,
            request=self.mock_request
        )
    
    def test_check_admin_permission_non_admin(self):
        """Test admin permission check with non-admin user."""
        with pytest.raises(RBACError) as exc_info:
            self.rbac_service.check_admin_permission(
                user_role=UserRole.ENGINEER,
                user_id=123,
                request=self.mock_request
            )
        
        assert exc_info.value.code == RBACErrorCode.ADMIN_REQUIRED
        assert "admin yetkisi" in exc_info.value.detail['message']


class TestRBACError:
    """Test RBAC error handling and security logging."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.mock_request = Mock(spec=Request)
        self.mock_request.client.host = "192.168.1.100"
        self.mock_request.method = "POST"
        self.mock_request.url.path = "/api/v1/models"
        self.mock_request.headers = {"user-agent": "TestClient/1.0"}
    
    @patch('app.middleware.rbac_middleware.logger')
    def test_rbac_error_logging(self, mock_logger):
        """Test RBAC error triggers security logging."""
        error = RBACError(
            code=RBACErrorCode.INSUFFICIENT_SCOPES,
            message="Yetersiz izin kapsamı",
            details={"required_scopes": ["models:create"]},
            user_id=123,
            request=self.mock_request
        )
        
        # Check HTTP exception properties
        assert error.status_code == status.HTTP_403_FORBIDDEN
        assert error.detail['error_code'] == RBACErrorCode.INSUFFICIENT_SCOPES
        assert error.detail['message'] == "Yetersiz izin kapsamı"
        assert error.detail['details']['required_scopes'] == ["models:create"]
        
        # Check logging was called
        mock_logger.warning.assert_called_once()
        log_call = mock_logger.warning.call_args
        
        assert 'RBAC authorization denied' in log_call[0][0]
        extra = log_call[1]['extra']
        assert extra['event_type'] == 'insufficient_scopes'
        assert extra['user_id'] == 123
        assert extra['endpoint'] == 'POST /api/v1/models'
        assert extra['client_ip'] == "192.168.1.100"
    
    def test_error_code_status_mapping(self):
        """Test error codes map to correct HTTP status codes."""
        auth_error = RBACError(RBACErrorCode.AUTH_REQUIRED, "Auth required")
        assert auth_error.status_code == status.HTTP_401_UNAUTHORIZED
        
        rbac_error = RBACError(RBACErrorCode.RBAC_FORBIDDEN, "Forbidden")
        assert rbac_error.status_code == status.HTTP_403_FORBIDDEN
        
        admin_error = RBACError(RBACErrorCode.ADMIN_REQUIRED, "Admin required")
        assert admin_error.status_code == status.HTTP_403_FORBIDDEN


class TestSecurityEventCreation:
    """Test security event creation and database operations."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.mock_db = Mock()
    
    @patch('app.middleware.rbac_middleware.logger')
    def test_create_security_event_success(self, mock_logger):
        """Test successful security event creation."""
        create_security_event_in_db(
            db=self.mock_db,
            event_type="insufficient_scopes",
            user_id=123,
            ip="192.168.1.100",
            user_agent="TestClient/1.0"
        )
        
        # Check database operations
        self.mock_db.add.assert_called_once()
        self.mock_db.commit.assert_called_once()
        
        # Check logging
        mock_logger.info.assert_called_once()
        log_call = mock_logger.info.call_args
        extra = log_call[1]['extra']
        assert extra['event_type'] == "insufficient_scopes"
        assert extra['user_id'] == 123
        assert extra['ip'] == "192.168.1.100"
    
    @patch('app.middleware.rbac_middleware.logger')
    def test_create_security_event_db_error(self, mock_logger):
        """Test security event creation with database error."""
        self.mock_db.add.side_effect = Exception("DB Error")
        
        create_security_event_in_db(
            db=self.mock_db,
            event_type="test_event",
            user_id=123
        )
        
        # Should handle error gracefully
        self.mock_db.rollback.assert_called_once()
        mock_logger.error.assert_called_once()
    
    def test_create_security_event_long_user_agent(self):
        """Test security event creation with oversized user agent."""
        long_user_agent = "A" * 2000  # Longer than 1000 char limit
        
        create_security_event_in_db(
            db=self.mock_db,
            event_type="test_event",
            user_agent=long_user_agent
        )
        
        # Check that SecurityEvent was created with truncated user agent
        self.mock_db.add.assert_called_once()
        security_event = self.mock_db.add.call_args[0][0]
        assert len(security_event.ua) == 1000


class TestRequestMetadataExtraction:
    """Test request metadata extraction for security logging."""
    
    def test_extract_request_metadata_complete(self):
        """Test metadata extraction with all fields present."""
        mock_request = Mock(spec=Request)
        mock_request.method = "POST"
        mock_request.url.path = "/api/v1/models"
        mock_request.client.host = "192.168.1.100"
        mock_request.headers = {
            "user-agent": "TestClient/1.0",
            "referer": "https://example.com/page"
        }
        
        metadata = extract_request_metadata(mock_request)
        
        assert metadata['method'] == "POST"
        assert metadata['path'] == "/api/v1/models"
        assert metadata['client_ip'] == "192.168.1.100"
        assert metadata['user_agent'] == "TestClient/1.0"
        assert metadata['referer'] == "https://example.com/page"
        assert metadata['endpoint'] == "POST /api/v1/models"
    
    def test_extract_request_metadata_minimal(self):
        """Test metadata extraction with minimal fields."""
        mock_request = Mock(spec=Request)
        mock_request.method = "GET"
        mock_request.url.path = "/api/v1/test"
        mock_request.client = None  # No client info
        mock_request.headers = {}  # No headers
        
        metadata = extract_request_metadata(mock_request)
        
        assert metadata['method'] == "GET"
        assert metadata['path'] == "/api/v1/test"
        assert metadata['client_ip'] is None
        assert metadata['user_agent'] == ""
        assert metadata['referer'] is None
        assert metadata['endpoint'] == "GET /api/v1/test"
    
    def test_extract_request_metadata_long_headers(self):
        """Test metadata extraction with long header values."""
        mock_request = Mock(spec=Request)
        mock_request.method = "POST"
        mock_request.url.path = "/test"
        mock_request.client.host = "192.168.1.100"
        
        long_user_agent = "A" * 500  # Longer than 200 char limit
        long_referer = "B" * 500
        
        mock_request.headers = {
            "user-agent": long_user_agent,
            "referer": long_referer
        }
        
        metadata = extract_request_metadata(mock_request)
        
        # Should be truncated to 200 characters
        assert len(metadata['user_agent']) == 200
        assert len(metadata['referer']) == 200
        assert metadata['user_agent'] == "A" * 200
        assert metadata['referer'] == "B" * 200


class TestPerformanceRequirements:
    """Test RBAC performance requirements (<10ms per check)."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.rbac_service = RBACService()
        self.mock_request = Mock(spec=Request)
        self.mock_request.client.host = "192.168.1.100"
        self.mock_request.method = "GET"
        self.mock_request.url.path = "/api/v1/test"
    
    def test_role_check_performance(self):
        """Test role permission check performance."""
        import time
        
        start_time = time.perf_counter()
        
        # Perform 100 role checks
        for _ in range(100):
            self.rbac_service.check_role_permission(
                user_role=UserRole.ENGINEER,
                required_role=UserRole.OPERATOR,
                user_id=123,
                request=self.mock_request
            )
        
        end_time = time.perf_counter()
        avg_time_ms = ((end_time - start_time) / 100) * 1000
        
        # Should be well under 10ms per check
        assert avg_time_ms < 10, f"Role check took {avg_time_ms}ms, exceeds 10ms requirement"
    
    def test_scope_check_performance(self):
        """Test scope permission check performance."""
        import time
        
        start_time = time.perf_counter()
        
        # Perform 100 scope checks
        for _ in range(100):
            self.rbac_service.check_scope_permission(
                user_role=UserRole.ENGINEER,
                required_scopes=['models:create'],
                user_id=123,
                request=self.mock_request
            )
        
        end_time = time.perf_counter()
        avg_time_ms = ((end_time - start_time) / 100) * 1000
        
        # Should be well under 10ms per check
        assert avg_time_ms < 10, f"Scope check took {avg_time_ms}ms, exceeds 10ms requirement"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.rbac_service = RBACService()
        self.mock_request = Mock(spec=Request)
    
    def test_empty_scopes_requirement(self):
        """Test permission check with empty scopes list."""
        # Empty scopes should always pass
        self.rbac_service.check_scope_permission(
            user_role=UserRole.VIEWER,
            required_scopes=[],
            user_id=123,
            request=self.mock_request
        )
    
    def test_nonexistent_scope(self):
        """Test permission check with non-existent scope."""
        with pytest.raises(RBACError):
            self.rbac_service.check_scope_permission(
                user_role=UserRole.ADMIN,
                required_scopes=['nonexistent:scope'],
                user_id=123,
                request=self.mock_request
            )
    
    def test_case_sensitivity(self):
        """Test that scope checking is case sensitive."""
        with pytest.raises(RBACError):
            self.rbac_service.check_scope_permission(
                user_role=UserRole.ENGINEER,
                required_scopes=['MODELS:CREATE'],  # Wrong case
                user_id=123,
                request=self.mock_request
            )
    
    def test_multiple_scope_combinations(self):
        """Test various combinations of multiple scope requirements."""
        # Engineer should have both read and write for models
        self.rbac_service.check_scope_permission(
            user_role=UserRole.ENGINEER,
            required_scopes=['models:read', 'models:write'],
            user_id=123,
            request=self.mock_request,
            require_all=True
        )
        
        # Engineer should have at least one of these
        self.rbac_service.check_scope_permission(
            user_role=UserRole.ENGINEER,
            required_scopes=['models:create', 'admin:users'],
            user_id=123,
            request=self.mock_request,
            require_all=False
        )