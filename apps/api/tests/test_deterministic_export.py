"""
Comprehensive Tests for Task 7.9 Deterministic Export Pipeline

Tests unified export functionality with version pinning and determinism verification.
"""

import hashlib
import json
import os
import tempfile
import time
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from apps.api.app.schemas.export import (
    ExportConfiguration,
    ExportFormat,
    ExportResult,
    ExportStepOptions,
    ExportStlOptions,
    ExportTessellationParams,
    MeshQuality,
    StepSchema,
    StlFormat,
    UnifiedExportResponse,
)


# Mock FreeCAD for testing
class MockFreeCAD:
    """Mock FreeCAD module for testing."""
    
    @staticmethod
    def Version():
        return ["1", "1", "0", "dev", "Git", "branch", "master", "hash"]
    
    @staticmethod
    def newDocument(name):
        return MockDocument(name)
    
    @staticmethod
    def openDocument(path):
        return MockDocument(Path(path).stem)
    
    @staticmethod
    def closeDocument(name):
        pass
    
    class Vector:
        def __init__(self, x=0, y=0, z=0):
            self.x = x
            self.y = y
            self.z = z
    
    class Rotation:
        def __init__(self, yaw=0, pitch=0, roll=0):
            self.yaw = yaw
            self.pitch = pitch
            self.roll = roll
    
    class Placement:
        def __init__(self):
            self.Base = MockFreeCAD.Vector()
            self.Rotation = MockFreeCAD.Rotation()


class MockShape:
    """Mock FreeCAD shape."""
    
    def __init__(self):
        self.isNull_value = False
        self.Volume = 100.0
        self.Area = 50.0
        self.BoundBox = MagicMock()
        self.BoundBox.XMin = 0
        self.BoundBox.XMax = 10
        self.BoundBox.YMin = 0
        self.BoundBox.YMax = 10
        self.BoundBox.ZMin = 0
        self.BoundBox.ZMax = 10
    
    def isNull(self):
        return self.isNull_value
    
    def exportStep(self, path):
        """Mock STEP export."""
        with open(path, 'w') as f:
            f.write("""ISO-10303-21;
HEADER;
FILE_NAME('test.step','2024-01-15T10:30:00',('author'),('org'),'preprocessor','originator','');
FILE_DESCRIPTION(('FreeCAD Model'),'2;1');
FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 3 1 1 }'));
ENDSEC;
DATA;
#1=SHAPE_REPRESENTATION('',(#2),#3);
ENDSEC;
END-ISO-10303-21;""")
    
    def exportStl(self, path):
        """Mock STL export."""
        with open(path, 'wb') as f:
            # Write minimal binary STL
            f.write(b'Binary STL' + b'\0' * 70)  # 80-byte header
            f.write((1).to_bytes(4, 'little'))  # 1 triangle
            f.write(b'\0' * 50)  # Triangle data (50 bytes)


class MockMesh:
    """Mock FreeCAD mesh."""
    
    def __init__(self):
        self.CountFacets = 100
        self.CountPoints = 50
        self.Facets = []
    
    def write(self, path, format):
        """Mock mesh write."""
        with open(path, 'wb') as f:
            # Write minimal binary STL
            f.write(b'Binary STL' + b'\0' * 70)  # 80-byte header
            f.write(self.CountFacets.to_bytes(4, 'little'))
            f.write(b'\0' * (50 * self.CountFacets))  # Triangle data


class MockPart:
    """Mock Part module."""
    
    @staticmethod
    def makeCompound(shapes):
        compound = MockShape()
        compound.Volume = sum(s.Volume for s in shapes)
        return compound
    
    @staticmethod
    def makeBox(length, width, height):
        shape = MockShape()
        shape.Volume = length * width * height
        return shape
    
    Shape = MockShape


class MockMeshModule:
    """Mock Mesh module."""
    
    @staticmethod
    def createFromShape(Shape, LinearDeflection, AngularDeflection, Relative):
        return MockMesh()
    
    Mesh = MockMesh


class MockObject:
    """Mock FreeCAD document object."""
    
    def __init__(self, name, type_id="Part::Feature"):
        self.Label = name
        self.TypeId = type_id
        self.Shape = MockShape()
        self.ViewObject = MagicMock()
        self.ViewObject.Visibility = True
    
    def recompute(self):
        pass


