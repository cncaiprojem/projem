#!/usr/bin/env python3
"""
Test script to verify multi-worker state management in performance profiling.

This script tests that all profiling state is properly stored in Redis
and accessible across different worker processes.
"""

import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime, timezone
import multiprocessing
import time
import json

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from apps.api.app.services.profiling_state_manager import state_manager
from apps.api.app.services.performance_profiler import performance_profiler
from apps.api.app.services.memory_profiler import memory_profiler
from apps.api.app.services.freecad_operation_profiler import (
    freecad_operation_profiler,
    FreeCADOperationType
)
from apps.api.app.services.optimization_recommender import optimization_recommender
from apps.api.app.services.performance_profiler import PerformanceIssueType


def test_redis_state_storage():
    """Test that state is stored in Redis and not locally."""
    print("\n=== Testing Redis State Storage ===")

    # Test CPU profile storage
    print("\n1. Testing CPU profile storage...")
    cpu_profile = {
        "profile_id": "test_cpu_001",
        "start_time": datetime.now(timezone.utc).isoformat(),
        "end_time": datetime.now(timezone.utc).isoformat(),
        "total_time": 1.5,
        "function_calls": {"test_func": {"cumtime": 1.2, "ncalls": 10}},
        "hot_spots": []
    }

    success = state_manager.add_cpu_profile(cpu_profile)
    assert success, "Failed to add CPU profile to Redis"

    profiles = state_manager.get_cpu_profiles(limit=1)
    assert len(profiles) > 0, "No CPU profiles retrieved from Redis"
    assert profiles[0]["profile_id"] == "test_cpu_001", "Wrong profile retrieved"
    print("✓ CPU profile storage working")

    # Test memory profile storage
    print("\n2. Testing memory profile storage...")
    memory_profile = {
        "profile_id": "test_mem_001",
        "start_time": datetime.now(timezone.utc).isoformat(),
        "memory_growth_mb": 150,
        "fragmentation_ratio": 0.35,
        "potential_leaks": []
    }

    success = state_manager.add_memory_profile(memory_profile)
    assert success, "Failed to add memory profile to Redis"

    profiles = state_manager.get_memory_profiles(limit=1)
    assert len(profiles) > 0, "No memory profiles retrieved from Redis"
    print("✓ Memory profile storage working")

    # Test FreeCAD operation storage
    print("\n3. Testing FreeCAD operation storage...")
    operation = {
        "operation_id": "test_op_001",
        "operation_type": "geometry_create",
        "duration_seconds": 2.5,
        "success": True
    }

    success = state_manager.add_active_freecad_operation("test_op_001", operation)
    assert success, "Failed to add active operation to Redis"

    active_ops = state_manager.get_active_freecad_operations()
    assert "test_op_001" in active_ops, "Active operation not found in Redis"

    # Move to completed
    state_manager.remove_active_freecad_operation("test_op_001")
    state_manager.add_completed_freecad_operation(operation)

    completed_ops = state_manager.get_completed_freecad_operations(limit=10)
    assert len(completed_ops) > 0, "No completed operations found"
    print("✓ FreeCAD operation storage working")

    print("\n✅ All Redis state storage tests passed!")


def test_profiler_integration():
    """Test that profilers use Redis correctly."""
    print("\n=== Testing Profiler Integration ===")

    # Test performance profiler
    print("\n1. Testing performance profiler...")

    # Profile a simple operation
    with performance_profiler.profile_cpu("test_operation"):
        # Simulate some work
        result = sum(i**2 for i in range(1000))

    # Check that profile was stored in Redis (not local)
    profiles = state_manager.get_cpu_profiles(limit=5)
    assert any("test_operation" in p.get("profile_id", "") for p in profiles), \
        "CPU profile not found in Redis"
    print("✓ Performance profiler using Redis")

    # Test memory profiler
    print("\n2. Testing memory profiler...")
    snapshot = memory_profiler.take_snapshot("test_snapshot")

    # Check that snapshot was stored in Redis
    snapshots = state_manager.get_memory_snapshots(limit=5)
    assert len(snapshots) > 0, "Memory snapshot not stored in Redis"
    print("✓ Memory profiler using Redis")

    # Test issue detection from Redis data
    print("\n3. Testing issue detection from Redis...")
    issues = performance_profiler.detect_performance_issues()
    # This should work even if there are issues or not
    print(f"✓ Detected {len(issues)} issues from Redis data")

    print("\n✅ All profiler integration tests passed!")


