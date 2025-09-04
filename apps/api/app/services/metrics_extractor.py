"""
Ultra-Enterprise Metrics Extraction Service for Task 7.10

This module provides comprehensive metrics extraction from FreeCAD models including:
- Shape analysis: solids, faces, edges from TopoShape
- Bounding box: dimensions, center, min/max arrays
- Volume calculation for closed shapes
- Triangle count from STL meshes
- Material properties and density resolution
- Mass calculation when volume and density available
- Runtime telemetry: CPU/memory monitoring with psutil
- Deterministic rounding with Decimal for reproducibility
- Turkish localization support

Author: Task 7.10 Implementation
Date: 2025
"""

from __future__ import annotations

import hashlib
import json
import os
import resource
import struct
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field, ConfigDict

from ..core.logging import get_logger
from ..core.metrics import freecad_operation_duration_seconds
from ..core.telemetry import create_span
from ..middleware.correlation_middleware import get_correlation_id

logger = get_logger(__name__)

# Try to import psutil for runtime telemetry
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil not available, runtime telemetry will be limited")


class ShapeMetrics(BaseModel):
    """Shape analysis metrics from FreeCAD TopoShape."""
    
    model_config = ConfigDict(validate_assignment=True)
    
    # Topology counts
    solids: int = Field(description="Number of solid shapes")
    faces: int = Field(description="Number of faces")
    edges: int = Field(description="Number of edges")
    vertices: int = Field(description="Number of vertices")
    
    # Closure status
    is_closed: bool = Field(description="Whether shape is closed")
    is_valid: bool = Field(description="Whether shape is topologically valid")
    
    # Shape type
    shape_type: Optional[str] = Field(default=None, description="Primary shape type")
    
    def to_turkish(self) -> Dict[str, Any]:
        """Convert to Turkish localized format."""
        return {
            "katılar": self.solids,
            "yüzeyler": self.faces,
            "kenarlar": self.edges,
            "köşeler": self.vertices,
            "kapalı": self.is_closed,
            "geçerli": self.is_valid,
            "şekil_tipi": self.shape_type
        }


class BoundingBoxMetrics(BaseModel):
    """Bounding box metrics with dimensional information."""
    
    model_config = ConfigDict(validate_assignment=True)
    
    # Dimensions in SI units (meters)
    width_m: Decimal = Field(description="Width (X dimension) in meters")
    height_m: Decimal = Field(description="Height (Y dimension) in meters")
    depth_m: Decimal = Field(description="Depth (Z dimension) in meters")
    
    # Center point
    center: List[Decimal] = Field(description="Center point [x, y, z] in meters")
    
    # Bounds
    min_point: List[Decimal] = Field(description="Minimum corner [x, y, z] in meters")
    max_point: List[Decimal] = Field(description="Maximum corner [x, y, z] in meters")
    
    # Diagonal length
    diagonal_m: Optional[Decimal] = Field(default=None, description="Diagonal length in meters")
    
    def to_turkish(self) -> Dict[str, Any]:
        """Convert to Turkish localized format."""
        return {
            "genişlik_m": float(self.width_m),
            "yükseklik_m": float(self.height_m),
            "derinlik_m": float(self.depth_m),
            "merkez": [float(x) for x in self.center],
            "min_nokta": [float(x) for x in self.min_point],
            "maks_nokta": [float(x) for x in self.max_point],
            "köşegen_m": float(self.diagonal_m) if self.diagonal_m else None
        }


class VolumeMetrics(BaseModel):
    """Volume and mass calculation metrics."""
    
    model_config = ConfigDict(validate_assignment=True)
    
    # Volume in SI units (cubic meters)
    volume_m3: Optional[Decimal] = Field(default=None, description="Volume in cubic meters")
    
    # Surface area
    surface_area_m2: Optional[Decimal] = Field(default=None, description="Surface area in square meters")
    
    # Material properties
    material_name: Optional[str] = Field(default=None, description="Material name")
    density_kg_m3: Optional[Decimal] = Field(default=None, description="Density in kg/m³")
    density_source: Optional[str] = Field(default=None, description="Source of density value")
    
    # Mass calculation
    mass_kg: Optional[Decimal] = Field(default=None, description="Mass in kilograms")
    
    def to_turkish(self) -> Dict[str, Any]:
        """Convert to Turkish localized format."""
        return {
            "hacim_m3": float(self.volume_m3) if self.volume_m3 else None,
            "yüzey_alanı_m2": float(self.surface_area_m2) if self.surface_area_m2 else None,
            "malzeme": self.material_name,
            "yoğunluk_kg_m3": float(self.density_kg_m3) if self.density_kg_m3 else None,
            "yoğunluk_kaynağı": self.density_source,
            "kütle_kg": float(self.mass_kg) if self.mass_kg else None
        }


