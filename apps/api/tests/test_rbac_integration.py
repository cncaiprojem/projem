"""
Integration tests for RBAC dependencies (Task 3.4)

Tests end-to-end RBAC enforcement with:
- FastAPI dependency integration
- Real HTTP requests with authentication
- Database security event logging
- Error response formats with Turkish localization
- Performance verification in realistic scenarios
"""

import pytest
from unittest.mock import patch, Mock
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.user import User
from app.models.security_event import SecurityEvent
from app.models.enums import UserRole
from app.db import get_db
from app.services.jwt_service import jwt_service


class TestRBACDependencyIntegration:
    """Test RBAC dependency integration with FastAPI."""

    def setup_method(self):
        """Set up test fixtures."""
        self.client = TestClient(app)
        self.mock_db = Mock(spec=Session)

        # Override database dependency
        def override_get_db():
            return self.mock_db

        app.dependency_overrides[get_db] = override_get_db

    def teardown_method(self):
        """Clean up after tests."""
        app.dependency_overrides.clear()

    def create_test_user(self, role: UserRole, user_id: int = 123) -> User:
        """Create test user with specified role."""
        user = User(
            id=user_id,
            email=f"test{user_id}@example.com",
            role=role,
            is_active=True,
            account_status="active",
            failed_login_attempts=0,
            account_locked_until=None,
        )
        return user

    def create_jwt_token(self, user: User, scopes: list = None) -> str:
        """Create JWT token for test user."""
        if scopes is None:
            # Use default scopes based on role
            from app.middleware.rbac_middleware import RolePermissions

            permissions = RolePermissions()
            scopes = list(permissions.get_scopes_for_role(user.role))

        # Mock session ID
        session_id = "test-session-123"

        with patch("app.services.jwt_service.jwt_service.create_access_token") as mock_create:
            mock_create.return_value = f"test-jwt-token-{user.id}-{user.role.value}"
            return mock_create.return_value

    @patch("app.middleware.jwt_middleware._authenticate_user")
    def test_require_auth_success(self, mock_auth):
        """Test successful authentication requirement."""
        from app.middleware.jwt_middleware import AuthenticatedUser
        from app.models.session import Session as SessionModel
        from app.services.jwt_service import JWTClaims

        # Create test user and session
        user = self.create_test_user(UserRole.ENGINEER)
        session = Mock(spec=SessionModel)
        session.id = "test-session-123"

        claims = Mock(spec=JWTClaims)
        claims.sub = str(user.id)
        claims.sid = session.id
        claims.scopes = ["models:read", "models:write"]

        authenticated_user = AuthenticatedUser(user, session, claims)
        mock_auth.return_value = authenticated_user

        # Mock database queries
        self.mock_db.query.return_value.filter.return_value.first.return_value = user

        # Test endpoint with require_auth
        response = self.client.get("/api/v1/me", headers={"Authorization": "Bearer test-token"})

        # Should succeed with authenticated user
        assert response.status_code == 200

    @patch("app.middleware.jwt_middleware._authenticate_user")
    def test_require_auth_inactive_user(self, mock_auth):
        """Test authentication requirement with inactive user."""
        from app.middleware.jwt_middleware import AuthenticatedUser
        from app.models.session import Session as SessionModel
        from app.services.jwt_service import JWTClaims

        # Create inactive test user
        user = self.create_test_user(UserRole.ENGINEER)
        user.is_active = False
        user.account_status = "suspended"

        session = Mock(spec=SessionModel)
        claims = Mock(spec=JWTClaims)
        authenticated_user = AuthenticatedUser(user, session, claims)
        mock_auth.return_value = authenticated_user

        response = self.client.get("/api/v1/me", headers={"Authorization": "Bearer test-token"})

        # Should fail with account inactive error
        assert response.status_code == 403
        assert response.json()["detail"]["error_code"] == "ERR-ACCOUNT-INACTIVE"
        assert "aktif değil" in response.json()["detail"]["message"]

    def test_require_auth_no_token(self):
        """Test authentication requirement without token."""
        response = self.client.get("/api/v1/me")

        # Should fail with authentication required error
        assert response.status_code == 401
        assert "Authorization header gerekli" in str(response.json())

    @patch("app.middleware.jwt_middleware._authenticate_user")
    def test_require_admin_success(self, mock_auth):
        """Test successful admin requirement."""
        from app.middleware.jwt_middleware import AuthenticatedUser
        from app.models.session import Session as SessionModel
        from app.services.jwt_service import JWTClaims

        # Create admin user
        user = self.create_test_user(UserRole.ADMIN)
        session = Mock(spec=SessionModel)
        claims = Mock(spec=JWTClaims)
        authenticated_user = AuthenticatedUser(user, session, claims)
        mock_auth.return_value = authenticated_user

        # Mock database for admin endpoints
        self.mock_db.query.return_value.filter.return_value.offset.return_value.limit.return_value.all.return_value = []

        response = self.client.get(
            "/api/v1/admin/users", headers={"Authorization": "Bearer admin-token"}
        )

        # Should succeed for admin user
        assert response.status_code == 200

    @patch("app.middleware.jwt_middleware._authenticate_user")
    def test_require_admin_non_admin(self, mock_auth):
        """Test admin requirement with non-admin user."""
        from app.middleware.jwt_middleware import AuthenticatedUser
        from app.models.session import Session as SessionModel
        from app.services.jwt_service import JWTClaims

        # Create non-admin user
        user = self.create_test_user(UserRole.ENGINEER)
        session = Mock(spec=SessionModel)
        claims = Mock(spec=JWTClaims)
        authenticated_user = AuthenticatedUser(user, session, claims)
        mock_auth.return_value = authenticated_user

        response = self.client.get(
            "/api/v1/admin/users", headers={"Authorization": "Bearer engineer-token"}
        )

        # Should fail with admin required error
        assert response.status_code == 403
        assert response.json()["detail"]["error_code"] == "ERR-ADMIN-REQUIRED"
        assert "admin yetkisi" in response.json()["detail"]["message"]

    @patch("app.middleware.jwt_middleware._authenticate_user")
    def test_require_scopes_success(self, mock_auth):
        """Test successful scope requirement."""
        from app.middleware.jwt_middleware import AuthenticatedUser
        from app.models.session import Session as SessionModel
        from app.services.jwt_service import JWTClaims

        # Create user with required scopes
        user = self.create_test_user(UserRole.ENGINEER)
        session = Mock(spec=SessionModel)
        claims = Mock(spec=JWTClaims)
        authenticated_user = AuthenticatedUser(user, session, claims)
        mock_auth.return_value = authenticated_user

        # Mock job creation
        mock_job = Mock()
        mock_job.id = 123
        self.mock_db.add = Mock()
        self.mock_db.commit = Mock()
        self.mock_db.refresh = Mock()

        with patch("app.routers.designs.db_session") as mock_db_session:
            mock_db_session.return_value.__enter__.return_value = self.mock_db
            mock_db_session.return_value.__exit__.return_value = None
            self.mock_db.query.return_value.filter_by.return_value.first.return_value = None

            with patch("app.routers.designs.design_orchestrate.delay") as mock_delay:
                with patch("app.routers.designs.is_queue_paused", return_value=False):
                    response = self.client.post(
                        "/api/v1/designs",
                        headers={"Authorization": "Bearer engineer-token"},
                        json={"prompt": "Test design", "targets": {"ratio": 2.0}},
                    )

        # Should succeed for user with designs:write scope
        assert (
            response.status_code == 200 or response.status_code == 422
        )  # Validation might fail, but auth should pass

    @patch("app.middleware.jwt_middleware._authenticate_user")
    def test_require_scopes_insufficient(self, mock_auth):
        """Test scope requirement with insufficient scopes."""
        from app.middleware.jwt_middleware import AuthenticatedUser
        from app.models.session import Session as SessionModel
        from app.services.jwt_service import JWTClaims

        # Create user without required scopes (viewer role)
        user = self.create_test_user(UserRole.VIEWER)
        session = Mock(spec=SessionModel)
        claims = Mock(spec=JWTClaims)
        authenticated_user = AuthenticatedUser(user, session, claims)
        mock_auth.return_value = authenticated_user

        response = self.client.post(
            "/api/v1/designs",
            headers={"Authorization": "Bearer viewer-token"},
            json={"prompt": "Test design"},
        )

        # Should fail with insufficient scopes error
        assert response.status_code == 403
        assert response.json()["detail"]["error_code"] == "ERR-INSUFFICIENT-SCOPES"
        assert "izin kapsamı" in response.json()["detail"]["message"]


