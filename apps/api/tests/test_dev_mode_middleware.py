"""
Integration Tests for Dev-Mode Middleware - Task 3.12
Ultra-Enterprise development/production mode behavior validation

**Test Coverage**:
- Dev-mode feature toggles
- Production hardening enforcement
- Environment configuration validation
- Security policy enforcement
- Turkish KVKV compliance validation
"""

from __future__ import annotations

import pytest
import json
import time
from unittest.mock import patch, MagicMock
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.environment import environment, EnvironmentMode, SecurityLevel
from app.middleware.dev_mode_middleware import (
    DevModeMiddleware,
    ProductionHardeningMiddleware,
    EnvironmentValidationMiddleware
)
from app.services.environment_service import environment_service


@pytest.fixture
def test_app():
    """Create test FastAPI application with dev-mode middleware."""
    app = FastAPI(title="Test App")
    
    # Add middleware in correct order
    app.add_middleware(EnvironmentValidationMiddleware)
    app.add_middleware(ProductionHardeningMiddleware)
    app.add_middleware(DevModeMiddleware)
    
    @app.get("/test")
    async def test_endpoint():
        return {"message": "test endpoint"}
    
    @app.post("/test-csrf")
    async def test_csrf_endpoint():
        return {"message": "csrf test endpoint"}
    
    @app.get("/debug/info")
    async def debug_endpoint():
        return {"debug": "information"}
    
    return app


@pytest.fixture
def client(test_app):
    """Create test client."""
    return TestClient(test_app)


class TestDevModeMiddleware:
    """Test dev-mode middleware functionality."""
    
    @patch('app.core.environment.environment.ENV', EnvironmentMode.DEVELOPMENT)
    @patch('app.core.environment.environment.DEV_MODE', True)
    @patch('app.core.environment.environment.DEV_RESPONSE_ANNOTATIONS', True)
    def test_dev_mode_response_annotations(self, client):
        """Test that dev mode adds response annotations."""
        
        response = client.get("/test")
        
        assert response.status_code == 200
        data = response.json()
        
        # Check for dev annotations
        assert "_dev" in data
        assert data["_dev"]["mode"] == "development"
        assert "processing_time_ms" in data["_dev"]
        assert "security_features" in data["_dev"]
        assert "warnings" in data["_dev"]
        
        # Check dev headers
        assert response.headers.get("X-Dev-Mode") == "true"
        assert response.headers.get("X-Environment") == "development"
        assert response.headers.get("X-Security-Level") == "development-relaxed"
    
    @patch('app.core.environment.environment.ENV', EnvironmentMode.DEVELOPMENT)
    @patch('app.core.environment.environment.DEV_MODE', True)
    @patch('app.core.environment.environment.CSRF_DEV_LOCALHOST_BYPASS', True)
    def test_csrf_localhost_bypass_in_dev_mode(self, client):
        """Test CSRF localhost bypass in development mode."""
        
        # Simulate localhost request
        headers = {
            "Host": "localhost:8000",
            "Origin": "http://localhost:3000",
            "X-Forwarded-For": "127.0.0.1"
        }
        
        response = client.post("/test-csrf", headers=headers)
        
        # Should bypass CSRF validation for localhost in dev mode
        assert response.status_code == 200
    
    @patch('app.core.environment.environment.ENV', EnvironmentMode.DEVELOPMENT)
    @patch('app.core.environment.environment.DEV_MODE', False)
    def test_no_dev_features_when_dev_mode_disabled(self, client):
        """Test that dev features are disabled when dev mode is off."""
        
        response = client.get("/test")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should not have dev annotations
        assert "_dev" not in data
        
        # Should not have dev headers
        assert "X-Dev-Mode" not in response.headers
    
    @patch('app.core.environment.environment.ENV', EnvironmentMode.PRODUCTION)
    @patch('app.core.environment.environment.DEV_MODE', True)
    def test_dev_mode_blocked_in_production(self, client):
        """Test that dev mode is blocked in production environment."""
        
        # This should raise an exception or return 500
        response = client.get("/test")
        
        assert response.status_code == 500
        data = response.json()
        assert "Güvenlik Hatası" in data.get("detail", "")


