"""
Ultra Enterprise JWT Security Tests for Task 3.3

This test suite verifies banking-level JWT security implementations:
- JWT token creation and verification
- Refresh token rotation with reuse detection
- Session correlation and revocation
- Cookie security attributes
- Error handling and Turkish localization
- Security event logging and audit trails
"""

import pytest
import jwt
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
import secrets

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

from app.services.jwt_service import jwt_service, JWTError, JWTErrorCode, JWTClaims
from app.services.token_service import token_service, TokenServiceError
from app.models.user import User
from app.models.session import Session
from app.models.security_event import SecurityEvent
from app.models.audit_log import AuditLog
from app.config import settings


class TestJWTService:
    """Test JWT token creation and verification."""

    def test_create_access_token_success(
        self, db: DBSession, test_user: User, test_session: Session
    ):
        """Test successful JWT access token creation."""
        # Create access token
        token = jwt_service.create_access_token(test_user, test_session)

        assert isinstance(token, str)
        assert len(token) > 100  # JWT tokens are typically long

        # Verify token structure
        claims = jwt_service.get_token_claims_without_verification(token)
        assert claims is not None
        assert claims["sub"] == str(test_user.id)
        assert claims["role"] == str(test_user.role)
        assert claims["sid"] == str(test_session.id)
        assert "scopes" in claims
        assert "iat" in claims
        assert "exp" in claims
        assert "jti" in claims

    def test_create_access_token_with_custom_scopes(
        self, db: DBSession, test_user: User, test_session: Session
    ):
        """Test JWT token creation with custom scopes."""
        custom_scopes = ["read", "write", "admin"]

        token = jwt_service.create_access_token(test_user, test_session, custom_scopes)

        claims = jwt_service.get_token_claims_without_verification(token)
        assert claims["scopes"] == custom_scopes

    def test_verify_access_token_success(
        self, db: DBSession, test_user: User, test_session: Session
    ):
        """Test successful JWT token verification."""
        # Create and verify token
        token = jwt_service.create_access_token(test_user, test_session)
        claims = jwt_service.verify_access_token(token, db)

        assert isinstance(claims, JWTClaims)
        assert claims.sub == str(test_user.id)
        assert claims.role == str(test_user.role)
        assert claims.sid == str(test_session.id)
        assert isinstance(claims.scopes, list)
        assert claims.iat is not None
        assert claims.exp is not None

    def test_verify_expired_token(self, db: DBSession, test_user: User, test_session: Session):
        """Test verification of expired JWT token."""
        # Create token with past expiration
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)

        # Mock expired token by manually creating payload
        payload = {
            "sub": str(test_user.id),
            "role": str(test_user.role),
            "scopes": ["read"],
            "sid": str(test_session.id),
            "iat": int((past_time - timedelta(hours=1)).timestamp()),
            "exp": int(past_time.timestamp()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "jti": str(uuid.uuid4()),
        }

        expired_token = jwt.encode(payload, jwt_service.secret_key, algorithm=jwt_service.algorithm)

        with pytest.raises(JWTError) as exc_info:
            jwt_service.verify_access_token(expired_token, db)

        assert exc_info.value.code == JWTErrorCode.TOKEN_EXPIRED
        assert "süresi dolmuş" in exc_info.value.message.lower()

    def test_verify_invalid_signature(self, db: DBSession, test_user: User, test_session: Session):
        """Test verification of token with invalid signature."""
        # Create token with wrong secret
        payload = {
            "sub": str(test_user.id),
            "role": str(test_user.role),
            "scopes": ["read"],
            "sid": str(test_session.id),
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(minutes=30)).timestamp()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "jti": str(uuid.uuid4()),
        }

        invalid_token = jwt.encode(payload, "wrong-secret-key", algorithm=jwt_service.algorithm)

        with pytest.raises(JWTError) as exc_info:
            jwt_service.verify_access_token(invalid_token, db)

        assert exc_info.value.code == JWTErrorCode.TOKEN_INVALID_SIGNATURE

    def test_verify_revoked_session_token(
        self, db: DBSession, test_user: User, test_session: Session
    ):
        """Test verification of token with revoked session."""
        # Create valid token
        token = jwt_service.create_access_token(test_user, test_session)

        # Revoke session
        test_session.revoke("security_test")
        db.commit()

        with pytest.raises(JWTError) as exc_info:
            jwt_service.verify_access_token(token, db)

        assert exc_info.value.code == JWTErrorCode.TOKEN_REVOKED

    def test_verify_missing_required_claims(self, db: DBSession):
        """Test verification of token with missing required claims."""
        # Create token with missing required claims
        payload = {
            "sub": "123",
            # Missing 'role', 'sid', etc.
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(minutes=30)).timestamp()),
        }

        invalid_token = jwt.encode(payload, jwt_service.secret_key, algorithm=jwt_service.algorithm)

        with pytest.raises(JWTError) as exc_info:
            jwt_service.verify_access_token(invalid_token, db)

        assert exc_info.value.code == JWTErrorCode.TOKEN_MISSING_CLAIMS


