"""
Test to verify Python constants and Prometheus alerts are in sync.

This test ensures that the default values in Python match those in Prometheus alerts.
"""

import re
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_prometheus_alerts_match_python_constants():
    """Verify that Prometheus alert thresholds match Python constant defaults."""
    
    # Import Python constants
    from app.core.constants import (
        EXPORT_VALIDATION_FAILURE_THRESHOLD,
        AI_PROVIDER_ERROR_THRESHOLD,
        MATERIAL_LIBRARY_ERROR_THRESHOLD,
        WORKBENCH_INCOMPATIBILITY_THRESHOLD,
    )
    
    # Read Prometheus alerts file
    prometheus_alerts_path = Path(__file__).parent.parent.parent.parent / \
        "infra/prometheus/alerts/task-7-17-model-generation-alerts.yml"
    
    assert prometheus_alerts_path.exists(), f"Prometheus alerts file not found at {prometheus_alerts_path}"
    
    with open(prometheus_alerts_path, 'r') as f:
        content = f.read()
    
    # Extract threshold values from Prometheus config
    # Pattern: ${VARIABLE_NAME:default_value}
    patterns = {
        "EXPORT_VALIDATION_FAILURE_THRESHOLD": r'\$\{EXPORT_VALIDATION_FAILURE_THRESHOLD:([0-9.]+)\}',
        "AI_PROVIDER_ERROR_THRESHOLD": r'\$\{AI_PROVIDER_ERROR_THRESHOLD:([0-9.]+)\}',
        "MATERIAL_LIBRARY_ERROR_THRESHOLD": r'\$\{MATERIAL_LIBRARY_ERROR_THRESHOLD:([0-9.]+)\}',
        "WORKBENCH_INCOMPATIBILITY_THRESHOLD": r'\$\{WORKBENCH_INCOMPATIBILITY_THRESHOLD:([0-9.]+)\}',
    }
    
    prometheus_defaults = {}
    for var_name, pattern in patterns.items():
        match = re.search(pattern, content)
        assert match, f"Could not find {var_name} in Prometheus alerts"
        prometheus_defaults[var_name] = float(match.group(1))
    
    # Compare values
    assert prometheus_defaults["EXPORT_VALIDATION_FAILURE_THRESHOLD"] == EXPORT_VALIDATION_FAILURE_THRESHOLD, \
        f"Export validation threshold mismatch: Prometheus={prometheus_defaults['EXPORT_VALIDATION_FAILURE_THRESHOLD']}, Python={EXPORT_VALIDATION_FAILURE_THRESHOLD}"
    
    assert prometheus_defaults["AI_PROVIDER_ERROR_THRESHOLD"] == AI_PROVIDER_ERROR_THRESHOLD, \
        f"AI provider error threshold mismatch: Prometheus={prometheus_defaults['AI_PROVIDER_ERROR_THRESHOLD']}, Python={AI_PROVIDER_ERROR_THRESHOLD}"
    
    assert prometheus_defaults["MATERIAL_LIBRARY_ERROR_THRESHOLD"] == MATERIAL_LIBRARY_ERROR_THRESHOLD, \
        f"Material library error threshold mismatch: Prometheus={prometheus_defaults['MATERIAL_LIBRARY_ERROR_THRESHOLD']}, Python={MATERIAL_LIBRARY_ERROR_THRESHOLD}"
    
    assert prometheus_defaults["WORKBENCH_INCOMPATIBILITY_THRESHOLD"] == WORKBENCH_INCOMPATIBILITY_THRESHOLD, \
        f"Workbench incompatibility threshold mismatch: Prometheus={prometheus_defaults['WORKBENCH_INCOMPATIBILITY_THRESHOLD']}, Python={WORKBENCH_INCOMPATIBILITY_THRESHOLD}"
    
    print("[PASS] All Python constants and Prometheus alert thresholds are in sync!")
    print(f"  - EXPORT_VALIDATION_FAILURE_THRESHOLD: {EXPORT_VALIDATION_FAILURE_THRESHOLD} (2%)")
    print(f"  - AI_PROVIDER_ERROR_THRESHOLD: {AI_PROVIDER_ERROR_THRESHOLD} (10%)")
    print(f"  - MATERIAL_LIBRARY_ERROR_THRESHOLD: {MATERIAL_LIBRARY_ERROR_THRESHOLD} (5%)")
    print(f"  - WORKBENCH_INCOMPATIBILITY_THRESHOLD: {WORKBENCH_INCOMPATIBILITY_THRESHOLD} (5%)")


def test_environment_variable_names_match():
    """Verify that environment variable names are consistent between Python and Prometheus."""
    
    prometheus_alerts_path = Path(__file__).parent.parent.parent.parent / \
        "infra/prometheus/alerts/task-7-17-model-generation-alerts.yml"
    
    with open(prometheus_alerts_path, 'r') as f:
        content = f.read()
    
    # Check that Prometheus uses the correct (non-percentage) variable names
    correct_vars = [
        "EXPORT_VALIDATION_FAILURE_THRESHOLD",
        "AI_PROVIDER_ERROR_THRESHOLD", 
        "MATERIAL_LIBRARY_ERROR_THRESHOLD",
        "WORKBENCH_INCOMPATIBILITY_THRESHOLD",
    ]
    
    for var in correct_vars:
        assert f"${{{var}:" in content, f"Prometheus should use {var} (without _PERCENT suffix)"
    
    # Check that old percentage variable names are NOT used
    old_vars = [
        "EXPORT_VALIDATION_FAILURE_THRESHOLD_PERCENT",
        "AI_PROVIDER_ERROR_THRESHOLD_PERCENT",
        "MATERIAL_LIBRARY_ERROR_THRESHOLD_PERCENT", 
        "WORKBENCH_INCOMPATIBILITY_THRESHOLD_PERCENT",
    ]
    
    for old_var in old_vars:
        assert f"${{{old_var}:" not in content, f"Prometheus should NOT use old variable {old_var}"
    
    print("[PASS] Environment variable names are consistent (no _PERCENT suffix)")


if __name__ == "__main__":
    test_prometheus_alerts_match_python_constants()
    test_environment_variable_names_match()