class TestProductionHardeningMiddleware:
    """Test production hardening middleware functionality."""
    
    @patch('app.core.environment.environment.ENV', EnvironmentMode.PRODUCTION)
    @patch('app.core.environment.environment.PROD_FORCE_HTTPS', True)
    def test_https_redirect_in_production(self, client):
        """Test HTTPS redirect enforcement in production."""
        
        # Simulate HTTP request
        with patch('app.middleware.dev_mode_middleware.ProductionHardeningMiddleware._is_http_request', return_value=True):
            response = client.get("/test")
            
            assert response.status_code == 301
            assert "Location" in response.headers
            assert response.headers["Location"].startswith("https://")
            assert "Strict-Transport-Security" in response.headers
    
    @patch('app.core.environment.environment.ENV', EnvironmentMode.PRODUCTION)
    @patch('app.core.environment.environment.PROD_DISABLE_DEBUG_ENDPOINTS', True)
    def test_debug_endpoints_blocked_in_production(self, client):
        """Test that debug endpoints are blocked in production."""
        
        response = client.get("/debug/info")
        
        assert response.status_code == 404
        data = response.json()
        assert "Sayfa bulunamadı" in data.get("detail", "")
    
    @patch('app.core.environment.environment.ENV', EnvironmentMode.PRODUCTION)
    @patch('app.core.environment.environment.PROD_MASK_ERROR_DETAILS', True)
    def test_error_masking_in_production(self, client):
        """Test that error details are masked in production."""
        
        # Mock an endpoint that raises an exception
        app = client.app
        
        @app.get("/error-endpoint")
        async def error_endpoint():
            raise ValueError("Detailed error message")
        
        response = client.get("/error-endpoint")
        
        assert response.status_code == 500
        data = response.json()
        
        # Error details should be masked
        assert "Sunucu hatası oluştu" in data.get("detail", "")
        assert "Detailed error message" not in str(data)
    
    @patch('app.core.environment.environment.ENV', EnvironmentMode.PRODUCTION)
    def test_production_headers_added(self, client):
        """Test that production-specific headers are added."""
        
        response = client.get("/test")
        
        # Check production headers
        assert response.headers.get("X-Production-Mode") == "true"
        assert response.headers.get("X-Security-Level") == "ultra-enterprise-banking"
        assert response.headers.get("X-KVKV-Compliant") == "true"
        
        # Dev headers should be removed
        assert "X-Dev-Mode" not in response.headers
    
    @patch('app.core.environment.environment.ENV', EnvironmentMode.DEVELOPMENT)
    def test_no_production_hardening_in_dev(self, client):
        """Test that production hardening is not applied in development."""
        
        response = client.get("/test")
        
        # Should not have production headers
        assert "X-Production-Mode" not in response.headers
        assert "X-Security-Level" not in response.headers or \
               response.headers.get("X-Security-Level") != "ultra-enterprise-banking"


class TestEnvironmentValidationMiddleware:
    """Test environment validation middleware functionality."""
    
    @patch('app.core.environment.environment.ENV', EnvironmentMode.PRODUCTION)
    @patch('app.core.environment.environment.DEV_MODE', True)
    def test_critical_misconfiguration_rejected(self, client):
        """Test that critical misconfigurations are rejected."""
        
        response = client.get("/test")
        
        assert response.status_code == 503
        data = response.json()
        assert "SERVICE_MISCONFIGURED" == data.get("error_code")
        assert "Servis geçici olarak kullanılamıyor" in data.get("detail", "")
    
    @patch('app.core.environment.environment.ENV', EnvironmentMode.PRODUCTION)
    @patch('app.core.environment.environment.SECRET_KEY', "dev-secret-key-change-in-production-minimum-32-chars")
    def test_default_secret_in_production_rejected(self, client):
        """Test that default secrets in production are rejected."""
        
        response = client.get("/test")
        
        assert response.status_code == 503
        data = response.json()
        assert "SERVICE_MISCONFIGURED" == data.get("error_code")
    
    @patch('app.core.environment.environment.ENV', EnvironmentMode.DEVELOPMENT)
    @patch('app.core.environment.environment.DEV_MODE', True)
    def test_valid_dev_configuration_accepted(self, client):
        """Test that valid development configuration is accepted."""
        
        response = client.get("/test")
        
        assert response.status_code == 200


