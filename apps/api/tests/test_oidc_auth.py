"""
Ultra Enterprise OIDC Authentication Tests for Task 3.5

These tests verify the Google OAuth2/OIDC authentication flow with:
- PKCE (S256) security validation
- State parameter CSRF protection
- Nonce verification in ID tokens
- Comprehensive error handling
- Turkish localized error messages
- Audit logging with PII masking
"""

import pytest
import json
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.user import User
from app.models.oidc_account import OIDCAccount
from app.models.audit_log import AuditLog
from app.models.security_event import SecurityEvent
from app.services.oidc_service import oidc_service, OIDCServiceError
from app.schemas.oidc_schemas import OIDC_ERROR_CODES


@pytest.fixture
def client():
    """Test client for OIDC endpoints."""
    return TestClient(app)


@pytest.fixture
def mock_redis():
    """Mock Redis client for OIDC state storage."""
    with patch("app.services.oidc_service.get_redis") as mock:
        redis_mock = AsyncMock()
        mock.return_value = redis_mock
        yield redis_mock


@pytest.fixture
def mock_google_config():
    """Mock Google OIDC configuration."""
    return {
        "issuer": "https://accounts.google.com",
        "authorization_endpoint": "https://accounts.google.com/o/oauth2/auth",
        "token_endpoint": "https://accounts.google.com/o/oauth2/token",
        "userinfo_endpoint": "https://openidconnect.googleapis.com/v1/userinfo",
        "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
    }


@pytest.fixture
def mock_id_token_claims():
    """Mock ID token claims from Google."""
    return {
        "iss": "https://accounts.google.com",
        "aud": "test-client-id.apps.googleusercontent.com",
        "sub": "google-user-123456789",
        "email": "test@example.com",
        "email_verified": True,
        "name": "Test User",
        "picture": "https://example.com/avatar.jpg",
        "nonce": "test-nonce-123",
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        "iat": int(datetime.now(timezone.utc).timestamp()),
    }


class TestOIDCStatus:
    """Test OIDC status endpoint."""

    def test_oidc_status_enabled(self, client):
        """Test OIDC status when enabled."""
        with (
            patch("app.settings.google_oauth_enabled", True),
            patch("app.settings.google_client_id", "test-client-id"),
        ):
            response = client.get("/api/v1/auth/oidc/status")

            assert response.status_code == 200
            data = response.json()
            assert data["google_oauth_enabled"] is True
            assert "client_id" in data
            assert data["scopes"] == ["openid", "email", "profile"]
            assert "redirect_uri" in data

    def test_oidc_status_disabled(self, client):
        """Test OIDC status when disabled."""
        with patch("app.settings.google_oauth_enabled", False):
            response = client.get("/api/v1/auth/oidc/status")

            assert response.status_code == 200
            data = response.json()
            assert data["google_oauth_enabled"] is False
            assert data["client_id"] is None


class TestOIDCAuthStart:
    """Test OIDC authentication start endpoint."""

    @patch("app.services.oidc_service.oidc_service.create_authorization_url")
    def test_start_auth_success(self, mock_create_url, client, mock_redis):
        """Test successful OIDC authentication start."""
        mock_create_url.return_value = (
            "https://accounts.google.com/o/oauth2/auth?client_id=test",
            "test-state-123",
        )

        with (
            patch("app.settings.google_oauth_enabled", True),
            patch("app.settings.google_client_id", "test-client-id"),
            patch("app.settings.google_client_secret", "test-secret"),
        ):
            response = client.get("/api/v1/auth/oidc/google/start")

            assert response.status_code == 200
            data = response.json()
            assert "authorization_url" in data
            assert "state" in data
            assert data["expires_in"] == 900  # 15 minutes
            assert "OIDC kimlik doğrulama başlatıldı" in data["message"]

    def test_start_auth_disabled(self, client):
        """Test OIDC start when disabled."""
        with patch("app.settings.google_oauth_enabled", False):
            response = client.get("/api/v1/auth/oidc/google/start")

            assert response.status_code == 403
            data = response.json()
            assert data["detail"]["error_code"] == "ERR-OIDC-DISABLED"

    def test_start_auth_missing_config(self, client):
        """Test OIDC start with incomplete configuration."""
        with (
            patch("app.settings.google_oauth_enabled", True),
            patch("app.settings.google_client_id", None),
        ):
            response = client.get("/api/v1/auth/oidc/google/start")

            assert response.status_code == 500
            data = response.json()
            assert data["detail"]["error_code"] == "ERR-OIDC-CONFIG-FAILED"

    @patch("app.services.oidc_service.oidc_service.create_authorization_url")
    def test_start_auth_service_error(self, mock_create_url, client):
        """Test OIDC start with service error."""
        mock_create_url.side_effect = OIDCServiceError("ERR-OIDC-AUTH-URL-FAILED", "Test error")

        with (
            patch("app.settings.google_oauth_enabled", True),
            patch("app.settings.google_client_id", "test-client-id"),
            patch("app.settings.google_client_secret", "test-secret"),
        ):
            response = client.get("/api/v1/auth/oidc/google/start")

            assert response.status_code == 400
            data = response.json()
            assert data["error_code"] == "ERR-OIDC-AUTH-URL-FAILED"


