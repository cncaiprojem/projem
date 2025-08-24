#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script to verify PR #253 fixes without running full test suite.
"""

import sys
import ast
import io

# Set UTF-8 encoding for stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def test_attribute_error_fix():
    """Test 1: AttributeError fix in list_dlq_queues"""
    with open("apps/api/app/routers/admin_dlq.py", "r") as f:
        content = f.read()
    
    # Use AST parsing for more reliable checking
    try:
        tree = ast.parse(content)
        has_dict_access = False
        has_attr_access = False
        
        for node in ast.walk(tree):
            # Check for q["message_count"] pattern
            if isinstance(node, ast.Subscript):
                if (isinstance(node.value, ast.Name) and node.value.id == "q"):
                    # Check if accessing "message_count"
                    if hasattr(node.slice, 'value'):  # Python 3.8 compatibility
                        if (isinstance(node.slice.value, ast.Constant) and 
                            node.slice.value.value == "message_count"):
                            has_dict_access = True
                    elif isinstance(node.slice, ast.Constant) and node.slice.value == "message_count":
                        has_dict_access = True
            
            # Check for q.message_count pattern (should not exist)
            if isinstance(node, ast.Attribute):
                if (isinstance(node.value, ast.Name) and 
                    node.value.id == "q" and 
                    node.attr == "message_count"):
                    has_attr_access = True
        
        if has_dict_access and not has_attr_access:
            print("✓ Test 1 PASSED: AttributeError fix applied - using q['message_count']")
            return True
        else:
            print("✗ Test 1 FAILED: AttributeError not fixed properly")
            return False
            
    except (SyntaxError, ValueError):
        # Fallback to string-based check if AST parsing fails
        if 'q["message_count"]' in content and 'q.message_count' not in content:
            print("✓ Test 1 PASSED: AttributeError fix applied - using q['message_count']")
            return True
        else:
            print("✗ Test 1 FAILED: AttributeError not fixed properly")
            return False

def test_aio_pika_import():
    """Test 2: Check aio-pika is imported instead of Kombu"""
    with open("apps/api/app/services/dlq_management_service.py", "r") as f:
        content = f.read()
    
    if "import aio_pika" in content and "from kombu import" not in content:
        print("✓ Test 2 PASSED: Using aio-pika instead of Kombu")
        return True
    else:
        print("✗ Test 2 FAILED: Still using Kombu or aio-pika not imported")
        return False

def test_rabbitmq_password():
    """Test 3: Check RabbitMQ password consistency"""
    with open("apps/api/app/config.py", "r") as f:
        content = f.read()
    
    if 'rabbitmq_url: str = "amqp://freecad:freecad_dev_pass@rabbitmq:5672/"' in content:
        print("✓ Test 3 PASSED: RabbitMQ password is consistent")
        return True
    else:
        print("✗ Test 3 FAILED: RabbitMQ password mismatch")
        return False

def test_mfa_in_body():
    """Test 4: Check MFA code field validator is properly defined"""
    with open("apps/api/app/schemas/dlq.py", "r") as f:
        content = f.read()
    
    # Check for Pydantic v2 field_validator decorator
    if '@field_validator("mfa_code")' in content:
        print("✓ Test 4 PASSED: MFA code using @field_validator decorator")
        return True
    else:
        print("✗ Test 4 FAILED: MFA code field_validator not found")
        return False

def test_audit_service_usage():
    """Test 5: Check audit_service is used instead of direct AuditLog"""
    with open("apps/api/app/services/job_audit_service.py", "r") as f:
        content = f.read()
    
    # Check for audit_service.create_audit_entry in DLQ methods
    if "await audit_service.create_audit_entry(" in content:
        print("✓ Test 5 PASSED: Using audit_service instead of direct AuditLog")
        return True
    else:
        print("✗ Test 5 FAILED: Still using direct AuditLog creation")
        return False

def test_context_manager():
    """Test 6: Check context manager implementation"""
    with open("apps/api/app/services/dlq_management_service.py", "r") as f:
        content = f.read()
    
    if "async def __aenter__(self):" in content and "async def __aexit__(self," in content:
        print("✓ Test 6 PASSED: Context manager implemented")
        return True
    else:
        print("✗ Test 6 FAILED: Context manager not implemented")
        return False

def test_dependency_injection():
    """Test 7: Check dependency injection for DLQManagementService"""
    with open("apps/api/app/routers/admin_dlq.py", "r") as f:
        content = f.read()
    
    if "async def get_dlq_service()" in content and "Depends(get_dlq_service)" in content:
        print("✓ Test 7 PASSED: Dependency injection implemented")
        return True
    else:
        print("✗ Test 7 FAILED: Dependency injection not implemented")
        return False

def test_broad_except():
    """Test 8: Check no broad except clauses remain"""
    with open("apps/api/app/services/dlq_management_service.py", "r") as f:
        content = f.read()
    
    # Check there are no bare except: clauses
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if line.strip() == "except:":
            print(f"✗ Test 8 FAILED: Broad except clause found at line {i+1}")
            return False
    
    print("✓ Test 8 PASSED: No broad except clauses")
    return True

def test_async_replay():
    """Test 9: Check replay_messages is using async aio-pika"""
    with open("apps/api/app/services/dlq_management_service.py", "r") as f:
        content = f.read()
    
    if "await connect_robust(conn_url)" in content and "async with dlq_queue.iterator()" in content:
        print("✓ Test 9 PASSED: replay_messages using async aio-pika")
        return True
    else:
        print("✗ Test 9 FAILED: replay_messages not using async aio-pika properly")
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("Running PR #253 Fix Verification Tests")
    print("=" * 60)
    
    tests = [
        test_attribute_error_fix,
        test_aio_pika_import,
        test_rabbitmq_password,
        test_mfa_in_body,
        test_audit_service_usage,
        test_context_manager,
        test_dependency_injection,
        test_broad_except,
        test_async_replay,
    ]
    
    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"✗ {test.__name__} FAILED with exception: {e}")
            results.append(False)
    
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"RESULTS: {passed}/{total} tests passed")
    
    if passed == total:
        print("✅ ALL TESTS PASSED - PR #253 fixes applied successfully!")
        return 0
    else:
        print(f"❌ {total - passed} tests failed - Review the fixes")
        return 1

if __name__ == "__main__":
    sys.exit(main())