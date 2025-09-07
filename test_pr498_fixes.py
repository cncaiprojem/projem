#!/usr/bin/env python
"""Test script to verify PR #498 fixes without dependencies."""

import sys
import os
import re
from pathlib import Path

# Add the apps/api directory to the path
project_root = Path(__file__).parent
api_path = project_root / "apps" / "api"
sys.path.insert(0, str(api_path))

def test_terminal_statuses_constant():
    """Test that TERMINAL_STATUSES constant is properly defined."""
    print("Testing TERMINAL_STATUSES constant...")
    
    # Check SSE file
    sse_file = api_path / "app" / "api" / "v1" / "sse.py"
    with open(sse_file, 'r', encoding='utf-8') as f:
        sse_content = f.read()
    
    # Check for import
    assert "from ...models.enums import JobStatus" in sse_content, "JobStatus not imported in sse.py"
    
    # Check for constant definition
    assert "TERMINAL_STATUSES = {" in sse_content, "TERMINAL_STATUSES not defined in sse.py"
    assert "JobStatus.COMPLETED.value" in sse_content, "JobStatus.COMPLETED not in TERMINAL_STATUSES"
    assert "JobStatus.FAILED.value" in sse_content, "JobStatus.FAILED not in TERMINAL_STATUSES"
    assert "JobStatus.CANCELLED.value" in sse_content, "JobStatus.CANCELLED not in TERMINAL_STATUSES"
    assert "JobStatus.TIMEOUT.value" in sse_content, "JobStatus.TIMEOUT not in TERMINAL_STATUSES"
    
    # Check usage
    assert "if progress.status in TERMINAL_STATUSES:" in sse_content, "TERMINAL_STATUSES not used in sse.py"
    
    print("[OK] SSE file correctly uses TERMINAL_STATUSES constant")
    
    # Check WebSocket file
    ws_file = api_path / "app" / "api" / "v1" / "websocket.py"
    with open(ws_file, 'r', encoding='utf-8') as f:
        ws_content = f.read()
    
    # Check for import
    assert "from ...models.enums import JobStatus" in ws_content, "JobStatus not imported in websocket.py"
    
    # Check for constant definition
    assert "TERMINAL_STATUSES = {" in ws_content, "TERMINAL_STATUSES not defined in websocket.py"
    
    # Check usage
    assert "if progress.status in TERMINAL_STATUSES:" in ws_content, "TERMINAL_STATUSES not used in websocket.py"
    
    print("[OK] WebSocket file correctly uses TERMINAL_STATUSES constant")


def test_phase_mapping_error_logging():
    """Test that phase mapping includes error logging."""
    print("\nTesting phase mapping error logging...")
    
    # Check progress_service.py
    service_file = api_path / "app" / "services" / "progress_service.py"
    with open(service_file, 'r', encoding='utf-8') as f:
        service_content = f.read()
    
    # Check for error logging patterns
    error_patterns = [
        r'phase_enum = PHASE_MAPPINGS\.get\("assembly4", \{\}\)\.get\(phase, None\)',
        r'if phase_enum is None:',
        r'logger\.error\(',
        r'"No phase mapping found for Assembly4Phase',
        r'"No phase mapping found for MaterialPhase',
        r'"No phase mapping found for TopologyPhase',
    ]
    
    for pattern in error_patterns:
        assert re.search(pattern, service_content), f"Pattern not found: {pattern}"
    
    print("[OK] Progress service includes proper error logging for missing mappings")
    
    # Check progress_reporter.py for consistency
    reporter_file = api_path / "app" / "workers" / "progress_reporter.py"
    with open(reporter_file, 'r', encoding='utf-8') as f:
        reporter_content = f.read()
    
    # Check that progress_reporter also has error logging
    assert "logger.error(" in reporter_content, "No error logging in progress_reporter.py"
    assert "No phase mapping found for Assembly4Phase" in reporter_content, "Assembly4Phase error message not in progress_reporter.py"
    
    print("[OK] Progress reporter includes consistent error logging")


def test_format_map_refactoring():
    """Test that nested ternary operator is refactored to dictionary."""
    print("\nTesting format mapping refactoring...")
    
    # Check freecad_with_progress.py
    task_file = api_path / "app" / "tasks" / "freecad_with_progress.py"
    with open(task_file, 'r', encoding='utf-8') as f:
        task_content = f.read()
    
    # Check for FORMAT_MAP dictionary
    assert "FORMAT_MAP = {" in task_content, "FORMAT_MAP dictionary not defined"
    
    # Check that nested ternary is removed
    assert "ExportFormat.STEP if" not in task_content or \
           "ExportFormat.STL if" not in task_content, \
           "Nested ternary operator still present"
    
    # Check for dictionary lookup
    assert "FORMAT_MAP.get(" in task_content, "FORMAT_MAP.get() not used"
    
    # Check for format mappings
    assert '"step": ExportFormat.STEP' in task_content, "STEP format not in FORMAT_MAP"
    assert '"stl": ExportFormat.STL' in task_content, "STL format not in FORMAT_MAP"
    assert '"fcstd": ExportFormat.FCSTD' in task_content, "FCSTD format not in FORMAT_MAP"
    
    print("[OK] Format conversion uses clean dictionary lookup instead of nested ternary")


def test_enum_consistency():
    """Test that JobStatus enum values are used consistently."""
    print("\nTesting enum consistency...")
    
    # Read enums file to verify JobStatus values
    enums_file = api_path / "app" / "models" / "enums.py"
    with open(enums_file, 'r', encoding='utf-8') as f:
        enums_content = f.read()
    
    # Verify JobStatus enum has required values
    required_statuses = ["COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"]
    for status in required_statuses:
        pattern = rf'{status}\s*=\s*"[^"]+"'
        assert re.search(pattern, enums_content), f"JobStatus.{status} not found in enums.py"
    
    print("[OK] JobStatus enum contains all required terminal statuses")


def main():
    """Run all tests."""
    print("=" * 60)
    print("PR #498 Fixes Verification")
    print("=" * 60)
    
    try:
        test_terminal_statuses_constant()
        test_phase_mapping_error_logging()
        test_format_map_refactoring()
        test_enum_consistency()
        
        print("\n" + "=" * 60)
        print("[SUCCESS] All PR #498 fixes verified successfully!")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n[ERROR] Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()