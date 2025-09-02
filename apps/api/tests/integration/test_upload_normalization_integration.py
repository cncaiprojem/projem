"""
Integration tests for Upload Normalization Service (Task 7.7)

Tests the complete upload normalization flow including:
- File upload to S3
- Format detection and validation
- Unit conversion and orientation normalization
- Mesh repair and geometry validation
- Preview generation
- Integration with FreeCAD service
- Error handling and Turkish localization
"""

import asyncio
import logging
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi import UploadFile
from sqlalchemy.orm import Session

# Set up logger
logger = logging.getLogger(__name__)

from apps.api.app.services.upload_normalization_service import (
    UploadNormalizationService,
    FileFormat,
    Units,
    NormalizationConfig,
    NormalizationResult,
    NormalizationException,
    NormalizationErrorCode,
    upload_normalization_service
)
from apps.api.app.services.s3_service import S3Service
from apps.api.app.services.freecad_service import FreeCADService
from apps.api.app.models.job import Job, JobStatus
from apps.api.app.schemas.jobs import JobCreate


@pytest.fixture
def mock_db():
    """Mock database session."""
    return MagicMock(spec=Session)


@pytest.fixture
def mock_s3_service():
    """Mock S3 service."""
    service = MagicMock(spec=S3Service)
    service.upload_file = MagicMock(return_value=True)
    service.download_file = MagicMock(return_value=True)
    service.get_presigned_url = MagicMock(return_value="https://s3.example.com/file")
    service.delete_file = MagicMock(return_value=True)
    return service


@pytest.fixture
def mock_freecad_service():
    """Mock FreeCAD service."""
    service = MagicMock(spec=FreeCADService)
    service.execute_script = MagicMock()
    service.health_check = MagicMock(return_value={"status": "healthy"})
    return service