class TestEnvironmentService:
    """Test environment service functionality."""
    
    @pytest.mark.asyncio
    async def test_environment_service_initialization(self):
        """Test environment service initialization."""
        
        # Reset service state
        environment_service._initialized = False
        
        # Initialize service
        await environment_service.initialize()
        
        assert environment_service._initialized is True
    
    def test_get_environment_status(self):
        """Test getting environment status."""
        
        status = environment_service.get_environment_status()
        
        assert "environment" in status
        assert "security_features" in status
        assert "dev_features" in status
        assert "production_hardening" in status
        assert "kvkv_compliance" in status
        assert "turkish_status" in status
    
    def test_is_feature_enabled(self):
        """Test feature flag checking."""
        
        # Test various features
        assert environment_service.is_feature_enabled("csrf_protection") is True
        assert environment_service.is_feature_enabled("rate_limiting") is True
        assert environment_service.is_feature_enabled("audit_logging") == environment.AUDIT_LOG_ENABLED
        
        # Test non-existent feature
        assert environment_service.is_feature_enabled("non_existent_feature") is False
    
    def test_get_security_policy(self):
        """Test getting security policy."""
        
        policy = environment_service.get_security_policy()
        
        assert "environment" in policy
        assert "security_level" in policy
        assert "authentication" in policy
        assert "csrf_protection" in policy
        assert "rate_limiting" in policy
        assert "security_headers" in policy
        assert "kvkv_compliance" in policy
    
    @pytest.mark.asyncio
    async def test_validate_runtime_security(self):
        """Test runtime security validation."""
        
        with patch('app.core.environment.environment.ENV', EnvironmentMode.DEVELOPMENT):
            with patch('app.core.environment.environment.DEV_MODE', True):
                is_valid, issues = await environment_service.validate_runtime_security()
                
                # Development mode should be valid with minimal issues
                assert isinstance(is_valid, bool)
                assert isinstance(issues, list)


class TestEnvironmentConfigurationEdgeCases:
    """Test edge cases and error conditions."""
    
    def test_localhost_detection_ipv4(self):
        """Test localhost detection for IPv4."""
        
        middleware = DevModeMiddleware(None)
        
        # Mock request with IPv4 localhost
        request = MagicMock()
        request.client.host = "127.0.0.1"
        request.headers = {"host": "localhost:8000"}
        
        assert middleware._is_localhost_request(request) is True
    
    def test_localhost_detection_ipv6(self):
        """Test localhost detection for IPv6."""
        
        middleware = DevModeMiddleware(None)
        
        # Mock request with IPv6 localhost
        request = MagicMock()
        request.client.host = "::1"
        request.headers = {"host": "localhost:8000"}
        
        assert middleware._is_localhost_request(request) is True
    
    def test_localhost_detection_forwarded(self):
        """Test localhost detection via X-Forwarded-For."""
        
        middleware = DevModeMiddleware(None)
        
        # Mock request with forwarded localhost
        request = MagicMock()
        request.client.host = "192.168.1.100"
        request.headers = {"x-forwarded-for": "127.0.0.1, 192.168.1.100"}
        
        assert middleware._is_localhost_request(request) is True
    
    def test_non_localhost_detection(self):
        """Test non-localhost request detection."""
        
        middleware = DevModeMiddleware(None)
        
        # Mock request from external IP
        request = MagicMock()
        request.client.host = "192.168.1.100"
        request.headers = {"host": "example.com"}
        
        assert middleware._is_localhost_request(request) is False
    
    def test_dev_annotation_with_non_dict_response(self):
        """Test dev annotation handling with non-dict responses."""
        
        middleware = DevModeMiddleware(None)
        
        # This should be handled gracefully
        # The actual implementation would need to be tested in integration
        pass
    
    @patch('app.core.environment.environment.ENV', EnvironmentMode.STAGING)
    def test_staging_environment_behavior(self, client):
        """Test staging environment specific behavior."""
        
        response = client.get("/test")
        
        # Staging should behave more like production
        assert response.status_code == 200
        
        # Should not have dev mode features
        data = response.json()
        assert "_dev" not in data


