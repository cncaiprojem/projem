#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script to verify PR #257 fixes from Gemini feedback.

This script verifies:
1. Pydantic v2 field_validator import and usage
2. AMQP connection reuse optimization
"""

import sys
import ast
import importlib.util
from pathlib import Path

def test_pydantic_v2_compatibility():
    """Test that schemas use Pydantic v2 field_validator."""
    print("\n=== Testing Pydantic v2 Compatibility ===")
    
    schema_path = Path("apps/api/app/schemas/dlq.py")
    if not schema_path.exists():
        print(f"[FAIL] Schema file not found: {schema_path}")
        return False
    
    with open(schema_path, 'r') as f:
        content = f.read()
    
    # Check import
    if "from pydantic import BaseModel, Field, field_validator" not in content:
        print("[FAIL] Missing field_validator import")
        return False
    print("[PASS] Correct import: field_validator imported from pydantic")
    
    # Check decorator usage
    if "@field_validator" not in content:
        print("[FAIL] field_validator decorator not used")
        return False
    
    if "@validator" in content:
        print("[FAIL] Deprecated @validator still present")
        return False
    
    print("[PASS] Using @field_validator decorator (Pydantic v2 style)")
    
    # Count field validators
    validator_count = content.count("@field_validator")
    print(f"[PASS] Found {validator_count} field_validator decorators")
    
    return True

def test_amqp_connection_optimization():
    """Test that DLQ service has optimized connection management."""
    print("\n=== Testing AMQP Connection Optimization ===")
    
    service_path = Path("apps/api/app/services/dlq_management_service.py")
    if not service_path.exists():
        print(f"[FAIL] Service file not found: {service_path}")
        return False
    
    with open(service_path, 'r') as f:
        content = f.read()
    
    # Check for connection reuse helper method
    if "async def _get_amqp_channel" not in content:
        print("[FAIL] Missing _get_amqp_channel helper method")
        return False
    print("[PASS] Found _get_amqp_channel helper method")
    
    # Check that it manages connection lifecycle
    if "if self._amqp_connection is None or self._amqp_connection.is_closed" not in content:
        print("[FAIL] Missing connection lifecycle management")
        return False
    print("[PASS] Proper connection lifecycle management implemented")
    
    # Check that replay_messages uses the helper
    if "channel = await self._get_amqp_channel()" not in content:
        print("[FAIL] replay_messages not using _get_amqp_channel")
        return False
    print("[PASS] replay_messages uses reusable connection via _get_amqp_channel")
    
    # Check that we don't create new connections in replay_messages
    lines = content.split('\n')
    in_replay_messages = False
    for line in lines:
        if "async def replay_messages" in line:
            in_replay_messages = True
        elif in_replay_messages and "def " in line and "replay_messages" not in line:
            in_replay_messages = False
        
        if in_replay_messages and "connection = await connect_robust" in line:
            print("[FAIL] Still creating new connection in replay_messages")
            return False
    
    print("[PASS] No new connection creation in replay_messages")
    
    # Check that connection is not closed in replay_messages
    if "await connection.close()" in content and "# Note: Connection is not closed here" not in content:
        # Make sure this close() is not in replay_messages
        replay_section = content[content.find("async def replay_messages"):content.find("async def get_queue_depth")]
        if "await connection.close()" in replay_section:
            print("[FAIL] Connection being closed in replay_messages")
            return False
    
    print("[PASS] Connection properly managed by service lifecycle")
    
    return True

def test_code_structure():
    """Test overall code structure and quality."""
    print("\n=== Testing Code Structure ===")
    
    # Check DLQ schema structure
    schema_path = Path("apps/api/app/schemas/dlq.py")
    with open(schema_path, 'r') as f:
        tree = ast.parse(f.read())
    
    classes_found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes_found.append(node.name)
    
    expected_classes = ["DLQQueueInfo", "DLQListResponse", "DLQMessagePreview", "DLQReplayRequest"]
    for cls in expected_classes:
        if cls in classes_found:
            print(f"[PASS] Found class: {cls}")
        else:
            print(f"[FAIL] Missing class: {cls}")
            return False
    
    return True

def main():
    """Run all tests."""
    print("=" * 60)
    print("PR #257 Fixes Verification Script")
    print("Testing Gemini feedback implementation")
    print("=" * 60)
    
    all_passed = True
    
    # Test 1: Pydantic v2 compatibility
    if not test_pydantic_v2_compatibility():
        all_passed = False
        print("\n[FAIL] Pydantic v2 compatibility test FAILED")
    else:
        print("\n[PASS] Pydantic v2 compatibility test PASSED")
    
    # Test 2: AMQP connection optimization
    if not test_amqp_connection_optimization():
        all_passed = False
        print("\n[FAIL] AMQP connection optimization test FAILED")
    else:
        print("\n[PASS] AMQP connection optimization test PASSED")
    
    # Test 3: Code structure
    if not test_code_structure():
        all_passed = False
        print("\n[FAIL] Code structure test FAILED")
    else:
        print("\n[PASS] Code structure test PASSED")
    
    print("\n" + "=" * 60)
    if all_passed:
        print("[PASS] ALL TESTS PASSED - PR #257 fixes successfully applied!")
        print("\nSummary of fixes:")
        print("1. [PASS] Updated imports from 'validator' to 'field_validator' (Pydantic v2)")
        print("2. [PASS] Changed @validator decorators to @field_validator")
        print("3. [PASS] Implemented connection reuse with _get_amqp_channel helper")
        print("4. [PASS] Optimized replay_messages to reuse connections")
        print("5. [PASS] Proper connection lifecycle management")
        return 0
    else:
        print("[FAIL] SOME TESTS FAILED - Please review the implementation")
        return 1

if __name__ == "__main__":
    sys.exit(main())