class MeshMetrics(BaseModel):
    """Mesh and tessellation metrics."""
    
    model_config = ConfigDict(validate_assignment=True)
    
    # Triangle count
    triangle_count: Optional[int] = Field(default=None, description="Number of triangles in mesh")
    vertex_count: Optional[int] = Field(default=None, description="Number of vertices in mesh")
    
    # STL parameters used
    linear_deflection: Optional[float] = Field(default=None, description="Linear deflection used")
    angular_deflection: Optional[float] = Field(default=None, description="Angular deflection used")
    relative: Optional[bool] = Field(default=None, description="Whether relative deflection was used")
    
    # STL file hash for traceability
    stl_hash: Optional[str] = Field(default=None, description="SHA256 hash of STL file")
    
    def to_turkish(self) -> Dict[str, Any]:
        """Convert to Turkish localized format."""
        return {
            "üçgen_sayısı": self.triangle_count,
            "köşe_sayısı": self.vertex_count,
            "doğrusal_sapma": self.linear_deflection,
            "açısal_sapma": self.angular_deflection,
            "göreli": self.relative,
            "stl_özeti": self.stl_hash[:8] if self.stl_hash else None
        }


class RuntimeTelemetry(BaseModel):
    """Runtime performance telemetry."""
    
    model_config = ConfigDict(validate_assignment=True)
    
    # Timing
    duration_ms: int = Field(description="Total duration in milliseconds")
    phase_timings: Optional[Dict[str, int]] = Field(default=None, description="Per-phase timings in ms")
    
    # CPU usage
    cpu_user_s: Optional[float] = Field(default=None, description="User CPU time in seconds")
    cpu_system_s: Optional[float] = Field(default=None, description="System CPU time in seconds")
    cpu_percent_peak: Optional[float] = Field(default=None, description="Peak CPU usage percentage")
    
    # Memory usage
    ram_peak_mb: Optional[float] = Field(default=None, description="Peak RAM usage in MB")
    ram_delta_mb: Optional[float] = Field(default=None, description="Memory delta in MB")
    
    # Worker metadata
    worker_pid: Optional[int] = Field(default=None, description="Process ID")
    worker_hostname: Optional[str] = Field(default=None, description="Worker hostname")
    worker_thread_id: Optional[int] = Field(default=None, description="Thread ID")
    queue_name: Optional[str] = Field(default=None, description="Queue name")
    
    def to_turkish(self) -> Dict[str, Any]:
        """Convert to Turkish localized format."""
        return {
            "süre_ms": self.duration_ms,
            "faz_süreleri": self.phase_timings,
            "cpu_kullanıcı_sn": self.cpu_user_s,
            "cpu_sistem_sn": self.cpu_system_s,
            "cpu_tepe_yüzde": self.cpu_percent_peak,
            "bellek_tepe_mb": self.ram_peak_mb,
            "bellek_delta_mb": self.ram_delta_mb,
            "işçi_pid": self.worker_pid,
            "işçi_sunucu": self.worker_hostname,
            "iş_parçacığı_id": self.worker_thread_id,
            "kuyruk_adı": self.queue_name
        }


