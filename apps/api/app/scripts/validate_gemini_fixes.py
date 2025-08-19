#!/usr/bin/env python3
"""
Validation script for Gemini Code Assist critical fixes for PR #127.
Tests all the fixed issues to ensure ultra-enterprise standards are met.
"""

import sys
import re
from pathlib import Path
from typing import List, Tuple

# Color codes for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"


def print_header(title: str):
    """Print a formatted header."""
    print(f"\n{BOLD}{BLUE}{'=' * 60}{RESET}")
    print(f"{BOLD}{BLUE}{title:^60}{RESET}")
    print(f"{BOLD}{BLUE}{'=' * 60}{RESET}\n")


def print_result(test_name: str, passed: bool, details: str = ""):
    """Print test result with color coding."""
    status = f"{GREEN}[PASSED]{RESET}" if passed else f"{RED}[FAILED]{RESET}"
    print(f"  {status} - {test_name}")
    if details:
        print(f"    {YELLOW}-> {details}{RESET}")


def validate_sms_constraint_fix() -> Tuple[bool, str]:
    """Validate that SMS constraint is exactly = 160, not <= 160."""
    migration_path = Path(
        "apps/api/alembic/versions/20250819_0000-task_47_notification_service_email_sms_provider_fallback.py"
    )
    model_path = Path("apps/api/app/models/notification_template.py")

    issues = []

    # Check migration file
    with open(migration_path, "r", encoding="utf-8") as f:
        migration_content = f.read()

    # Check for correct constraint in migration
    if "(channel = 'sms' AND max_length = 160)" not in migration_content:
        issues.append("Migration: SMS constraint not fixed to '= 160'")
    if "(channel = 'sms' AND max_length <= 160)" in migration_content:
        issues.append("Migration: Still contains wrong '<= 160' constraint")

    # Check model file
    with open(model_path, "r", encoding="utf-8") as f:
        model_content = f.read()

    # Check for correct constraint in model
    if "(channel = 'sms' AND max_length = 160)" not in model_content:
        issues.append("Model: SMS constraint not fixed to '= 160'")

    return len(issues) == 0, "; ".join(
        issues
    ) if issues else "SMS constraint correctly set to = 160"


def validate_no_security_event_import() -> Tuple[bool, str]:
    """Validate that SecurityEventService import is removed from payment_service.py."""
    payment_service_path = Path("apps/api/app/services/payment_service.py")

    with open(payment_service_path, "r", encoding="utf-8") as f:
        content = f.read()

    issues = []

    # Check for the bad import
    if "from .security_event_service import SecurityEventService" in content:
        issues.append("SecurityEventService import still present")

    # Check for actual instantiation or usage (not in comments)
    lines = content.split("\n")
    for i, line in enumerate(lines, 1):
        # Skip comment lines
        if "#" in line:
            line = line[: line.index("#")]

        # Check for SecurityEventService usage
        if "SecurityEventService()" in line:
            issues.append(f"Line {i}: SecurityEventService instantiation found")
        elif "SecurityEventService." in line:
            issues.append(f"Line {i}: SecurityEventService method call found")

    return len(issues) == 0, "; ".join(
        issues
    ) if issues else "No SecurityEventService imports or code references found"


def validate_unique_constraint_as_index() -> Tuple[bool, str]:
    """Validate that unique constraint is implemented as partial index, not UniqueConstraint."""
    migration_path = Path(
        "apps/api/alembic/versions/20250819_0000-task_47_notification_service_email_sms_provider_fallback.py"
    )

    with open(migration_path, "r", encoding="utf-8") as f:
        content = f.read()

    issues = []

    # Check for wrong UniqueConstraint usage
    if re.search(
        r"sa\.UniqueConstraint\([^)]*'type'[^)]*'channel'[^)]*'language'[^)]*'is_active'", content
    ):
        issues.append("Still using UniqueConstraint instead of Index")

    # Check for correct Index with partial where clause
    if not re.search(
        r"sa\.Index\([^)]*'uq_notification_templates_active'[^)]*unique=True[^)]*postgresql_where",
        content,
    ):
        issues.append("Partial unique index not properly implemented")

    # Verify the where clause is correct
    if 'postgresql_where=sa.text("is_active = true")' not in content:
        issues.append("Partial index where clause not correct")

    return len(issues) == 0, "; ".join(issues) if issues else "Correctly using partial unique index"


