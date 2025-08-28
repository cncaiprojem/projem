"""
Shared security validation utility for AST-based code validation.

This module provides a unified security validator that ensures consistent
security enforcement across all services that need to validate Python scripts.
"""

from __future__ import annotations

import ast
import threading
from typing import List, Set, Optional, Tuple

from ..core.logging import get_logger

logger = get_logger(__name__)


class SecurityValidationError(Exception):
    """Security validation failed exception."""
    pass


class ASTSecurityValidator:
    """
    Thread-safe AST-based security validator for FreeCAD Python scripts.
    
    This validator performs comprehensive security checks including:
    - Import whitelist enforcement
    - Forbidden function/attribute blocking
    - AST depth limiting
    - Node count limiting
    - Recursive structure detection
    - Dunder method protection
    - Lambda function blocking
    - Timeout protection (cross-platform)
    """
    
    # Configuration constants
    MAX_SCRIPT_LENGTH = 50000  # 50KB max script size
    MAX_PARSE_TIME = 2.0  # 2 seconds max for parsing
    MAX_AST_DEPTH = 100  # Maximum AST depth
    MAX_NODE_COUNT = 10000  # Maximum number of AST nodes
    
    # Whitelist of allowed modules
    ALLOWED_IMPORTS: Set[str] = {
        'FreeCAD', 'App', 'Part', 'PartDesign', 
        'Sketcher', 'Draft', 'Import', 'Mesh', 
        'math', 'numpy', 'Base', 'Vector'
    }
    
    # Forbidden function/attribute names (comprehensive list)
    FORBIDDEN_CALLS: Set[str] = {
        '__import__', 'exec', 'eval', 'compile', 'execfile',
        'open', 'file', 'input', 'raw_input', 'reload',
        'os', 'subprocess', 'sys', 'importlib', 'getattr', 
        'setattr', 'delattr', 'hasattr', 'globals', 'locals',
        'vars', 'dir', '__builtins__', 'help', 'id', 'type',
        'memoryview', 'bytearray', 'bytes', 'object'
    }
    
    # Forbidden dunder attributes
    FORBIDDEN_DUNDERS: Set[str] = {
        '__dict__', '__class__', '__bases__', '__base__',
        '__subclasses__', '__import__', '__builtins__',
        '__code__', '__globals__', '__annotations__'
    }
    
    def __init__(self):
        """Initialize security validator."""
        self._lock = threading.Lock()
    
    def validate_script(
        self,
        script: str,
        raise_on_error: bool = True
    ) -> Tuple[bool, List[str]]:
        """
        Validate a Python script for security violations.
        
        Args:
            script: The Python script to validate
            raise_on_error: Whether to raise exception on validation failure
            
        Returns:
            Tuple of (is_valid, list_of_violations)
            
        Raises:
            SecurityValidationError: If validation fails and raise_on_error is True
        """
        with self._lock:
            violations = []
            
            # Check script size
            if len(script) > self.MAX_SCRIPT_LENGTH:
                violation = f"Script too large: {len(script)} bytes (max {self.MAX_SCRIPT_LENGTH})"
                violations.append(violation)
                if raise_on_error:
                    raise SecurityValidationError(violation)
                return False, violations
            
            # Parse with timeout protection
            try:
                tree = self._parse_with_timeout(script)
            except (SyntaxError, TimeoutError) as e:
                violation = f"Parse error: {e}"
                violations.append(violation)
                if raise_on_error:
                    raise SecurityValidationError(violation)
                return False, violations
            
            # Validate AST
            validator = self._SecurityValidator(
                self.ALLOWED_IMPORTS,
                self.FORBIDDEN_CALLS,
                self.FORBIDDEN_DUNDERS,
                self.MAX_AST_DEPTH,
                self.MAX_NODE_COUNT
            )
            
            validator.visit(tree)
            violations.extend(validator.violations)
            
            if violations and raise_on_error:
                raise SecurityValidationError(f"Security violations found: {'; '.join(violations)}")
            
            return len(violations) == 0, violations
    
    def _parse_with_timeout(self, script: str) -> ast.AST:
        """
        Parse script with timeout protection (cross-platform).
        
        Args:
            script: Python script to parse
            
        Returns:
            AST tree
            
        Raises:
            TimeoutError: If parsing takes too long
            SyntaxError: If script has invalid syntax
        """
        timeout_occurred = threading.Event()
        parse_result = {'tree': None, 'error': None}
        
        def parse_with_timeout():
            """Parse script in separate thread."""
            try:
                parse_result['tree'] = ast.parse(script)
            except SyntaxError as e:
                parse_result['error'] = e
        
        def timeout_handler():
            """Handle timeout event."""
            timeout_occurred.set()
        
        # Start timer for timeout protection
        timer = threading.Timer(self.MAX_PARSE_TIME, timeout_handler)
        timer.start()
        
        # Run parsing in separate thread
        parse_thread = threading.Thread(target=parse_with_timeout)
        parse_thread.start()
        parse_thread.join(timeout=self.MAX_PARSE_TIME)
        
        # Cancel timer if parsing completed
        timer.cancel()
        
        # Check for timeout
        if timeout_occurred.is_set() or parse_thread.is_alive():
            raise TimeoutError("AST parsing timeout - possible malicious code")
        
        # Check for parsing error
        if parse_result['error']:
            raise SyntaxError(f"Invalid Python syntax: {parse_result['error']}")
        
        if not parse_result['tree']:
            raise SyntaxError("Failed to parse script")
        
        return parse_result['tree']
    
    class _SecurityValidator(ast.NodeVisitor):
        """Internal AST visitor for security validation."""
        
        def __init__(
            self,
            allowed_imports: Set[str],
            forbidden_calls: Set[str],
            forbidden_dunders: Set[str],
            max_depth: int,
            max_nodes: int
        ):
            self.allowed_imports = allowed_imports
            self.forbidden_calls = forbidden_calls
            self.forbidden_dunders = forbidden_dunders
            self.max_depth = max_depth
            self.max_nodes = max_nodes
            self.violations: List[str] = []
            self.depth = 0
            self.max_depth_reached = 0
            self.node_count = 0
            self.visited_nodes: Set[int] = set()
        
        def generic_visit(self, node):
            """Visit all nodes with security checks."""
            # Count nodes
            self.node_count += 1
            if self.node_count > self.max_nodes:
                self.violations.append(
                    f"AST node limit exceeded: {self.node_count} (max {self.max_nodes})"
                )
                return  # Stop traversing
            
            # Check depth
            self.depth += 1
            self.max_depth_reached = max(self.max_depth_reached, self.depth)
            
            if self.depth > self.max_depth:
                self.violations.append(
                    f"AST depth limit exceeded: {self.depth} (max {self.max_depth})"
                )
                return  # Stop traversing deeper
            
            # Check for recursive structures
            node_id = id(node)
            if node_id in self.visited_nodes:
                self.violations.append("Recursive AST structure detected - possible attack")
                return
            self.visited_nodes.add(node_id)
            
            super().generic_visit(node)
            self.depth -= 1
        
        def visit_Import(self, node):
            """Check import statements."""
            for alias in node.names:
                module = alias.name.split('.')[0]
                if module not in self.allowed_imports:
                    self.violations.append(f"Forbidden import: {module}")
            self.generic_visit(node)
        
        def visit_ImportFrom(self, node):
            """Check from-import statements."""
            if node.module:
                module = node.module.split('.')[0]
                if module not in self.allowed_imports:
                    self.violations.append(f"Forbidden import from: {module}")
            self.generic_visit(node)
        
        def visit_Name(self, node):
            """Check name access."""
            # Check for __builtins__ and dunder access
            if node.id == '__builtins__' or node.id in self.forbidden_calls:
                self.violations.append(f"Forbidden name access: {node.id}")
            elif node.id.startswith('__') and node.id.endswith('__'):
                if node.id in self.forbidden_dunders:
                    self.violations.append(f"Forbidden dunder access: {node.id}")
            self.generic_visit(node)
        
        def visit_Attribute(self, node):
            """Check attribute access."""
            if node.attr in self.forbidden_calls:
                self.violations.append(f"Forbidden attribute access: {node.attr}")
            elif node.attr in self.forbidden_dunders:
                self.violations.append(f"Forbidden dunder attribute: {node.attr}")
            elif node.attr in ['export', 'save', 'write', 'dump']:
                self.violations.append(f"File I/O not allowed: {node.attr}")
            self.generic_visit(node)
        
        def visit_Call(self, node):
            """Check function calls."""
            if isinstance(node.func, ast.Name):
                if node.func.id in self.forbidden_calls:
                    self.violations.append(f"Forbidden function call: {node.func.id}")
            elif isinstance(node.func, ast.Attribute):
                if node.func.attr in self.forbidden_calls:
                    self.violations.append(f"Forbidden method call: {node.func.attr}")
            self.generic_visit(node)
        
        def visit_Lambda(self, node):
            """Block lambda functions."""
            self.violations.append("Lambda functions are not allowed")
            self.generic_visit(node)


# Global validator instance
security_validator = ASTSecurityValidator()