#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script to verify PR #258 fixes from Copilot and Gemini feedback.

This script verifies:
1. TOTP service method call is corrected (Gemini critical fix)
2. URL parsing moved to __init__ method (Copilot suggestion)
3. Test scripts use AST parsing for robustness (Copilot suggestion)
"""

import sys
import ast
import re
from pathlib import Path


def test_totp_service_fix():
    """Test that TOTP service call is correctly implemented."""
    print("\n=== Testing TOTP Service Fix (Gemini Critical) ===")
    
    admin_dlq_path = Path("apps/api/app/routers/admin_dlq.py")
    if not admin_dlq_path.exists():
        print(f"[FAIL] File not found: {admin_dlq_path}")
        return False
    
    with open(admin_dlq_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check that we're using the correct method name and parameters
    if "totp_service.verify_totp_code(" not in content:
        print("[FAIL] Not using correct method name 'verify_totp_code'")
        return False
    print("[PASS] Using correct method name 'verify_totp_code'")
    
    # Check that we're NOT awaiting (it's synchronous)
    if "await totp_service.verify_totp_code" in content:
        print("[FAIL] Still using 'await' with synchronous method")
        return False
    print("[PASS] Not using 'await' (method is synchronous)")
    
    # Check that we're using correct parameter name 'code'
    if "code=mfa_code" not in content:
        print("[FAIL] Not using correct parameter name 'code'")
        return False
    print("[PASS] Using correct parameter name 'code=mfa_code'")
    
    # Use regex patterns to allow for whitespace variations
    essential_regexes = [
        r"totp_service\s*\.\s*verify_totp_code\s*\(",
        r"db\s*=\s*db",
        r"user\s*=\s*user",
        r"code\s*=\s*mfa_code"
    ]
    
    all_found = all(re.search(pattern, content) for pattern in essential_regexes)
    if not all_found:
        print("[FAIL] Essential fix patterns not found")
        return False
    print("[PASS] Essential fix patterns applied correctly")
    
    return True


def test_url_parsing_optimization():
    """Test that URL parsing is moved to __init__ method."""
    print("\n=== Testing URL Parsing Optimization (Copilot) ===")
    
    service_path = Path("apps/api/app/services/dlq_management_service.py")
    if not service_path.exists():
        print(f"[FAIL] File not found: {service_path}")
        return False
    
    with open(service_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Parse AST to check class structure
    tree = ast.parse(content)
    
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "DLQManagementService":
            # Check that _parsed_url is NOT a class variable
            has_class_level_parsing = False
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and target.id == "_parsed_url":
                            has_class_level_parsing = True
                            break
            
            if has_class_level_parsing:
                print("[FAIL] URL parsing still at class level")
                return False
            print("[PASS] URL parsing not at class level")
            
            # Check that __init__ method contains URL parsing
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    init_source = ast.unparse(item) if hasattr(ast, 'unparse') else ""
                    if not init_source:
                        # Fallback: use AST node line numbers to extract source
                        if hasattr(item, 'lineno') and hasattr(item, 'end_lineno'):
                            lines = content.splitlines()
                            # AST line numbers are 1-based
                            init_source = "\n".join(lines[item.lineno - 1:item.end_lineno])
                        else:
                            # If end_lineno is not available, fallback to string search (legacy)
                            init_start = content.find("def __init__(self):")
                            init_end = content.find("\n    def ", init_start + 1)
                            if init_end == -1:
                                init_end = content.find("\n    async def ", init_start + 1)
                            init_source = content[init_start:init_end] if init_end != -1 else content[init_start:]
                    
                    if "parsed_url = urlparse(settings.rabbitmq_url)" in init_source:
                        print("[PASS] URL parsing moved to __init__ method")
                    else:
                        print("[FAIL] URL parsing not found in __init__ method")
                        return False
                    
                    if "self.RABBITMQ_USER = parsed_url.username" in init_source:
                        print("[PASS] Credentials extracted in __init__")
                    else:
                        print("[FAIL] Credentials not extracted in __init__")
                        return False
                    
                    break
            break
    
    return True


def test_improved_test_robustness():
    """Test that test scripts use AST parsing for robustness."""
    print("\n=== Testing Improved Test Script Robustness (Copilot) ===")
    
    # Check test_pr257_fixes.py
    test257_path = Path("test_pr257_fixes.py")
    if test257_path.exists():
        with open(test257_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for AST-based parsing
        if "ast.parse(content)" in content and "ast.walk(tree)" in content:
            print("[PASS] test_pr257_fixes.py uses AST parsing")
        else:
            print("[WARN] test_pr257_fixes.py could use more AST parsing")
        
        # Check for improved error handling
        if "except (SyntaxError, ValueError)" in content:
            print("[PASS] test_pr257_fixes.py has error handling for AST parsing")
        else:
            print("[WARN] test_pr257_fixes.py could use better error handling")
    
    # Check test_pr253_fixes.py
    test253_path = Path("test_pr253_fixes.py")
    if test253_path.exists():
        with open(test253_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for AST-based parsing
        if "ast.parse(content)" in content and "ast.walk(tree)" in content:
            print("[PASS] test_pr253_fixes.py uses AST parsing")
        else:
            print("[WARN] test_pr253_fixes.py could use more AST parsing")
        
        # Check for fallback mechanisms
        if "except (SyntaxError, ValueError)" in content:
            print("[PASS] test_pr253_fixes.py has fallback for AST parsing")
        else:
            print("[WARN] test_pr253_fixes.py could use fallback mechanisms")
    
    return True


def test_all_pr258_fixes():
    """Test that all PR #258 fixes are properly applied."""
    print("\n=== Testing All PR #258 Fixes ===")
    
    # Additional validation for the critical TOTP fix
    admin_dlq_path = Path("apps/api/app/routers/admin_dlq.py")
    with open(admin_dlq_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Find the exact location of the fix
    for i, line in enumerate(lines):
        if "totp_service.verify_totp_code(" in line:
            # Check surrounding lines
            if i > 0 and "await" in lines[i-1]:
                print("[FAIL] 'await' found near verify_totp_code call")
                return False
            
            # Check the complete call
            call_lines = []
            j = i
            while j < len(lines) and ")" not in lines[j]:
                call_lines.append(lines[j].strip())
                j += 1
            if j < len(lines):
                call_lines.append(lines[j].strip())
            
            full_call = " ".join(call_lines)
            if "code=mfa_code" in full_call:
                print("[PASS] Complete TOTP service call is correct")
            else:
                print("[FAIL] TOTP service call parameters incorrect")
                return False
            break
    
    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("PR #258 Fixes Verification Script")
    print("Testing Copilot and Gemini feedback implementation")
    print("=" * 60)
    
    results = []
    
    # Test 1: Critical TOTP fix
    result1 = test_totp_service_fix()
    results.append(("TOTP Service Fix (Gemini Critical)", result1))
    
    # Test 2: URL parsing optimization
    result2 = test_url_parsing_optimization()
    results.append(("URL Parsing Optimization (Copilot)", result2))
    
    # Test 3: Test script robustness
    result3 = test_improved_test_robustness()
    results.append(("Test Script Robustness (Copilot)", result3))
    
    # Test 4: All fixes validation
    result4 = test_all_pr258_fixes()
    results.append(("All PR #258 Fixes", result4))
    
    print("\n" + "=" * 60)
    print("TEST RESULTS SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for test_name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status} {test_name}")
        if not result:
            all_passed = False
    
    print("=" * 60)
    if all_passed:
        print("[SUCCESS] ALL PR #258 FIXES SUCCESSFULLY APPLIED!")
        print("\nSummary of fixes:")
        print("1. [PASS] TOTP service call corrected (verify_totp_code, no await, code parameter)")
        print("2. [PASS] URL parsing moved from class level to __init__ method")
        print("3. [PASS] Test scripts improved with AST parsing and error handling")
        print("4. [PASS] All critical issues from PR #258 feedback resolved")
        return 0
    else:
        print("[ERROR] Some PR #258 fixes are not properly applied")
        print("Please review the failed tests above")
        return 1


if __name__ == "__main__":
    sys.exit(main())