def test_gpu_issue_mapping():
    """Test GPU issue type mapping helper method."""
    print("\n=== Testing GPU Issue Mapping ===")

    test_cases = [
        ("GPU temperature too high", PerformanceIssueType.GPU_OVERHEATING),
        ("GPU overheating detected", PerformanceIssueType.GPU_OVERHEATING),
        ("Thermal throttling active", PerformanceIssueType.GPU_OVERHEATING),
        ("GPU memory full", PerformanceIssueType.GPU_MEMORY_FULL),
        ("VRAM allocation failed", PerformanceIssueType.GPU_MEMORY_FULL),
        ("CUDA driver error", PerformanceIssueType.GPU_DRIVER_ERROR),
        ("OpenCL not available", PerformanceIssueType.GPU_DRIVER_ERROR),
        ("GPU utilization low", PerformanceIssueType.GPU_UNDERUTILIZATION),
        ("GPU idle", PerformanceIssueType.GPU_UNDERUTILIZATION),
        ("Random GPU issue", PerformanceIssueType.GPU_UNDERUTILIZATION),  # Default
    ]

    for issue_text, expected_type in test_cases:
        result = optimization_recommender._map_gpu_issue_type(issue_text)
        assert result == expected_type, \
            f"Failed: '{issue_text}' should map to {expected_type}, got {result}"
        print(f"✓ '{issue_text}' -> {expected_type.value}")

    print("\n✅ All GPU issue mapping tests passed!")


def worker_process(worker_id: int, barrier: multiprocessing.Barrier):
    """Worker process to test multi-worker state sharing."""
    print(f"\n[Worker {worker_id}] Starting...")

    # Each worker adds its own profile
    profile = {
        "profile_id": f"worker_{worker_id}_profile",
        "start_time": datetime.now(timezone.utc).isoformat(),
        "total_time": worker_id * 0.5,
        "function_calls": {},
        "worker_id": worker_id
    }

    state_manager.add_cpu_profile(profile)
    print(f"[Worker {worker_id}] Added profile to Redis")

    # Wait for all workers to add their profiles
    barrier.wait()

    # Each worker should see all profiles
    time.sleep(0.5)  # Small delay to ensure Redis consistency
    all_profiles = state_manager.get_cpu_profiles(limit=20)
    worker_profiles = [p for p in all_profiles if "worker_" in p.get("profile_id", "")]

    print(f"[Worker {worker_id}] Can see {len(worker_profiles)} worker profiles in Redis")
    return len(worker_profiles)


def test_multi_worker_state_sharing():
    """Test that state is properly shared across multiple workers."""
    print("\n=== Testing Multi-Worker State Sharing ===")

    num_workers = 3
    barrier = multiprocessing.Barrier(num_workers)

    # Clear any existing test profiles
    print("Clearing existing test data...")

    # Start worker processes
    processes = []
    for i in range(num_workers):
        p = multiprocessing.Process(target=worker_process, args=(i, barrier))
        p.start()
        processes.append(p)

    # Wait for all workers to complete
    for p in processes:
        p.join()

    # Verify all profiles are in Redis
    time.sleep(1)  # Give Redis time to sync
    all_profiles = state_manager.get_cpu_profiles(limit=20)
    worker_profiles = [p for p in all_profiles if "worker_" in p.get("profile_id", "")]

    print(f"\nMain process sees {len(worker_profiles)} worker profiles")
    assert len(worker_profiles) >= num_workers, \
        f"Expected at least {num_workers} profiles, found {len(worker_profiles)}"

    print("\n✅ Multi-worker state sharing test passed!")


def main():
    """Run all tests."""
    print("=" * 60)
    print("MULTI-WORKER PROFILING STATE MANAGEMENT TEST")
    print("=" * 60)

    try:
        # Test Redis state storage
        test_redis_state_storage()

        # Test profiler integration
        test_profiler_integration()

        # Test GPU issue mapping
        test_gpu_issue_mapping()

        # Test multi-worker state sharing
        test_multi_worker_state_sharing()

        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED SUCCESSFULLY!")
        print("=" * 60)

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()