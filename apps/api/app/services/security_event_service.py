"""
Ultra-Enterprise Security Event Service
Task 3.11: Real-time security monitoring with Turkish KVKV compliance

Features:
- Real-time security event tracking
- Threat intelligence integration
- Automated incident escalation
- KVKV/GDPR compliant data handling
- Performance optimized for high-frequency events
- Turkish cybersecurity law compliance
- Banking-level security monitoring
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, desc, func, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..core.logging import get_logger
from ..middleware.correlation_middleware import get_correlation_id, get_session_id
from ..models.security_event import SecurityEvent
from ..models.user import User
from ..services.pii_masking_service import DataClassification, MaskingLevel, pii_masking_service


logger = get_logger(__name__)


class SecurityEventType(str, Enum):
    """Security event types for classification."""

    # Authentication Events
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGIN_BLOCKED = "LOGIN_BLOCKED"
    LOGOUT = "LOGOUT"
    SESSION_EXPIRED = "SESSION_EXPIRED"

    # Authorization Events
    ACCESS_GRANTED = "ACCESS_GRANTED"
    ACCESS_DENIED = "ACCESS_DENIED"
    PRIVILEGE_ESCALATION = "PRIVILEGE_ESCALATION"
    UNAUTHORIZED_ACCESS = "UNAUTHORIZED_ACCESS"

    # Security Threats
    BRUTE_FORCE_DETECTED = "BRUTE_FORCE_DETECTED"
    SUSPICIOUS_LOGIN = "SUSPICIOUS_LOGIN"
    MALICIOUS_PAYLOAD = "MALICIOUS_PAYLOAD"
    SQL_INJECTION_ATTEMPT = "SQL_INJECTION_ATTEMPT"
    XSS_ATTEMPT = "XSS_ATTEMPT"

    # Rate Limiting
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    API_ABUSE_DETECTED = "API_ABUSE_DETECTED"

    # Data Protection
    DATA_ACCESS_ANOMALY = "DATA_ACCESS_ANOMALY"
    SENSITIVE_DATA_ACCESS = "SENSITIVE_DATA_ACCESS"
    GDPR_VIOLATION_DETECTED = "GDPR_VIOLATION_DETECTED"

    # System Security
    SECURITY_CONFIG_CHANGED = "SECURITY_CONFIG_CHANGED"
    CERTIFICATE_EXPIRED = "CERTIFICATE_EXPIRED"
    FIREWALL_BREACH = "FIREWALL_BREACH"


class SecuritySeverity(str, Enum):
    """Security severity levels for incident classification."""

    INFO = "info"  # Bilgi
    LOW = "low"  # Düşük
    MEDIUM = "medium"  # Orta
    HIGH = "high"  # Yüksek
    CRITICAL = "critical"  # Kritik
    EMERGENCY = "emergency"  # Acil


class SecurityEventService:
    """Ultra-enterprise security event service with real-time monitoring."""

    def __init__(self):
        """Initialize security event service."""
        self.enable_real_time_alerts = True
        self.alert_thresholds = {
            SecuritySeverity.CRITICAL: 1,  # Immediate alert
            SecuritySeverity.HIGH: 3,  # Alert after 3 events
            SecuritySeverity.MEDIUM: 10,  # Alert after 10 events
            SecuritySeverity.LOW: 50,  # Alert after 50 events
        }

    async def create_security_event(
        self,
        db: Session,
        event_type: SecurityEventType,
        severity: SecuritySeverity,
        user_id: Optional[int] = None,
        resource: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> SecurityEvent:
        """Create comprehensive security event with KVKV compliance.

        Args:
            db: Database session
            event_type: Type of security event
            severity: Severity level of the event
            user_id: ID of affected user
            resource: Resource involved in the event
            ip_address: Source IP address (will be masked)
            user_agent: Client user agent (will be masked)
            metadata: Additional event metadata
            correlation_id: Request correlation ID
            session_id: User session ID

        Returns:
            Created security event

        Raises:
            SQLAlchemyError: If database operation fails
            ValueError: If event data is invalid
        """
        try:
            # Use correlation context if not provided
            correlation_id = correlation_id or get_correlation_id()
            session_id = session_id or get_session_id()

            # Apply KVKV-compliant masking
            masked_ip = None
            masked_ua = None
            masked_metadata = metadata

            if ip_address:
                masked_ip = pii_masking_service.mask_ip_address(
                    ip_address,
                    MaskingLevel.MEDIUM,  # KVKV compliance level
                )

            if user_agent:
                masked_ua = pii_masking_service.mask_user_agent(
                    user_agent,
                    MaskingLevel.LIGHT,  # Preserve security-relevant info
                )

            if metadata:
                # Apply classification-based masking
                classification = self._determine_data_classification(event_type, severity)
                masked_metadata = pii_masking_service.create_masked_metadata(
                    metadata,
                    classification,
                    preserve_keys=["timestamp", "event_id", "severity", "threat_score"],
                )

            # Create security event
            security_event = SecurityEvent(
                user_id=user_id,
                type=event_type.value,
                session_id=session_id,
                correlation_id=correlation_id,
                resource=resource,
                ip_masked=masked_ip,
                ua_masked=masked_ua,
                metadata=masked_metadata,
                created_at=datetime.now(timezone.utc),
            )

            # Add to database
            db.add(security_event)
            db.flush()  # Get ID without committing

            # Log security event creation
            self._log_security_event_creation(
                security_event.id, event_type, severity, correlation_id
            )

            # Check for real-time alerting
            if self.enable_real_time_alerts:
                await self._check_alert_conditions(db, event_type, severity, user_id, ip_address)

            return security_event

        except SQLAlchemyError as e:
            logger.error(
                "security_event_creation_failed",
                event_type=event_type.value,
                severity=severity.value,
                user_id=user_id,
                error=str(e),
                correlation_id=correlation_id,
            )
            raise
        except Exception as e:
            logger.error(
                "security_event_creation_error",
                event_type=event_type.value,
                error_type=type(e).__name__,
                error=str(e),
                correlation_id=correlation_id,
            )
            raise ValueError(f"Failed to create security event: {str(e)}")

    async def get_security_events(
        self,
        db: Session,
        correlation_id: Optional[str] = None,
        user_id: Optional[int] = None,
        event_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        severity_filter: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Retrieve security events with filtering and pagination.

        Args:
            db: Database session
            correlation_id: Filter by correlation ID
            user_id: Filter by user ID
            event_type: Filter by event type
            start_date: Filter by start date
            end_date: Filter by end date
            severity_filter: Filter by severity levels
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            Dictionary containing security events and metadata
        """
        try:
            # Build query
            query = db.query(SecurityEvent)

            # Apply filters
            if correlation_id:
                query = query.filter(SecurityEvent.correlation_id == correlation_id)

            if user_id:
                query = query.filter(SecurityEvent.user_id == user_id)

            if event_type:
                query = query.filter(SecurityEvent.type.ilike(f"%{event_type}%"))

            if start_date:
                query = query.filter(SecurityEvent.created_at >= start_date)

            if end_date:
                query = query.filter(SecurityEvent.created_at <= end_date)

            if severity_filter:
                # Filter by severity in metadata (if stored there)
                severity_conditions = []
                for severity in severity_filter:
                    severity_conditions.append(
                        SecurityEvent.metadata.op("->>")("severity") == severity
                    )
                if severity_conditions:
                    query = query.filter(or_(*severity_conditions))

            # Get total count for pagination
            total_count = query.count()

            # Apply ordering and pagination
            security_events = (
                query.order_by(desc(SecurityEvent.created_at)).limit(limit).offset(offset).all()
            )

            # Format results
            formatted_events = []
            for event in security_events:
                formatted_event = {
                    "id": event.id,
                    "type": event.type,
                    "user_id": event.user_id,
                    "session_id": event.session_id,
                    "correlation_id": event.correlation_id,
                    "resource": event.resource,
                    "ip_masked": event.ip_masked,
                    "ua_masked": event.ua_masked,
                    "metadata": event.metadata,
                    "created_at": event.created_at.isoformat(),
                    "is_anonymous": event.is_anonymous,
                    "is_authenticated": event.is_authenticated,
                    "is_login_related": event.is_login_related(),
                    "is_access_related": event.is_access_related(),
                    "is_suspicious": event.is_suspicious(),
                }
                formatted_events.append(formatted_event)

            return {
                "events": formatted_events,
                "pagination": {
                    "total": total_count,
                    "limit": limit,
                    "offset": offset,
                    "has_more": offset + limit < total_count,
                },
                "filters_applied": {
                    "correlation_id": correlation_id,
                    "user_id": user_id,
                    "event_type": event_type,
                    "date_range": {
                        "start": start_date.isoformat() if start_date else None,
                        "end": end_date.isoformat() if end_date else None,
                    },
                    "severity_filter": severity_filter,
                },
            }

        except SQLAlchemyError as e:
            logger.error(
                "security_events_retrieval_failed", error=str(e), correlation_id=correlation_id
            )
            raise

    async def analyze_security_trends(
        self, db: Session, time_window_hours: int = 24, user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Analyze security trends and patterns.

        Args:
            db: Database session
            time_window_hours: Time window for analysis in hours
            user_id: Optional user ID to focus analysis

        Returns:
            Security trend analysis report
        """
        try:
            from datetime import timedelta

            # Calculate time window
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(hours=time_window_hours)

            # Base query for time window
            base_query = db.query(SecurityEvent).filter(SecurityEvent.created_at >= start_time)

            if user_id:
                base_query = base_query.filter(SecurityEvent.user_id == user_id)

            # Event type distribution
            event_type_stats = (
                base_query.with_entities(
                    SecurityEvent.type, func.count(SecurityEvent.id).label("count")
                )
                .group_by(SecurityEvent.type)
                .order_by(desc("count"))
                .all()
            )

            # Hourly event distribution
            hourly_stats = (
                base_query.with_entities(
                    func.date_trunc("hour", SecurityEvent.created_at).label("hour"),
                    func.count(SecurityEvent.id).label("count"),
                )
                .group_by("hour")
                .order_by("hour")
                .all()
            )

            # Top affected users (if not filtering by user)
            top_users = []
            if not user_id:
                top_users = (
                    base_query.filter(SecurityEvent.user_id.isnot(None))
                    .with_entities(
                        SecurityEvent.user_id, func.count(SecurityEvent.id).label("event_count")
                    )
                    .group_by(SecurityEvent.user_id)
                    .order_by(desc("event_count"))
                    .limit(10)
                    .all()
                )

            # Suspicious activity detection
            suspicious_events = base_query.filter(
                or_(
                    SecurityEvent.type.like("%SUSPICIOUS%"),
                    SecurityEvent.type.like("%BRUTE_FORCE%"),
                    SecurityEvent.type.like("%INJECTION%"),
                )
            ).count()

            return {
                "analysis_period": {
                    "start": start_time.isoformat(),
                    "end": end_time.isoformat(),
                    "hours": time_window_hours,
                },
                "total_events": base_query.count(),
                "suspicious_events": suspicious_events,
                "event_type_distribution": [
                    {"type": event_type, "count": count} for event_type, count in event_type_stats
                ],
                "hourly_distribution": [
                    {"hour": hour.isoformat(), "count": count} for hour, count in hourly_stats
                ],
                "top_affected_users": [
                    {"user_id": user_id, "event_count": count} for user_id, count in top_users
                ]
                if not user_id
                else [],
                "security_score": self._calculate_security_score(
                    base_query.count(), suspicious_events, time_window_hours
                ),
            }

        except Exception as e:
            logger.error(
                "security_trend_analysis_failed", error=str(e), time_window_hours=time_window_hours
            )
            raise

    async def record_authentication_event(
        self,
        db: Session,
        event_type: SecurityEventType,
        user_id: Optional[int],
        success: bool,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        additional_data: Optional[Dict[str, Any]] = None,
    ) -> SecurityEvent:
        """Record authentication-related security event.

        Args:
            db: Database session
            event_type: Authentication event type
            user_id: User ID (if known)
            success: Whether authentication was successful
            ip_address: Source IP address
            user_agent: Client user agent
            additional_data: Additional authentication data

        Returns:
            Created security event
        """
        severity = SecuritySeverity.INFO if success else SecuritySeverity.MEDIUM

        auth_metadata = {
            "authentication_success": success,
            "event_category": "authentication",
            **(additional_data or {}),
        }

        return await self.create_security_event(
            db=db,
            event_type=event_type,
            severity=severity,
            user_id=user_id,
            resource="authentication_system",
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=auth_metadata,
        )

    async def record_access_control_event(
        self,
        db: Session,
        resource: str,
        action: str,
        user_id: int,
        granted: bool,
        ip_address: Optional[str] = None,
        additional_data: Optional[Dict[str, Any]] = None,
    ) -> SecurityEvent:
        """Record access control security event.

        Args:
            db: Database session
            resource: Resource being accessed
            action: Action being performed
            user_id: User ID performing action
            granted: Whether access was granted
            ip_address: Source IP address
            additional_data: Additional access control data

        Returns:
            Created security event
        """
        event_type = (
            SecurityEventType.ACCESS_GRANTED if granted else SecurityEventType.ACCESS_DENIED
        )
        severity = SecuritySeverity.INFO if granted else SecuritySeverity.HIGH

        access_metadata = {
            "access_granted": granted,
            "action": action,
            "event_category": "access_control",
            **(additional_data or {}),
        }

        return await self.create_security_event(
            db=db,
            event_type=event_type,
            severity=severity,
            user_id=user_id,
            resource=resource,
            ip_address=ip_address,
            metadata=access_metadata,
        )

    def _determine_data_classification(
        self, event_type: SecurityEventType, severity: SecuritySeverity
    ) -> DataClassification:
        """Determine data classification based on event type and severity.

        Args:
            event_type: Security event type
            severity: Event severity

        Returns:
            Appropriate data classification level
        """
        # High-sensitivity events
        if severity in [SecuritySeverity.CRITICAL, SecuritySeverity.EMERGENCY]:
            return DataClassification.SENSITIVE

        # Authentication and authorization events
        if event_type in [
            SecurityEventType.LOGIN_FAILED,
            SecurityEventType.UNAUTHORIZED_ACCESS,
            SecurityEventType.PRIVILEGE_ESCALATION,
        ]:
            return DataClassification.RESTRICTED

        # Data protection events
        if event_type in [
            SecurityEventType.SENSITIVE_DATA_ACCESS,
            SecurityEventType.GDPR_VIOLATION_DETECTED,
        ]:
            return DataClassification.SENSITIVE

        # Default to personal data classification
        return DataClassification.PERSONAL

    async def _check_alert_conditions(
        self,
        db: Session,
        event_type: SecurityEventType,
        severity: SecuritySeverity,
        user_id: Optional[int],
        ip_address: Optional[str],
    ) -> None:
        """Check if alert conditions are met for real-time monitoring.

        Args:
            db: Database session
            event_type: Security event type
            severity: Event severity
            user_id: Affected user ID
            ip_address: Source IP address
        """
        try:
            # Immediate alert for critical events
            if severity in [SecuritySeverity.CRITICAL, SecuritySeverity.EMERGENCY]:
                await self._trigger_security_alert(
                    "CRITICAL_SECURITY_EVENT",
                    {
                        "event_type": event_type.value,
                        "severity": severity.value,
                        "user_id": user_id,
                        "ip_address": ip_address,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )

            # Check for brute force patterns
            if event_type == SecurityEventType.LOGIN_FAILED and ip_address:
                await self._check_brute_force_pattern(db, ip_address)

            # Check for suspicious user activity
            if user_id and event_type in [
                SecurityEventType.UNAUTHORIZED_ACCESS,
                SecurityEventType.PRIVILEGE_ESCALATION,
            ]:
                await self._check_user_anomaly_pattern(db, user_id)

        except Exception as e:
            logger.error("alert_condition_check_failed", event_type=event_type.value, error=str(e))

    async def _trigger_security_alert(self, alert_type: str, alert_data: Dict[str, Any]) -> None:
        """Trigger security alert for immediate response.

        Args:
            alert_type: Type of security alert
            alert_data: Alert data and context
        """
        logger.critical(
            "security_alert_triggered",
            alert_type=alert_type,
            alert_data=alert_data,
            requires_immediate_attention=True,
        )

        # Here you would integrate with external alerting systems
        # such as SIEM, email alerts, SMS, etc.

    async def _check_brute_force_pattern(self, db: Session, ip_address: str) -> None:
        """Check for brute force attack patterns from IP.

        Args:
            db: Database session
            ip_address: IP address to analyze
        """
        from datetime import timedelta

        # Look for login failures in last 15 minutes
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=15)

        # Use proper PII masking service to mask the IP address for accurate comparison
        # This ensures IPv4/IPv6 compatibility and prevents false positives
        masked_ip_to_check = pii_masking_service.mask_ip_address(ip_address)

        recent_failures = (
            db.query(SecurityEvent)
            .filter(
                and_(
                    SecurityEvent.type == SecurityEventType.LOGIN_FAILED.value,
                    SecurityEvent.created_at >= recent_time,
                    SecurityEvent.ip_masked == masked_ip_to_check,  # Exact masked IP match
                )
            )
            .count()
        )

        if recent_failures >= 5:  # Threshold for brute force
            await self._trigger_security_alert(
                "BRUTE_FORCE_DETECTED",
                {
                    "ip_masked": masked_ip_to_check,  # Use masked IP for KVKV compliance
                    "failed_attempts": recent_failures,
                    "time_window_minutes": 15,
                    "threat_level": "HIGH",  # Enhanced threat classification
                },
            )

    async def _check_user_anomaly_pattern(self, db: Session, user_id: int) -> None:
        """Check for anomalous user activity patterns.

        Args:
            db: Database session
            user_id: User ID to analyze
        """
        from datetime import timedelta

        # Look for suspicious events in last hour
        recent_time = datetime.now(timezone.utc) - timedelta(hours=1)

        suspicious_events = (
            db.query(SecurityEvent)
            .filter(
                and_(
                    SecurityEvent.user_id == user_id,
                    SecurityEvent.created_at >= recent_time,
                    or_(
                        SecurityEvent.type.like("%UNAUTHORIZED%"),
                        SecurityEvent.type.like("%ESCALATION%"),
                        SecurityEvent.type.like("%SUSPICIOUS%"),
                    ),
                )
            )
            .count()
        )

        if suspicious_events >= 3:  # Threshold for user anomaly
            await self._trigger_security_alert(
                "USER_ANOMALY_DETECTED",
                {
                    "user_id": user_id,
                    "suspicious_events": suspicious_events,
                    "time_window_hours": 1,
                },
            )

    def _calculate_security_score(
        self, total_events: int, suspicious_events: int, time_window_hours: int
    ) -> Dict[str, Any]:
        """Calculate security score based on event patterns.

        Args:
            total_events: Total number of events
            suspicious_events: Number of suspicious events
            time_window_hours: Analysis time window

        Returns:
            Security score analysis
        """
        if total_events == 0:
            return {
                "score": 100,
                "level": "EXCELLENT",
                "description": "No security events detected",
            }

        # Calculate suspicious event ratio
        suspicious_ratio = suspicious_events / total_events

        # Calculate event frequency (events per hour)
        event_frequency = total_events / time_window_hours

        # Base score calculation (100 is perfect)
        base_score = 100

        # Deduct points for suspicious events
        suspicious_penalty = min(suspicious_ratio * 50, 40)

        # Deduct points for high event frequency (potential issues)
        frequency_penalty = min(event_frequency / 10, 20) if event_frequency > 50 else 0

        final_score = max(base_score - suspicious_penalty - frequency_penalty, 0)

        # Determine security level
        if final_score >= 90:
            level = "EXCELLENT"
        elif final_score >= 75:
            level = "GOOD"
        elif final_score >= 60:
            level = "MODERATE"
        elif final_score >= 40:
            level = "POOR"
        else:
            level = "CRITICAL"

        return {
            "score": round(final_score, 1),
            "level": level,
            "suspicious_ratio": round(suspicious_ratio * 100, 1),
            "event_frequency": round(event_frequency, 1),
            "description": f"Security level: {level} ({final_score:.1f}/100)",
        }

    def _log_security_event_creation(
        self,
        event_id: int,
        event_type: SecurityEventType,
        severity: SecuritySeverity,
        correlation_id: Optional[str],
    ) -> None:
        """Log security event creation for monitoring.

        Args:
            event_id: Created security event ID
            event_type: Type of security event
            severity: Event severity
            correlation_id: Request correlation ID
        """
        logger.info(
            "security_event_created",
            event_id=event_id,
            event_type=event_type.value,
            severity=severity.value,
            correlation_id=correlation_id,
            compliance="KVKV_GDPR",
            real_time_monitoring=self.enable_real_time_alerts,
        )


# Singleton instance for application use
security_event_service = SecurityEventService()


# Export main service and enums
__all__ = [
    "SecurityEventService",
    "SecurityEventType",
    "SecuritySeverity",
    "security_event_service",
]
