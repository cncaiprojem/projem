"""
Ultra-Enterprise Tests for Upload Normalization Service

Comprehensive test coverage for CAD file upload normalization including:
- Format detection and handling
- Unit conversion validation
- Orientation normalization
- Mesh repair operations
- Layer consolidation
- Geometry validation
- Error handling
- Turkish localization
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call, ANY

import pytest

from apps.api.app.services.upload_normalization_service import (
    UploadNormalizationService,
    FileFormat,
    Units,
    NormalizationConfig,
    NormalizationResult,
    NormalizationException,
    NormalizationErrorCode,
    GeometryMetrics,
    STEPHandler,
    STLHandler,
    DXFHandler,
    IFCHandler,
    upload_normalization_service
)


class TestFileFormatDetection:
    """Test file format detection."""
    
    def test_detect_step_format(self):
        """Test STEP format detection."""
        service = UploadNormalizationService()
        
        # Test .step extension
        assert service.detect_format(Path("model.step")) == FileFormat.STEP
        assert service.detect_format(Path("model.STEP")) == FileFormat.STEP
        assert service.detect_format(Path("model.stp")) == FileFormat.STEP
        assert service.detect_format(Path("model.STP")) == FileFormat.STEP
    
    def test_detect_iges_format(self):
        """Test IGES format detection."""
        service = UploadNormalizationService()
        
        assert service.detect_format(Path("model.iges")) == FileFormat.IGES
        assert service.detect_format(Path("model.IGES")) == FileFormat.IGES
        assert service.detect_format(Path("model.igs")) == FileFormat.IGES
        assert service.detect_format(Path("model.IGS")) == FileFormat.IGES
    
    def test_detect_stl_format(self):
        """Test STL format detection."""
        service = UploadNormalizationService()
        
        assert service.detect_format(Path("model.stl")) == FileFormat.STL
        assert service.detect_format(Path("model.STL")) == FileFormat.STL
    
    def test_detect_dxf_format(self):
        """Test DXF format detection."""
        service = UploadNormalizationService()
        
        assert service.detect_format(Path("model.dxf")) == FileFormat.DXF
        assert service.detect_format(Path("model.DXF")) == FileFormat.DXF
    
    def test_detect_ifc_format(self):
        """Test IFC format detection."""
        service = UploadNormalizationService()
        
        assert service.detect_format(Path("building.ifc")) == FileFormat.IFC
        assert service.detect_format(Path("building.IFC")) == FileFormat.IFC
    
    def test_unsupported_format(self):
        """Test unsupported format raises exception."""
        service = UploadNormalizationService()
        
        with pytest.raises(NormalizationException) as exc_info:
            service.detect_format(Path("model.xyz"))
        
        assert exc_info.value.code == NormalizationErrorCode.UNSUPPORTED_FORMAT
        assert "xyz" in exc_info.value.message
        assert exc_info.value.turkish_message is not None


class TestSTEPHandler:
    """Test STEP format handler."""
    
    def test_detect_units_millimeter(self, tmp_path):
        """Test detecting millimeter units from STEP file."""
        handler = STEPHandler()
        
        # Create test STEP file with mm units
        step_file = tmp_path / "test.step"
        step_file.write_text("""
ISO-10303-21;
HEADER;
FILE_SCHEMA(('CONFIG_CONTROL_DESIGN'));
/* Units in millimeters */
#1=LENGTH_UNIT('MILLIMETRE');
ENDSEC;
DATA;
ENDSEC;
END-ISO-10303-21;
""")
        
        assert handler.detect_units(step_file) == Units.MILLIMETER
    
    def test_detect_units_meter(self, tmp_path):
        """Test detecting meter units from STEP file."""
        handler = STEPHandler()
        
        # Create test STEP file with meter units
        step_file = tmp_path / "test.step"
        step_file.write_text("""
ISO-10303-21;
HEADER;
FILE_SCHEMA(('CONFIG_CONTROL_DESIGN'));
/* Units in meters */
#1=LENGTH_UNIT('METRE');
ENDSEC;
DATA;
ENDSEC;
END-ISO-10303-21;
""")
        
        assert handler.detect_units(step_file) == Units.METER
    
    def test_detect_units_inch(self, tmp_path):
        """Test detecting inch units from STEP file."""
        handler = STEPHandler()
        
        # Create test STEP file with inch units
        step_file = tmp_path / "test.step"
        step_file.write_text("""