class MockDocument:
    """Mock FreeCAD document."""
    
    def __init__(self, name):
        self.Name = name
        self.Objects = [
            MockObject("Box"),
            MockObject("Cylinder"),
            MockObject("Sphere"),
        ]
    
    def saveAs(self, path):
        """Mock save as FCStd."""
        # Create a minimal ZIP file
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_STORED) as zf:
            # Add Document.xml
            zf.writestr('Document.xml', '<?xml version="1.0"?><Document/>')
            # Add GuiDocument.xml (will be excluded in deterministic export)
            zf.writestr('GuiDocument.xml', '<?xml version="1.0"?><GuiDocument/>')
    
    def recompute(self):
        pass
    
    def addObject(self, type_name, obj_name):
        obj = MockObject(obj_name, type_name)
        self.Objects.append(obj)
        return obj
    
    def getObject(self, name):
        for obj in self.Objects:
            if obj.Label == name:
                return obj
        return None


# Fixtures
@pytest.fixture
def mock_freecad(monkeypatch):
    """Mock FreeCAD modules."""
    import sys
    
    # Add mocks to sys.modules
    sys.modules['FreeCAD'] = MockFreeCAD
    sys.modules['Part'] = MockPart
    sys.modules['Mesh'] = MockMeshModule
    
    # Also patch imports
    monkeypatch.setattr('apps.api.app.services.freecad.deterministic_exporter.FreeCAD', MockFreeCAD, raising=False)
    monkeypatch.setattr('apps.api.app.services.freecad.deterministic_exporter.Part', MockPart, raising=False)
    monkeypatch.setattr('apps.api.app.services.freecad.deterministic_exporter.Mesh', MockMeshModule, raising=False)
    
    yield
    
    # Clean up
    del sys.modules['FreeCAD']
    del sys.modules['Part']
    del sys.modules['Mesh']


@pytest.fixture
def test_document(mock_freecad):
    """Create test FreeCAD document."""
    doc = MockFreeCAD.newDocument("test_doc")
    
    # Add some objects
    box = doc.addObject("Part::Box", "Box")
    cylinder = doc.addObject("Part::Cylinder", "Cylinder")
    
    return doc


@pytest.fixture
def export_config(tmp_path):
    """Create test export configuration."""
    return ExportConfiguration(
        formats=[ExportFormat.STEP, ExportFormat.STL],
        output_directory=str(tmp_path),
        base_name="test_export",
        deterministic_mode=True,
        source_date_epoch=946684800,  # 2000-01-01
        validate_output=True,
    )


# Import after mocking
@pytest.fixture
def unified_exporter(mock_freecad):
    """Create unified exporter instance."""
    from apps.api.app.services.freecad.deterministic_exporter import UnifiedDeterministicExporter
    return UnifiedDeterministicExporter(source_date_epoch=946684800)


