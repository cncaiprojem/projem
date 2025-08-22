"""
Core utility functions for the application.

Provides common utility functions used across multiple services and modules.
"""

from __future__ import annotations

from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


def convert_user_id_to_int(user_id: str | None) -> int | None:
    """
    Safely convert user_id to integer.
    
    This utility function is used across multiple services to handle
    the conversion of user IDs from string format to integer, with
    proper error handling and logging.
    
    Args:
        user_id: User ID as string or None
        
    Returns:
        User ID as integer or None if invalid/not provided
        
    Examples:
        >>> convert_user_id_to_int("123")
        123
        >>> convert_user_id_to_int(None)
        None
        >>> convert_user_id_to_int("invalid")
        None
    """
    if not user_id:
        return None
        
    try:
        return int(user_id)
    except (ValueError, TypeError) as e:
        logger.warning(
            "Invalid user_id format, cannot convert to integer",
            user_id=user_id,
            error=str(e)
        )
        return None