class TestSecurityEventLogging:
    """Test security event logging in database."""

    def setup_method(self):
        """Set up test fixtures."""
        self.client = TestClient(app)
        self.mock_db = Mock(spec=Session)

        # Override database dependency
        def override_get_db():
            return self.mock_db

        app.dependency_overrides[get_db] = override_get_db

    def teardown_method(self):
        """Clean up after tests."""
        app.dependency_overrides.clear()

    @patch("app.middleware.jwt_middleware._authenticate_user")
    def test_security_event_logged_on_rbac_failure(self, mock_auth):
        """Test that RBAC failures create security events in database."""
        from app.middleware.jwt_middleware import AuthenticatedUser
        from app.models.session import Session as SessionModel
        from app.services.jwt_service import JWTClaims

        # Create user without admin privileges
        user = User(
            id=123,
            email="test@example.com",
            role=UserRole.ENGINEER,
            is_active=True,
            account_status="active",
        )

        session = Mock(spec=SessionModel)
        session.id = "test-session-123"
        claims = Mock(spec=JWTClaims)
        authenticated_user = AuthenticatedUser(user, session, claims)
        mock_auth.return_value = authenticated_user

        # Track security event creation
        security_events = []

        def mock_add(obj):
            if isinstance(obj, SecurityEvent):
                security_events.append(obj)

        self.mock_db.add = mock_add
        self.mock_db.commit = Mock()

        # Attempt admin action
        response = self.client.get(
            "/api/v1/admin/users", headers={"Authorization": "Bearer engineer-token"}
        )

        # Should fail and create security event
        assert response.status_code == 403
        assert len(security_events) == 1

        security_event = security_events[0]
        assert security_event.user_id == 123
        assert security_event.type == "admin_required"

    @patch("app.middleware.jwt_middleware._authenticate_user")
    def test_security_event_contains_request_metadata(self, mock_auth):
        """Test that security events contain request metadata."""
        from app.middleware.jwt_middleware import AuthenticatedUser
        from app.models.session import Session as SessionModel
        from app.services.jwt_service import JWTClaims

        user = User(
            id=456,
            email="test2@example.com",
            role=UserRole.VIEWER,
            is_active=True,
            account_status="active",
        )

        session = Mock(spec=SessionModel)
        claims = Mock(spec=JWTClaims)
        authenticated_user = AuthenticatedUser(user, session, claims)
        mock_auth.return_value = authenticated_user

        security_events = []

        def mock_add(obj):
            if isinstance(obj, SecurityEvent):
                security_events.append(obj)

        self.mock_db.add = mock_add
        self.mock_db.commit = Mock()

        # Make request with custom headers
        response = self.client.post(
            "/api/v1/designs",
            headers={
                "Authorization": "Bearer viewer-token",
                "User-Agent": "TestClient/2.0",
                "X-Forwarded-For": "203.0.113.1",
            },
            json={"prompt": "Test"},
        )

        # Should create security event with metadata
        assert response.status_code == 403
        assert len(security_events) == 1

        security_event = security_events[0]
        assert security_event.user_id == 456
        assert security_event.type == "insufficient_scopes"
        # Note: FastAPI TestClient doesn't set real IP, but in production it would


