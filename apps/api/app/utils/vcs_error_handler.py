"""
Error handling utilities for Version Control System API endpoints.

This module provides decorators and utilities for consistent error handling
across VCS API endpoints.
"""

import functools
import structlog
from typing import Callable, Optional, Type, Union
from fastapi import HTTPException, status

from app.services.model_version_control import ModelVersionControlError
from app.services.vcs_repository_registry import VCSRepositoryRegistryError
from app.services.model_branch_manager import BranchManagerError
from app.services.model_object_store import ObjectStoreError

logger = structlog.get_logger(__name__)


class VCSErrorHandler:
    """Centralized error handler for VCS operations."""
    
    @staticmethod
    def get_http_status(error: Exception) -> int:
        """
        Map exception types to HTTP status codes.
        
        Args:
            error: The exception to map
            
        Returns:
            HTTP status code
        """
        error_mapping = {
            ValueError: status.HTTP_400_BAD_REQUEST,
            KeyError: status.HTTP_404_NOT_FOUND,
            PermissionError: status.HTTP_403_FORBIDDEN,
            NotImplementedError: status.HTTP_501_NOT_IMPLEMENTED,
            VCSRepositoryRegistryError: status.HTTP_400_BAD_REQUEST,
            ModelVersionControlError: status.HTTP_400_BAD_REQUEST,
            BranchManagerError: status.HTTP_400_BAD_REQUEST,
            ObjectStoreError: status.HTTP_500_INTERNAL_SERVER_ERROR,
        }
        
        for error_type, status_code in error_mapping.items():
            if isinstance(error, error_type):
                return status_code
        
        return status.HTTP_500_INTERNAL_SERVER_ERROR
    
    @staticmethod
    def format_error_detail(error: Exception) -> dict:
        """
        Format error details for API response.
        
        Args:
            error: The exception to format
            
        Returns:
            Formatted error detail dictionary
        """
        # Check if error has custom fields (code, message, turkish_message)
        if hasattr(error, 'code') and hasattr(error, 'message'):
            detail = {
                "code": error.code,
                "message": error.message
            }
            if hasattr(error, 'turkish_message'):
                detail["turkish_message"] = error.turkish_message
            return detail
        
        # Default formatting
        return {
            "code": "vcs.error",
            "message": str(error),
            "type": type(error).__name__
        }


def handle_vcs_errors(
    operation: Optional[str] = None,
    log_errors: bool = True,
    default_status: int = status.HTTP_500_INTERNAL_SERVER_ERROR
):
    """
    Decorator for handling VCS-related errors in API endpoints.
    
    Args:
        operation: Optional operation name for logging
        log_errors: Whether to log errors
        default_status: Default HTTP status for unhandled errors
        
    Usage:
        @handle_vcs_errors(operation="repository_init")
        async def init_repository(...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
                
            except (VCSRepositoryRegistryError, ModelVersionControlError, BranchManagerError) as e:
                # Known VCS errors with structured format
                if log_errors:
                    logger.error(
                        f"vcs_{operation or 'operation'}_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        **kwargs  # Log request parameters
                    )
                
                raise HTTPException(
                    status_code=VCSErrorHandler.get_http_status(e),
                    detail=VCSErrorHandler.format_error_detail(e)
                )
                
            except ValueError as e:
                # Validation errors
                if log_errors:
                    logger.warning(
                        f"vcs_{operation or 'operation'}_validation_failed",
                        error=str(e),
                        **kwargs
                    )
                
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "vcs.validation_error",
                        "message": str(e)
                    }
                )
                
            except Exception as e:
                # Unexpected errors
                if log_errors:
                    logger.error(
                        f"vcs_{operation or 'operation'}_unexpected_error",
                        error=str(e),
                        error_type=type(e).__name__,
                        **kwargs
                    )
                
                # Return generic error to client (don't expose internals)
                raise HTTPException(
                    status_code=default_status,
                    detail={
                        "code": "vcs.internal_error",
                        "message": "An unexpected error occurred. Please try again later."
                    }
                )
        
        # Handle both async and sync functions
        if asyncio.iscoroutinefunction(func):
            return wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except ValueError as e:
                    if log_errors:
                        logger.error(
                            f"vcs_{operation or 'operation'}_validation_error",
                            error=str(e),
                            error_type="ValueError",
                            **kwargs
                        )
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "code": "vcs.validation_error",
                            "message": str(e)
                        }
                    )
                except PermissionError as e:
                    if log_errors:
                        logger.error(
                            f"vcs_{operation or 'operation'}_permission_denied",
                            error=str(e),
                            error_type="PermissionError",
                            **kwargs
                        )
                    raise HTTPException(
                        status_code=403,
                        detail={
                            "code": "vcs.permission_denied",
                            "message": "You don't have permission to perform this operation."
                        }
                    )
                except FileNotFoundError as e:
                    if log_errors:
                        logger.error(
                            f"vcs_{operation or 'operation'}_not_found",
                            error=str(e),
                            error_type="FileNotFoundError",
                            **kwargs
                        )
                    raise HTTPException(
                        status_code=404,
                        detail={
                            "code": "vcs.not_found",
                            "message": "The requested resource was not found."
                        }
                    )
                except Exception as e:
                    # Use same error handling logic as async
                    if log_errors:
                        logger.error(
                            f"vcs_{operation or 'operation'}_failed",
                            error=str(e),
                            error_type=type(e).__name__,
                            **kwargs
                        )
                    
                    # Check for known error types
                    if "already exists" in str(e).lower():
                        raise HTTPException(
                            status_code=409,
                            detail={
                                "code": "vcs.conflict",
                                "message": str(e)
                            }
                        )
                    
                    # Default internal error
                    raise HTTPException(
                        status_code=500,
                        detail={
                            "code": "vcs.internal_error",
                            "message": "An unexpected error occurred. Please try again later."
                        }
                    )
            return sync_wrapper
    
    return decorator


# Import asyncio only if needed
import asyncio