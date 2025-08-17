"""
Ultra Enterprise Audit Chain Helper Functions
Task 2.10: Banking-level audit chain management with Turkish compliance

This module provides helper functions for:
- Cryptographic audit chain creation and verification
- Canonical JSON serialization for hash consistency
- Turkish regulatory compliance (KVKV/GDPR)
- Enterprise-grade security controls
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import AuditLog
from ..models.validators import AuditChainValidator


class AuditChainHelper:
    """Ultra enterprise audit chain management helper."""
    
    @staticmethod
    def create_audit_entry(
        db: Session,
        action: str,
        user_id: Optional[int] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None
    ) -> AuditLog:
        """
        Create a new audit log entry with proper hash chain integrity.
        
        Args:
            db: Database session
            action: Action being audited (e.g., 'user_create', 'payment_process')
            user_id: ID of user performing action
            resource_type: Type of resource being acted upon
            resource_id: ID of resource being acted upon
            ip_address: Client IP address
            user_agent: Client user agent string
            metadata: Additional audit metadata
            scope_type: Audit scope type for categorization
            scope_id: Audit scope ID for categorization
            
        Returns:
            Created audit log entry
            
        Raises:
            ValueError: If audit entry creation fails validation
        """
        # Get previous hash for chain integrity
        prev_entry = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
        prev_hash = prev_entry.chain_hash if prev_entry else None
        
        # Build canonical payload
        payload = {
            "action": action,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        # Add optional fields in canonical order
        if user_id is not None:
            payload["user_id"] = user_id
        if ip_address:
            payload["ip_address"] = ip_address
        if user_agent:
            payload["user_agent"] = user_agent
        if resource_type:
            payload["resource_type"] = resource_type
        if resource_id:
            payload["resource_id"] = resource_id
        if metadata:
            payload["metadata"] = metadata
        
        # Generate cryptographic hash for chain
        chain_hash = AuditChainValidator.generate_chain_hash(payload, prev_hash)
        
        # Create audit log entry
        audit_log = AuditLog(
            event_type=action,
            scope_type=scope_type or "system",
            scope_id=scope_id or "global", 
            actor_user_id=user_id,
            payload=payload,
            chain_hash=chain_hash,
            prev_chain_hash=prev_hash,
            created_at=datetime.now(timezone.utc)
        )
        
        # Add to session (validation will happen automatically)
        db.add(audit_log)
        
        return audit_log
    
    @staticmethod
    def verify_chain_integrity(
        db: Session, 
        start_id: Optional[int] = None,
        end_id: Optional[int] = None,
        limit: int = 1000
    ) -> Dict[str, Any]:
        """
        Verify audit chain integrity for a range of entries.
        
        Args:
            db: Database session
            start_id: Starting audit log ID (optional)
            end_id: Ending audit log ID (optional)
            limit: Maximum number of entries to verify
            
        Returns:
            Verification report with integrity status and details
        """
        query = db.query(AuditLog).order_by(AuditLog.id)
        
        if start_id:
            query = query.filter(AuditLog.id >= start_id)
        if end_id:
            query = query.filter(AuditLog.id <= end_id)
        
        entries = query.limit(limit).all()
        
        if not entries:
            return {
                "status": "no_entries",
                "verified_count": 0,
                "integrity_violations": [],
                "chain_breaks": []
            }
        
        integrity_violations = []
        chain_breaks = []
        verified_count = 0
        
        for i, entry in enumerate(entries):
            # Get expected previous hash
            expected_prev_hash = entries[i-1].chain_hash if i > 0 else None
            
            # Check chain linkage
            if entry.prev_chain_hash != expected_prev_hash:
                chain_breaks.append({
                    "entry_id": entry.id,
                    "expected_prev_hash": expected_prev_hash,
                    "actual_prev_hash": entry.prev_chain_hash,
                    "position": i
                })
            
            # Verify hash integrity
            expected_hash = AuditChainValidator.generate_chain_hash(
                entry.payload, 
                entry.prev_chain_hash
            )
            
            if entry.chain_hash != expected_hash:
                integrity_violations.append({
                    "entry_id": entry.id,
                    "expected_hash": expected_hash,
                    "actual_hash": entry.chain_hash,
                    "position": i
                })
            else:
                verified_count += 1
        
        # Determine overall status
        if integrity_violations or chain_breaks:
            status = "violations_detected"
        else:
            status = "integrity_verified"
        
        return {
            "status": status,
            "verified_count": verified_count,
            "total_checked": len(entries),
            "integrity_violations": integrity_violations,
            "chain_breaks": chain_breaks,
            "start_id": entries[0].id if entries else None,
            "end_id": entries[-1].id if entries else None
        }
    
    @staticmethod
    def audit_user_action(
        db: Session,
        action: str,
        user_id: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        **kwargs
    ) -> AuditLog:
        """
        Convenience method for auditing user actions.
        
        Args:
            db: Database session
            action: Action being performed
            user_id: ID of user performing action
            ip_address: Client IP address
            user_agent: Client user agent
            **kwargs: Additional audit metadata
            
        Returns:
            Created audit log entry
        """
        return AuditChainHelper.create_audit_entry(
            db=db,
            action=action,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=kwargs,
            scope_type="user",
            scope_id=str(user_id)
        )
    
    @staticmethod
    def audit_financial_action(
        db: Session,
        action: str,
        user_id: int,
        amount_cents: int,
        currency: str,
        invoice_id: Optional[int] = None,
        payment_id: Optional[int] = None,
        **kwargs
    ) -> AuditLog:
        """
        Convenience method for auditing financial actions with Turkish compliance.
        
        Args:
            db: Database session
            action: Financial action being performed
            user_id: ID of user performing action
            amount_cents: Amount in cents for precision
            currency: Currency code (TRY, USD, EUR)
            invoice_id: Related invoice ID
            payment_id: Related payment ID
            **kwargs: Additional audit metadata
            
        Returns:
            Created audit log entry
        """
        from decimal import Decimal
        
        # Prepare financial metadata with Turkish compliance
        financial_metadata = {
            "amount_cents": amount_cents,
            "amount_decimal": str(Decimal(amount_cents) / Decimal('100')),
            "currency": currency,
            **kwargs
        }
        
        if invoice_id:
            financial_metadata["invoice_id"] = invoice_id
        if payment_id:
            financial_metadata["payment_id"] = payment_id
        
        # Add Turkish tax information if applicable
        if currency == "TRY" and "kdv_rate" not in financial_metadata:
            financial_metadata["kdv_rate"] = 20  # Default Turkish VAT rate
        
        return AuditChainHelper.create_audit_entry(
            db=db,
            action=action,
            user_id=user_id,
            resource_type="financial",
            metadata=financial_metadata,
            scope_type="financial",
            scope_id=f"user_{user_id}"
        )
    
    @staticmethod
    def audit_job_action(
        db: Session,
        action: str,
        job_id: int,
        user_id: Optional[int] = None,
        job_type: Optional[str] = None,
        **kwargs
    ) -> AuditLog:
        """
        Convenience method for auditing job/task actions.
        
        Args:
            db: Database session
            action: Job action being performed
            job_id: ID of job being acted upon
            user_id: ID of user performing action
            job_type: Type of job (CAD, CAM, simulation, etc.)
            **kwargs: Additional audit metadata
            
        Returns:
            Created audit log entry
        """
        job_metadata = {
            "job_id": job_id,
            **kwargs
        }
        
        if job_type:
            job_metadata["job_type"] = job_type
        
        return AuditChainHelper.create_audit_entry(
            db=db,
            action=action,
            user_id=user_id,
            resource_type="job",
            resource_id=str(job_id),
            metadata=job_metadata,
            scope_type="job",
            scope_id=str(job_id)
        )
    
    @staticmethod
    def audit_security_event(
        db: Session,
        event_type: str,
        severity: str,
        user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        **kwargs
    ) -> AuditLog:
        """
        Convenience method for auditing security events.
        
        Args:
            db: Database session
            event_type: Type of security event
            severity: Event severity (low, medium, high, critical)
            user_id: ID of affected user (if applicable)
            ip_address: Source IP address
            user_agent: Client user agent
            **kwargs: Additional security metadata
            
        Returns:
            Created audit log entry
        """
        security_metadata = {
            "event_type": event_type,
            "severity": severity,
            **kwargs
        }
        
        return AuditChainHelper.create_audit_entry(
            db=db,
            action=f"security_{event_type}",
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            resource_type="security",
            metadata=security_metadata,
            scope_type="security",
            scope_id="global"
        )


class CanonicalJSONHelper:
    """Helper for canonical JSON operations ensuring hash consistency."""
    
    @staticmethod
    def to_canonical_json(data: Any) -> str:
        """
        Convert data to canonical JSON string for consistent hash generation.
        
        Args:
            data: Data to serialize
            
        Returns:
            Canonical JSON string
        """
        return json.dumps(
            data, 
            sort_keys=True, 
            separators=(',', ':'), 
            ensure_ascii=False
        )
    
    @staticmethod
    def validate_canonical_json(json_str: str) -> bool:
        """
        Validate if JSON string is in canonical format.
        
        Args:
            json_str: JSON string to validate
            
        Returns:
            True if canonical, False otherwise
        """
        try:
            data = json.loads(json_str)
            canonical = CanonicalJSONHelper.to_canonical_json(data)
            return json_str == canonical
        except (json.JSONDecodeError, TypeError):
            return False
    
    @staticmethod
    def normalize_audit_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize audit payload to canonical format.
        
        Args:
            payload: Audit payload to normalize
            
        Returns:
            Normalized payload
        """
        # Ensure timestamp is in ISO format
        if 'timestamp' in payload:
            if isinstance(payload['timestamp'], datetime):
                payload['timestamp'] = payload['timestamp'].isoformat()
        
        # Sort nested objects
        normalized = {}
        for key in sorted(payload.keys()):
            value = payload[key]
            if isinstance(value, dict):
                normalized[key] = CanonicalJSONHelper.normalize_audit_payload(value)
            elif isinstance(value, list):
                # Sort list items if they're dictionaries
                if value and isinstance(value[0], dict):
                    normalized[key] = [
                        CanonicalJSONHelper.normalize_audit_payload(item) 
                        if isinstance(item, dict) else item 
                        for item in value
                    ]
                else:
                    normalized[key] = value
            else:
                normalized[key] = value
        
        return normalized


