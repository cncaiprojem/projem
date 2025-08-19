"""
Ultra enterprise security core module for FreeCAD CNC/CAM platform.
Implements banking-level security controls and CSP nonce generation.
"""

from __future__ import annotations

import secrets
import string
from typing import Dict, Optional


class SecurityManager:
    """Enterprise security manager for ultra-secure operations."""

    @staticmethod
    def generate_csp_nonce() -> str:
        """Generate cryptographically secure nonce for CSP.

        Returns:
            Base64-encoded 128-bit random nonce for CSP directives
        """
        # Generate 16 bytes (128 bits) of cryptographically secure random data
        # Convert to base64 for CSP usage
        return secrets.token_urlsafe(16)

    @staticmethod
    def get_enterprise_csp_policy(nonce: str, environment: str = "production") -> str:
        """Get ultra enterprise Content Security Policy.

        Args:
            nonce: CSP nonce for inline scripts/styles
            environment: Environment name (dev/production)

        Returns:
            Complete CSP policy string
        """
        base_policy = (
            f"default-src 'self'; "
            f"frame-ancestors 'none'; "
            f"object-src 'none'; "
            f"script-src 'self' 'nonce-{nonce}'; "
            f"style-src 'self' 'nonce-{nonce}'; "
            f"img-src 'self' data: https:; "
            f"connect-src 'self'; "
            f"font-src 'self'; "
            f"media-src 'self'; "
            f"worker-src 'none'; "
            f"base-uri 'self'; "
            f"form-action 'self'"
        )

        # Add development-specific policies for debugging
        if environment == "development":
            base_policy += (
                f"; script-src 'self' 'nonce-{nonce}' 'unsafe-eval'; connect-src 'self' ws: wss:"
            )

        return base_policy

    @staticmethod
    def get_enterprise_permissions_policy() -> str:
        """Get ultra enterprise Permissions Policy.

        Denies access to sensitive browser APIs by default.

        Returns:
            Complete Permissions-Policy header value
        """
        return (
            "camera=(), "
            "microphone=(), "
            "geolocation=(), "
            "payment=(), "
            "usb=(), "
            "accelerometer=(), "
            "gyroscope=(), "
            "magnetometer=(), "
            "fullscreen=(self), "
            "autoplay=(), "
            "encrypted-media=(), "
            "picture-in-picture=(), "
            "screen-wake-lock=(), "
            "web-share=()"
        )

    @staticmethod
    def get_enterprise_security_headers(
        nonce: str, environment: str = "production", hsts_enabled: bool = True
    ) -> Dict[str, str]:
        """Get complete set of ultra enterprise security headers.

        Args:
            nonce: CSP nonce for dynamic content
            environment: Environment name
            hsts_enabled: Whether HSTS should be enabled

        Returns:
            Dictionary of security headers
        """
        headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "X-XSS-Protection": "1; mode=block",
            "Cross-Origin-Embedder-Policy": "require-corp",
            "Cross-Origin-Opener-Policy": "same-origin",
            "Cross-Origin-Resource-Policy": "same-origin",
            "Content-Security-Policy": SecurityManager.get_enterprise_csp_policy(
                nonce, environment
            ),
            "Permissions-Policy": SecurityManager.get_enterprise_permissions_policy(),
        }

        # Add HSTS only if enabled and in production/staging
        if hsts_enabled and environment != "development":
            headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        return headers

    @staticmethod
    def is_suspicious_request(request_data: Dict) -> bool:
        """Detect potentially suspicious request patterns.

        Args:
            request_data: Request information dictionary

        Returns:
            True if request appears suspicious
        """
        # Common XSS patterns
        xss_patterns = [
            "<script",
            "</script>",
            "javascript:",
            "onload=",
            "onerror=",
            "onclick=",
            "onmouseover=",
            "alert(",
            "confirm(",
            "prompt(",
            "eval(",
            "setTimeout(",
            "setInterval(",
        ]

        # Check for XSS patterns in common fields
        for field_name, field_value in request_data.items():
            if isinstance(field_value, str):
                value_lower = field_value.lower()
                for pattern in xss_patterns:
                    if pattern in value_lower:
                        return True

        return False

    @staticmethod
    def sanitize_html_input(input_text: str) -> str:
        """Basic HTML sanitization for text inputs.

        Args:
            input_text: Raw input text that may contain HTML

        Returns:
            Sanitized text with HTML entities escaped
        """
        if not isinstance(input_text, str):
            return str(input_text)

        # HTML entity escaping
        html_escape_table = {
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#x27;",
            "/": "&#x2F;",
        }

        escaped = input_text
        for char, escape in html_escape_table.items():
            escaped = escaped.replace(char, escape)

        return escaped

    @staticmethod
    def validate_input_safety(input_data: Dict) -> Dict[str, str]:
        """Validate input data for security issues.

        Args:
            input_data: Dictionary of input data to validate

        Returns:
            Dictionary of field names to error messages
        """
        errors = {}

        for field_name, field_value in input_data.items():
            if isinstance(field_value, str):
                # Check for common injection patterns
                if SecurityManager.is_suspicious_request({field_name: field_value}):
                    errors[field_name] = (
                        f"Güvenlik: '{field_name}' alanında şüpheli içerik tespit edildi"
                    )

                # Check for SQL injection patterns
                sql_patterns = ["'", '"', ";", "--", "/*", "*/", "xp_", "sp_"]
                value_lower = field_value.lower()
                for pattern in sql_patterns:
                    if (
                        pattern in value_lower and len(field_value) > 50
                    ):  # Only flag on longer inputs
                        errors[field_name] = (
                            f"Güvenlik: '{field_name}' alanında potansiyel SQL enjeksiyonu"
                        )
                        break

        return errors


# Global security manager instance
security_manager = SecurityManager()