class TestTokenService:
    """Test refresh token management and rotation."""

    def test_generate_refresh_token(self):
        """Test refresh token generation."""
        token = token_service.generate_refresh_token()

        assert isinstance(token, str)
        assert len(token) >= 80  # Base64URL encoded 64 bytes should be longer

        # Test uniqueness
        token2 = token_service.generate_refresh_token()
        assert token != token2

    def test_hash_refresh_token(self):
        """Test refresh token hashing."""
        token = "test-refresh-token"
        hash1 = token_service.hash_refresh_token(token)
        hash2 = token_service.hash_refresh_token(token)

        assert hash1 == hash2  # Same input should produce same hash
        assert len(hash1) == 128  # SHA512 hex = 128 chars
        assert hash1 != token  # Hash should be different from input

        # Different tokens should produce different hashes
        different_hash = token_service.hash_refresh_token("different-token")
        assert hash1 != different_hash

    def test_create_refresh_session(self, db: DBSession, test_user: User):
        """Test refresh session creation."""
        result = token_service.create_refresh_session(
            db=db,
            user=test_user,
            device_fingerprint="test-fingerprint",
            ip_address="192.168.1.100",
            user_agent="TestAgent/1.0",
        )

        assert result.session is not None
        assert result.refresh_token is not None
        assert result.access_token is not None
        assert result.expires_in > 0

        # Verify session was created properly
        assert result.session.user_id == test_user.id
        assert result.session.device_fingerprint == "test-fingerprint"
        assert result.session.is_active

        # Verify access token is valid JWT
        claims = jwt_service.get_token_claims_without_verification(result.access_token)
        assert claims["sub"] == str(test_user.id)
        assert claims["sid"] == str(result.session.id)

    def test_rotate_refresh_token_success(self, db: DBSession, test_user: User):
        """Test successful refresh token rotation."""
        # Create initial session
        initial_result = token_service.create_refresh_session(
            db=db, user=test_user, device_fingerprint="test-fingerprint"
        )

        initial_session_id = initial_result.session.id
        initial_token = initial_result.refresh_token

        # Rotate token
        rotated_result = token_service.rotate_refresh_token(
            db=db, current_refresh_token=initial_token, device_fingerprint="test-fingerprint"
        )

        # Verify rotation
        assert rotated_result.session.id != initial_session_id
        assert rotated_result.refresh_token != initial_token
        assert rotated_result.session.rotated_from == initial_session_id

        # Verify old session is revoked
        db.refresh(initial_result.session)
        assert initial_result.session.revoked_at is not None

        # Verify new session is active
        assert rotated_result.session.is_active

    def test_refresh_token_reuse_detection(self, db: DBSession, test_user: User):
        """Test refresh token reuse attack detection."""
        # Create initial session and rotate
        initial_result = token_service.create_refresh_session(db=db, user=test_user)
        initial_token = initial_result.refresh_token

        # First rotation (legitimate)
        rotated_result = token_service.rotate_refresh_token(
            db=db, current_refresh_token=initial_token
        )

        # Attempt to reuse old token (attack simulation)
        with pytest.raises(TokenServiceError) as exc_info:
            token_service.rotate_refresh_token(
                db=db,
                current_refresh_token=initial_token,  # Reusing revoked token
            )

        assert exc_info.value.code == "ERR-REFRESH-REUSE"
        assert "yeniden kullanım" in exc_info.value.message.lower()

        # Verify all user sessions are revoked (nuclear response)
        active_sessions = (
            db.query(Session)
            .filter(Session.user_id == test_user.id, Session.revoked_at.is_(None))
            .count()
        )
        assert active_sessions == 0

        # Verify security event was logged
        security_events = (
            db.query(SecurityEvent)
            .filter(
                SecurityEvent.user_id == test_user.id,
                SecurityEvent.event_type == "REFRESH_TOKEN_REUSE_ATTACK",
            )
            .count()
        )
        assert security_events > 0

    def test_revoke_refresh_token(self, db: DBSession, test_user: User):
        """Test refresh token revocation."""
        # Create session
        result = token_service.create_refresh_session(db=db, user=test_user)

        # Revoke token
        revoked = token_service.revoke_refresh_token(
            db=db, refresh_token=result.refresh_token, reason="test_revocation"
        )

        assert revoked is True

        # Verify session is revoked
        db.refresh(result.session)
        assert result.session.revoked_at is not None
        assert result.session.revocation_reason == "test_revocation"

    def test_revoke_all_refresh_tokens(self, db: DBSession, test_user: User):
        """Test revoking all refresh tokens for a user."""
        # Create multiple sessions
        session1 = token_service.create_refresh_session(db=db, user=test_user)
        session2 = token_service.create_refresh_session(db=db, user=test_user)
        session3 = token_service.create_refresh_session(db=db, user=test_user)

        # Revoke all tokens
        revoked_count = token_service.revoke_all_refresh_tokens(
            db=db, user_id=test_user.id, reason="logout_all_test"
        )

        assert revoked_count == 3

        # Verify all sessions are revoked
        active_sessions = (
            db.query(Session)
            .filter(Session.user_id == test_user.id, Session.revoked_at.is_(None))
            .count()
        )
        assert active_sessions == 0