class TestUnifiedDeterministicExporter:
    """Test unified deterministic exporter."""
    
    def test_initialization(self, unified_exporter):
        """Test exporter initialization."""
        assert unified_exporter.source_date_epoch == 946684800
        assert unified_exporter.linear_deflection == 0.1
        assert unified_exporter.angular_deflection == 0.5
        assert unified_exporter.step_schema == "AP214"
        assert unified_exporter.enable_validation == True
    
    def test_version_validation(self, unified_exporter):
        """Test dependency version validation."""
        assert unified_exporter.metadata.freecad_version == "1.1.0"
        assert unified_exporter.metadata.python_version is not None
    
    def test_export_fcstd(self, unified_exporter, test_document, tmp_path):
        """Test FCStd export with deterministic repacking."""
        base_path = tmp_path / "test"
        result = unified_exporter._export_fcstd_unified(test_document, base_path)
        
        assert result["format"] == "FCStd"
        assert result["deterministic"] == True
        assert Path(result["path"]).exists()
        assert result["hash"] is not None
        
        # Check ZIP structure
        with zipfile.ZipFile(result["path"], 'r') as zf:
            files = zf.namelist()
            assert "Document.xml" in files
            assert "GuiDocument.xml" not in files  # Should be excluded
            assert not any("thumbnails/" in f for f in files)  # Should be excluded
    
    def test_export_step(self, unified_exporter, test_document, tmp_path):
        """Test STEP export with canonicalization."""
        base_path = tmp_path / "test"
        result = unified_exporter._export_step_unified(test_document, base_path)
        
        assert result["format"] == "STEP"
        assert result["schema"] == "AP214"
        assert result["deterministic"] == True
        assert Path(result["path"]).exists()
        
        # Check STEP content
        with open(result["path"], 'r') as f:
            content = f.read()
            assert "ISO-10303-21" in content
            assert "HEADER" in content
            assert "DATA" in content
            assert "END-ISO-10303-21" in content
            
            # Check canonicalization
            assert "2000-01-01T00:00:00" in content  # Fixed timestamp
    
    def test_export_stl(self, unified_exporter, test_document, tmp_path):
        """Test STL export with fixed mesh parameters."""
        base_path = tmp_path / "test"
        result = unified_exporter._export_stl_unified(test_document, base_path)
        
        assert result["format"] == "STL"
        assert result["deterministic"] == True
        assert Path(result["path"]).exists()
        assert result["facets"] == 100
        assert result["vertices"] == 50
    
    @patch('apps.api.app.services.freecad.deterministic_exporter.trimesh')
    def test_export_glb(self, mock_trimesh, unified_exporter, test_document, tmp_path):
        """Test GLB export via trimesh."""
        # Set trimesh as available
        unified_exporter._trimesh_available = True
        
        # Mock trimesh operations
        mock_mesh = MagicMock()
        mock_mesh.vertices = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
        mock_mesh.faces = [[0, 1, 2]]
        mock_trimesh.load.return_value = mock_mesh
        
        mock_scene = MagicMock()
        mock_scene.export.return_value = b'glTF\x02\x00\x00\x00' + b'\x00' * 100
        mock_trimesh.Scene.return_value = mock_scene
        
        base_path = tmp_path / "test"
        
        # First create STL for GLB to use
        stl_result = unified_exporter._export_stl_unified(test_document, base_path.with_suffix(".tmp"))
        
        result = unified_exporter._export_glb_unified(test_document, base_path)
        
        assert result["format"] == "GLB"
        assert result["deterministic"] == True
        assert Path(result["path"]).exists()
    
    def test_unified_export(self, unified_exporter, test_document, tmp_path):
        """Test unified export to multiple formats."""
        base_path = tmp_path / "test"
        results = unified_exporter.export_unified(
            test_document,
            base_path,
            formats=["FCStd", "STEP", "STL"]
        )
        
        assert "FCStd" in results
        assert "STEP" in results
        assert "STL" in results
        assert "metadata" in results
        
        # Check metadata file
        metadata_path = base_path.with_suffix(".export_metadata.json")
        assert metadata_path.exists()
        
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)
            assert metadata["freecad_version"] == "1.1.0"
            assert "hash_values" in metadata
    
    def test_determinism_verification(self, unified_exporter, test_document, tmp_path):
        """Test that multiple exports produce identical outputs."""
        results = []
        
        for i in range(3):
            base_path = tmp_path / f"test_{i}"
            result = unified_exporter.export_unified(
                test_document,
                base_path,
                formats=["STEP", "STL"],
                validate=False  # Skip validation for speed
            )
            results.append(result)
        
        # Check that all hashes are identical
        for fmt in ["STEP", "STL"]:
            hashes = [r[fmt]["hash"] for r in results if "hash" in r[fmt]]
            assert len(set(hashes)) == 1, f"Non-deterministic output for {fmt}"
    
    def test_float_canonicalization(self, unified_exporter):
        """Test floating point canonicalization."""
        text = "1.2345678901234567890 0.0000000001 1e-10 1.0e+6"
        result = unified_exporter._canonicalize_floats(text)
        
        # Check consistent formatting
        assert "1.2345678901" in result
        assert "0." in result  # Very small numbers become 0
        assert "E" in result or "e" not in result  # Consistent exponent format
    
    def test_xml_cleaning(self, unified_exporter):
        """Test XML content cleaning for determinism."""
        xml_content = b'''<?xml version="1.0"?>
<Document LastModifiedDate="2024-01-15T10:30:00" CreationDate="2024-01-15T10:00:00">
    <ObjectId>12345678-1234-5678-1234-567812345678</ObjectId>
    <Path>C:/Users/username/Documents/model.FCStd</Path>
</Document>'''
        
        cleaned = unified_exporter._clean_xml_content(xml_content)
        cleaned_str = cleaned.decode('utf-8')
        
        # Check timestamp replacement
        assert "2000-01-01T00:00:00" in cleaned_str
        
        # Check UUID replacement
        assert "00000000-0000-0000-0000-000000000000" in cleaned_str
        
        # Check path replacement
        assert "/deterministic/path" in cleaned_str
        assert "C:/Users" not in cleaned_str
    
    def test_step_canonicalization(self, unified_exporter, tmp_path):
        """Test STEP file canonicalization."""
        step_path = tmp_path / "test.step"
        
        # Write test STEP content
        with open(step_path, 'w') as f:
            f.write("""ISO-10303-21;
HEADER;
FILE_NAME('test.step','2024-01-15T10:30:00',('user@company.com'),('org'),'preprocessor','originator','');
FILE_DESCRIPTION(('FreeCAD Model'),'2;1');
FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 3 1 1 }'));
ENDSEC;
DATA;
#1=SHAPE_REPRESENTATION('',(#2),#3);
ENDSEC;
END-ISO-10303-21;""")
        
        unified_exporter._canonicalize_step_file(step_path)
        
        with open(step_path, 'r') as f:
            content = f.read()
            
            # Check replacements
            assert "2000-01-01T00:00:00" in content
            assert "deterministic@export" in content
            assert "user@company.com" not in content
    
    def test_glb_canonicalization(self, unified_exporter):
        """Test GLB data canonicalization."""
        # Create minimal GLB data
        json_data = json.dumps({
            "asset": {
                "generator": "FreeCAD",
                "version": "2.0",
                "copyright": "User"
            },
            "extensionsUsed": ["KHR_materials_unlit", "KHR_texture_transform"]
        })
        
        json_bytes = json_data.encode('utf-8')
        padding = (4 - len(json_bytes) % 4) % 4
        json_bytes += b' ' * padding
        
        glb_data = b'glTF'  # Magic
        glb_data += (2).to_bytes(4, 'little')  # Version
        glb_data += (12 + 8 + len(json_bytes)).to_bytes(4, 'little')  # Length
        glb_data += len(json_bytes).to_bytes(4, 'little')  # JSON chunk length
        glb_data += b'JSON'  # JSON chunk type
        glb_data += json_bytes
        
        result = unified_exporter._canonicalize_glb(glb_data)
        
        # Parse result
        json_start = 20
        json_length = int.from_bytes(result[12:16], 'little')
        result_json = json.loads(result[json_start:json_start+json_length].strip())
        
        assert result_json["asset"]["generator"] == "DeterministicExporter"
        assert "copyright" not in result_json["asset"]
        assert result_json["extensionsUsed"] == sorted(["KHR_materials_unlit", "KHR_texture_transform"])
    
    def test_cache_management(self, unified_exporter):
        """Test shape and hash cache management."""
        # Add some cache entries
        unified_exporter._shape_cache["test1"] = MockShape()
        unified_exporter._hash_cache["test2"] = "abcd1234"
        
        assert len(unified_exporter._shape_cache) == 1
        assert len(unified_exporter._hash_cache) == 1
        
        # Clear caches
        unified_exporter.clear_caches()
        
        assert len(unified_exporter._shape_cache) == 0
        assert len(unified_exporter._hash_cache) == 0
    
    def test_export_validation(self, unified_exporter, tmp_path):
        """Test export file validation."""
        # Create test STEP file
        step_path = tmp_path / "test.step"
        with open(step_path, 'w') as f:
            f.write("ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;")
        
        # Create test result
        result = {
            "path": str(step_path),
            "hash": unified_exporter._compute_file_hash(step_path),
            "size": step_path.stat().st_size
        }
        
        # Should not raise
        unified_exporter._validate_export(result, "STEP")
        
        # Test with non-existent file
        result["path"] = str(tmp_path / "nonexistent.step")
        with pytest.raises(ValueError, match="does not exist"):
            unified_exporter._validate_export(result, "STEP")
        
        # Test with empty file
        empty_path = tmp_path / "empty.step"
        empty_path.touch()
        result["path"] = str(empty_path)
        result["hash"] = unified_exporter._compute_file_hash(empty_path)
        with pytest.raises(ValueError, match="is empty"):
            unified_exporter._validate_export(result, "STEP")
    
    def test_stl_validation(self, unified_exporter, tmp_path):
        """Test STL file validation."""
        # Create binary STL
        stl_path = tmp_path / "test.stl"
        with open(stl_path, 'wb') as f:
            f.write(b'Binary STL' + b'\0' * 70)  # 80-byte header
            f.write((2).to_bytes(4, 'little'))  # 2 triangles
            f.write(b'\0' * 100)  # 2 triangles * 50 bytes
        
        # Should validate successfully
        unified_exporter._validate_stl_export(stl_path)
        
        # Create invalid size STL
        bad_stl = tmp_path / "bad.stl"
        with open(bad_stl, 'wb') as f:
            f.write(b'Binary STL' + b'\0' * 70)  # 80-byte header
            f.write((2).to_bytes(4, 'little'))  # 2 triangles
            f.write(b'\0' * 50)  # Only 1 triangle worth of data
        
        with pytest.raises(ValueError, match="size mismatch"):
            unified_exporter._validate_stl_export(bad_stl)


