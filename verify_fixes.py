#!/usr/bin/env python3
"""
Verification script for PR #468 fixes.
Tests that the code changes are correct without requiring full environment setup.
"""

import ast
import re
from pathlib import Path


def verify_batch_delete_fix():
    """Verify that for-else logic has been fixed in batch delete."""
    storage_client = Path("apps/api/app/services/storage_client.py")
    content = storage_client.read_text()
    
    # Check that we're not using for-else incorrectly
    # The else block after for should not be used for error checking
    problematic_pattern = r'for error in errors:\s+.*?\s+else:\s+deleted_count'
    
    if re.search(problematic_pattern, content, re.DOTALL):
        return False, "Still using for-else pattern incorrectly"
    
    # Check that we're using error_count properly
    if "error_count = 0" in content and "if error_count == 0:" in content:
        return True, "Batch delete logic correctly uses error counting"
    
    return False, "Could not find proper error counting logic"


def verify_minio_policy_fix():
    """Verify that MinIO bucket policy doesn't use AWS-specific conditions."""
    storage_client = Path("apps/api/app/services/storage_client.py")
    content = storage_client.read_text()
    
    # Check that we're not using AWS-specific conditions
    if "AIDAI*" in content or "AIDA*" in content or "AROA*" in content:
        return False, "Still using AWS-specific IAM userid patterns"
    
    # Check for simpler deny all policy
    if '"Principal": "*"' in content and '"Effect": "Deny"' in content:
        return True, "Using simple deny-all policy for MinIO"
    
    return False, "Could not find proper MinIO policy"


def verify_uuid_in_s3_keys():
    """Verify that UUID is used in S3 key generation."""
    artefact_service = Path("apps/api/app/services/artefact_service_v2.py")
    content = artefact_service.read_text()
    
    # Check that uuid is imported
    if "import uuid" not in content:
        return False, "UUID module not imported"
    
    # Check that UUID is used in key generation
    if "uuid.uuid4()" in content and "{unique_id}" in content:
        return True, "UUID properly used in S3 key generation"
    
    return False, "UUID not properly integrated in S3 keys"


def verify_import_at_top():
    """Verify that imports are at the top of files."""
    garbage_collection = Path("apps/api/app/tasks/garbage_collection.py")
    content = garbage_collection.read_text()
    
    # Check that timedelta is imported properly at the top
    if "from datetime import datetime, timedelta, timezone" in content:
        # Verify no duplicate imports in function
        if content.count("from datetime import") == 1:
            # Check it's in the import section (first 30 lines after docstring)
            lines = content.split('\n')
            found_in_imports = False
            for i, line in enumerate(lines[:30]):
                if "from datetime import datetime, timedelta, timezone" in line:
                    found_in_imports = True
                    break
            
            if found_in_imports:
                return True, "Imports properly organized at top of file"
            else:
                return False, "datetime import not in top import section"
        else:
            return False, "Multiple datetime imports found"
    
    return False, "timedelta not properly imported"


def main():
    """Run all verification checks."""
    print("Verifying PR #468 fixes...")
    print("-" * 60)
    
    checks = [
        ("Batch Delete Logic Fix", verify_batch_delete_fix),
        ("MinIO Policy Fix", verify_minio_policy_fix),
        ("UUID in S3 Keys", verify_uuid_in_s3_keys),
        ("Import Organization", verify_import_at_top),
    ]
    
    all_passed = True
    for name, check_func in checks:
        try:
            passed, message = check_func()
            status = "PASS" if passed else "FAIL"
            print(f"{status}: {name}")
            print(f"  -> {message}")
            if not passed:
                all_passed = False
        except Exception as e:
            print(f"ERROR: {name}")
            print(f"  -> {e}")
            all_passed = False
        print()
    
    print("-" * 60)
    if all_passed:
        print("All checks passed! The fixes are properly implemented.")
    else:
        print("Some checks failed. Please review the fixes.")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(main())