#!/usr/bin/env python3
"""
Test script to verify all PR #255 critical fixes have been applied.
Tests for NameErrors and infinite loop prevention.
"""

import ast
import re
import sys
from pathlib import Path


def test_admin_dlq_fixes():
    """Test all critical fixes in admin_dlq.py"""
    print("Testing admin_dlq.py fixes...")
    
    admin_dlq_path = Path("apps/api/app/routers/admin_dlq.py")
    if not admin_dlq_path.exists():
        print(f"ERROR: {admin_dlq_path} not found!")
        return False
    
    with open(admin_dlq_path, 'r', encoding='utf-8') as f:
        code = f.read()
    
    # Test 1: Syntax validity
    try:
        ast.parse(code)
        print("  [PASS] Syntax is valid")
    except SyntaxError as e:
        print(f"  [FAIL] Syntax error: {e}")
        return False
    
    # Test 2: verify_admin_only function exists
    if 'async def verify_admin_only(' in code:
        print("  [PASS] verify_admin_only function is defined")
    else:
        print("  [FAIL] verify_admin_only function is missing")
        return False
    
    # Test 3: verify_mfa_code helper function exists
    if 'async def verify_mfa_code(' in code:
        print("  [PASS] verify_mfa_code helper function is defined")
    else:
        print("  [FAIL] verify_mfa_code helper function is missing")
        return False
    
    # Test 4: dlq_service injected in list_dlq_queues
    list_match = re.search(r'async def list_dlq_queues\((.*?)\):', code, re.MULTILINE | re.DOTALL)
    if list_match and 'dlq_service' in list_match.group(1):
        print("  [PASS] dlq_service injected in list_dlq_queues")
    else:
        print("  [FAIL] dlq_service NOT injected in list_dlq_queues")
        return False
    
    # Test 5: dlq_service injected in peek_dlq_messages
    peek_match = re.search(r'async def peek_dlq_messages\((.*?)\):', code, re.MULTILINE | re.DOTALL)
    if peek_match and 'dlq_service' in peek_match.group(1):
        print("  [PASS] dlq_service injected in peek_dlq_messages")
    else:
        print("  [FAIL] dlq_service NOT injected in peek_dlq_messages")
        return False
    
    # Test 6: dlq_service already present in replay_dlq_messages
    replay_match = re.search(r'async def replay_dlq_messages\((.*?)\):', code, re.MULTILINE | re.DOTALL)
    if replay_match and 'dlq_service' in replay_match.group(1):
        print("  [PASS] dlq_service injected in replay_dlq_messages")
    else:
        print("  [FAIL] dlq_service NOT injected in replay_dlq_messages")
        return False
    
    # Test 7: verify_admin_only used in replay_dlq_messages
    if 'Depends(verify_admin_only)' in code:
        print("  [PASS] verify_admin_only is used as dependency")
    else:
        print("  [FAIL] verify_admin_only is not used")
        return False
    
    return True


def test_dlq_service_fixes():
    """Test DLQ management service fixes"""
    print("\nTesting dlq_management_service.py fixes...")
    
    service_path = Path("apps/api/app/services/dlq_management_service.py")
    if not service_path.exists():
        print(f"ERROR: {service_path} not found!")
        return False
    
    with open(service_path, 'r', encoding='utf-8') as f:
        code = f.read()
    
    # Test 1: Syntax validity
    try:
        ast.parse(code)
        print("  [PASS] Syntax is valid")
    except SyntaxError as e:
        print(f"  [FAIL] Syntax error: {e}")
        return False
    
    # Test 2: requeue=False to prevent infinite loops
    if 'async with message.process(requeue=False):' in code:
        print("  [PASS] requeue=False used to prevent infinite loops")
    else:
        print("  [FAIL] Still using requeue=True (infinite loop risk!)")
        return False
    
    # Test 3: No more references to requeue=True in replay logic
    replay_section = code[code.find('async def replay_messages'):code.find('async def replay_messages') + 5000]
    if 'requeue=True' not in replay_section:
        print("  [PASS] No requeue=True in replay_messages method")
    else:
        print("  [FAIL] Found requeue=True in replay_messages (infinite loop risk!)")
        return False
    
    return True


def main():
    """Run all tests"""
    print("=" * 60)
    print("PR #254 Critical Fixes Verification")
    print("=" * 60)
    
    all_passed = True
    
    # Test admin_dlq.py fixes
    if not test_admin_dlq_fixes():
        all_passed = False
    
    # Test dlq_management_service.py fixes
    if not test_dlq_service_fixes():
        all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("SUCCESS: All critical fixes have been applied!")
        print("=" * 60)
        return 0
    else:
        print("FAILURE: Some fixes are missing or incorrect!")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())