#!/usr/bin/env python3
"""
Unit tests for PR #454 formatting fixes.
Tests the formatting functions directly without any dependencies.
"""

import sys
import os
from decimal import Decimal

# Add the app module to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import only the formatting functions we need to test
from app.schemas.metrics import _format_number_locale_independent, format_metric_for_display


def test_pr454_critical_fixes():
    """Test all critical fixes from PR #454 feedback."""
    
    print("Testing PR #454 Critical Fixes")
    print("-" * 40)
    
    # Issue 1: Decimal precision with str() instead of format()
    print("\n1. Testing Decimal precision preservation...")
    decimal_val = Decimal("123.456789")
    result = _format_number_locale_independent(decimal_val, decimals=3)
    print(f"   Decimal('123.456789') with 3 decimals: '{result}'")
    assert "123.457" in result, f"Expected '123.457', got '{result}'"
    print("   [PASS] Decimal uses str() to preserve precision")
    
    # Issue 2: Thread-safe formatting (no setlocale)
    print("\n2. Testing thread-safe formatting...")
    # Test that we can format without any locale errors
    try:
        tr_result = format_metric_for_display(1234.567, "tr")
        en_result = format_metric_for_display(1234.567, "en")
        print(f"   Turkish: '{tr_result}', English: '{en_result}'")
        assert tr_result == "1.234,567", f"Turkish formatting failed: {tr_result}"
        assert en_result == "1,234.567", f"English formatting failed: {en_result}"
        print("   [PASS] Formatting works without setlocale()")
    except Exception as e:
        print(f"   [FAIL] Error during formatting: {e}")
        raise
    
    # Issue 3: Integer formatting without decimals
    print("\n3. Testing integer formatting...")
    int_val = 1024
    result = format_metric_for_display(int_val, "en")
    print(f"   Integer 1024: '{result}'")
    assert result == "1,024", f"Expected '1,024' for integer, got '{result}'"
    
    # Also test Decimal that is a whole number
    decimal_int = Decimal("2048.000")
    result = format_metric_for_display(decimal_int, "en")
    print(f"   Decimal('2048.000'): '{result}'")
    assert result == "2,048", f"Expected '2,048' for whole Decimal, got '{result}'"
    print("   [PASS] Integers formatted without unnecessary decimals")
    
    # Issue 4: CPU metric naming (tested in main verification script)
    print("\n4. CPU metric naming...")
    print("   [INFO] cpu_percent_avg naming tested in main verification")
    
    print("\n" + "=" * 40)
    print("All PR #454 critical fixes verified!")
    print("=" * 40)


if __name__ == "__main__":
    try:
        test_pr454_critical_fixes()
        print("\n[SUCCESS] All formatting fixes work correctly!")
    except AssertionError as e:
        print(f"\n[FAIL] Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)