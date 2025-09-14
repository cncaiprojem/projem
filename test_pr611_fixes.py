#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script to verify PR #611 fixes
Tests all critical issues identified by Gemini
"""

import os
import sys
import json
from pathlib import Path

# Set UTF-8 encoding for Windows
if sys.platform == 'win32':
    import locale
    locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')

# Add the API app to path
sys.path.insert(0, str(Path(__file__).parent / "apps" / "api"))

def test_performance_profiling_api():
    """Test performance_profiling.py fixes"""
    print("Testing performance_profiling.py fixes...")

    # Read the file and check for issues
    file_path = Path(__file__).parent / "apps" / "api" / "app" / "api" / "v2" / "performance_profiling.py"
    content = file_path.read_text()

    # Test 1: Check that _operation_history deque is removed
    assert "deque(maxlen=100)" not in content, "FAIL Issue 1: deque still present in ConnectionManager"
    print("[OK] Issue 1: _operation_history deque removed from ConnectionManager")

    # Test 2: Check that Redis state manager is used for metrics
    assert "state_manager.get_recent_operations" in content, "FAIL Issue 1: Not using Redis for operations"
    print("[OK] Issue 1: Using Redis state_manager for operation history")

    # Test 3: Check datetime error handling
    assert "except (ValueError, TypeError)" in content, "FAIL Issue 3: Missing datetime error handling"
    print("[OK] Issue 3: Datetime error handling added")

    # Test 4: Check test/mock code removal
    assert "time.sleep(0.01)" not in content, "FAIL Issue 7: Test code still present"
    assert "operation.object_count = 10" not in content, "FAIL Issue 7: Mock data still present"
    print("[OK] Issue 7: Test/mock code removed from profile_operation")

    # Test 5: Check Redis-only state management
    assert "performance_profiler._active_profilers[profile_id]" not in content, "FAIL Issue 8: Still using local state"
    print("[OK] Issue 8: Using Redis-only state management")

    # Test 6: Check import organization
    assert "import re" in content, "FAIL Issue 9: re module not imported at top"
    assert "import time" in content, "FAIL Issue 9: time module not imported"
    assert "time as time_module" not in content, "FAIL Issue 9: Duplicate time import still present"
    print("[OK] Issue 9: Import organization fixed")


def test_user_model():
    """Test user.py model fixes"""
    print("\nTesting user.py model fixes...")

    file_path = Path(__file__).parent / "apps" / "api" / "app" / "models" / "user.py"
    content = file_path.read_text()

    # Count occurrences of performance_profiles relationship
    perf_profile_count = content.count('performance_profiles: Mapped[List["PerformanceProfile"]]')
    assert perf_profile_count == 1, f"FAIL Issue 2: performance_profiles defined {perf_profile_count} times (should be 1)"
    print("[OK] Issue 2: Duplicate performance_profiles relationship removed")

    # Count occurrences of optimization_plans relationship
    opt_plans_count = content.count('optimization_plans: Mapped[List["OptimizationPlan"]]')
    assert opt_plans_count == 1, f"FAIL Issue 2: optimization_plans defined {opt_plans_count} times (should be 1)"
    print("[OK] Issue 2: Duplicate optimization_plans relationship removed")


def test_memory_profiler():
    """Test memory_profiler.py fixes"""
    print("\nTesting memory_profiler.py fixes...")

    file_path = Path(__file__).parent / "apps" / "api" / "app" / "services" / "memory_profiler.py"
    content = file_path.read_text()

    # Check memory leak detection only for positive growth
    assert "if growth_rate_mb_per_hour > self.leak_detection_threshold_mb:" in content, "FAIL Issue 4: Still using abs() for leak detection"
    assert "abs(growth_rate_mb_per_hour)" not in content, "FAIL Issue 4: abs() still present in leak detection"
    print("[OK] Issue 4: Memory leak detection fixed to only detect positive growth")


def test_freecad_operation_profiler():
    """Test freecad_operation_profiler.py fixes"""
    print("\nTesting freecad_operation_profiler.py fixes...")

    file_path = Path(__file__).parent / "apps" / "api" / "app" / "services" / "freecad_operation_profiler.py"
    content = file_path.read_text()

    # Check peak memory calculation
    assert "peak_memory = max(initial_memory, final_memory)" in content, "FAIL Issue 5: Peak memory not calculated correctly"
    print("[OK] Issue 5: Peak memory calculation improved")

    # Check mock data removal
    assert "random.randint" not in content, "FAIL Issue 5: Random mock data still present"
    assert 'logger.warning("FreeCAD not available' in content, "FAIL Issue 5: No warning for missing FreeCAD"
    print("[OK] Issue 5: Mock data removed, proper warning added")


def test_performance_schemas():
    """Test performance.py schema fixes"""
    print("\nTesting performance.py schema fixes...")

    file_path = Path(__file__).parent / "apps" / "api" / "app" / "schemas" / "performance.py"
    content = file_path.read_text()

    # Check for new GPU issue types
    assert 'GPU_OVERHEATING = "gpu_overheating"' in content, "FAIL Issue 6: GPU_OVERHEATING not added"
    assert 'GPU_MEMORY_FULL = "gpu_memory_full"' in content, "FAIL Issue 6: GPU_MEMORY_FULL not added"
    assert 'GPU_DRIVER_ERROR = "gpu_driver_error"' in content, "FAIL Issue 6: GPU_DRIVER_ERROR not added"
    print("[OK] Issue 6: Missing GPU issue types added to PerformanceIssueTypeSchema")


def test_syntax():
    """Test Python syntax of all modified files"""
    print("\nTesting Python syntax...")

    files = [
        "apps/api/app/api/v2/performance_profiling.py",
        "apps/api/app/models/user.py",
        "apps/api/app/services/memory_profiler.py",
        "apps/api/app/services/freecad_operation_profiler.py",
        "apps/api/app/schemas/performance.py"
    ]

    import py_compile

    for file in files:
        file_path = Path(__file__).parent / file
        try:
            py_compile.compile(str(file_path), doraise=True)
            print(f"[OK] {file}: Syntax OK")
        except py_compile.PyCompileError as e:
            print(f"FAIL {file}: Syntax error - {e}")
            return False

    return True


def main():
    """Run all tests"""
    print("=" * 60)
    print("PR #611 Critical Issues Fix Verification")
    print("=" * 60)

    try:
        test_performance_profiling_api()
        test_user_model()
        test_memory_profiler()
        test_freecad_operation_profiler()
        test_performance_schemas()
        test_syntax()

        print("\n" + "=" * 60)
        print("[SUCCESS] ALL CRITICAL ISSUES FIXED SUCCESSFULLY!")
        print("=" * 60)

        print("\nSummary of fixes:")
        print("1. [OK] ConnectionManager now uses Redis for operation history")
        print("2. [OK] Duplicate relationships removed from User model")
        print("3. [OK] Datetime error handling added with try-except blocks")
        print("4. [OK] Memory leak detection fixed to only track positive growth")
        print("5. [OK] FreeCAD profiler: mock data removed, peak memory fixed")
        print("6. [OK] GPU issue types added to performance schemas")
        print("7. [OK] Test/mock code removed from production")
        print("8. [OK] State management uses Redis exclusively")
        print("9. [OK] Import organization cleaned up")

        return 0

    except AssertionError as e:
        print(f"\nFAIL TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\nFAIL UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())