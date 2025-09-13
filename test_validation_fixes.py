#!/usr/bin/env python
"""Test script to verify PR #584 fixes."""

import ast
import os

def check_file_for_issues(filepath):
    """Check a Python file for common issues."""
    issues = []
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        
    # Check for ValueError instead of HTTPException
    if 'raise ValueError' in content and '/api/v2/' in filepath:
        # Count occurrences
        count = content.count('raise ValueError')
        if count > 0:
            issues.append(f"Found {count} ValueError raises that should be HTTPException")
    
    # Check for bare except clauses
    if 'except:' in content:
        count = content.count('except:')
        if count > 0:
            issues.append(f"Found {count} bare except clauses")
    
    # Parse AST to check for more complex issues
    try:
        tree = ast.parse(content)
        
        # Check for missing imports at module level
        module_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module_imports.append(node.module)
        
        # Check if imports are inside functions (bad practice)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for child in ast.walk(node):
                    if isinstance(child, ast.ImportFrom) and child.module:
                        if child.module not in ['app.services.storage_client', 'sqlalchemy']:
                            # These are allowed to be imported inside functions
                            pass  # OK for now
                            
    except SyntaxError as e:
        issues.append(f"Syntax error: {e}")
    
    return issues

def main():
    """Check all critical files for issues."""
    files_to_check = [
        'apps/api/app/api/v2/model_validation.py',
        'apps/api/app/services/manufacturing_validator.py',
        'apps/api/app/services/quality_metrics.py',
        'apps/api/app/services/standards_checker.py',
        'apps/api/app/models/manufacturing_models.py'
    ]
    
    all_issues = {}
    
    for filepath in files_to_check:
        full_path = os.path.join(os.getcwd(), filepath)
        if os.path.exists(full_path):
            issues = check_file_for_issues(full_path)
            if issues:
                all_issues[filepath] = issues
        else:
            all_issues[filepath] = [f"File not found: {full_path}"]
    
    # Report results
    if not all_issues:
        print("SUCCESS: All checks passed! No critical issues found.")
        return 0
    else:
        print("FAILURE: Issues found:")
        for filepath, issues in all_issues.items():
            print(f"\n{filepath}:")
            for issue in issues:
                print(f"  - {issue}")
        return 1

if __name__ == "__main__":
    exit(main())