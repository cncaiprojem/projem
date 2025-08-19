"""
KVKV (Turkish GDPR) Compliance Service for Task 3.1

This service ensures compliance with Turkish Personal Data Protection Law (KVKV):
- Data processing consent management
- Data retention policies
- Right to access personal data
- Right to rectification
- Right to erasure (right to be forgotten)
- Data portability
- Consent withdrawal
- Privacy audit logging
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..core.logging import get_logger
from ..models.artefact import Artefact
from ..models.audit_log import AuditLog
from ..models.invoice import Invoice
from ..models.job import Job
from ..models.model import Model
from ..models.security_event import SecurityEvent
from ..models.user import User

logger = get_logger(__name__)


class KVKVComplianceService:
    """Turkish KVKV compliance service for data protection."""

    def __init__(self):
        self.data_retention_days = 2555  # 7 years for financial records
        self.consent_version = "1.0"
        self.processing_purposes = {
            "authentication": "Kullanıcı kimlik doğrulama ve hesap yönetimi",
            "security": "Güvenlik ve dolandırıcılık önleme",
            "service_provision": "Hizmet sunumu ve müşteri desteği",
            "legal_compliance": "Yasal yükümlülüklerin yerine getirilmesi",
            "analytics": "Hizmet iyileştirme ve analitik",
            "marketing": "Pazarlama ve promosyonel iletişim (isteğe bağlı)"
        }

    def record_consent(
        self,
        db: Session,
        user_id: int,
        data_processing_consent: bool,
        marketing_consent: bool,
        ip_address: str | None = None,
        user_agent: str | None = None
    ) -> bool:
        """
        Record user consent for KVKV compliance.
        
        Args:
            db: Database session
            user_id: User ID
            data_processing_consent: Core data processing consent
            marketing_consent: Marketing communication consent
            ip_address: Client IP for audit trail
            user_agent: Client user agent for audit trail
            
        Returns:
            True if consent recorded successfully
        """
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                logger.error("User not found for consent recording", extra={
                    "user_id": user_id
                })
                return False

            now = datetime.now(UTC)

            # Update consent status
            user.data_processing_consent = data_processing_consent
            user.data_processing_consent_at = now if data_processing_consent else None
            user.marketing_consent = marketing_consent
            user.marketing_consent_at = now if marketing_consent else None

            # Update metadata
            if not user.auth_metadata:
                user.auth_metadata = {}

            user.auth_metadata.update({
                "kvkv_consent_version": self.consent_version,
                "consent_recorded_at": now.isoformat(),
                "consent_ip": ip_address,
                "consent_user_agent": user_agent,
                "processing_purposes": [
                    purpose for purpose, consent_given in [
                        ("authentication", data_processing_consent),
                        ("security", data_processing_consent),
                        ("service_provision", data_processing_consent),
                        ("legal_compliance", data_processing_consent),
                        ("marketing", marketing_consent)
                    ] if consent_given
                ]
            })

            # Create audit log entry
            self._create_consent_audit_log(
                db, user_id, data_processing_consent, marketing_consent,
                ip_address, user_agent
            )

            db.commit()

            logger.info("KVKV consent recorded", extra={
                "user_id": user_id,
                "data_processing_consent": data_processing_consent,
                "marketing_consent": marketing_consent,
                "consent_version": self.consent_version
            })

            return True

        except Exception as e:
            db.rollback()
            logger.error("Failed to record KVKV consent", exc_info=True, extra={
                "user_id": user_id,
                "error_type": type(e).__name__
            })
            return False

    def withdraw_consent(
        self,
        db: Session,
        user_id: int,
        consent_type: str,  # "data_processing" or "marketing"
        ip_address: str | None = None,
        user_agent: str | None = None
    ) -> bool:
        """
        Withdraw user consent and handle data according to KVKV requirements.
        
        Args:
            db: Database session
            user_id: User ID
            consent_type: Type of consent to withdraw
            ip_address: Client IP for audit trail
            user_agent: Client user agent for audit trail
            
        Returns:
            True if consent withdrawn successfully
        """
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return False

            now = datetime.now(UTC)

            if consent_type == "data_processing":
                # Withdrawing data processing consent requires account deactivation
                user.data_processing_consent = False
                user.data_processing_consent_at = None
                user.account_status = "deactivated"
                user.deactivated_at = now
                user.deactivation_reason = "KVKV data processing consent withdrawn"

                logger.warning("Data processing consent withdrawn - account deactivated", extra={
                    "user_id": user_id
                })

            elif consent_type == "marketing":
                user.marketing_consent = False
                user.marketing_consent_at = None

                logger.info("Marketing consent withdrawn", extra={
                    "user_id": user_id
                })

            # Update metadata
            if not user.auth_metadata:
                user.auth_metadata = {}

            user.auth_metadata.update({
                f"{consent_type}_consent_withdrawn_at": now.isoformat(),
                f"{consent_type}_consent_withdrawn_ip": ip_address,
                f"{consent_type}_consent_withdrawn_user_agent": user_agent
            })

            # Create audit log entry
            self._create_consent_withdrawal_audit_log(
                db, user_id, consent_type, ip_address, user_agent
            )

            db.commit()
            return True

        except Exception as e:
            db.rollback()
            logger.error("Failed to withdraw consent", exc_info=True, extra={
                "user_id": user_id,
                "consent_type": consent_type,
                "error_type": type(e).__name__
            })
            return False

    def get_user_data_summary(self, db: Session, user_id: int) -> dict[str, Any]:
        """
        Get comprehensive user data summary for KVKV compliance (right to access).
        
        Args:
            db: Database session
            user_id: User ID
            
        Returns:
            Dictionary containing all user data
        """
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return {}

            # Personal data summary
            data_summary = {
                "user_information": {
                    "user_id": user.id,
                    "email": user.email,
                    "full_name": user.full_name,
                    "display_name": user.display_name,
                    "phone": user.phone,
                    "company_name": user.company_name,
                    "tax_no": user.tax_no,
                    "address": user.address,
                    "locale": user.locale.value if user.locale else None,
                    "timezone": user.timezone,
                    "created_at": user.created_at.isoformat() if user.created_at else None,
                    "updated_at": user.updated_at.isoformat() if user.updated_at else None
                },
                "consent_information": {
                    "data_processing_consent": user.data_processing_consent,
                    "data_processing_consent_at": user.data_processing_consent_at.isoformat() if user.data_processing_consent_at else None,
                    "marketing_consent": user.marketing_consent,
                    "marketing_consent_at": user.marketing_consent_at.isoformat() if user.marketing_consent_at else None,
                    "consent_version": user.auth_metadata.get("kvkv_consent_version") if user.auth_metadata else None
                },
                "account_information": {
                    "account_status": user.account_status,
                    "is_active": user.is_active,
                    "is_verified": user.is_verified,
                    "email_verified_at": user.email_verified_at.isoformat() if user.email_verified_at else None,
                    "last_successful_login_at": user.last_successful_login_at.isoformat() if user.last_successful_login_at else None,
                    "total_login_count": user.total_login_count,
                    "deactivated_at": user.deactivated_at.isoformat() if user.deactivated_at else None,
                    "deactivation_reason": user.deactivation_reason
                },
                "security_information": {
                    "failed_login_attempts": user.failed_login_attempts,
                    "account_locked_until": user.account_locked_until.isoformat() if user.account_locked_until else None,
                    "password_updated_at": user.password_updated_at.isoformat() if user.password_updated_at else None,
                    "password_algorithm": user.password_algorithm,
                    "last_login_ip": self._mask_ip_for_export(user.last_login_ip),
                    "last_failed_login_at": user.last_failed_login_at.isoformat() if user.last_failed_login_at else None
                },
                "processing_purposes": self._get_processing_purposes(user),
                "data_retention": {
                    "retention_period_days": self.data_retention_days,
                    "estimated_deletion_date": self._calculate_deletion_date(user)
                }
            }

            # Get related data counts (for transparency and KVKV "right to access" compliance)
            data_summary["related_data_counts"] = {
                "jobs": db.query(Job).filter(Job.user_id == user_id).count(),
                "models": db.query(Model).filter(Model.user_id == user_id).count(),
                "invoices": db.query(Invoice).filter(Invoice.user_id == user_id).count(),
                "security_events": db.query(SecurityEvent).filter(SecurityEvent.user_id == user_id).count(),
                "artefacts": db.query(Artefact).join(Job).filter(Job.user_id == user_id).count(),
                "audit_logs": db.query(AuditLog).filter(AuditLog.actor_user_id == user_id).count()
            }

            logger.info("User data summary generated for KVKV compliance", extra={
                "user_id": user_id,
                "summary_generated_at": datetime.now(UTC).isoformat()
            })

            return data_summary

        except Exception as e:
            logger.error("Failed to generate user data summary", exc_info=True, extra={
                "user_id": user_id,
                "error_type": type(e).__name__
            })
            return {}

    def request_data_deletion(
        self,
        db: Session,
        user_id: int,
        ip_address: str | None = None,
        user_agent: str | None = None
    ) -> bool:
        """
        Process user request for data deletion (right to be forgotten).
        
        Args:
            db: Database session
            user_id: User ID
            ip_address: Client IP for audit trail
            user_agent: Client user agent for audit trail
            
        Returns:
            True if deletion request processed successfully
        """
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return False

            now = datetime.now(UTC)

            # Check if user can request deletion
            if not self._can_request_deletion(user):
                logger.warning("Data deletion request denied - active obligations", extra={
                    "user_id": user_id,
                    "account_status": user.account_status
                })
                return False

            # Mark for deletion (soft delete approach for compliance)
            user.account_status = "pending_deletion"
            user.deactivated_at = now
            user.deactivation_reason = "KVKV data deletion request"

            # Update metadata
            if not user.auth_metadata:
                user.auth_metadata = {}

            user.auth_metadata.update({
                "deletion_requested_at": now.isoformat(),
                "deletion_request_ip": ip_address,
                "deletion_request_user_agent": user_agent,
                "deletion_scheduled_for": (now + timedelta(days=30)).isoformat()  # 30-day grace period
            })

            # Create audit log entry
            self._create_deletion_request_audit_log(
                db, user_id, ip_address, user_agent
            )

            db.commit()

            logger.info("Data deletion request processed", extra={
                "user_id": user_id,
                "deletion_scheduled_for": (now + timedelta(days=30)).isoformat()
            })

            return True

        except Exception as e:
            db.rollback()
            logger.error("Failed to process data deletion request", exc_info=True, extra={
                "user_id": user_id,
                "error_type": type(e).__name__
            })
            return False

    def export_user_data(self, db: Session, user_id: int) -> dict[str, Any]:
        """
        Export user data in portable format (right to data portability).
        
        Args:
            db: Database session
            user_id: User ID
            
        Returns:
            Exportable user data
        """
        try:
            data_summary = self.get_user_data_summary(db, user_id)

            # Add export metadata
            export_data = {
                "export_metadata": {
                    "export_timestamp": datetime.now(UTC).isoformat(),
                    "export_version": "1.0",
                    "kvkv_compliance_version": self.consent_version,
                    "data_controller": "FreeCAD CNC Production Platform",
                    "export_format": "JSON"
                },
                "user_data": data_summary
            }

            logger.info("User data exported for KVKV compliance", extra={
                "user_id": user_id,
                "export_timestamp": export_data["export_metadata"]["export_timestamp"]
            })

            return export_data

        except Exception as e:
            logger.error("Failed to export user data", exc_info=True, extra={
                "user_id": user_id,
                "error_type": type(e).__name__
            })
            return {}

    def _create_consent_audit_log(
        self,
        db: Session,
        user_id: int,
        data_processing_consent: bool,
        marketing_consent: bool,
        ip_address: str | None,
        user_agent: str | None
    ) -> None:
        """Create audit log entry for consent recording."""
        try:
            audit_entry = AuditLog(
                actor_user_id=user_id,
                action="KVKV_CONSENT_RECORDED",
                resource_type="User",
                resource_id=str(user_id),
                details={
                    "data_processing_consent": data_processing_consent,
                    "marketing_consent": marketing_consent,
                    "consent_version": self.consent_version,
                    "ip_address": ip_address,
                    "user_agent": user_agent
                }
            )
            db.add(audit_entry)
            db.flush()
        except Exception:
            logger.error("Failed to create consent audit log", exc_info=True)

    def _create_consent_withdrawal_audit_log(
        self,
        db: Session,
        user_id: int,
        consent_type: str,
        ip_address: str | None,
        user_agent: str | None
    ) -> None:
        """Create audit log entry for consent withdrawal."""
        try:
            audit_entry = AuditLog(
                actor_user_id=user_id,
                action="KVKV_CONSENT_WITHDRAWN",
                resource_type="User",
                resource_id=str(user_id),
                details={
                    "consent_type": consent_type,
                    "withdrawal_timestamp": datetime.now(UTC).isoformat(),
                    "ip_address": ip_address,
                    "user_agent": user_agent
                }
            )
            db.add(audit_entry)
            db.flush()
        except Exception:
            logger.error("Failed to create consent withdrawal audit log", exc_info=True)

    def _create_deletion_request_audit_log(
        self,
        db: Session,
        user_id: int,
        ip_address: str | None,
        user_agent: str | None
    ) -> None:
        """Create audit log entry for data deletion request."""
        try:
            audit_entry = AuditLog(
                actor_user_id=user_id,
                action="KVKV_DATA_DELETION_REQUESTED",
                resource_type="User",
                resource_id=str(user_id),
                details={
                    "deletion_requested_at": datetime.now(UTC).isoformat(),
                    "ip_address": ip_address,
                    "user_agent": user_agent,
                    "grace_period_days": 30
                }
            )
            db.add(audit_entry)
            db.flush()
        except Exception:
            logger.error("Failed to create deletion request audit log", exc_info=True)

    def _get_processing_purposes(self, user: User) -> list[str]:
        """Get list of data processing purposes for the user."""
        purposes = []

        if user.data_processing_consent:
            purposes.extend([
                "authentication",
                "security",
                "service_provision",
                "legal_compliance"
            ])

        if user.marketing_consent:
            purposes.append("marketing")

        return [self.processing_purposes[purpose] for purpose in purposes]

    def _calculate_deletion_date(self, user: User) -> str | None:
        """Calculate estimated data deletion date."""
        if user.account_status == "deactivated" and user.deactivated_at:
            deletion_date = user.deactivated_at + timedelta(days=self.data_retention_days)
            return deletion_date.isoformat()
        return None

    def _can_request_deletion(self, user: User) -> bool:
        """Check if user can request data deletion."""
        # Users with active legal obligations cannot request immediate deletion
        if user.account_status in ["active", "suspended"]:
            return False  # Need to deactivate first

        # Check for pending financial obligations, active jobs, etc.
        # This would include business logic checks

        return True

    def _mask_ip_for_export(self, ip_address: str | None) -> str | None:
        """Mask IP address for data export while maintaining audit trail."""
        if not ip_address:
            return None

        # For exports, we mask the IP but indicate it exists
        return f"{ip_address[:8]}***" if len(ip_address) > 8 else "***"


# Global instance
kvkv_service = KVKVComplianceService()
