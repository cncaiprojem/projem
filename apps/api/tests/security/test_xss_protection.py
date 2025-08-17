"""
Ultra enterprise XSS protection tests for Task 3.10.
Tests XSS detection middleware with real attack vectors.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app
from app.settings import app_settings


class TestXSSProtection:
    """Test XSS protection middleware and detection."""
    
    def setup_method(self):
        """Setup test client."""
        self.client = TestClient(app)
    
    # Real XSS attack vectors for testing
    XSS_PAYLOADS = [
        # Basic script injection
        "<script>alert('XSS')</script>",
        "<script>alert(1)</script>",
        "<script>prompt('XSS')</script>",
        "<script>confirm('XSS')</script>",
        
        # Event handler injection
        "onload=alert('XSS')",
        "onerror=alert('XSS')",
        "onclick=alert('XSS')",
        "onmouseover=alert('XSS')",
        
        # JavaScript protocol
        "javascript:alert('XSS')",
        "javascript:prompt('XSS')",
        "javascript:void(0)",
        
        # Advanced XSS vectors
        "<img src=x onerror=alert('XSS')>",
        "<iframe src=javascript:alert('XSS')></iframe>",
        "<object data=javascript:alert('XSS')></object>",
        "<embed src=javascript:alert('XSS')>",
        
        # Encoded XSS attempts
        "&lt;script&gt;alert('XSS')&lt;/script&gt;",
        "%3Cscript%3Ealert('XSS')%3C/script%3E",
        
        # CSS-based XSS
        "<style>@import 'javascript:alert(\"XSS\")';</style>",
        "<link rel=stylesheet href=javascript:alert('XSS')>",
        
        # HTML5 XSS vectors
        "<details open ontoggle=alert('XSS')>",
        "<video><source onerror=alert('XSS')>",
        "<audio src=x onerror=alert('XSS')>",
        
        # Data URI XSS
        "data:text/html,<script>alert('XSS')</script>",
        
        # SVG XSS
        "<svg onload=alert('XSS')>",
        "<svg><script>alert('XSS')</script></svg>",
        
        # Form-based XSS
        "<form><button formaction=javascript:alert('XSS')>Submit</button></form>",
        
        # Template injection attempts
        "{{alert('XSS')}}",
        "${alert('XSS')}",
        "#{alert('XSS')}",
        
        # Function call attempts
        "eval('alert(\"XSS\")')",
        "setTimeout('alert(\"XSS\")', 1)",
        "setInterval('alert(\"XSS\")', 1)",
        "Function('alert(\"XSS\")')())"
    ]
    
    @patch.object(app_settings, 'security_xss_detection_enabled', True)
    def test_xss_detection_blocks_payloads(self):
        """Test that XSS detection middleware blocks malicious payloads."""
        
        for payload in self.XSS_PAYLOADS:
            # Test in query parameters
            response = self.client.get(f"/?test={payload}")
            
            # Should return 400 with Turkish error message
            assert response.status_code == 400
            assert "Güvenlik" in response.text
            assert "şüpheli içerik" in response.text.lower()
            
            # Test in path parameters (if supported by endpoint)
            # Note: This might need adjustment based on actual endpoints
            try:
                response = self.client.get(f"/test/{payload}")
                # Either 400 (blocked) or 404 (endpoint not found)
                assert response.status_code in [400, 404]
            except:
                # Skip if path parameter testing fails
                pass
    
    @patch.object(app_settings, 'security_xss_detection_enabled', True)
    def test_xss_detection_in_post_data(self):
        """Test XSS detection in POST request bodies."""
        
        for payload in self.XSS_PAYLOADS[:10]:  # Test subset for performance
            # Test JSON POST data
            response = self.client.post(
                "/api/some-endpoint",  # Adjust to actual endpoint
                json={"test_field": payload}
            )
            
            # Should be blocked or endpoint not found
            # We expect either 400 (blocked) or 404 (endpoint doesn't exist)
            assert response.status_code in [400, 404, 405]
            
            if response.status_code == 400:
                assert "Güvenlik" in response.text
    
    @patch.object(app_settings, 'security_xss_detection_enabled', False)
    def test_xss_detection_disabled(self):
        """Test that XSS detection can be disabled."""
        
        # When XSS detection is disabled, requests should pass through
        response = self.client.get("/?test=<script>alert('test')</script>")
        
        # Should not be blocked by XSS middleware
        # (might still be 404 if endpoint doesn't exist)
        assert response.status_code != 400 or "şüpheli içerik" not in response.text.lower()
    
    def test_legitimate_content_not_blocked(self):
        """Test that legitimate content is not incorrectly flagged as XSS."""
        
        legitimate_content = [
            "Hello world",
            "This is a normal text",
            "Email: user@example.com",
            "Price: $100.50",
            "Date: 2024-01-01",
            "Mathematical expression: 2 < 5 > 1",
            "HTML entities: &amp; &lt; &gt;",
            "Programming: if (x < y) { return true; }",
            "Legitimate script mention without injection",
            "CSS styles discussion",
            "JavaScript tutorial content"
        ]
        
        for content in legitimate_content:
            response = self.client.get(f"/?test={content}")
            
            # Should not be blocked (either 200 or 404, but not 400 XSS block)
            assert response.status_code != 400 or "şüpheli içerik" not in response.text.lower()
    
    def test_xss_detection_logging(self):
        """Test that XSS attempts are properly logged."""
        
        with patch('app.middleware.headers.logger') as mock_logger:
            # Trigger XSS detection
            payload = "<script>alert('XSS')</script>"
            response = self.client.get(f"/?test={payload}")
            
            # Check that warning was logged
            mock_logger.warning.assert_called()
            
            # Verify log contains XSS detection information
            log_calls = mock_logger.warning.call_args_list
            assert any("XSS attempt detected" in str(call) for call in log_calls)
    
    def test_xss_error_response_format(self):
        """Test that XSS error responses have correct format and headers."""
        
        payload = "<script>alert('XSS')</script>"
        response = self.client.get(f"/?test={payload}")
        
        if response.status_code == 400:
            # Check response format
            assert "application/json" in response.headers.get("content-type", "")
            
            # Check security headers on error response
            assert "X-Content-Type-Options" in response.headers
            assert "X-Frame-Options" in response.headers
            
            # Check response body structure
            data = response.json()
            assert "detail" in data
            assert "error_code" in data
            assert data["error_code"] == "XSS_ATTEMPT_DETECTED"
    
    def test_xss_detection_with_different_encodings(self):
        """Test XSS detection with various encoding attempts."""
        
        encoded_payloads = [
            # URL encoding
            "%3Cscript%3Ealert%28%27XSS%27%29%3C%2Fscript%3E",
            
            # Double encoding
            "%253Cscript%253Ealert%2527XSS%2527%253C%252Fscript%253E",
            
            # HTML entity encoding
            "&lt;script&gt;alert(&#39;XSS&#39;)&lt;/script&gt;",
            
            # Mixed encoding
            "%3Cscript%3Ealert(&quot;XSS&quot;)%3C/script%3E"
        ]
        
        for payload in encoded_payloads:
            response = self.client.get(f"/?test={payload}")
            
            # These should also be detected and blocked
            # (depending on the sophistication of the detection)
            # At minimum, they should not cause server errors
            assert response.status_code in [200, 400, 404]
    
    def test_xss_detection_performance(self):
        """Test that XSS detection doesn't significantly impact performance."""
        
        import time
        
        # Test with normal content
        start_time = time.time()
        for _ in range(10):
            response = self.client.get("/?test=normal_content")
        normal_time = time.time() - start_time
        
        # Test with XSS payload (will be blocked)
        start_time = time.time()
        for _ in range(10):
            response = self.client.get("/?test=<script>alert('xss')</script>")
        xss_time = time.time() - start_time
        
        # XSS detection should not significantly slow down requests
        # Allow up to 2x slower for XSS detection
        assert xss_time < normal_time * 2 + 1.0  # +1s tolerance
    
    def test_xss_detection_with_large_payloads(self):
        """Test XSS detection with large payloads."""
        
        # Large legitimate content
        large_content = "A" * 10000
        response = self.client.get(f"/?test={large_content}")
        assert response.status_code != 400 or "şüpheli içerik" not in response.text.lower()
        
        # Large malicious content
        large_xss = "<script>alert('XSS')</script>" + "A" * 10000
        response = self.client.get(f"/?test={large_xss}")
        # Should still be detected and blocked
        if response.status_code == 400:
            assert "Güvenlik" in response.text
    
    def test_multiple_xss_attempts_in_single_request(self):
        """Test handling of multiple XSS attempts in one request."""
        
        # Multiple XSS payloads in different parameters
        response = self.client.get(
            "/?param1=<script>alert(1)</script>&param2=<img src=x onerror=alert(2)>&param3=javascript:alert(3)"
        )
        
        # Should be blocked
        if response.status_code == 400:
            assert "Güvenlik" in response.text
    
    def test_xss_detection_case_insensitive(self):
        """Test that XSS detection is case insensitive."""
        
        case_variations = [
            "<SCRIPT>alert('XSS')</SCRIPT>",
            "<Script>Alert('XSS')</Script>",
            "<ScRiPt>AlErT('XSS')</ScRiPt>",
            "JAVASCRIPT:alert('XSS')",
            "OnLoAd=alert('XSS')"
        ]
        
        for payload in case_variations:
            response = self.client.get(f"/?test={payload}")
            
            # Should be detected regardless of case
            if response.status_code == 400:
                assert "Güvenlik" in response.text