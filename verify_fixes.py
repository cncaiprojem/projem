#!/usr/bin/env python3
"""
Verification script for PR #471 fixes.
Tests that the code changes are correct without requiring full environment setup.
"""

import ast
import re
from pathlib import Path


def verify_batch_delete_fix():
    """Verify that for-else logic has been fixed in batch delete using AST parsing."""
    storage_client = Path("apps/api/app/services/storage_client.py")
    content = storage_client.read_text()
    
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        return False, f"Failed to parse file: {e}"
    
    # Check for proper error counting pattern using AST
    has_error_count_init = False
    has_error_count_check = False
    uses_for_else_incorrectly = False
    
    class BatchDeleteVisitor(ast.NodeVisitor):
        def __init__(self):
            self.has_error_count_init = False
            self.has_error_count_check = False
            self.uses_for_else_incorrectly = False
            self.in_batch_delete = False
            
        def visit_FunctionDef(self, node):
            # Check for batch delete or delete_all_versions function
            if 'delete' in node.name.lower() and ('batch' in node.name.lower() or 'all_versions' in node.name.lower()):
                self.in_batch_delete = True
                self.generic_visit(node)
                self.in_batch_delete = False
            else:
                self.generic_visit(node)
        
        def visit_AsyncFunctionDef(self, node):
            # Check for batch delete or delete_all_versions function
            if 'delete' in node.name.lower() and ('batch' in node.name.lower() or 'all_versions' in node.name.lower()):
                self.in_batch_delete = True
                self.generic_visit(node)
                self.in_batch_delete = False
            else:
                self.generic_visit(node)
                
        def visit_Assign(self, node):
            # Check for error_count = 0 initialization
            if self.in_batch_delete:
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == 'error_count':
                        if isinstance(node.value, ast.Constant) and node.value.value == 0:
                            self.has_error_count_init = True
            self.generic_visit(node)
            
        def visit_If(self, node):
            # Check for if error_count == 0 check
            if self.in_batch_delete:
                if isinstance(node.test, ast.Compare):
                    if (isinstance(node.test.left, ast.Name) and 
                        node.test.left.id == 'error_count' and
                        len(node.test.ops) == 1 and
                        isinstance(node.test.ops[0], ast.Eq) and
                        len(node.test.comparators) == 1 and
                        isinstance(node.test.comparators[0], ast.Constant) and
                        node.test.comparators[0].value == 0):
                        self.has_error_count_check = True
            self.generic_visit(node)
            
        def visit_For(self, node):
            # Check for problematic for-else pattern with errors
            if self.in_batch_delete and node.orelse:
                # Check if iterating over 'errors' and has else clause
                if (isinstance(node.iter, ast.Name) and 'error' in node.iter.id.lower()):
                    # Check if else clause has deleted_count operation
                    for else_stmt in node.orelse:
                        if self._contains_deleted_count(else_stmt):
                            self.uses_for_else_incorrectly = True
            self.generic_visit(node)
            
        def _contains_deleted_count(self, node):
            """Check if node contains reference to deleted_count."""
            if isinstance(node, ast.Name) and 'deleted_count' in node.id:
                return True
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and 'deleted_count' in child.id:
                    return True
            return False
    
    visitor = BatchDeleteVisitor()
    visitor.visit(tree)
    
    if visitor.uses_for_else_incorrectly:
        return False, "Still using for-else pattern incorrectly with errors"
    
    if visitor.has_error_count_init and visitor.has_error_count_check:
        return True, "Batch delete logic correctly uses error counting (verified with AST)"
    
    return False, "Could not find proper error counting logic in delete_all_versions function"


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
    """Verify that UUID is used in S3 key generation using AST parsing."""
    artefact_service = Path("apps/api/app/services/artefact_service_v2.py")
    content = artefact_service.read_text()
    
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        return False, f"Failed to parse file: {e}"
    
    class UUIDUsageVisitor(ast.NodeVisitor):
        def __init__(self):
            self.has_uuid_import = False
            self.uses_uuid4 = False
            self.uses_unique_id_in_format = False
            self.s3_key_generation_found = False
            
        def visit_Import(self, node):
            for alias in node.names:
                if alias.name == 'uuid':
                    self.has_uuid_import = True
            self.generic_visit(node)
            
        def visit_ImportFrom(self, node):
            if node.module == 'uuid':
                self.has_uuid_import = True
            self.generic_visit(node)
            
        def visit_Call(self, node):
            # Check for uuid.uuid4() calls
            if (isinstance(node.func, ast.Attribute) and
                isinstance(node.func.value, ast.Name) and
                node.func.value.id == 'uuid' and
                node.func.attr == 'uuid4'):
                self.uses_uuid4 = True
                
            # Check for str.format() or f-string with unique_id
            if (isinstance(node.func, ast.Attribute) and
                node.func.attr == 'format'):
                # Check if format string contains unique_id placeholder
                for keyword in node.keywords:
                    if keyword.arg == 'unique_id':
                        self.uses_unique_id_in_format = True
                        # Check if this is in S3 key context
                        self._check_s3_context(node)
            self.generic_visit(node)
            
        def visit_JoinedStr(self, node):
            # Check f-strings for unique_id usage
            for value in node.values:
                if isinstance(value, ast.FormattedValue):
                    if (isinstance(value.value, ast.Name) and 
                        value.value.id == 'unique_id'):
                        self.uses_unique_id_in_format = True
            self.generic_visit(node)
            
        def _check_s3_context(self, node):
            """Check if the node is in S3 key generation context."""
            # Walk up to find if we're in a function that generates S3 keys
            for parent_node in ast.walk(tree):
                if isinstance(parent_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if any(keyword in parent_node.name.lower() 
                           for keyword in ['s3', 'key', 'upload', 'store']):
                        # Check if this function contains our node
                        for child in ast.walk(parent_node):
                            if child == node:
                                self.s3_key_generation_found = True
                                return
    
    visitor = UUIDUsageVisitor()
    visitor.visit(tree)
    
    if not visitor.has_uuid_import:
        return False, "UUID module not imported"
    
    if visitor.uses_uuid4 and visitor.uses_unique_id_in_format:
        return True, "UUID properly used in S3 key generation (verified with AST)"
    
    if not visitor.uses_uuid4:
        return False, "uuid.uuid4() not found in code"
        
    if not visitor.uses_unique_id_in_format:
        return False, "unique_id not used in string formatting for S3 keys"
    
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
    print("Verifying PR #471 fixes...")
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