class TestExportSchemas:
    """Test export Pydantic schemas."""
    
    def test_export_configuration(self, tmp_path):
        """Test export configuration schema."""
        config = ExportConfiguration(
            formats=[ExportFormat.STEP, ExportFormat.STL],
            output_directory=str(tmp_path),
            base_name="test",
            deterministic_mode=True,
        )
        
        assert config.deterministic_mode == True
        assert len(config.formats) == 2
        assert config.random_seed == 42
        assert config.validate_output == True
        
        # Check format options are initialized
        assert config.step_options is not None
        assert config.stl_options is not None
    
    def test_tessellation_params(self):
        """Test tessellation parameter schema."""
        # Test with quality preset
        params = ExportTessellationParams(quality=MeshQuality.HIGH)
        assert params.linear_deflection == 0.01
        assert params.angular_deflection == 0.2
        
        # Test with custom values
        params = ExportTessellationParams(
            quality=MeshQuality.CUSTOM,
            linear_deflection=0.05,
            angular_deflection=0.3
        )
        assert params.linear_deflection == 0.05
        assert params.angular_deflection == 0.3
    
    def test_step_options(self):
        """Test STEP export options."""
        options = ExportStepOptions(
            schema=StepSchema.AP242,
            tolerance=0.01,
            compress=False
        )
        
        assert options.schema == StepSchema.AP242
        assert options.tolerance == 0.01
        assert options.write_surfaces == True
        assert options.write_solids == True
    
    def test_stl_options(self):
        """Test STL export options."""
        options = ExportStlOptions(
            format=StlFormat.BINARY,
            tessellation=ExportTessellationParams(quality=MeshQuality.STANDARD)
        )
        
        assert options.format == StlFormat.BINARY
        assert options.tessellation.linear_deflection == 0.1
        assert options.export_colors == False
    
    def test_export_result(self):
        """Test export result schema."""
        result = ExportResult(
            format=ExportFormat.STEP,
            path="/path/to/file.step",
            size=1024,
            hash="abcd1234",
            deterministic=True,
            schema_version="AP214",
            export_time_ms=100.5
        )
        
        assert result.format == ExportFormat.STEP
        assert result.size == 1024
        assert result.deterministic == True
        assert result.schema_version == "AP214"
    
    def test_unified_response(self):
        """Test unified export response schema."""
        response = UnifiedExportResponse(
            job_id="test-job-123",
            status="success",
            total_time_ms=500.0,
            results={
                "STEP": ExportResult(
                    format=ExportFormat.STEP,
                    path="/path/to/file.step",
                    size=1024,
                    hash="abcd1234",
                    deterministic=True
                ),
                "STL": ExportResult(
                    format=ExportFormat.STL,
                    path="/path/to/file.stl",
                    size=2048,
                    hash="efgh5678",
                    deterministic=True,
                    facet_count=100,
                    vertex_count=50
                )
            }
        )
        
        assert response.success_count == 2
        assert response.failure_count == 0
        assert response.get_result("STEP") is not None
        assert response.get_result(ExportFormat.STL) is not None


