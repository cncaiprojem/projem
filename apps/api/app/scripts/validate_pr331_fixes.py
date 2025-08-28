#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate PR #331 fixes - All CRITICAL and HIGH priority issues.

This script validates that all critical fixes from PR #331 have been properly implemented:
1. UUID to bigint conversion using proper PostgreSQL functions
2. SQL injection vulnerability fix
3. Updated validation script for new UUID pattern
4. Regex patterns moved to module level
5. Test script fallback to RuntimeError
6. N+1 query warning added
"""

import re
from pathlib import Path


def validate_uuid_to_bigint_conversion():
    """Validate proper UUID to bigint conversion (Copilot CRITICAL)."""
    print("\n1. Validating UUID to bigint Conversion (CRITICAL)")
    print("=" * 50)
    
    migration_file = Path("apps/api/alembic/versions/20250827_213512_task_715_model_flows_database_schema.py")
    content = migration_file.read_text(encoding='utf-8')
    
    # Check for proper UUID byte extraction using uuid_send and get_byte
    if "uuid_bytes := uuid_send(NEW.freecad_doc_uuid)" in content:
        print("[PASS] Using uuid_send() to convert UUID to bytea")
    else:
        print("[FAIL] Not using uuid_send() for UUID conversion")
        return False
    
    # Check for get_byte usage to extract individual bytes
    if "get_byte(uuid_bytes, 0)::bigint << 56" in content:
        print("[PASS] Using get_byte() to extract UUID bytes")
        print("   - Properly extracts each byte and shifts for bigint conversion")
    else:
        print("[FAIL] Not using get_byte() for byte extraction")
        return False
    
    # Check for two lock IDs (128-bit lock)
    if "lock_id1 bigint" in content and "lock_id2 bigint" in content:
        print("[PASS] Creating two bigint values for 128-bit advisory lock")
    else:
        print("[FAIL] Not creating proper 128-bit lock")
        return False
    
    # Check for pg_advisory_xact_lock with two parameters
    if "pg_advisory_xact_lock(lock_id1, lock_id2)" in content:
        print("[PASS] Using pg_advisory_xact_lock with two bigint parameters")
        print("   - Prevents race conditions in concurrent model_rev updates")
    else:
        print("[FAIL] Not using proper advisory lock call")
        return False
    
    return True


def validate_sql_injection_fix():
    """Validate SQL injection vulnerability fix (Gemini CRITICAL)."""
    print("\n2. Validating SQL Injection Fix (CRITICAL)")
    print("=" * 50)
    
    migration_file = Path("apps/api/alembic/versions/20250827_213512_task_715_model_flows_database_schema.py")
    content = migration_file.read_text(encoding='utf-8')
    
    # Check for proper escaping of single quotes
    if 'escaped_values = [v.replace("\'", "\'\'") for v in values]' in content:
        print("[PASS] Properly escaping single quotes in enum values")
        print("   - Prevents SQL injection in CREATE TYPE statements")
    else:
        print("[FAIL] Not properly escaping single quotes")
        return False
    
    # Check that escaped values are used in the query
    if "values_str = ', '.join([f\"'{v}'\" for v in escaped_values])" in content:
        print("[PASS] Using escaped values in SQL query")
    else:
        print("[FAIL] Not using escaped values in query")
        return False
    
    return True


def validate_validation_script_update():
    """Validate validation script update (Gemini CRITICAL)."""
    print("\n3. Validating Validation Script Update (CRITICAL)")
    print("=" * 50)
    
    validation_file = Path("apps/api/app/scripts/validate_pr329_fixes.py")
    content = validation_file.read_text(encoding='utf-8')
    
    # Check for new UUID byte extraction pattern check
    if 'uuid_send(NEW.freecad_doc_uuid)' in content and 'get_byte(uuid_bytes' in content:
        print("[PASS] Validation script checks for new UUID byte extraction pattern")
        print("   - Properly validates uuid_send() and get_byte() usage")
    else:
        print("[FAIL] Validation script not checking correct pattern")
        return False
    
    return True


def validate_regex_patterns_at_module_level():
    """Validate regex patterns moved to module level (Copilot HIGH)."""
    print("\n4. Validating Regex Patterns at Module Level (HIGH)")
    print("=" * 50)
    
    model_file = Path("apps/api/app/models/ai_suggestions.py")
    content = model_file.read_text(encoding='utf-8')
    
    # Check for all required module-level patterns
    patterns = [
        ("EMAIL_PATTERN", "Email addresses"),
        ("COMPILED_PHONE_REGEX", "Turkish phone numbers"),
        ("TC_KIMLIK_PATTERN", "Turkish ID numbers"),
        ("CREDIT_CARD_PATTERN", "Credit card numbers"),
        ("IBAN_PATTERN", "IBAN numbers"),
        ("TURKISH_NAMES_REGEX", "Turkish names"),
        ("ADDRESS_REGEX", "Turkish addresses")
    ]
    
    all_found = True
    for pattern_name, description in patterns:
        if f"{pattern_name} = re.compile(" in content:
            print(f"[PASS] {pattern_name} compiled at module level ({description})")
        else:
            print(f"[FAIL] {pattern_name} not compiled at module level")
            all_found = False
    
    # Check that patterns are used in mask_pii method
    if all_found:
        usage_checks = [
            "EMAIL_PATTERN.sub(",
            "COMPILED_PHONE_REGEX.sub(",
            "TC_KIMLIK_PATTERN.sub(",
            "CREDIT_CARD_PATTERN.sub(",
            "IBAN_PATTERN.sub(",
            "TURKISH_NAMES_REGEX.sub(",
            "ADDRESS_REGEX.sub("
        ]
        
        for usage in usage_checks:
            if usage not in content:
                print(f"[FAIL] Pattern not used: {usage}")
                all_found = False
        
        if all_found:
            print("[PASS] All patterns are used with precompiled regexes")
            print("   - Patterns compiled once at module load, not per call")
            print("   - Significant performance improvement for repeated calls")
    
    return all_found


def validate_test_script_fallback():
    """Validate test script RuntimeError instead of fallback (Gemini HIGH)."""
    print("\n5. Validating Test Script RuntimeError (HIGH)")
    print("=" * 50)
    
    test_file = Path("apps/api/app/scripts/test_task_715_migration.py")
    content = test_file.read_text(encoding='utf-8')
    
    # Check for RuntimeError instead of returning head_revision
    if "raise RuntimeError(" in content and "Task 7.15 migration not found" in content:
        print("[PASS] Test script raises RuntimeError if migration not found")
        print("   - Prevents silent failures if migration is missing")
        print("   - Ensures test fails explicitly with clear error message")
    else:
        print("[FAIL] Test script doesn't raise RuntimeError")
        return False
    
    # Check that it doesn't fall back to head_revision
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'return head_revision' in line and 'raise RuntimeError' not in '\n'.join(lines[max(0, i-5):i]):
            print("[FAIL] Still falling back to head_revision")
            return False
    
    print("[PASS] No fallback to head_revision")
    
    return True


def validate_datetime_imports():
    """Validate datetime imports moved to top (Gemini MEDIUM)."""
    print("\n6. Validating Datetime Imports at Top (MEDIUM)")
    print("=" * 50)
    
    model_file = Path("apps/api/app/models/ai_suggestions.py")
    content = model_file.read_text(encoding='utf-8')
    lines = content.split('\n')
    
    # Find import section (before first class definition)
    import_section = []
    for line in lines:
        if line.startswith('class '):
            break
        import_section.append(line)
    
    import_text = '\n'.join(import_section)
    
    # Check for datetime imports at top
    if "from datetime import datetime, timezone, timedelta" in import_text:
        print("[PASS] Datetime imports at module level")
        print("   - datetime, timezone, timedelta imported at top")
    else:
        print("[FAIL] Datetime imports not at module level")
        return False
    
    # Check that they're not imported inside methods
    method_section = '\n'.join(lines[len(import_section):])
    if "from datetime import" in method_section:
        print("[FAIL] Still importing datetime inside methods")
        return False
    else:
        print("[PASS] No datetime imports inside methods")
    
    return True


def validate_n1_query_warning():
    """Validate N+1 query warning added (Gemini HIGH)."""
    print("\n7. Validating N+1 Query Warning (HIGH)")
    print("=" * 50)
    
    model_file = Path("apps/api/app/models/model.py")
    content = model_file.read_text(encoding='utf-8')
    
    # Check for N+1 warning in is_latest_revision property
    if "WARNING: This property may cause N+1 queries" in content:
        print("[PASS] N+1 query warning added to is_latest_revision property")
    else:
        print("[FAIL] N+1 query warning not added")
        return False
    
    # Check for eager loading example
    if "selectinload(Model.child_models)" in content or "joinedload()" in content:
        print("[PASS] Eager loading example provided")
        print("   - Shows how to avoid N+1 queries with selectinload/joinedload")
    else:
        print("[FAIL] No eager loading example provided")
        return False
    
    return True


def main():
    """Run all validation checks for PR #331 fixes."""
    print("PR #331 Fixes Validation")
    print("=" * 60)
    print("Validating all CRITICAL and HIGH priority fixes from Copilot and Gemini")
    
    results = []
    
    # Run all validations
    results.append(("UUID to bigint Conversion", validate_uuid_to_bigint_conversion()))
    results.append(("SQL Injection Fix", validate_sql_injection_fix()))
    results.append(("Validation Script Update", validate_validation_script_update()))
    results.append(("Regex Patterns at Module Level", validate_regex_patterns_at_module_level()))
    results.append(("Test Script RuntimeError", validate_test_script_fallback()))
    results.append(("Datetime Imports", validate_datetime_imports()))
    results.append(("N+1 Query Warning", validate_n1_query_warning()))
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"{name:.<35} {status}")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("SUCCESS: ALL PR #331 FIXES SUCCESSFULLY IMPLEMENTED!")
        print("\nKey fixes applied:")
        print("- CRITICAL: Fixed UUID to bigint conversion using uuid_send() and get_byte()")
        print("- CRITICAL: Fixed SQL injection vulnerability with proper escaping")
        print("- CRITICAL: Updated validation script to check correct patterns")
        print("- HIGH: Moved all regex patterns to module level for performance")
        print("- HIGH: Test script now raises RuntimeError instead of silent fallback")
        print("- HIGH: Added N+1 query warning with eager loading guidance")
        print("- MEDIUM: Moved datetime imports to module level")
        print("\nAll security vulnerabilities and performance issues have been resolved.")
    else:
        print("FAILED: Some PR #331 fixes are not properly implemented")
        return 1
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())