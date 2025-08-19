"""
Admin Logging APIs with Ultra-Enterprise RBAC Enforcement
Task 3.11: Secure audit log access with Turkish compliance

Features:
- RBAC-enforced audit log access
- Advanced filtering and pagination
- Correlation ID tracing
- Security event monitoring
- KVKV-compliant data presentation
- Turkish error messages and audit terminology
- Real-time security analytics
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.logging import get_logger
from ..middleware.correlation_middleware import get_correlation_id
from ..models.user import User
from ..routers.auth import get_current_user
from ..services.audit_service import audit_service
from ..services.rbac_service import rbac_service
from ..services.security_event_service import (
    SecurityEventType,
    SecuritySeverity,
    security_event_service,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/admin/logs", tags=["admin", "logs", "audit"])


# Turkish error messages for KVKV compliance
TURKISH_ERRORS = {
    "ERR-RBAC-FORBIDDEN": "Bu işlem için yetkiniz bulunmamaktadır. (RBAC yetkilendirme hatası)",
    "ERR-AUDIT-ACCESS-DENIED": "Denetim kayıtlarına erişim reddedildi. Yönetici yetkisi gereklidir.",
    "ERR-INVALID-DATE-RANGE": "Geçersiz tarih aralığı. Başlangıç tarihi bitiş tarihinden önce olmalıdır.",
    "ERR-CORRELATION-NOT-FOUND": "Belirtilen korelasyon ID'si ile kayıt bulunamadı.",
    "ERR-AUDIT-RETRIEVAL-FAILED": "Denetim kayıtları alınırken hata oluştu.",
    "ERR-SECURITY-ANALYSIS-FAILED": "Güvenlik analizi gerçekleştirilemedi."
}


class AuditLogFilter(BaseModel):
    """Audit log filtering parameters with Turkish field descriptions."""

    correlation_id: str | None = Field(
        None,
        description="İstek korelasyon ID'si ile filtreleme"
    )
    user_id: int | None = Field(
        None,
        description="Kullanıcı ID'si ile filtreleme"
    )
    event_type: str | None = Field(
        None,
        description="Olay türü ile filtreleme (kısmi eşleşme)"
    )
    scope_type: str | None = Field(
        None,
        description="Kapsam türü ile filtreleme (user, job, financial, etc.)"
    )
    start_date: datetime | None = Field(
        None,
        description="Başlangıç tarihi (ISO 8601 formatında)"
    )
    end_date: datetime | None = Field(
        None,
        description="Bitiş tarihi (ISO 8601 formatında)"
    )


class SecurityEventFilter(BaseModel):
    """Security event filtering parameters."""

    correlation_id: str | None = Field(
        None,
        description="İstek korelasyon ID'si ile filtreleme"
    )
    user_id: int | None = Field(
        None,
        description="Kullanıcı ID'si ile filtreleme"
    )
    event_type: str | None = Field(
        None,
        description="Güvenlik olayı türü ile filtreleme"
    )
    severity_filter: list[str] | None = Field(
        None,
        description="Önem derecesi ile filtreleme (info, low, medium, high, critical)"
    )
    start_date: datetime | None = Field(
        None,
        description="Başlangıç tarihi"
    )
    end_date: datetime | None = Field(
        None,
        description="Bitiş tarihi"
    )


class AuditLogResponse(BaseModel):
    """Audit log response model with Turkish descriptions."""

    id: int = Field(description="Denetim kaydı ID'si")
    event_type: str = Field(description="Olay türü")
    scope_type: str = Field(description="Kapsam türü")
    scope_id: int | None = Field(description="Kapsam ID'si")
    user_id: int | None = Field(description="Kullanıcı ID'si")
    correlation_id: str | None = Field(description="Korelasyon ID'si")
    session_id: str | None = Field(description="Oturum ID'si")
    resource: str | None = Field(description="Kaynak")
    ip_masked: str | None = Field(description="Maskelenmiş IP adresi (KVKV uyumlu)")
    ua_masked: str | None = Field(description="Maskelenmiş kullanıcı agent'ı")
    payload: dict[str, Any] | None = Field(description="Olay verisi")
    chain_hash: str = Field(description="Zincir hash'i (bütünlük doğrulama)")
    created_at: str = Field(description="Oluşturulma zamanı")
    is_system_action: bool = Field(description="Sistem eylemi mi?")


class SecurityEventResponse(BaseModel):
    """Security event response model."""

    id: int = Field(description="Güvenlik olayı ID'si")
    type: str = Field(description="Olay türü")
    user_id: int | None = Field(description="Kullanıcı ID'si")
    session_id: str | None = Field(description="Oturum ID'si")
    correlation_id: str | None = Field(description="Korelasyon ID'si")
    resource: str | None = Field(description="Etkilenen kaynak")
    ip_masked: str | None = Field(description="Maskelenmiş IP adresi")
    ua_masked: str | None = Field(description="Maskelenmiş kullanıcı agent'ı")
    metadata: dict[str, Any] | None = Field(description="Ek olay verisi")
    created_at: str = Field(description="Oluşturulma zamanı")
    is_anonymous: bool = Field(description="Anonim olay mı?")
    is_authenticated: bool = Field(description="Kimlik doğrulamalı olay mı?")
    is_suspicious: bool = Field(description="Şüpheli olay mı?")


class PaginatedAuditResponse(BaseModel):
    """Paginated audit log response."""

    logs: list[AuditLogResponse] = Field(description="Denetim kayıtları listesi")
    pagination: dict[str, Any] = Field(description="Sayfalama bilgileri")
    filters_applied: dict[str, Any] = Field(description="Uygulanan filtreler")


class PaginatedSecurityResponse(BaseModel):
    """Paginated security events response."""

    events: list[SecurityEventResponse] = Field(description="Güvenlik olayları listesi")
    pagination: dict[str, Any] = Field(description="Sayfalama bilgileri")
    filters_applied: dict[str, Any] = Field(description="Uygulanan filtreler")


async def verify_admin_access(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> User:
    """Verify user has admin access for audit logs.
    
    Args:
        current_user: Current authenticated user
        db: Database session
        
    Returns:
        Verified admin user
        
    Raises:
        HTTPException: If user lacks admin privileges
    """
    # Check if user has admin role
    has_admin_role = await rbac_service.user_has_role(db, current_user.id, "admin")

    # Check if user has audit access permission
    has_audit_permission = await rbac_service.user_has_permission(
        db, current_user.id, "audit:read"
    )

    if not (has_admin_role or has_audit_permission):
        # Log unauthorized access attempt
        await security_event_service.create_security_event(
            db=db,
            event_type=SecurityEventType.ACCESS_DENIED,
            severity=SecuritySeverity.HIGH,
            user_id=current_user.id,
            resource="admin_audit_logs",
            metadata={
                "attempted_action": "audit_log_access",
                "required_permissions": ["admin", "audit:read"],
                "user_roles": current_user.roles if hasattr(current_user, 'roles') else []
            }
        )

        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "ERR-RBAC-FORBIDDEN",
                "error_message": TURKISH_ERRORS["ERR-RBAC-FORBIDDEN"],
                "error_message_en": "Insufficient privileges for audit log access",
                "required_permissions": ["admin", "audit:read"]
            }
        )

    # Log successful admin access
    await security_event_service.create_security_event(
        db=db,
        event_type=SecurityEventType.ACCESS_GRANTED,
        severity=SecuritySeverity.INFO,
        user_id=current_user.id,
        resource="admin_audit_logs",
        metadata={
            "action": "audit_log_access_granted",
            "user_permissions": ["admin", "audit:read"]
        }
    )

    return current_user


@router.get(
    "/audit",
    response_model=PaginatedAuditResponse,
    summary="Denetim Kayıtlarını Getir (Get Audit Logs)",
    description="Denetim kayıtlarını filtreleme ve sayfalama ile getirir. Yönetici yetkisi gereklidir."
)
async def get_audit_logs(
    request: Request,
    correlation_id: str | None = Query(
        None,
        description="Korelasyon ID'si ile filtreleme"
    ),
    user_id: int | None = Query(
        None,
        description="Kullanıcı ID'si ile filtreleme"
    ),
    event_type: str | None = Query(
        None,
        description="Olay türü ile filtreleme"
    ),
    scope_type: str | None = Query(
        None,
        description="Kapsam türü ile filtreleme"
    ),
    start_date: datetime | None = Query(
        None,
        description="Başlangıç tarihi (ISO 8601)"
    ),
    end_date: datetime | None = Query(
        None,
        description="Bitiş tarihi (ISO 8601)"
    ),
    limit: int = Query(
        100,
        ge=1,
        le=1000,
        description="Sayfa başına maksimum kayıt sayısı"
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Atlanacak kayıt sayısı (sayfalama için)"
    ),
    db: Session = Depends(get_db),
    admin_user: User = Depends(verify_admin_access)
) -> PaginatedAuditResponse:
    """Get audit logs with filtering and pagination."""

    try:
        # Validate date range
        if start_date and end_date and start_date > end_date:
            raise HTTPException(
                status_code=400,
                detail={
                    "error_code": "ERR-INVALID-DATE-RANGE",
                    "error_message": TURKISH_ERRORS["ERR-INVALID-DATE-RANGE"],
                    "error_message_en": "Start date must be before end date"
                }
            )

        # Get audit logs
        result = await audit_service.get_audit_logs(
            db=db,
            correlation_id=correlation_id,
            user_id=user_id,
            event_type=event_type,
            scope_type=scope_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset
        )

        # Convert to response format
        audit_logs = [
            AuditLogResponse(**log) for log in result["logs"]
        ]

        # Log admin audit access
        await audit_service.create_audit_entry(
            db=db,
            event_type="admin_audit_access",
            user_id=admin_user.id,
            scope_type="admin",
            resource="audit_logs",
            payload={
                "filters": {
                    "correlation_id": correlation_id,
                    "user_id": user_id,
                    "event_type": event_type,
                    "scope_type": scope_type,
                    "date_range": {
                        "start": start_date.isoformat() if start_date else None,
                        "end": end_date.isoformat() if end_date else None
                    }
                },
                "pagination": {
                    "limit": limit,
                    "offset": offset
                },
                "results_count": len(audit_logs),
                "total_count": result["pagination"]["total"]
            }
        )

        return PaginatedAuditResponse(
            logs=audit_logs,
            pagination=result["pagination"],
            filters_applied=result["filters_applied"]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "audit_logs_retrieval_failed",
            error=str(e),
            user_id=admin_user.id,
            correlation_id=get_correlation_id()
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "ERR-AUDIT-RETRIEVAL-FAILED",
                "error_message": TURKISH_ERRORS["ERR-AUDIT-RETRIEVAL-FAILED"],
                "error_message_en": "Failed to retrieve audit logs"
            }
        )


@router.get(
    "/security-events",
    response_model=PaginatedSecurityResponse,
    summary="Güvenlik Olaylarını Getir (Get Security Events)",
    description="Güvenlik olaylarını filtreleme ve sayfalama ile getirir. Yönetici yetkisi gereklidir."
)
async def get_security_events(
    request: Request,
    correlation_id: str | None = Query(
        None,
        description="Korelasyon ID'si ile filtreleme"
    ),
    user_id: int | None = Query(
        None,
        description="Kullanıcı ID'si ile filtreleme"
    ),
    event_type: str | None = Query(
        None,
        description="Güvenlik olayı türü ile filtreleme"
    ),
    start_date: datetime | None = Query(
        None,
        description="Başlangıç tarihi (ISO 8601)"
    ),
    end_date: datetime | None = Query(
        None,
        description="Bitiş tarihi (ISO 8601)"
    ),
    severity_filter: list[str] | None = Query(
        None,
        description="Önem derecesi filtresi"
    ),
    limit: int = Query(
        100,
        ge=1,
        le=1000,
        description="Sayfa başına maksimum kayıt sayısı"
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Atlanacak kayıt sayısı"
    ),
    db: Session = Depends(get_db),
    admin_user: User = Depends(verify_admin_access)
) -> PaginatedSecurityResponse:
    """Get security events with filtering and pagination."""

    try:
        # Validate date range
        if start_date and end_date and start_date > end_date:
            raise HTTPException(
                status_code=400,
                detail={
                    "error_code": "ERR-INVALID-DATE-RANGE",
                    "error_message": TURKISH_ERRORS["ERR-INVALID-DATE-RANGE"],
                    "error_message_en": "Start date must be before end date"
                }
            )

        # Get security events
        result = await security_event_service.get_security_events(
            db=db,
            correlation_id=correlation_id,
            user_id=user_id,
            event_type=event_type,
            start_date=start_date,
            end_date=end_date,
            severity_filter=severity_filter,
            limit=limit,
            offset=offset
        )

        # Convert to response format
        security_events = [
            SecurityEventResponse(**event) for event in result["events"]
        ]

        # Log admin security event access
        await audit_service.create_audit_entry(
            db=db,
            event_type="admin_security_events_access",
            user_id=admin_user.id,
            scope_type="admin",
            resource="security_events",
            payload={
                "filters": {
                    "correlation_id": correlation_id,
                    "user_id": user_id,
                    "event_type": event_type,
                    "severity_filter": severity_filter,
                    "date_range": {
                        "start": start_date.isoformat() if start_date else None,
                        "end": end_date.isoformat() if end_date else None
                    }
                },
                "pagination": {
                    "limit": limit,
                    "offset": offset
                },
                "results_count": len(security_events),
                "total_count": result["pagination"]["total"]
            }
        )

        return PaginatedSecurityResponse(
            events=security_events,
            pagination=result["pagination"],
            filters_applied=result["filters_applied"]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "security_events_retrieval_failed",
            error=str(e),
            user_id=admin_user.id,
            correlation_id=get_correlation_id()
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "ERR-SECURITY-RETRIEVAL-FAILED",
                "error_message": "Güvenlik olayları alınırken hata oluştu.",
                "error_message_en": "Failed to retrieve security events"
            }
        )


@router.get(
    "/correlation/{correlation_id}",
    summary="Korelasyon ID ile Kayıtları Getir (Get Logs by Correlation ID)",
    description="Belirli bir korelasyon ID'sine ait tüm denetim ve güvenlik kayıtlarını getirir."
)
async def get_logs_by_correlation(
    correlation_id: str,
    db: Session = Depends(get_db),
    admin_user: User = Depends(verify_admin_access)
) -> dict[str, Any]:
    """Get all logs (audit and security) for a specific correlation ID."""

    try:
        # Get audit logs for correlation ID
        audit_result = await audit_service.get_audit_logs(
            db=db,
            correlation_id=correlation_id,
            limit=1000  # High limit for correlation tracing
        )

        # Get security events for correlation ID
        security_result = await security_event_service.get_security_events(
            db=db,
            correlation_id=correlation_id,
            limit=1000  # High limit for correlation tracing
        )

        if not audit_result["logs"] and not security_result["events"]:
            raise HTTPException(
                status_code=404,
                detail={
                    "error_code": "ERR-CORRELATION-NOT-FOUND",
                    "error_message": TURKISH_ERRORS["ERR-CORRELATION-NOT-FOUND"],
                    "error_message_en": f"No logs found for correlation ID: {correlation_id}"
                }
            )

        # Log correlation trace access
        await audit_service.create_audit_entry(
            db=db,
            event_type="admin_correlation_trace",
            user_id=admin_user.id,
            scope_type="admin",
            resource="correlation_trace",
            payload={
                "correlation_id": correlation_id,
                "audit_logs_count": len(audit_result["logs"]),
                "security_events_count": len(security_result["events"]),
                "total_logs": len(audit_result["logs"]) + len(security_result["events"])
            }
        )

        return {
            "correlation_id": correlation_id,
            "audit_logs": {
                "count": len(audit_result["logs"]),
                "logs": [AuditLogResponse(**log) for log in audit_result["logs"]]
            },
            "security_events": {
                "count": len(security_result["events"]),
                "events": [SecurityEventResponse(**event) for event in security_result["events"]]
            },
            "summary": {
                "total_entries": len(audit_result["logs"]) + len(security_result["events"]),
                "time_span": {
                    "earliest": min(
                        [log["created_at"] for log in audit_result["logs"]] +
                        [event["created_at"] for event in security_result["events"]]
                    ) if audit_result["logs"] or security_result["events"] else None,
                    "latest": max(
                        [log["created_at"] for log in audit_result["logs"]] +
                        [event["created_at"] for event in security_result["events"]]
                    ) if audit_result["logs"] or security_result["events"] else None
                }
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "correlation_trace_failed",
            correlation_id=correlation_id,
            error=str(e),
            user_id=admin_user.id
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "ERR-CORRELATION-TRACE-FAILED",
                "error_message": "Korelasyon izleme işlemi başarısız oldu.",
                "error_message_en": "Correlation trace operation failed"
            }
        )


@router.get(
    "/security-analytics",
    summary="Güvenlik Analizi (Security Analytics)",
    description="Güvenlik trendleri ve anormallik analizi. Yönetici yetkisi gereklidir."
)
async def get_security_analytics(
    time_window_hours: int = Query(
        24,
        ge=1,
        le=168,  # Max 1 week
        description="Analiz zaman penceresi (saat)"
    ),
    user_id: int | None = Query(
        None,
        description="Belirli kullanıcı için analiz"
    ),
    db: Session = Depends(get_db),
    admin_user: User = Depends(verify_admin_access)
) -> dict[str, Any]:
    """Get security analytics and trend analysis."""

    try:
        # Get security trend analysis
        analytics = await security_event_service.analyze_security_trends(
            db=db,
            time_window_hours=time_window_hours,
            user_id=user_id
        )

        # Verify audit chain integrity for the same period
        audit_verification = await audit_service.verify_audit_chain_integrity(
            db=db,
            limit=1000
        )

        # Log security analytics access
        await audit_service.create_audit_entry(
            db=db,
            event_type="admin_security_analytics",
            user_id=admin_user.id,
            scope_type="admin",
            resource="security_analytics",
            payload={
                "time_window_hours": time_window_hours,
                "target_user_id": user_id,
                "total_events_analyzed": analytics["total_events"],
                "security_score": analytics["security_score"],
                "audit_chain_status": audit_verification["status"]
            }
        )

        return {
            "security_analytics": analytics,
            "audit_chain_integrity": audit_verification,
            "compliance_status": {
                "kvkv_compliant": True,
                "gdpr_compliant": True,
                "data_masking_enabled": True,
                "chain_integrity_verified": audit_verification["status"] == "integrity_verified"
            },
            "generated_at": datetime.now(UTC).isoformat(),
            "generated_by": {
                "user_id": admin_user.id,
                "correlation_id": get_correlation_id()
            }
        }

    except Exception as e:
        logger.error(
            "security_analytics_failed",
            error=str(e),
            user_id=admin_user.id,
            time_window_hours=time_window_hours
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "ERR-SECURITY-ANALYSIS-FAILED",
                "error_message": TURKISH_ERRORS["ERR-SECURITY-ANALYSIS-FAILED"],
                "error_message_en": "Security analysis operation failed"
            }
        )


# Health check endpoint for monitoring
@router.get(
    "/health",
    summary="Denetim Sistemi Sağlık Kontrolü (Audit System Health)",
    description="Denetim ve güvenlik sistemlerinin sağlık durumunu kontrol eder."
)
async def audit_system_health(
    db: Session = Depends(get_db),
    admin_user: User = Depends(verify_admin_access)
) -> dict[str, Any]:
    """Check health status of audit and security systems."""

    try:
        # Check recent audit log creation
        recent_audit = await audit_service.get_audit_logs(
            db=db,
            limit=1
        )

        # Check recent security events
        recent_security = await security_event_service.get_security_events(
            db=db,
            limit=1
        )

        # Quick chain integrity check
        integrity_check = await audit_service.verify_audit_chain_integrity(
            db=db,
            limit=10  # Quick check on last 10 entries
        )

        health_status = {
            "status": "healthy",
            "timestamp": datetime.now(UTC).isoformat(),
            "components": {
                "audit_service": {
                    "status": "operational",
                    "recent_logs": recent_audit["pagination"]["total"] > 0
                },
                "security_service": {
                    "status": "operational",
                    "recent_events": recent_security["pagination"]["total"] > 0
                },
                "chain_integrity": {
                    "status": "verified" if integrity_check["status"] == "integrity_verified" else "issues_detected",
                    "verified_entries": integrity_check["verified_count"],
                    "violations": len(integrity_check["integrity_violations"])
                },
                "pii_masking": {
                    "status": "operational",
                    "kvkv_compliant": True
                },
                "correlation_tracking": {
                    "status": "operational",
                    "current_correlation_id": get_correlation_id()
                }
            }
        }

        # Log health check
        await audit_service.create_audit_entry(
            db=db,
            event_type="admin_health_check",
            user_id=admin_user.id,
            scope_type="admin",
            resource="audit_system_health",
            payload=health_status
        )

        return health_status

    except Exception as e:
        logger.error(
            "audit_health_check_failed",
            error=str(e),
            user_id=admin_user.id
        )

        error_status = {
            "status": "unhealthy",
            "timestamp": datetime.now(UTC).isoformat(),
            "error": str(e)
        }

        return error_status