class TestDeterministicEnvironment:
    """Test deterministic environment context manager."""
    
    def test_environment_setup(self, mock_freecad):
        """Test deterministic environment setup."""
        from apps.api.app.services.freecad.deterministic_exporter import DeterministicEnvironment
        
        import random
        import locale
        
        # Save original state
        original_random = random.getstate()
        original_locale = locale.getlocale()
        
        with DeterministicEnvironment(seed=12345):
            # Check environment variables
            assert os.environ.get('TZ') == 'UTC'
            assert os.environ.get('OMP_NUM_THREADS') == '1'
            
            # Check random seed
            assert random.randint(0, 1000000) == random.Random(12345).randint(0, 1000000)
        
        # Check restoration
        assert random.getstate() == original_random
        assert os.environ.get('OMP_NUM_THREADS') is None


class TestPublicAPI:
    """Test public API functions."""
    
    def test_export_deterministic(self, mock_freecad, test_document, tmp_path):
        """Test public export_deterministic function."""
        from apps.api.app.services.freecad.deterministic_exporter import export_deterministic
        
        results = export_deterministic(
            document=test_document,
            output_dir=tmp_path,
            formats=["STEP", "STL"],
            job_id="test-123"
        )
        
        assert "STEP" in results
        assert "STL" in results
        assert "metadata" in results
    
    def test_verify_determinism(self, mock_freecad, test_document):
        """Test determinism verification function."""
        from apps.api.app.services.freecad.deterministic_exporter import verify_determinism
        
        # Mock to ensure deterministic output
        with patch('apps.api.app.services.freecad.deterministic_exporter.UnifiedDeterministicExporter.export_unified') as mock_export:
            mock_export.return_value = {
                "STEP": {"hash": "abcd1234", "format": "STEP"},
                "STL": {"hash": "efgh5678", "format": "STL"},
            }
            
            result = verify_determinism(test_document, iterations=3)
            assert result == True
            assert mock_export.call_count == 3
    
    def test_metrics_extraction(self, mock_freecad, test_document, tmp_path):
        """Test metrics extraction functionality."""
        from apps.api.app.services.freecad.deterministic_exporter import UnifiedDeterministicExporter
        
        exporter = UnifiedDeterministicExporter()
        base_path = tmp_path / "test"
        
        # Test with material and queue parameters
        results = exporter.export_unified(
            test_document,
            base_path,
            formats=["STEP"],
            job_id="test-job-123",
            material="aluminum",
            queue_name="model"
        )
        
        # Check that metrics were extracted
        assert "metadata" in results
        assert results["metadata"]["metrics"] is not None
        
        metrics = results["metadata"]["metrics"]
        assert "object_count" in metrics
        assert "face_count" in metrics
        assert "edge_count" in metrics
        assert "vertex_count" in metrics
        assert "volume" in metrics
        assert "surface_area" in metrics
        assert "material_type" in metrics
        assert metrics["material_type"] == "aluminum"
        assert metrics["queue_name"] == "model"
        assert metrics["job_id"] == "test-job-123"
    
    def test_metrics_formatting(self):
        """Test thousands separator formatting in metrics."""
        from apps.api.app.schemas.metrics import JobMetrics
        from decimal import Decimal
        from datetime import datetime, timezone
        
        metrics = JobMetrics(
            object_count=1234567,
            face_count=987654,
            edge_count=2468024,
            vertex_count=1357913,
            volume=Decimal('1234567.890123'),
            surface_area=Decimal('98765.4321'),
            bounding_box_volume=Decimal('5000000.0'),
            export_formats=["STEP", "STL"],
            export_timestamp=datetime.now(timezone.utc),
            export_duration_ms=12345
        )
        
        formatted = metrics.format_large_numbers()
        
        # Test integer formatting with commas
        assert formatted['object_count'] == '1,234,567'
        assert formatted['face_count'] == '987,654'
        assert formatted['edge_count'] == '2,468,024'
        assert formatted['vertex_count'] == '1,357,913'
        
        # Test decimal formatting with commas
        assert formatted['volume'] == '1,234,567.890123'
        assert formatted['surface_area'] == '98,765.4321'
        assert formatted['bounding_box_volume'] == '5,000,000.0'
        assert formatted['export_duration_ms'] == '12,345'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])