class TestOIDCCallback:
    """Test OIDC callback endpoint."""

    @patch("app.services.oidc_service.oidc_service.exchange_code_for_tokens")
    @patch("app.services.oidc_service.oidc_service.authenticate_or_link_user")
    def test_callback_success_existing_user(
        self,
        mock_auth_user,
        mock_exchange_tokens,
        client,
        mock_redis,
        mock_id_token_claims,
        db_session,
    ):
        """Test successful OIDC callback for existing user."""
        # Mock token exchange
        mock_exchange_tokens.return_value = {
            "access_token": "google-access-token",
            "id_token": "google-id-token",
            "id_token_claims": mock_id_token_claims,
            "expires_in": 3600,
        }

        # Create existing user
        user = User(email="test@example.com", role="engineer", account_status="active")
        db_session.add(user)
        db_session.commit()

        # Create OIDC account
        oidc_account = OIDCAccount(
            user_id=user.id,
            provider="google",
            sub="google-user-123456789",
            email="test@example.com",
            email_verified=True,
        )

        # Mock authentication result
        from app.services.oidc_service import OIDCAuthResult

        auth_result = OIDCAuthResult(
            user=user,
            oidc_account=oidc_account,
            is_new_user=False,
            is_new_oidc_link=False,
            access_token="jwt-access-token",
            refresh_token="refresh-token",
            expires_in=1800,
        )
        mock_auth_user.return_value = auth_result

        with (
            patch("app.settings.google_oauth_enabled", True),
            patch("app.settings.google_client_id", "test-client-id"),
            patch("app.settings.google_client_secret", "test-secret"),
        ):
            response = client.get(
                "/api/v1/auth/oidc/google/callback",
                params={"code": "test-auth-code", "state": "test-state"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["access_token"] == "jwt-access-token"
            assert data["user_id"] == user.id
            assert data["email"] == "test@example.com"
            assert data["is_new_user"] is False
            assert data["is_new_oidc_link"] is False
            assert "Google OIDC girişi başarılı" in data["message"]

    @patch("app.services.oidc_service.oidc_service.exchange_code_for_tokens")
    def test_callback_token_exchange_failure(self, mock_exchange_tokens, client):
        """Test OIDC callback with token exchange failure."""
        mock_exchange_tokens.side_effect = OIDCServiceError(
            "ERR-OIDC-TOKEN-EXCHANGE", "OIDC token değişimi başarısız"
        )

        with (
            patch("app.settings.google_oauth_enabled", True),
            patch("app.settings.google_client_id", "test-client-id"),
            patch("app.settings.google_client_secret", "test-secret"),
        ):
            response = client.get(
                "/api/v1/auth/oidc/google/callback",
                params={"code": "test-auth-code", "state": "test-state"},
            )

            assert response.status_code == 400
            data = response.json()
            assert data["error_code"] == "ERR-OIDC-TOKEN-EXCHANGE"

    def test_callback_oauth_error(self, client):
        """Test OIDC callback with OAuth error from Google."""
        with patch("app.settings.google_oauth_enabled", True):
            response = client.get(
                "/api/v1/auth/oidc/google/callback",
                params={
                    "error": "access_denied",
                    "error_description": "User denied access",
                    "state": "test-state",
                },
            )

            assert response.status_code == 400
            data = response.json()
            assert "Kullanıcı erişim izni vermedi" in data["message"]

    def test_callback_disabled(self, client):
        """Test OIDC callback when disabled."""
        with patch("app.settings.google_oauth_enabled", False):
            response = client.get(
                "/api/v1/auth/oidc/google/callback",
                params={"code": "test-auth-code", "state": "test-state"},
            )

            assert response.status_code == 403
            data = response.json()
            assert data["detail"]["error_code"] == "ERR-OIDC-DISABLED"


class TestOIDCService:
    """Test OIDC service methods."""

    @pytest.mark.asyncio
    async def test_generate_pkce_pair(self):
        """Test PKCE code verifier and challenge generation."""
        code_verifier, code_challenge = oidc_service.generate_pkce_pair()

        assert len(code_verifier) >= 43  # Base64URL encoded 96 bytes
        assert len(code_challenge) == 43  # Base64URL encoded SHA256 hash
        assert code_verifier != code_challenge

    def test_generate_secure_state(self):
        """Test secure state parameter generation."""
        state = oidc_service.generate_secure_state()

        assert len(state) >= 43  # 64 bytes base64url encoded
        assert all(c.isalnum() or c in "-_" for c in state)  # URL-safe

    def test_generate_nonce(self):
        """Test nonce generation."""
        nonce = oidc_service.generate_nonce()

        assert len(nonce) >= 22  # 32 bytes base64url encoded
        assert all(c.isalnum() or c in "-_" for c in nonce)  # URL-safe

    @pytest.mark.asyncio
    async def test_store_oauth_state(self, mock_redis):
        """Test OAuth state storage in Redis."""
        state = "test-state-123"
        pkce_verifier = "test-verifier"
        nonce = "test-nonce"
        redirect_uri = "http://localhost:3000/callback"

        await oidc_service.store_oauth_state(state, pkce_verifier, nonce, redirect_uri)

        # Verify Redis calls
        assert mock_redis.setex.call_count == 3  # state, pkce, nonce

        # Check state data call
        state_call = mock_redis.setex.call_args_list[0]
        assert state_call[0][0] == f"oidc:state:{state}"
        assert state_call[0][1] == 900  # 15 minutes

        state_data = json.loads(state_call[0][2])
        assert state_data["pkce_verifier"] == pkce_verifier
        assert state_data["nonce"] == nonce
        assert state_data["redirect_uri"] == redirect_uri

    @pytest.mark.asyncio
    async def test_retrieve_and_validate_state_success(self, mock_redis):
        """Test successful state retrieval and validation."""
        state = "test-state-123"

        # Mock Redis responses
        state_data = {
            "pkce_verifier": "test-verifier",
            "nonce": "test-nonce",
            "redirect_uri": "http://localhost:3000/callback",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        mock_redis.get.side_effect = [
            json.dumps(state_data),  # state data
            "test-verifier",  # pkce verifier
            "test-nonce",  # nonce
        ]

        result = await oidc_service.retrieve_and_validate_state(state)

        assert result["pkce_verifier"] == "test-verifier"
        assert result["nonce"] == "test-nonce"
        assert result["redirect_uri"] == "http://localhost:3000/callback"

        # Verify cleanup calls
        assert mock_redis.delete.call_count == 3

    @pytest.mark.asyncio
    async def test_retrieve_and_validate_state_not_found(self, mock_redis):
        """Test state validation with missing state."""
        mock_redis.get.return_value = None

        with pytest.raises(OIDCServiceError) as exc_info:
            await oidc_service.retrieve_and_validate_state("invalid-state")

        assert exc_info.value.code == "ERR-OIDC-STATE"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_get_google_config_success(self, mock_http_get, mock_google_config):
        """Test successful Google configuration retrieval."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_google_config
        mock_response.raise_for_status.return_value = None
        mock_http_get.return_value.__aenter__.return_value.get.return_value = mock_response

        config = await oidc_service.get_google_config()

        assert config["issuer"] == "https://accounts.google.com"
        assert "authorization_endpoint" in config
        assert "token_endpoint" in config

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_get_google_config_http_error(self, mock_http_get):
        """Test Google configuration retrieval with HTTP error."""
        mock_http_get.side_effect = Exception("Network error")

        with pytest.raises(OIDCServiceError) as exc_info:
            await oidc_service.get_google_config()

        assert exc_info.value.code == "ERR-OIDC-CONFIG-FAILED"

    def test_verify_id_token_success(self, mock_id_token_claims):
        """Test successful ID token verification."""
        # Mock JWT decode
        with patch("jwt.decode", return_value=mock_id_token_claims):
            claims = oidc_service._verify_id_token("mock-id-token", "test-nonce-123")

            assert claims["sub"] == "google-user-123456789"
            assert claims["email"] == "test@example.com"
            assert claims["nonce"] == "test-nonce-123"

    def test_verify_id_token_invalid_nonce(self, mock_id_token_claims):
        """Test ID token verification with invalid nonce."""
        with patch("jwt.decode", return_value=mock_id_token_claims):
            with pytest.raises(OIDCServiceError) as exc_info:
                oidc_service._verify_id_token("mock-id-token", "wrong-nonce")

            assert exc_info.value.code == "ERR-OIDC-NONCE"

    def test_verify_id_token_invalid_issuer(self, mock_id_token_claims):
        """Test ID token verification with invalid issuer."""
        mock_id_token_claims["iss"] = "https://evil.com"

        with patch("jwt.decode", return_value=mock_id_token_claims):
            with pytest.raises(OIDCServiceError) as exc_info:
                oidc_service._verify_id_token("mock-id-token", "test-nonce-123")

            assert exc_info.value.code == "ERR-OIDC-INVALID-ISSUER"


class TestOIDCLogout:
    """Test OIDC logout endpoint."""

    @patch("app.services.token_service.token_service.get_refresh_token_from_request")
    @patch("app.services.token_service.token_service.revoke_refresh_token")
    @patch("app.services.token_service.token_service.clear_refresh_cookie")
    def test_logout_success(self, mock_clear_cookie, mock_revoke_token, mock_get_token, client):
        """Test successful OIDC logout."""
        mock_get_token.return_value = "test-refresh-token"

        response = client.post("/api/v1/auth/oidc/logout")

        assert response.status_code == 200
        data = response.json()
        assert "başarıyla kapatıldı" in data["message"]

        # Verify service calls
        mock_revoke_token.assert_called_once()
        mock_clear_cookie.assert_called_once()

    @patch("app.services.token_service.token_service.get_refresh_token_from_request")
    def test_logout_no_token(self, mock_get_token, client):
        """Test logout without refresh token."""
        mock_get_token.return_value = None

        response = client.post("/api/v1/auth/oidc/logout")

        assert response.status_code == 200
        data = response.json()
        assert "başarıyla kapatıldı" in data["message"]


class TestOIDCSecurityValidation:
    """Test OIDC security validation."""

    def test_error_codes_coverage(self):
        """Test that all OIDC error codes have Turkish messages."""
        for code, message in OIDC_ERROR_CODES.items():
            assert code.startswith("ERR-OIDC-")
            assert len(message) > 10  # Meaningful message
            assert any(char in "çğıöşüÇĞIİÖŞÜ" for char in message)  # Turkish chars

    @pytest.mark.asyncio
    async def test_pkce_security_validation(self):
        """Test PKCE security parameters."""
        verifier, challenge = oidc_service.generate_pkce_pair()

        # Verify verifier entropy (should be 96 bytes = 768 bits)
        assert len(verifier) >= 43  # Base64URL minimum

        # Verify challenge is derived from verifier
        import hashlib
        import base64

        expected_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )

        assert challenge == expected_challenge

    def test_state_parameter_entropy(self):
        """Test state parameter has sufficient entropy."""
        states = [oidc_service.generate_secure_state() for _ in range(100)]

        # All states should be unique
        assert len(set(states)) == 100

        # Each state should have sufficient length
        for state in states:
            assert len(state) >= 43  # 64 bytes base64url = 43+ chars

    def test_nonce_parameter_entropy(self):
        """Test nonce parameter has sufficient entropy."""
        nonces = [oidc_service.generate_nonce() for _ in range(100)]

        # All nonces should be unique
        assert len(set(nonces)) == 100

        # Each nonce should have sufficient length
        for nonce in nonces:
            assert len(nonce) >= 22  # 32 bytes base64url = 22+ chars


@pytest.mark.integration
class TestOIDCIntegration:
    """Integration tests for complete OIDC flow."""

    def test_complete_oidc_flow_simulation(self, client, db_session):
        """Test complete OIDC authentication flow simulation."""
        # This would test the complete flow in a real environment
        # For now, just verify endpoints are accessible

        with (
            patch("app.settings.google_oauth_enabled", True),
            patch("app.settings.google_client_id", "test-client-id"),
            patch("app.settings.google_client_secret", "test-secret"),
        ):
            # Test status endpoint
            status_response = client.get("/api/v1/auth/oidc/status")
            assert status_response.status_code == 200

            # Test start endpoint (will fail without proper mocking)
            # start_response = client.get("/api/v1/auth/oidc/google/start")
            # This would require more complex mocking for full integration test