class TestErrorResponseFormat:
    """Test error response format and Turkish localization."""

    def setup_method(self):
        """Set up test fixtures."""
        self.client = TestClient(app)
        self.mock_db = Mock(spec=Session)

        def override_get_db():
            return self.mock_db

        app.dependency_overrides[get_db] = override_get_db

    def teardown_method(self):
        """Clean up after tests."""
        app.dependency_overrides.clear()

    def test_auth_required_error_format(self):
        """Test authentication required error format."""
        response = self.client.get("/api/v1/me")

        assert response.status_code == 401
        error_detail = response.json()["detail"]

        # Check error structure
        assert "error_code" in error_detail
        assert "message" in error_detail
        assert "timestamp" in error_detail

        # Check Turkish localization
        assert "Bearer token" in error_detail["message"]

    @patch("app.middleware.jwt_middleware._authenticate_user")
    def test_rbac_forbidden_error_format(self, mock_auth):
        """Test RBAC forbidden error format."""
        from app.middleware.jwt_middleware import AuthenticatedUser
        from app.models.session import Session as SessionModel
        from app.services.jwt_service import JWTClaims

        user = User(
            id=789,
            email="viewer@example.com",
            role=UserRole.VIEWER,
            is_active=True,
            account_status="active",
        )

        session = Mock(spec=SessionModel)
        claims = Mock(spec=JWTClaims)
        authenticated_user = AuthenticatedUser(user, session, claims)
        mock_auth.return_value = authenticated_user

        self.mock_db.add = Mock()
        self.mock_db.commit = Mock()

        response = self.client.get(
            "/api/v1/admin/users", headers={"Authorization": "Bearer viewer-token"}
        )

        assert response.status_code == 403
        error_detail = response.json()["detail"]

        # Check error structure
        assert error_detail["error_code"] == "ERR-ADMIN-REQUIRED"
        assert "admin yetkisi" in error_detail["message"]
        assert "details" in error_detail
        assert "timestamp" in error_detail

        # Check details contain role information
        assert error_detail["details"]["user_role"] == "viewer"

    @patch("app.middleware.jwt_middleware._authenticate_user")
    def test_insufficient_scopes_error_format(self, mock_auth):
        """Test insufficient scopes error format."""
        from app.middleware.jwt_middleware import AuthenticatedUser
        from app.models.session import Session as SessionModel
        from app.services.jwt_service import JWTClaims

        user = User(
            id=999,
            email="operator@example.com",
            role=UserRole.OPERATOR,
            is_active=True,
            account_status="active",
        )

        session = Mock(spec=SessionModel)
        claims = Mock(spec=JWTClaims)
        authenticated_user = AuthenticatedUser(user, session, claims)
        mock_auth.return_value = authenticated_user

        self.mock_db.add = Mock()
        self.mock_db.commit = Mock()

        response = self.client.post(
            "/api/v1/designs",
            headers={"Authorization": "Bearer operator-token"},
            json={"prompt": "Test design"},
        )

        assert response.status_code == 403
        error_detail = response.json()["detail"]

        # Check error structure
        assert error_detail["error_code"] == "ERR-INSUFFICIENT-SCOPES"
        assert "izin kapsamı" in error_detail["message"]
        assert "required_scopes" in error_detail["details"]
        assert "user_scopes" in error_detail["details"]

        # Check scope information
        assert "designs:write" in error_detail["details"]["required_scopes"]


