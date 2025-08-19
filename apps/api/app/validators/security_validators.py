"""
Ultra enterprise security validators for Pydantic schemas.
Provides automatic input sanitization and validation.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationInfo, field_validator
from pydantic_core import ValidationError

from ..core.logging import get_logger
from ..services.input_sanitization_service import input_sanitization_service

logger = get_logger(__name__)


class SecurityValidationError(ValidationError):
    """Custom validation error for security violations."""
    pass


def sanitize_text_field(value: Any) -> str:
    """Pydantic validator for text fields requiring sanitization.
    
    Args:
        value: Input value to sanitize
        
    Returns:
        Sanitized text value
        
    Raises:
        ValueError: If input contains security threats
    """
    if value is None:
        return ""

    if not isinstance(value, str):
        value = str(value)

    # Perform comprehensive validation
    result = input_sanitization_service.comprehensive_validate(value)

    # Log security threats if detected
    if not result["is_safe"]:
        logger.warning(
            "Security threat detected in text input",
            extra={
                'operation': 'input_validation_failed',
                'threats': result["threats"],
                'input_length': result["input_length"]
            }
        )

        # Generate Turkish error message
        error_message = input_sanitization_service.get_security_error_message(result["threats"])
        raise ValueError(error_message)

    # Return sanitized value
    return result["sanitized"]


def sanitize_html_field(value: Any) -> str:
    """Pydantic validator for HTML content fields.
    
    Args:
        value: Input value to sanitize
        
    Returns:
        HTML-escaped text value
        
    Raises:
        ValueError: If input contains XSS threats
    """
    if value is None:
        return ""

    if not isinstance(value, str):
        value = str(value)

    # Check specifically for XSS
    xss_result = input_sanitization_service.validate_against_xss(value)

    if not xss_result["is_safe"]:
        logger.warning(
            "XSS threat detected in HTML input",
            extra={
                'operation': 'xss_validation_failed',
                'threats': xss_result["threats"],
                'input_length': len(value)
            }
        )

        raise ValueError("Güvenlik: HTML içeriğinde XSS tehdidi tespit edildi.")

    # Return HTML-escaped content
    return input_sanitization_service.sanitize_html(value)


def sanitize_filename_field(value: Any) -> str:
    """Pydantic validator for filename fields.
    
    Args:
        value: Filename to sanitize
        
    Returns:
        Sanitized filename
    """
    if value is None:
        return "file"

    if not isinstance(value, str):
        value = str(value)

    return input_sanitization_service.sanitize_filename(value)


def validate_url_field(value: Any) -> str:
    """Pydantic validator for URL fields.
    
    Args:
        value: URL to validate
        
    Returns:
        Validated URL
        
    Raises:
        ValueError: If URL is invalid or dangerous
    """
    if value is None:
        raise ValueError("URL gereklidir")

    if not isinstance(value, str):
        value = str(value)

    sanitized_url = input_sanitization_service.sanitize_url(value)

    if sanitized_url is None:
        raise ValueError("Güvenlik: Geçersiz veya güvenli olmayan URL")

    return sanitized_url


def validate_sql_safe_field(value: Any) -> str:
    """Pydantic validator for fields that need SQL injection protection.
    
    Args:
        value: Input value to check for SQL injection
        
    Returns:
        Sanitized value if safe
        
    Raises:
        ValueError: If SQL injection patterns detected
    """
    if value is None:
        return ""

    if not isinstance(value, str):
        value = str(value)

    # Check for SQL injection patterns
    sql_result = input_sanitization_service.validate_against_sql_injection(value)

    if not sql_result["is_safe"]:
        logger.warning(
            "SQL injection threat detected",
            extra={
                'operation': 'sql_injection_validation_failed',
                'threats': sql_result["threats"],
                'input_length': len(value)
            }
        )

        raise ValueError("Güvenlik: Potansiyel SQL enjeksiyonu tespit edildi.")

    # Return sanitized value
    return input_sanitization_service.sanitize_text_input(value)


class SecurityValidatorMixin:
    """Mixin class for Pydantic models requiring security validation."""

    @field_validator('*', mode='before')
    @classmethod
    def validate_all_fields(cls, value: Any, info: ValidationInfo) -> Any:
        """Apply security validation to all string fields."""
        field_name = info.field_name

        # Skip validation for certain system fields
        if field_name in ['id', 'created_at', 'updated_at', 'password_hash']:
            return value

        # Apply text sanitization to string fields
        if isinstance(value, str) and len(value) > 0:
            # Basic sanitization for all text fields
            result = input_sanitization_service.comprehensive_validate(value)

            # Log but don't block non-critical fields
            if not result["is_safe"]:
                threat_types = [threat["type"] for threat in result["threats"]]

                # Block critical threats
                if any(threat in ["XSS", "SQL_INJECTION"] for threat in threat_types):
                    logger.warning(
                        f"Critical security threat in field '{field_name}'",
                        extra={
                            'operation': 'critical_threat_blocked',
                            'field': field_name,
                            'threats': result["threats"]
                        }
                    )

                    error_message = input_sanitization_service.get_security_error_message(result["threats"])
                    raise ValueError(f"{field_name}: {error_message}")

                # Log non-critical threats but allow
                else:
                    logger.info(
                        f"Non-critical security pattern in field '{field_name}'",
                        extra={
                            'operation': 'non_critical_threat_logged',
                            'field': field_name,
                            'threats': result["threats"]
                        }
                    )

            # Return sanitized value for safety
            return result["sanitized"]

        return value


# Common validator functions for specific use cases
class CommonValidators:
    """Collection of common security validators."""

    @staticmethod
    def user_input_text(value: str) -> str:
        """Validate user-generated text content."""
        return sanitize_text_field(value)

    @staticmethod
    def user_input_html(value: str) -> str:
        """Validate user-generated HTML content."""
        return sanitize_html_field(value)

    @staticmethod
    def file_name(value: str) -> str:
        """Validate file names."""
        return sanitize_filename_field(value)

    @staticmethod
    def external_url(value: str) -> str:
        """Validate external URLs."""
        return validate_url_field(value)

    @staticmethod
    def database_query_param(value: str) -> str:
        """Validate database query parameters."""
        return validate_sql_safe_field(value)
