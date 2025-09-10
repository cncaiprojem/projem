"""
Shared validation utilities for Version Control System.

This module provides common validation functions used across VCS components
to ensure consistency and avoid code duplication.
"""

from typing import List


def validate_branch_name(name: str) -> bool:
    """
    Validate branch name following Git conventions.
    
    Args:
        name: Branch name to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not name:
        return False
    
    # Invalid patterns (Git conventions)
    invalid_patterns = ['..', '~', '^', ':', '\\', '?', '*', '[', '@{', '//']
    for pattern in invalid_patterns:
        if pattern in name:
            return False
    
    # Can't start/end with certain characters
    if name.startswith('.') or name.startswith('-'):
        return False
    if name.endswith('.'):
        return False
    
    # Can't have consecutive dots
    if '..' in name:
        return False
    
    # Can't start or end with slash
    if name.startswith('/') or name.endswith('/'):
        return False
    
    # Can't end with .lock
    if name.endswith('.lock'):
        return False
    
    return True


def validate_tag_name(name: str) -> bool:
    """
    Validate tag name following Git conventions.
    
    Args:
        name: Tag name to validate
        
    Returns:
        True if valid, False otherwise
    """
    # Same rules as branch names for now
    return validate_branch_name(name)


def get_invalid_branch_name_reasons(name: str) -> List[str]:
    """
    Get list of reasons why a branch name is invalid.
    
    Args:
        name: Branch name to check
        
    Returns:
        List of validation error messages
    """
    errors = []
    
    if not name:
        errors.append("Branch name cannot be empty")
        return errors
    
    # Check invalid patterns
    invalid_patterns = {
        '..': "consecutive dots",
        '~': "tilde character",
        '^': "caret character",
        ':': "colon character",
        '\\': "backslash character",
        '?': "question mark",
        '*': "asterisk",
        '[': "square bracket",
        '@{': "reflog syntax",
        '//': "consecutive slashes"
    }
    
    for pattern, description in invalid_patterns.items():
        if pattern in name:
            errors.append(f"Branch name cannot contain {description} ('{pattern}')")
    
    # Check start/end conditions
    if name.startswith('.'):
        errors.append("Branch name cannot start with a dot")
    if name.startswith('-'):
        errors.append("Branch name cannot start with a hyphen")
    if name.endswith('.'):
        errors.append("Branch name cannot end with a dot")
    if name.startswith('/'):
        errors.append("Branch name cannot start with a slash")
    if name.endswith('/'):
        errors.append("Branch name cannot end with a slash")
    if name.endswith('.lock'):
        errors.append("Branch name cannot end with '.lock'")
    
    return errors