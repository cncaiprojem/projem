"""
Admin DLQ Management API for Task 6.9

Ultra-enterprise secured endpoints for Dead Letter Queue management with:
- Admin role enforcement with RBAC
- MFA verification requirement
- Rate limiting (30 requests/minute)
- Full audit logging with justification
- RabbitMQ Management API integration
- Message peeking and replay capabilities
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Query, Depends, Body
from sqlalchemy.orm import Session

from ..db import get_db
from ..dependencies.auth_dependencies import get_current_user
from ..middleware.enterprise_rate_limiter import RateLimitDependency
from ..models.user import User
from ..models.enums import UserRole
from ..schemas.dlq import (
    DLQListResponse,
    DLQMessagePreview,
    DLQReplayRequest,
    DLQReplayResponse,
    DLQQueueInfo
)
from ..services.dlq_management_service import DLQManagementService
from ..services.job_audit_service import JobAuditService
from ..services.mfa_service import TOTPService
from ..services.rate_limiting_service import RateLimitType
from ..core.logging import get_logger

logger = get_logger(__name__)


# Dependency for DLQ Management Service
async def get_dlq_service() -> DLQManagementService:
    """
    Dependency injection for DLQ Management Service.
    Creates and manages service lifecycle.
    """
    service = DLQManagementService()
    try:
        yield service
    finally:
        await service.close()


router = APIRouter(
    prefix="/api/v1/admin/dlq",
    tags=["Admin - DLQ Management"],
    responses={
        401: {"description": "Unauthorized - ERR-DLQ-401"},
        403: {"description": "MFA verification failed - ERR-DLQ-403"},
        404: {"description": "Invalid queue - ERR-DLQ-404"},
        429: {"description": "Rate limit exceeded - ERR-DLQ-429"}
    }
)


async def verify_admin_only(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Verify admin role only (without MFA check).
    Used for endpoints that handle MFA verification separately.
    
    Args:
        current_user: Current authenticated user
        
    Returns:
        Verified admin user
        
    Raises:
        HTTPException: 401 for non-admin
    """
    # Check admin role
    if current_user.role != UserRole.ADMIN:
        logger.warning(
            "Non-admin user attempted DLQ access",
            user_id=current_user.id,
            role=current_user.role.value
        )
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "ERR-DLQ-401",
                "message": "Admin role required for DLQ management",
                "message_tr": "DLQ yönetimi için admin rolü gerekli"
            }
        )
    
    return current_user


async def verify_mfa_code(
    mfa_code: str,
    user: User,
    db: Session
) -> None:
    """
    Helper function to verify MFA code from request body.
    
    Args:
        mfa_code: TOTP MFA code from request body
        user: User to verify MFA for
        db: Database session
        
    Raises:
        HTTPException: 403 for failed MFA verification
    """
    totp_service = TOTPService()
    try:
        is_valid = await totp_service.verify_totp(
            db=db,
            user=user,
            totp_code=mfa_code
        )
        
        if not is_valid:
            logger.warning(
                "Invalid MFA code for DLQ access",
                user_id=user.id
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "error_code": "ERR-DLQ-403",
                    "message": "MFA verification failed",
                    "message_tr": "MFA doğrulaması başarısız"
                }
            )
            
    except Exception as e:
        logger.error(
            "MFA verification error",
            user_id=user.id,
            error=str(e)
        )
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "ERR-DLQ-403",
                "message": "MFA verification failed",
                "message_tr": "MFA doğrulaması başarısız"
            }
        )


async def verify_admin_with_mfa(
    current_user: User = Depends(get_current_user),
    mfa_code: str = Query(..., description="6-digit TOTP MFA code"),
    db: Session = Depends(get_db)
) -> User:
    """
    Verify admin role and MFA for DLQ operations.
    
    Args:
        current_user: Current authenticated user
        mfa_code: TOTP MFA code for verification
        db: Database session
        
    Returns:
        Verified admin user
        
    Raises:
        HTTPException: 401 for non-admin, 403 for failed MFA
    """
    # Check admin role
    if current_user.role != UserRole.ADMIN:
        logger.warning(
            "Non-admin user attempted DLQ access",
            user_id=current_user.id,
            role=current_user.role.value
        )
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "ERR-DLQ-401",
                "message": "Admin role required for DLQ management",
                "message_tr": "DLQ yönetimi için admin rolü gerekli"
            }
        )
    
    # Verify MFA using helper function
    await verify_mfa_code(mfa_code, current_user, db)
    
    return current_user


@router.get(
    "",
    response_model=DLQListResponse,
    summary="List all DLQ queues",
    description="List all Dead Letter Queues with message counts and metadata"
)
async def list_dlq_queues(
    current_user: User = Depends(verify_admin_with_mfa),
    db: Session = Depends(get_db),
    dlq_service: DLQManagementService = Depends(get_dlq_service),
    _: None = Depends(RateLimitDependency(RateLimitType.ADMIN))
) -> DLQListResponse:
    """
    List all DLQ queues with message counts.
    
    Returns:
        DLQListResponse with queue information
    """
    try:
        # Get DLQ queue list from RabbitMQ
        queues = await dlq_service.list_dlq_queues()
        
        # Audit the action
        await JobAuditService.audit_dlq_action(
            db=db,
            actor_id=current_user.id,
            action="list_dlq_queues",
            metadata={
                "queue_count": len(queues),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )
        
        logger.info(
            "DLQ queues listed",
            user_id=current_user.id,
            queue_count=len(queues)
        )
        
        return DLQListResponse(
            queues=queues,
            total_messages=sum(q["message_count"] for q in queues),
            timestamp=datetime.now(timezone.utc)
        )
        
    except Exception as e:
        logger.error(
            "Failed to list DLQ queues",
            user_id=current_user.id,
            error=str(e)
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "ERR-DLQ-500",
                "message": "Failed to list DLQ queues",
                "message_tr": "DLQ kuyrukları listelenemedi"
            }
        )


