"""
Tests for Task 7.10: Metrics extraction and runtime telemetry

This test suite verifies:
- Shape analysis metrics extraction
- Bounding box calculation
- Volume and mass computation
- Triangle count from STL
- Runtime telemetry capture
- Turkish localization
- Error handling and warnings
"""

import json
import locale
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.services.metrics_extractor import (
    MetricsExtractor,
    ModelMetrics,
    ShapeMetrics,
    BoundingBoxMetrics,
    VolumeMetrics,
    MeshMetrics,
    RuntimeTelemetry,
    extract_model_metrics
)
from app.schemas.metrics import (
    ModelMetricsSchema,
    ModelMetricsSummary,
    format_metric_for_display,
    TURKISH_METRIC_LABELS
)


class TestShapeMetrics:
    """Test shape analysis metrics extraction."""
    
    def test_shape_metrics_creation(self):
        """Test creating shape metrics."""
        metrics = ShapeMetrics(
            solids=3,
            faces=18,
            edges=36,
            vertices=24,
            is_closed=True,
            is_valid=True,
            shape_type="solid"
        )
        
        assert metrics.solids == 3
        assert metrics.faces == 18
        assert metrics.is_closed is True
        assert metrics.shape_type == "solid"
    
    def test_shape_metrics_turkish_conversion(self):
        """Test Turkish localization of shape metrics."""
        metrics = ShapeMetrics(
            solids=1,
            faces=6,
            edges=12,
            vertices=8,
            is_closed=True,
            is_valid=True,
            shape_type="solid"
        )
        
        turkish = metrics.to_turkish()
        
        assert turkish["katılar"] == 1
        assert turkish["yüzeyler"] == 6
        assert turkish["kenarlar"] == 12
        assert turkish["köşeler"] == 8
        assert turkish["kapalı"] is True
        assert turkish["geçerli"] is True
        assert turkish["şekil_tipi"] == "solid"


class TestBoundingBoxMetrics:
    """Test bounding box metrics extraction."""
    
    def test_bounding_box_creation(self):
        """Test creating bounding box metrics."""
        metrics = BoundingBoxMetrics(
            width_m=Decimal("0.100"),
            height_m=Decimal("0.050"),
            depth_m=Decimal("0.025"),
            center=[Decimal("0.050"), Decimal("0.025"), Decimal("0.0125")],
            min_point=[Decimal("0"), Decimal("0"), Decimal("0")],
            max_point=[Decimal("0.100"), Decimal("0.050"), Decimal("0.025")],
            diagonal_m=Decimal("0.114564")
        )
        
        assert metrics.width_m == Decimal("0.100")
        assert metrics.height_m == Decimal("0.050")
        assert len(metrics.center) == 3
        assert metrics.diagonal_m == Decimal("0.114564")
    
    def test_bounding_box_turkish_conversion(self):
        """Test Turkish localization of bounding box."""
        metrics = BoundingBoxMetrics(
            width_m=Decimal("0.100"),
            height_m=Decimal("0.050"),
            depth_m=Decimal("0.025"),
            center=[Decimal("0.050"), Decimal("0.025"), Decimal("0.0125")],
            min_point=[Decimal("0"), Decimal("0"), Decimal("0")],
            max_point=[Decimal("0.100"), Decimal("0.050"), Decimal("0.025")],
            diagonal_m=Decimal("0.114564")
        )
        
        turkish = metrics.to_turkish()
        
        assert turkish["genişlik_m"] == 0.100
        assert turkish["yükseklik_m"] == 0.050
        assert turkish["derinlik_m"] == 0.025
        assert turkish["merkez"] == [0.050, 0.025, 0.0125]
        assert turkish["köşegen_m"] == 0.114564


class TestVolumeMetrics:
    """Test volume and mass metrics extraction."""
    
    def test_volume_metrics_creation(self):
        """Test creating volume metrics."""
        metrics = VolumeMetrics(
            volume_m3=Decimal("0.000125"),  # 125 cm³
            surface_area_m2=Decimal("0.015"),
            material_name="aluminum",
            density_kg_m3=Decimal("2700"),
            density_source="database",
            mass_kg=Decimal("0.3375")  # 337.5 grams
        )
        
        assert metrics.volume_m3 == Decimal("0.000125")
        assert metrics.density_kg_m3 == Decimal("2700")
        assert metrics.mass_kg == Decimal("0.3375")
        assert metrics.material_name == "aluminum"
    
    def test_mass_calculation(self):
        """Test mass calculation from volume and density."""
        volume_m3 = Decimal("0.001")  # 1 liter
        density_kg_m3 = Decimal("7850")  # Steel
        
        expected_mass = volume_m3 * density_kg_m3
        assert expected_mass == Decimal("7.850")


