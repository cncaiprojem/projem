"""
Job Audit Service for Task 6.8
Append-only audit log with hash-chain for job state transitions.

Features:
- Job-specific audit events with hash-chain integrity
- All job state transitions tracked (created, queued, started, progress, retrying, cancelled, failed, succeeded, dlq_replayed)
- Canonical JSON serialization for consistent hashing
- Tamper-evident chain verification
- Integration with existing audit infrastructure
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..core.logging import get_logger
from ..models.audit_log import AuditLog
from ..models.enums import JobStatus
from ..models.job import Job
from ..services.audit_service import audit_service

logger = get_logger(__name__)


# Job-specific event types for Task 6.8
JOB_EVENT_TYPES = {
    "created": "job_created",
    "queued": "job_queued", 
    "started": "job_started",
    "progress": "job_progress",
    "retrying": "job_retrying",
    "cancelled": "job_cancelled",
    "failed": "job_failed",
    "succeeded": "job_succeeded",
    "dlq_replayed": "job_dlq_replayed",
}

# Reverse mapping for verification (from full event type to short form)
JOB_EVENT_TYPE_REVERSE_MAP = {v: k for k, v in JOB_EVENT_TYPES.items()}


class JobAuditService:
    """
    Specialized audit service for job state transitions.
    Implements Task 6.8 requirements for append-only audit log with hash-chain.
    """
    
    @staticmethod
    def canonical_json(data: Any) -> str:
        """
        Create canonical JSON representation for consistent hashing.
        
        Rules:
        - Stable key ordering (sorted alphabetically)
        - Normalized floats/ints (no trailing zeros)
        - No whitespace between elements
        - UTF-8 encoding
        
        Args:
            data: Data to serialize
            
        Returns:
            Canonical JSON string
        """
        def normalize_value(v: Any) -> Any:
            """Normalize values for canonical representation."""
            if isinstance(v, float):
                # Convert float to string without scientific notation
                if v == int(v):
                    return int(v)
                return float(f"{v:.10f}".rstrip('0').rstrip('.'))
            elif isinstance(v, Decimal):
                # Convert Decimal to normalized string
                normalized = str(v).rstrip('0').rstrip('.')
                return normalized
            elif isinstance(v, datetime):
                # Convert datetime to ISO format with UTC
                if v.tzinfo is None:
                    v = v.replace(tzinfo=timezone.utc)
                return v.isoformat()
            elif isinstance(v, dict):
                # Recursively normalize dictionary
                return {k: normalize_value(v[k]) for k in sorted(v.keys())}
            elif isinstance(v, (list, tuple)):
                # Recursively normalize list/tuple
                return [normalize_value(item) for item in v]
            else:
                return v
        
        normalized_data = normalize_value(data)
        
        return json.dumps(
            normalized_data,
            sort_keys=True,
            separators=(',', ':'),
            ensure_ascii=False
        )
    
    @staticmethod
    def compute_job_chain_hash(
        prev_hash: str,
        job_id: int,
        event_type: str,
        payload: Dict[str, Any]
    ) -> str:
        """
        Compute SHA256 hash for job audit chain.
        
        Formula: chain_hash = sha256(prev_hash || canonical_json(payload))
        
        Args:
            prev_hash: Previous entry's chain_hash (32 zero bytes for first entry)
            job_id: Job ID being audited
            event_type: Type of job event
            payload: Event payload data (must include timestamp for deterministic hashing)
            
        Returns:
            64-character hex SHA256 hash
        """
        # Build canonical payload with job context
        # Note: timestamp must be in payload already for deterministic hashing
        canonical_payload = {
            "job_id": job_id,
            "event_type": event_type,
            **payload
        }
        
        # Create canonical JSON
        canonical_str = JobAuditService.canonical_json(canonical_payload)
        
        # Compute hash: SHA256(prev_hash || canonical_json)
        hash_input = prev_hash + canonical_str
        return hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
    
    @staticmethod
    async def audit_job_created(
        db: Session,
        job: Job,
        actor_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        """
        Audit job creation event.
        
        Args:
            db: Database session
            job: Created job instance
            actor_id: User who created the job
            metadata: Additional metadata
            
        Returns:
            Created audit log entry
        """
        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "job_type": job.type.value if hasattr(job.type, 'value') else str(job.type),
            "priority": job.priority,
            "params": job.params,
            "idempotency_key": job.idempotency_key,
            "metadata": metadata or {}
        }
        
        return await JobAuditService._create_job_audit(
            db=db,
            job_id=job.id,
            event_type="created",
            actor_id=actor_id,
            payload=payload
        )
    
    @staticmethod
    async def audit_job_queued(
        db: Session,
        job_id: int,
        queue_name: str,
        routing_key: str,
        actor_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        """
        Audit job queued to message broker event.
        
        Args:
            db: Database session
            job_id: Job ID
            queue_name: Target queue name
            routing_key: Message routing key
            actor_id: User who queued the job (if manual)
            metadata: Additional metadata
            
        Returns:
            Created audit log entry
        """
        payload = {
            "queue_name": queue_name,
            "routing_key": routing_key,
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {}
        }
        
        return await JobAuditService._create_job_audit(
            db=db,
            job_id=job_id,
            event_type="queued",
            actor_id=actor_id,
            payload=payload
        )
    
    @staticmethod
    async def audit_job_started(
        db: Session,
        job_id: int,
        worker_id: Optional[str] = None,
        task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        """
        Audit job execution start event.
        
        Args:
            db: Database session
            job_id: Job ID
            worker_id: Worker process ID
            task_id: Celery task ID
            metadata: Additional metadata
            
        Returns:
            Created audit log entry
        """
        payload = {
            "worker_id": worker_id,
            "task_id": task_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {}
        }
        
        return await JobAuditService._create_job_audit(
            db=db,
            job_id=job_id,
            event_type="started",
            actor_id=None,  # System action
            payload=payload
        )
    
    @staticmethod
    async def audit_job_progress(
        db: Session,
        job_id: int,
        progress: int,
        message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        """
        Audit job progress update event.
        
        Args:
            db: Database session
            job_id: Job ID
            progress: Progress percentage (0-100)
            message: Progress message
            metadata: Additional metadata
            
        Returns:
            Created audit log entry
        """
        payload = {
            "progress": progress,
            "message": message,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {}
        }
        
        return await JobAuditService._create_job_audit(
            db=db,
            job_id=job_id,
            event_type="progress",
            actor_id=None,  # System action
            payload=payload
        )
    
    @staticmethod
    async def audit_job_retrying(
        db: Session,
        job_id: int,
        retry_count: int,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        next_retry_at: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        """
        Audit job retry event.
        
        Args:
            db: Database session
            job_id: Job ID
            retry_count: Current retry attempt number
            error_code: Error code that triggered retry
            error_message: Error message
            next_retry_at: Scheduled time for next retry
            metadata: Additional metadata
            
        Returns:
            Created audit log entry
        """
        payload = {
            "retry_count": retry_count,
            "error_code": error_code,
            "error_message": error_message,
            "next_retry_at": next_retry_at.isoformat() if next_retry_at else None,
            "retried_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {}
        }
        
        return await JobAuditService._create_job_audit(
            db=db,
            job_id=job_id,
            event_type="retrying",
            actor_id=None,  # System action
            payload=payload
        )
    
    @staticmethod
    async def audit_job_cancelled(
        db: Session,
        job_id: int,
        actor_id: Optional[int] = None,
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        """
        Audit job cancellation event.
        
        Args:
            db: Database session
            job_id: Job ID
            actor_id: User who cancelled the job
            reason: Cancellation reason
            metadata: Additional metadata
            
        Returns:
            Created audit log entry
        """
        payload = {
            "reason": reason,
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
            "cancelled_by": "user" if actor_id else "system",
            "metadata": metadata or {}
        }
        
        return await JobAuditService._create_job_audit(
            db=db,
            job_id=job_id,
            event_type="cancelled",
            actor_id=actor_id,
            payload=payload
        )
    
    @staticmethod
    async def audit_job_failed(
        db: Session,
        job_id: int,
        error_code: str,
        error_message: str,
        traceback: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        """
        Audit job failure event.
        
        Args:
            db: Database session
            job_id: Job ID
            error_code: Error code
            error_message: Error message
            traceback: Full error traceback
            metadata: Additional metadata
            
        Returns:
            Created audit log entry
        """
        payload = {
            "error_code": error_code,
            "error_message": error_message,
            "traceback": traceback[:5000] if traceback else None,  # Limit traceback size
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {}
        }
        
        return await JobAuditService._create_job_audit(
            db=db,
            job_id=job_id,
            event_type="failed",
            actor_id=None,  # System action
            payload=payload
        )
    
    @staticmethod
    async def audit_job_succeeded(
        db: Session,
        job_id: int,
        output_data: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        """
        Audit job success event.
        
        Args:
            db: Database session
            job_id: Job ID
            output_data: Job output data
            duration_ms: Execution duration in milliseconds
            metadata: Additional metadata
            
        Returns:
            Created audit log entry
        """
        payload = {
            "output_summary": _summarize_output(output_data),
            "duration_ms": duration_ms,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {}
        }
        
        return await JobAuditService._create_job_audit(
            db=db,
            job_id=job_id,
            event_type="succeeded",
            actor_id=None,  # System action
            payload=payload
        )
    
    @staticmethod
    async def audit_job_dlq_replayed(
        db: Session,
        job_id: int,
        dlq_name: str,
        original_error: Optional[str] = None,
        replay_attempt: int = 1,
        actor_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        """
        Audit job replay from Dead Letter Queue event.
        
        Args:
            db: Database session
            job_id: Job ID
            dlq_name: Dead Letter Queue name
            original_error: Original error that sent job to DLQ
            replay_attempt: Number of replay attempts
            actor_id: User who initiated replay (if manual)
            metadata: Additional metadata
            
        Returns:
            Created audit log entry
        """
        payload = {
            "dlq_name": dlq_name,
            "original_error": original_error,
            "replay_attempt": replay_attempt,
            "replayed_at": datetime.now(timezone.utc).isoformat(),
            "replayed_by": "user" if actor_id else "system",
            "metadata": metadata or {}
        }
        
        return await JobAuditService._create_job_audit(
            db=db,
            job_id=job_id,
            event_type="dlq_replayed",
            actor_id=actor_id,
            payload=payload
        )
    
    @staticmethod
    async def _create_job_audit(
        db: Session,
        job_id: int,
        event_type: str,
        actor_id: Optional[int],
        payload: Dict[str, Any]
    ) -> AuditLog:
        """
        Internal method to create job audit entry with hash chain.
        
        Args:
            db: Database session
            job_id: Job ID
            event_type: Event type from JOB_EVENT_TYPES
            actor_id: Actor user ID (None for system)
            payload: Event payload
            
        Returns:
            Created audit log entry
        """
        try:
            # Get the previous audit entry for this job
            prev_job_audit = (
                db.query(AuditLog)
                .filter(
                    AuditLog.scope_type == "job",
                    AuditLog.scope_id == job_id
                )
                .order_by(desc(AuditLog.id))
                .first()
            )
            
            # Determine previous hash
            if prev_job_audit:
                # chain_hash is stored in the payload JSON, not as a direct attribute
                prev_hash = prev_job_audit.payload.get("chain_hash", "0" * 64)
            else:
                # First entry for this job - use genesis hash
                prev_hash = "0" * 64
            
            # Compute chain hash for this entry
            chain_hash = JobAuditService.compute_job_chain_hash(
                prev_hash=prev_hash,
                job_id=job_id,
                event_type=event_type,
                payload=payload
            )
            
            # Add chain hash to payload for verification
            payload["chain_hash"] = chain_hash
            payload["prev_hash"] = prev_hash
            
            # Create audit entry using the main audit service
            audit_entry = await audit_service.create_audit_entry(
                db=db,
                event_type=JOB_EVENT_TYPES.get(event_type, f"job_{event_type}"),
                user_id=actor_id,
                scope_type="job",
                scope_id=job_id,
                resource=f"job/{job_id}",
                payload=payload
            )
            
            # Log the audit creation
            logger.info(
                "job_audit_created",
                job_id=job_id,
                event_type=event_type,
                audit_id=audit_entry.id,
                chain_hash=chain_hash[:8] + "..."  # Log first 8 chars of hash
            )
            
            return audit_entry
            
        except Exception as e:
            logger.error(
                "job_audit_creation_failed",
                job_id=job_id,
                event_type=event_type,
                error=str(e)
            )
            raise
    
    @staticmethod
    async def verify_job_audit_chain(
        db: Session,
        job_id: int
    ) -> Dict[str, Any]:
        """
        Verify the audit chain integrity for a specific job.
        
        Args:
            db: Database session
            job_id: Job ID to verify
            
        Returns:
            Verification result with details
        """
        try:
            # Get all audit entries for this job
            audit_entries = (
                db.query(AuditLog)
                .filter(
                    AuditLog.scope_type == "job",
                    AuditLog.scope_id == job_id
                )
                .order_by(AuditLog.id)
                .all()
            )
            
            if not audit_entries:
                return {
                    "valid": True,
                    "job_id": job_id,
                    "entries_checked": 0,
                    "message": "No audit entries found for job"
                }
            
            violations = []
            prev_hash = "0" * 64  # Genesis hash
            
            for i, entry in enumerate(audit_entries):
                # Extract stored hashes from payload
                stored_prev_hash = entry.payload.get("prev_hash")
                stored_chain_hash = entry.payload.get("chain_hash")
                
                # Check if prev_hash matches expected
                if stored_prev_hash != prev_hash:
                    violations.append({
                        "entry_id": entry.id,
                        "position": i,
                        "error": "prev_hash mismatch",
                        "expected": prev_hash,
                        "actual": stored_prev_hash
                    })
                
                # Recompute chain hash
                clean_payload = {
                    k: v for k, v in entry.payload.items()
                    if k not in ["chain_hash", "prev_hash"]
                }
                
                # Use reverse mapping to get short event type safely with robust regex fallback
                short_event_type = JOB_EVENT_TYPE_REVERSE_MAP.get(
                    entry.event_type,
                    re.match(r"^job_(.+)$", entry.event_type).group(1) if re.match(r"^job_(.+)$", entry.event_type) else entry.event_type  # Robust fallback
                )
                
                expected_hash = JobAuditService.compute_job_chain_hash(
                    prev_hash=prev_hash,
                    job_id=job_id,
                    event_type=short_event_type,
                    payload=clean_payload
                )
                
                # Check if chain_hash is correct
                if stored_chain_hash != expected_hash:
                    violations.append({
                        "entry_id": entry.id,
                        "position": i,
                        "error": "chain_hash mismatch",
                        "expected": expected_hash,
                        "actual": stored_chain_hash
                    })
                
                # Update prev_hash for next iteration
                prev_hash = stored_chain_hash or expected_hash
            
            return {
                "valid": len(violations) == 0,
                "job_id": job_id,
                "entries_checked": len(audit_entries),
                "violations": violations,
                "message": "Chain integrity valid" if not violations else f"Found {len(violations)} violations"
            }
            
        except Exception as e:
            logger.error(
                "job_audit_verification_failed",
                job_id=job_id,
                error=str(e)
            )
            return {
                "valid": False,
                "job_id": job_id,
                "error": str(e),
                "message": "Verification failed with error"
            }


def _summarize_output(output_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Create a summary of job output data for audit logging.
    
    Args:
        output_data: Full output data
        
    Returns:
        Summarized output suitable for audit
    """
    if not output_data:
        return {"empty": True}
    
    summary = {
        "keys": list(output_data.keys()),
        "size": len(json.dumps(output_data))
    }
    
    # Include small outputs directly
    if summary["size"] < 1000:
        summary["data"] = output_data
    else:
        # For large outputs, include only metadata
        summary["truncated"] = True
        if "result" in output_data:
            summary["result_type"] = type(output_data["result"]).__name__
        if "error" in output_data:
            summary["has_error"] = True
    
    return summary


# Singleton instance
job_audit_service = JobAuditService()

__all__ = ["JobAuditService", "job_audit_service", "JOB_EVENT_TYPES", "JOB_EVENT_TYPE_REVERSE_MAP"]