ISO-10303-21;
HEADER;
FILE_SCHEMA(('CONFIG_CONTROL_DESIGN'));
/* Units in inches */
#1=LENGTH_UNIT('INCH');
ENDSEC;
DATA;
ENDSEC;
END-ISO-10303-21;
""")
        
        assert handler.detect_units(step_file) == Units.INCH
    
    def test_detect_units_unknown(self, tmp_path):
        """Test unknown units detection."""
        handler = STEPHandler()
        
        # Create test STEP file without unit info
        step_file = tmp_path / "test.step"
        step_file.write_text("""
ISO-10303-21;
HEADER;
ENDSEC;
DATA;
ENDSEC;
END-ISO-10303-21;
""")
        
        assert handler.detect_units(step_file) == Units.UNKNOWN
    
    @patch('apps.api.app.services.upload_normalization_service.freecad_service')
    def test_load_step_file(self, mock_freecad_service):
        """Test loading STEP file into FreeCAD."""
        handler = STEPHandler()
        
        # Mock FreeCAD response
        mock_freecad_service.execute_script.return_value = {
            "success": True,
            "object_count": 3,
            "doc_name": "test_doc"
        }
        
        result = handler.load(Path("/test/model.step"), "test_doc")
        
        assert result["success"] is True
        assert result["object_count"] == 3
        assert result["doc_name"] == "test_doc"
        
        # Verify script was called
        mock_freecad_service.execute_script.assert_called_once()
        script = mock_freecad_service.execute_script.call_args[0][0]
        assert "Import.open" in script
        assert "/test/model.step" in script
    
    @patch('apps.api.app.services.upload_normalization_service.freecad_service')
    def test_normalize_step_geometry(self, mock_freecad_service):
        """Test normalizing STEP geometry."""
        handler = STEPHandler()
        
        # Mock FreeCAD response
        mock_freecad_service.execute_script.return_value = {
            "bbox_min": [-10, -10, -10],
            "bbox_max": [10, 10, 10],
            "volume": 8000.0,
            "surface_area": 2400.0,
            "edge_count": 12,
            "vertex_count": 8,
            "is_manifold": True,
            "is_watertight": True
        }
        
        config = NormalizationConfig(
            target_units=Units.MILLIMETER,
            normalize_orientation=True,
            center_geometry=True,
            merge_duplicates=True
        )
        
        doc = {"doc_name": "test_doc"}
        file_path = Path("/test/model.step")
        metrics = handler.normalize(doc, config, file_path)
        
        assert metrics.bbox_min == [-10, -10, -10]
        assert metrics.bbox_max == [10, 10, 10]
        assert metrics.volume == 8000.0
        assert metrics.surface_area == 2400.0
        assert metrics.is_manifold is True
        assert metrics.is_watertight is True
    
    @patch('apps.api.app.services.upload_normalization_service.freecad_service')
    def test_validate_step_geometry(self, mock_freecad_service):
        """Test validating STEP geometry."""
        handler = STEPHandler()
        
        # Mock validation warnings
        mock_freecad_service.execute_script.return_value = [
            "Shape Part1 has self-intersections",
            "Shape Part2 has very small volume (0.000001 mm³)"
        ]
        
        doc = {"doc_name": "test_doc"}
        warnings = handler.validate(doc)
        
        assert len(warnings) == 2
        assert "self-intersections" in warnings[0]
        assert "very small volume" in warnings[1]


class TestSTLHandler:
    """Test STL format handler."""
    
    @patch('apps.api.app.services.upload_normalization_service.TRIMESH_AVAILABLE', True)
    @patch('apps.api.app.services.upload_normalization_service.trimesh')
    def test_detect_units_heuristic(self, mock_trimesh, tmp_path):
        """Test detecting units from STL using heuristics."""
        handler = STLHandler()
        
        # Mock trimesh mesh with small bounding box (likely inches)
        mock_mesh = MagicMock()
        mock_mesh.bounds = [[0, 0, 0], [5, 5, 5]]  # 5 units diagonal
        mock_trimesh.load.return_value = mock_mesh
        
        stl_file = tmp_path / "test.stl"
        stl_file.write_bytes(b"dummy stl content")
        
        assert handler.detect_units(stl_file) == Units.INCH
        
        # Test with large bounding box (likely mm)
        mock_mesh.bounds = [[0, 0, 0], [100, 100, 100]]  # 100 units diagonal
        assert handler.detect_units(stl_file) == Units.MILLIMETER
    
    @patch('apps.api.app.services.upload_normalization_service.freecad_service')
    def test_load_stl_file(self, mock_freecad_service):
        """Test loading STL file into FreeCAD."""
        handler = STLHandler()
        
        # Mock FreeCAD response
        mock_freecad_service.execute_script.return_value = {
            "success": True,
            "has_mesh": True,
            "has_shape": False,
            "doc_name": "test_doc",
            "triangle_count": 1000,
            "vertex_count": 502
        }
        
        result = handler.load(Path("/test/model.stl"), "test_doc")
        
        assert result["success"] is True
        assert result["has_mesh"] is True
        assert result["triangle_count"] == 1000
        assert result["vertex_count"] == 502
    
    @patch('apps.api.app.services.upload_normalization_service.TRIMESH_AVAILABLE', True)
    @patch('apps.api.app.services.upload_normalization_service.trimesh')
    def test_normalize_stl_with_repair(self, mock_trimesh):
        """Test STL normalization with mesh repair."""
        handler = STLHandler()
        
        # Mock trimesh mesh needing repair
        mock_mesh = MagicMock()
        mock_mesh.is_watertight = False
        mock_mesh.is_winding_consistent = False
        mock_mesh.is_manifold = True
        mock_mesh.bounds = [[0, 0, 0], [10, 10, 10]]
        mock_mesh.volume = 1000.0
        mock_mesh.area = 600.0
        mock_mesh.center_mass = [5, 5, 5]
        
        mock_trimesh.load.return_value = mock_mesh
        
        config = NormalizationConfig(repair_mesh=True)
        doc = {"triangle_count": 1000, "vertex_count": 502}
        file_path = Path("/test/model.stl")
        
        metrics = handler.normalize(doc, config, file_path)
        
        # Verify repair methods were called
        mock_mesh.fill_holes.assert_called_once()
        mock_mesh.fix_normals.assert_called_once()
        mock_mesh.remove_degenerate_faces.assert_called_once()
        mock_mesh.remove_duplicate_faces.assert_called_once()
        mock_mesh.remove_unreferenced_vertices.assert_called_once()
        
        assert metrics.volume == 1000.0
        assert metrics.surface_area == 600.0
        assert metrics.is_manifold is True


class TestDXFHandler:
    """Test DXF format handler."""
    
    @patch('apps.api.app.services.upload_normalization_service.EZDXF_AVAILABLE', True)
    @patch('apps.api.app.services.upload_normalization_service.ezdxf')
    def test_detect_units_from_insunits(self, mock_ezdxf, tmp_path):
        """Test detecting units from DXF $INSUNITS."""
        handler = DXFHandler()
        
        # Mock ezdxf document with mm units
        mock_doc = MagicMock()
        mock_doc.header.get.return_value = 4  # Millimeter code
        mock_ezdxf.readfile.return_value = mock_doc
        
        dxf_file = tmp_path / "test.dxf"
        dxf_file.write_text("dummy dxf content")
        
        assert handler.detect_units(dxf_file) == Units.MILLIMETER
        
        # Test inch units
        mock_doc.header.get.return_value = 1  # Inch code
        assert handler.detect_units(dxf_file) == Units.INCH
        
        # Test meter units
        mock_doc.header.get.return_value = 6  # Meter code
        assert handler.detect_units(dxf_file) == Units.METER
    
    @patch('apps.api.app.services.upload_normalization_service.freecad_service')
    def test_load_dxf_file(self, mock_freecad_service):
        """Test loading DXF file into FreeCAD."""
        handler = DXFHandler()
        
        # Mock FreeCAD response
        mock_freecad_service.execute_script.return_value = {
            "success": True,
            "doc_name": "test_doc",
            "object_count": 50,
            "layers": ["Layer1", "Layer2", "Default"]
        }
        
        result = handler.load(Path("/test/drawing.dxf"), "test_doc")
        
        assert result["success"] is True
        assert result["object_count"] == 50
        assert "Layer1" in result["layers"]
        assert "Layer2" in result["layers"]
    
    @patch('apps.api.app.services.upload_normalization_service.freecad_service')
    def test_normalize_dxf_with_extrusion(self, mock_freecad_service):
        """Test DXF normalization with 2D extrusion."""
        handler = DXFHandler()
        
        # Mock FreeCAD response
        mock_freecad_service.execute_script.return_value = {
            "bbox_min": [-50, -50, 0],
            "bbox_max": [50, 50, 0.5],
            "volume": 5.0,  # Small volume due to thin extrusion
            "surface_area": 200.5,
            "edge_count": 100,
            "vertex_count": 50
        }
        
        config = NormalizationConfig(
            extrude_2d_thickness=0.5,
            merge_duplicates=True
        )
        
        doc = {"doc_name": "test_doc", "layers": ["Layer1"]}
        file_path = Path("/test/drawing.dxf")
        metrics = handler.normalize(doc, config, file_path)
        
        assert metrics.volume == 5.0
        assert metrics.bbox_max[2] == 0.5  # Z height from extrusion


class TestIFCHandler:
    """Test IFC format handler."""
    
    def test_detect_units_from_ifc(self, tmp_path):
        """Test detecting units from IFC file."""
        handler = IFCHandler()
        
        # Create test IFC file with meter units
        ifc_file = tmp_path / "building.ifc"
        ifc_file.write_text("""
ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');
FILE_NAME('building.ifc','2024-01-01T00:00:00',('Author'),('Organization'),'IFC2X3','','');
FILE_SCHEMA(('IFC2X3'));
ENDSEC;
DATA;
#1=IFCSIUNIT(*,.LENGTHUNIT.,.METRE.);
ENDSEC;
END-ISO-10303-21;
""")
        
        assert handler.detect_units(ifc_file) == Units.METER
        
        # Test with millimeter units
        ifc_file.write_text("""