class TestJWTAPIEndpoints:
    """Test JWT authentication API endpoints."""

    def test_refresh_token_endpoint_success(
        self, client: TestClient, db: DBSession, test_user: User
    ):
        """Test successful token refresh via API endpoint."""
        # Create session with refresh token
        result = token_service.create_refresh_session(db=db, user=test_user)

        # Set refresh token cookie
        client.cookies.set(settings.refresh_token_cookie_name, result.refresh_token)

        # Call refresh endpoint
        response = client.post("/api/v1/auth/token/refresh")

        assert response.status_code == 200
        data = response.json()

        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert "expires_in" in data

        # Verify new refresh token cookie was set
        cookies = response.cookies
        assert settings.refresh_token_cookie_name in cookies
        new_refresh_token = cookies[settings.refresh_token_cookie_name]
        assert new_refresh_token != result.refresh_token

    def test_refresh_token_endpoint_missing_cookie(self, client: TestClient):
        """Test refresh endpoint without refresh token cookie."""
        response = client.post("/api/v1/auth/token/refresh")

        assert response.status_code == 401
        data = response.json()

        assert data["error_code"] == "ERR-REFRESH-MISSING"
        assert "bulunamadı" in data["message"].lower()

    def test_refresh_token_endpoint_invalid_token(self, client: TestClient):
        """Test refresh endpoint with invalid refresh token."""
        # Set invalid refresh token cookie
        client.cookies.set(settings.refresh_token_cookie_name, "invalid-token")

        response = client.post("/api/v1/auth/token/refresh")

        assert response.status_code == 401
        data = response.json()

        assert data["error_code"] == "ERR-REFRESH-INVALID"

    def test_logout_endpoint_success(self, client: TestClient, db: DBSession, test_user: User):
        """Test successful logout via API endpoint."""
        # Create session and access token
        result = token_service.create_refresh_session(db=db, user=test_user)
        access_token = result.access_token

        # Set refresh token cookie
        client.cookies.set(settings.refresh_token_cookie_name, result.refresh_token)

        # Call logout endpoint with access token
        response = client.post(
            "/api/v1/auth/logout", headers={"Authorization": f"Bearer {access_token}"}
        )

        assert response.status_code == 204

        # Verify refresh token cookie was cleared
        cookies = response.cookies
        assert settings.refresh_token_cookie_name in cookies
        assert cookies[settings.refresh_token_cookie_name] == ""

        # Verify session was revoked
        db.refresh(result.session)
        assert result.session.revoked_at is not None

    def test_logout_all_endpoint_success(self, client: TestClient, db: DBSession, test_user: User):
        """Test successful logout all sessions via API endpoint."""
        # Create multiple sessions
        session1 = token_service.create_refresh_session(db=db, user=test_user)
        session2 = token_service.create_refresh_session(db=db, user=test_user)
        session3 = token_service.create_refresh_session(db=db, user=test_user)

        access_token = session1.access_token

        # Call logout all endpoint
        response = client.post(
            "/api/v1/auth/logout/all", headers={"Authorization": f"Bearer {access_token}"}
        )

        assert response.status_code == 204

        # Verify all sessions were revoked
        active_sessions = (
            db.query(Session)
            .filter(Session.user_id == test_user.id, Session.revoked_at.is_(None))
            .count()
        )
        assert active_sessions == 0

    def test_list_active_sessions_endpoint(
        self, client: TestClient, db: DBSession, test_user: User
    ):
        """Test listing active sessions via API endpoint."""
        # Create sessions
        session1 = token_service.create_refresh_session(db=db, user=test_user)
        session2 = token_service.create_refresh_session(db=db, user=test_user)

        access_token = session1.access_token

        # Call sessions endpoint
        response = client.get(
            "/api/v1/auth/sessions", headers={"Authorization": f"Bearer {access_token}"}
        )

        assert response.status_code == 200
        data = response.json()

        assert "sessions" in data
        assert "total_count" in data
        assert "current_session_id" in data

        assert data["total_count"] == 2
        assert len(data["sessions"]) == 2

        # Verify current session is marked
        current_session_marked = any(session["is_current"] for session in data["sessions"])
        assert current_session_marked


