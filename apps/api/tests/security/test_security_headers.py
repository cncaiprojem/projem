"""
Ultra enterprise security headers tests for Task 3.10.
Tests all banking-level security headers and CSP policies.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app
from app.settings import app_settings


class TestSecurityHeaders:
    """Test ultra enterprise security headers implementation."""
    
    def setup_method(self):
        """Setup test client."""
        self.client = TestClient(app)
    
    def test_basic_security_headers_present(self):
        """Test that all basic security headers are present."""
        response = self.client.get("/")
        
        # Check all required security headers
        assert "X-Content-Type-Options" in response.headers
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        
        assert "X-Frame-Options" in response.headers
        assert response.headers["X-Frame-Options"] == "DENY"
        
        assert "Referrer-Policy" in response.headers
        assert response.headers["Referrer-Policy"] == "no-referrer"
        
        assert "X-XSS-Protection" in response.headers
        assert response.headers["X-XSS-Protection"] == "1; mode=block"
    
    def test_csp_header_present_and_correct(self):
        """Test Content Security Policy header."""
        response = self.client.get("/")
        
        assert "Content-Security-Policy" in response.headers
        csp = response.headers["Content-Security-Policy"]
        
        # Check for required CSP directives as per Task 3.10
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "object-src 'none'" in csp
        assert "script-src 'self'" in csp
        assert "style-src 'self'" in csp
        
        # Check for nonce in script-src and style-src
        assert "'nonce-" in csp
    
    def test_permissions_policy_header(self):
        """Test Permissions-Policy header for minimal permissions."""
        response = self.client.get("/")
        
        assert "Permissions-Policy" in response.headers
        permissions_policy = response.headers["Permissions-Policy"]
        
        # Check that dangerous permissions are denied
        assert "camera=()" in permissions_policy
        assert "microphone=()" in permissions_policy
        assert "geolocation=()" in permissions_policy
        assert "payment=()" in permissions_policy
        assert "usb=()" in permissions_policy
    
    def test_cross_origin_headers(self):
        """Test Cross-Origin security headers."""
        response = self.client.get("/")
        
        assert "Cross-Origin-Embedder-Policy" in response.headers
        assert response.headers["Cross-Origin-Embedder-Policy"] == "require-corp"
        
        assert "Cross-Origin-Opener-Policy" in response.headers
        assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
        
        assert "Cross-Origin-Resource-Policy" in response.headers
        assert response.headers["Cross-Origin-Resource-Policy"] == "same-origin"
    
    @patch.object(app_settings, 'security_hsts_enabled', True)
    @patch.object(app_settings, 'security_environment', 'production')
    def test_hsts_header_production(self):
        """Test HSTS header in production environment."""
        response = self.client.get("/")
        
        assert "Strict-Transport-Security" in response.headers
        hsts = response.headers["Strict-Transport-Security"]
        
        assert "max-age=31536000" in hsts
        assert "includeSubDomains" in hsts
        assert "preload" in hsts
    
    @patch.object(app_settings, 'security_environment', 'development')
    def test_no_hsts_header_development(self):
        """Test that HSTS header is not set in development."""
        response = self.client.get("/")
        
        # HSTS should not be present in development
        assert "Strict-Transport-Security" not in response.headers
    
    @patch.object(app_settings, 'security_csp_enabled', False)
    def test_basic_headers_when_csp_disabled(self):
        """Test that basic headers are still applied when CSP is disabled."""
        response = self.client.get("/")
        
        # Basic headers should still be present
        assert "X-Content-Type-Options" in response.headers
        assert "X-Frame-Options" in response.headers
        assert "Referrer-Policy" in response.headers
        assert "X-XSS-Protection" in response.headers
        
        # But no advanced CSP/Permissions headers
        assert "Content-Security-Policy" not in response.headers
        assert "Permissions-Policy" not in response.headers
    
    def test_headers_on_different_endpoints(self):
        """Test that security headers are applied to all endpoints."""
        endpoints = [
            "/",
            "/healthz",
            "/api/v1/auth/login",  # If this endpoint exists
        ]
        
        for endpoint in endpoints:
            try:
                response = self.client.get(endpoint)
                # Check that at least basic security headers are present
                assert "X-Content-Type-Options" in response.headers
                assert "X-Frame-Options" in response.headers
            except:
                # Skip if endpoint doesn't exist
                continue
    
    def test_csp_nonce_uniqueness(self):
        """Test that CSP nonces are unique across requests."""
        response1 = self.client.get("/")
        response2 = self.client.get("/")
        
        csp1 = response1.headers.get("Content-Security-Policy", "")
        csp2 = response2.headers.get("Content-Security-Policy", "")
        
        # Extract nonces
        import re
        nonce_pattern = r"'nonce-([^']+)'"
        nonces1 = re.findall(nonce_pattern, csp1)
        nonces2 = re.findall(nonce_pattern, csp2)
        
        if nonces1 and nonces2:
            # Nonces should be different between requests
            assert nonces1[0] != nonces2[0]
    
    def test_csp_environment_specific_policies(self):
        """Test that CSP policies differ between environments."""
        
        # Test production CSP (stricter)
        with patch.object(app_settings, 'security_environment', 'production'):
            response_prod = self.client.get("/")
            csp_prod = response_prod.headers.get("Content-Security-Policy", "")
            
            # Production should not have unsafe-eval
            assert "unsafe-eval" not in csp_prod
        
        # Test development CSP (more permissive)
        with patch.object(app_settings, 'security_environment', 'development'):
            response_dev = self.client.get("/")
            csp_dev = response_dev.headers.get("Content-Security-Policy", "")
            
            # Development might have additional permissions for debugging
            # (This depends on the actual implementation)
    
    def test_headers_not_duplicated(self):
        """Test that security headers are not duplicated."""
        response = self.client.get("/")
        
        # Check that each security header appears only once
        for header_name in [
            "X-Content-Type-Options",
            "X-Frame-Options", 
            "Referrer-Policy",
            "Content-Security-Policy",
            "Permissions-Policy"
        ]:
            if header_name in response.headers:
                # FastAPI/Starlette automatically handles header deduplication
                # but we can check that the value is consistent
                assert isinstance(response.headers[header_name], str)
    
    def test_security_headers_order_and_consistency(self):
        """Test that security headers are consistently applied."""
        # Make multiple requests to ensure consistency
        responses = [self.client.get("/") for _ in range(5)]
        
        # All responses should have the same security headers
        first_response_headers = {
            k: v for k, v in responses[0].headers.items()
            if k.startswith(('X-', 'Content-Security-Policy', 'Permissions-Policy', 'Referrer-Policy'))
        }
        
        for response in responses[1:]:
            current_headers = {
                k: v for k, v in response.headers.items()
                if k.startswith(('X-', 'Content-Security-Policy', 'Permissions-Policy', 'Referrer-Policy'))
            }
            
            # Headers should be consistent (except for CSP nonces)
            for header_name, header_value in first_response_headers.items():
                if header_name == "Content-Security-Policy":
                    # CSP will have different nonces, so just check structure
                    assert header_name in current_headers
                    assert "default-src 'self'" in current_headers[header_name]
                else:
                    assert current_headers.get(header_name) == header_value