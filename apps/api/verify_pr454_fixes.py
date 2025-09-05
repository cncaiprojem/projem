#!/usr/bin/env python3
"""
Verification script for PR #454 fixes.

Tests all critical issues identified by Copilot and Gemini:
1. Decimal precision preservation using str() instead of format()
2. Thread-safe formatting without setlocale()
3. Integer formatting without unnecessary decimals
4. cpu_percent_avg naming consistency
"""

import threading
import time
from decimal import Decimal, ROUND_HALF_UP
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
import os

# Add the app module to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.schemas.metrics import (
    _format_number_locale_independent,
    format_metric_for_display,
    RuntimeTelemetrySchema
)


def test_decimal_precision():
    """Test that Decimal precision is preserved without float conversion."""
    print("Testing Decimal precision preservation...")
    
    # Test case 1: Exact Decimal value
    value = Decimal("123.456789")
    formatted = _format_number_locale_independent(value, decimals=3)
    # Should be "123.457" (rounded) with exact precision
    assert formatted == "123.457", f"Expected '123.457', got '{formatted}'"
    
    # Test case 2: Very precise Decimal
    value = Decimal("999999.999999")
    formatted = _format_number_locale_independent(value, decimals=3)
    assert formatted == "1,000,000.000", f"Expected '1,000,000.000', got '{formatted}'"
    
    # Test case 3: Small Decimal
    value = Decimal("0.0001234")
    formatted = _format_number_locale_independent(value, decimals=3)
    assert formatted == "0.000", f"Expected '0.000', got '{formatted}'"
    
    print("[PASS] Decimal precision tests passed")


def test_integer_formatting():
    """Test that integers don't get unnecessary decimal places."""
    print("Testing integer formatting...")
    
    # Test case 1: Simple integer
    value = 1024
    formatted = format_metric_for_display(value, "en")
    assert formatted == "1,024", f"Expected '1,024' for integer, got '{formatted}'"
    
    # Test case 2: Large integer
    value = 1000000
    formatted = format_metric_for_display(value, "en")
    assert formatted == "1,000,000", f"Expected '1,000,000' for integer, got '{formatted}'"
    
    # Test case 3: Integer in Turkish locale
    value = 1024
    formatted = format_metric_for_display(value, "tr")
    assert formatted == "1.024", f"Expected '1.024' for Turkish integer, got '{formatted}'"
    
    # Test case 4: Float should have decimals
    value = 1024.5
    formatted = format_metric_for_display(value, "en")
    assert formatted == "1,024.500", f"Expected '1,024.500' for float, got '{formatted}'"
    
    # Test case 5: Decimal that is a whole number
    value = Decimal("1024.000")
    formatted = format_metric_for_display(value, "en")
    assert formatted == "1,024", f"Expected '1,024' for whole Decimal, got '{formatted}'"
    
    print("[PASS] Integer formatting tests passed")


def test_thread_safety():
    """Test that formatting is thread-safe without locale changes."""
    print("Testing thread safety...")
    
    results = {}
    errors = []
    
    def format_in_thread(thread_id, locale_code, value):
        """Format a value in a thread."""
        try:
            result = format_metric_for_display(value, locale_code)
            results[thread_id] = result
        except Exception as e:
            errors.append((thread_id, str(e)))
    
    # Create multiple threads with different locales
    threads = []
    test_data = [
        (1, "en", 1234.567),
        (2, "tr", 1234.567),
        (3, "en", 9876),
        (4, "tr", 9876),
        (5, "en", Decimal("5555.555")),
        (6, "tr", Decimal("5555.555")),
    ]
    
    # Run threads concurrently
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = []
        for thread_id, locale_code, value in test_data:
            future = executor.submit(format_in_thread, thread_id, locale_code, value)
            futures.append((thread_id, locale_code, value, future))
        
        # Wait for completion
        for thread_id, locale_code, value, future in futures:
            future.result()
    
    # Check for errors
    assert len(errors) == 0, f"Thread errors occurred: {errors}"
    
    # Verify results
    assert results[1] == "1,234.567", f"Thread 1: Expected '1,234.567', got '{results[1]}'"
    assert results[2] == "1.234,567", f"Thread 2: Expected '1.234,567', got '{results[2]}'"
    assert results[3] == "9,876", f"Thread 3: Expected '9,876', got '{results[3]}'"
    assert results[4] == "9.876", f"Thread 4: Expected '9.876', got '{results[4]}'"
    assert results[5] == "5,555.555", f"Thread 5: Expected '5,555.555', got '{results[5]}'"
    assert results[6] == "5.555,555", f"Thread 6: Expected '5.555,555', got '{results[6]}'"
    
    print("[PASS] Thread safety tests passed")