class TestMeshMetrics:
    """Test mesh tessellation metrics."""
    
    def test_mesh_metrics_creation(self):
        """Test creating mesh metrics."""
        metrics = MeshMetrics(
            triangle_count=1024,
            vertex_count=514,
            linear_deflection=0.1,
            angular_deflection=0.5,
            relative=False,
            stl_hash="abc123def456"
        )
        
        assert metrics.triangle_count == 1024
        assert metrics.vertex_count == 514
        assert metrics.linear_deflection == 0.1
        assert metrics.angular_deflection == 0.5
        assert metrics.relative is False
    
    def test_mesh_metrics_turkish_conversion(self):
        """Test Turkish localization of mesh metrics."""
        metrics = MeshMetrics(
            triangle_count=1024,
            vertex_count=514,
            stl_hash="abc123def456789"
        )
        
        turkish = metrics.to_turkish()
        
        assert turkish["üçgen_sayısı"] == 1024
        assert turkish["köşe_sayısı"] == 514
        assert turkish["stl_özeti"] == "abc123de"  # First 8 chars


class TestRuntimeTelemetry:
    """Test runtime performance telemetry."""
    
    def test_telemetry_creation(self):
        """Test creating runtime telemetry."""
        telemetry = RuntimeTelemetry(
            duration_ms=1234,
            phase_timings={
                "shape_analysis": 100,
                "bounding_box": 50,
                "volume_calculation": 84
            },
            cpu_user_s=0.234,
            cpu_system_s=0.056,
            cpu_percent_peak=45.6,
            ram_peak_mb=128.5,
            ram_delta_mb=32.0,
            worker_pid=12345,
            worker_hostname="worker-01",
            worker_thread_id=67890,
            queue_name="model"
        )
        
        assert telemetry.duration_ms == 1234
        assert telemetry.phase_timings["shape_analysis"] == 100
        assert telemetry.cpu_percent_peak == 45.6
        assert telemetry.ram_peak_mb == 128.5
        assert telemetry.queue_name == "model"
    
    def test_telemetry_turkish_conversion(self):
        """Test Turkish localization of telemetry."""
        telemetry = RuntimeTelemetry(
            duration_ms=1234,
            cpu_user_s=0.234,
            ram_peak_mb=128.5,
            worker_hostname="worker-01",
            queue_name="model"
        )
        
        turkish = telemetry.to_turkish()
        
        assert turkish["süre_ms"] == 1234
        assert turkish["cpu_kullanıcı_sn"] == 0.234
        assert turkish["bellek_tepe_mb"] == 128.5
        assert turkish["işçi_sunucu"] == "worker-01"
        assert turkish["kuyruk_adı"] == "model"


class TestModelMetrics:
    """Test complete model metrics container."""
    
    def test_model_metrics_creation(self):
        """Test creating complete model metrics."""
        shape = ShapeMetrics(
            solids=1, faces=6, edges=12, vertices=8,
            is_closed=True, is_valid=True, shape_type="solid"
        )
        
        bbox = BoundingBoxMetrics(
            width_m=Decimal("0.1"), height_m=Decimal("0.1"), depth_m=Decimal("0.1"),
            center=[Decimal("0.05"), Decimal("0.05"), Decimal("0.05")],
            min_point=[Decimal("0"), Decimal("0"), Decimal("0")],
            max_point=[Decimal("0.1"), Decimal("0.1"), Decimal("0.1")]
        )
        
        metrics = ModelMetrics(
            shape=shape,
            bounding_box=bbox,
            job_id="job-123",
            request_id="req-456",
            metrics_version="1.0.0"
        )
        
        assert metrics.shape.solids == 1
        assert metrics.bounding_box.width_m == Decimal("0.1")
        assert metrics.job_id == "job-123"
        assert metrics.metrics_version == "1.0.0"
    
    def test_model_metrics_with_warnings(self):
        """Test model metrics with warnings and errors."""
        metrics = ModelMetrics(
            warnings=["Could not extract material properties"],
            errors=["STL export failed"]
        )
        
        assert len(metrics.warnings) == 1
        assert len(metrics.errors) == 1
        assert "material properties" in metrics.warnings[0]


