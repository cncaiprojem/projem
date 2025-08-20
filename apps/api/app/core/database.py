"""
Database configuration and session management.
This module provides backward compatibility for imports.
"""

from ..db import (
    engine,
    SessionLocal,
    db_session,
    get_db,
    check_db
)

__all__ = [
    'engine',
    'SessionLocal',
    'db_session',
    'get_db',
    'check_db'
]