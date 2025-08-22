"""
Error Taxonomy for Task 6.2 - Retry Strategy Implementation
Defines error classes and classification for retry vs DLQ handling.

This module provides:
- Custom exception classes for different error types
- Classification functions for retry decision-making
- Error categorization for proper DLQ routing
"""

from __future__ import annotations

from typing import Type, Union
import traceback


class RetryableError(Exception):
    """Base class for errors that should be retried."""
    def __init__(self, message: str, retry_count: int = 0, max_retries: int = 5):
        super().__init__(message)
        self.retry_count = retry_count
        self.max_retries = max_retries


class TransientExternalError(RetryableError):
    """External service temporarily unavailable - should retry."""
    pass


class RateLimitedError(RetryableError):
    """Rate limited by external service - should retry with backoff."""
    def __init__(self, message: str, retry_after: int = None, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class NetworkError(RetryableError):
    """Network connectivity issues - should retry."""
    pass


class NonRetryableError(Exception):
    """Base class for errors that should not be retried."""
    pass


class ValidationError(NonRetryableError):
    """Input validation failed - no point in retrying."""
    pass


class UnauthorizedError(NonRetryableError):
    """Authentication/authorization failed - no point in retrying."""
    pass


class QuotaExceededError(NonRetryableError):
    """Resource quota exceeded - should not retry."""
    pass


class CancellationError(Exception):
    """Base class for cancellation-related errors."""
    pass


class JobCancelledError(CancellationError):
    """Job was cancelled - should not retry."""
    pass


class FatalError(Exception):
    """Base class for fatal errors that should go directly to DLQ."""
    pass


class IntegrityError(FatalError):
    """Data integrity violation - fatal, send to DLQ immediately."""
    pass


# Error classification mappings per Task 6.2 requirements
RETRYABLE_EXCEPTIONS = (
    TransientExternalError,
    RateLimitedError, 
    NetworkError,
    # Standard library exceptions that are typically retryable
    ConnectionError,
    TimeoutError,
    OSError,  # Includes network-related OS errors
)

NON_RETRYABLE_EXCEPTIONS = (
    ValidationError,
    UnauthorizedError,
    QuotaExceededError,
    ValueError,  # Input validation
    TypeError,   # Type errors usually indicate programming bugs
    KeyError,    # Missing required data
)

CANCELLATION_EXCEPTIONS = (
    JobCancelledError,
    KeyboardInterrupt,  # User cancellation
)

FATAL_EXCEPTIONS = (
    IntegrityError,
    MemoryError,       # System resource exhaustion
    SystemExit,        # System shutdown
)


def classify_error(exc: Union[Exception, Type[Exception]]) -> str:
    """
    Classify an exception for retry decision making.
    
    Args:
        exc: Exception instance or class to classify
        
    Returns:
        str: Error classification ('retryable', 'non_retryable', 'cancellation', 'fatal')
    """
    if isinstance(exc, type):
        exc_type = exc
    else:
        exc_type = type(exc)
    
    # Check in order of precedence
    if issubclass(exc_type, FATAL_EXCEPTIONS):
        return 'fatal'
    elif issubclass(exc_type, CANCELLATION_EXCEPTIONS):
        return 'cancellation'
    elif issubclass(exc_type, NON_RETRYABLE_EXCEPTIONS):
        return 'non_retryable'
    elif issubclass(exc_type, RETRYABLE_EXCEPTIONS):
        return 'retryable'
    else:
        # Default to non-retryable for unknown exceptions
        return 'non_retryable'


def should_retry_error(exc: Union[Exception, Type[Exception]]) -> bool:
    """
    Determine if an error should be retried.
    
    Args:
        exc: Exception instance or class
        
    Returns:
        bool: True if error should be retried, False otherwise
    """
    classification = classify_error(exc)
    return classification == 'retryable'


def get_error_metadata(exc: Exception) -> dict:
    """
    Extract metadata from an exception for logging and observability.
    
    Args:
        exc: Exception instance
        
    Returns:
        dict: Error metadata including type, message, and classification
    """
    return {
        'error_type': type(exc).__name__,
        'error_module': type(exc).__module__,
        'error_message': str(exc),
        'error_classification': classify_error(exc),
        'is_retryable': should_retry_error(exc),
        'traceback': traceback.format_exc() if exc.__traceback__ else None,
        # Additional metadata for specific error types
        'retry_after': getattr(exc, 'retry_after', None),
        'retry_count': getattr(exc, 'retry_count', None),
        'max_retries': getattr(exc, 'max_retries', None),
    }


