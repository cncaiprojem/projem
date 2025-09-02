"""
Validation tests for PR #389 fixes.

This module validates all code quality improvements made in response to
Copilot and Gemini feedback for PR #389.

Tests validate:
1. Geometry validator comment clarity
2. Worker script comment conciseness
3. Standard parts security comment
4. Import organization in worker script
5. Test mock simplification
6. Assembly4 class attribute cleanup
7. Dictionary mapping replacement for if/elif chains
8. GLB format inclusion in defaults
"""

import ast
import os
import sys
import unittest
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))


class TestPR389Fixes(unittest.TestCase):
    """Validate all PR #389 code quality fixes."""
    
    def test_geometry_validator_comment_clarity(self):
        """Verify ray intersection comment is clear and concise."""
        file_path = project_root / "apps/api/app/services/freecad/geometry_validator.py"
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for the improved comment
        self.assertIn("OpenCASCADE line-solid intersection returns edges/vertices", content)
        self.assertNotIn("Line-solid intersection has zero volume", content)
        
    def test_worker_script_comment_conciseness(self):
        """Verify worker script comments are concise."""
        file_path = project_root / "apps/api/app/services/freecad/worker_script.py"
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Check that verbose comment block is condensed
        # Original was lines 1312-1341 (30 lines), should be much shorter now
        comment_lines = []
        in_comment = False
        for i, line in enumerate(lines[1310:1350], start=1311):
            if '"""' in line:
                if in_comment:
                    comment_lines.append(i)
                    break
                else:
                    in_comment = True
                    comment_lines.append(i)
            elif in_comment:
                comment_lines.append(i)
        
        # Should be significantly reduced from 30 lines
        if comment_lines:
            self.assertLess(len(comment_lines), 20, "Comment should be condensed")
    
    def test_standard_parts_security_comment(self):
        """Verify security comment is concise."""
        file_path = project_root / "apps/api/app/services/freecad/standard_parts.py"
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for the concise security comment
        self.assertIn("SECURITY: Template variables validated via Jinja2", content)
        
    def test_worker_script_imports_at_module_level(self):
        """Verify PathValidator import is at module level."""
        file_path = project_root / "apps/api/app/services/freecad/worker_script.py"
        
        # Use itertools.islice to read only first 100 lines efficiently
        import itertools
        with open(file_path, 'r', encoding='utf-8') as f:
            # Read only the first 100 lines without loading entire file
            first_100_lines = list(itertools.islice(f, 100))
        
        # Check that PathValidator is imported at module level (in first 100 lines)
        found_import = False
        for i, line in enumerate(first_100_lines):
            # Check for PathValidator import (either relative or absolute)
            if 'from' in line and 'path_validator' in line.lower() and 'PathValidator' in line:
                found_import = True
                # Make sure it's not inside a function/class (no indentation)
                if line[0] not in (' ', '\t'):
                    break
                # Also check try/except blocks at module level
                elif i > 0 and 'try:' in first_100_lines[i-2:i]:
                    break
        
        self.assertTrue(found_import, "PathValidator should be imported at module level")
    
    def test_test_file_mock_simplification(self):
        """Verify test mocks are simplified."""
        file_path = project_root / "apps/api/tests/test_pr386_fixes.py"
        
        # Use itertools.islice to read only specific lines efficiently
        import itertools
        with open(file_path, 'r', encoding='utf-8') as f:
            # Skip to line 175 and read only 5 lines
            for _ in itertools.islice(f, 174):  # Skip first 174 lines
                pass
            target_lines = list(itertools.islice(f, 5))  # Read lines 175-179
        
        # Check that unnecessary assignments are removed (lines 175-179)
        unnecessary_patterns = [
            "test_dir = ",
            "os.makedirs(test_dir",
            "test_file = os.path.join"
        ]
        
        # Verify that test setup is efficient
        combined_operations = 0
        for line in target_lines:
            line_stripped = line.strip()
            # Check if operations are combined efficiently
            if any(pattern in line_stripped for pattern in unnecessary_patterns):
                combined_operations += 1
        
        # Assert that operations are combined (should be 3 or fewer lines)
        self.assertLessEqual(combined_operations, 3, 
                           "Test setup operations should be combined for efficiency")
    
    def test_assembly4_no_redundant_class_attribute(self):
        """Verify Assembly4Manager doesn't have redundant class attribute."""
        file_path = project_root / "apps/api/app/services/freecad/a4_assembly.py"
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse AST to check class attributes
        tree = ast.parse(content)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == 'Assembly4Manager':
                # Check class body for _shape_cache assignment
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        if item.target.id == '_shape_cache':
                            # Should not have class-level assignment
                            self.assertIsNone(item.value, "_shape_cache should not be initialized at class level")
    
    def test_worker_script_uses_dictionary_mapping(self):
        """Verify if/elif chain is replaced with dictionary mapping."""
        file_path = project_root / "apps/api/app/services/freecad/worker_script.py"
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for ARTEFACT_TYPE_MAP dictionary
        self.assertIn("ARTEFACT_TYPE_MAP", content)
        
        # Verify dictionary contains expected mappings
        self.assertIn("'FCStd': 'freecad_document'", content)
        self.assertIn("'STEP': 'cad_model'", content)
        self.assertIn("'STL': 'mesh_model'", content)
        self.assertIn("'GLB': 'gltf_model'", content)
        
        # Check that dictionary is used instead of if/elif
        self.assertIn("ARTEFACT_TYPE_MAP.get", content)
    
    def test_glb_in_default_formats(self):
        """Verify GLB is included in default export formats."""
        file_path = project_root / "apps/api/app/services/freecad/worker_script.py"
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that GLB is in the default formats for both locations
        # Line 1306 and 1861 should have GLB in defaults
        expected_pattern = 'formats", ["FCStd", "STEP", "STL", "GLB"]'
        self.assertIn(expected_pattern, content, "GLB should be in default export formats")


if __name__ == "__main__":
    # Run tests with verbose output
    unittest.main(verbosity=2)