class ModelMetrics(BaseModel):
    """Complete model metrics container."""
    
    model_config = ConfigDict(validate_assignment=True)
    
    # Core metrics
    shape: Optional[ShapeMetrics] = Field(default=None, description="Shape analysis")
    bounding_box: Optional[BoundingBoxMetrics] = Field(default=None, description="Bounding box")
    volume: Optional[VolumeMetrics] = Field(default=None, description="Volume and mass")
    mesh: Optional[MeshMetrics] = Field(default=None, description="Mesh metrics")
    
    # Runtime telemetry
    telemetry: Optional[RuntimeTelemetry] = Field(default=None, description="Runtime telemetry")
    
    # Metadata
    metrics_version: str = Field(default="1.0.0", description="Metrics schema version")
    request_id: Optional[str] = Field(default=None, description="Request correlation ID")
    job_id: Optional[str] = Field(default=None, description="Job identifier")
    timestamp: Optional[str] = Field(default=None, description="Extraction timestamp")
    
    # Warnings and errors
    warnings: List[str] = Field(default_factory=list, description="Non-fatal warnings")
    errors: List[str] = Field(default_factory=list, description="Extraction errors")
    
    def to_turkish(self) -> Dict[str, Any]:
        """Convert to Turkish localized format."""
        result = {
            "şekil": self.shape.to_turkish() if self.shape else None,
            "sınır_kutusu": self.bounding_box.to_turkish() if self.bounding_box else None,
            "hacim": self.volume.to_turkish() if self.volume else None,
            "ağ": self.mesh.to_turkish() if self.mesh else None,
            "telemetri": self.telemetry.to_turkish() if self.telemetry else None,
            "metrik_sürümü": self.metrics_version,
            "istek_id": self.request_id,
            "iş_id": self.job_id,
            "zaman_damgası": self.timestamp,
            "uyarılar": self.warnings,
            "hatalar": self.errors
        }
        return result


