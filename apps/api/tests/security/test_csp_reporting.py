"""
Ultra enterprise CSP violation reporting tests for Task 3.10.
Tests CSP violation reporting endpoint and security event logging.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from sqlalchemy.orm import Session

from app.main import app
from app.models.security_event import SecurityEvent


class TestCSPReporting:
    """Test CSP violation reporting functionality."""
    
    def setup_method(self):
        """Setup test client."""
        self.client = TestClient(app)
    
    def test_csp_report_endpoint_exists(self):
        """Test that CSP reporting endpoint exists and accepts POST."""
        
        # Valid CSP report structure
        csp_report = {
            "csp-report": {
                "document-uri": "https://example.com/page",
                "referrer": "https://example.com/",
                "blocked-uri": "https://evil.com/malicious.js",
                "violated-directive": "script-src 'self'",
                "effective-directive": "script-src",
                "original-policy": "default-src 'self'; script-src 'self'",
                "disposition": "enforce",
                "status-code": 200
            }
        }
        
        response = self.client.post("/api/security/csp-report", json=csp_report)
        
        # Should accept the report (204 No Content)
        assert response.status_code == 204
    
    def test_csp_report_direct_format(self):
        """Test CSP reporting with direct format (no wrapper)."""
        
        # Some browsers send direct format
        csp_report = {
            "document-uri": "https://example.com/page",
            "referrer": "https://example.com/",
            "blocked-uri": "javascript:alert('xss')",
            "violated-directive": "script-src 'self'",
            "effective-directive": "script-src",
            "original-policy": "default-src 'self'; script-src 'self'",
            "disposition": "enforce",
            "status-code": 200
        }
        
        response = self.client.post("/api/security/csp-report", json=csp_report)
        assert response.status_code == 204
    
    def test_csp_report_logging(self):
        """Test that CSP violations are properly logged."""
        
        with patch('app.routers.security.logger') as mock_logger:
            csp_report = {
                "csp-report": {
                    "document-uri": "https://example.com/page",
                    "blocked-uri": "https://evil.com/malicious.js",
                    "violated-directive": "script-src 'self'",
                    "effective-directive": "script-src",
                    "original-policy": "default-src 'self'; script-src 'self'",
                    "disposition": "enforce"
                }
            }
            
            response = self.client.post("/api/security/csp-report", json=csp_report)
            assert response.status_code == 204
            
            # Verify logging was called
            mock_logger.warning.assert_called()
            
            # Check log content
            log_calls = mock_logger.warning.call_args_list
            assert any("CSP violation detected" in str(call) for call in log_calls)
    
    @patch('app.routers.security.get_db')
    def test_csp_report_database_storage(self, mock_get_db):
        """Test that CSP violations are stored in database."""
        
        # Mock database session
        mock_db = MagicMock(spec=Session)
        mock_get_db.return_value = mock_db
        
        csp_report = {
            "csp-report": {
                "document-uri": "https://example.com/page",
                "blocked-uri": "javascript:alert('xss')",
                "violated-directive": "script-src 'self'",
                "effective-directive": "script-src",
                "original-policy": "default-src 'self'; script-src 'self'"
            }
        }
        
        response = self.client.post("/api/security/csp-report", json=csp_report)
        assert response.status_code == 204
        
        # Verify database operations
        mock_db.add.assert_called()
        mock_db.commit.assert_called()
        
        # Check that a SecurityEvent was created
        added_event = mock_db.add.call_args[0][0]
        assert isinstance(added_event, SecurityEvent)
        assert added_event.type == "CSP_VIOLATION_REPORT"
    
    def test_suspicious_csp_violation_detection(self):
        """Test detection of suspicious CSP violations."""
        
        with patch('app.routers.security.logger') as mock_logger:
            # Suspicious CSP violation (javascript: protocol)
            suspicious_report = {
                "csp-report": {
                    "document-uri": "https://example.com/page",
                    "blocked-uri": "javascript:alert('xss')",
                    "violated-directive": "script-src 'self'",
                    "effective-directive": "script-src",
                    "original-policy": "default-src 'self'; script-src 'self'",
                    "script-sample": "<script>alert('xss')</script>"
                }
            }
            
            response = self.client.post("/api/security/csp-report", json=suspicious_report)
            assert response.status_code == 204
            
            # Should log as critical/suspicious
            log_calls = mock_logger.critical.call_args_list
            assert any("Suspicious CSP violation" in str(call) for call in log_calls)
    
    def test_csp_report_malformed_data(self):
        """Test handling of malformed CSP reports."""
        
        malformed_reports = [
            {},  # Empty report
            {"invalid": "data"},  # Wrong structure
            {"csp-report": {}},  # Empty CSP report
            {"csp-report": {"incomplete": "data"}},  # Missing required fields
        ]
        
        for malformed_report in malformed_reports:
            response = self.client.post("/api/security/csp-report", json=malformed_report)
            
            # Should handle gracefully (400 or 204)
            assert response.status_code in [204, 400]
    
    def test_csp_report_security_headers(self):
        """Test that CSP report responses include security headers."""
        
        csp_report = {
            "csp-report": {
                "document-uri": "https://example.com/page",
                "blocked-uri": "https://evil.com/script.js",
                "violated-directive": "script-src 'self'",
                "effective-directive": "script-src",
                "original-policy": "default-src 'self'; script-src 'self'"
            }
        }
        
        response = self.client.post("/api/security/csp-report", json=csp_report)
        
        # Response should include security headers
        assert "X-Content-Type-Options" in response.headers
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "X-Frame-Options" in response.headers
        assert response.headers["X-Frame-Options"] == "DENY"
    
    def test_xss_report_endpoint(self):
        """Test XSS detection reporting endpoint."""
        
        xss_report = {
            "url": "https://example.com/page",
            "payload": "<script>alert('xss')</script>",
            "detected_at": "2024-01-01T12:00:00Z"
        }
        
        response = self.client.post("/api/security/xss-report", json=xss_report)
        assert response.status_code == 204
    
    @patch('app.routers.security.get_db')
    def test_xss_report_database_storage(self, mock_get_db):
        """Test that XSS reports are stored in database."""
        
        mock_db = MagicMock(spec=Session)
        mock_get_db.return_value = mock_db
        
        xss_report = {
            "payload": "<script>alert('xss')</script>",
            "url": "https://example.com/vulnerable-page"
        }
        
        response = self.client.post("/api/security/xss-report", json=xss_report)
        assert response.status_code == 204
        
        # Verify database operations
        mock_db.add.assert_called()
        mock_db.commit.assert_called()
        
        # Check that a SecurityEvent was created
        added_event = mock_db.add.call_args[0][0]
        assert isinstance(added_event, SecurityEvent)
        assert added_event.type == "XSS_ATTEMPT_DETECTED"
    
    def test_csp_violation_analysis(self):
        """Test CSP violation threat analysis."""
        
        # Import the analysis function for direct testing
        from app.routers.security import _analyze_csp_violation
        from app.routers.security import CSPViolationReport
        
        # Test suspicious violation
        suspicious_report = CSPViolationReport(
            document_uri="https://example.com/page",
            blocked_uri="javascript:alert('xss')",
            violated_directive="script-src 'self'",
            effective_directive="script-src",
            original_policy="default-src 'self'",
            script_sample="<script>alert('xss')</script>"
        )
        
        analysis = _analyze_csp_violation(suspicious_report, "192.168.1.1", "Mozilla/5.0")
        
        assert analysis["is_suspicious"] is True
        assert len(analysis["indicators"]) > 0
        assert analysis["threat_level"] in ["medium", "high"]
        
        # Test normal violation
        normal_report = CSPViolationReport(
            document_uri="https://example.com/page",
            blocked_uri="https://fonts.googleapis.com/css",
            violated_directive="style-src 'self'",
            effective_directive="style-src",
            original_policy="default-src 'self'"
        )
        
        analysis = _analyze_csp_violation(normal_report, "192.168.1.1", "Mozilla/5.0")
        
        assert analysis["is_suspicious"] is False
        assert len(analysis["indicators"]) == 0
        assert analysis["threat_level"] == "low"
    
    def test_csp_report_rate_limiting(self):
        """Test that CSP reporting doesn't get rate limited inappropriately."""
        
        csp_report = {
            "csp-report": {
                "document-uri": "https://example.com/page",
                "blocked-uri": "https://fonts.googleapis.com/css",
                "violated-directive": "style-src 'self'",
                "effective-directive": "style-src",
                "original-policy": "default-src 'self'"
            }
        }
        
        # Send multiple reports rapidly
        for _ in range(10):
            response = self.client.post("/api/security/csp-report", json=csp_report)
            # Should not be rate limited (CSP reports are legitimate browser behavior)
            assert response.status_code == 204
    
    def test_csp_report_client_info_extraction(self):
        """Test extraction of client information from CSP reports."""
        
        with patch('app.routers.security.logger') as mock_logger:
            # Send CSP report with custom headers
            headers = {
                "User-Agent": "Mozilla/5.0 (Test Browser)",
                "X-Forwarded-For": "203.0.113.1"
            }
            
            csp_report = {
                "csp-report": {
                    "document-uri": "https://example.com/page",
                    "blocked-uri": "https://evil.com/script.js",
                    "violated-directive": "script-src 'self'",
                    "effective-directive": "script-src",
                    "original-policy": "default-src 'self'"
                }
            }
            
            response = self.client.post(
                "/api/security/csp-report", 
                json=csp_report,
                headers=headers
            )
            assert response.status_code == 204
            
            # Check that client info was logged
            log_calls = mock_logger.warning.call_args_list
            log_extras = [call.kwargs.get('extra', {}) for call in log_calls]
            
            # Should have captured user agent and client IP
            assert any('user_agent' in extra for extra in log_extras)
    
    def test_csp_report_error_handling(self):
        """Test error handling in CSP report processing."""
        
        # Test with invalid JSON
        response = self.client.post(
            "/api/security/csp-report",
            data="invalid json data",
            headers={"Content-Type": "application/json"}
        )
        
        # Should handle gracefully
        assert response.status_code in [400, 422]
        
        # Test with missing content-type
        response = self.client.post("/api/security/csp-report", data="data")
        assert response.status_code in [400, 422, 415]