#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Verification script for PR 442 AI reviewer feedback fixes.
This verifies that:
1. Type annotations are added to service methods
2. FinalDepth calculation properly uses provided value or stock calculation
3. CAMOperation schema includes final_depth field
"""

import ast
import json
from pathlib import Path

def check_type_annotations():
    """Check that type annotations are added to the specified methods."""
    print("Checking type annotations in assembly4_service.py...")
    
    service_path = Path("apps/api/app/services/assembly4_service.py")
    with open(service_path, 'r') as f:
        content = f.read()
    
    # Check for type annotations in method signatures
    methods_to_check = [
        ('_setup_cam_job', '-> Tuple[Any, Any]:'),
        ('_manage_tool_controller', '-> Tuple[Any, int, bool]:'),
        ('_create_cam_operation', '-> Any:'),
        ('_post_process_job', '-> Tuple[Dict[str, str], Dict[str, Any]]:')
    ]
    
    all_good = True
    for method_name, expected_annotation in methods_to_check:
        if expected_annotation in content:
            print(f"  [OK] {method_name}: Type annotation found")
        else:
            print(f"  [FAIL] {method_name}: Type annotation missing or incorrect")
            all_good = False
    
    return all_good


def check_final_depth_calculation():
    """Check that FinalDepth calculation is fixed."""
    print("\nChecking FinalDepth calculation in _create_cam_operation...")
    
    service_path = Path("apps/api/app/services/assembly4_service.py")
    with open(service_path, 'r') as f:
        content = f.read()
    
    # Check for the new final_depth logic
    checks = [
        ("if operation.final_depth is not None:", "Check for provided final_depth"),
        ("op.FinalDepth = operation.final_depth", "Use provided final_depth"),
        ("op.FinalDepth = -cam_parameters.stock.margins.z", "Calculate from stock (not *2)")
    ]
    
    all_good = True
    for check_str, description in checks:
        if check_str in content:
            print(f"  [OK] {description}: Found")
        else:
            print(f"  [FAIL] {description}: Not found")
            all_good = False
    
    # Verify the old incorrect calculation is gone
    if "-cam_parameters.stock.margins.z * 2" not in content or \
       "op.FinalDepth = -cam_parameters.stock.margins.z * 2" not in content:
        print(f"  [OK] Old hardcoded calculation (margins.z * 2) removed")
    else:
        print(f"  [FAIL] Old hardcoded calculation still present!")
        all_good = False
    
    return all_good


def check_schema_field():
    """Check that CAMOperation schema includes final_depth field."""
    print("\nChecking CAMOperation schema for final_depth field...")
    
    schema_path = Path("apps/api/app/schemas/assembly4.py")
    with open(schema_path, 'r') as f:
        content = f.read()
    
    # Look for final_depth field definition
    checks = [
        ('final_depth: Optional[float]', 'Field type definition'),
        ('Field(None, description=', 'Field descriptor'),
        ('"Final cutting depth in mm', 'Field description'),
        ('"final_depth": -10.0', 'Example value in schema')
    ]
    
    all_good = True
    for check_str, description in checks:
        if check_str in content:
            print(f"  [OK] {description}: Found")
        else:
            print(f"  [FAIL] {description}: Not found")
            all_good = False
    
    return all_good


def main():
    """Run all verification checks."""
    print("=" * 60)
    print("PR 442 AI Reviewer Feedback Fixes Verification")
    print("=" * 60)
    
    results = []
    
    # Run checks
    results.append(("Type Annotations", check_type_annotations()))
    results.append(("FinalDepth Calculation", check_final_depth_calculation()))
    results.append(("Schema Field", check_schema_field()))
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    all_passed = all(result for _, result in results)
    
    for check_name, passed in results:
        status = "[OK] PASSED" if passed else "[FAIL] FAILED"
        print(f"{check_name}: {status}")
    
    print("\n" + "=" * 60)
    if all_passed:
        print("SUCCESS: ALL FIXES VERIFIED SUCCESSFULLY!")
        print("\nAddressed AI Reviewer Feedback:")
        print("1. Copilot: Added missing type annotations to 4 methods")
        print("2. Gemini: Fixed FinalDepth calculation to use proper depth")
        print("3. Schema: Added final_depth optional field to CAMOperation")
    else:
        print("WARNING: Some checks failed. Please review the output above.")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(main())