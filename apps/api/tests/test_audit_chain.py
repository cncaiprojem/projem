"""
Comprehensive tests for Task 6.8: Audit log hash-chain for job state transitions.

Tests cover:
- Job audit event creation for all state transitions
- Hash-chain integrity verification
- Canonical JSON serialization
- Tamper detection
- Event ordering and completeness
"""

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, List
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Import models and services using proper Python path
# Tests should be run from the project root with proper PYTHONPATH
from app.models.audit_log import AuditLog
from app.models.enums import JobStatus, JobType
from app.models.job import Job
from app.models.user import User
from app.services.job_audit_service import (
    JobAuditService,
    job_audit_service,
    JOB_EVENT_TYPES
)
from app.services.audit_service import audit_service
from app.core.database import Base


class TestJobAuditChain:
    """Test suite for job audit log hash-chain integrity."""
    
    @pytest.fixture
    def db_session(self):
        """Create a test database session."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()
    
    @pytest.fixture
    def test_user(self, db_session: Session):
        """Create a test user."""
        user = User(
            email="test@example.com",
            username="testuser",
            role="user"
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user
    
    @pytest.fixture
    def test_job(self, db_session: Session, test_user: User):
        """Create a test job."""
        job = Job(
            type=JobType.FREECAD_MODEL,
            status=JobStatus.PENDING,
            params={"model": "test_model", "parameters": {"size": 100}},
            user_id=test_user.id,
            priority=1,
            progress=0,
            retry_count=0,
            max_retries=3
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)
        return job
    
    def test_canonical_json_serialization(self):
        """Test canonical JSON serialization for consistent hashing."""
        # Test key ordering
        data1 = {"b": 2, "a": 1, "c": 3}
        data2 = {"c": 3, "a": 1, "b": 2}
        json1 = JobAuditService.canonical_json(data1)
        json2 = JobAuditService.canonical_json(data2)
        assert json1 == json2
        assert json1 == '{"a":1,"b":2,"c":3}'
        
        # Test float normalization
        data_float = {"value": 10.0, "decimal": Decimal("10.50"), "int_float": 5.0}
        json_float = JobAuditService.canonical_json(data_float)
        assert '"value":10' in json_float  # 10.0 -> 10
        assert '"decimal":"10.5"' in json_float  # Decimal normalized
        assert '"int_float":5' in json_float  # 5.0 -> 5
        
        # Test datetime serialization
        dt = datetime(2024, 1, 15, 10, 30, 45, tzinfo=timezone.utc)
        data_dt = {"timestamp": dt}
        json_dt = JobAuditService.canonical_json(data_dt)
        assert '"timestamp":"2024-01-15T10:30:45+00:00"' in json_dt
        
        # Test nested structures
        nested = {
            "outer": {
                "inner": [3, 1, 2],
                "data": {"z": 26, "a": 1}
            }
        }
        json_nested = JobAuditService.canonical_json(nested)
        assert '{"outer":{"data":{"a":1,"z":26},"inner":[3,1,2]}}' == json_nested
    
    def test_compute_job_chain_hash(self):
        """Test hash computation for job audit chain."""
        prev_hash = "0" * 64  # Genesis hash
        job_id = 123
        event_type = "created"
        payload = {
            "job_type": "freecad_model",
            "priority": 1,
            "params": {"model": "test"}
        }
        
        # Compute hash
        hash1 = JobAuditService.compute_job_chain_hash(
            prev_hash, job_id, event_type, payload
        )
        
        # Verify hash format
        assert len(hash1) == 64
        assert all(c in "0123456789abcdef" for c in hash1)
        
        # Verify deterministic
        hash2 = JobAuditService.compute_job_chain_hash(
            prev_hash, job_id, event_type, payload
        )
        assert hash1 == hash2
        
        # Verify different inputs produce different hashes
        hash3 = JobAuditService.compute_job_chain_hash(
            prev_hash, job_id + 1, event_type, payload
        )
        assert hash1 != hash3
    
    @pytest.mark.asyncio
    async def test_audit_job_created(self, db_session: Session, test_job: Job, test_user: User):
        """Test audit log creation for job created event."""
        # Create audit entry
        audit_entry = await job_audit_service.audit_job_created(
            db=db_session,
            job=test_job,
            actor_id=test_user.id,
            metadata={"source": "api", "ip": "127.0.0.1"}
        )
        
        assert audit_entry is not None
        assert audit_entry.event_type == JOB_EVENT_TYPES["created"]
        assert audit_entry.scope_type == "job"
        assert audit_entry.scope_id == test_job.id
        assert audit_entry.actor_user_id == test_user.id
        
        # Verify payload contains required fields
        payload = audit_entry.payload
        assert payload["job_type"] == test_job.type.value
        assert payload["priority"] == test_job.priority
        assert payload["params"] == test_job.params
        assert "chain_hash" in payload
        assert "prev_hash" in payload
    
    @pytest.mark.asyncio
    async def test_audit_job_state_transitions(self, db_session: Session, test_job: Job):
        """Test audit logging for complete job lifecycle."""
        job_id = test_job.id
        
        # 1. Job created
        await job_audit_service.audit_job_created(
            db=db_session,
            job=test_job,
            actor_id=test_job.user_id
        )
        db_session.commit()
        
        # 2. Job queued
        await job_audit_service.audit_job_queued(
            db=db_session,
            job_id=job_id,
            queue_name="model",
            routing_key="jobs.model"
        )
        db_session.commit()
        
        # 3. Job started
        await job_audit_service.audit_job_started(
            db=db_session,
            job_id=job_id,
            worker_id="worker-123",
            task_id="task-456"
        )
        db_session.commit()
        
        # 4. Job progress updates
        for progress in [25, 50, 75]:
            await job_audit_service.audit_job_progress(
                db=db_session,
                job_id=job_id,
                progress=progress,
                message=f"Processing... {progress}%"
            )
            db_session.commit()
        
        # 5. Job succeeded
        await job_audit_service.audit_job_succeeded(
            db=db_session,
            job_id=job_id,
            output_data={"result": "success", "file": "output.stl"},
            duration_ms=5000
        )
        db_session.commit()
        
        # Verify all audit entries were created
        audit_entries = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.scope_type == "job",
                AuditLog.scope_id == job_id
            )
            .order_by(AuditLog.id)
            .all()
        )
        
        assert len(audit_entries) == 6  # created, queued, started, 3 progress, succeeded
        
        # Verify event types
        event_types = [entry.event_type for entry in audit_entries]
        assert event_types[0] == JOB_EVENT_TYPES["created"]
        assert event_types[1] == JOB_EVENT_TYPES["queued"]
        assert event_types[2] == JOB_EVENT_TYPES["started"]
        assert event_types[3] == JOB_EVENT_TYPES["progress"]
        assert event_types[-1] == JOB_EVENT_TYPES["succeeded"]
    
    @pytest.mark.asyncio
    async def test_audit_chain_integrity_verification(self, db_session: Session, test_job: Job):
        """Test verification of audit chain integrity."""
        job_id = test_job.id
        
        # Create a chain of audit entries
        await job_audit_service.audit_job_created(
            db=db_session,
            job=test_job
        )
        db_session.commit()
        
        await job_audit_service.audit_job_queued(
            db=db_session,
            job_id=job_id,
            queue_name="test_queue",
            routing_key="test.key"
        )
        db_session.commit()
        
        await job_audit_service.audit_job_started(
            db=db_session,
            job_id=job_id
        )
        db_session.commit()
        
        # Verify chain integrity
        result = await job_audit_service.verify_job_audit_chain(
            db=db_session,
            job_id=job_id
        )
        
        assert result["valid"] is True
        assert result["job_id"] == job_id
        assert result["entries_checked"] == 3
        assert len(result["violations"]) == 0
    
    @pytest.mark.asyncio
    async def test_audit_chain_tamper_detection(self, db_session: Session, test_job: Job):
        """Test detection of tampering in audit chain."""
        job_id = test_job.id
        
        # Create initial audit entries
        await job_audit_service.audit_job_created(
            db=db_session,
            job=test_job
        )
        db_session.commit()
        
        await job_audit_service.audit_job_queued(
            db=db_session,
            job_id=job_id,
            queue_name="test_queue",
            routing_key="test.key"
        )
        db_session.commit()
        
        # Tamper with an audit entry
        audit_entry = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.scope_type == "job",
                AuditLog.scope_id == job_id
            )
            .first()
        )
        
        # Modify the payload (simulating tampering)
        original_payload = audit_entry.payload.copy()
        audit_entry.payload["tampered"] = True
        db_session.commit()
        
        # Verify chain integrity - should detect tampering
        result = await job_audit_service.verify_job_audit_chain(
            db=db_session,
            job_id=job_id
        )
        
        assert result["valid"] is False
        assert len(result["violations"]) > 0
        
        # Check violation details
        violation = result["violations"][0]
        assert violation["error"] in ["chain_hash mismatch", "prev_hash mismatch"]
    
    @pytest.mark.asyncio
    async def test_audit_job_failure_and_retry(self, db_session: Session, test_job: Job):
        """Test audit logging for job failure and retry scenarios."""
        job_id = test_job.id
        
        # Job fails
        await job_audit_service.audit_job_failed(
            db=db_session,
            job_id=job_id,
            error_code="FREECAD_ERROR",
            error_message="FreeCAD process crashed",
            traceback="Stack trace here..."
        )
        db_session.commit()
        
        # Job retrying
        await job_audit_service.audit_job_retrying(
            db=db_session,
            job_id=job_id,
            retry_count=1,
            error_code="FREECAD_ERROR",
            error_message="Retrying after crash",
            next_retry_at=datetime.now(timezone.utc)
        )
        db_session.commit()
        
        # Verify audit entries
        audit_entries = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.scope_type == "job",
                AuditLog.scope_id == job_id
            )
            .all()
        )
        
        failed_entry = next(
            e for e in audit_entries 
            if e.event_type == JOB_EVENT_TYPES["failed"]
        )
        assert failed_entry.payload["error_code"] == "FREECAD_ERROR"
        
        retry_entry = next(
            e for e in audit_entries 
            if e.event_type == JOB_EVENT_TYPES["retrying"]
        )
        assert retry_entry.payload["retry_count"] == 1
    
    @pytest.mark.asyncio
    async def test_audit_job_cancellation(self, db_session: Session, test_job: Job, test_user: User):
        """Test audit logging for job cancellation."""
        job_id = test_job.id
        
        # User cancels job
        await job_audit_service.audit_job_cancelled(
            db=db_session,
            job_id=job_id,
            actor_id=test_user.id,
            reason="User requested cancellation",
            metadata={"via": "api", "ip": "192.168.1.1"}
        )
        db_session.commit()
        
        # Verify audit entry
        audit_entry = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.scope_type == "job",
                AuditLog.scope_id == job_id,
                AuditLog.event_type == JOB_EVENT_TYPES["cancelled"]
            )
            .first()
        )
        
        assert audit_entry is not None
        assert audit_entry.actor_user_id == test_user.id
        assert audit_entry.payload["reason"] == "User requested cancellation"
        assert audit_entry.payload["cancelled_by"] == "user"
    
    @pytest.mark.asyncio
    async def test_audit_dlq_replay(self, db_session: Session, test_job: Job):
        """Test audit logging for Dead Letter Queue replay."""
        job_id = test_job.id
        
        # Job replayed from DLQ
        await job_audit_service.audit_job_dlq_replayed(
            db=db_session,
            job_id=job_id,
            dlq_name="model_dlq",
            original_error="Connection timeout",
            replay_attempt=1,
            metadata={"manual": False, "auto_replay": True}
        )
        db_session.commit()
        
        # Verify audit entry
        audit_entry = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.scope_type == "job",
                AuditLog.scope_id == job_id,
                AuditLog.event_type == JOB_EVENT_TYPES["dlq_replayed"]
            )
            .first()
        )
        
        assert audit_entry is not None
        assert audit_entry.payload["dlq_name"] == "model_dlq"
        assert audit_entry.payload["original_error"] == "Connection timeout"
        assert audit_entry.payload["replay_attempt"] == 1
        assert audit_entry.payload["replayed_by"] == "system"
    
    @pytest.mark.asyncio
    async def test_audit_chain_ordering(self, db_session: Session, test_job: Job):
        """Test that audit entries maintain correct chronological and hash chain order."""
        job_id = test_job.id
        
        # Create multiple audit entries with timestamps
        events = [
            ("created", {}),
            ("queued", {"queue_name": "test", "routing_key": "test.key"}),
            ("started", {"worker_id": "worker-1"}),
            ("progress", {"progress": 50, "message": "Halfway"}),
            ("succeeded", {"duration_ms": 1000})
        ]
        
        for event_type, extra_args in events:
            method_name = f"audit_job_{event_type}"
            method = getattr(job_audit_service, method_name)
            
            if event_type == "created":
                await method(db_session, test_job)
            else:
                await method(db_session, job_id, **extra_args)
            
            db_session.commit()
            # Small delay to ensure timestamp ordering
            await asyncio.sleep(0.01)
        
        # Retrieve all audit entries
        audit_entries = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.scope_type == "job",
                AuditLog.scope_id == job_id
            )
            .order_by(AuditLog.id)
            .all()
        )
        
        # Verify chronological ordering
        timestamps = [e.created_at for e in audit_entries]
        assert timestamps == sorted(timestamps)
        
        # Verify hash chain continuity
        prev_hash = "0" * 64  # Genesis hash
        for entry in audit_entries:
            stored_prev_hash = entry.payload.get("prev_hash")
            assert stored_prev_hash == prev_hash
            prev_hash = entry.payload.get("chain_hash")
    
    def test_output_summary_generation(self):
        """Test generation of output data summary for audit logs."""
        from app.services.job_audit_service import _summarize_output
        
        # Small output - included directly
        small_output = {"result": "success", "count": 10}
        summary = _summarize_output(small_output)
        assert summary["data"] == small_output
        assert "truncated" not in summary
        
        # Large output - only metadata
        large_output = {
            "result": "success",
            "data": "x" * 1000,  # Large string
            "error": None
        }
        summary = _summarize_output(large_output)
        assert summary["truncated"] is True
        assert summary["result_type"] == "str"
        assert "data" not in summary  # Not included due to size
        
        # Empty output
        summary = _summarize_output(None)
        assert summary == {"empty": True}
        
        # Output with error
        error_output = {"error": "Something went wrong", "details": {}}
        summary = _summarize_output(error_output)
        assert summary["has_error"] is True


class TestAuditChainIntegration:
    """Integration tests for audit chain with real job operations."""
    
    @pytest.mark.asyncio
    async def test_complete_job_lifecycle_audit(self, db_session: Session):
        """Test audit chain for complete job lifecycle from creation to completion."""
        # Create user and job
        user = User(email="worker@test.com", username="worker")
        db_session.add(user)
        db_session.commit()
        
        job = Job(
            type=JobType.CAM_GENERATION,
            status=JobStatus.PENDING,
            params={"input_file": "model.step", "tool": "endmill"},
            user_id=user.id,
            priority=2
        )
        db_session.add(job)
        db_session.commit()
        
        job_id = job.id
        
        # Simulate complete job lifecycle with audit logging
        
        # 1. Created
        await job_audit_service.audit_job_created(db_session, job, user.id)
        job.status = JobStatus.PENDING
        db_session.commit()
        
        # 2. Queued
        await job_audit_service.audit_job_queued(
            db_session, job_id, "cam", "jobs.cam"
        )
        job.status = JobStatus.QUEUED
        job.task_id = "celery-task-123"
        db_session.commit()
        
        # 3. Started by worker
        await job_audit_service.audit_job_started(
            db_session, job_id, "worker-cam-01", job.task_id
        )
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        db_session.commit()
        
        # 4. Progress updates
        for percent in [10, 30, 50, 70, 90]:
            await job_audit_service.audit_job_progress(
                db_session, job_id, percent, 
                f"Processing toolpath: {percent}% complete"
            )
            job.progress = percent
            db_session.commit()
        
        # 5. Completed
        await job_audit_service.audit_job_succeeded(
            db_session, job_id,
            output_data={"gcode_file": "output.nc", "lines": 5000},
            duration_ms=15000
        )
        job.status = JobStatus.COMPLETED
        job.progress = 100
        job.finished_at = datetime.now(timezone.utc)
        db_session.commit()
        
        # Verify complete audit trail
        audit_entries = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.scope_type == "job",
                AuditLog.scope_id == job_id
            )
            .order_by(AuditLog.id)
            .all()
        )
        
        # Should have all events
        assert len(audit_entries) >= 8  # created, queued, started, 5 progress, succeeded
        
        # Verify chain integrity
        result = await job_audit_service.verify_job_audit_chain(db_session, job_id)
        assert result["valid"] is True
        assert result["entries_checked"] == len(audit_entries)
        
        # Verify no events can be removed without detection
        # Simulate removing an entry
        middle_entry = audit_entries[len(audit_entries) // 2]
        db_session.delete(middle_entry)
        db_session.commit()
        
        # Re-verify - should detect break in chain
        result = await job_audit_service.verify_job_audit_chain(db_session, job_id)
        assert result["valid"] is False
        assert len(result["violations"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])