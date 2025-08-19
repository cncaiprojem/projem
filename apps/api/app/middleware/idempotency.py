"""
Idempotency middleware for API request deduplication.
Task 4.11: Ensures exactly-once semantics for critical operations.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from typing import Any

from fastapi import HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.logging import get_logger
from ..db import get_db
from ..models.idempotency import IdempotencyKey

logger = get_logger(__name__)


class IdempotencyMiddleware:
    """Middleware to handle idempotency keys for API requests."""

    HEADER_NAME = "Idempotency-Key"
    DEFAULT_TTL_HOURS = 24
    PROCESSING_TIMEOUT_SECONDS = 60

    def __init__(self):
        self.logger = logger

    def compute_request_hash(self, request_body: bytes) -> str:
        """Compute SHA256 hash of request body."""
        return hashlib.sha256(request_body).hexdigest()

    async def check_idempotency(
        self,
        db: Session,
        user_id: int,
        idempotency_key: str,
        request_path: str,
        request_method: str,
        request_body: bytes
    ) -> dict[str, Any] | None:
        """Check if this is a duplicate request and return cached response if available.
        
        Returns:
            Cached response if this is a duplicate request, None otherwise
        """
        request_hash = self.compute_request_hash(request_body)

        # Look for existing idempotency key
        existing = db.query(IdempotencyKey).filter(
            IdempotencyKey.user_id == user_id,
            IdempotencyKey.key == idempotency_key
        ).first()

        if existing:
            # Check if expired
            if existing.is_expired():
                self.logger.info(
                    "Idempotency key expired, deleting",
                    extra={
                        "user_id": user_id,
                        "key": idempotency_key,
                        "expired_at": existing.expires_at.isoformat()
                    }
                )
                db.delete(existing)
                db.commit()
                return None

            # Check if request matches
            if existing.request_hash != request_hash:
                self.logger.warning(
                    "Idempotency key reused with different request",
                    extra={
                        "user_id": user_id,
                        "key": idempotency_key,
                        "expected_hash": existing.request_hash,
                        "actual_hash": request_hash
                    }
                )
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "error": "IDEMPOTENCY_KEY_MISMATCH",
                        "message": "Idempotency key used with different request body",
                        "message_tr": "Idempotency anahtarı farklı bir istek gövdesiyle kullanıldı"
                    }
                )

            # Check if still processing
            if existing.is_processing:
                # Check for timeout
                if existing.is_timeout(self.PROCESSING_TIMEOUT_SECONDS):
                    self.logger.warning(
                        "Processing timeout, resetting",
                        extra={
                            "user_id": user_id,
                            "key": idempotency_key,
                            "started_at": existing.processing_started_at.isoformat()
                        }
                    )
                    existing.is_processing = False
                    db.commit()
                    return None

                # Still processing, return conflict
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error": "REQUEST_IN_PROGRESS",
                        "message": "Request with this idempotency key is still being processed",
                        "message_tr": "Bu idempotency anahtarıyla istek hala işleniyor"
                    }
                )

            # Return cached response
            self.logger.info(
                "Returning cached response for idempotency key",
                extra={
                    "user_id": user_id,
                    "key": idempotency_key,
                    "response_status": existing.response_status
                }
            )

            return {
                "status_code": existing.response_status,
                "body": existing.response_body
            }

        return None

    def store_idempotency_key(
        self,
        db: Session,
        user_id: int,
        idempotency_key: str,
        request_path: str,
        request_method: str,
        request_body: bytes,
        ttl_hours: int = None
    ) -> IdempotencyKey:
        """Store a new idempotency key for processing.
        
        Returns:
            Created IdempotencyKey object
        """
        if ttl_hours is None:
            ttl_hours = self.DEFAULT_TTL_HOURS

        request_hash = self.compute_request_hash(request_body)

        idempotency_obj = IdempotencyKey.create_for_request(
            user_id=user_id,
            key=idempotency_key,
            request_path=request_path,
            request_method=request_method,
            request_hash=request_hash,
            ttl_hours=ttl_hours
        )

        try:
            db.add(idempotency_obj)
            db.commit()

            self.logger.info(
                "Stored new idempotency key",
                extra={
                    "user_id": user_id,
                    "key": idempotency_key,
                    "path": request_path,
                    "expires_at": idempotency_obj.expires_at.isoformat()
                }
            )

            return idempotency_obj

        except IntegrityError:
            # Race condition - another request created it first
            db.rollback()

            # Fetch the existing one
            existing = db.query(IdempotencyKey).filter(
                IdempotencyKey.user_id == user_id,
                IdempotencyKey.key == idempotency_key
            ).first()

            if existing:
                # Wait for it to complete or timeout
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error": "REQUEST_IN_PROGRESS",
                        "message": "Request with this idempotency key is being processed",
                        "message_tr": "Bu idempotency anahtarıyla istek işleniyor"
                    }
                )
            else:
                # Shouldn't happen, but handle gracefully
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "error": "IDEMPOTENCY_ERROR",
                        "message": "Failed to process idempotency key",
                        "message_tr": "Idempotency anahtarı işlenemedi"
                    }
                )

    def complete_request(
        self,
        db: Session,
        idempotency_obj: IdempotencyKey,
        response_status: int,
        response_body: dict | None = None
    ) -> None:
        """Mark request as complete and store response."""
        idempotency_obj.complete_processing(response_status, response_body)
        db.commit()

        self.logger.info(
            "Completed idempotent request",
            extra={
                "user_id": idempotency_obj.user_id,
                "key": idempotency_obj.key,
                "response_status": response_status
            }
        )

    def cleanup_expired_keys(self, db: Session) -> int:
        """Remove expired idempotency keys.
        
        Returns:
            Number of keys deleted
        """
        now = datetime.now(UTC)

        expired_keys = db.query(IdempotencyKey).filter(
            IdempotencyKey.expires_at < now
        ).all()

        count = len(expired_keys)

        for key in expired_keys:
            db.delete(key)

        db.commit()

        if count > 0:
            self.logger.info(
                f"Cleaned up {count} expired idempotency keys",
                extra={"count": count}
            )

        return count


# Singleton instance
idempotency_middleware = IdempotencyMiddleware()


def require_idempotency(
    ttl_hours: int = 24,
    required: bool = True
):
    """Decorator to enforce idempotency on API endpoints.
    
    Args:
        ttl_hours: How long to cache the response
        required: Whether idempotency key is required (vs optional)
    
    Usage:
        @router.post("/license/assign")
        @require_idempotency(ttl_hours=24)
        async def assign_license(...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(
            request: Request,
            *args,
            **kwargs
        ):
            # Get idempotency key from header
            idempotency_key = request.headers.get(IdempotencyMiddleware.HEADER_NAME)

            if not idempotency_key and required:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "IDEMPOTENCY_KEY_REQUIRED",
                        "message": f"{IdempotencyMiddleware.HEADER_NAME} header is required",
                        "message_tr": f"{IdempotencyMiddleware.HEADER_NAME} başlığı gerekli"
                    }
                )

            if idempotency_key:
                # Get database session
                db_gen = get_db()
                db = next(db_gen)

                try:
                    # Get current user (assumes middleware has set this)
                    current_user = kwargs.get("current_user")
                    if not current_user:
                        # Try to get from request state
                        current_user = getattr(request.state, "user", None)

                    if not current_user:
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail={
                                "error": "UNAUTHORIZED",
                                "message": "Authentication required for idempotent requests",
                                "message_tr": "İdempotent istekler için kimlik doğrulama gerekli"
                            }
                        )

                    # Read request body
                    request_body = await request.body()

                    # Check for cached response
                    cached = await idempotency_middleware.check_idempotency(
                        db=db,
                        user_id=current_user.id,
                        idempotency_key=idempotency_key,
                        request_path=str(request.url.path),
                        request_method=request.method,
                        request_body=request_body
                    )

                    if cached:
                        # Return cached response
                        return Response(
                            content=json.dumps(cached["body"]),
                            status_code=cached["status_code"],
                            media_type="application/json",
                            headers={
                                "X-Idempotent-Replay": "true"
                            }
                        )

                    # Store idempotency key
                    idempotency_obj = idempotency_middleware.store_idempotency_key(
                        db=db,
                        user_id=current_user.id,
                        idempotency_key=idempotency_key,
                        request_path=str(request.url.path),
                        request_method=request.method,
                        request_body=request_body,
                        ttl_hours=ttl_hours
                    )

                    # Execute the actual function
                    response = await func(request, *args, **kwargs)

                    # Store response
                    response_body = None
                    if hasattr(response, "body"):
                        try:
                            response_body = json.loads(response.body)
                        except:
                            response_body = {"data": str(response.body)}
                    elif isinstance(response, dict):
                        response_body = response

                    response_status = getattr(response, "status_code", 200)

                    idempotency_middleware.complete_request(
                        db=db,
                        idempotency_obj=idempotency_obj,
                        response_status=response_status,
                        response_body=response_body
                    )

                    return response

                finally:
                    db_gen.close()
            else:
                # No idempotency key, just execute normally
                return await func(request, *args, **kwargs)

        return wrapper
    return decorator
