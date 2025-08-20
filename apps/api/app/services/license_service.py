"""
License service for Task 4.1: State transitions and business logic.
Ultra-enterprise implementation with audit trail and validation.

Enhanced for Task 4.10: Comprehensive observability with metrics and correlation IDs
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from dateutil.relativedelta import relativedelta
import hashlib
import json
import time

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_, or_

from ..models.license import License
from ..models.license_audit import LicenseAudit
from ..models.user import User
from ..core.logging import get_logger
from ..core.telemetry import create_span, create_financial_span
from ..middleware.correlation_middleware import get_correlation_id, get_session_id
from ..services.audit_service import audit_service
from ..config import settings
from .. import metrics

logger = get_logger(__name__)

# Module-level constants for license configuration
ALLOWED_LICENSE_TYPES = ['3m', '6m', '12m']
LICENSE_DURATION_MAP = {'3m': 3, '6m': 6, '12m': 12}


class LicenseStateError(Exception):
    """Exception raised for invalid license state transitions."""
    pass


class LicenseService:
    """Service for managing license lifecycle and state transitions.
    
    Task 4.1 State Transitions:
    - assign: Create new active license
    - extend: Extend existing active license
    - cancel: Cancel active license
    - expire: Mark license as expired
    """
    
    @staticmethod
    def _create_audit_log(
        db: Session,
        license: License,
        event_type: str,
        old_state: Optional[dict],
        new_state: dict,
        delta: Optional[dict] = None,
        user_id: Optional[int] = None,
        actor_type: str = "system",
        actor_id: Optional[str] = None,
        reason: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> LicenseAudit:
        """Create an audit log entry with hash-chain integrity."""
        
        # Get the previous audit record for hash chaining
        previous_audit = db.query(LicenseAudit).filter(
            LicenseAudit.license_id == license.id
        ).order_by(LicenseAudit.id.desc()).first()
        
        # Create audit record
        audit = LicenseAudit(
            license_id=license.id,
            user_id=user_id,
            event_type=event_type,
            old_state=old_state,
            new_state=new_state,
            delta=delta,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
            ip_address=ip_address,
            user_agent=user_agent,
            previous_hash=previous_audit.current_hash if previous_audit else None,
            audit_metadata={
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'license_type': license.type,
                'user_email': license.user.email if license.user else None
            }
        )
        
        # We need to flush to get the ID for hash calculation
        db.add(audit)
        db.flush()
        
        # Compute hash for this record
        audit_data = audit.to_dict()
        audit.current_hash = LicenseAudit.compute_hash(audit_data)
        
        return audit
    
    @staticmethod
    def assign_license(
        db: Session,
        user_id: int,
        license_type: str,
        scope: Dict[str, Any],
        actor_type: str = "system",
        actor_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> License:
        """Assign a new license to a user with comprehensive observability.
        
        Task 4.1 'assign' transition:
        - Create active license with ends_at = starts_at + duration
        - Audit event 'license_assigned'
        - Enforce one active license per user constraint
        
        Enhanced Task 4.10: Observability integration:
        - OpenTelemetry tracing with business context
        - Prometheus metrics for license operations
        - Comprehensive audit logging with correlation IDs
        - Performance monitoring and error tracking
        
        Args:
            db: Database session
            user_id: User to assign license to
            license_type: License duration type ('3m', '6m', '12m')
            scope: License scope configuration (features, limits)
            actor_type: Who initiated (user, system, admin, api)
            actor_id: Identifier of the actor
            ip_address: Request IP (anonymized for KVKV)
            user_agent: Request user agent
            
        Returns:
            Created License object
            
        Raises:
            LicenseStateError: If user already has an active license
            ValueError: If invalid license type
        """
        
        # Get correlation context for observability
        correlation_id = get_correlation_id()
        session_id = get_session_id()
        current_user_id = actor_id  # Use actor_id as the current user
        start_time = time.time()
        
        # Create business span for license assignment
        with create_span(
            "lisans_atama",
            operation_type="business",
            user_id=user_id,
            correlation_id=correlation_id,
            attributes={
                "license.type": license_type,
                "license.scope": json.dumps(scope),
                "actor.type": actor_type,
                "actor.id": actor_id or "unknown"
            }
        ) as span:
            
            try:
                # Validate license type
                if license_type not in ALLOWED_LICENSE_TYPES:
                    error_msg = f"Invalid license type: {license_type}"
                    
                    # Track validation failure metric
                    metrics.license_operations_total.labels(
                        operation="assign",
                        license_type=license_type,
                        status="validation_failed",
                        user_type=actor_type
                    ).inc()
                    
                    # Log validation failure
                    logger.warning(
                        "license_assignment_validation_failed",
                        user_id=user_id,
                        license_type=license_type,
                        reason="invalid_license_type",
                        correlation_id=correlation_id,
                        session_id=session_id
                    )
                    
                    raise ValueError(error_msg)
                
                # Check for existing active license
                existing_active = db.query(License).filter(
                    and_(
                        License.user_id == user_id,
                        License.status == 'active',
                        License.ends_at > datetime.now(timezone.utc)
                    )
                ).first()
                
                if existing_active:
                    error_msg = (
                        f"User {user_id} already has an active license (ID: {existing_active.id}). "
                        "Cannot assign another active license."
                    )
                    
                    # Track conflict metric
                    metrics.license_operations_total.labels(
                        operation="assign",
                        license_type=license_type,
                        status="conflict_active_license",
                        user_type=actor_type
                    ).inc()
                    
                    # Log license conflict
                    logger.warning(
                        "license_assignment_conflict",
                        user_id=user_id,
                        existing_license_id=existing_active.id,
                        existing_license_type=existing_active.type,
                        new_license_type=license_type,
                        correlation_id=correlation_id,
                        session_id=session_id,
                        event_type="license_conflict"
                    )
                    
                    raise LicenseStateError(error_msg)
                
                # Calculate duration
                months = LICENSE_DURATION_MAP[license_type]
                
                # Create new license
                now = datetime.now(timezone.utc)
                # Calculate end date using relativedelta for accurate month calculation
                ends_at = now + relativedelta(months=months)
                
                license = License(
                    user_id=user_id,
                    type=license_type,
                    scope=scope,
                    status='active',
                    starts_at=now,
                    ends_at=ends_at
                )
                
                db.add(license)
                db.flush()  # Get the ID
                
                # Add span attributes for successful license creation
                span.set_attribute("license.id", str(license.id))
                span.set_attribute("license.starts_at", now.isoformat())
                span.set_attribute("license.ends_at", ends_at.isoformat())
                span.set_attribute("license.duration_months", str(months))
                
                # Create comprehensive audit log entry using structured logging
                # This provides observability without requiring async context
                logger.info(
                    "license_business_audit",
                    event_type="license_assigned",
                    scope_type="license",
                    scope_id=license.id,
                    user_id=current_user_id or user_id,
                    target_user_id=user_id,
                    license_type=license_type,
                    duration_months=months,
                    scope=scope,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    starts_at=now.isoformat(),
                    ends_at=ends_at.isoformat(),
                    business_operation="license_assignment",
                    correlation_id=correlation_id,
                    session_id=session_id,
                    classification="business_audit",
                    compliance="KVKV_GDPR"
                )
                
                # Create legacy audit log for backwards compatibility
                audit = LicenseService._create_audit_log(
                    db=db,
                    license=license,
                    event_type='license_assigned',
                    old_state=None,
                    new_state={
                        'status': 'active',
                        'type': license_type,
                        'starts_at': now.isoformat(),
                        'ends_at': ends_at.isoformat(),
                        'scope': scope
                    },
                    delta={
                        'action': 'assign',
                        'duration_months': months
                    },
                    user_id=user_id,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                
                db.add(audit)
                
                # Calculate operation duration for metrics
                operation_duration = time.time() - start_time
                
                # Track successful license assignment metrics
                metrics.license_operations_total.labels(
                    operation="assign",
                    license_type=license_type,
                    status="success",
                    user_type=actor_type
                ).inc()
                
                metrics.license_assignment_duration_seconds.labels(
                    license_type=license_type,
                    status="success"
                ).observe(operation_duration)
                
                metrics.licenses_active_total.labels(
                    license_type=license_type,
                    environment=getattr(settings, 'env', 'development')
                ).inc()
                
                # Log successful license assignment with Turkish compliance
                logger.info(
                    "lisans_atama_başarılı",
                    license_id=license.id,
                    user_id=user_id,
                    license_type=license_type,
                    duration_months=months,
                    audit_id=audit.id,
                    operation_duration_seconds=round(operation_duration, 3),
                    correlation_id=correlation_id,
                    session_id=session_id,
                    actor_type=actor_type,
                    event_type="license_assigned",
                    compliance="KVKV_GDPR"
                )
                
                return license
                
            except Exception as e:
                # Calculate error duration
                operation_duration = time.time() - start_time
                
                # Track failure metrics
                metrics.license_operations_total.labels(
                    operation="assign",
                    license_type=license_type,
                    status="error",
                    user_type=actor_type
                ).inc()
                
                metrics.license_assignment_duration_seconds.labels(
                    license_type=license_type,
                    status="error"
                ).observe(operation_duration)
                
                # Log error with full context
                logger.error(
                    "lisans_atama_hatası",
                    user_id=user_id,
                    license_type=license_type,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    operation_duration_seconds=round(operation_duration, 3),
                    correlation_id=correlation_id,
                    session_id=session_id,
                    actor_type=actor_type,
                    event_type="license_assignment_error",
                    compliance="KVKV_GDPR",
                    exc_info=True
                )
                
                # Re-raise the exception
                raise
    
    @staticmethod
    def extend_license(
        db: Session,
        license_id: int,
        extension_type: str,
        actor_type: str = "user",
        actor_id: Optional[str] = None,
        reason: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> License:
        """Extend an active license.
        
        Task 4.1 'extend' transition:
        - Only if status='active' and ends_at>=now()
        - On extend, ends_at += duration months (append, not reset)
        - Audit 'license_extended' with delta
        
        Args:
            db: Database session
            license_id: License to extend
            extension_type: Extension duration ('3m', '6m', '12m')
            actor_type: Who initiated the extension
            actor_id: Identifier of the actor
            reason: Reason for extension
            ip_address: Request IP
            user_agent: Request user agent
            
        Returns:
            Extended License object
            
        Raises:
            LicenseStateError: If license cannot be extended
            ValueError: If invalid extension type
        """
        
        # Validate extension type
        if extension_type not in ALLOWED_LICENSE_TYPES:
            raise ValueError(f"Invalid extension type: {extension_type}")
        
        # Get the license
        license = db.query(License).filter(License.id == license_id).first()
        if not license:
            raise ValueError(f"License {license_id} not found")
        
        # Check if license can be extended
        if not license.can_extend():
            raise LicenseStateError(
                f"License {license_id} cannot be extended. "
                f"Status: {license.status}, Expired: {license.is_expired}"
            )
        
        # Calculate extension
        months = LICENSE_DURATION_MAP[extension_type]
        
        # Store old state for audit
        old_state = {
            'ends_at': license.ends_at.isoformat(),
            'type': license.type
        }
        
        # Extend the license (append to current end date)
        old_ends_at = license.ends_at
        license.ends_at = license.ends_at + relativedelta(months=months)
        
        # Create audit log
        audit = LicenseService._create_audit_log(
            db=db,
            license=license,
            event_type='license_extended',
            old_state=old_state,
            new_state={
                'ends_at': license.ends_at.isoformat(),
                'type': license.type
            },
            delta={
                'extension_type': extension_type,
                'extension_months': months,
                'old_ends_at': old_ends_at.isoformat(),
                'new_ends_at': license.ends_at.isoformat(),
                'days_added': (license.ends_at - old_ends_at).days
            },
            user_id=license.user_id,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        db.add(audit)
        
        logger.info(
            f"License {license_id} extended by {months} months",
            extra={
                'license_id': license_id,
                'user_id': license.user_id,
                'extension_months': months,
                'new_ends_at': license.ends_at.isoformat(),
                'audit_id': audit.id
            }
        )
        
        return license
    
    @staticmethod
    def cancel_license(
        db: Session,
        license_id: int,
        reason: str,
        actor_type: str = "user",
        actor_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> License:
        """Cancel an active license.
        
        Task 4.1 'cancel' transition:
        - Set status='canceled', reason, canceled_at=now()
        - Audit 'license_canceled'
        
        Args:
            db: Database session
            license_id: License to cancel
            reason: Cancellation reason
            actor_type: Who initiated the cancellation
            actor_id: Identifier of the actor
            ip_address: Request IP
            user_agent: Request user agent
            
        Returns:
            Canceled License object
            
        Raises:
            LicenseStateError: If license cannot be canceled
        """
        
        # Get the license
        license = db.query(License).filter(License.id == license_id).first()
        if not license:
            raise ValueError(f"License {license_id} not found")
        
        # Check if license can be canceled
        if not license.can_cancel():
            raise LicenseStateError(
                f"License {license_id} cannot be canceled. Status: {license.status}"
            )
        
        # Store old state for audit
        old_state = {
            'status': license.status,
            'canceled_at': None,
            'reason': None
        }
        
        # Cancel the license
        now = datetime.now(timezone.utc)
        license.status = 'canceled'
        license.reason = reason
        license.canceled_at = now
        
        # Create audit log
        audit = LicenseService._create_audit_log(
            db=db,
            license=license,
            event_type='license_canceled',
            old_state=old_state,
            new_state={
                'status': 'canceled',
                'canceled_at': now.isoformat(),
                'reason': reason
            },
            delta={
                'cancellation_reason': reason,
                'days_remaining': (license.ends_at - now).days if license.ends_at > now else 0
            },
            user_id=license.user_id,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        db.add(audit)
        
        logger.info(
            f"License {license_id} canceled",
            extra={
                'license_id': license_id,
                'user_id': license.user_id,
                'reason': reason,
                'audit_id': audit.id
            }
        )
        
        return license
    
    @staticmethod
    def expire_licenses(
        db: Session,
        batch_size: int = 100
    ) -> int:
        """Expire licenses that have passed their end date.
        
        Task 4.1 'expire' transition:
        - When now()>ends_at treat as expired
        - Status may be updated lazily by middleware or via scheduled task
        - Audit 'license_expired'
        
        Args:
            db: Database session
            batch_size: Number of licenses to process at once
            
        Returns:
            Number of licenses expired
        """
        
        now = datetime.now(timezone.utc)
        
        # Find active licenses that should be expired
        expired_licenses = db.query(License).filter(
            and_(
                License.status == 'active',
                License.ends_at <= now
            )
        ).limit(batch_size).all()
        
        count = 0
        for license in expired_licenses:
            # Store old state for audit
            old_state = {
                'status': license.status
            }
            
            # Expire the license
            license.status = 'expired'
            
            # Create audit log
            audit = LicenseService._create_audit_log(
                db=db,
                license=license,
                event_type='license_expired',
                old_state=old_state,
                new_state={
                    'status': 'expired'
                },
                delta={
                    'expired_at': now.isoformat(),
                    'days_overdue': (now - license.ends_at).days
                },
                user_id=license.user_id,
                actor_type='system',
                actor_id='scheduled_task',
                reason='License end date reached'
            )
            
            db.add(audit)
            count += 1
            
            logger.info(
                f"License {license.id} expired",
                extra={
                    'license_id': license.id,
                    'user_id': license.user_id,
                    'ends_at': license.ends_at.isoformat(),
                    'audit_id': audit.id
                }
            )
        
        if count > 0:
            logger.info(f"Expired {count} licenses in batch")
        
        return count
    
    @staticmethod
    def get_active_license(db: Session, user_id: int) -> Optional[License]:
        """Get the active license for a user.
        
        Args:
            db: Database session
            user_id: User ID
            
        Returns:
            Active License or None
        """
        
        now = datetime.now(timezone.utc)
        return db.query(License).filter(
            and_(
                License.user_id == user_id,
                License.status == 'active',
                License.ends_at > now
            )
        ).first()
    
    @staticmethod
    def validate_license_integrity(db: Session, license_id: int) -> bool:
        """Validate the integrity of a license and its audit trail.
        
        Args:
            db: Database session
            license_id: License to validate
            
        Returns:
            True if valid, False otherwise
        """
        
        # Get all audit logs for this license
        audit_logs = db.query(LicenseAudit).filter(
            LicenseAudit.license_id == license_id
        ).order_by(LicenseAudit.id.asc()).all()
        
        if not audit_logs:
            logger.warning(f"No audit logs found for license {license_id}")
            return False
        
        # Verify hash chain
        previous = None
        for audit in audit_logs:
            if not audit.verify_hash_chain(previous):
                logger.error(
                    f"Hash chain broken at audit {audit.id} for license {license_id}"
                )
                return False
            previous = audit
        
        logger.info(f"License {license_id} audit trail verified successfully")
        return True