#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Verification script for PR #260 fixes.

This script verifies all fixes applied based on Copilot and Gemini feedback:
1. CRITICAL: Exception handling fix in admin_dlq.py (Gemini HIGH priority)
2. Regex pattern matching in test scripts (Copilot suggestions)
3. Function renaming for clarity (Copilot suggestion)
"""

import re
from pathlib import Path
import sys


def test_exception_handling_fix():
    """Test that exception handling is correctly fixed in admin_dlq.py."""
    print("\n=== Testing Exception Handling Fix (Gemini CRITICAL) ===")
    
    admin_dlq_path = Path("apps/api/app/routers/admin_dlq.py")
    if not admin_dlq_path.exists():
        print(f"[FAIL] File not found: {admin_dlq_path}")
        return False
    
    with open(admin_dlq_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the verify_mfa_code function
    func_pattern = r'async def verify_mfa_code\([^)]*\).*?(?=\n\nasync def|\n\n@|\Z)'
    func_match = re.search(func_pattern, content, re.DOTALL)
    
    if not func_match:
        print("[FAIL] Could not find verify_mfa_code function")
        return False
    
    func_content = func_match.group(0)
    
    # Check that try block only wraps the verify_totp_code call
    try_pattern = r'try:\s+is_valid = totp_service\.verify_totp_code\([^)]+\)\s+except Exception'
    if not re.search(try_pattern, func_content, re.DOTALL):
        print("[FAIL] Try block not correctly wrapping only verify_totp_code call")
        return False
    print("[PASS] Try block correctly wraps only verify_totp_code call")
    
    # Check that if not is_valid is OUTSIDE the try block
    if_pattern = r'except Exception.*?\n\s+if not is_valid:'
    if not re.search(if_pattern, func_content, re.DOTALL):
        print("[FAIL] 'if not is_valid' check not placed after exception handler")
        return False
    print("[PASS] 'if not is_valid' check correctly placed outside try block")
    
    # Check that 403 error is raised for invalid MFA (not caught by except)
    error_403_pattern = r'if not is_valid:.*?status_code=403.*?ERR-DLQ-403'
    if not re.search(error_403_pattern, func_content, re.DOTALL):
        print("[FAIL] 403 error not correctly raised for invalid MFA")
        return False
    print("[PASS] 403 error correctly raised for invalid MFA")
    
    # Check that 500 error is only for unexpected exceptions
    error_500_pattern = r'except Exception.*?status_code=500.*?ERR-DLQ-500'
    if not re.search(error_500_pattern, func_content, re.DOTALL):
        print("[FAIL] 500 error not correctly configured for exceptions")
        return False
    print("[PASS] 500 error correctly configured for unexpected exceptions")
    
    return True


def test_function_renaming():
    """Test that verify_admin_only was renamed to verify_admin_role."""
    print("\n=== Testing Function Renaming (Copilot suggestion) ===")
    
    admin_dlq_path = Path("apps/api/app/routers/admin_dlq.py")
    if not admin_dlq_path.exists():
        print(f"[FAIL] File not found: {admin_dlq_path}")
        return False
    
    with open(admin_dlq_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check that verify_admin_role exists
    if not re.search(r'async def verify_admin_role\(', content):
        print("[FAIL] Function not renamed to verify_admin_role")
        return False
    print("[PASS] Function renamed to verify_admin_role")
    
    # Check that verify_admin_only doesn't exist
    if re.search(r'async def verify_admin_only\(', content):
        print("[FAIL] Old function name verify_admin_only still exists")
        return False
    print("[PASS] Old function name verify_admin_only removed")
    
    # Check that dependencies use the new name
    if not re.search(r'Depends\(verify_admin_role\)', content):
        print("[FAIL] Dependencies not updated to use verify_admin_role")
        return False
    print("[PASS] Dependencies updated to use verify_admin_role")
    
    return True


def test_regex_patterns_in_tests():
    """Test that test scripts use regex patterns instead of exact matching."""
    print("\n=== Testing Regex Patterns in Test Scripts (Copilot) ===")
    
    # Test test_pr259_final_fixes.py
    test_file1 = Path("test_pr259_final_fixes.py")
    if test_file1.exists():
        with open(test_file1, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for regex pattern usage
        if not re.search(r're\.search\(.*totp_service.*verify_totp_code', content):
            print("[FAIL] test_pr259_final_fixes.py not using regex for mock checking")
            return False
        print("[PASS] test_pr259_final_fixes.py uses regex for mock checking")
    
    # Test test_pr258_fixes.py
    test_file2 = Path("test_pr258_fixes.py")
    if test_file2.exists():
        with open(test_file2, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for regex patterns with whitespace handling
        if not re.search(r'essential_regexes.*=.*\[', content):
            print("[FAIL] test_pr258_fixes.py not using regex patterns list")
            return False
        print("[PASS] test_pr258_fixes.py uses regex patterns list")
        
        # Check for re.search usage
        if not re.search(r're\.search\(pattern, content\)', content):
            print("[FAIL] test_pr258_fixes.py not using re.search for patterns")
            return False
        print("[PASS] test_pr258_fixes.py uses re.search for pattern matching")
    
    return True


def main():
    """Run all verification tests."""
    print("=" * 70)
    print("PR #260 Fixes Verification")
    print("Testing all Copilot and Gemini feedback fixes")
    print("=" * 70)
    
    tests = [
        ("Exception Handling Fix", test_exception_handling_fix),
        ("Function Renaming", test_function_renaming),
        ("Regex Patterns in Tests", test_regex_patterns_in_tests)
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            passed = test_func()
            results.append((test_name, passed))
        except Exception as e:
            print(f"[ERROR] {test_name} failed with exception: {e}")
            results.append((test_name, False))
    
    print("\n" + "=" * 70)
    print("FINAL RESULTS SUMMARY")
    print("=" * 70)
    
    all_passed = True
    for test_name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status} {test_name}")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 70)
    if all_passed:
        print("[SUCCESS] All PR #260 fixes have been successfully applied!")
        print("\nFixed issues:")
        print("1. Exception handling correctly separates validation from error catching")
        print("2. Function renamed from verify_admin_only to verify_admin_role for clarity")
        print("3. Test scripts use regex patterns for robust matching")
        return 0
    else:
        print("[FAILURE] Some PR #260 fixes were not applied correctly")
        return 1


if __name__ == "__main__":
    sys.exit(main())