class TurkishComplianceHelper:
    """Helper for Turkish regulatory compliance (KVKV/GDPR/KDV)."""
    
    @staticmethod
    def audit_gdpr_action(
        db: Session,
        action: str,
        user_id: int,
        data_type: str,
        legal_basis: str,
        ip_address: Optional[str] = None,
        **kwargs
    ) -> AuditLog:
        """
        Audit GDPR/KVKV related actions for Turkish compliance.
        
        Args:
            db: Database session
            action: GDPR action (access, rectification, erasure, etc.)
            user_id: ID of data subject
            data_type: Type of personal data involved
            legal_basis: Legal basis for processing
            ip_address: Client IP address
            **kwargs: Additional compliance metadata
            
        Returns:
            Created audit log entry
        """
        compliance_metadata = {
            "regulation": "KVKV_GDPR",
            "data_type": data_type,
            "legal_basis": legal_basis,
            "processing_purpose": kwargs.get("purpose", "service_provision"),
            **kwargs
        }
        
        return AuditChainHelper.create_audit_entry(
            db=db,
            action=f"gdpr_{action}",
            user_id=user_id,
            ip_address=ip_address,
            resource_type="personal_data",
            metadata=compliance_metadata,
            scope_type="compliance",
            scope_id=f"kvkv_user_{user_id}"
        )
    
    @staticmethod
    def audit_tax_calculation(
        db: Session,
        user_id: int,
        amount_cents: int,
        kdv_rate: int,
        kdv_amount_cents: int,
        invoice_id: Optional[int] = None,
        **kwargs
    ) -> AuditLog:
        """
        Audit Turkish tax (KDV) calculations for compliance.
        
        Args:
            db: Database session
            user_id: ID of user/taxpayer
            amount_cents: Base amount in cents
            kdv_rate: KDV rate percentage
            kdv_amount_cents: Calculated KDV amount in cents
            invoice_id: Related invoice ID
            **kwargs: Additional tax metadata
            
        Returns:
            Created audit log entry
        """
        from decimal import Decimal
        
        tax_metadata = {
            "tax_type": "KDV",
            "base_amount_cents": amount_cents,
            "base_amount_tl": str(Decimal(amount_cents) / Decimal('100')),
            "kdv_rate_percent": kdv_rate,
            "kdv_amount_cents": kdv_amount_cents,
            "kdv_amount_tl": str(Decimal(kdv_amount_cents) / Decimal('100')),
            "total_amount_cents": amount_cents + kdv_amount_cents,
            "currency": "TRY",
            **kwargs
        }
        
        if invoice_id:
            tax_metadata["invoice_id"] = invoice_id
        
        return AuditChainHelper.create_audit_entry(
            db=db,
            action="tax_calculation",
            user_id=user_id,
            resource_type="tax",
            metadata=tax_metadata,
            scope_type="tax",
            scope_id=f"user_{user_id}"
        )


# Export main helper classes
__all__ = [
    "AuditChainHelper",
    "CanonicalJSONHelper", 
    "TurkishComplianceHelper"
]