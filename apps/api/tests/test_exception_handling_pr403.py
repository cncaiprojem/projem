#!/usr/bin/env python3
"""
Test script to verify exception handling improvements from PR #403.

This test validates that:
1. Specific exceptions are caught instead of broad Exception
2. Original stack traces are preserved
3. Unexpected exceptions are not masked
"""

import sys
import unittest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# Add the parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.freecad.a4_assembly import Assembly4Service
from app.services.freecad.standard_parts import StandardPartsService, InvalidSizeFormatError


class TestA4AssemblyExceptionHandling(unittest.TestCase):
    """Test exception handling improvements in a4_assembly.py"""
    
    def setUp(self):
        self.service = Assembly4Service()
        
    @patch('app.services.freecad.a4_assembly.FreeCAD')
    def test_file_import_ioerror_handling(self, mock_freecad):
        """Test that IOError is caught specifically when importing files"""
        # Mock FreeCAD.open to raise IOError
        mock_freecad.open.side_effect = IOError("Permission denied")
        
        # Create a mock document and component
        mock_doc = Mock()
        mock_component = Mock()
        mock_component.file_path = "/test/file.step"
        mock_component.id = "test_component"
        mock_component.initial_placement = None
        
        # Test that IOError is properly caught and converted to ValueError
        with self.assertRaises(ValueError) as ctx:
            # Need to patch validate_file_path to avoid security check
            with patch.object(self.service, 'validate_file_path') as mock_validate:
                mock_validate.return_value = Path("/test/file.step")
                # Mock the path exists check
                with patch('pathlib.Path.exists', return_value=True):
                    self.service._create_component(mock_doc, mock_component)
        
        self.assertIn("Could not access file", str(ctx.exception))
    
    @patch('app.services.freecad.a4_assembly.FreeCAD')
    def test_file_import_runtimeerror_handling(self, mock_freecad):
        """Test that RuntimeError is caught specifically when importing files"""
        # Mock FreeCAD.open to raise RuntimeError
        mock_freecad.open.side_effect = RuntimeError("Corrupt file format")
        
        # Create a mock document and component
        mock_doc = Mock()
        mock_component = Mock()
        mock_component.file_path = "/test/file.step"
        mock_component.id = "test_component"
        mock_component.initial_placement = None
        
        # Test that RuntimeError is properly caught and converted to ValueError
        with self.assertRaises(ValueError) as ctx:
            with patch.object(self.service, 'validate_file_path') as mock_validate:
                mock_validate.return_value = Path("/test/file.step")
                with patch('pathlib.Path.exists', return_value=True):
                    self.service._create_component(mock_doc, mock_component)
        
        self.assertIn("File processing error", str(ctx.exception))
    
    @patch('app.services.freecad.a4_assembly.FreeCAD')
    def test_unexpected_exception_propagates(self, mock_freecad):
        """Test that unexpected exceptions are not masked"""
        # Mock FreeCAD.open to raise an unexpected exception
        mock_freecad.open.side_effect = MemoryError("Out of memory")
        
        # Create a mock document and component
        mock_doc = Mock()
        mock_component = Mock()
        mock_component.file_path = "/test/file.step"
        mock_component.id = "test_component"
        mock_component.initial_placement = None
        
        # Test that MemoryError propagates unchanged
        with self.assertRaises(MemoryError):
            with patch.object(self.service, 'validate_file_path') as mock_validate:
                mock_validate.return_value = Path("/test/file.step")
                with patch('pathlib.Path.exists', return_value=True):
                    self.service._create_component(mock_doc, mock_component)


class TestStandardPartsExceptionHandling(unittest.TestCase):
    """Test exception handling improvements in standard_parts.py"""
    
    def setUp(self):
        self.service = StandardPartsService()
        
    def test_valueerror_handling_in_size_parsing(self):
        """Test that ValueError in size parsing is caught specifically"""
        # Mock a part definition
        mock_part_def = Mock()
        mock_part_def.category = Mock(value="FASTENERS")
        mock_part_def.get_size_parameters = Mock(side_effect=ValueError("Invalid number"))
        
        # Patch _get_standard_definition to return our mock
        with patch.object(self.service, '_get_standard_definition', return_value=mock_part_def):
            with self.assertRaises(InvalidSizeFormatError) as ctx:
                self.service.get_standard_part("ISO4014", "invalid_size")
            
            self.assertIn("Parsing error", str(ctx.exception))
            self.assertIn("Invalid number", str(ctx.exception))
    
    def test_indexerror_handling_in_size_parsing(self):
        """Test that IndexError in size parsing is caught specifically"""
        # Mock a part definition
        mock_part_def = Mock()
        mock_part_def.category = Mock(value="BEARINGS")
        mock_part_def.get_size_parameters = Mock(side_effect=IndexError("list index out of range"))
        
        # Patch _get_standard_definition to return our mock
        with patch.object(self.service, '_get_standard_definition', return_value=mock_part_def):
            with patch.object(self.service, '_parse_bearing_size', side_effect=IndexError("list index out of range")):
                with self.assertRaises(InvalidSizeFormatError) as ctx:
                    self.service.get_standard_part("ISO1234", "wrong_format")
                
                self.assertIn("Format error", str(ctx.exception))
    
    def test_unexpected_exception_propagates_in_parsing(self):
        """Test that unexpected exceptions in parsing are not masked"""
        # Mock a part definition
        mock_part_def = Mock()
        mock_part_def.category = Mock(value="FASTENERS")
        mock_part_def.get_size_parameters = Mock(side_effect=SystemError("System error"))
        
        # Patch _get_standard_definition to return our mock
        with patch.object(self.service, '_get_standard_definition', return_value=mock_part_def):
            # SystemError should propagate unchanged
            with self.assertRaises(SystemError):
                self.service.get_standard_part("ISO4014", "M10x30")


class TestScriptExecutionExceptionHandling(unittest.TestCase):
    """Test exception handling in script execution"""
    
    def setUp(self):
        self.service = Assembly4Service()
    
    def test_nameerror_in_script_execution(self):
        """Test that NameError in script execution is caught specifically"""
        script = """
# Simple script with undefined variable
result = undefined_variable + 1
"""
        
        with self.assertRaises(ValueError) as ctx:
            self.service.execute_parametric_script(Mock(), script, "test_comp")
        
        self.assertIn("undefined reference", str(ctx.exception))
    
    def test_typeerror_in_script_execution(self):
        """Test that TypeError in script execution is caught specifically"""
        script = """
# Simple script with type error
result = "string" + 5  # Can't add string and int
"""
        
        with self.assertRaises(ValueError) as ctx:
            self.service.execute_parametric_script(Mock(), script, "test_comp")
        
        self.assertIn("invalid operation", str(ctx.exception))


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)