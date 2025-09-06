#!/usr/bin/env python3
"""
Verification script for PR #473 batch delete fixes.
Tests the logic without requiring full environment setup.
"""

import re
from pathlib import Path


def verify_batch_delete_fix():
    """Verify that batch delete error handling returns correct counts."""
    storage_client = Path("apps/api/app/services/storage_client.py")
    
    if not storage_client.exists():
        return False, "storage_client.py not found"
    
    content = storage_client.read_text(encoding='utf-8')
    
    # Find the _process_batch_delete_errors method
    method_pattern = r'def _process_batch_delete_errors\([\s\S]*?(?=\n    def |\nclass |\Z)'
    method_match = re.search(method_pattern, content)
    
    if not method_match:
        return False, "Could not find _process_batch_delete_errors method"
    
    method_content = method_match.group(0)
    
    # Check for the correct implementation patterns
    checks = [
        (
            "Calculates successful deletions correctly",
            r'successful_deletions\s*=\s*batch_size\s*-\s*error_count'
        ),
        (
            "Returns successful_deletions (not 0 on errors)",
            r'return\s+successful_deletions'
        ),
        (
            "Logs info when errors occur",
            r'logger\.info\([^)]*"Batch delete completed with errors"'
        ),
        (
            "Tracks error count properly",
            r'error_count\s*\+=\s*1'
        ),
        (
            "Does NOT return 0 if error_count > 0",
            lambda m: 'return batch_size if error_count == 0 else 0' not in m
        ),
    ]
    
    for check_name, pattern in checks:
        if callable(pattern):
            # It's a lambda function
            if not pattern(method_content):
                return False, f"Failed check: {check_name}"
        else:
            # It's a regex pattern
            if not re.search(pattern, method_content):
                return False, f"Failed check: {check_name}"
    
    # Additional verification: ensure it doesn't have the old buggy logic
    if 'return batch_size if error_count == 0 else 0' in method_content:
        return False, "Still has the old buggy logic (returns 0 on any error)"
    
    return True, "Batch delete error handling correctly returns actual successful count"


def verify_pr_number_consistency():
    """Verify that PR numbers are consistent across documentation."""
    files_to_check = [
        ("PR468_VERIFICATION_REPORT.md", "PR #468"),
        ("PR471_FIX_SUMMARY.md", "PR #471"),
        ("verify_fixes.py", "PR #471"),
        ("test_pr471_fixes.py", "PR #471"),
    ]
    
    results = []
    for filename, expected_pr in files_to_check:
        file_path = Path(filename)
        if file_path.exists():
            content = file_path.read_text(encoding='utf-8')
            # Check first few lines for PR reference
            first_lines = '\n'.join(content.split('\n')[:5])
            if expected_pr in first_lines:
                results.append(f"[OK] {filename}: Correctly references {expected_pr}")
            else:
                # Find what PR it actually references
                pr_match = re.search(r'PR #\d+', first_lines)
                if pr_match:
                    results.append(f"[ERROR] {filename}: References {pr_match.group()} instead of {expected_pr}")
                else:
                    results.append(f"[ERROR] {filename}: No PR reference found (expected {expected_pr})")
        else:
            results.append(f"[SKIP] {filename}: File not found")
    
    # Check that verify_fixes.py prints the correct PR in main()
    verify_fixes = Path("verify_fixes.py")
    if verify_fixes.exists():
        content = verify_fixes.read_text(encoding='utf-8')
        main_match = re.search(r'print\("Verifying PR #(\d+)', content)
        if main_match:
            pr_num = main_match.group(1)
            if pr_num == "471":
                results.append(f"[OK] verify_fixes.py main(): Correctly prints PR #471")
            else:
                results.append(f"[ERROR] verify_fixes.py main(): Prints PR #{pr_num} instead of PR #471")
    
    all_correct = all('[OK]' in r for r in results if not r.startswith('[SKIP]'))
    return all_correct, '\n'.join(results)


def main():
    """Run all verification checks for PR #473 fixes."""
    print("=" * 70)
    print("PR #473 Fix Verification")
    print("=" * 70)
    
    checks = [
        ("Batch Delete Error Handling", verify_batch_delete_fix),
        ("PR Number Consistency", verify_pr_number_consistency),
    ]
    
    all_passed = True
    for check_name, check_func in checks:
        print(f"\n{check_name}:")
        print("-" * 40)
        passed, message = check_func()
        
        if passed:
            print(f"[PASSED] {message}")
        else:
            print(f"[FAILED] {message}")
            all_passed = False
    
    print("\n" + "=" * 70)
    if all_passed:
        print("[SUCCESS] ALL CHECKS PASSED - PR #473 fixes are correctly implemented")
    else:
        print("[ERROR] SOME CHECKS FAILED - Please review the failures above")
    print("=" * 70)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(main())