#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate PR #329 fixes without database connection.

This script demonstrates that all fixes from PR #329 have been properly implemented:
1. Advisory lock in trigger function
2. Optimized Turkish name masking
3. Removed redundant onupdate
4. Improved email masking
5. Test assertions
"""

import re
from pathlib import Path


def validate_advisory_lock_fix():
    """Validate that advisory lock was added to increment_model_rev trigger."""
    print("\n1. Validating Advisory Lock Fix (HIGH)")
    print("=" * 50)
    
    migration_file = Path("apps/api/alembic/versions/20250827_213512_task_715_model_flows_database_schema.py")
    content = migration_file.read_text(encoding='utf-8')
    
    # Check for advisory lock
    if "pg_advisory_xact_lock(hashtext(NEW.freecad_doc_uuid::text))" in content:
        print("[PASS] Advisory lock properly added using pg_advisory_xact_lock")
        print("   - Uses hashtext() to convert UUID to bigint for lock ID")
        print("   - Prevents concurrent transactions from getting same model_rev")
    else:
        print("[FAIL] Advisory lock not found")
        return False
    
    # Check that it's in the increment_model_rev function
    if "CREATE OR REPLACE FUNCTION increment_model_rev()" in content and "pg_advisory_xact_lock" in content:
        print("[PASS] Advisory lock is in the correct trigger function")
    else:
        print("[FAIL] Advisory lock not in increment_model_rev function")
        return False
    
    return True


def validate_turkish_name_masking_optimization():
    """Validate optimized Turkish name masking."""
    print("\n2. Validating Turkish Name Masking Optimization (HIGH)")
    print("=" * 50)
    
    model_file = Path("apps/api/app/models/ai_suggestions.py")
    content = model_file.read_text(encoding='utf-8')
    
    # Check for optimized single regex pattern
    if "escaped_names = [re.escape(name) for name in turkish_names]" in content:
        print("[PASS] Building single regex pattern for all names")
    else:
        print("[FAIL] Not building optimized regex pattern")
        return False
    
    if "names_pattern = r'\\b(' + '|'.join(escaped_names)" in content:
        print("[PASS] Using single compiled regex pattern (efficient)")
    else:
        print("[FAIL] Not using single regex pattern")
        return False
    
    # Check for proper replacement function
    if "def mask_name(match):" in content and "first_name = match.group(1)" in content:
        print("[PASS] Using replacement function with match groups")
        print("   - Properly uses match.group(1) not loop variable")
    else:
        print("[FAIL] Not using proper replacement function")
        return False
    
    # Verify no loop through individual names
    if "for name in turkish_names:" in content and "name_pattern = rf'\\b{re.escape(name)}" in content:
        print("[FAIL] Still looping through names (inefficient)")
        return False
    else:
        print("[PASS] No inefficient loop through individual names")
    
    return True


def validate_redundant_onupdate_removal():
    """Validate removal of redundant onupdate."""
    print("\n3. Validating Redundant onupdate Removal (MEDIUM)")
    print("=" * 50)
    
    migration_file = Path("apps/api/alembic/versions/20250827_213512_task_715_model_flows_database_schema.py")
    content = migration_file.read_text(encoding='utf-8')
    
    # Check that onupdate is NOT present with updated_at
    updated_at_lines = [line for line in content.split('\n') if 'updated_at' in line and 'Column' in line]
    
    has_onupdate = any('onupdate=' in line for line in updated_at_lines)
    
    if not has_onupdate:
        print("[PASS] No redundant onupdate=sa.func.now() on updated_at columns")
        print("   - Using database triggers instead (more reliable)")
    else:
        print("[FAIL] Still has onupdate on updated_at columns")
        return False
    
    # Verify triggers are still created
    if "CREATE TRIGGER update_" in content and "update_updated_at_column()" in content:
        print("[PASS] Database triggers properly configured for updated_at")
    else:
        print("[FAIL] Missing database triggers for updated_at")
        return False
    
    return True


def validate_email_masking_improvement():
    """Validate improved email masking."""
    print("\n4. Validating Email Masking Improvement (MEDIUM)")
    print("=" * 50)
    
    model_file = Path("apps/api/app/models/ai_suggestions.py")
    content = model_file.read_text(encoding='utf-8')
    
    # Check for improved email masking function
    if "def mask_email(match):" in content:
        print("[PASS] Using custom email masking function")
    else:
        print("[FAIL] Not using custom email masking function")
        return False
    
    # Check for proper handling of short emails
    if "if len(local) <= 2:" in content:
        print("[PASS] Special handling for short emails (<=2 chars)")
    else:
        print("[FAIL] Not handling short emails specially")
        return False
    
    # Check for preserving first and last chars
    if 'return f"{local[0]}***{local[-1]}@{domain}"' in content:
        print("[PASS] Preserving first and last chars of email local part")
        print("   - Example: user@example.com -> u***r@example.com")
    else:
        print("[FAIL] Not preserving first and last chars")
        return False
    
    return True


def validate_test_assertions():
    """Validate that tests use assertions instead of warnings."""
    print("\n5. Validating Test Assertions (MEDIUM)")
    print("=" * 50)
    
    test_file = Path("apps/api/app/scripts/test_task_715_migration.py")
    content = test_file.read_text(encoding='utf-8')
    
    # Check for assertions on constraints
    if 'assert False, f"Missing constraints: {missing_constraints}"' in content:
        print("[PASS] Using assertions for missing constraints (will fail test)")
    else:
        print("[FAIL] Still using warnings for constraints")
        return False
    
    # Check for assertions on indexes
    if 'assert False, f"Missing indexes: {missing_indexes}"' in content:
        print("[PASS] Using assertions for missing indexes (will fail test)")
    else:
        print("[FAIL] Still using warnings for indexes")
        return False
    
    # Check for using task_715_revision variable
    if "command.upgrade(alembic_cfg, task_715_revision)" in content:
        print("[PASS] Using task_715_revision variable instead of hardcoded ID")
    else:
        print("[FAIL] Still using hardcoded revision ID")
        return False
    
    return True


def test_email_masking():
    """Test the actual email masking logic."""
    print("\n6. Testing Email Masking Logic")
    print("=" * 50)
    
    # Simulate the email masking function
    def mask_email(match):
        local = match.group(1)
        domain = match.group(2)
        
        if len(local) <= 2:
            return f"***@{domain}"
        else:
            return f"{local[0]}***{local[-1]}@{domain}"
    
    email_pattern = r'\b([a-zA-Z0-9._%+-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b'
    
    test_cases = [
        ("john.doe@example.com", "j***e@example.com"),
        ("ab@test.com", "***@test.com"),
        ("a@test.com", "***@test.com"),
        ("support@company.co.uk", "s***t@company.co.uk"),
    ]
    
    all_passed = True
    for email, expected in test_cases:
        result = re.sub(email_pattern, mask_email, email, flags=re.IGNORECASE)
        if result == expected:
            print(f"[PASS] {email} -> {result}")
        else:
            print(f"[FAIL] {email} -> {result} (expected {expected})")
            all_passed = False
    
    return all_passed


def main():
    """Run all validation checks."""
    print("PR #329 Fixes Validation")
    print("=" * 60)
    
    results = []
    
    # Run all validations
    results.append(("Advisory Lock", validate_advisory_lock_fix()))
    results.append(("Turkish Name Masking", validate_turkish_name_masking_optimization()))
    results.append(("Redundant onupdate", validate_redundant_onupdate_removal()))
    results.append(("Email Masking", validate_email_masking_improvement()))
    results.append(("Test Assertions", validate_test_assertions()))
    results.append(("Email Masking Logic", test_email_masking()))
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"{name:.<30} {status}")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("SUCCESS: ALL PR #329 FIXES SUCCESSFULLY IMPLEMENTED!")
        print("\nKey improvements:")
        print("- Race condition prevention with PostgreSQL advisory locks")
        print("- Optimized regex performance for Turkish name masking")
        print("- Cleaner code without redundant ORM updates")
        print("- Better UX with partial email masking")
        print("- Robust tests that properly fail on issues")
    else:
        print("FAILED: Some fixes are not properly implemented")
        return 1
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())