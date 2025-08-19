"""
Ultra-Enterprise Audit Service with Hash-Chain Integrity
Task 3.11: Banking-level audit logging with Turkish KVKV compliance

Features:
- Cryptographic hash-chain integrity verification
- KVKV/GDPR compliant PII masking
- Correlation ID integration for distributed tracing
- Multi-threaded performance optimization
- Turkish regulatory compliance
- Banking-level security controls
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..core.logging import get_logger
from ..helpers.audit_chain import AuditChainHelper
from ..middleware.correlation_middleware import get_correlation_id, get_session_id
from ..models.audit_log import AuditLog
from ..services.pii_masking_service import DataClassification, MaskingLevel, pii_masking_service

logger = get_logger(__name__)


class AuditService:
    """Ultra-enterprise audit service with hash-chain integrity and KVKV compliance."""

    def __init__(self):
        """Initialize audit service with configuration."""
        self.enable_masking = True
        self.default_classification = DataClassification.PERSONAL
        self.max_payload_size = 10 * 1024  # 10KB max payload

    async def create_audit_entry(
        self,
        db: Session,
        event_type: str,
        user_id: int | None = None,
        scope_type: str = "system",
        scope_id: int | None = None,
        resource: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        payload: dict[str, Any] | None = None,
        classification: DataClassification = DataClassification.PERSONAL,
        correlation_id: str | None = None,
        session_id: str | None = None
    ) -> AuditLog:
        """Create comprehensive audit log entry with hash-chain integrity.
        
        Args:
            db: Database session
            event_type: Type of event being audited
            user_id: ID of user performing action
            scope_type: Audit scope type (user, job, financial, etc.)
            scope_id: Audit scope identifier
            resource: Resource being accessed/modified
            ip_address: Client IP address (will be masked)
            user_agent: Client user agent (will be masked)
            payload: Additional audit data
            classification: Data classification for masking level
            correlation_id: Request correlation ID
            session_id: User session ID
            
        Returns:
            Created audit log entry
            
        Raises:
            SQLAlchemyError: If database operation fails
            ValueError: If audit data is invalid
        """
        try:
            # Use correlation context if not provided
            correlation_id = correlation_id or get_correlation_id()
            session_id = session_id or get_session_id()

            # Validate and prepare payload
            if payload and len(json.dumps(payload)) > self.max_payload_size:
                # Truncate large payloads but preserve metadata
                payload = {
                    "truncated": True,
                    "original_size": len(json.dumps(payload)),
                    "metadata": payload.get("metadata", {}),
                    "summary": str(payload)[:500] + "..." if len(str(payload)) > 500 else str(payload)
                }

            # Apply PII masking to sensitive data
            masked_ip = None
            masked_ua = None
            masked_payload = payload

            if self.enable_masking:
                if ip_address:
                    masked_ip = pii_masking_service.mask_ip_address(
                        ip_address,
                        MaskingLevel.MEDIUM
                    )

                if user_agent:
                    masked_ua = pii_masking_service.mask_user_agent(
                        user_agent,
                        MaskingLevel.LIGHT
                    )

                if payload:
                    masked_payload = pii_masking_service.create_masked_metadata(
                        payload,
                        classification,
                        preserve_keys=["timestamp", "event_id", "version"]
                    )

            # Get previous audit entry for hash chain
            prev_entry = db.query(AuditLog).order_by(desc(AuditLog.id)).first()
            prev_hash = prev_entry.chain_hash if prev_entry else AuditLog.get_genesis_hash()

            # Prepare canonical payload for hash calculation
            canonical_payload = {
                "event_type": event_type,
                "timestamp": datetime.now(UTC).isoformat(),
                "scope_type": scope_type,
                "scope_id": scope_id,
                "user_id": user_id,
                "correlation_id": correlation_id,
                "session_id": session_id,
                "resource": resource,
                "data": masked_payload
            }

            # Remove None values for canonical representation
            canonical_payload = {k: v for k, v in canonical_payload.items() if v is not None}

            # Compute hash chain
            chain_hash = AuditLog.compute_chain_hash(prev_hash, canonical_payload)

            # Create audit log entry
            audit_entry = AuditLog(
                event_type=event_type,
                scope_type=scope_type,
                scope_id=scope_id,
                actor_user_id=user_id,
                correlation_id=correlation_id,
                session_id=session_id,
                resource=resource,
                ip_masked=masked_ip,
                ua_masked=masked_ua,
                payload=canonical_payload,
                prev_chain_hash=prev_hash,
                chain_hash=chain_hash,
                created_at=datetime.now(UTC)
            )

            # Add to database
            db.add(audit_entry)
            db.flush()  # Get ID without committing

            # Log audit creation for monitoring
            self._log_audit_creation(
                audit_entry.id,
                event_type,
                classification,
                correlation_id
            )

            return audit_entry

        except SQLAlchemyError as e:
            logger.error(
                "audit_creation_failed",
                event_type=event_type,
                user_id=user_id,
                error=str(e),
                correlation_id=correlation_id
            )
            raise
        except Exception as e:
            logger.error(
                "audit_creation_error",
                event_type=event_type,
                error_type=type(e).__name__,
                error=str(e),
                correlation_id=correlation_id
            )
            raise ValueError(f"Failed to create audit entry: {str(e)}")

    async def get_audit_logs(
        self,
        db: Session,
        correlation_id: str | None = None,
        user_id: int | None = None,
        event_type: str | None = None,
        scope_type: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
        offset: int = 0
    ) -> dict[str, Any]:
        """Retrieve audit logs with filtering and pagination.
        
        Args:
            db: Database session
            correlation_id: Filter by correlation ID
            user_id: Filter by user ID
            event_type: Filter by event type
            scope_type: Filter by scope type
            start_date: Filter by start date
            end_date: Filter by end date
            limit: Maximum number of results
            offset: Offset for pagination
            
        Returns:
            Dictionary containing audit logs and metadata
        """
        try:
            # Build query
            query = db.query(AuditLog)

            # Apply filters
            if correlation_id:
                query = query.filter(AuditLog.correlation_id == correlation_id)

            if user_id:
                query = query.filter(AuditLog.actor_user_id == user_id)

            if event_type:
                query = query.filter(AuditLog.event_type.ilike(f"%{event_type}%"))

            if scope_type:
                query = query.filter(AuditLog.scope_type == scope_type)

            if start_date:
                query = query.filter(AuditLog.created_at >= start_date)

            if end_date:
                query = query.filter(AuditLog.created_at <= end_date)

            # Get total count for pagination
            total_count = query.count()

            # Apply ordering and pagination
            audit_logs = (
                query.order_by(desc(AuditLog.created_at))
                .limit(limit)
                .offset(offset)
                .all()
            )

            # Format results
            formatted_logs = []
            for log in audit_logs:
                formatted_log = {
                    "id": log.id,
                    "event_type": log.event_type,
                    "scope_type": log.scope_type,
                    "scope_id": log.scope_id,
                    "user_id": log.actor_user_id,
                    "correlation_id": log.correlation_id,
                    "session_id": log.session_id,
                    "resource": log.resource,
                    "ip_masked": log.ip_masked,
                    "ua_masked": log.ua_masked,
                    "payload": log.payload,
                    "chain_hash": log.chain_hash,
                    "created_at": log.created_at.isoformat(),
                    "is_system_action": log.is_system_action
                }
                formatted_logs.append(formatted_log)

            return {
                "logs": formatted_logs,
                "pagination": {
                    "total": total_count,
                    "limit": limit,
                    "offset": offset,
                    "has_more": offset + limit < total_count
                },
                "filters_applied": {
                    "correlation_id": correlation_id,
                    "user_id": user_id,
                    "event_type": event_type,
                    "scope_type": scope_type,
                    "date_range": {
                        "start": start_date.isoformat() if start_date else None,
                        "end": end_date.isoformat() if end_date else None
                    }
                }
            }

        except SQLAlchemyError as e:
            logger.error(
                "audit_retrieval_failed",
                error=str(e),
                correlation_id=correlation_id
            )
            raise

    async def verify_audit_chain_integrity(
        self,
        db: Session,
        start_id: int | None = None,
        end_id: int | None = None,
        limit: int = 1000
    ) -> dict[str, Any]:
        """Verify audit chain integrity for a range of entries.
        
        Args:
            db: Database session
            start_id: Starting audit log ID
            end_id: Ending audit log ID
            limit: Maximum entries to verify
            
        Returns:
            Verification report with integrity status
        """
        try:
            verification_result = AuditChainHelper.verify_chain_integrity(
                db, start_id, end_id, limit
            )

            # Log verification result
            logger.info(
                "audit_chain_verification",
                status=verification_result["status"],
                verified_count=verification_result["verified_count"],
                total_checked=verification_result["total_checked"],
                violations_count=len(verification_result["integrity_violations"]),
                breaks_count=len(verification_result["chain_breaks"])
            )

            return verification_result

        except Exception as e:
            logger.error(
                "audit_verification_failed",
                error=str(e),
                start_id=start_id,
                end_id=end_id
            )
            raise

    async def audit_user_action(
        self,
        db: Session,
        action: str,
        user_id: int,
        resource: str | None = None,
        details: dict[str, Any] | None = None,
        classification: DataClassification = DataClassification.PERSONAL,
        ip_address: str | None = None,
        user_agent: str | None = None
    ) -> AuditLog:
        """Convenience method for auditing user actions.
        
        Args:
            db: Database session
            action: Action performed by user
            user_id: ID of user performing action
            resource: Resource being acted upon
            details: Additional action details
            classification: Data classification for masking
            ip_address: Client IP address
            user_agent: Client user agent
            
        Returns:
            Created audit log entry
        """
        return await self.create_audit_entry(
            db=db,
            event_type=f"user_{action}",
            user_id=user_id,
            scope_type="user",
            scope_id=user_id,
            resource=resource,
            ip_address=ip_address,
            user_agent=user_agent,
            payload=details,
            classification=classification
        )

    async def audit_security_event(
        self,
        db: Session,
        event_type: str,
        severity: str,
        user_id: int | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None
    ) -> AuditLog:
        """Convenience method for auditing security events.
        
        Args:
            db: Database session
            event_type: Type of security event
            severity: Event severity (low, medium, high, critical)
            user_id: ID of affected user
            details: Security event details
            ip_address: Source IP address
            user_agent: Client user agent
            
        Returns:
            Created audit log entry
        """
        security_payload = {
            "severity": severity,
            "event_details": details or {},
            "security_classification": "SENSITIVE"
        }

        return await self.create_audit_entry(
            db=db,
            event_type=f"security_{event_type}",
            user_id=user_id,
            scope_type="security",
            scope_id=None,
            resource="security_event",
            ip_address=ip_address,
            user_agent=user_agent,
            payload=security_payload,
            classification=DataClassification.SENSITIVE
        )

    async def audit_financial_transaction(
        self,
        db: Session,
        action: str,
        user_id: int,
        amount_cents: int,
        currency: str = "TRY",
        invoice_id: int | None = None,
        payment_id: int | None = None,
        details: dict[str, Any] | None = None
    ) -> AuditLog:
        """Convenience method for auditing financial transactions.
        
        Args:
            db: Database session
            action: Financial action performed
            user_id: ID of user performing transaction
            amount_cents: Transaction amount in cents
            currency: Transaction currency
            invoice_id: Related invoice ID
            payment_id: Related payment ID
            details: Additional transaction details
            
        Returns:
            Created audit log entry
        """
        from decimal import Decimal

        financial_payload = {
            "amount_cents": amount_cents,
            "amount_decimal": str(Decimal(amount_cents) / Decimal('100')),
            "currency": currency,
            "invoice_id": invoice_id,
            "payment_id": payment_id,
            "transaction_details": details or {},
            "compliance": "KVKV_GDPR",
            "financial_regulation": "Turkish_Banking_Law"
        }

        return await self.create_audit_entry(
            db=db,
            event_type=f"financial_{action}",
            user_id=user_id,
            scope_type="financial",
            scope_id=invoice_id or payment_id,
            resource="financial_transaction",
            payload=financial_payload,
            classification=DataClassification.RESTRICTED
        )

    def _log_audit_creation(
        self,
        audit_id: int,
        event_type: str,
        classification: DataClassification,
        correlation_id: str | None
    ) -> None:
        """Log audit entry creation for monitoring.
        
        Args:
            audit_id: Created audit log ID
            event_type: Type of audited event
            classification: Data classification level
            correlation_id: Request correlation ID
        """
        logger.info(
            "audit_entry_created",
            audit_id=audit_id,
            event_type=event_type,
            classification=classification.value,
            correlation_id=correlation_id,
            compliance="KVKV_GDPR",
            hash_chain_enabled=True
        )


# Singleton instance for application use
audit_service = AuditService()


# Export main service
__all__ = ["AuditService", "audit_service"]
