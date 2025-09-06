#!/usr/bin/env python3
"""
Test script to verify all PR #471 fixes have been applied correctly.
"""

import ast
import sys
from pathlib import Path


def test_singleton_storage_client():
    """Test that storage client singleton is properly implemented."""
    storage_file = Path("apps/api/app/core/storage.py")
    
    if not storage_file.exists():
        return False, "Storage singleton file not found"
    
    content = storage_file.read_text(encoding='utf-8')
    
    # Check for key singleton patterns
    checks = [
        ("StorageManager class exists", "class StorageManager"),
        ("Singleton pattern implemented", "_instance: Optional"),
        ("get_storage_client function", "def get_storage_client"),
        ("lru_cache decorator", "@lru_cache"),
        ("initialize_storage function", "async def initialize_storage"),
        ("initialize_buckets method", "async def initialize_buckets"),
    ]
    
    for check_name, pattern in checks:
        if pattern not in content:
            return False, f"Missing: {check_name}"
    
    return True, "Storage singleton properly implemented"


def test_lifespan_initialization():
    """Test that storage initialization is in lifespan context."""
    main_file = Path("apps/api/app/main.py")
    
    if not main_file.exists():
        return False, "Main file not found"
    
    content = main_file.read_text(encoding='utf-8')
    
    # Check for storage initialization in lifespan
    if "from .core.storage import initialize_storage" not in content:
        return False, "Storage import not found in main.py"
    
    if "await initialize_storage()" not in content:
        return False, "Storage initialization not called in lifespan"
    
    if "storage_initialization" not in content:
        return False, "Storage initialization logging not found"
    
    return True, "Storage initialization properly added to lifespan"


def test_artefact_service_no_init():
    """Test that ArtefactServiceV2 no longer initializes bucket in __init__."""
    service_file = Path("apps/api/app/services/artefact_service_v2.py")
    
    if not service_file.exists():
        return False, "ArtefactServiceV2 file not found"
    
    content = service_file.read_text(encoding='utf-8')
    
    # Check that _initialize_bucket method is removed
    if "def _initialize_bucket" in content:
        return False, "_initialize_bucket method still exists"
    
    # Check for singleton import
    if "from app.core.storage import get_storage_client" not in content:
        return False, "get_storage_client import not found"
    
    # Check that singleton is used
    if "storage_client or get_storage_client()" not in content:
        return False, "Singleton storage client not used"
    
    return True, "ArtefactServiceV2 properly uses singleton"


def test_async_database_calls():
    """Test that all database calls are wrapped in asyncio.to_thread."""
    service_file = Path("apps/api/app/services/artefact_service_v2.py")
    
    if not service_file.exists():
        return False, "ArtefactServiceV2 file not found"
    
    content = service_file.read_text(encoding='utf-8')
    
    # Check for async wrapping in key methods
    checks = [
        "await asyncio.to_thread(self.db.commit)",
        "await asyncio.to_thread(self.db.rollback)",
        "await asyncio.to_thread(self.db.add",
        "await asyncio.to_thread(self.db.query",
    ]
    
    missing = []
    for check in checks:
        if check not in content:
            missing.append(check)
    
    if missing:
        return False, f"Missing async wrapping: {', '.join(missing[:2])}"
    
    return True, "Database calls properly wrapped in asyncio.to_thread"


def test_user_variable_in_test():
    """Test that user variable is properly defined in test."""
    test_file = Path("apps/api/tests/test_task_711_artefact_storage.py")
    
    if not test_file.exists():
        return False, "Test file not found"
    
    content = test_file.read_text(encoding='utf-8')
    
    # Check for user definition in test_turkish_error_messages
    if "def test_turkish_error_messages" not in content:
        return False, "test_turkish_error_messages not found"
    
    # Find the test method
    lines = content.split('\n')
    in_test = False
    user_defined = False
    
    for line in lines:
        if "def test_turkish_error_messages" in line:
            in_test = True
        elif in_test and "def " in line and "test_" in line:
            break
        elif in_test and "user = User(" in line:
            user_defined = True
            break
    
    if not user_defined:
        return False, "User variable not defined in test_turkish_error_messages"
    
    return True, "User variable properly defined in test"


def test_redundant_dependencies():
    """Test that redundant dependencies are removed from router."""
    router_file = Path("apps/api/app/routers/artefacts_v2.py")
    
    if not router_file.exists():
        return False, "Router file not found"
    
    content = router_file.read_text(encoding='utf-8')
    
    # Check that redundant dependencies are removed
    lines = content.split('\n')
    found_redundant = False
    
    for i, line in enumerate(lines):
        if "dependencies=[Depends(get_current_user)]" in line:
            # Check if the next few lines also have current_user parameter
            for j in range(i+1, min(i+10, len(lines))):
                if "current_user: User = Depends(get_current_user)" in lines[j]:
                    found_redundant = True
                    break
    
    if found_redundant:
        return False, "Redundant dependencies still exist in router"
    
    return True, "Redundant dependencies removed from router"


def test_documentation_updates():
    """Test that documentation has correct PR number."""
    verification_file = Path("PR468_VERIFICATION_REPORT.md")
    
    if verification_file.exists():
        content = verification_file.read_text(encoding='utf-8')
        if "PR #471" not in content:
            return False, "Verification report still shows PR #468"
    
    verify_script = Path("verify_fixes.py")
    if verify_script.exists():
        content = verify_script.read_text(encoding='utf-8')
        if "PR #471" not in content[:200]:  # Check in docstring
            return False, "Verify script docstring still shows PR #468"
    
    return True, "Documentation properly updated"


def main():
    """Run all tests."""
    # Set UTF-8 encoding for Windows console
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    print("=" * 60)
    print("PR #471 Fixes Verification")
    print("=" * 60)
    
    tests = [
        ("1. Storage Singleton Implementation", test_singleton_storage_client),
        ("2. Lifespan Initialization", test_lifespan_initialization),
        ("3. ArtefactServiceV2 Uses Singleton", test_artefact_service_no_init),
        ("4. Async Database Calls", test_async_database_calls),
        ("5. Test User Variable", test_user_variable_in_test),
        ("6. Redundant Dependencies", test_redundant_dependencies),
        ("7. Documentation Updates", test_documentation_updates),
    ]
    
    all_passed = True
    
    for name, test_func in tests:
        try:
            passed, message = test_func()
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"\n{name}: {status}")
            print(f"  {message}")
            if not passed:
                all_passed = False
        except Exception as e:
            print(f"\n{name}: ❌ ERROR")
            print(f"  {str(e)}")
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ All PR #471 fixes verified successfully!")
        return 0
    else:
        print("❌ Some fixes are missing or incorrect")
        return 1


if __name__ == "__main__":
    sys.exit(main())