@router.get(
    "/{queue_name}/peek",
    response_model=List[DLQMessagePreview],
    summary="Peek messages in DLQ",
    description="Preview messages in a specific DLQ without consuming them"
)
async def peek_dlq_messages(
    queue_name: str,
    limit: int = Query(10, ge=1, le=100, description="Number of messages to preview"),
    current_user: User = Depends(verify_admin_with_mfa),
    db: Session = Depends(get_db),
    dlq_service: DLQManagementService = Depends(get_dlq_service),
    _: None = Depends(RateLimitDependency(RateLimitType.ADMIN))
) -> List[DLQMessagePreview]:
    """
    Peek messages in a DLQ without consuming them.
    
    Args:
        queue_name: Name of the DLQ queue
        limit: Number of messages to preview
        
    Returns:
        List of message previews
    """
    # Validate queue name ends with _dlq
    if not queue_name.endswith("_dlq"):
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "ERR-DLQ-404",
                "message": f"Invalid DLQ queue name: {queue_name}",
                "message_tr": f"Geçersiz DLQ kuyruk adı: {queue_name}"
            }
        )
    
    try:
        # Peek messages from the queue
        messages = await dlq_service.peek_messages(
            queue_name=queue_name,
            limit=limit
        )
        
        # Audit the action
        await JobAuditService.audit_dlq_action(
            db=db,
            actor_id=current_user.id,
            action="peek_dlq_messages",
            metadata={
                "queue_name": queue_name,
                "limit": limit,
                "messages_peeked": len(messages),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )
        
        logger.info(
            "DLQ messages peeked",
            user_id=current_user.id,
            queue_name=queue_name,
            message_count=len(messages)
        )
        
        return messages
        
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "ERR-DLQ-404",
                "message": str(e),
                "message_tr": "Kuyruk bulunamadı"
            }
        )
    except Exception as e:
        logger.error(
            "Failed to peek DLQ messages",
            user_id=current_user.id,
            queue_name=queue_name,
            error=str(e)
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "ERR-DLQ-500",
                "message": "Failed to peek messages",
                "message_tr": "Mesajlar önizlenemedi"
            }
        )


@router.post(
    "/{queue_name}/replay",
    response_model=DLQReplayResponse,
    summary="Replay messages from DLQ",
    description="Replay messages from DLQ back to their origin queues with justification"
)
async def replay_dlq_messages(
    queue_name: str,
    request: DLQReplayRequest,
    current_user: User = Depends(verify_admin_only),
    db: Session = Depends(get_db),
    dlq_service: DLQManagementService = Depends(get_dlq_service),
    _: None = Depends(RateLimitDependency(RateLimitType.ADMIN))
) -> DLQReplayResponse:
    """
    Replay messages from DLQ to origin queues.
    
    Args:
        queue_name: Name of the DLQ queue
        request: Replay request with justification
        
    Returns:
        DLQReplayResponse with replay results
    """
    # Validate queue name ends with _dlq
    if not queue_name.endswith("_dlq"):
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "ERR-DLQ-404",
                "message": f"Invalid DLQ queue name: {queue_name}",
                "message_tr": f"Geçersiz DLQ kuyruk adı: {queue_name}"
            }
        )
    
    # Verify MFA from request body
    await verify_mfa_code(request.mfa_code, current_user, db)
    
    try:
        # Replay messages with backoff
        replay_result = await dlq_service.replay_messages(
            queue_name=queue_name,
            max_messages=request.max_messages,
            backoff_ms=request.backoff_ms
        )
        
        # Audit the replay action with justification
        await JobAuditService.audit_dlq_replay(
            db=db,
            actor_id=current_user.id,
            queue_name=queue_name,
            messages_replayed=replay_result["replayed_count"],
            justification=request.justification,
            metadata={
                "max_messages": request.max_messages,
                "backoff_ms": request.backoff_ms,
                "failed_replays": replay_result.get("failed_count", 0),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )
        
        logger.info(
            "DLQ messages replayed",
            user_id=current_user.id,
            queue_name=queue_name,
            replayed_count=replay_result["replayed_count"],
            justification=request.justification[:50]  # Log first 50 chars
        )
        
        return DLQReplayResponse(
            queue_name=queue_name,
            messages_replayed=replay_result["replayed_count"],
            messages_failed=replay_result.get("failed_count", 0),
            justification=request.justification,
            timestamp=datetime.now(timezone.utc),
            details=replay_result.get("details")
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "ERR-DLQ-404",
                "message": str(e),
                "message_tr": "Kuyruk bulunamadı"
            }
        )
    except Exception as e:
        logger.error(
            "Failed to replay DLQ messages",
            user_id=current_user.id,
            queue_name=queue_name,
            error=str(e)
        )
        
        # Audit the failed replay attempt
        await JobAuditService.audit_dlq_action(
            db=db,
            actor_id=current_user.id,
            action="replay_failed",
            metadata={
                "queue_name": queue_name,
                "error": str(e),
                "justification": request.justification,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )
        
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "ERR-DLQ-500",
                "message": "Failed to replay messages",
                "message_tr": "Mesajlar yeniden oynatılamadı"
            }
        )
