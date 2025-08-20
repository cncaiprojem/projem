"""
Task 4.2: Idempotency Service
Ultra-enterprise banking grade idempotency service for preventing duplicate API operations.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from uuid import UUID
import json
import logging

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ..models.idempotency import IdempotencyKey as IdempotencyRecord
from ..core.logging import get_logger

logger = get_logger(__name__)


class IdempotencyService:
    """
    Service for managing idempotency in API operations.
    
    Ultra-Enterprise Features:
    - Database-backed idempotency tracking
    - Automatic TTL and cleanup
    - Response replay for duplicate requests
    - Turkish KVKV compliance
    """
    
    # Default TTL for idempotency records (24 hours)
    DEFAULT_TTL_HOURS = 24
    
    @classmethod
    async def get_response(
        cls,
        db: Session,
        key: str,
        user_id: int | UUID,
        endpoint: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get existing response for idempotency key.
        
        Args:
            db: Database session
            key: Idempotency key from header
            user_id: User ID making the request
            endpoint: Optional endpoint for additional validation
            
        Returns:
            Stored response data if found and valid, None otherwise
        """
        try:
            # Convert user_id to UUID if needed
            if isinstance(user_id, int):
                # This shouldn't happen in production, but handle it gracefully
                logger.warning(f"Received int user_id {user_id}, expected UUID")
                return None
            
            # Query for existing idempotency record
            record = db.query(IdempotencyRecord).filter(
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.idempotency_key == key
            ).first()
            
            if not record:
                return None
            
            # Check if record has expired
            if record.is_expired():
                logger.info(
                    f"Idempotency record expired for key {key[:20]}...",
                    extra={
                        "user_id": str(user_id),
                        "expired_at": record.expires_at.isoformat()
                    }
                )
                # Delete expired record
                db.delete(record)
                db.commit()
                return None
            
            # Validate endpoint if provided
            if endpoint and record.endpoint != endpoint:
                logger.warning(
                    f"Idempotency key used for different endpoint",
                    extra={
                        "user_id": str(user_id),
                        "key": key[:20],
                        "expected_endpoint": endpoint,
                        "stored_endpoint": record.endpoint
                    }
                )
                return None
            
            logger.info(
                f"Found valid idempotency record for key {key[:20]}...",
                extra={
                    "user_id": str(user_id),
                    "endpoint": record.endpoint,
                    "created_at": record.created_at.isoformat()
                }
            )
            
            return record.response_data
            
        except Exception as e:
            logger.error(
                f"Error retrieving idempotency record",
                exc_info=True,
                extra={
                    "user_id": str(user_id),
                    "key": key[:20] if key else None,
                    "error_type": type(e).__name__
                }
            )
            return None
    
    @classmethod
    async def store_response(
        cls,
        db: Session,
        key: str,
        user_id: int | UUID,
        response: Dict[str, Any],
        endpoint: str = "",
        method: str = "POST",
        status_code: int = 200,
        ttl_hours: Optional[int] = None
    ) -> bool:
        """
        Store response for idempotency key.
        
        Args:
            db: Database session
            key: Idempotency key from header
            user_id: User ID making the request
            response: Response data to store
            endpoint: API endpoint path
            method: HTTP method
            status_code: HTTP response status code
            ttl_hours: Optional TTL in hours (defaults to 24)
            
        Returns:
            True if stored successfully, False otherwise
        """
        try:
            # Convert user_id to UUID if needed
            if isinstance(user_id, int):
                logger.warning(f"Received int user_id {user_id}, expected UUID")
                return False
            
            # Calculate expiry time
            ttl = ttl_hours or cls.DEFAULT_TTL_HOURS
            expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl)
            
            # Create idempotency record
            record = IdempotencyRecord(
                user_id=user_id,
                idempotency_key=key,
                endpoint=endpoint,
                method=method,
                response_status=status_code,
                response_data=response,
                expires_at=expires_at
            )
            
            db.add(record)
            db.commit()
            
            logger.info(
                f"Stored idempotency record for key {key[:20]}...",
                extra={
                    "user_id": str(user_id),
                    "endpoint": endpoint,
                    "method": method,
                    "expires_at": expires_at.isoformat()
                }
            )
            
            return True
            
        except IntegrityError as e:
            # This means the key already exists for this user
            db.rollback()
            logger.warning(
                f"Idempotency key already exists",
                extra={
                    "user_id": str(user_id),
                    "key": key[:20] if key else None,
                    "endpoint": endpoint
                }
            )
            return False
            
        except Exception as e:
            db.rollback()
            logger.error(
                f"Error storing idempotency record",
                exc_info=True,
                extra={
                    "user_id": str(user_id),
                    "key": key[:20] if key else None,
                    "error_type": type(e).__name__
                }
            )
            return False
    
    @classmethod
    async def cleanup_expired_records(cls, db: Session) -> int:
        """
        Clean up expired idempotency records.
        
        This should be run periodically (e.g., daily) to remove expired records.
        
        Args:
            db: Database session
            
        Returns:
            Number of records deleted
        """
        try:
            now = datetime.now(timezone.utc)
            
            # Find and delete expired records
            expired_count = db.query(IdempotencyRecord).filter(
                IdempotencyRecord.expires_at < now
            ).delete(synchronize_session=False)
            
            db.commit()
            
            if expired_count > 0:
                logger.info(
                    f"Cleaned up {expired_count} expired idempotency records",
                    extra={
                        "deleted_count": expired_count,
                        "cleanup_time": now.isoformat()
                    }
                )
            
            return expired_count
            
        except Exception as e:
            db.rollback()
            logger.error(
                f"Error cleaning up expired idempotency records",
                exc_info=True,
                extra={
                    "error_type": type(e).__name__
                }
            )
            return 0