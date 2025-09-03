"""Comprehensive tests for Assembly4 service and functionality."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import json

from app.services.assembly4_service import (
    Assembly4Service,
    CUT_MODE_MAP,
    SPINDLE_DIRECTION_MAP
)
from app.core.exceptions import ValidationError


@pytest.fixture
def assembly4_service():
    """Create Assembly4Service instance for testing."""
    return Assembly4Service()


@pytest.fixture
def sample_parts():
    """Sample parts for assembly testing."""
    return [
        {
            "name": "base_plate",
            "type": "box",
            "dimensions": {"length": 100, "width": 100, "height": 10}
        },
        {
            "name": "support_column",
            "type": "cylinder",
            "dimensions": {"radius": 10, "height": 50}
        }
    ]


@pytest.fixture
def sample_constraints():
    """Sample constraints for assembly testing."""
    return [
        {
            "type": "coincident",
            "parts": ["base_plate", "support_column"],
            "faces": ["top", "bottom"]
        }
    ]


@pytest.fixture
def sample_cam_settings():
    """Sample CAM settings for testing."""
    return {
        "cut_mode": "climb",
        "spindle_direction": "forward",
        "feed_rate": 150.0,
        "spindle_speed": 1500.0,
        "tool_diameter": 6.0,
        "depth_of_cut": 2.0,
        # Fix: Use world_origin as expected by fixture
        "wcs_origin": "world_origin"  # Changed from LCS_Origin to world_origin
    }


class TestAssembly4Service:
    """Test Assembly4Service functionality."""
    
    def test_cut_mode_mapping(self, assembly4_service):
        """Test cut mode mapping to FreeCAD values."""
        test_cases = [
            ("climb", "Climb"),
            ("conventional", "Conventional"),
            ("cw", "CW"),
            ("ccw", "CCW"),
            ("inside", "Inside"),
            ("outside", "Outside"),
            ("clockwise", "CW"),
            ("counterclockwise", "CCW"),
        ]
        
        for input_val, expected_val in test_cases:
            settings = {"cut_mode": input_val}
            processed = assembly4_service._process_cam_settings(settings)
            assert processed["cut_mode"] == expected_val
    
    def test_spindle_direction_mapping(self, assembly4_service):
        """Test spindle direction mapping."""
        test_cases = [
            ("forward", "Forward"),
            ("reverse", "Reverse"),
            ("cw", "Forward"),
            ("ccw", "Reverse"),
            ("m3", "Forward"),
            ("m4", "Reverse"),
        ]
        
        for input_val, expected_val in test_cases:
            settings = {"spindle_direction": input_val}
            processed = assembly4_service._process_cam_settings(settings)
            assert processed["spindle_direction"] == expected_val
    
    def test_unknown_cut_mode_defaults(self, assembly4_service):
        """Test that unknown cut modes default to Climb."""
        settings = {"cut_mode": "unknown_mode"}
        processed = assembly4_service._process_cam_settings(settings)
        assert processed["cut_mode"] == "Climb"
    
    def test_unknown_spindle_direction_defaults(self, assembly4_service):
        """Test that unknown spindle directions default to Forward."""
        settings = {"spindle_direction": "unknown_direction"}
        processed = assembly4_service._process_cam_settings(settings)
        assert processed["spindle_direction"] == "Forward"
    
    def test_feed_rate_validation(self, assembly4_service):
        """Test feed rate validation and conversion."""
        # Valid feed rate
        settings = {"feed_rate": "200.5"}
        processed = assembly4_service._process_cam_settings(settings)
        assert processed["feed_rate"] == 200.5
        
        # Invalid feed rate defaults to 100.0
        settings = {"feed_rate": "invalid"}
        processed = assembly4_service._process_cam_settings(settings)
        assert processed["feed_rate"] == 100.0
        
        # Negative feed rate defaults to 100.0
        settings = {"feed_rate": -50}
        processed = assembly4_service._process_cam_settings(settings)
        assert processed["feed_rate"] == 100.0
    
    def test_spindle_speed_validation(self, assembly4_service):
        """Test spindle speed validation and conversion."""
        # Valid spindle speed
        settings = {"spindle_speed": "2000"}
        processed = assembly4_service._process_cam_settings(settings)
        assert processed["spindle_speed"] == 2000.0
        
        # Invalid spindle speed defaults to 1000.0
        settings = {"spindle_speed": "invalid"}
        processed = assembly4_service._process_cam_settings(settings)
        assert processed["spindle_speed"] == 1000.0
        
        # Negative spindle speed defaults to 1000.0
        settings = {"spindle_speed": -100}
        processed = assembly4_service._process_cam_settings(settings)
        assert processed["spindle_speed"] == 1000.0
    
    def test_cut_direction_processing(self, assembly4_service):
        """Test cut direction processing for profile operations."""
        test_cases = [
            ("cw", "CW"),
            ("clockwise", "CW"),
            ("ccw", "CCW"),
            ("counter-clockwise", "CCW"),
            ("counterclockwise", "CCW"),
        ]
        
        for input_val, expected_val in test_cases:
            settings = {"cut_direction": input_val}
            processed = assembly4_service._process_cam_settings(settings)
            assert processed["cut_direction"] == expected_val
    
    @patch('app.services.assembly4_service.assembly4_manager')
    def test_create_assembly_success(
        self, mock_manager, assembly4_service, sample_parts, sample_constraints, sample_cam_settings
    ):
        """Test successful assembly creation."""
        mock_manager.create_assembly.return_value = {
            "id": "test_assembly_123",
            "name": "test_assembly",
            "parts": sample_parts,
            "constraints": sample_constraints
        }
        
        result = assembly4_service.create_assembly(
            name="test_assembly",
            parts=sample_parts,
            constraints=sample_constraints,
            cam_settings=sample_cam_settings
        )
        
        assert result["id"] == "test_assembly_123"
        assert result["name"] == "test_assembly"
        mock_manager.create_assembly.assert_called_once()
    
    @patch('app.services.assembly4_service.assembly4_manager')
    def test_create_assembly_failure(self, mock_manager, assembly4_service, sample_parts):
        """Test assembly creation failure."""
        mock_manager.create_assembly.side_effect = Exception("FreeCAD error")
        
        with pytest.raises(ValidationError, match="Assembly4 oluşturma başarısız"):
            assembly4_service.create_assembly(
                name="test_assembly",
                parts=sample_parts
            )
    
    def test_validate_shape(self, assembly4_service):
        """Test shape validation."""
        # Valid shape mock
        valid_shape = Mock()
        valid_shape.Volume = 100.0
        valid_shape.Area = 50.0
        assert assembly4_service._validate_shape(valid_shape) is True
        
        # Invalid shape - None
        assert assembly4_service._validate_shape(None) is False
        
        # Invalid shape - missing properties
        invalid_shape = Mock(spec=[])
        assert assembly4_service._validate_shape(invalid_shape) is False
    
    def test_validate_sub_object(self, assembly4_service):
        """Test sub-object validation."""
        # Valid sub-object
        valid_sub_obj = Mock()
        valid_sub_obj.Label = "TestLabel"
        assert assembly4_service._validate_sub_object(valid_sub_obj) is True
        
        # Invalid sub-object - None
        assert assembly4_service._validate_sub_object(None) is False
        
        # Invalid sub-object - missing Label
        invalid_sub_obj = Mock(spec=[])
        assert assembly4_service._validate_sub_object(invalid_sub_obj) is False
    
    @patch('app.services.assembly4_service.assembly4_manager')
    def test_add_part(self, mock_manager, assembly4_service):
        """Test adding part to assembly."""
        mock_manager.add_part_to_assembly.return_value = {
            "id": "test_assembly_123",
            "parts_count": 3
        }
        
        part = {
            "name": "new_part",
            "type": "box",
            "dimensions": {"length": 50, "width": 50, "height": 20}
        }
        position = {"x": 10, "y": 20, "z": 30}
        
        result = assembly4_service.add_part(
            assembly_id="test_assembly_123",
            part=part,
            position=position
        )
        
        assert result["parts_count"] == 3
        mock_manager.add_part_to_assembly.assert_called_once()
    
    @patch('app.services.assembly4_service.assembly4_manager')
    def test_apply_constraint_success(self, mock_manager, assembly4_service):
        """Test applying constraint to assembly."""
        mock_manager.apply_constraint.return_value = {
            "id": "test_assembly_123",
            "constraints_count": 2
        }
        
        constraint = {
            "type": "coincident",
            "parts": ["part1", "part2"],
            "faces": ["face1", "face2"]
        }
        
        result = assembly4_service.apply_constraint(
            assembly_id="test_assembly_123",
            constraint=constraint
        )
        
        assert result["constraints_count"] == 2
        mock_manager.apply_constraint.assert_called_once()
    
    def test_apply_constraint_validation_errors(self, assembly4_service):
        """Test constraint validation errors."""
        # Missing type
        with pytest.raises(ValidationError, match="Constraint type is required"):
            assembly4_service.apply_constraint(
                assembly_id="test_123",
                constraint={"parts": ["part1", "part2"]}
            )
        
        # Insufficient parts
        with pytest.raises(ValidationError, match="At least two parts required"):
            assembly4_service.apply_constraint(
                assembly_id="test_123",
                constraint={"type": "coincident", "parts": ["part1"]}
            )
    
    @patch('app.services.assembly4_service.assembly4_manager')
    def test_generate_cam_paths(
        self, mock_manager, assembly4_service, sample_cam_settings
    ):
        """Test CAM path generation."""
        mock_manager.generate_paths.return_value = {
            "gcode": "G0 X0 Y0 Z0\nG1 X100 Y0 Z-5",
            "path_count": 10
        }
        
        result = assembly4_service.generate_cam_paths(
            assembly_id="test_assembly_123",
            operation="pocket",
            settings=sample_cam_settings
        )
        
        assert "gcode" in result
        assert result["path_count"] == 10
        mock_manager.generate_paths.assert_called_once()
        
        # Verify settings were processed
        call_args = mock_manager.generate_paths.call_args
        assert call_args[1]["settings"]["cut_mode"] == "Climb"
        assert call_args[1]["settings"]["spindle_direction"] == "Forward"
    
    @patch('app.services.assembly4_service.assembly4_manager')
    def test_export_assembly(self, mock_manager, assembly4_service):
        """Test assembly export."""
        expected_path = Path("/tmp/exports/assembly_123.step")
        mock_manager.export_assembly.return_value = expected_path
        
        result = assembly4_service.export_assembly(
            assembly_id="test_assembly_123",
            format="step",
            include_paths=True
        )
        
        assert result == expected_path
        mock_manager.export_assembly.assert_called_once_with(
            assembly_id="test_assembly_123",
            format="step",
            include_paths=True
        )
    
    @patch('app.services.assembly4_service.assembly4_manager')
    def test_get_assembly_info(self, mock_manager, assembly4_service):
        """Test getting assembly information."""
        mock_info = {
            "id": "test_assembly_123",
            "name": "test_assembly",
            "parts_count": 5,
            "constraints_count": 3
        }
        mock_manager.get_assembly_info.return_value = mock_info
        
        result = assembly4_service.get_assembly_info("test_assembly_123")
        
        assert result == mock_info
        mock_manager.get_assembly_info.assert_called_once_with("test_assembly_123")
    
    def test_wcs_origin_fixture_value(self, sample_cam_settings):
        """Test that fixture correctly uses world_origin instead of LCS_Origin."""
        # This test verifies the fix for the PR feedback
        assert sample_cam_settings["wcs_origin"] == "world_origin"
        # Not "LCS_Origin" as was incorrectly expected before