def validate_no_sql_injection() -> Tuple[bool, str]:
    """Validate that template seeding uses parameterized queries, not f-strings."""
    migration_path = Path(
        "apps/api/alembic/versions/20250819_0000-task_47_notification_service_email_sms_provider_fallback.py"
    )

    with open(migration_path, "r", encoding="utf-8") as f:
        content = f.read()

    issues = []

    # Check for f-string in SQL (SQL injection vulnerability)
    insert_section = content[
        content.find("def insert_default_templates") : content.find("def downgrade")
    ]

    if re.search(r'text\(f""".*INSERT INTO', insert_section, re.DOTALL):
        issues.append("Found f-string in SQL query - SQL injection vulnerability!")

    if re.search(r"text\(f'.*INSERT INTO", insert_section, re.DOTALL):
        issues.append("Found f-string in SQL query - SQL injection vulnerability!")

    # Check for proper parameterized query
    if ":type, :channel" not in insert_section:
        issues.append("Not using proper parameter placeholders")

    # Verify template values are passed as parameters
    if "'type': template['type']" not in insert_section:
        issues.append("Template type not passed as parameter")

    if "'channel': template['channel']" not in insert_section:
        issues.append("Template channel not passed as parameter")

    return len(issues) == 0, "; ".join(issues) if issues else "Using secure parameterized queries"


def validate_session_management() -> Tuple[bool, str]:
    """Validate that get_active_template accepts session as parameter."""
    model_path = Path("apps/api/app/models/notification_template.py")

    with open(model_path, "r", encoding="utf-8") as f:
        content = f.read()

    issues = []

    # Find the get_active_template method
    method_match = re.search(r"def get_active_template\([^)]+\)", content)

    if not method_match:
        issues.append("Could not find get_active_template method")
    else:
        method_sig = method_match.group(0)
        if "db: Session" not in method_sig:
            issues.append("Method doesn't accept db session as parameter")

        # Check it's the first parameter after cls
        if not re.match(r"def get_active_template\(\s*cls,\s*db:", method_sig):
            issues.append("db parameter should be first after cls")

    # Check for SessionLocal usage (should not be there)
    method_section = content[
        content.find("def get_active_template") : content.find(
            "def create_license_reminder_templates"
        )
    ]
    if "SessionLocal" in method_section:
        issues.append("Still using SessionLocal instead of passed session")

    if "with SessionLocal() as db:" in method_section:
        issues.append("Creating own session instead of using parameter")

    return len(issues) == 0, "; ".join(
        issues
    ) if issues else "Properly accepts session as parameter"


def validate_python_syntax() -> Tuple[bool, str]:
    """Validate that all modified files have valid Python syntax."""
    files_to_check = [
        "apps/api/app/services/payment_service.py",
        "apps/api/app/models/notification_template.py",
        "apps/api/alembic/versions/20250819_0000-task_47_notification_service_email_sms_provider_fallback.py",
    ]

    issues = []

    for file_path in files_to_check:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                code = f.read()
            compile(code, file_path, "exec")
        except SyntaxError as e:
            issues.append(f"{Path(file_path).name}: {e}")

    return len(issues) == 0, "; ".join(issues) if issues else "All files have valid Python syntax"


def main():
    """Run all validation tests."""
    print_header("GEMINI CODE ASSIST FIXES VALIDATION")
    print(f"{BOLD}Validating critical fixes for PR #127{RESET}\n")

    tests = [
        ("SMS Constraint Fix (= 160)", validate_sms_constraint_fix),
        ("Security Event Import Removal", validate_no_security_event_import),
        ("Unique Constraint as Partial Index", validate_unique_constraint_as_index),
        ("SQL Injection Prevention", validate_no_sql_injection),
        ("Session Management Fix", validate_session_management),
        ("Python Syntax Validation", validate_python_syntax),
    ]

    results = []
    for test_name, test_func in tests:
        passed, details = test_func()
        results.append(passed)
        print_result(test_name, passed, details)

    print(f"\n{BOLD}{'=' * 60}{RESET}")

    # Summary
    total_tests = len(tests)
    passed_tests = sum(results)

    if all(results):
        print(f"{BOLD}{GREEN}[SUCCESS] ALL TESTS PASSED ({passed_tests}/{total_tests}){RESET}")
        print(f"{GREEN}All Gemini Code Assist critical issues have been fixed!{RESET}")
        return 0
    else:
        print(f"{BOLD}{RED}[ERROR] SOME TESTS FAILED ({passed_tests}/{total_tests}){RESET}")
        print(f"{RED}Please review the failed tests above.{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
