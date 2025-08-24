#!/usr/bin/env python3
"""
Final validation script for PR #254 critical fixes.
Ensures all NameErrors and infinite loop issues are resolved.
"""

import ast
import sys
from pathlib import Path


def validate_fixes():
    """Validate all critical fixes have been applied"""
    
    print("=" * 70)
    print("PR #254 FINAL VALIDATION - All Critical Fixes")
    print("=" * 70)
    
    issues_found = []
    
    # Check admin_dlq.py
    admin_dlq_path = Path("apps/api/app/routers/admin_dlq.py")
    with open(admin_dlq_path, 'r', encoding='utf-8') as f:
        admin_code = f.read()
    
    print("\n[1] Checking admin_dlq.py...")
    
    # Parse AST to ensure valid Python
    try:
        tree = ast.parse(admin_code)
        print("    [PASS] Python syntax is valid")
    except SyntaxError as e:
        issues_found.append(f"Syntax error in admin_dlq.py: {e}")
        print(f"    [FAIL] Syntax error: {e}")
    
    # Check for all required functions
    functions = {
        'verify_admin_only': 'Admin-only verification dependency',
        'verify_mfa_code': 'MFA verification helper function',
        'verify_admin_with_mfa': 'Admin + MFA verification dependency',
        'get_dlq_service': 'DLQ service dependency injection',
        'list_dlq_queues': 'List DLQ queues endpoint',
        'peek_dlq_messages': 'Peek DLQ messages endpoint',
        'replay_dlq_messages': 'Replay DLQ messages endpoint'
    }
    
    for func_name, description in functions.items():
        if f'def {func_name}(' in admin_code or f'async def {func_name}(' in admin_code:
            print(f"    [PASS] {func_name}: {description}")
        else:
            issues_found.append(f"Missing function: {func_name}")
            print(f"    [FAIL] Missing: {func_name}")
    
    # Check that dlq_service is injected in all endpoints
    print("\n[2] Checking dependency injection...")
    
    endpoints = ['list_dlq_queues', 'peek_dlq_messages', 'replay_dlq_messages']
    for endpoint in endpoints:
        # Find function definition and check for dlq_service parameter
        import re
        pattern = rf'async def {endpoint}\((.*?)\):'
        match = re.search(pattern, admin_code, re.DOTALL)
        if match:
            params = match.group(1)
            if 'dlq_service' in params and 'Depends(get_dlq_service)' in params:
                print(f"    [PASS] {endpoint}: dlq_service properly injected")
            else:
                issues_found.append(f"{endpoint}: dlq_service not properly injected")
                print(f"    [FAIL] {endpoint}: dlq_service not properly injected")
        else:
            issues_found.append(f"Could not find {endpoint} function")
            print(f"    [FAIL] Could not find {endpoint}")
    
    # Check that verify_admin_only is used correctly
    if 'Depends(verify_admin_only)' in admin_code:
        print("    [PASS] verify_admin_only is used as dependency")
    else:
        issues_found.append("verify_admin_only not used as dependency")
        print("    [FAIL] verify_admin_only not used")
    
    # Check dlq_management_service.py
    service_path = Path("apps/api/app/services/dlq_management_service.py")
    with open(service_path, 'r', encoding='utf-8') as f:
        service_code = f.read()
    
    print("\n[3] Checking dlq_management_service.py...")
    
    # Parse AST to ensure valid Python
    try:
        tree = ast.parse(service_code)
        print("    [PASS] Python syntax is valid")
    except SyntaxError as e:
        issues_found.append(f"Syntax error in dlq_management_service.py: {e}")
        print(f"    [FAIL] Syntax error: {e}")
    
    # Check for requeue=False to prevent infinite loops
    if 'async with message.process(requeue=False):' in service_code:
        print("    [PASS] Using requeue=False to prevent infinite loops")
    else:
        issues_found.append("Still using requeue=True (infinite loop risk)")
        print("    [FAIL] Still using requeue=True (infinite loop risk)")
    
    # Make sure no requeue=True in replay_messages
    replay_start = service_code.find('async def replay_messages')
    if replay_start != -1:
        replay_section = service_code[replay_start:replay_start + 5000]
        if 'requeue=True' in replay_section:
            issues_found.append("Found requeue=True in replay_messages")
            print("    [FAIL] Found requeue=True in replay_messages")
        else:
            print("    [PASS] No requeue=True in replay_messages")
    
    # Summary
    print("\n" + "=" * 70)
    if not issues_found:
        print("SUCCESS: SUCCESS: All PR #254 critical fixes have been applied correctly!")
        print("\nFixes applied:")
        print("  1. NameError in list_dlq_queues - FIXED [PASS]")
        print("  2. NameError in peek_dlq_messages - FIXED [PASS]")
        print("  3. Missing verify_admin_only dependency - FIXED [PASS]")
        print("  4. Missing verify_mfa_code helper - FIXED [PASS]")
        print("  5. Infinite loop risk with requeue=True - FIXED [PASS]")
        return 0
    else:
        print("FAILURE: FAILURE: Issues found:")
        for issue in issues_found:
            print(f"  - {issue}")
        return 1
    
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(validate_fixes())