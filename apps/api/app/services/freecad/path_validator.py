"""
Shared path validation utility for FreeCAD services.

This module provides a centralized, secure path validation mechanism
to prevent directory traversal attacks and ensure all file operations
remain within designated safe directories.

Security Features:
    - Path traversal prevention using realpath resolution
    - Whitelist-based directory validation
    - Consistent error handling across services
    - Detailed logging for security auditing

Usage:
    from app.services.freecad.path_validator import PathValidator
    
    validator = PathValidator(['/work/uploads', '/tmp/freecad'])
    safe_path = validator.validate_path(user_input, 'upload')
"""

import os
from pathlib import Path
from typing import List, Optional, Union

from ...core.logging import get_logger

logger = get_logger(__name__)


class PathValidationError(ValueError):
    """Raised when a path fails validation.
    
    Inherits from ValueError to maintain backward compatibility
    with existing error handling code.
    """
    
    def __init__(self, path: str, reason: str, path_type: str = "path"):
        self.path = path
        self.reason = reason
        self.path_type = path_type
        super().__init__(f"Invalid {path_type}: {path}. Reason: {reason}")


class PathValidator:
    """
    Centralized path validation utility for secure file operations.
    
    This class provides a single source of truth for path validation
    logic, eliminating code duplication and ensuring consistent
    security checks across all FreeCAD services.
    """
    
    def __init__(self, allowed_directories: Optional[List[str]] = None):
        """
        Initialize the path validator with allowed directories.
        
        Args:
            allowed_directories: List of directories where operations are permitted.
                                If None, uses default safe directories.
        """
        if allowed_directories is None:
            # Default safe directories for FreeCAD operations
            self.allowed_dirs = [
                "/work/uploads",
                "/tmp/freecad_uploads",
                "/work/freecad",
                "/tmp/freecad_templates"
            ]
        else:
            self.allowed_dirs = allowed_directories
        
        # Resolve all allowed directories to their real paths
        self.resolved_dirs = []
        for dir_path in self.allowed_dirs:
            try:
                if os.path.exists(dir_path):
                    resolved = os.path.realpath(dir_path)
                    self.resolved_dirs.append(resolved)
                    logger.debug(f"Allowed directory resolved: {dir_path} -> {resolved}")
                else:
                    logger.warning(f"Allowed directory does not exist: {dir_path}")
            except Exception as e:
                logger.warning(f"Could not resolve allowed directory {dir_path}: {e}")
    
    def validate_path(
        self,
        path: Union[str, Path],
        path_type: str = "path",
        must_exist: bool = False,
        create_parents: bool = False
    ) -> Path:
        """
        Validate a path is within allowed directories and safe to use.
        
        Args:
            path: Path to validate (absolute or relative)
            path_type: Type of path for error messages (e.g., "upload", "template")
            must_exist: If True, the path must already exist
            create_parents: If True, create parent directories if they don't exist
            
        Returns:
            Validated Path object
            
        Raises:
            PathValidationError: If the path is invalid or outside allowed directories
        """
        # Convert to Path object for consistent handling
        if isinstance(path, str):
            path = Path(path)
        
        # Handle absolute vs relative paths
        if path.is_absolute():
            # Direct validation for absolute paths
            resolved_path = Path(os.path.realpath(str(path)))
        else:
            # For relative paths, try each allowed directory
            resolved_path = None
            for allowed_dir in self.resolved_dirs:
                candidate = Path(allowed_dir) / path
                candidate_resolved = Path(os.path.realpath(str(candidate)))
                
                # Check if the resolved path is within this allowed directory
                try:
                    candidate_resolved.relative_to(allowed_dir)
                    resolved_path = candidate_resolved
                    break
                except ValueError:
                    # Path is outside this allowed directory, try next
                    continue
            
            if resolved_path is None:
                # Try with first allowed directory as default
                if self.resolved_dirs:
                    candidate = Path(self.resolved_dirs[0]) / path
                    resolved_path = Path(os.path.realpath(str(candidate)))
                else:
                    raise PathValidationError(
                        str(path),
                        "No allowed directories configured",
                        path_type
                    )
        
        # Security check: Ensure resolved path is within allowed directories
        is_allowed = False
        allowed_parent = None
        
        for allowed_dir in self.resolved_dirs:
            try:
                # Check if resolved path is within this allowed directory
                resolved_path.relative_to(allowed_dir)
                is_allowed = True
                allowed_parent = allowed_dir
                break
            except ValueError:
                # Path is outside this allowed directory
                continue
        
        if not is_allowed:
            logger.warning(
                f"Path traversal attempt detected: {path} -> {resolved_path} "
                f"(not in allowed dirs: {self.resolved_dirs})"
            )
            raise PathValidationError(
                str(path),
                "Path is outside allowed directories (potential traversal attack)",
                path_type
            )
        
        # Check existence if required
        if must_exist and not resolved_path.exists():
            raise PathValidationError(
                str(path),
                "Path does not exist",
                path_type
            )
        
        # Create parent directories if requested
        if create_parents and not resolved_path.parent.exists():
            try:
                resolved_path.parent.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created parent directories for {path_type}: {resolved_path.parent}")
            except Exception as e:
                raise PathValidationError(
                    str(path),
                    f"Could not create parent directories: {e}",
                    path_type
                )
        
        logger.debug(f"Path validated successfully: {path} -> {resolved_path} ({path_type})")
        return resolved_path
    
    def is_path_safe(self, path: Union[str, Path]) -> bool:
        """
        Check if a path is safe without raising exceptions.
        
        Args:
            path: Path to check
            
        Returns:
            True if path is within allowed directories, False otherwise
        """
        try:
            self.validate_path(path)
            return True
        except PathValidationError:
            return False
    
    def get_safe_filename(self, filename: str) -> str:
        """
        Sanitize a filename to remove potentially dangerous characters.
        
        Args:
            filename: Original filename
            
        Returns:
            Sanitized filename safe for filesystem operations
        """
        import re
        
        # Remove path separators and null bytes
        filename = filename.replace('/', '_').replace('\\', '_').replace('\x00', '')
        
        # Remove leading dots (hidden files)
        filename = filename.lstrip('.')
        
        # Keep only safe characters: alphanumeric, dash, underscore, dot
        filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
        
        # Limit length to prevent filesystem issues
        max_length = 255
        if len(filename) > max_length:
            # Preserve extension if present
            parts = filename.rsplit('.', 1)
            if len(parts) == 2 and len(parts[1]) < 10:  # Reasonable extension length
                base = parts[0][:max_length - len(parts[1]) - 1]
                filename = f"{base}.{parts[1]}"
            else:
                filename = filename[:max_length]
        
        # Ensure filename is not empty
        if not filename:
            filename = "unnamed_file"
        
        return filename


# Global instance for convenience
default_validator = PathValidator()


def validate_path(
    path: Union[str, Path],
    path_type: str = "path",
    allowed_directories: Optional[List[str]] = None
) -> Path:
    """
    Convenience function for path validation using default or custom validator.
    
    Args:
        path: Path to validate
        path_type: Type of path for error messages
        allowed_directories: Optional custom list of allowed directories
        
    Returns:
        Validated Path object
        
    Raises:
        PathValidationError: If the path is invalid
    """
    if allowed_directories:
        validator = PathValidator(allowed_directories)
    else:
        validator = default_validator
    
    return validator.validate_path(path, path_type)