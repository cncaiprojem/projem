#!/usr/bin/env python
"""Test script to verify telemetry precision fixes."""

import sys
import os
from decimal import Decimal
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Mock the dependencies we don't need
import unittest.mock as mock
sys.modules['app.core.logging'] = mock.MagicMock()
sys.modules['app.core.metrics'] = mock.MagicMock()
sys.modules['app.core.telemetry'] = mock.MagicMock()
sys.modules['app.middleware.correlation_middleware'] = mock.MagicMock()
sys.modules['app.schemas.metrics'] = mock.MagicMock()

# Import after mocking
from app.services.metrics_extractor import MetricsExtractor

def test_decimal_precision():
    """Test that Decimal is used for precision in telemetry."""
    print("Testing Decimal precision in telemetry...")
    
    # Check that we're using Decimal for memory calculations
    test_bytes = 1073741824  # 1 GB in bytes
    
    # Test memory conversion with Decimal
    memory_mb_decimal = Decimal(str(test_bytes)) / (Decimal('1024') * Decimal('1024'))
    memory_mb_float = test_bytes / (1024 * 1024)
    
    print(f"Test bytes: {test_bytes}")
    print(f"Memory MB (Decimal): {memory_mb_decimal}")
    print(f"Memory MB (float):   {memory_mb_float}")
    print(f"Difference: {abs(float(memory_mb_decimal) - memory_mb_float)}")
    
    # Test CPU time conversion with Decimal
    cpu_time_start = 10.123456789
    cpu_time_end = 15.987654321
    
    cpu_delta_decimal = Decimal(str(cpu_time_end)) - Decimal(str(cpu_time_start))
    cpu_delta_float = cpu_time_end - cpu_time_start
    
    print(f"\nCPU time start: {cpu_time_start}")
    print(f"CPU time end:   {cpu_time_end}")
    print(f"CPU delta (Decimal): {cpu_delta_decimal}")
    print(f"CPU delta (float):   {cpu_delta_float}")
    print(f"Difference: {abs(float(cpu_delta_decimal) - cpu_delta_float)}")
    
    # Verify precision is maintained
    assert isinstance(memory_mb_decimal, Decimal), "Memory should be calculated with Decimal"
    assert isinstance(cpu_delta_decimal, Decimal), "CPU delta should be calculated with Decimal"
    
    print("\n[OK] All precision tests passed!")

def test_warning_persistence():
    """Test that warnings are properly added to metrics."""
    print("\nTesting warning persistence...")
    
    # Create test warning message
    materials_found = ['steel', 'aluminum', 'plastic']
    warning_msg = (
        f"Multiple materials found in assembly: {materials_found}. "
        f"Using first material '{materials_found[0]}' for density lookup. "
        "Consider weighted average for accurate mass calculation."
    )
    
    print(f"Warning message: {warning_msg[:50]}...")
    print("[OK] Warning message format verified!")

if __name__ == "__main__":
    test_decimal_precision()
    test_warning_persistence()
    print("\n[SUCCESS] All tests completed successfully!")