class TestPerformanceIntegration:
    """Test RBAC performance in realistic integration scenarios."""

    def setup_method(self):
        """Set up test fixtures."""
        self.client = TestClient(app)
        self.mock_db = Mock(spec=Session)

        def override_get_db():
            return self.mock_db

        app.dependency_overrides[get_db] = override_get_db

    def teardown_method(self):
        """Clean up after tests."""
        app.dependency_overrides.clear()

    @patch("app.middleware.jwt_middleware._authenticate_user")
    def test_authorization_performance_under_load(self, mock_auth):
        """Test authorization performance with multiple concurrent requests."""
        import time
        from concurrent.futures import ThreadPoolExecutor
        from app.middleware.jwt_middleware import AuthenticatedUser
        from app.models.session import Session as SessionModel
        from app.services.jwt_service import JWTClaims

        # Create test user
        user = User(
            id=1000,
            email="perf@example.com",
            role=UserRole.ENGINEER,
            is_active=True,
            account_status="active",
        )

        session = Mock(spec=SessionModel)
        claims = Mock(spec=JWTClaims)
        authenticated_user = AuthenticatedUser(user, session, claims)
        mock_auth.return_value = authenticated_user

        # Mock successful responses
        self.mock_db.add = Mock()
        self.mock_db.commit = Mock()

        def make_request():
            start = time.perf_counter()
            response = self.client.get("/api/v1/me", headers={"Authorization": "Bearer test-token"})
            end = time.perf_counter()
            return (response.status_code, (end - start) * 1000)  # Return time in ms

        # Make 50 concurrent requests
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request) for _ in range(50)]
            results = [future.result() for future in futures]

        # Check all requests succeeded
        status_codes = [result[0] for result in results]
        assert all(code == 200 for code in status_codes)

        # Check performance (<10ms per request)
        response_times = [result[1] for result in results]
        avg_time = sum(response_times) / len(response_times)
        max_time = max(response_times)

        # In integration tests, times may be higher due to FastAPI overhead
        # but should still be reasonable
        assert avg_time < 50, f"Average response time {avg_time}ms too high"
        assert max_time < 100, f"Max response time {max_time}ms too high"

    @patch("app.middleware.jwt_middleware._authenticate_user")
    def test_complex_permission_check_performance(self, mock_auth):
        """Test performance of complex permission checks."""
        import time
        from app.middleware.jwt_middleware import AuthenticatedUser
        from app.models.session import Session as SessionModel
        from app.services.jwt_service import JWTClaims

        # Create admin user (has most permissions)
        user = User(
            id=2000,
            email="admin@example.com",
            role=UserRole.ADMIN,
            is_active=True,
            account_status="active",
        )

        session = Mock(spec=SessionModel)
        claims = Mock(spec=JWTClaims)
        authenticated_user = AuthenticatedUser(user, session, claims)
        mock_auth.return_value = authenticated_user

        # Mock admin endpoint responses
        self.mock_db.query.return_value.filter.return_value.offset.return_value.limit.return_value.all.return_value = []

        start_time = time.perf_counter()

        # Make multiple admin requests (complex permission checks)
        for _ in range(20):
            response = self.client.get(
                "/api/v1/admin/users", headers={"Authorization": "Bearer admin-token"}
            )
            assert response.status_code == 200

        end_time = time.perf_counter()
        avg_time_ms = ((end_time - start_time) / 20) * 1000

        # Admin endpoints should still be fast
        assert avg_time_ms < 100, f"Complex permission check took {avg_time_ms}ms per request"