class TestMetricsExtractor:
    """Test the MetricsExtractor class."""
    
    def test_extractor_initialization(self):
        """Test metrics extractor initialization."""
        extractor = MetricsExtractor()
        
        assert extractor.LENGTH_PRECISION == Decimal('1e-9')
        assert extractor.VOLUME_PRECISION == Decimal('1e-12')
        assert extractor.MASS_PRECISION == Decimal('1e-9')
        assert 'steel' in extractor.MATERIAL_DENSITIES
        assert extractor.MATERIAL_DENSITIES['steel'] == Decimal('7850')
    
    def test_phase_timer(self):
        """Test phase timing context manager."""
        extractor = MetricsExtractor()
        extractor.start_telemetry()
        
        import time
        with extractor.phase_timer("test_phase"):
            time.sleep(0.01)  # 10ms
        
        assert "test_phase" in extractor._phase_timers
        assert extractor._phase_timers["test_phase"] >= 10  # At least 10ms
    
    @patch.object(MetricsExtractor, '_extract_shape_metrics')
    @patch.object(MetricsExtractor, '_extract_bounding_box')
    @patch.object(MetricsExtractor, '_extract_volume_metrics')
    @patch.object(MetricsExtractor, '_extract_mesh_metrics')
    @patch.object(MetricsExtractor, '_capture_telemetry')
    def test_extract_metrics_with_mock_methods(self, mock_telemetry, mock_mesh, mock_volume, mock_bbox, mock_shape):
        """Test metrics extraction by mocking individual extraction methods."""
        # Setup mock return values
        mock_shape.return_value = ShapeMetrics(
            solids=2, faces=12, edges=24, vertices=16,
            is_closed=True, is_valid=True, shape_type="solid"
        )
        
        mock_bbox.return_value = BoundingBoxMetrics(
            width_m=Decimal("0.1"), height_m=Decimal("0.05"), depth_m=Decimal("0.025"),
            center=[Decimal("0.05"), Decimal("0.025"), Decimal("0.0125")],
            min_point=[Decimal("0"), Decimal("0"), Decimal("0")],
            max_point=[Decimal("0.1"), Decimal("0.05"), Decimal("0.025")],
            diagonal_m=Decimal("0.114564")
        )
        
        mock_volume.return_value = VolumeMetrics(
            volume_m3=Decimal("0.000125"),
            surface_area_m2=Decimal("0.015"),
            material_name="aluminum",
            density_kg_m3=Decimal("2700"),
            density_source="database",
            mass_kg=Decimal("0.3375")
        )
        
        mock_mesh.return_value = MeshMetrics(
            triangle_count=1024,
            vertex_count=514,
            stl_hash="abc123def456789"
        )
        
        mock_telemetry.return_value = RuntimeTelemetry(
            duration_ms=1234,
            phase_timings={"shape_analysis": 100},
            cpu_user_s=0.234,
            ram_peak_mb=128.5,
            queue_name="model"
        )
        
        # Create extractor and extract metrics
        extractor = MetricsExtractor()
        mock_doc = Mock()
        
        metrics = extractor.extract_metrics(
            document=mock_doc,
            stl_path=Path("/tmp/test.stl"),
            job_id="test-job",
            material="aluminum",
            queue_name="model"
        )
        
        # Verify all methods were called
        mock_shape.assert_called_once_with(mock_doc)
        mock_bbox.assert_called_once_with(mock_doc)
        mock_volume.assert_called_once_with(mock_doc, "aluminum")
        mock_mesh.assert_called_once_with(Path("/tmp/test.stl"))
        mock_telemetry.assert_called_once_with("model")
        
        # Verify the returned metrics
        assert metrics.shape.solids == 2
        assert metrics.bounding_box.width_m == Decimal("0.1")
        assert metrics.volume.material_name == "aluminum"
        assert metrics.mesh.triangle_count == 1024
        assert metrics.telemetry.duration_ms == 1234
        assert metrics.job_id == "test-job"