def test_cpu_metric_naming():
    """Test that cpu_percent_avg is used instead of cpu_percent_peak."""
    print("Testing CPU metric naming...")
    
    # Create telemetry with cpu_percent_avg
    telemetry = RuntimeTelemetrySchema(
        duration_ms=1000,
        cpu_percent_avg=45.6,
        ram_peak_mb=512.0
    )
    
    # Check that the field exists and has correct value
    assert hasattr(telemetry, 'cpu_percent_avg'), "Missing cpu_percent_avg field"
    assert telemetry.cpu_percent_avg == 45.6, f"Expected 45.6, got {telemetry.cpu_percent_avg}"
    
    # Check that old field doesn't exist
    assert not hasattr(telemetry, 'cpu_percent_peak'), "Old cpu_percent_peak field still exists"
    
    # Check Turkish translation
    turkish = telemetry.to_turkish()
    assert 'cpu_ortalama_yüzde' in turkish, "Missing Turkish translation for cpu_percent_avg"
    assert turkish['cpu_ortalama_yüzde'] == 45.6, "Turkish translation has wrong value"
    
    print("[PASS] CPU metric naming tests passed")


def test_locale_independent_formatting():
    """Test the locale-independent formatting function."""
    print("Testing locale-independent formatting...")
    
    # Test with different separator combinations
    test_cases = [
        # (value, thousands_sep, decimal_sep, decimals, expected)
        (1234.567, ',', '.', 3, "1,234.567"),
        (1234.567, '.', ',', 3, "1.234,567"),
        (1234.567, ' ', '.', 2, "1 234.57"),
        (1234567.89, ',', '.', 1, "1,234,567.9"),
        (-1234.567, ',', '.', 3, "-1,234.567"),
        (0.123, ',', '.', 3, "0.123"),
        (1000000, ',', '.', 0, "1,000,000"),
        (Decimal("1234.5678"), ',', '.', 2, "1,234.57"),
    ]
    
    for value, thousands_sep, decimal_sep, decimals, expected in test_cases:
        result = _format_number_locale_independent(
            value, thousands_sep, decimal_sep, decimals
        )
        assert result == expected, f"For {value}: expected '{expected}', got '{result}'"
    
    print("[PASS] Locale-independent formatting tests passed")


def main():
    """Run all verification tests."""
    print("=" * 60)
    print("PR #454 Fixes Verification")
    print("=" * 60)
    
    try:
        test_decimal_precision()
        test_integer_formatting()
        test_thread_safety()
        test_cpu_metric_naming()
        test_locale_independent_formatting()
        
        print("\n" + "=" * 60)
        print("[SUCCESS] ALL TESTS PASSED!")
        print("=" * 60)
        print("\nSummary of fixes verified:")
        print("1. [PASS] Decimal precision preserved using str() instead of format()")
        print("2. [PASS] Thread-safe formatting without setlocale()")
        print("3. [PASS] Integers formatted without unnecessary decimals")
        print("4. [PASS] cpu_percent_avg used instead of cpu_percent_peak")
        print("5. [PASS] Locale-independent formatting works correctly")
        
    except AssertionError as e:
        print("\n" + "=" * 60)
        print("[FAIL] TEST FAILED!")
        print("=" * 60)
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print("\n" + "=" * 60)
        print("[ERROR] UNEXPECTED ERROR!")
        print("=" * 60)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()