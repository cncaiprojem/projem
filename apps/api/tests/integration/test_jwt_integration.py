"""
JWT Integration Tests for Task 3.3

End-to-end integration tests for the complete JWT authentication flow:
- Login with JWT token creation and refresh cookie setting
- Protected route access with JWT verification
- Refresh token rotation workflow
- Logout and session cleanup
- Security scenarios and edge cases
"""

import pytest
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

from app.models.user import User
from app.models.session import Session
from app.models.security_event import SecurityEvent
from app.models.audit_log import AuditLog
from app.services.jwt_service import jwt_service
from app.services.token_service import token_service
from app.config import settings


class TestJWTAuthenticationFlow:
    """Test complete JWT authentication workflow."""

    def test_complete_login_refresh_logout_flow(
        self, client: TestClient, db: DBSession, test_user_with_password: User
    ):
        """Test complete authentication flow from login to logout."""

        # Step 1: Login and get JWT access token + refresh cookie
        login_response = client.post(
            "/api/v1/auth/login",
            json={
                "email": test_user_with_password.email,
                "password": "TestPassword123!",
                "device_fingerprint": "integration-test-device",
            },
        )

        assert login_response.status_code == 200
        login_data = login_response.json()

        assert "access_token" in login_data
        assert login_data["token_type"] == "bearer"
        assert "expires_in" in login_data

        access_token = login_data["access_token"]

        # Verify refresh cookie was set
        cookies = login_response.cookies
        assert settings.refresh_token_cookie_name in cookies
        refresh_cookie = cookies[settings.refresh_token_cookie_name]
        assert len(refresh_cookie) > 50

        # Step 2: Access protected route with JWT token
        protected_response = client.get(
            "/api/v1/auth/sessions", headers={"Authorization": f"Bearer {access_token}"}
        )

        assert protected_response.status_code == 200
        sessions_data = protected_response.json()
        assert "sessions" in sessions_data
        assert sessions_data["total_count"] >= 1

        # Step 3: Refresh access token using refresh cookie
        # Set the refresh cookie from login response
        client.cookies.set(settings.refresh_token_cookie_name, refresh_cookie)

        refresh_response = client.post("/api/v1/auth/token/refresh")

        assert refresh_response.status_code == 200
        refresh_data = refresh_response.json()

        assert "access_token" in refresh_data
        assert refresh_data["token_type"] == "bearer"

        new_access_token = refresh_data["access_token"]
        assert new_access_token != access_token  # Should be different token

        # Verify new refresh cookie was set (rotation)
        new_cookies = refresh_response.cookies
        assert settings.refresh_token_cookie_name in new_cookies
        new_refresh_cookie = new_cookies[settings.refresh_token_cookie_name]
        assert new_refresh_cookie != refresh_cookie

        # Step 4: Use new access token for protected route
        protected_response2 = client.get(
            "/api/v1/auth/sessions", headers={"Authorization": f"Bearer {new_access_token}"}
        )

        assert protected_response2.status_code == 200

        # Step 5: Logout and cleanup
        logout_response = client.post(
            "/api/v1/auth/logout", headers={"Authorization": f"Bearer {new_access_token}"}
        )

        assert logout_response.status_code == 204

        # Verify refresh cookie was cleared
        logout_cookies = logout_response.cookies
        assert settings.refresh_token_cookie_name in logout_cookies
        assert logout_cookies[settings.refresh_token_cookie_name] == ""

        # Step 6: Verify access token no longer works
        protected_response3 = client.get(
            "/api/v1/auth/sessions", headers={"Authorization": f"Bearer {new_access_token}"}
        )

        assert protected_response3.status_code == 401
        error_data = protected_response3.json()
        assert error_data["detail"]["error_code"] == "ERR-TOKEN-REVOKED"

    def test_refresh_token_reuse_attack_scenario(
        self, client: TestClient, db: DBSession, test_user_with_password: User
    ):
        """Simulate refresh token reuse attack and verify security response."""

        # Step 1: Login and get initial tokens
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": test_user_with_password.email, "password": "TestPassword123!"},
        )

        assert login_response.status_code == 200
        initial_refresh_cookie = login_response.cookies[settings.refresh_token_cookie_name]

        # Step 2: Legitimate refresh (rotation)
        client.cookies.set(settings.refresh_token_cookie_name, initial_refresh_cookie)
        refresh_response = client.post("/api/v1/auth/token/refresh")

        assert refresh_response.status_code == 200
        new_refresh_cookie = refresh_response.cookies[settings.refresh_token_cookie_name]

        # Step 3: Attempt to reuse old refresh token (attack simulation)
        client.cookies.set(settings.refresh_token_cookie_name, initial_refresh_cookie)
        attack_response = client.post("/api/v1/auth/token/refresh")

        # Should detect reuse and revoke all sessions
        assert attack_response.status_code == 401
        error_data = attack_response.json()
        assert error_data["detail"]["error_code"] == "ERR-REFRESH-REUSE"
        assert "yeniden kullanım" in error_data["detail"]["message"].lower()

        # Step 4: Verify all sessions for user are revoked (nuclear response)
        active_sessions = (
            db.query(Session)
            .filter(Session.user_id == test_user_with_password.id, Session.revoked_at.is_(None))
            .count()
        )
        assert active_sessions == 0

        # Step 5: Verify security event was logged
        security_events = (
            db.query(SecurityEvent)
            .filter(
                SecurityEvent.user_id == test_user_with_password.id,
                SecurityEvent.event_type == "REFRESH_TOKEN_REUSE_ATTACK",
            )
            .count()
        )
        assert security_events > 0

        # Step 6: Verify legitimate refresh token also no longer works
        client.cookies.set(settings.refresh_token_cookie_name, new_refresh_cookie)
        legitimate_response = client.post("/api/v1/auth/token/refresh")
        assert legitimate_response.status_code == 401

    def test_logout_all_sessions_scenario(
        self, client: TestClient, db: DBSession, test_user_with_password: User
    ):
        """Test logout all sessions functionality."""

        # Step 1: Create multiple sessions (simulate multiple devices)
        session_tokens = []

        for i in range(3):
            login_response = client.post(
                "/api/v1/auth/login",
                json={
                    "email": test_user_with_password.email,
                    "password": "TestPassword123!",
                    "device_fingerprint": f"device-{i}",
                },
            )

            assert login_response.status_code == 200
            session_tokens.append(login_response.json()["access_token"])

        # Step 2: Verify all sessions are active
        active_sessions_before = (
            db.query(Session)
            .filter(Session.user_id == test_user_with_password.id, Session.revoked_at.is_(None))
            .count()
        )
        assert active_sessions_before == 3

        # Step 3: Use one session to logout all
        logout_all_response = client.post(
            "/api/v1/auth/logout/all", headers={"Authorization": f"Bearer {session_tokens[0]}"}
        )

        assert logout_all_response.status_code == 204

        # Step 4: Verify all sessions are revoked
        active_sessions_after = (
            db.query(Session)
            .filter(Session.user_id == test_user_with_password.id, Session.revoked_at.is_(None))
            .count()
        )
        assert active_sessions_after == 0

        # Step 5: Verify none of the access tokens work anymore
        for token in session_tokens:
            protected_response = client.get(
                "/api/v1/auth/sessions", headers={"Authorization": f"Bearer {token}"}
            )
            assert protected_response.status_code == 401

    def test_jwt_token_expiration_handling(
        self, client: TestClient, db: DBSession, test_user_with_password: User
    ):
        """Test JWT access token expiration handling."""

        # Create a session manually to control token expiration
        result = token_service.create_refresh_session(db=db, user=test_user_with_password)

        # Create an expired access token manually
        from datetime import datetime, timezone, timedelta

        past_time = datetime.now(timezone.utc) - timedelta(hours=1)

        expired_payload = {
            "sub": str(test_user_with_password.id),
            "role": str(test_user_with_password.role),
            "scopes": ["read"],
            "sid": str(result.session.id),
            "iat": int((past_time - timedelta(hours=1)).timestamp()),
            "exp": int(past_time.timestamp()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "jti": "expired-token-test",
        }

        import jwt

        expired_token = jwt.encode(
            expired_payload, jwt_service.secret_key, algorithm=jwt_service.algorithm
        )

        # Try to use expired token
        protected_response = client.get(
            "/api/v1/auth/sessions", headers={"Authorization": f"Bearer {expired_token}"}
        )

        assert protected_response.status_code == 401
        error_data = protected_response.json()
        assert error_data["detail"]["error_code"] == "ERR-TOKEN-EXPIRED"
        assert "süresi dolmuş" in error_data["detail"]["message"].lower()

    def test_device_fingerprint_security_monitoring(
        self, client: TestClient, db: DBSession, test_user_with_password: User
    ):
        """Test device fingerprint security monitoring."""

        # Step 1: Login with specific device fingerprint
        original_fingerprint = "secure-device-fingerprint-123"

        login_response = client.post(
            "/api/v1/auth/login",
            json={
                "email": test_user_with_password.email,
                "password": "TestPassword123!",
                "device_fingerprint": original_fingerprint,
            },
        )

        assert login_response.status_code == 200
        refresh_cookie = login_response.cookies[settings.refresh_token_cookie_name]

        # Step 2: Attempt refresh with different device fingerprint (suspicious)
        client.cookies.set(settings.refresh_token_cookie_name, refresh_cookie)

        suspicious_response = client.post(
            "/api/v1/auth/token/refresh",
            headers={"X-Device-Fingerprint": "different-suspicious-fingerprint"},
        )

        # Should still work but log security event
        assert suspicious_response.status_code == 200

        # Step 3: Verify security event was logged for device mismatch
        security_events = (
            db.query(SecurityEvent)
            .filter(
                SecurityEvent.user_id == test_user_with_password.id,
                SecurityEvent.event_type == "DEVICE_FINGERPRINT_MISMATCH",
            )
            .count()
        )
        assert security_events > 0

    def test_concurrent_session_management(
        self, client: TestClient, db: DBSession, test_user_with_password: User
    ):
        """Test concurrent session management and limits."""

        # Create many sessions to test session limit
        access_tokens = []

        # Create sessions up to the limit
        for i in range(12):  # Exceeds max_sessions_per_user (10)
            login_response = client.post(
                "/api/v1/auth/login",
                json={
                    "email": test_user_with_password.email,
                    "password": "TestPassword123!",
                    "device_fingerprint": f"device-{i}",
                },
            )

            assert login_response.status_code == 200
            access_tokens.append(login_response.json()["access_token"])

        # Verify session limit was enforced (oldest sessions should be revoked)
        active_sessions = (
            db.query(Session)
            .filter(Session.user_id == test_user_with_password.id, Session.revoked_at.is_(None))
            .count()
        )

        # Should not exceed max limit
        max_sessions = token_service.session_service.max_sessions_per_user
        assert active_sessions <= max_sessions

        # Verify security event was logged for session limit exceeded
        security_events = (
            db.query(SecurityEvent)
            .filter(
                SecurityEvent.user_id == test_user_with_password.id,
                SecurityEvent.event_type == "SESSION_LIMIT_EXCEEDED",
            )
            .count()
        )
        assert security_events > 0


class TestJWTErrorScenarios:
    """Test various JWT error scenarios and edge cases."""

    def test_malformed_jwt_token(self, client: TestClient):
        """Test handling of malformed JWT tokens."""
        # Test with completely invalid token
        response = client.get(
            "/api/v1/auth/sessions", headers={"Authorization": "Bearer invalid-token"}
        )

        assert response.status_code == 401
        error_data = response.json()
        assert error_data["detail"]["error_code"] == "ERR-TOKEN-MALFORMED"

    def test_missing_authorization_header(self, client: TestClient):
        """Test protected route without authorization header."""
        response = client.get("/api/v1/auth/sessions")

        assert response.status_code == 401
        error_data = response.json()
        assert error_data["detail"]["error_code"] == "ERR-TOKEN-INVALID"
        assert "authorization header" in error_data["detail"]["message"].lower()

    def test_wrong_token_algorithm(
        self, client: TestClient, db: DBSession, test_user_with_password: User
    ):
        """Test JWT token with wrong algorithm."""
        # Create token with wrong algorithm
        payload = {
            "sub": str(test_user_with_password.id),
            "role": str(test_user_with_password.role),
            "scopes": ["read"],
            "sid": str(uuid.uuid4()),
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(minutes=30)).timestamp()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "jti": str(uuid.uuid4()),
        }

        import jwt

        wrong_algo_token = jwt.encode(
            payload, jwt_service.secret_key, algorithm="HS512"
        )  # Wrong algorithm

        response = client.get(
            "/api/v1/auth/sessions", headers={"Authorization": f"Bearer {wrong_algo_token}"}
        )

        assert response.status_code == 401

    def test_token_with_nonexistent_user(self, client: TestClient, db: DBSession):
        """Test JWT token for user that no longer exists."""
        # Create token for non-existent user
        payload = {
            "sub": "99999",  # Non-existent user ID
            "role": "engineer",
            "scopes": ["read"],
            "sid": str(uuid.uuid4()),
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(minutes=30)).timestamp()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "jti": str(uuid.uuid4()),
        }

        import jwt

        token = jwt.encode(payload, jwt_service.secret_key, algorithm=jwt_service.algorithm)

        response = client.get("/api/v1/auth/sessions", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401
        error_data = response.json()
        assert error_data["detail"]["error_code"] == "ERR-USER-NOT-FOUND"


class TestJWTPerformance:
    """Test JWT performance characteristics."""

    def test_jwt_verification_performance(self, db: DBSession, test_user_with_password: User):
        """Test JWT verification performance for high-throughput scenarios."""
        # Create session and token
        result = token_service.create_refresh_session(db=db, user=test_user_with_password)
        access_token = result.access_token

        # Time multiple verifications
        import time

        start_time = time.time()

        for _ in range(100):
            claims = jwt_service.verify_access_token(access_token, db)
            assert claims.sub == str(test_user_with_password.id)

        end_time = time.time()
        total_time = end_time - start_time
        avg_time_ms = (total_time / 100) * 1000

        # Should be fast enough for production use
        assert avg_time_ms < 50  # Less than 50ms per verification

    def test_refresh_token_generation_performance(self):
        """Test refresh token generation performance."""
        import time

        start_time = time.time()

        tokens = []
        for _ in range(1000):
            token = token_service.generate_refresh_token()
            tokens.append(token)

        end_time = time.time()
        total_time = end_time - start_time
        avg_time_ms = (total_time / 1000) * 1000

        # Should be fast enough for production use
        assert avg_time_ms < 5  # Less than 5ms per token generation

        # Verify all tokens are unique
        assert len(set(tokens)) == 1000


@pytest.fixture
def test_user_with_password(db: DBSession) -> User:
    """Create a test user with a real password hash."""
    from app.services.password_service import password_service

    password_hash = password_service.hash_password("TestPassword123!")

    user = User(
        email="jwt-integration@example.com",
        password_hash=password_hash,
        role="engineer",
        is_active=True,
        email_verified=True,
        failed_login_attempts=0,
        account_locked_until=None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# Additional imports for testing
import uuid
