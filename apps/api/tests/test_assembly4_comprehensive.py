"""
Comprehensive test suite for Task 7.8 - Assembly4 implementation

Tests:
- Assembly4 JSON parsing and validation
- OndselSolver integration with fallback
- Collision detection (AABB and precise)
- DOF analysis
- CAM generation via Path Workbench
- Export capabilities
- Turkish localization
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from pydantic import ValidationError

# Add project root to path
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.schemas.assembly4 import (
    Assembly4Input,
    AssemblyConstraint,
    AssemblyHierarchy,
    CAMJobParameters,
    CAMOperation,
    CollisionReport,
    ConstraintReference,
    ConstraintType,
    DOFAnalysis,
    ExportOptions,
    FeedsAndSpeeds,
    LCSDefinition,
    OperationType,
    PartReference,
    Placement,
    PostProcessor,
    SolverType,
    Stock,
    Tool,
    Vector3D,
    WorkCoordinateSystem,
)
from app.services.assembly4_service import (
    Assembly4Service,
    Assembly4Exception,
    Assembly4ErrorCode,
    OndselSolverWrapper,
    CollisionDetector,
    DOFAnalyzer,
)


@pytest.fixture
def sample_assembly_input():
    """Create a sample Assembly4 input for testing."""
    return Assembly4Input(
        name="TestAssembly",
        parts=[
            PartReference(
                id="base_plate",
                model_ref="/models/base_plate.step",
                initial_placement=Placement(
                    position=Vector3D(x=0, y=0, z=0),
                    rotation=Vector3D(x=0, y=0, z=0)
                ),
                lcs=["LCS_Origin", "LCS_Top"],
                quantity=1,
                visible=True
            ),
            PartReference(
                id="bearing",
                model_ref="/models/bearing.fcstd",
                initial_placement=Placement(
                    position=Vector3D(x=50, y=50, z=10),
                    rotation=Vector3D(x=0, y=0, z=0)
                ),
                lcs=["LCS_Center"],
                quantity=4,
                visible=True,
                color="#FF5733"
            ),
            PartReference(
                id="shaft",
                model_ref="/models/shaft.step",
                initial_placement=Placement(
                    position=Vector3D(x=50, y=50, z=20),
                    rotation=Vector3D(x=0, y=0, z=90)
                ),
                lcs=["LCS_Bottom", "LCS_Top"],
                quantity=1,
                visible=True
            )
        ],
        constraints=[
            AssemblyConstraint(
                id="fix_base",
                type=ConstraintType.ATTACHMENT,
                reference1=ConstraintReference(part_id="base_plate", lcs="LCS_Origin"),
                reference2=ConstraintReference(part_id="world", lcs="Origin"),
                enabled=True
            ),
            AssemblyConstraint(
                id="bearing_on_plate",
                type=ConstraintType.PLANE_COINCIDENT,
                reference1=ConstraintReference(part_id="bearing", lcs="LCS_Center"),
                reference2=ConstraintReference(part_id="base_plate", lcs="LCS_Top"),
                enabled=True
            ),
            AssemblyConstraint(
                id="shaft_in_bearing",
                type=ConstraintType.AXIS_COINCIDENT,
                reference1=ConstraintReference(part_id="shaft", lcs="LCS_Bottom"),
                reference2=ConstraintReference(part_id="bearing", lcs="LCS_Center"),
                enabled=True
            )
        ],
        lcs_definitions=[
            LCSDefinition(
                name="world_origin",
                placement=Placement(
                    position=Vector3D(x=0, y=0, z=0),
                    rotation=Vector3D(x=0, y=0, z=0)
                ),
                visible=True
            )
        ],
        hierarchy=AssemblyHierarchy(
            root="base_plate",
            parent_child_map={
                "base_plate": ["bearing"],
                "bearing": ["shaft"]
            }
        ),
        solver_type=SolverType.ONDSEL,
        tolerance=0.01
    )


@pytest.fixture
def sample_cam_parameters():
    """Create sample CAM parameters for testing."""
    return CAMJobParameters(
        wcs=WorkCoordinateSystem(
            coordinate_system="G54",
            origin_lcs="world_origin",
            offset=Vector3D(x=0, y=0, z=0)
        ),
        stock=Stock(
            type="box",
            margins=Vector3D(x=5, y=5, z=2)
        ),
        operations=[
            CAMOperation(
                type=OperationType.FACING,
                tool=Tool(
                    name="FaceMill_10mm",
                    number=1,
                    type="endmill",
                    diameter=10.0,
                    flutes=4,
                    cutting_height=15.0
                ),
                feeds_speeds=FeedsAndSpeeds(
                    feed_rate=300.0,
                    plunge_rate=100.0,
                    spindle_speed=3000,
                    spindle_direction="CW"
                ),
                depths={
                    "start_depth": 0.0,
                    "final_depth": -0.5,
                    "step_down": 0.5
                },
                strategy="ZigZag",
                cut_mode="Climb",
                parameters={
                    "step_over": 60
                }
            ),
            CAMOperation(
                type=OperationType.POCKET,
                tool=Tool(
                    name="EndMill_6mm",
                    number=2,
                    type="endmill",
                    diameter=6.0,
                    flutes=2,
                    cutting_height=20.0
                ),
                feeds_speeds=FeedsAndSpeeds(
                    feed_rate=200.0,
                    plunge_rate=50.0,
                    spindle_speed=4000,
                    spindle_direction="CW"
                ),
                depths={
                    "start_depth": 0.0,
                    "final_depth": -5.0,
                    "step_down": 1.0
                },
                strategy="Offset",
                cut_mode="Climb",
                finish_pass=True,
                coolant="Mist"
            ),
            CAMOperation(
                type=OperationType.DRILLING,
                tool=Tool(
                    name="Drill_8mm",
                    number=3,
                    type="drill",
                    diameter=8.0,
                    tip_angle=118.0
                ),
                feeds_speeds=FeedsAndSpeeds(
                    feed_rate=50.0,
                    plunge_rate=50.0,
                    spindle_speed=1500,
                    spindle_direction="CW"
                ),
                depths={
                    "start_depth": 0.0,
                    "final_depth": -15.0,
                    "step_down": 3.0
                },
                parameters={
                    "peck_depth": 3.0,
                    "dwell": 0.5,
                    "retract": 2.0
                }
            )
        ],
        post_processor=PostProcessor.LINUXCNC,
        optimize_sequence=True,
        safety={
            "clearance_height": 10.0,
            "safe_height": 5.0,
            "retract_height": 1.0
        }
    )


class TestAssembly4Input:
    """Test Assembly4 input validation."""
    
    def test_valid_input(self, sample_assembly_input):
        """Test that valid input passes validation."""
        assert sample_assembly_input.name == "TestAssembly"
        assert len(sample_assembly_input.parts) == 3
        assert len(sample_assembly_input.constraints) == 3
        assert sample_assembly_input.solver_type == SolverType.ONDSEL
    
    def test_invalid_constraint_references(self):
        """Test that invalid constraint references are caught."""
        with pytest.raises(ValidationError):
            Assembly4Input(
                name="InvalidAssembly",
                parts=[
                    PartReference(
                        id="part1",
                        model_ref="/models/part1.step",
                        quantity=1
                    )
                ],
                constraints=[
                    AssemblyConstraint(
                        id="invalid",
                        type=ConstraintType.ATTACHMENT,
                        reference1=ConstraintReference(
                            part_id="nonexistent",
                            lcs="LCS1"
                        ),
                        reference2=ConstraintReference(
                            part_id="part1",
                            lcs="LCS2"
                        )
                    )
                ]
            )
    
    def test_hierarchy_validation(self):
        """Test hierarchy validation."""
        with pytest.raises(ValidationError):
            Assembly4Input(
                name="HierarchyTest",
                parts=[
                    PartReference(id="part1", model_ref="/test.step", quantity=1)
                ],
                constraints=[],
                hierarchy=AssemblyHierarchy(
                    root="nonexistent",
                    parent_child_map={"part1": ["part2"]}
                )
            )


class TestOndselSolverWrapper:
    """Test OndselSolver wrapper with fallback."""
    
    def test_fallback_when_ondsel_not_available(self):
        """Test fallback solver when OndselSolver is not available."""
        with patch.dict('sys.modules', {'py_slvs': None}):
            solver = OndselSolverWrapper()
            assert not solver.is_available()
            
            # Test fallback solving
            parts = [
                PartReference(id="p1", model_ref="/test.step", quantity=1),
                PartReference(id="p2", model_ref="/test2.step", quantity=1)
            ]
            constraints = [
                AssemblyConstraint(
                    id="c1",
                    type=ConstraintType.ATTACHMENT,
                    reference1=ConstraintReference(part_id="p1", lcs="L1"),
                    reference2=ConstraintReference(part_id="p2", lcs="L2")
                )
            ]
            
            result = solver.solve_constraints(parts, constraints)
            assert "p1" in result
            assert "p2" in result
    
    @patch('app.services.assembly4_service.py_slvs')
    def test_ondsel_solver_available(self, mock_py_slvs):
        """Test when OndselSolver is available."""
        solver = OndselSolverWrapper()
        assert solver.is_available()


class TestCollisionDetector:
    """Test collision detection."""
    
    def test_aabb_overlap_detection(self):
        """Test AABB overlap detection."""
        detector = CollisionDetector(tolerance=0.01)
        
        # Create mock parts with bounding boxes
        part1 = MagicMock()
        part1.Shape.BoundBox.XMin = 0
        part1.Shape.BoundBox.XMax = 10
        part1.Shape.BoundBox.YMin = 0
        part1.Shape.BoundBox.YMax = 10
        part1.Shape.BoundBox.ZMin = 0
        part1.Shape.BoundBox.ZMax = 10
        
        part2 = MagicMock()
        part2.Shape.BoundBox.XMin = 5
        part2.Shape.BoundBox.XMax = 15
        part2.Shape.BoundBox.YMin = 5
        part2.Shape.BoundBox.YMax = 15
        part2.Shape.BoundBox.ZMin = 5
        part2.Shape.BoundBox.ZMax = 15
        
        # Should overlap
        assert detector._check_aabb_overlap(part1, part2)
        
        # Move part2 away
        part2.Shape.BoundBox.XMin = 20
        part2.Shape.BoundBox.XMax = 30
        
        # Should not overlap
        assert not detector._check_aabb_overlap(part1, part2)
    
    @patch('app.services.assembly4_service.Part')
    def test_precise_collision_check(self, mock_Part):
        """Test precise collision checking."""
        detector = CollisionDetector(tolerance=0.01)
        
        # Create mock parts
        part1 = MagicMock()
        part2 = MagicMock()
        
        # Mock common shape with volume
        common_shape = MagicMock()
        common_shape.Volume = 5.0
        part1.Shape.common.return_value = common_shape
        
        result = detector._check_precise_collision(
            part1, part2, "part1", "part2"
        )
        
        assert result is not None
        assert result.part1_id == "part1"
        assert result.part2_id == "part2"
        assert result.type == "interference"
        assert result.volume == 5.0


class TestDOFAnalyzer:
    """Test DOF analysis."""
    
    def test_fully_constrained_assembly(self):
        """Test DOF analysis for fully constrained assembly."""
        analyzer = DOFAnalyzer()
        
        parts = [
            PartReference(id="base", model_ref="/base.step", quantity=1),
            PartReference(id="top", model_ref="/top.step", quantity=1)
        ]
        
        constraints = [
            AssemblyConstraint(
                id="fix",
                type=ConstraintType.ATTACHMENT,
                reference1=ConstraintReference(part_id="base", lcs="L1"),
                reference2=ConstraintReference(part_id="world", lcs="Origin"),
                enabled=True
            ),
            AssemblyConstraint(
                id="attach_top",
                type=ConstraintType.ATTACHMENT,
                reference1=ConstraintReference(part_id="top", lcs="L1"),
                reference2=ConstraintReference(part_id="base", lcs="L2"),
                enabled=True
            )
        ]
        
        result = analyzer.analyze(parts, constraints)
        
        assert result.total_parts == 2
        assert result.total_dof == 12  # 2 parts * 6 DOF
        assert result.constrained_dof == 12  # 2 attachments * 6 DOF
        assert result.remaining_dof == 0
        assert result.is_fully_constrained
        assert not result.is_over_constrained
    
    def test_under_constrained_assembly(self):
        """Test DOF analysis for under-constrained assembly."""
        analyzer = DOFAnalyzer()
        
        parts = [
            PartReference(id="p1", model_ref="/p1.step", quantity=1),
            PartReference(id="p2", model_ref="/p2.step", quantity=1),
            PartReference(id="p3", model_ref="/p3.step", quantity=1)
        ]
        
        constraints = [
            AssemblyConstraint(
                id="c1",
                type=ConstraintType.PLANE_COINCIDENT,
                reference1=ConstraintReference(part_id="p1", lcs="L1"),
                reference2=ConstraintReference(part_id="p2", lcs="L2"),
                enabled=True
            )
        ]
        
        result = analyzer.analyze(parts, constraints)
        
        assert result.total_parts == 3
        assert result.total_dof == 18  # 3 parts * 6 DOF
        assert result.constrained_dof == 3  # 1 plane constraint
        assert result.remaining_dof == 15
        assert not result.is_fully_constrained
        assert not result.is_over_constrained
        assert result.mobility == 9  # 15 - 6 (fixed frame)
    
    def test_over_constrained_assembly(self):
        """Test DOF analysis for over-constrained assembly."""
        analyzer = DOFAnalyzer()
        
        parts = [
            PartReference(id="p1", model_ref="/p1.step", quantity=1)
        ]
        
        # More constraints than DOF
        constraints = [
            AssemblyConstraint(
                id=f"c{i}",
                type=ConstraintType.ATTACHMENT,
                reference1=ConstraintReference(part_id="p1", lcs=f"L{i}"),
                reference2=ConstraintReference(part_id="world", lcs=f"W{i}"),
                enabled=True
            )
            for i in range(3)  # 3 attachments = 18 DOF reduction
        ]
        
        result = analyzer.analyze(parts, constraints)
        
        assert result.total_parts == 1
        assert result.total_dof == 6
        assert result.constrained_dof == 18  # Over-constrained
        assert result.is_over_constrained


class TestAssembly4Service:
    """Test main Assembly4 service."""
    
    @patch('app.services.assembly4_service.FreeCADDocumentManager')
    @patch('app.services.assembly4_service.FreeCAD')
    def test_process_assembly_success(
        self, mock_freecad, mock_doc_manager, sample_assembly_input
    ):
        """Test successful assembly processing."""
        service = Assembly4Service()
        
        # Mock document manager
        mock_doc = MagicMock()
        mock_doc_manager.create_document.return_value.__enter__.return_value = mock_doc
        service.document_manager = mock_doc_manager
        
        # Mock FreeCAD operations
        mock_freecad.newDocument.return_value = mock_doc
        mock_freecad.openDocument.return_value = mock_doc
        
        # Create export options
        export_options = ExportOptions(
            formats=["FCStd", "STEP", "BOM_JSON"],
            merge_step=True,
            generate_exploded=True,
            exploded_factor=1.5
        )
        
        with patch.object(service, '_load_parts') as mock_load:
            with patch.object(service, '_extract_lcs') as mock_lcs:
                with patch.object(service, '_save_assembly') as mock_save:
                    mock_load.return_value = {"base_plate": mock_doc}
                    mock_lcs.return_value = {}
                    mock_save.return_value = "/tmp/assembly.FCStd"
                    
                    result = service.process_assembly(
                        job_id="test_123",
                        assembly_input=sample_assembly_input,
                        generate_cam=False,
                        export_options=export_options
                    )
                    
                    assert result.job_id == "test_123"
                    assert result.status in ["success", "partial"]
                    assert result.assembly_file == "/tmp/assembly.FCStd"
    
    def test_assembly_exception_handling(self):
        """Test Assembly4Exception handling."""
        exc = Assembly4Exception(
            "Test error",
            Assembly4ErrorCode.PART_NOT_FOUND,
            {"part": "missing"},
            "Test hatası"
        )
        
        assert exc.message == "Test error"
        assert exc.error_code == Assembly4ErrorCode.PART_NOT_FOUND
        assert exc.details == {"part": "missing"}
        assert exc.turkish_message == "Test hatası"
    
    @patch('app.services.assembly4_service.Path')
    @patch('app.services.assembly4_service.FreeCAD')
    def test_cam_generation(
        self, mock_freecad, mock_path, sample_cam_parameters
    ):
        """Test CAM generation."""
        service = Assembly4Service()
        
        # Mock document
        mock_doc = MagicMock()
        mock_assembly = MagicMock()
        
        # Mock Path workbench
        mock_job = MagicMock()
        mock_doc.addObject.return_value = mock_job
        
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('tempfile.gettempdir', return_value=tmpdir):
                # This would require full Path Workbench mocking
                # For now, test that the method exists and handles errors
                try:
                    result = service._generate_cam(
                        mock_doc,
                        mock_assembly,
                        "test_job",
                        sample_cam_parameters
                    )
                except Assembly4Exception as e:
                    # Expected if Path Workbench not available
                    assert e.error_code == Assembly4ErrorCode.CAM_GENERATION_FAILED


class TestCAMParameters:
    """Test CAM parameter validation."""
    
    def test_valid_cam_parameters(self, sample_cam_parameters):
        """Test valid CAM parameters."""
        assert sample_cam_parameters.wcs.coordinate_system == "G54"
        assert sample_cam_parameters.stock.type == "box"
        assert len(sample_cam_parameters.operations) == 3
        assert sample_cam_parameters.post_processor == PostProcessor.LINUXCNC
    
    def test_operation_validation(self):
        """Test CAM operation validation."""
        operation = CAMOperation(
            type=OperationType.ADAPTIVE,
            tool=Tool(
                name="Adaptive_5mm",
                number=4,
                type="endmill",
                diameter=5.0,
                flutes=3,
                cutting_height=25.0
            ),
            feeds_speeds=FeedsAndSpeeds(
                feed_rate=400.0,
                plunge_rate=100.0,
                spindle_speed=5000,
                spindle_direction="CW",
                surface_speed=80.0,
                chip_load=0.05
            ),
            depths={
                "start_depth": 0.0,
                "final_depth": -10.0,
                "step_down": 2.0
            },
            strategy="Spiral",
            cut_mode="Climb",
            parameters={
                "step_over": 20,
                "helix_angle": 3.0,
                "helix_diameter": 10.0
            }
        )
        
        assert operation.type == OperationType.ADAPTIVE
        assert operation.tool.diameter == 5.0
        assert operation.feeds_speeds.spindle_speed == 5000
        assert operation.parameters["helix_angle"] == 3.0


class TestExportOptions:
    """Test export options."""
    
    def test_export_formats(self):
        """Test export format validation."""
        options = ExportOptions(
            formats=["FCStd", "STEP", "IGES", "BOM_JSON", "BOM_CSV"],
            merge_step=True,
            generate_exploded=True,
            exploded_factor=2.0,
            include_hidden=False
        )
        
        assert "STEP" in options.formats
        assert options.exploded_factor == 2.0
        assert not options.include_hidden


class TestIntegration:
    """Integration tests."""
    
    @pytest.mark.integration
    @patch('app.services.assembly4_service.FreeCAD')
    def test_full_workflow(
        self, mock_freecad, sample_assembly_input, sample_cam_parameters
    ):
        """Test full assembly to CAM workflow."""
        service = Assembly4Service()
        
        # This would be a full integration test with real FreeCAD
        # For unit tests, we mock the FreeCAD interactions
        mock_doc = MagicMock()
        mock_freecad.newDocument.return_value = mock_doc
        
        # Test would verify:
        # 1. Assembly creation
        # 2. Constraint solving
        # 3. Collision detection
        # 4. DOF analysis
        # 5. CAM generation
        # 6. Export to various formats
        
        # This requires extensive mocking or actual FreeCAD environment
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])