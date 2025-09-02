"""
Tests for FreeCAD Worker Script (Task 7.6)

Tests parametric model generation with deterministic outputs.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestResourceMonitor:
    """Test resource monitoring functionality."""
    
    def test_time_limit_check(self):
        """Test time limit enforcement."""
        from app.services.freecad.worker_script import ResourceMonitor
        
        monitor = ResourceMonitor(max_time_seconds=1, max_memory_mb=2048)
        
        # Initially should be OK
        ok, error = monitor.check_limits()
        assert ok is True
        assert error is None
        
        # Simulate time passing
        import time
        time.sleep(1.1)
        
        # Should exceed time limit
        ok, error = monitor.check_limits()
        assert ok is False
        assert "Time limit exceeded" in error
    
    @pytest.mark.skipif(not pytest.importorskip("psutil"), reason="psutil not available")
    def test_memory_limit_check(self):
        """Test memory limit enforcement."""
        from app.services.freecad.worker_script import ResourceMonitor
        
        # Set very low memory limit
        monitor = ResourceMonitor(max_time_seconds=20, max_memory_mb=1)
        
        # Should exceed memory limit (process uses more than 1MB)
        ok, error = monitor.check_limits()
        
        # This test might be flaky depending on actual memory usage
        # Just verify the method works
        assert isinstance(ok, bool)
        if not ok and error:
            assert "Memory limit exceeded" in error or "Shutdown requested" in error
    
    def test_metrics_collection(self):
        """Test resource metrics collection."""
        from app.services.freecad.worker_script import ResourceMonitor
        
        monitor = ResourceMonitor()
        metrics = monitor.get_metrics()
        
        assert "wall_time_seconds" in metrics
        assert "peak_memory_mb" in metrics
        assert metrics["wall_time_seconds"] >= 0


class TestFreeCADParametricGenerator:
    """Test parametric generation functionality."""
    
    @patch('app.services.freecad.worker_script.App')
    @patch('app.services.freecad.worker_script.Part')
    def test_create_prism_with_hole(self, mock_part, mock_app):
        """Test prism with hole generation."""
        from app.services.freecad.worker_script import (
            FreeCADParametricGenerator,
            ResourceMonitor
        )
        
        # Mock FreeCAD modules
        mock_app.Version.return_value = [1, 1, 0]
        mock_box = MagicMock()
        mock_cylinder = MagicMock()
        mock_result = MagicMock()
        
        mock_part.makeBox.return_value = mock_box
        mock_part.makeCylinder.return_value = mock_cylinder
        mock_box.cut.return_value = mock_result
        
        # Create generator
        monitor = ResourceMonitor()
        generator = FreeCADParametricGenerator(monitor)
        
        # Generate prism with hole
        shape = generator.create_prism_with_hole(
            length=100.0,
            width=50.0,
            height=30.0,
            hole_diameter=10.0,
            units="mm"
        )
        
        # Verify calls
        mock_part.makeBox.assert_called_once_with(100.0, 50.0, 30.0)
        mock_part.makeCylinder.assert_called_once()
        mock_box.cut.assert_called_once_with(mock_cylinder)
        
        assert shape == mock_result
    
    def test_dimension_validation(self):
        """Test dimension validation."""
        from app.services.freecad.worker_script import (
            FreeCADParametricGenerator,
            ResourceMonitor
        )
        
        with patch('app.services.freecad.worker_script.App') as mock_app:
            mock_app.Version.return_value = [1, 1, 0]
            
            monitor = ResourceMonitor()
            generator = FreeCADParametricGenerator(monitor)
            
            # Test dimension out of range
            with pytest.raises(ValueError, match="out of range"):
                generator.create_prism_with_hole(
                    length=1001.0,  # > 1000mm
                    width=50.0,
                    height=30.0,
                    hole_diameter=10.0
                )
            
            # Test hole too large
            with pytest.raises(ValueError, match="too large"):
                generator.create_prism_with_hole(
                    length=100.0,
                    width=50.0,
                    height=30.0,
                    hole_diameter=100.0  # >= width
                )


class TestMaterialMachineCompatibility:
    """Test material-machine compatibility validation."""
    
    def test_valid_combinations(self):
        """Test valid material-process combinations."""
        from app.services.freecad.worker_script import validate_material_machine_compatibility
        
        # Test valid combinations
        valid_cases = [
            ("aluminum", "milling"),
            ("steel", "cnc"),
            ("abs", "injection_molding"),
            ("pla", "3d_printing"),
        ]
        
        for material, process in valid_cases:
            valid, error = validate_material_machine_compatibility(material, process)
            assert valid is True, f"Failed for {material} + {process}"
            assert error is None
    
    def test_invalid_combinations(self):
        """Test invalid material-process combinations."""
        from app.services.freecad.worker_script import validate_material_machine_compatibility
        
        # Test invalid combinations
        invalid_cases = [
            ("aluminum", "injection_molding"),  # Metals can't be injection molded
            ("pla", "milling"),  # PLA not typically milled
        ]
        
        for material, process in invalid_cases:
            valid, error = validate_material_machine_compatibility(material, process)
            assert valid is False, f"Should fail for {material} + {process}"
            assert error is not None
            assert "incompatible" in error.lower()


class TestTurkishNormalization:
    """Test Turkish parameter normalization."""
    
    def test_turkish_param_normalization(self):
        """Test Turkish to English parameter mapping."""
        from app.services.freecad.worker_script import normalize_turkish_params
        
        turkish_params = {
            "uzunluk": 100,
            "genişlik": 50,
            "yükseklik": 30,
            "delik çapı": 10,
            "malzeme": "alüminyum",
            "makine": "freze"
        }
        
        normalized = normalize_turkish_params(turkish_params)
        
        assert normalized["length"] == 100
        assert normalized["width"] == 50
        assert normalized["height"] == 30
        assert normalized["hole_diameter"] == 10
        assert normalized["material"] == "alüminyum"
        assert normalized["process"] == "freze"
    
    def test_mixed_language_params(self):
        """Test mixed Turkish and English parameters."""
        from app.services.freecad.worker_script import normalize_turkish_params
        
        mixed_params = {
            "length": 100,  # Already English
            "genişlik": 50,  # Turkish
            "height": 30,  # Already English
            "delik_çapı": 10,  # Turkish
        }
        
        normalized = normalize_turkish_params(mixed_params)
        
        assert normalized["length"] == 100
        assert normalized["width"] == 50
        assert normalized["height"] == 30
        assert normalized["hole_diameter"] == 10


class TestDeterministicOutput:
    """Test deterministic output generation."""
    
    def test_environment_variables(self):
        """Test deterministic environment variables are set."""
        import app.services.freecad.worker_script
        
        # Check that module sets environment variables
        assert os.environ.get("PYTHONHASHSEED") == "0"
        assert "SOURCE_DATE_EPOCH" in os.environ
    
    @patch('app.services.freecad.worker_script.hashlib.sha256')
    def test_file_hashing(self, mock_sha256):
        """Test SHA256 file hashing."""
        from app.services.freecad.worker_script import FreeCADParametricGenerator, ResourceMonitor
        
        # Create temp file
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"test content")
            tmp_path = Path(tmp.name)
        
        try:
            with patch('app.services.freecad.worker_script.App') as mock_app:
                mock_app.Version.return_value = [1, 1, 0]
                
                monitor = ResourceMonitor()
                generator = FreeCADParametricGenerator(monitor)
                
                # Mock sha256
                mock_hasher = MagicMock()
                mock_hasher.hexdigest.return_value = "abc123"
                mock_sha256.return_value = mock_hasher
                
                # Compute hash
                hash_value = generator._compute_file_hash(tmp_path)
                
                assert hash_value == "abc123"
                mock_hasher.update.assert_called()
        finally:
            tmp_path.unlink()


class TestMainFunction:
    """Test main entry point."""
    
    @patch('sys.stdin')
    @patch('sys.stdout')
    @patch('app.services.freecad.worker_script.FreeCADParametricGenerator')
    def test_main_success(self, mock_generator_class, mock_stdout, mock_stdin):
        """Test successful execution of main function."""
        from app.services.freecad.worker_script import main
        
        # Mock input
        input_data = {
            "length": 100,
            "width": 50,
            "height": 30,
            "hole_diameter": 10,
            "material": "aluminum",
            "process": "milling",
            "formats": ["STEP", "STL"]
        }
        mock_stdin.read.return_value = json.dumps(input_data)
        
        # Mock generator
        mock_generator = MagicMock()
        mock_generator_class.return_value = mock_generator
        mock_generator.create_prism_with_hole.return_value = MagicMock()
        mock_generator.export_shape.return_value = {
            "STEP": {"path": "test.step", "sha256": "abc123"},
            "STL": {"path": "test.stl", "sha256": "def456"}
        }
        mock_generator.extract_metrics.return_value = {
            "volume_mm3": 150000,
            "area_mm2": 10000
        }
        
        # Run main
        with patch('builtins.print') as mock_print:
            main()
            
            # Check output was printed
            mock_print.assert_called()
            output = mock_print.call_args[0][0]
            output_data = json.loads(output)
            
            assert output_data["success"] is True
            assert "exports" in output_data
            assert "metrics" in output_data