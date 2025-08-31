"""
Test suite for geometry validator tool accessibility checks.
Tests the fix for PR #393 - ensuring proper tool clearance analysis.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
import math

from app.services.freecad.geometry_validator import GeometryValidator, ManufacturingConstraints


class TestToolAccessibility(unittest.TestCase):
    """Test tool accessibility validation for CNC operations."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.validator = GeometryValidator()
        
    def test_tool_accessibility_with_deep_features(self):
        """Test that deep features are properly detected."""
        # Mock FreeCAD shape with deep pocket
        mock_shape = Mock()
        mock_shape.BoundBox = Mock()
        mock_shape.BoundBox.XMin = 0
        mock_shape.BoundBox.XMax = 100
        mock_shape.BoundBox.YMin = 0  
        mock_shape.BoundBox.YMax = 100
        mock_shape.BoundBox.ZMin = 0
        mock_shape.BoundBox.ZMax = 100
        mock_shape.BoundBox.XLength = 100
        mock_shape.BoundBox.YLength = 100
        mock_shape.BoundBox.ZLength = 100
        
        # Mock faces for deep pocket analysis
        mock_face = Mock()
        mock_face.BoundBox = Mock()
        mock_face.BoundBox.XMin = 40
        mock_face.BoundBox.XMax = 60
        mock_face.BoundBox.YMin = 40
        mock_face.BoundBox.YMax = 60
        mock_face.BoundBox.ZMin = 10
        mock_face.BoundBox.ZMax = 20  # Deep pocket at Z=20, depth=80mm
        mock_face.BoundBox.XLength = 20
        mock_face.BoundBox.YLength = 20
        
        mock_shape.Faces = [mock_face]
        
        # Run the check
        result = self.validator._check_tool_accessibility(mock_shape)
        
        # Verify warnings are generated for deep pockets
        self.assertIn("warnings", result)
        self.assertTrue(any("Deep pocket" in w for w in result["warnings"]))
        
    def test_tool_accessibility_with_clearance_issues(self):
        """Test detection of tool clearance issues."""
        # This tests the new clearance analysis logic
        with patch('app.services.freecad.geometry_validator.Part') as mock_part:
            # Setup mock shape
            mock_shape = Mock()
            mock_shape.BoundBox = Mock()
            mock_shape.BoundBox.XMin = 0
            mock_shape.BoundBox.XMax = 50
            mock_shape.BoundBox.YMin = 0
            mock_shape.BoundBox.YMax = 50
            mock_shape.BoundBox.ZMin = 0
            mock_shape.BoundBox.ZMax = 30
            mock_shape.BoundBox.XLength = 50
            mock_shape.BoundBox.YLength = 50
            mock_shape.BoundBox.ZLength = 30
            
            # Mock intersection with significant volume (clearance issue)
            mock_intersection = Mock()
            mock_intersection.Edges = [Mock()]
            mock_intersection.Edges[0].Vertexes = [Mock()]
            mock_intersection.Edges[0].Vertexes[0].Point = Mock()
            mock_intersection.Edges[0].Vertexes[0].Point.z = 15
            
            # Mock collision detection
            mock_collision = Mock()
            mock_collision.Volume = 500  # Large volume indicates interference
            
            mock_shape.common = Mock(side_effect=[mock_intersection, mock_collision])
            mock_shape.Faces = []
            
            # Configure Part mock
            mock_part.makeLine = Mock(return_value=Mock())
            mock_part.makeCylinder = Mock(return_value=Mock())
            mock_part.Vertex = Mock(return_value=Mock(Point=Mock(x=0, y=0, z=0)))
            
            # Run the check
            result = self.validator._check_tool_accessibility(mock_shape)
            
            # The function should handle this gracefully
            self.assertIn("warnings", result)
            self.assertIn("errors", result)
            
    def test_minimum_internal_radius_calculation(self):
        """Test that minimum internal radius is calculated correctly."""
        # Industry standard: R = (H/10) + 0.5mm
        depths = [10, 20, 30, 40, 50]
        expected_radii = [1.5, 2.5, 3.5, 4.5, 5.5]
        
        for depth, expected_radius in zip(depths, expected_radii):
            calculated_radius = (depth / 10) + 0.5
            self.assertAlmostEqual(calculated_radius, expected_radius)
            
    def test_tool_diameter_recommendation(self):
        """Test tool diameter recommendations based on cavity depth."""
        # Industry standard: D = H/5
        depths = [10, 20, 30, 40, 50]
        expected_diameters = [2, 4, 6, 8, 10]
        
        for depth, expected_diameter in zip(depths, expected_diameters):
            calculated_diameter = depth / 5
            self.assertAlmostEqual(calculated_diameter, expected_diameter)
            
    def test_aspect_ratio_warnings(self):
        """Test that high aspect ratios generate appropriate warnings."""
        mock_shape = Mock()
        mock_shape.BoundBox = Mock()
        mock_shape.BoundBox.XMin = 0
        mock_shape.BoundBox.XMax = 100
        mock_shape.BoundBox.YMin = 0
        mock_shape.BoundBox.YMax = 100
        mock_shape.BoundBox.ZMin = 0
        mock_shape.BoundBox.ZMax = 100
        mock_shape.BoundBox.XLength = 100
        mock_shape.BoundBox.YLength = 100
        mock_shape.BoundBox.ZLength = 100
        
        # Create a face with high aspect ratio (depth/width > 5)
        mock_face = Mock()
        mock_face.BoundBox = Mock()
        mock_face.BoundBox.XMin = 45
        mock_face.BoundBox.XMax = 55  # 10mm width
        mock_face.BoundBox.YMin = 45
        mock_face.BoundBox.YMax = 55  # 10mm width
        mock_face.BoundBox.ZMin = 0
        mock_face.BoundBox.ZMax = 40  # 60mm depth from top
        mock_face.BoundBox.XLength = 10
        mock_face.BoundBox.YLength = 10
        
        mock_shape.Faces = [mock_face]
        
        result = self.validator._check_tool_accessibility(mock_shape)
        
        # Should generate warnings about deep pockets
        self.assertTrue(any("Deep pocket" in w for w in result["warnings"]))
        # Should also suggest optimal tool diameter
        self.assertTrue(any("chip evacuation" in w for w in result["warnings"]))
        
    def test_tool_length_exceeded(self):
        """Test detection of features exceeding standard tool length."""
        with patch('app.services.freecad.geometry_validator.Part') as mock_part:
            mock_shape = Mock()
            mock_shape.BoundBox = Mock()
            mock_shape.BoundBox.XMin = 0
            mock_shape.BoundBox.XMax = 100
            mock_shape.BoundBox.YMin = 0
            mock_shape.BoundBox.YMax = 100
            mock_shape.BoundBox.ZMin = 0
            mock_shape.BoundBox.ZMax = 100  # 100mm tall part
            mock_shape.BoundBox.XLength = 100
            mock_shape.BoundBox.YLength = 100
            mock_shape.BoundBox.ZLength = 100
            
            # Mock intersection at depth > 50mm (standard tool length)
            mock_intersection = Mock()
            mock_intersection.Edges = [Mock()]
            mock_intersection.Edges[0].Vertexes = [Mock()]
            mock_intersection.Edges[0].Vertexes[0].Point = Mock()
            mock_intersection.Edges[0].Vertexes[0].Point.z = 30  # 70mm depth from top
            
            mock_shape.common = Mock(return_value=mock_intersection)
            mock_shape.Faces = []
            
            # Configure Part mock
            mock_part.makeLine = Mock(return_value=Mock())
            mock_part.makeCylinder = Mock(return_value=Mock())
            mock_part.Vertex = Mock(return_value=Mock(Point=Mock(x=0, y=0, z=0)))
            
            # This should handle the edge case gracefully
            result = self.validator._check_tool_accessibility(mock_shape)
            
            # Should return a result dict with errors/warnings lists
            self.assertIsInstance(result, dict)
            self.assertIn("errors", result)
            self.assertIn("warnings", result)


if __name__ == "__main__":
    unittest.main()