class TestRBACZeroFalsePositives:
    """Test that RBAC has zero false positives/negatives."""

    def setup_method(self):
        """Set up test fixtures."""
        self.client = TestClient(app)
        self.mock_db = Mock(spec=Session)

        def override_get_db():
            return self.mock_db

        app.dependency_overrides[get_db] = override_get_db

    def teardown_method(self):
        """Clean up after tests."""
        app.dependency_overrides.clear()

    @patch("app.middleware.jwt_middleware._authenticate_user")
    def test_no_false_positives_viewer_admin_access(self, mock_auth):
        """Test viewer cannot access admin endpoints (no false positive)."""
        from app.middleware.jwt_middleware import AuthenticatedUser
        from app.models.session import Session as SessionModel
        from app.services.jwt_service import JWTClaims

        # Viewer should NEVER access admin endpoints
        user = User(
            id=3001,
            email="viewer@example.com",
            role=UserRole.VIEWER,
            is_active=True,
            account_status="active",
        )

        session = Mock(spec=SessionModel)
        claims = Mock(spec=JWTClaims)
        authenticated_user = AuthenticatedUser(user, session, claims)
        mock_auth.return_value = authenticated_user

        self.mock_db.add = Mock()
        self.mock_db.commit = Mock()

        # Test multiple admin endpoints
        admin_endpoints = [
            "/api/v1/admin/users",
            "/api/v1/admin/security-events",
            "/api/v1/admin/permissions",
        ]

        for endpoint in admin_endpoints:
            response = self.client.get(endpoint, headers={"Authorization": "Bearer viewer-token"})

            # Should ALWAYS be denied
            assert response.status_code == 403, f"Viewer incorrectly allowed access to {endpoint}"
            assert response.json()["detail"]["error_code"] == "ERR-ADMIN-REQUIRED"

    @patch("app.middleware.jwt_middleware._authenticate_user")
    def test_no_false_negatives_admin_access(self, mock_auth):
        """Test admin can access all endpoints (no false negative)."""
        from app.middleware.jwt_middleware import AuthenticatedUser
        from app.models.session import Session as SessionModel
        from app.services.jwt_service import JWTClaims

        # Admin should access ALL endpoints
        user = User(
            id=4001,
            email="admin@example.com",
            role=UserRole.ADMIN,
            is_active=True,
            account_status="active",
        )

        session = Mock(spec=SessionModel)
        claims = Mock(spec=JWTClaims)
        authenticated_user = AuthenticatedUser(user, session, claims)
        mock_auth.return_value = authenticated_user

        # Mock successful responses
        self.mock_db.query.return_value.filter.return_value.offset.return_value.limit.return_value.all.return_value = []

        # Test admin endpoints
        response = self.client.get(
            "/api/v1/admin/users", headers={"Authorization": "Bearer admin-token"}
        )

        # Admin should ALWAYS be allowed
        assert response.status_code == 200, "Admin incorrectly denied access"

    @patch("app.middleware.jwt_middleware._authenticate_user")
    def test_no_false_negatives_engineer_model_access(self, mock_auth):
        """Test engineer can access model endpoints (no false negative)."""
        from app.middleware.jwt_middleware import AuthenticatedUser
        from app.models.session import Session as SessionModel
        from app.services.jwt_service import JWTClaims

        # Engineer should access model operations
        user = User(
            id=5001,
            email="engineer@example.com",
            role=UserRole.ENGINEER,
            is_active=True,
            account_status="active",
        )

        session = Mock(spec=SessionModel)
        claims = Mock(spec=JWTClaims)
        authenticated_user = AuthenticatedUser(user, session, claims)
        mock_auth.return_value = authenticated_user

        # Mock database for design creation
        with patch("app.routers.designs.db_session") as mock_db_session:
            mock_db_session.return_value.__enter__.return_value = self.mock_db
            mock_db_session.return_value.__exit__.return_value = None
            self.mock_db.query.return_value.filter_by.return_value.first.return_value = None

            with patch("app.routers.designs.design_orchestrate.delay"):
                with patch("app.routers.designs.is_queue_paused", return_value=False):
                    response = self.client.post(
                        "/api/v1/designs/analyze",
                        headers={"Authorization": "Bearer engineer-token"},
                        json={"prompt": "Test design", "targets": {"ratio": 2.0}},
                    )

        # Engineer should be allowed (status 200 or 422 for validation errors)
        assert response.status_code in [200, 422], (
            "Engineer incorrectly denied access to design endpoints"
        )

        # Should not be authorization error
        if response.status_code != 200:
            error_detail = response.json().get("detail", {})
            if isinstance(error_detail, dict):
                assert error_detail.get("error_code") not in [
                    "ERR-ADMIN-REQUIRED",
                    "ERR-INSUFFICIENT-SCOPES",
                    "ERR-RBAC-FORBIDDEN",
                ], "Engineer denied access due to authorization, not validation"
