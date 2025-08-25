#!/usr/bin/env python3
"""
Verification script for PR #295 fixes.
Checks that all identified issues have been properly addressed.
"""

import os
import re
from pathlib import Path

def check_file_contains(filepath: str, pattern: str, should_not_contain: bool = False) -> bool:
    """Check if file contains or doesn't contain a pattern."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            found = pattern in content or re.search(pattern, content)
            if should_not_contain:
                return not found
            return found
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return False

def verify_fixes():
    """Verify all PR #295 fixes."""
    results = []
    base_dir = Path("C:/Users/kafge/projem")
    
    # 1. CRITICAL: PostgreSQL ALTER TYPE fix
    print("1. Checking PostgreSQL ALTER TYPE fix...")
    migration_file = base_dir / "apps/api/alembic/versions/20250824_add_jobtype_assembly.py"
    # Should NOT contain AFTER clause
    no_after = check_file_contains(str(migration_file), "AFTER 'model'", should_not_contain=True)
    # Should contain correct syntax
    correct_syntax = check_file_contains(str(migration_file), 
        'op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS \'assembly\'")')
    results.append(("PostgreSQL ALTER TYPE fix", no_after and correct_syntax))
    
    # 2. Simplified idempotency fallback
    print("2. Checking simplified idempotency fallback...")
    router_file = base_dir / "apps/api/app/routers/designs_v1.py"
    # Should NOT have try/except around json normalization
    no_try_except = check_file_contains(str(router_file), 
        r"try:\s+.*normalized_params = json\.loads", should_not_contain=True)
    # Should have simple logger.info
    has_logger_info = check_file_contains(str(router_file), 
        'logger.info(\n                "Calculating hash from params for backward compatibility"')
    results.append(("Simplified idempotency fallback", no_try_except and has_logger_info))
    
    # 3. PR294 summary fix
    print("3. Checking PR294 summary fix...")
    pr294_file = base_dir / "PR294_FIXES_SUMMARY.md"
    # Should have values_clause construction shown
    has_values_clause = check_file_contains(str(pr294_file), 
        "values_clause = ', '.join")
    results.append(("PR294 summary code snippet", has_values_clause))
    
    # 4. PR_284 summary correction
    print("4. Checking PR_284 summary correction...")
    pr284_file = base_dir / "PR_284_FIXES_SUMMARY.md"
    # Should clarify input_params is correct
    has_clarification = check_file_contains(str(pr284_file), 
        "Database column name**: `input_params`")
    results.append(("PR_284 summary clarification", has_clarification))
    
    # 5. Batch update utility module
    print("5. Checking batch update utility module...")
    utility_file = base_dir / "apps/api/alembic/utils/batch_update.py"
    exists = utility_file.exists()
    has_functions = False
    if exists:
        has_functions = (check_file_contains(str(utility_file), "def execute_batch_update") and
                        check_file_contains(str(utility_file), "def execute_params_hash_batch_update"))
    results.append(("Batch update utility module", exists and has_functions))
    
    # 6. Production checks in JWT service
    print("6. Checking production checks in JWT service...")
    jwt_file = base_dir / "apps/api/app/services/jwt_service.py"
    has_prod_check = check_file_contains(str(jwt_file), "is_production = any")
    has_critical_log = check_file_contains(str(jwt_file), 
        'logger.critical(\n                "SECURITY VIOLATION')
    results.append(("JWT production checks", has_prod_check and has_critical_log))
    
    # 7. Testable settings
    print("7. Checking testable settings...")
    schema_file = base_dir / "apps/api/app/schemas/design_v2.py"
    has_context_manager = check_file_contains(str(schema_file), 
        "class design_settings_context:")
    results.append(("Testable settings context manager", has_context_manager))
    
    # 8. Async S3 check
    print("8. Checking async S3 check...")
    storage_file = base_dir / "apps/api/app/storage.py"
    has_async_func = check_file_contains(str(storage_file), 
        "async def object_exists_async")
    has_proxy = check_file_contains(str(storage_file), "class S3ServiceProxy:")
    router_uses_async = check_file_contains(str(router_file), 
        "await s3_service.object_exists_async")
    results.append(("Async S3 check", has_async_func and has_proxy and router_uses_async))
    
    # 9. Hash algorithm documentation
    print("9. Checking hash algorithm documentation...")
    job_model_file = base_dir / "apps/api/app/models/job.py"
    has_sha256_comment = check_file_contains(str(job_model_file), 
        "# Hash algorithm: SHA-256, stored as 64-character lowercase hexadecimal string")
    has_hex_format = check_file_contains(str(job_model_file), 
        'comment="SHA-256 hash (hex format)')
    results.append(("Hash algorithm documentation", has_sha256_comment and has_hex_format))
    
    # 10. Comment consistency
    print("10. Checking comment consistency...")
    migration_file2 = base_dir / "apps/api/alembic/versions/20250825_add_params_hash_and_idempotency_constraint.py"
    has_clear_comment = check_file_contains(str(migration_file2), 
        "# CRITICAL: Database column naming clarification:")
    results.append(("Comment consistency", has_clear_comment))
    
    # Print results
    print("\n" + "="*60)
    print("PR #295 FIXES VERIFICATION RESULTS")
    print("="*60)
    
    all_passed = True
    for name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status}: {name}")
        if not passed:
            all_passed = False
    
    print("="*60)
    if all_passed:
        print("[SUCCESS] ALL FIXES VERIFIED SUCCESSFULLY!")
    else:
        print("[WARNING] Some fixes need attention")
    
    return all_passed

if __name__ == "__main__":
    verify_fixes()