class MetricsExtractor:
    """
    Comprehensive metrics extraction from FreeCAD models.
    
    Features:
    - Shape topology analysis
    - Bounding box computation
    - Volume and mass calculation
    - STL triangle counting
    - Runtime telemetry capture
    - Deterministic rounding
    - Error recovery
    """
    
    # Rounding precision for deterministic output
    LENGTH_PRECISION = Decimal('1e-9')  # 1 nanometer
    VOLUME_PRECISION = Decimal('1e-12')  # 1 cubic micrometer
    MASS_PRECISION = Decimal('1e-9')  # 1 microgram
    
    # Material density database (kg/m³)
    MATERIAL_DENSITIES = {
        'steel': Decimal('7850'),
        'aluminum': Decimal('2700'),
        'copper': Decimal('8960'),
        'brass': Decimal('8500'),
        'titanium': Decimal('4500'),
        'plastic': Decimal('1200'),
        'pla': Decimal('1250'),
        'abs': Decimal('1050'),
        'wood': Decimal('700'),
        'glass': Decimal('2500'),
        'concrete': Decimal('2400'),
    }
    
    def __init__(self):
        """Initialize metrics extractor."""
        self.logger = logger
        self._runtime_start = None
        self._phase_timers = {}
        self._cpu_start = None
        self._memory_start = None
        self._process = None
        
        # Initialize process monitoring if available
        if PSUTIL_AVAILABLE:
            try:
                self._process = psutil.Process()
            except Exception as e:
                logger.warning(f"Could not initialize process monitoring: {e}")
    
    @contextmanager
    def phase_timer(self, phase_name: str):
        """Context manager for timing individual phases."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            self._phase_timers[phase_name] = elapsed_ms
    
    def start_telemetry(self):
        """Start runtime telemetry capture."""
        self._runtime_start = time.perf_counter()
        self._phase_timers.clear()
        
        # Capture CPU start
        try:
            rusage = resource.getrusage(resource.RUSAGE_SELF)
            self._cpu_start = {
                'user': rusage.ru_utime,
                'system': rusage.ru_stime
            }
        except Exception:
            self._cpu_start = None
        
        # Capture memory start
        if self._process:
            try:
                self._memory_start = self._process.memory_info().rss / (1024 * 1024)  # MB
            except Exception:
                self._memory_start = None
    
    def extract_metrics(
        self,
        document: Any,
        stl_path: Optional[Path] = None,
        job_id: Optional[str] = None,
        material: Optional[str] = None,
        queue_name: Optional[str] = None
    ) -> ModelMetrics:
        """
        Extract comprehensive metrics from FreeCAD document.
        
        Args:
            document: FreeCAD document or shape
            stl_path: Optional path to STL file for triangle counting
            job_id: Job identifier
            material: Material name for density lookup
            queue_name: Queue name for telemetry
        
        Returns:
            ModelMetrics with all available metrics
        """
        correlation_id = get_correlation_id()
        
        with create_span("metrics_extraction", correlation_id=correlation_id) as span:
            if job_id:
                span.set_attribute("job_id", job_id)
            
            # Start telemetry
            self.start_telemetry()
            
            # Initialize metrics container
            metrics = ModelMetrics(
                job_id=job_id,
                request_id=correlation_id,
                timestamp=datetime.now(timezone.utc).isoformat()
            )
            
            # Extract shape metrics
            with self.phase_timer("shape_analysis"):
                try:
                    shape_metrics = self._extract_shape_metrics(document)
                    metrics.shape = shape_metrics
                except Exception as e:
                    logger.warning(f"Could not extract shape metrics: {e}")
                    metrics.warnings.append(f"Shape analysis failed: {str(e)}")
            
            # Extract bounding box
            with self.phase_timer("bounding_box"):
                try:
                    bbox_metrics = self._extract_bounding_box(document)
                    metrics.bounding_box = bbox_metrics
                except Exception as e:
                    logger.warning(f"Could not extract bounding box: {e}")
                    metrics.warnings.append(f"Bounding box failed: {str(e)}")
            
            # Extract volume and mass
            with self.phase_timer("volume_calculation"):
                try:
                    volume_metrics = self._extract_volume_metrics(document, material)
                    metrics.volume = volume_metrics
                except Exception as e:
                    logger.warning(f"Could not extract volume metrics: {e}")
                    metrics.warnings.append(f"Volume calculation failed: {str(e)}")
            
            # Extract mesh metrics
            if stl_path:
                with self.phase_timer("mesh_analysis"):
                    try:
                        mesh_metrics = self._extract_mesh_metrics(stl_path)
                        metrics.mesh = mesh_metrics
                    except Exception as e:
                        logger.warning(f"Could not extract mesh metrics: {e}")
                        metrics.warnings.append(f"Mesh analysis failed: {str(e)}")
            
            # Capture runtime telemetry
            telemetry = self._capture_telemetry(queue_name)
            metrics.telemetry = telemetry
            
            # Log summary
            logger.info(
                "metrics_extraction_complete",
                job_id=job_id,
                duration_ms=telemetry.duration_ms if telemetry else 0,
                shape_valid=metrics.shape.is_valid if metrics.shape else False,
                volume_m3=float(metrics.volume.volume_m3) if metrics.volume and metrics.volume.volume_m3 else None,
                triangles=metrics.mesh.triangle_count if metrics.mesh else None,
                warnings=len(metrics.warnings),
                correlation_id=correlation_id
            )
            
            return metrics
    
    def _extract_shape_metrics(self, document: Any) -> ShapeMetrics:
        """Extract shape topology metrics."""
        try:
            import FreeCAD
            import Part
            
            # Get all shapes from document
            shapes = []
            if hasattr(document, 'Objects'):
                # It's a document
                for obj in document.Objects:
                    if hasattr(obj, 'Shape') and obj.Shape and not obj.Shape.isNull():
                        shapes.append(obj.Shape)
            elif hasattr(document, 'Solids'):
                # It's already a shape
                shapes = [document]
            else:
                raise ValueError("No valid shapes found in document")
            
            if not shapes:
                raise ValueError("No shapes to analyze")
            
            # Create compound if multiple shapes
            if len(shapes) == 1:
                shape = shapes[0]
            else:
                shape = Part.makeCompound(shapes)
            
            # Analyze topology
            metrics = ShapeMetrics(
                solids=len(shape.Solids),
                faces=len(shape.Faces),
                edges=len(shape.Edges),
                vertices=len(shape.Vertexes),
                is_closed=shape.isClosed() if hasattr(shape, 'isClosed') else False,
                is_valid=shape.isValid() if hasattr(shape, 'isValid') else True
            )
            
            # Determine shape type
            if shape.Solids:
                metrics.shape_type = "solid"
            elif shape.Shells:
                metrics.shape_type = "shell"
            elif shape.Faces:
                metrics.shape_type = "face"
            elif shape.Wires:
                metrics.shape_type = "wire"
            elif shape.Edges:
                metrics.shape_type = "edge"
            else:
                metrics.shape_type = "vertex"
            
            return metrics
            
        except Exception as e:
            logger.error(f"Shape metrics extraction failed: {e}")
            raise
    
    def _extract_bounding_box(self, document: Any) -> BoundingBoxMetrics:
        """Extract bounding box metrics."""
        try:
            import FreeCAD
            import Part
            
            # Get bounding box
            if hasattr(document, 'Objects'):
                # Document - get overall bounding box
                bbox = FreeCAD.BoundBox()
                for obj in document.Objects:
                    if hasattr(obj, 'Shape') and obj.Shape and not obj.Shape.isNull():
                        bbox.add(obj.Shape.BoundBox)
            elif hasattr(document, 'BoundBox'):
                # Shape
                bbox = document.BoundBox
            else:
                raise ValueError("Cannot extract bounding box")
            
            # Convert to SI units (meters) with deterministic rounding
            def to_decimal_meters(value_mm: float) -> Decimal:
                """Convert mm to meters with deterministic rounding."""
                value_m = Decimal(str(value_mm)) / Decimal('1000')
                return value_m.quantize(self.LENGTH_PRECISION, rounding=ROUND_HALF_EVEN)
            
            width_m = to_decimal_meters(bbox.XLength)
            height_m = to_decimal_meters(bbox.YLength)
            depth_m = to_decimal_meters(bbox.ZLength)
            
            # Calculate diagonal
            diagonal_m = (width_m**2 + height_m**2 + depth_m**2).sqrt()
            diagonal_m = diagonal_m.quantize(self.LENGTH_PRECISION, rounding=ROUND_HALF_EVEN)
            
            # Get center and bounds
            center = [
                to_decimal_meters(bbox.Center.x),
                to_decimal_meters(bbox.Center.y),
                to_decimal_meters(bbox.Center.z)
            ]
            
            min_point = [
                to_decimal_meters(bbox.XMin),
                to_decimal_meters(bbox.YMin),
                to_decimal_meters(bbox.ZMin)
            ]
            
            max_point = [
                to_decimal_meters(bbox.XMax),
                to_decimal_meters(bbox.YMax),
                to_decimal_meters(bbox.ZMax)
            ]
            
            return BoundingBoxMetrics(
                width_m=width_m,
                height_m=height_m,
                depth_m=depth_m,
                center=center,
                min_point=min_point,
                max_point=max_point,
                diagonal_m=diagonal_m
            )
            
        except Exception as e:
            logger.error(f"Bounding box extraction failed: {e}")
            raise
    
    def _extract_volume_metrics(self, document: Any, material: Optional[str] = None) -> VolumeMetrics:
        """Extract volume and mass metrics."""
        try:
            import FreeCAD
            import Part
            
            metrics = VolumeMetrics()
            
            # Get shape
            if hasattr(document, 'Objects'):
                shapes = []
                for obj in document.Objects:
                    if hasattr(obj, 'Shape') and obj.Shape and not obj.Shape.isNull():
                        shapes.append(obj.Shape)
                        # Check for material property
                        if not material and hasattr(obj, 'Material'):
                            material = str(obj.Material)
                
                if shapes:
                    shape = Part.makeCompound(shapes) if len(shapes) > 1 else shapes[0]
                else:
                    return metrics
            elif hasattr(document, 'Volume'):
                shape = document
            else:
                return metrics
            
            # Calculate volume if shape has solids or is closed
            if shape.Solids or (hasattr(shape, 'isClosed') and shape.isClosed()):
                # Volume in mm³, convert to m³
                if shape.Solids:
                    volume_mm3 = sum(solid.Volume for solid in shape.Solids)
                else:
                    volume_mm3 = shape.Volume
                
                volume_m3 = Decimal(str(volume_mm3)) / Decimal('1e9')
                metrics.volume_m3 = volume_m3.quantize(self.VOLUME_PRECISION, rounding=ROUND_HALF_EVEN)
                
                # Surface area
                if hasattr(shape, 'Area'):
                    area_mm2 = shape.Area
                    area_m2 = Decimal(str(area_mm2)) / Decimal('1e6')
                    metrics.surface_area_m2 = area_m2.quantize(self.LENGTH_PRECISION, rounding=ROUND_HALF_EVEN)
            
            # Resolve material density
            if material:
                metrics.material_name = material
                material_lower = material.lower()
                
                # Check material database
                for mat_name, density in self.MATERIAL_DENSITIES.items():
                    if mat_name in material_lower:
                        metrics.density_kg_m3 = density
                        metrics.density_source = "database"
                        break
                
                # Calculate mass if we have volume and density
                if metrics.volume_m3 and metrics.density_kg_m3:
                    mass_kg = metrics.volume_m3 * metrics.density_kg_m3
                    metrics.mass_kg = mass_kg.quantize(self.MASS_PRECISION, rounding=ROUND_HALF_EVEN)
            
            return metrics
            
        except Exception as e:
            logger.error(f"Volume metrics extraction failed: {e}")
            raise
    
    def _extract_mesh_metrics(self, stl_path: Path) -> MeshMetrics:
        """Extract mesh metrics from STL file."""
        try:
            metrics = MeshMetrics()
            
            if not stl_path.exists():
                raise FileNotFoundError(f"STL file not found: {stl_path}")
            
            # Check if binary or ASCII STL
            with open(stl_path, 'rb') as f:
                header = f.read(80)
                
                # ASCII STL starts with "solid"
                if header.startswith(b'solid'):
                    # ASCII STL - count lines
                    with open(stl_path, 'r') as ascii_f:
                        lines = ascii_f.readlines()
                        facet_lines = [l for l in lines if 'facet normal' in l]
                        metrics.triangle_count = len(facet_lines)
                else:
                    # Binary STL - read triangle count from header
                    f.seek(80)
                    triangle_count_bytes = f.read(4)
                    metrics.triangle_count = struct.unpack('<I', triangle_count_bytes)[0]
            
            # Compute file hash for traceability
            sha256 = hashlib.sha256()
            with open(stl_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    sha256.update(chunk)
            metrics.stl_hash = sha256.hexdigest()
            
            # Try to load with FreeCAD Mesh module for more details
            try:
                import Mesh
                mesh = Mesh.Mesh(str(stl_path))
                metrics.vertex_count = mesh.CountPoints
                
                # Verify triangle count
                if metrics.triangle_count != mesh.CountFacets:
                    logger.warning(
                        f"Triangle count mismatch: header={metrics.triangle_count}, "
                        f"mesh={mesh.CountFacets}"
                    )
                    metrics.triangle_count = mesh.CountFacets
            except Exception as e:
                logger.debug(f"Could not load STL with Mesh module: {e}")
            
            return metrics
            
        except Exception as e:
            logger.error(f"Mesh metrics extraction failed: {e}")
            raise
    
    def _capture_telemetry(self, queue_name: Optional[str] = None) -> RuntimeTelemetry:
        """Capture runtime telemetry."""
        telemetry = RuntimeTelemetry(
            duration_ms=int((time.perf_counter() - self._runtime_start) * 1000) if self._runtime_start else 0,
            phase_timings=self._phase_timers.copy() if self._phase_timers else None,
            queue_name=queue_name
        )
        
        # Get worker metadata
        telemetry.worker_pid = os.getpid()
        telemetry.worker_hostname = os.environ.get('HOSTNAME', 'unknown')
        try:
            import threading
            telemetry.worker_thread_id = threading.current_thread().ident
        except Exception:
            pass
        
        # Capture CPU metrics
        if self._cpu_start:
            try:
                rusage = resource.getrusage(resource.RUSAGE_SELF)
                telemetry.cpu_user_s = rusage.ru_utime - self._cpu_start['user']
                telemetry.cpu_system_s = rusage.ru_stime - self._cpu_start['system']
            except Exception as e:
                logger.debug(f"Could not capture CPU metrics: {e}")
        
        # Capture memory metrics with psutil
        if self._process:
            try:
                memory_info = self._process.memory_info()
                current_mb = memory_info.rss / (1024 * 1024)
                telemetry.ram_peak_mb = current_mb
                
                if self._memory_start:
                    telemetry.ram_delta_mb = current_mb - self._memory_start
                
                # Get CPU percent
                telemetry.cpu_percent_peak = self._process.cpu_percent()
            except Exception as e:
                logger.debug(f"Could not capture psutil metrics: {e}")
        
        return telemetry


# Global metrics extractor instance
metrics_extractor = MetricsExtractor()


def extract_model_metrics(
    document: Any,
    stl_path: Optional[Union[str, Path]] = None,
    job_id: Optional[str] = None,
    material: Optional[str] = None,
    queue_name: Optional[str] = None
) -> ModelMetrics:
    """
    Extract comprehensive metrics from FreeCAD model.
    
    Public API function for metrics extraction.
    
    Args:
        document: FreeCAD document or shape
        stl_path: Optional path to STL file
        job_id: Job identifier
        material: Material name
        queue_name: Queue name
    
    Returns:
        ModelMetrics with all extracted metrics
    """
    if stl_path and not isinstance(stl_path, Path):
        stl_path = Path(stl_path)
    
    return metrics_extractor.extract_metrics(
        document=document,
        stl_path=stl_path,
        job_id=job_id,
        material=material,
        queue_name=queue_name
    )