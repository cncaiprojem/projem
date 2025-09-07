"""
Utility functions for safe environment variable parsing.

This module provides robust error handling for environment variable parsing
to prevent application crashes from malformed configuration values.
"""

import os
from typing import Optional, TypeVar, Callable, Any
from ..core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


def safe_parse_env(
    env_var: str,
    default: T,
    parser: Callable[[str], T],
    validator: Optional[Callable[[T], bool]] = None,
    error_message: Optional[str] = None
) -> T:
    """
    Safely parse an environment variable with error handling and validation.
    
    Args:
        env_var: Environment variable name
        default: Default value if parsing fails or env var is not set
        parser: Function to parse the string value (e.g., int, float)
        validator: Optional validation function that returns True if value is valid
        error_message: Optional custom error message for logging
        
    Returns:
        Parsed value or default if parsing/validation fails
        
    Example:
        >>> threshold = safe_parse_env(
        ...     "MEMORY_THRESHOLD",
        ...     1610612736,
        ...     int,
        ...     lambda x: x > 0,
        ...     "Memory threshold must be positive"
        ... )
    """
    raw_value = os.getenv(env_var)
    
    if raw_value is None:
        return default
    
    try:
        parsed_value = parser(raw_value)
        
        # Validate if validator provided
        if validator and not validator(parsed_value):
            logger.warning(
                "Environment variable validation failed",
                env_var=env_var,
                raw_value=raw_value,
                parsed_value=parsed_value,
                error_message=error_message or "Validation failed",
                using_default=default
            )
            return default
            
        return parsed_value
        
    except (ValueError, TypeError, Exception) as e:
        logger.error(
            "Failed to parse environment variable",
            env_var=env_var,
            raw_value=raw_value,
            error=str(e),
            error_type=type(e).__name__,
            error_message=error_message,
            using_default=default
        )
        return default


def safe_parse_int(
    env_var: str,
    default: int,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
    error_message: Optional[str] = None
) -> int:
    """
    Safely parse an integer environment variable with range validation.
    
    Args:
        env_var: Environment variable name
        default: Default value if parsing fails
        min_value: Optional minimum allowed value
        max_value: Optional maximum allowed value
        error_message: Optional custom error message
        
    Returns:
        Parsed integer or default if parsing/validation fails
    """
    def validator(value: int) -> bool:
        if min_value is not None and value < min_value:
            return False
        if max_value is not None and value > max_value:
            return False
        return True
    
    return safe_parse_env(
        env_var=env_var,
        default=default,
        parser=int,
        validator=validator,
        error_message=error_message or f"Integer must be between {min_value} and {max_value}"
    )


def safe_parse_float(
    env_var: str,
    default: float,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    error_message: Optional[str] = None
) -> float:
    """
    Safely parse a float environment variable with range validation.
    
    Args:
        env_var: Environment variable name
        default: Default value if parsing fails
        min_value: Optional minimum allowed value
        max_value: Optional maximum allowed value
        error_message: Optional custom error message
        
    Returns:
        Parsed float or default if parsing/validation fails
    """
    def validator(value: float) -> bool:
        if min_value is not None and value < min_value:
            return False
        if max_value is not None and value > max_value:
            return False
        return True
    
    return safe_parse_env(
        env_var=env_var,
        default=default,
        parser=float,
        validator=validator,
        error_message=error_message or f"Float must be between {min_value} and {max_value}"
    )


def safe_parse_bool(
    env_var: str,
    default: bool,
    error_message: Optional[str] = None
) -> bool:
    """
    Safely parse a boolean environment variable.
    
    Recognizes: true/false, yes/no, 1/0, on/off (case insensitive)
    
    Args:
        env_var: Environment variable name
        default: Default value if parsing fails
        error_message: Optional custom error message
        
    Returns:
        Parsed boolean or default if parsing fails
    """
    raw_value = os.getenv(env_var)
    
    if raw_value is None:
        return default
    
    raw_lower = raw_value.lower().strip()
    
    if raw_lower in ('true', 'yes', '1', 'on'):
        return True
    elif raw_lower in ('false', 'no', '0', 'off'):
        return False
    else:
        logger.warning(
            "Invalid boolean environment variable",
            env_var=env_var,
            raw_value=raw_value,
            error_message=error_message or "Expected true/false, yes/no, 1/0, or on/off",
            using_default=default
        )
        return default


__all__ = [
    'safe_parse_env',
    'safe_parse_int',
    'safe_parse_float',
    'safe_parse_bool',
]