ISO-10303-21;
HEADER;
ENDSEC;
DATA;
#1=IFCSIUNIT(*,.LENGTHUNIT.,$,.MILLI.,.METRE.);
ENDSEC;
END-ISO-10303-21;
""")
        
        assert handler.detect_units(ifc_file) == Units.MILLIMETER
    
    @patch('apps.api.app.services.upload_normalization_service.freecad_service')
    def test_load_ifc_file_success(self, mock_freecad_service):
        """Test successful IFC file loading."""
        handler = IFCHandler()
        
        # Mock successful IFC import
        mock_freecad_service.execute_script.return_value = {
            "success": True,
            "doc_name": "test_doc",
            "error": None,
            "object_count": 150,
            "building_elements": [
                {"name": "Wall1", "ifc_type": "IfcWall", "ifc_guid": "ABC123"},
                {"name": "Slab1", "ifc_type": "IfcSlab", "ifc_guid": "DEF456"}
            ]
        }
        
        result = handler.load(Path("/test/building.ifc"), "test_doc")
        
        assert result["success"] is True
        assert result["object_count"] == 150
        assert len(result["building_elements"]) == 2
        assert result["building_elements"][0]["ifc_type"] == "IfcWall"
    
    @patch('apps.api.app.services.upload_normalization_service.freecad_service')
    def test_load_ifc_file_missing_dependency(self, mock_freecad_service):
        """Test IFC loading with missing IfcOpenShell."""
        handler = IFCHandler()
        
        # Mock failed IFC import
        mock_freecad_service.execute_script.return_value = {
            "success": False,
            "doc_name": "test_doc",
            "error": "IfcOpenShell not installed",
            "object_count": 0,
            "building_elements": []
        }
        
        with pytest.raises(NormalizationException) as exc_info:
            handler.load(Path("/test/building.ifc"), "test_doc")
        
        assert exc_info.value.code == NormalizationErrorCode.IFC_DEP_MISSING
        assert "IfcOpenShell" in exc_info.value.message
        assert exc_info.value.turkish_message is not None


class TestUploadNormalizationService:
    """Test main upload normalization service."""
    
    @patch('apps.api.app.services.upload_normalization_service.s3_service')
    @patch('apps.api.app.services.upload_normalization_service.freecad_service')
    @patch('apps.api.app.services.upload_normalization_service.get_correlation_id')
    def test_normalize_step_upload_success(self, mock_correlation, mock_freecad, mock_s3):
        """Test successful STEP file normalization."""
        service = UploadNormalizationService()
        
        # Setup mocks
        mock_correlation.return_value = "test-correlation-id"
        mock_s3.download_file.return_value = True
        mock_s3.upload_file.return_value = True
        
        # Mock FreeCAD operations
        mock_freecad.execute_script.side_effect = [
            # Load response
            {"success": True, "object_count": 3, "doc_name": "doc_job123"},
            # Normalize response
            {
                "bbox_min": [-10, -10, -10],
                "bbox_max": [10, 10, 10],
                "volume": 8000.0,
                "surface_area": 2400.0,
                "edge_count": 12,
                "vertex_count": 8,
                "is_manifold": True,
                "is_watertight": True
            },
            # Validate response
            [],
            # Export FCStd response
            {"success": True},
            # Export STEP response
            {"success": True, "exported": 3},
            # Export STL response
            {"success": True, "mesh_count": 1},
            # Cleanup response
            {"success": True}
        ]
        
        # Create temp file for testing
        with tempfile.NamedTemporaryFile(suffix='.step', delete=False) as tmp:
            tmp.write(b"dummy step content")
            tmp_path = tmp.name
        
        # Mock download to create actual file
        def mock_download(s3_key, local_path):
            Path(local_path).write_bytes(b"dummy step content")
            return True
        
        mock_s3.download_file.side_effect = mock_download
        
        try:
            result = service.normalize_upload(
                s3_key="uploads/model.step",
                job_id="job123",
                config=NormalizationConfig(
                    target_units=Units.MILLIMETER,
                    normalize_orientation=True,
                    generate_preview=False  # Skip GLB generation for test
                )
            )
            
            # Verify result
            assert result.success is True
            assert result.job_id == "job123"
            assert result.original_format == FileFormat.STEP
            assert result.normalized_fcstd_key is not None
            assert result.normalized_step_key is not None
            assert result.normalized_stl_key is not None
            assert result.metrics.volume == 8000.0
            assert result.metrics.is_manifold is True
            assert len(result.warnings) == 0
            assert result.processing_time_ms > 0
            assert result.file_hash != ""
            
            # Verify S3 operations
            assert mock_s3.download_file.called
            assert mock_s3.upload_file.call_count >= 3  # FCStd, STEP, STL
            
        finally:
            # Clean up
            Path(tmp_path).unlink(missing_ok=True)
    
    @patch('apps.api.app.services.upload_normalization_service.s3_service')
    def test_normalize_upload_s3_download_failure(self, mock_s3):
        """Test handling S3 download failure."""
        service = UploadNormalizationService()
        
        # Mock S3 download failure
        mock_s3.download_file.return_value = False
        
        with pytest.raises(NormalizationException) as exc_info:
            service.normalize_upload(
                s3_key="uploads/model.step",
                job_id="job123"
            )
        
        assert exc_info.value.code == NormalizationErrorCode.S3_DOWNLOAD_FAILED
        assert "Failed to download" in exc_info.value.message
    
    @patch('apps.api.app.services.upload_normalization_service.s3_service')
    @patch('apps.api.app.services.upload_normalization_service.freecad_service')
    def test_normalize_upload_with_warnings(self, mock_freecad, mock_s3):
        """Test normalization with validation warnings."""
        service = UploadNormalizationService()
        
        # Setup mocks
        mock_s3.download_file.return_value = True
        mock_s3.upload_file.return_value = True
        
        # Mock download to create actual file
        def mock_download(s3_key, local_path):
            Path(local_path).write_bytes(b"dummy stl content")
            return True
        
        mock_s3.download_file.side_effect = mock_download
        
        # Mock FreeCAD operations with warnings
        mock_freecad.execute_script.side_effect = [
            # Load response
            {"success": True, "has_mesh": True, "has_shape": False, 
             "doc_name": "doc_job124", "triangle_count": 1000000, "vertex_count": 500000},
            # Validate response with warnings
            ["Very high triangle count (1000000), may impact performance"],
            # Export FCStd response
            {"success": True},
            # Export STL response
            {"success": True, "mesh_count": 1},
            # Cleanup response
            {"success": True}
        ]
        
        result = service.normalize_upload(
            s3_key="uploads/model.stl",
            job_id="job124",
            config=NormalizationConfig(generate_preview=False)
        )
        
        # Verify warnings were captured
        assert result.success is True
        assert len(result.warnings) == 1
        assert "high triangle count" in result.warnings[0]
    
    def test_turkish_error_messages(self):
        """Test Turkish localization of error messages."""
        service = UploadNormalizationService()
        
        # Test each error code has Turkish message
        for error_code in [
            NormalizationErrorCode.UNSUPPORTED_FORMAT,
            NormalizationErrorCode.STEP_TOPOLOGY,
            NormalizationErrorCode.STL_NOT_MANIFOLD,
            NormalizationErrorCode.DXF_UNITS_UNKNOWN,
            NormalizationErrorCode.IFC_DEP_MISSING,
            NormalizationErrorCode.FILE_CORRUPTED,
            NormalizationErrorCode.VALIDATION_FAILED
        ]:
            assert error_code in service.turkish_messages
            assert len(service.turkish_messages[error_code]) > 0
            # Check for Turkish characters
            turkish_chars = ['ç', 'ğ', 'ı', 'ö', 'ş', 'ü', 'Ç', 'Ğ', 'İ', 'Ö', 'Ş', 'Ü']
            message = service.turkish_messages[error_code]
            # At least some messages should contain Turkish characters
            if error_code in [NormalizationErrorCode.STL_NOT_MANIFOLD, 
                             NormalizationErrorCode.DXF_UNITS_UNKNOWN]:
                assert any(char in message for char in turkish_chars)


class TestNormalizationConfig:
    """Test normalization configuration."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = NormalizationConfig()
        
        assert config.target_units == Units.MILLIMETER
        assert config.normalize_orientation is True
        assert config.center_geometry is False
        assert config.repair_mesh is True
        assert config.merge_duplicates is True
        assert config.validate_geometry is True
        assert config.generate_preview is True
        assert config.extrude_2d_thickness == 0.5
        assert config.tolerance == 0.001
        assert config.max_file_size_mb == 500.0
    
    def test_custom_config(self):
        """Test custom configuration."""
        config = NormalizationConfig(
            target_units=Units.INCH,
            center_geometry=True,
            repair_mesh=False,
            material_name="Aluminum 6061",
            tolerance=0.01
        )
        
        assert config.target_units == Units.INCH
        assert config.center_geometry is True
        assert config.repair_mesh is False
        assert config.material_name == "Aluminum 6061"
        assert config.tolerance == 0.01