class TestMetricsSchema:
    """Test Pydantic schemas for metrics."""
    
    def test_model_metrics_schema(self):
        """Test ModelMetricsSchema validation."""
        data = {
            "shape": {
                "solids": 1,
                "faces": 6,
                "edges": 12,
                "vertices": 8,
                "is_closed": True,
                "is_valid": True,
                "shape_type": "solid"
            },
            "bounding_box": {
                "width_m": 0.1,
                "height_m": 0.05,
                "depth_m": 0.025,
                "center": [0.05, 0.025, 0.0125],
                "min_point": [0, 0, 0],
                "max_point": [0.1, 0.05, 0.025]
            },
            "job_id": "job-123",
            "metrics_version": "1.0.0"
        }
        
        schema = ModelMetricsSchema(**data)
        
        assert schema.shape.solids == 1
        assert schema.bounding_box.width_m == 0.1
        assert schema.job_id == "job-123"
    
    def test_metrics_summary_creation(self):
        """Test creating metrics summary from full metrics."""
        full_metrics = ModelMetricsSchema(
            shape={"solids": 2, "faces": 12, "edges": 24, "vertices": 16, 
                   "is_closed": True, "is_valid": True},
            volume={"volume_m3": 0.001, "mass_kg": 2.7},
            mesh={"triangle_count": 1024},
            bounding_box={
                "width_m": 0.1, "height_m": 0.05, "depth_m": 0.025,
                "center": [0.05, 0.025, 0.0125],
                "min_point": [0, 0, 0],
                "max_point": [0.1, 0.05, 0.025]
            }
        )
        
        summary = ModelMetricsSummary.from_full_metrics(full_metrics)
        
        assert summary.solids_count == 2
        assert summary.faces_count == 12
        assert summary.volume_m3 == 0.001
        assert summary.mass_kg == 2.7
        assert summary.triangles_count == 1024
        assert summary.width_mm == 100  # 0.1m = 100mm
        assert summary.height_mm == 50
        assert summary.depth_mm == 25


class TestLocalization:
    """Test Turkish localization features."""
    
    def test_format_metric_for_display_english(self):
        """Test English metric formatting."""
        assert format_metric_for_display(123.456, "en") == "123.456"
        assert format_metric_for_display(True, "en") == "Yes"
        assert format_metric_for_display(False, "en") == "No"
        assert format_metric_for_display(None, "en") == "-"
    
    @patch('app.schemas.metrics.system_locale.setlocale')
    @patch('app.schemas.metrics.system_locale.getlocale')
    def test_format_metric_for_display_turkish(self, mock_getlocale, mock_setlocale):
        """Test Turkish metric formatting with mocked locale."""
        # Mock locale functions to avoid system dependency
        mock_getlocale.return_value = ('en_US', 'UTF-8')
        
        # Test with fallback formatting (when locale setting fails)
        mock_setlocale.side_effect = locale.Error("Locale not available")
        assert format_metric_for_display(123.456, "tr") == "123,456"
        
        # Test boolean formatting (doesn't use locale)
        assert format_metric_for_display(True, "tr") == "Evet"
        assert format_metric_for_display(False, "tr") == "Hayır"
        assert format_metric_for_display(None, "tr") == "-"
    
    def test_turkish_metric_labels(self):
        """Test Turkish metric label mappings."""
        assert TURKISH_METRIC_LABELS["solids"] == "Katılar"
        assert TURKISH_METRIC_LABELS["faces"] == "Yüzeyler"
        assert TURKISH_METRIC_LABELS["edges"] == "Kenarlar"
        assert TURKISH_METRIC_LABELS["volume"] == "Hacim"
        assert TURKISH_METRIC_LABELS["mass"] == "Kütle"
        assert TURKISH_METRIC_LABELS["material"] == "Malzeme"
        assert TURKISH_METRIC_LABELS["density"] == "Yoğunluk"


class TestDeterministicRounding:
    """Test deterministic rounding with Decimal."""
    
    def test_length_rounding(self):
        """Test length rounding to nanometer precision."""
        extractor = MetricsExtractor()
        
        # 1 nanometer precision
        value = Decimal("0.123456789123")
        rounded = value.quantize(extractor.LENGTH_PRECISION, rounding=Decimal.ROUND_HALF_EVEN)
        assert rounded == Decimal("0.123456789")
    
    def test_volume_rounding(self):
        """Test volume rounding to cubic micrometer precision."""
        extractor = MetricsExtractor()
        
        # 1 cubic micrometer precision
        value = Decimal("0.000123456789123456")
        rounded = value.quantize(extractor.VOLUME_PRECISION, rounding=Decimal.ROUND_HALF_EVEN)
        assert rounded == Decimal("0.000123456789")
    
    def test_mass_rounding(self):
        """Test mass rounding to microgram precision."""
        extractor = MetricsExtractor()
        
        # 1 microgram precision
        value = Decimal("1.234567891234")
        rounded = value.quantize(extractor.MASS_PRECISION, rounding=Decimal.ROUND_HALF_EVEN)
        assert rounded == Decimal("1.234567891")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])