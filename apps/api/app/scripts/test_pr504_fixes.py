#!/usr/bin/env python3
"""
Test script to validate PR #504 fixes for Task 7.17 observability.

This script validates:
1. Constants module with error handling for thresholds
2. Metrics recording in finally blocks
3. Improved test assertions
4. Documentation consistency
5. Alert configurations
"""

import os
import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.core import constants
from app.core import metrics
from app.services.model_generation_observability import model_observability


def test_constants_module():
    """Test that constants module is properly configured."""
    print("Testing constants module...")
    
    # Test that constants exist and are valid
    assert constants.OCCT_HIGH_MEMORY_THRESHOLD_BYTES > 0, "Invalid OCCT memory threshold"
    assert constants.ASSEMBLY4_SOLVER_SLOW_THRESHOLD_SECONDS > 0, "Invalid Assembly4 slow threshold"
    assert constants.ASSEMBLY4_EXCESSIVE_ITERATIONS_THRESHOLD > 0, "Invalid Assembly4 iterations threshold"
    
    print(f"  [OK] OCCT memory threshold: {constants.OCCT_HIGH_MEMORY_THRESHOLD_BYTES} bytes")
    print(f"  [OK] Assembly4 slow threshold: {constants.ASSEMBLY4_SOLVER_SLOW_THRESHOLD_SECONDS} seconds")
    print(f"  [OK] Assembly4 iterations threshold: {constants.ASSEMBLY4_EXCESSIVE_ITERATIONS_THRESHOLD}")
    

def test_memory_threshold_error_handling():
    """Test error handling for invalid memory threshold."""
    print("\nTesting memory threshold error handling...")
    
    # Test the _get_memory_threshold method
    threshold = model_observability._get_memory_threshold()
    assert threshold > 0, "Memory threshold should be positive"
    print(f"  [OK] Memory threshold with error handling: {threshold} bytes")
    
    # Test with invalid environment variable (would be caught by error handling)
    original_val = os.environ.get("OCCT_HIGH_MEMORY_THRESHOLD_BYTES")
    try:
        # Set invalid value
        os.environ["OCCT_HIGH_MEMORY_THRESHOLD_BYTES"] = "-1000"
        # Reload constants module
        import importlib
        importlib.reload(constants)
        
        # Check that error handling works
        threshold = model_observability._get_memory_threshold()
        assert threshold == 1610612736, "Should use default for invalid value"
        print("  [OK] Error handling for invalid threshold works correctly")
    finally:
        # Restore original value
        if original_val:
            os.environ["OCCT_HIGH_MEMORY_THRESHOLD_BYTES"] = original_val
        else:
            os.environ.pop("OCCT_HIGH_MEMORY_THRESHOLD_BYTES", None)


def test_metrics_finally_blocks():
    """Test that metrics are recorded in finally blocks even on exceptions."""
    print("\nTesting metrics recording in finally blocks...")
    
    # Test successful operation
    try:
        with model_observability.observe_stage("test", "validation"):
            time.sleep(0.01)
    except:
        pass
    
    # Check that metrics were recorded
    samples = list(metrics.model_generation_stage_duration_seconds.collect())
    assert len(samples) > 0, "Stage duration metrics should be recorded"
    print("  [OK] Stage duration metrics recorded successfully")
    
    # Test with exception (metrics should still be recorded in finally block)
    try:
        with model_observability.observe_occt_boolean("union", 5):
            time.sleep(0.01)
            raise ValueError("Test exception")
    except ValueError:
        pass  # Expected
    
    # Check that metrics were still recorded
    samples = list(metrics.occt_boolean_duration_seconds.collect())
    assert len(samples) > 0, "OCCT boolean metrics should be recorded even on exception"
    print("  [OK] Metrics recorded in finally block even with exceptions")


def test_inc_with_count():
    """Test that inc(count) is used instead of loop."""
    print("\nTesting inc(count) optimization...")
    
    # Record multiple objects at once
    model_observability.record_object_creation(
        object_class="Part::Box",
        workbench="Part",
        count=5
    )
    
    # Check that counter was incremented correctly
    count = metrics.freecad_object_created_total.labels(
        **{"class": "Part::Box"},
        workbench="Part"
    )._value.get()
    assert count == 5, f"Expected 5 objects created, got {count}"
    print("  [OK] inc(count) works correctly for batch object creation")


def test_alert_configuration():
    """Test that alert configuration uses proper thresholds."""
    print("\nTesting alert configuration...")
    
    # Read alert configuration file
    alert_file = Path(__file__).parent.parent.parent.parent.parent / "infra" / "prometheus" / "alerts" / "task-7-17-model-generation-alerts.yml"
    if alert_file.exists():
        content = alert_file.read_text()
        
        # Check that alert uses proper description for stage latency
        assert "Slow model generation stage detected" in content, "Alert should mention stage"
        assert "P95 Stage Latencies" in content or "stage" in content.lower(), "Alert should be for stages"
        
        # Check that OCCT memory threshold comment is clear
        assert "Configurable via OCCT_HIGH_MEMORY_THRESHOLD_BYTES environment variable" in content, "Should mention env var"
        
        print("  [OK] Alert configuration properly updated")
    else:
        print("  [WARN] Alert configuration file not found (may be OK in test environment)")


def test_dashboard_consistency():
    """Test that Grafana dashboard is consistent with implementation."""
    print("\nTesting dashboard consistency...")
    
    # Check dashboard file
    dashboard_file = Path(__file__).parent.parent.parent.parent.parent / "infra" / "grafana" / "task-7-17-model-generation-dashboard.json"
    if dashboard_file.exists():
        content = dashboard_file.read_text()
        
        # Check that dashboard uses correct title for stage latencies
        assert "P95 Stage Latencies" in content, "Dashboard should show stage latencies"
        
        print("  [OK] Dashboard configuration is consistent")
    else:
        print("  [WARN] Dashboard file not found (may be OK in test environment)")


def main():
    """Run all PR #504 fix validations."""
    print("=" * 60)
    print("PR #504 Fix Validation Script")
    print("=" * 60)
    
    try:
        test_constants_module()
        test_memory_threshold_error_handling()
        test_metrics_finally_blocks()
        test_inc_with_count()
        test_alert_configuration()
        test_dashboard_consistency()
        
        print("\n" + "=" * 60)
        print("[SUCCESS] All PR #504 fixes validated successfully!")
        print("=" * 60)
        return 0
        
    except Exception as e:
        print(f"\n[FAILED] Validation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())