class TestGeometryMetrics:
    """Test geometry metrics model."""
    
    def test_complete_metrics(self):
        """Test complete geometry metrics."""
        metrics = GeometryMetrics(
            bbox_min=[-10, -10, -10],
            bbox_max=[10, 10, 10],
            volume=8000.0,
            surface_area=2400.0,
            triangle_count=1000,
            edge_count=12,
            vertex_count=8,
            is_manifold=True,
            is_watertight=True,
            material_name="Steel AISI 1018",
            material_density=7.85,
            mass=62800.0,
            center_of_mass=[0, 0, 0]
        )
        
        assert metrics.volume == 8000.0
        assert metrics.mass == 62800.0
        assert metrics.material_density == 7.85
        assert metrics.is_manifold is True
        assert metrics.is_watertight is True
    
    def test_minimal_metrics(self):
        """Test minimal required metrics."""
        metrics = GeometryMetrics(
            bbox_min=[0, 0, 0],
            bbox_max=[1, 1, 1],
            volume=1.0,
            surface_area=6.0
        )
        
        assert metrics.triangle_count is None
        assert metrics.material_name is None
        assert metrics.mass is None


class TestIntegrationScenarios:
    """Test complete integration scenarios."""
    
    @patch('apps.api.app.services.upload_normalization_service.s3_service')
    @patch('apps.api.app.services.upload_normalization_service.freecad_service')
    @patch('apps.api.app.services.upload_normalization_service.TRIMESH_AVAILABLE', True)
    @patch('apps.api.app.services.upload_normalization_service.trimesh')
    def test_stl_repair_workflow(self, mock_trimesh, mock_freecad, mock_s3):
        """Test complete STL repair workflow."""
        service = UploadNormalizationService()
        
        # Setup mocks
        mock_s3.download_file.return_value = True
        mock_s3.upload_file.return_value = True
        
        # Mock download to create actual file
        def mock_download(s3_key, local_path):
            Path(local_path).write_bytes(b"dummy stl content")
            return True
        
        mock_s3.download_file.side_effect = mock_download
        
        # Mock trimesh operations
        mock_mesh = MagicMock()
        mock_mesh.is_watertight = False
        mock_mesh.is_manifold = True
        mock_mesh.bounds = [[0, 0, 0], [10, 10, 10]]
        mock_mesh.volume = 1000.0
        mock_mesh.area = 600.0
        mock_mesh.center_mass = [5, 5, 5]
        mock_trimesh.load.return_value = mock_mesh
        
        # Mock FreeCAD operations
        mock_freecad.execute_script.side_effect = [
            # Load response
            {"success": True, "has_mesh": True, "has_shape": False,
             "doc_name": "doc_job125", "triangle_count": 5000, "vertex_count": 2502},
            # Validate response
            [],
            # Export FCStd response
            {"success": True},
            # Export STL response
            {"success": True, "mesh_count": 1},
            # Cleanup response
            {"success": True}
        ]
        
        result = service.normalize_upload(
            s3_key="uploads/broken.stl",
            job_id="job125",
            config=NormalizationConfig(
                repair_mesh=True,
                generate_preview=False
            )
        )
        
        # Verify repair was attempted
        mock_mesh.fill_holes.assert_called_once()
        mock_mesh.fix_normals.assert_called_once()
        
        assert result.success is True
        assert result.metrics.is_manifold is True
    
    @patch('apps.api.app.services.upload_normalization_service.s3_service')
    @patch('apps.api.app.services.upload_normalization_service.freecad_service')
    def test_unit_conversion_workflow(self, mock_freecad, mock_s3):
        """Test unit conversion from inches to millimeters."""
        service = UploadNormalizationService()
        
        # Setup mocks
        mock_s3.download_file.return_value = True
        mock_s3.upload_file.return_value = True
        
        # Mock download to create actual file with inch units
        def mock_download(s3_key, local_path):
            Path(local_path).write_text("""
ISO-10303-21;
HEADER;
#1=LENGTH_UNIT('INCH');
ENDSEC;
DATA;
ENDSEC;
END-ISO-10303-21;
""")
            return True
        
        mock_s3.download_file.side_effect = mock_download
        
        # Mock FreeCAD operations
        mock_freecad.execute_script.side_effect = [
            # Load response
            {"success": True, "object_count": 1, "doc_name": "doc_job126"},
            # Normalize response (after conversion)
            {
                "bbox_min": [-254, -254, -254],  # 10 inches = 254 mm
                "bbox_max": [254, 254, 254],
                "volume": 262144000.0,  # Scaled volume
                "surface_area": 387096.0,  # Scaled area
                "edge_count": 12,
                "vertex_count": 8,
                "is_manifold": True,
                "is_watertight": True
            },
            # Validate response
            [],
            # Export FCStd response
            {"success": True},
            # Export STEP response
            {"success": True, "exported": 1},
            # Export STL response
            {"success": True, "mesh_count": 1},
            # Cleanup response
            {"success": True}
        ]
        
        result = service.normalize_upload(
            s3_key="uploads/inch_model.step",
            job_id="job126",
            config=NormalizationConfig(
                target_units=Units.MILLIMETER,
                generate_preview=False
            ),
            declared_units=Units.INCH
        )
        
        assert result.success is True
        assert result.original_units == Units.INCH
        # Verify conversion happened (254mm = 10 inches)
        assert result.metrics.bbox_max[0] == 254