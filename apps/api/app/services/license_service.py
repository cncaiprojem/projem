"""
License service for Task 4.1: State transitions and business logic.
Ultra-enterprise implementation with audit trail and validation.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from dateutil.relativedelta import relativedelta
import hashlib
import json

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_, or_

from ..models.license import License
from ..models.license_audit import LicenseAudit
from ..models.user import User
from ..core.logging import get_logger

logger = get_logger(__name__)


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
        """Assign a new license to a user.
        
        Task 4.1 'assign' transition:
        - Create active license with ends_at = starts_at + duration
        - Audit event 'license_assigned'
        - Enforce one active license per user constraint
        
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
        
        # Validate license type
        if license_type not in ['3m', '6m', '12m']:
            raise ValueError(f"Invalid license type: {license_type}")
        
        # Check for existing active license
        existing_active = db.query(License).filter(
            and_(
                License.user_id == user_id,
                License.status == 'active',
                License.ends_at > datetime.now(timezone.utc)
            )
        ).first()
        
        if existing_active:
            raise LicenseStateError(
                f"User {user_id} already has an active license (ID: {existing_active.id}). "
                "Cannot assign another active license."
            )
        
        # Calculate duration
        duration_map = {'3m': 3, '6m': 6, '12m': 12}
        months = duration_map[license_type]
        
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
        
        # Create audit log
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
        
        logger.info(
            f"License assigned to user {user_id}",
            extra={
                'license_id': license.id,
                'license_type': license_type,
                'duration_months': months,
                'audit_id': audit.id
            }
        )
        
        return license
    
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
        if extension_type not in ['3m', '6m', '12m']:
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
        duration_map = {'3m': 3, '6m': 6, '12m': 12}
        months = duration_map[extension_type]
        
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