class TestUploadNormalizationIntegration:
    """Integration tests for upload normalization."""
    
    @pytest.mark.asyncio
    async def test_step_file_upload_and_normalization(self, mock_db, mock_s3_service, mock_freecad_service):
        """Test complete STEP file upload and normalization flow."""
        # Create test STEP file
        with tempfile.NamedTemporaryFile(suffix='.step', delete=False) as tmp:
            tmp.write(b"""
ISO-10303-21;
HEADER;
FILE_SCHEMA(('CONFIG_CONTROL_DESIGN'));
#1=LENGTH_UNIT('MILLIMETRE');
ENDSEC;
DATA;
#2=CARTESIAN_POINT('Origin',(0.,0.,0.));
#3=DIRECTION('Z',(0.,0.,1.));
#4=DIRECTION('X',(1.,0.,0.));
#5=AXIS2_PLACEMENT_3D('',#2,#3,#4);
#6=ADVANCED_BREP_SHAPE_REPRESENTATION('',(#7),#8);
#7=MANIFOLD_SOLID_BREP('Box',#9);
#8=(GEOMETRIC_REPRESENTATION_CONTEXT(3)
GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#10))
GLOBAL_UNIT_ASSIGNED_CONTEXT((#1,#11,#12))
REPRESENTATION_CONTEXT('ID1','3D'));
#9=CLOSED_SHELL('',(#13));
#10=UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-6),#1,'distance_accuracy_value','');
#11=(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.));
#12=(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT());
#13=ADVANCED_FACE('',(#14),#15,.T.);
#14=FACE_BOUND('',#16,.T.);
#15=PLANE('',#5);
#16=EDGE_LOOP('',(#17,#18,#19,#20));
#17=ORIENTED_EDGE('',*,*,#21,.T.);
#18=ORIENTED_EDGE('',*,*,#22,.T.);
#19=ORIENTED_EDGE('',*,*,#23,.T.);
#20=ORIENTED_EDGE('',*,*,#24,.T.);
ENDSEC;
END-ISO-10303-21;
""")
            step_file_path = tmp.name
        
        try:
            # Mock S3 operations
            def mock_download(s3_key, local_path):
                # Copy test file to local path
                shutil.copy(step_file_path, local_path)
                return True
            
            mock_s3_service.download_file = mock_download
            
            # Mock FreeCAD operations
            mock_freecad_service.execute_script.side_effect = [
                # Load response
                {"success": True, "object_count": 1, "doc_name": "doc_test123"},
                # Normalize response
                {
                    "bbox_min": [-50, -50, -50],
                    "bbox_max": [50, 50, 50],
                    "volume": 1000000.0,
                    "surface_area": 60000.0,
                    "edge_count": 12,
                    "vertex_count": 8,
                    "is_manifold": True,
                    "is_watertight": True
                },
                # Validate response
                [],
                # Export FCStd
                {"success": True},
                # Export STEP
                {"success": True, "exported": 1},
                # Export STL
                {"success": True, "mesh_count": 1},
                # Cleanup
                {"success": True}
            ]
            
            # Patch the services
            with patch('apps.api.app.services.upload_normalization_service.s3_service', mock_s3_service):
                with patch('apps.api.app.services.upload_normalization_service.freecad_service', mock_freecad_service):
                    # Execute normalization
                    result = upload_normalization_service.normalize_upload(
                        s3_key="uploads/test_model.step",
                        job_id="test123",
                        config=NormalizationConfig(
                            target_units=Units.MILLIMETER,
                            normalize_orientation=True,
                            center_geometry=False,
                            validate_geometry=True,
                            generate_preview=False
                        )
                    )
            
            # Verify results
            assert result.success is True
            assert result.job_id == "test123"
            assert result.original_format == FileFormat.STEP
            assert result.original_units == Units.MILLIMETER
            assert result.normalized_fcstd_key is not None
            assert result.normalized_step_key is not None
            assert result.normalized_stl_key is not None
            assert result.metrics.volume == 1000000.0
            assert result.metrics.is_manifold is True
            assert result.metrics.is_watertight is True
            assert len(result.warnings) == 0
            
            # Verify S3 uploads were called
            assert mock_s3_service.upload_file.call_count >= 3  # FCStd, STEP, STL
            
            # Verify FreeCAD operations were called
            assert mock_freecad_service.execute_script.call_count >= 6
            
        finally:
            # Cleanup
            Path(step_file_path).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_stl_file_with_repair(self, mock_db, mock_s3_service, mock_freecad_service):
        """Test STL file upload with mesh repair."""
        # Create test STL file (ASCII format)
        with tempfile.NamedTemporaryFile(suffix='.stl', delete=False) as tmp:
            tmp.write(b"""solid TestCube
  facet normal 0 0 -1
    outer loop
      vertex 0 0 0
      vertex 1 0 0
      vertex 1 1 0
    endloop
  endfacet
  facet normal 0 0 -1
    outer loop
      vertex 0 0 0
      vertex 1 1 0
      vertex 0 1 0
    endloop
  endfacet
endsolid TestCube
""")
            stl_file_path = tmp.name
        
        try:
            # Mock S3 operations
            def mock_download(s3_key, local_path):
                shutil.copy(stl_file_path, local_path)
                return True
            
            mock_s3_service.download_file = mock_download
            
            # Mock FreeCAD operations
            mock_freecad_service.execute_script.side_effect = [
                # Load response
                {"success": True, "has_mesh": True, "has_shape": False,
                 "doc_name": "doc_test124", "triangle_count": 12, "vertex_count": 8},
                # Validate response with warning
                ["STL could not be converted to solid shape"],
                # Export FCStd
                {"success": True},
                # Export STL
                {"success": True, "mesh_count": 1},
                # Cleanup
                {"success": True}
            ]
            
            # Mock trimesh if available
            with patch('apps.api.app.services.upload_normalization_service.TRIMESH_AVAILABLE', True):
                mock_trimesh = MagicMock()
                mock_mesh = MagicMock()
                mock_mesh.is_watertight = False
                mock_mesh.is_manifold = False
                mock_mesh.bounds = [[0, 0, 0], [1, 1, 1]]
                mock_mesh.volume = 1.0
                mock_mesh.area = 6.0
                mock_mesh.center_mass = [0.5, 0.5, 0.5]
                mock_trimesh.load.return_value = mock_mesh
                
                with patch('apps.api.app.services.upload_normalization_service.trimesh', mock_trimesh):
                    with patch('apps.api.app.services.upload_normalization_service.s3_service', mock_s3_service):
                        with patch('apps.api.app.services.upload_normalization_service.freecad_service', mock_freecad_service):
                            # Execute normalization with repair
                            result = upload_normalization_service.normalize_upload(
                                s3_key="uploads/broken_mesh.stl",
                                job_id="test124",
                                config=NormalizationConfig(
                                    repair_mesh=True,
                                    validate_geometry=True,
                                    generate_preview=False
                                )
                            )
            
            # Verify results
            assert result.success is True
            assert result.original_format == FileFormat.STL
            assert result.normalized_fcstd_key is not None
            assert result.normalized_stl_key is not None
            assert result.normalized_step_key is None  # STL can't be converted to STEP
            assert len(result.warnings) == 1
            assert "solid shape" in result.warnings[0]
            
            # Verify repair operations were called
            mock_mesh.fill_holes.assert_called_once()
            mock_mesh.fix_normals.assert_called_once()
            mock_mesh.remove_degenerate_faces.assert_called_once()
            
        finally:
            # Cleanup
            Path(stl_file_path).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_dxf_file_with_extrusion(self, mock_db, mock_s3_service, mock_freecad_service):
        """Test DXF file upload with 2D to 3D extrusion."""
        # Create test DXF file
        with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as tmp:
            tmp.write(b"""0
SECTION
2
HEADER
9
$INSUNITS
70
4
0
ENDSEC
0
SECTION
2
ENTITIES
0
LINE
8
Layer1
10
0.0
20
0.0
30
0.0
11
100.0
21
100.0
31
0.0
0
ENDSEC
0
EOF
""")
            dxf_file_path = tmp.name
        
        try:
            # Mock S3 operations
            def mock_download(s3_key, local_path):
                shutil.copy(dxf_file_path, local_path)
                return True
            
            mock_s3_service.download_file = mock_download
            
            # Mock FreeCAD operations
            mock_freecad_service.execute_script.side_effect = [
                # Load response
                {"success": True, "doc_name": "doc_test125",
                 "object_count": 5, "layers": ["Layer1", "Default"]},
                # Normalize response (with extrusion)
                {
                    "bbox_min": [0, 0, 0],
                    "bbox_max": [100, 100, 0.5],
                    "volume": 5.0,
                    "surface_area": 200.5,
                    "edge_count": 20,
                    "vertex_count": 10
                },
                # Validate response
                [],
                # Export FCStd
                {"success": True},
                # Export STL
                {"success": True, "mesh_count": 1},
                # Export DXF
                {"success": True, "exported": 5},
                # Cleanup
                {"success": True}
            ]
            
            with patch('apps.api.app.services.upload_normalization_service.s3_service', mock_s3_service):
                with patch('apps.api.app.services.upload_normalization_service.freecad_service', mock_freecad_service):
                    # Execute normalization with extrusion
                    result = upload_normalization_service.normalize_upload(
                        s3_key="uploads/drawing.dxf",
                        job_id="test125",
                        config=NormalizationConfig(
                            extrude_2d_thickness=0.5,
                            merge_duplicates=True,
                            generate_preview=False
                        ),
                        declared_units=Units.MILLIMETER
                    )
            
            # Verify results
            assert result.success is True
            assert result.original_format == FileFormat.DXF
            assert result.original_units == Units.MILLIMETER
            assert result.normalized_dxf_key is not None  # DXF export preserved
            assert result.metrics.bbox_max[2] == 0.5  # Z height from extrusion
            assert result.metrics.volume == 5.0  # Small volume due to thin extrusion
            
        finally:
            # Cleanup
            Path(dxf_file_path).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_ifc_file_with_bom_extraction(self, mock_db, mock_s3_service, mock_freecad_service):
        """Test IFC file upload with BOM extraction."""
        # Create test IFC file
        with tempfile.NamedTemporaryFile(suffix='.ifc', delete=False) as tmp:
            tmp.write(b"""ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');
FILE_NAME('building.ifc','2024-01-01T00:00:00',('Author'),('Org'),'IFC2X3','','');
FILE_SCHEMA(('IFC2X3'));
ENDSEC;
DATA;
#1=IFCSIUNIT(*,.LENGTHUNIT.,.METRE.);
#2=IFCWALL('ABC123',#3,'Wall1',$,$,#4,#5,$,$);
#3=IFCOWNERHISTORY(#6,#7,$,.ADDED.,1609459200,$,$,1609459200);
#4=IFCLOCALPLACEMENT($,#8);
#5=IFCPRODUCTDEFINITIONSHAPE($,$,(#9));
#6=IFCPERSONANDORGANIZATION(#10,#11,$);
#7=IFCAPPLICATION(#11,'1.0','FreeCAD','FreeCAD');
#8=IFCAXIS2PLACEMENT3D(#12,$,$);
#9=IFCSHAPEREPRESENTATION(#13,'Body','SweptSolid',(#14));
#10=IFCPERSON($,'Author',$,$,$,$,$,$);
#11=IFCORGANIZATION($,'Org',$,$,$);
#12=IFCCARTESIANPOINT((0.,0.,0.));
#13=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#8,$);
#14=IFCEXTRUDEDAREASOLID(#15,#16,#17,3.);
#15=IFCRECTANGLEPROFILEDEF(.AREA.,$,#16,4.,0.2);
#16=IFCAXIS2PLACEMENT2D(#18,$);
#17=IFCDIRECTION((0.,0.,1.));
#18=IFCCARTESIANPOINT((0.,0.));
ENDSEC;
END-ISO-10303-21;
""")
            ifc_file_path = tmp.name
        
        try:
            # Mock S3 operations
            def mock_download(s3_key, local_path):
                shutil.copy(ifc_file_path, local_path)
                return True
            
            mock_s3_service.download_file = mock_download
            
            # Mock FreeCAD operations
            mock_freecad_service.execute_script.side_effect = [
                # Load response (successful)
                {"success": True, "doc_name": "doc_test126", "error": None,
                 "object_count": 10,
                 "building_elements": [
                     {"name": "Wall1", "ifc_type": "IfcWall", "ifc_guid": "ABC123"},
                     {"name": "Slab1", "ifc_type": "IfcSlab", "ifc_guid": "DEF456"}
                 ]},
                # Normalize response (with BOM)
                {
                    "bbox_min": [0, 0, 0],
                    "bbox_max": [4000, 200, 3000],  # In mm after conversion
                    "volume": 2400000.0,
                    "surface_area": 52000.0,
                    "edge_count": 12,
                    "vertex_count": 8,
                    "is_manifold": True,
                    "solid_count": 1,
                    "bom_count": 2
                },
                # Validate response
                [],
                # Export FCStd
                {"success": True},
                # Export STEP
                {"success": True, "exported": 1},
                # Export STL
                {"success": True, "mesh_count": 1},
                # Export IFC
                {"success": True, "error": None},
                # Cleanup
                {"success": True}
            ]
            
            with patch('apps.api.app.services.upload_normalization_service.s3_service', mock_s3_service):
                with patch('apps.api.app.services.upload_normalization_service.freecad_service', mock_freecad_service):
                    # Execute normalization
                    result = upload_normalization_service.normalize_upload(
                        s3_key="uploads/building.ifc",
                        job_id="test126",
                        config=NormalizationConfig(
                            generate_preview=False
                        )
                    )
            
            # Verify results
            assert result.success is True
            assert result.original_format == FileFormat.IFC
            assert result.original_units == Units.METER  # IFC default
            assert result.normalized_fcstd_key is not None
            assert result.metrics.metadata.get("bom_count") == 2
            assert result.metrics.volume > 0  # Converted to mm³
            
        finally:
            # Cleanup
            Path(ifc_file_path).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_error_handling_unsupported_format(self, mock_s3_service):
        """Test error handling for unsupported file format."""
        # Mock S3 download to create unsupported file
        def mock_download(s3_key, local_path):
            Path(local_path).write_text("unsupported content")
            return True
        
        mock_s3_service.download_file = mock_download
        
        with patch('apps.api.app.services.upload_normalization_service.s3_service', mock_s3_service):
            with pytest.raises(NormalizationException) as exc_info:
                upload_normalization_service.normalize_upload(
                    s3_key="uploads/model.xyz",
                    job_id="test_error"
                )
        
        assert exc_info.value.code == NormalizationErrorCode.UNSUPPORTED_FORMAT
        assert "xyz" in exc_info.value.message
        assert exc_info.value.turkish_message is not None
    
    @pytest.mark.asyncio
    async def test_error_handling_ifc_missing_dependency(self, mock_s3_service, mock_freecad_service):
        """Test error handling for missing IFC dependencies."""
        # Create test IFC file
        with tempfile.NamedTemporaryFile(suffix='.ifc', delete=False) as tmp:
            tmp.write(b"ISO-10303-21;")
            ifc_file_path = tmp.name
        
        try:
            # Mock S3 operations
            def mock_download(s3_key, local_path):
                shutil.copy(ifc_file_path, local_path)
                return True
            
            mock_s3_service.download_file = mock_download
            
            # Mock FreeCAD with IFC import failure
            mock_freecad_service.execute_script.return_value = {
                "success": False,
                "doc_name": "doc_test",
                "error": "IfcOpenShell not installed",
                "object_count": 0,
                "building_elements": []
            }
            
            with patch('apps.api.app.services.upload_normalization_service.s3_service', mock_s3_service):
                with patch('apps.api.app.services.upload_normalization_service.freecad_service', mock_freecad_service):
                    with pytest.raises(NormalizationException) as exc_info:
                        upload_normalization_service.normalize_upload(
                            s3_key="uploads/building.ifc",
                            job_id="test_ifc_error"
                        )
            
            assert exc_info.value.code == NormalizationErrorCode.IFC_DEP_MISSING
            assert "IfcOpenShell" in exc_info.value.message
            assert "IfcOpenShell" in exc_info.value.turkish_message
            
        finally:
            # Cleanup
            Path(ifc_file_path).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_unit_conversion_inch_to_mm(self, mock_s3_service, mock_freecad_service):
        """Test unit conversion from inches to millimeters."""
        # Create STEP file with inch units
        with tempfile.NamedTemporaryFile(suffix='.step', delete=False) as tmp:
            tmp.write(b"""ISO-10303-21;
HEADER;
#1=LENGTH_UNIT('INCH');
ENDSEC;
DATA;
ENDSEC;
END-ISO-10303-21;
""")
            step_file_path = tmp.name
        
        try:
            # Mock S3 operations
            def mock_download(s3_key, local_path):
                shutil.copy(step_file_path, local_path)
                return True
            
            mock_s3_service.download_file = mock_download
            
            # Mock FreeCAD operations
            mock_freecad_service.execute_script.side_effect = [
                # Load response
                {"success": True, "object_count": 1, "doc_name": "doc_test127"},
                # Normalize response (converted to mm)
                {
                    "bbox_min": [-25.4, -25.4, -25.4],  # 1 inch = 25.4 mm
                    "bbox_max": [25.4, 25.4, 25.4],
                    "volume": 16387.064,  # (2 inch)³ in mm³
                    "surface_area": 3870.96,  # Surface area in mm²
                    "edge_count": 12,
                    "vertex_count": 8,
                    "is_manifold": True,
                    "is_watertight": True
                },
                # Validate response
                [],
                # Export FCStd
                {"success": True},
                # Export STEP
                {"success": True, "exported": 1},
                # Export STL
                {"success": True, "mesh_count": 1},
                # Cleanup
                {"success": True}
            ]
            
            with patch('apps.api.app.services.upload_normalization_service.s3_service', mock_s3_service):
                with patch('apps.api.app.services.upload_normalization_service.freecad_service', mock_freecad_service):
                    # Execute normalization
                    result = upload_normalization_service.normalize_upload(
                        s3_key="uploads/inch_model.step",
                        job_id="test127",
                        config=NormalizationConfig(
                            target_units=Units.MILLIMETER,
                            generate_preview=False
                        )
                    )
            
            # Verify results
            assert result.success is True
            assert result.original_units == Units.INCH
            assert abs(result.metrics.bbox_max[0] - 25.4) < 0.01  # 1 inch = 25.4 mm
            assert result.metrics.volume > 16000  # Converted volume
            
        finally:
            # Cleanup
            Path(step_file_path).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_glb_preview_generation(self, mock_s3_service, mock_freecad_service):
        """Test GLB preview generation from STL."""
        # Create test STL file
        with tempfile.NamedTemporaryFile(suffix='.stl', delete=False) as tmp:
            tmp.write(b"solid test\nendsolid test")
            stl_file_path = tmp.name
        
        try:
            # Mock S3 operations
            def mock_download(s3_key, local_path):
                shutil.copy(stl_file_path, local_path)
                return True
            
            mock_s3_service.download_file = mock_download
            
            # Mock FreeCAD operations
            mock_freecad_service.execute_script.side_effect = [
                # Load response
                {"success": True, "has_mesh": True, "has_shape": True,
                 "doc_name": "doc_test128", "triangle_count": 100, "vertex_count": 52},
                # Validate response
                [],
                # Export FCStd
                {"success": True},
                # Export STL
                {"success": True, "mesh_count": 1},
                # Cleanup
                {"success": True}
            ]
            
            # Mock trimesh for GLB generation
            with patch('apps.api.app.services.upload_normalization_service.TRIMESH_AVAILABLE', True):
                mock_trimesh = MagicMock()
                mock_mesh = MagicMock()
                mock_mesh.export = MagicMock()
                mock_trimesh.load.return_value = mock_mesh
                
                with patch('apps.api.app.services.upload_normalization_service.trimesh', mock_trimesh):
                    with patch('apps.api.app.services.upload_normalization_service.s3_service', mock_s3_service):
                        with patch('apps.api.app.services.upload_normalization_service.freecad_service', mock_freecad_service):
                            # Mock GLB file creation
                            def mock_export(path, file_type):
                                if file_type == 'glb':
                                    Path(path).write_bytes(b"GLB content")
                            
                            mock_mesh.export = mock_export
                            
                            # Execute normalization with preview
                            result = upload_normalization_service.normalize_upload(
                                s3_key="uploads/model.stl",
                                job_id="test128",
                                config=NormalizationConfig(
                                    generate_preview=True
                                )
                            )
            
            # Verify GLB was generated and uploaded
            assert result.success is True
            assert result.preview_glb_key is not None
            assert "preview.glb" in result.preview_glb_key
            
        finally:
            # Cleanup
            Path(stl_file_path).unlink(missing_ok=True)