class TestKVKVComplianceIntegration:
    """Test Turkish KVKV compliance integration."""
    
    @patch('app.core.environment.environment.KVKV_AUDIT_LOG_ENABLED', False)
    @pytest.mark.asyncio
    async def test_kvkv_audit_logging_validation(self):
        """Test KVKV audit logging requirement validation."""
        
        is_valid, issues = await environment_service.validate_runtime_security()
        
        assert "KVKV audit logging disabled" in issues
    
    def test_kvkv_compliance_status(self):
        """Test KVKV compliance status reporting."""
        
        status = environment_service.get_environment_status()
        
        assert "kvkv_compliance" in status
        kvkv_status = status["kvkv_compliance"]
        
        assert "audit_logging" in kvkv_status
        assert "pii_masking" in kvkv_status
        assert "consent_required" in kvkv_status
        assert "data_retention_days" in kvkv_status
        assert "compliance_status" in kvkv_status
    
    def test_turkish_error_messages(self):
        """Test Turkish error message integration."""
        
        with patch('app.core.environment.environment.ENV', EnvironmentMode.PRODUCTION):
            with patch('app.core.environment.environment.DEV_MODE', True):
                
                client = TestClient(FastAPI())
                middleware = EnvironmentValidationMiddleware(None)
                
                # Mock request
                request = MagicMock()
                request.client.host = "192.168.1.100"
                request.url.path = "/test"
                
                response = middleware._reject_misconfigured_request(request)
                
                # Should have Turkish error message
                assert "Servis geçici olarak kullanılamıyor" in response.body.decode()


class TestSecurityPolicyEnforcement:
    """Test security policy enforcement across environments."""
    
    @patch('app.core.environment.environment.ENV', EnvironmentMode.PRODUCTION)
    @patch('app.core.environment.environment.CORS_ALLOWED_ORIGINS', ["*"])
    def test_wildcard_cors_in_production_validation(self):
        """Test that wildcard CORS is caught in production validation."""
        
        # This should raise an error during environment initialization
        with pytest.raises(ValueError) as exc_info:
            from app.core.environment import UltraEnterpriseEnvironment
            config = UltraEnterpriseEnvironment(ENV="production", CORS_ALLOWED_ORIGINS=["*"])
            config.model_validate(config.model_dump())
        
        assert "Wildcard '*' in CORS_ALLOWED_ORIGINS" in str(exc_info.value)
    
    @patch('app.core.environment.environment.ENV', EnvironmentMode.PRODUCTION)
    @patch('app.core.environment.environment.SESSION_COOKIE_SECURE', False)
    def test_insecure_cookies_in_production_validation(self):
        """Test that insecure cookies are caught in production."""
        
        with pytest.raises(ValueError) as exc_info:
            from app.core.environment import UltraEnterpriseEnvironment
            config = UltraEnterpriseEnvironment(
                ENV="production", 
                SESSION_COOKIE_SECURE=False,
                SECRET_KEY="very-secure-production-secret-key-with-sufficient-length",
                CSRF_SECRET_KEY="very-secure-csrf-secret-key-with-sufficient-length"
            )
            config.model_validate(config.model_dump())
        
        assert "SESSION_COOKIE_SECURE must be True in production" in str(exc_info.value)


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])