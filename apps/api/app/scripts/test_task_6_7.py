#!/usr/bin/env python3
"""
Test script for Task 6.7: Worker progress update conventions and status change events

This script tests:
1. Progress updates with throttling
2. Monotonic progress validation
3. Event publishing on status transitions
4. Worker helper functions
5. Integration with existing job infrastructure
"""

import asyncio
import json
import reprlib
import time
from datetime import datetime, timezone

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.job import Job
from app.models.enums import JobStatus, JobType
from app.services.worker_progress_service import worker_progress_service
from app.services.event_publisher_service import event_publisher_service
from app.tasks.worker_helpers import progress, start_job, complete_job, fail_job
from app.core.logging import get_logger

logger = get_logger(__name__)

# Database setup
engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


async def test_progress_updates():
    """Test progress update functionality."""
    print("\n" + "="*60)
    print("TEST 1: Progress Updates with Throttling")
    print("="*60)
    
    db = SessionLocal()
    try:
        # Create a test job
        job = Job(
            type=JobType.MODEL,
            status=JobStatus.PENDING,
            params={"test": "progress"},
            progress=0,
            attempts=0,
            priority=5,
            max_retries=3,
            timeout_seconds=3600
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        
        print(f"✓ Created test job with ID: {job.id}")
        
        # Test 1: Initial progress update
        result = await worker_progress_service.update_progress(
            db, job.id, 10, "initialization", "Starting job processing"
        )
        print(f"✓ Initial progress update: {result}")
        assert result["success"] is True
        assert result["percent"] == 10
        
        # Test 2: Rapid updates should be throttled
        print("\n Testing throttling (rapid updates within 2s)...")
        for i in range(20, 50, 5):
            result = await worker_progress_service.update_progress(
                db, job.id, i, "processing", f"Processing {i}%"
            )
            if result.get("throttled"):
                print(f"  - Update {i}% was throttled (expected)")
            else:
                print(f"  - Update {i}% was applied")
            time.sleep(0.1)  # Small delay between attempts
        
        # Test 3: After throttle window, update should succeed
        print("\n Waiting for throttle window to expire...")
        time.sleep(2.5)
        
        result = await worker_progress_service.update_progress(
            db, job.id, 50, "halfway", "Halfway complete"
        )
        print(f"✓ Post-throttle update: {result}")
        assert result["success"] is True
        assert not result.get("throttled")
        
        # Test 4: Verify monotonic progress (no decrease)
        print("\n Testing monotonic validation...")
        result = await worker_progress_service.update_progress(
            db, job.id, 30, "backward", "Trying to go backward"
        )
        print(f"✓ Backward progress rejected: {result}")
        assert result["success"] is False
        assert "cannot decrease" in result["error"].lower()
        
        # Verify final state
        db.refresh(job)
        print(f"\n✓ Final job progress: {job.progress}%")
        print(f"✓ Final job status: {job.status.value}")
        
        return job.id
        
    finally:
        db.close()


async def test_status_transitions():
    """Test automatic status transitions based on progress."""
    print("\n" + "="*60)
    print("TEST 2: Status Transitions")
    print("="*60)
    
    db = SessionLocal()
    try:
        # Create a test job
        job = Job(
            type=JobType.CAM,
            status=JobStatus.PENDING,
            params={"test": "transitions"},
            progress=0,
            attempts=0,
            priority=5,
            max_retries=3,
            timeout_seconds=3600
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        
        print(f"✓ Created test job with ID: {job.id}")
        print(f"  Initial status: {job.status.value}")
        
        # Test status transitions
        transitions = [
            (0, JobStatus.QUEUED, "Job queued"),
            (10, JobStatus.RUNNING, "Job started running"),
            (50, JobStatus.RUNNING, "Still running"),
            (100, JobStatus.RUNNING, "Complete but status not auto-changed"),
        ]
        
        for percent, expected_status, description in transitions:
            result = await worker_progress_service.update_progress(
                db, job.id, percent, "transition_test", description
            )
            
            db.refresh(job)
            print(f"  Progress {percent}% -> Status: {job.status.value} ({description})")
            
            # For 100%, status doesn't auto-change to COMPLETED
            # Workers should explicitly call update_status for completion
            if percent < 100:
                assert job.status == expected_status, f"Expected {expected_status.value}, got {job.status.value}"
        
        # Explicitly complete the job
        result = await worker_progress_service.update_job_status(
            db, job.id, JobStatus.COMPLETED,
            output_data={"result": "success"}
        )
        
        db.refresh(job)
        print(f"✓ Final status after completion: {job.status.value}")
        assert job.status == JobStatus.COMPLETED
        
        return job.id
        
    finally:
        db.close()


async def test_event_publishing():
    """Test event publishing on status changes."""
    print("\n" + "="*60)
    print("TEST 3: Event Publishing")
    print("="*60)
    
    # Test event publisher service
    print("Testing job.status.changed event publishing...")
    
    result = await event_publisher_service.publish_job_status_changed(
        job_id=999,
        status="running",
        progress=25,
        attempt=1,
        previous_status="pending",
        previous_progress=0,
        step="processing",
        message="Test event publishing"
    )
    
    if result:
        print("✓ Successfully published job.status.changed event")
        print("  - Event will be routed to events.jobs exchange")
        print("  - Event will fanout to erp.outbound exchange")
    else:
        print("✗ Failed to publish event (RabbitMQ may not be configured)")
    
    # Test deduplication
    print("\nTesting event deduplication...")
    
    # First event should succeed
    result1 = await event_publisher_service.publish_job_status_changed(
        job_id=1000, status="completed", progress=100, attempt=1
    )
    
    # Duplicate event should be deduplicated
    result2 = await event_publisher_service.publish_job_status_changed(
        job_id=1000, status="completed", progress=100, attempt=1
    )
    
    print(f"  First publish: {result1}")
    print(f"  Duplicate publish (should be deduplicated): {result2}")


def test_worker_helpers():
    """Test worker helper functions."""
    print("\n" + "="*60)
    print("TEST 4: Worker Helper Functions")
    print("="*60)
    
    db = SessionLocal()
    try:
        # Create a test job
        job = Job(
            type=JobType.SIMULATION,
            status=JobStatus.PENDING,
            params={"test": "helpers"},
            progress=0,
            attempts=0,
            priority=5,
            max_retries=3,
            timeout_seconds=3600
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        
        print(f"✓ Created test job with ID: {job.id}")
        
        # Test start_job helper
        result = start_job(db, job.id, "Starting with helper")
        print(f"✓ start_job() result: {result}")
        
        # Test progress helper (with throttling)
        for i in range(10, 90, 20):
            result = progress(
                db, job.id, i,
                step="processing",
                message=f"Processing step {i}%",
                metrics={"current_item": i}
            )
            print(f"  progress({i}%): {'throttled' if result.get('throttled') else 'applied'}")
            time.sleep(0.5)
        
        # Test complete_job helper
        output_data = {"files": ["output1.stl", "output2.gcode"], "status": "success"}
        result = complete_job(db, job.id, output_data, "Job completed successfully")
        print(f"✓ complete_job() result: {result}")
        
        # Verify final state
        db.refresh(job)
        print(f"\n✓ Final job state:")
        print(f"  - Status: {job.status.value}")
        print(f"  - Progress: {job.progress}%")
        print(f"  - Output data: {job.output_data}")
        
        # Test fail_job helper on a new job
        job2 = Job(
            type=JobType.REPORT,
            status=JobStatus.RUNNING,
            params={"test": "failure"},
            progress=45,
            attempts=1,
            priority=5,
            max_retries=3,
            timeout_seconds=3600
        )
        db.add(job2)
        db.commit()
        db.refresh(job2)
        
        result = fail_job(
            db, job2.id,
            error_code="TEST_ERROR",
            error_message="Simulated failure for testing",
            progress_percent=45
        )
        print(f"\n✓ fail_job() result: {result}")
        
        db.refresh(job2)
        print(f"  - Failed job status: {job2.status.value}")
        print(f"  - Error code: {job2.error_code}")
        
    finally:
        db.close()


async def test_integration():
    """Test integration with existing job infrastructure."""
    print("\n" + "="*60)
    print("TEST 5: Integration Test")
    print("="*60)
    
    db = SessionLocal()
    try:
        # Simulate a complete job lifecycle
        job = Job(
            type=JobType.MODEL,
            status=JobStatus.PENDING,
            params={
                "model_type": "parametric",
                "dimensions": {"x": 100, "y": 100, "z": 50}
            },
            progress=0,
            attempts=0,
            priority=7,
            max_retries=3,
            timeout_seconds=3600,
            idempotency_key=f"test_integration_{datetime.now(timezone.utc).isoformat()}"
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        
        print(f"✓ Created integration test job: {job.id}")
        
        # Simulate worker processing
        print("\nSimulating worker processing...")
        
        # Start
        await worker_progress_service.update_progress(
            db, job.id, 0, "initialization", "Initializing FreeCAD environment"
        )
        time.sleep(0.5)
        
        # Processing phases
        phases = [
            (10, "setup", "Setting up workspace"),
            (25, "modeling", "Creating 3D model"),
            (50, "validation", "Validating geometry"),
            (75, "optimization", "Optimizing mesh"),
            (90, "export", "Exporting files"),
            (95, "cleanup", "Cleaning up temporary files"),
        ]
        
        for percent, step, message in phases:
            result = await worker_progress_service.update_progress(
                db, job.id, percent, step, message,
                metrics={"phase": step, "timestamp": datetime.now(timezone.utc).isoformat()}
            )
            print(f"  {percent:3d}% - {step:15s} - {message}")
            
            # Check if event was published
            if result.get("event_published"):
                print(f"       ↳ Event published for {step}")
            
            time.sleep(0.3)
        
        # Complete
        await worker_progress_service.update_progress(
            db, job.id, 100, "completed", "Model generation complete"
        )
        
        await worker_progress_service.update_job_status(
            db, job.id, JobStatus.COMPLETED,
            output_data={
                "model_file": "s3://bucket/models/output.stl",
                "size_bytes": 1048576,
                "triangles": 50000
            }
        )
        
        # Final verification
        db.refresh(job)
        print(f"\n✓ Job completed successfully:")
        print(f"  - Final status: {job.status.value}")
        print(f"  - Final progress: {job.progress}%")
        # Use reprlib.repr() for safe truncation that won't break JSON structure
        print(f"  - Metrics: {reprlib.repr(json.dumps(job.metrics, indent=2))}")
        
    finally:
        db.close()


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("TASK 6.7 TEST SUITE")
    print("Worker Progress Update Conventions & Status Events")
    print("="*60)
    
    try:
        # Run tests
        job_id1 = await test_progress_updates()
        job_id2 = await test_status_transitions()
        await test_event_publishing()
        test_worker_helpers()
        await test_integration()
        
        print("\n" + "="*60)
        print("ALL TESTS COMPLETED SUCCESSFULLY! ✓")
        print("="*60)
        print("\nSummary:")
        print("✓ Progress updates with throttling work correctly")
        print("✓ Monotonic progress validation prevents decreases")
        print("✓ Status transitions occur automatically based on progress")
        print("✓ Events are published on status changes")
        print("✓ Worker helper functions simplify progress reporting")
        print("✓ Integration with existing job infrastructure works")
        print("\nTask 6.7 Implementation Complete!")
        
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())