class TestPerformanceAndScalability:
    """Test performance and scalability aspects."""
    
    @pytest.mark.asyncio
    async def test_large_file_handling(self, mock_s3_service, mock_freecad_service):
        """Test handling of large CAD files."""
        # Create a "large" test file
        with tempfile.NamedTemporaryFile(suffix='.stl', delete=False) as tmp:
            # Simulate large STL with many triangles
            tmp.write(b"solid large\n")
            for i in range(100000):  # 100k triangles
                tmp.write(f"  facet normal 0 0 1\n".encode())
                tmp.write(f"    outer loop\n".encode())
                tmp.write(f"      vertex {i} 0 0\n".encode())
                tmp.write(f"      vertex {i+1} 0 0\n".encode())
                tmp.write(f"      vertex {i} 1 0\n".encode())
                tmp.write(f"    endloop\n".encode())
                tmp.write(f"  endfacet\n".encode())
            tmp.write(b"endsolid large")
            large_file_path = tmp.name
        
        try:
            # Mock S3 operations
            def mock_download(s3_key, local_path):
                shutil.copy(large_file_path, local_path)
                return True
            
            mock_s3_service.download_file = mock_download
            
            # Mock FreeCAD operations
            mock_freecad_service.execute_script.side_effect = [
                # Load response
                {"success": True, "has_mesh": True, "has_shape": False,
                 "doc_name": "doc_large", "triangle_count": 100000, "vertex_count": 50001},
                # Validate response with warning
                ["Very high triangle count (100000), may impact performance"],
                # Export FCStd
                {"success": True},
                # Export STL
                {"success": True, "mesh_count": 1},
                # Cleanup
                {"success": True}
            ]
            
            with patch('apps.api.app.services.upload_normalization_service.s3_service', mock_s3_service):
                with patch('apps.api.app.services.upload_normalization_service.freecad_service', mock_freecad_service):
                    # Execute normalization
                    result = upload_normalization_service.normalize_upload(
                        s3_key="uploads/large_model.stl",
                        job_id="test_large",
                        config=NormalizationConfig(
                            generate_preview=False,
                            repair_mesh=False  # Skip repair for performance
                        )
                    )
            
            # Verify handling
            assert result.success is True
            assert len(result.warnings) == 1
            assert "high triangle count" in result.warnings[0]
            assert result.metrics.triangle_count == 100000
            
        finally:
            # Cleanup
            Path(large_file_path).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_multiple_normalizations_sequentially(self, mock_s3_service, mock_freecad_service):
        """Test sequential normalization of multiple files.
        
        Note: This test processes multiple files sequentially, not concurrently.
        For true concurrent testing, see test_concurrent_normalization_with_asyncio.
        """
        import asyncio
        
        # Create test files
        test_files = []
        for i in range(3):
            with tempfile.NamedTemporaryFile(suffix='.step', delete=False) as tmp:
                tmp.write(f"ISO-10303-21; /* Test file {i} */".encode())
                test_files.append(tmp.name)
        
        try:
            # Mock S3 operations
            def mock_download(s3_key, local_path):
                # Use different file based on job_id
                if "job1" in s3_key:
                    shutil.copy(test_files[0], local_path)
                elif "job2" in s3_key:
                    shutil.copy(test_files[1], local_path)
                else:
                    shutil.copy(test_files[2], local_path)
                return True
            
            mock_s3_service.download_file = mock_download
            
            # Mock FreeCAD operations (simplified)
            def mock_execute(script, timeout=60):
                if "newDocument" in script:
                    return {"success": True, "object_count": 1, "doc_name": "doc_concurrent"}
                elif "bbox" in script.lower():
                    return {
                        "bbox_min": [0, 0, 0],
                        "bbox_max": [10, 10, 10],
                        "volume": 1000.0,
                        "surface_area": 600.0,
                        "edge_count": 12,
                        "vertex_count": 8,
                        "is_manifold": True,
                        "is_watertight": True
                    }
                else:
                    return {"success": True}
            
            mock_freecad_service.execute_script = mock_execute
            
            with patch('apps.api.app.services.upload_normalization_service.s3_service', mock_s3_service):
                with patch('apps.api.app.services.upload_normalization_service.freecad_service', mock_freecad_service):
                    # Execute concurrent normalizations
                    tasks = [
                        upload_normalization_service.normalize_upload(
                            s3_key=f"uploads/job{i}/model.step",
                            job_id=f"job{i}",
                            config=NormalizationConfig(generate_preview=False)
                        )
                        for i in range(1, 4)
                    ]
                    
                    # Run concurrently (simulated)
                    results = []
                    for task in tasks:
                        results.append(task)
            
            # Verify all succeeded
            assert len(results) == 3
            for result in results:
                assert result.success is True
                assert result.metrics.volume == 1000.0
            
        finally:
            # Cleanup
            for file_path in test_files:
                Path(file_path).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_concurrent_normalization_with_asyncio(self, mock_s3_service, mock_freecad_service):
        """Test true concurrent normalization using asyncio.gather.
        
        This test demonstrates actual concurrent execution of multiple
        normalization tasks using asyncio.gather, following pytest-asyncio
        best practices for concurrent testing.
        """
        import asyncio
        from unittest.mock import AsyncMock
        
        # Create test files
        test_files = []
        for i in range(3):
            with tempfile.NamedTemporaryFile(suffix='.step', delete=False) as tmp:
                tmp.write(f"ISO-10303-21; /* Concurrent test file {i} */".encode())
                test_files.append(tmp.name)
        
        try:
            # Mock S3 operations
            def mock_download(s3_key, local_path):
                # Use different file based on job_id
                job_num = int(s3_key.split('job')[1][0])
                shutil.copy(test_files[job_num - 1], local_path)
                return True
            
            mock_s3_service.download_file = mock_download
            
            # Create thread-safe counter for tracking concurrent calls
            import threading
            call_counter = {'count': 0, 'max_concurrent': 0}
            current_concurrent = {'count': 0}
            lock = threading.Lock()
            
            # Mock FreeCAD operations with concurrency tracking
            def mock_execute(script, timeout=60):
                with lock:
                    current_concurrent['count'] += 1
                    call_counter['count'] += 1
                    call_counter['max_concurrent'] = max(
                        call_counter['max_concurrent'],
                        current_concurrent['count']
                    )
                
                # Simulate some processing time
                time.sleep(0.1)
                
                result = None
                if "newDocument" in script:
                    result = {"success": True, "object_count": 1, "doc_name": f"doc_concurrent_{call_counter['count']}"}
                elif "bbox" in script.lower():
                    result = {
                        "bbox_min": [0, 0, 0],
                        "bbox_max": [10, 10, 10],
                        "volume": 1000.0,
                        "surface_area": 600.0,
                        "edge_count": 12,
                        "vertex_count": 8,
                        "is_manifold": True,
                        "is_watertight": True
                    }
                else:
                    result = {"success": True}
                
                with lock:
                    current_concurrent['count'] -= 1
                
                return result
            
            mock_freecad_service.execute_script = mock_execute
            
            with patch('apps.api.app.services.upload_normalization_service.s3_service', mock_s3_service):
                with patch('apps.api.app.services.upload_normalization_service.freecad_service', mock_freecad_service):
                    # Create async wrapper for normalize_upload if it's synchronous
                    async def async_normalize(s3_key, job_id, config):
                        # Run synchronous function in threadpool to avoid blocking
                        from fastapi.concurrency import run_in_threadpool
                        return await run_in_threadpool(
                            upload_normalization_service.normalize_upload,
                            s3_key=s3_key,
                            job_id=job_id,
                            config=config
                        )
                    
                    # Execute concurrent normalizations using asyncio.gather
                    tasks = [
                        async_normalize(
                            s3_key=f"uploads/job{i}/model.step",
                            job_id=f"job{i}",
                            config=NormalizationConfig(generate_preview=False)
                        )
                        for i in range(1, 4)
                    ]
                    
                    # Run all tasks concurrently
                    results = await asyncio.gather(*tasks)
            
            # Verify all succeeded
            assert len(results) == 3
            for result in results:
                assert result.success is True
                assert result.metrics.volume == 1000.0
            
            # Verify concurrent execution occurred
            assert call_counter['max_concurrent'] > 1, \
                f"Expected concurrent execution, but max concurrent was {call_counter['max_concurrent']}"
            
            logger.info(f"Concurrent test stats: total_calls={call_counter['count']}, "
                       f"max_concurrent={call_counter['max_concurrent']}")
            
        finally:
            # Cleanup
            for file_path in test_files:
                Path(file_path).unlink(missing_ok=True)