"""
Test suite for verifying core constants ratio conversion (PR #508 fix).

This test ensures that all threshold constants use ratios (0-1) instead of percentages (0-100).
"""

import os
import pytest
from unittest.mock import patch


def test_threshold_constants_are_ratios():
    """Verify that all threshold constants are ratios between 0 and 1."""
    # Import inside test to allow mocking of environment variables
    from app.core.constants import (
        EXPORT_VALIDATION_FAILURE_THRESHOLD,
        AI_PROVIDER_ERROR_THRESHOLD,
        MATERIAL_LIBRARY_ERROR_THRESHOLD,
        WORKBENCH_INCOMPATIBILITY_THRESHOLD,
    )
    
    # All thresholds should be ratios (0.0 to 1.0)
    assert 0.0 <= EXPORT_VALIDATION_FAILURE_THRESHOLD <= 1.0, \
        f"EXPORT_VALIDATION_FAILURE_THRESHOLD should be a ratio, got {EXPORT_VALIDATION_FAILURE_THRESHOLD}"
    assert 0.0 <= AI_PROVIDER_ERROR_THRESHOLD <= 1.0, \
        f"AI_PROVIDER_ERROR_THRESHOLD should be a ratio, got {AI_PROVIDER_ERROR_THRESHOLD}"
    assert 0.0 <= MATERIAL_LIBRARY_ERROR_THRESHOLD <= 1.0, \
        f"MATERIAL_LIBRARY_ERROR_THRESHOLD should be a ratio, got {MATERIAL_LIBRARY_ERROR_THRESHOLD}"
    assert 0.0 <= WORKBENCH_INCOMPATIBILITY_THRESHOLD <= 1.0, \
        f"WORKBENCH_INCOMPATIBILITY_THRESHOLD should be a ratio, got {WORKBENCH_INCOMPATIBILITY_THRESHOLD}"
    
    # Verify default values are as expected (ratios, not percentages)
    assert EXPORT_VALIDATION_FAILURE_THRESHOLD == 0.02, "Default should be 0.02 (2%)"
    assert AI_PROVIDER_ERROR_THRESHOLD == 0.1, "Default should be 0.1 (10%)"
    assert MATERIAL_LIBRARY_ERROR_THRESHOLD == 0.05, "Default should be 0.05 (5%)"
    assert WORKBENCH_INCOMPATIBILITY_THRESHOLD == 0.05, "Default should be 0.05 (5%)"


def test_threshold_constants_from_environment():
    """Test that threshold constants can be overridden via environment variables."""
    test_env = {
        "EXPORT_VALIDATION_FAILURE_THRESHOLD": "0.03",  # 3% as ratio
        "AI_PROVIDER_ERROR_THRESHOLD": "0.15",  # 15% as ratio
        "MATERIAL_LIBRARY_ERROR_THRESHOLD": "0.08",  # 8% as ratio
        "WORKBENCH_INCOMPATIBILITY_THRESHOLD": "0.12",  # 12% as ratio
    }
    
    with patch.dict(os.environ, test_env, clear=False):
        # Re-import to pick up environment variables
        import importlib
        import sys
        if 'app.core.constants' in sys.modules:
            del sys.modules['app.core.constants']
        
        from app.core.constants import (
            EXPORT_VALIDATION_FAILURE_THRESHOLD,
            AI_PROVIDER_ERROR_THRESHOLD,
            MATERIAL_LIBRARY_ERROR_THRESHOLD,
            WORKBENCH_INCOMPATIBILITY_THRESHOLD,
        )
        
        assert EXPORT_VALIDATION_FAILURE_THRESHOLD == 0.03
        assert AI_PROVIDER_ERROR_THRESHOLD == 0.15
        assert MATERIAL_LIBRARY_ERROR_THRESHOLD == 0.08
        assert WORKBENCH_INCOMPATIBILITY_THRESHOLD == 0.12


def test_old_percentage_environment_variables_not_used():
    """Ensure old percentage-based environment variables are no longer used."""
    # Set old-style environment variables (should be ignored)
    old_env = {
        "EXPORT_VALIDATION_FAILURE_THRESHOLD_PERCENT": "5.0",  # Old style
        "AI_PROVIDER_ERROR_THRESHOLD_PERCENT": "20.0",  # Old style
        "MATERIAL_LIBRARY_ERROR_THRESHOLD_PERCENT": "10.0",  # Old style
        "WORKBENCH_INCOMPATIBILITY_THRESHOLD_PERCENT": "15.0",  # Old style
    }
    
    with patch.dict(os.environ, old_env, clear=False):
        # Clear any new-style variables to ensure we're testing defaults
        for key in ["EXPORT_VALIDATION_FAILURE_THRESHOLD", 
                    "AI_PROVIDER_ERROR_THRESHOLD",
                    "MATERIAL_LIBRARY_ERROR_THRESHOLD", 
                    "WORKBENCH_INCOMPATIBILITY_THRESHOLD"]:
            os.environ.pop(key, None)
        
        # Re-import to pick up environment variables
        import importlib
        import sys
        if 'app.core.constants' in sys.modules:
            del sys.modules['app.core.constants']
        
        from app.core.constants import (
            EXPORT_VALIDATION_FAILURE_THRESHOLD,
            AI_PROVIDER_ERROR_THRESHOLD,
            MATERIAL_LIBRARY_ERROR_THRESHOLD,
            WORKBENCH_INCOMPATIBILITY_THRESHOLD,
        )
        
        # Should use defaults, not the old percentage values
        assert EXPORT_VALIDATION_FAILURE_THRESHOLD == 0.02, \
            "Should use default 0.02, not old percentage value"
        assert AI_PROVIDER_ERROR_THRESHOLD == 0.1, \
            "Should use default 0.1, not old percentage value"
        assert MATERIAL_LIBRARY_ERROR_THRESHOLD == 0.05, \
            "Should use default 0.05, not old percentage value"
        assert WORKBENCH_INCOMPATIBILITY_THRESHOLD == 0.05, \
            "Should use default 0.05, not old percentage value"


def test_threshold_validation_boundaries():
    """Test that invalid threshold values are rejected."""
    # Test values outside valid range
    invalid_values = [
        ("EXPORT_VALIDATION_FAILURE_THRESHOLD", "-0.1"),  # Negative
        ("AI_PROVIDER_ERROR_THRESHOLD", "1.5"),  # Greater than 1
        ("MATERIAL_LIBRARY_ERROR_THRESHOLD", "2.0"),  # Way too high
    ]
    
    for env_var, value in invalid_values:
        with patch.dict(os.environ, {env_var: value}):
            # Re-import should use default due to validation failure
            import importlib
            import sys
            if 'app.core.constants' in sys.modules:
                del sys.modules['app.core.constants']
            
            # Import should succeed but use default value
            from app.core import constants
            
            # Verify it falls back to default
            if env_var == "EXPORT_VALIDATION_FAILURE_THRESHOLD":
                assert constants.EXPORT_VALIDATION_FAILURE_THRESHOLD == 0.02
            elif env_var == "AI_PROVIDER_ERROR_THRESHOLD":
                assert constants.AI_PROVIDER_ERROR_THRESHOLD == 0.1
            elif env_var == "MATERIAL_LIBRARY_ERROR_THRESHOLD":
                assert constants.MATERIAL_LIBRARY_ERROR_THRESHOLD == 0.05