class TestJWTSecurityFeatures:
    """Test JWT security features and edge cases."""

    def test_jwt_token_expiration_timing(
        self, db: DBSession, test_user: User, test_session: Session
    ):
        """Test JWT token expiration timing accuracy."""
        start_time = datetime.now(timezone.utc)
        token = jwt_service.create_access_token(test_user, test_session)
        end_time = datetime.now(timezone.utc)

        claims = jwt_service.get_token_claims_without_verification(token)

        # Verify expiration time is approximately correct
        expected_exp = start_time + timedelta(minutes=settings.jwt_access_token_expire_minutes)
        actual_exp = datetime.fromtimestamp(claims["exp"], tz=timezone.utc)

        # Allow 1 second tolerance for timing
        time_diff = abs((actual_exp - expected_exp).total_seconds())
        assert time_diff <= 1

    def test_refresh_token_entropy(self):
        """Test refresh token has sufficient entropy."""
        tokens = set()

        # Generate many tokens to test uniqueness
        for _ in range(1000):
            token = token_service.generate_refresh_token()
            assert token not in tokens, "Duplicate refresh token generated"
            tokens.add(token)

        # All tokens should be unique
        assert len(tokens) == 1000

    def test_session_correlation_security(self, db: DBSession, test_user: User):
        """Test that JWT tokens are properly correlated with sessions."""
        # Create session and token
        result = token_service.create_refresh_session(db=db, user=test_user)

        # Verify JWT contains correct session ID
        claims = jwt_service.get_token_claims_without_verification(result.access_token)
        assert claims["sid"] == str(result.session.id)

        # Verify token verification checks session
        verified_claims = jwt_service.verify_access_token(result.access_token, db)
        assert verified_claims.sid == str(result.session.id)

    def test_cookie_security_attributes(self, client: TestClient, db: DBSession, test_user: User):
        """Test refresh token cookie security attributes."""
        # Login to get cookie
        result = token_service.create_refresh_session(db=db, user=test_user)

        # Mock response to check cookie attributes
        from fastapi import Response

        response = Response()
        token_service.set_refresh_cookie(response, result.refresh_token)

        # Verify cookie attributes are set correctly
        set_cookie_header = response.headers.get("set-cookie", "")

        assert f"{settings.refresh_token_cookie_name}=" in set_cookie_header
        assert "HttpOnly" in set_cookie_header
        assert "SameSite=strict" in set_cookie_header.lower()
        assert "Path=/" in set_cookie_header

        # In production, should also have Secure flag
        if settings.env != "development":
            assert "Secure" in set_cookie_header

    def test_audit_logging_completeness(self, db: DBSession, test_user: User):
        """Test that all JWT operations are properly audit logged."""
        initial_audit_count = db.query(AuditLog).filter(AuditLog.user_id == test_user.id).count()

        # Perform various JWT operations
        result1 = token_service.create_refresh_session(db=db, user=test_user)
        result2 = token_service.rotate_refresh_token(
            db=db, current_refresh_token=result1.refresh_token
        )
        token_service.revoke_refresh_token(db=db, refresh_token=result2.refresh_token)

        final_audit_count = db.query(AuditLog).filter(AuditLog.user_id == test_user.id).count()

        # Should have audit logs for each operation
        assert final_audit_count > initial_audit_count

        # Verify specific audit actions exist
        audit_actions = db.query(AuditLog.action).filter(AuditLog.user_id == test_user.id).all()
        action_list = [action[0] for action in audit_actions]

        expected_actions = ["refresh_token_created", "refresh_token_rotated"]
        for expected_action in expected_actions:
            assert any(expected_action in action for action in action_list)


@pytest.fixture
def test_user(db: DBSession) -> User:
    """Create a test user."""
    user = User(
        email="jwt-test@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",  # Mock hash
        role="engineer",
        is_active=True,
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def test_session(db: DBSession, test_user: User) -> Session:
    """Create a test session."""
    session = Session.create_default_session(
        user_id=test_user.id,
        refresh_token_hash="a" * 128,  # Mock hash
        device_fingerprint="test-fingerprint",
        ip_address="192.168.1.100",
        user_agent="TestAgent/1.0",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session
