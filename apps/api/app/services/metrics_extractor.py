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
import struct
import threading  # Move inline import to top
import time

# Try to import resource module (Unix-only)
try:
    import resource
    RESOURCE_AVAILABLE = True
except ImportError:
    RESOURCE_AVAILABLE = False
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

# Import metrics models from schemas to avoid duplication
from ..schemas.metrics import (
    ShapeMetricsSchema as ShapeMetrics,
    BoundingBoxMetricsSchema as BoundingBoxMetrics,
    VolumeMetricsSchema as VolumeMetrics,
    MeshMetricsSchema as MeshMetrics,
    RuntimeTelemetrySchema as RuntimeTelemetry,
    ModelMetricsSchema as ModelMetrics,
)

logger = get_logger(__name__)

# Try to import psutil for runtime telemetry
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil not available, runtime telemetry will be limited")

# Try to import FreeCAD modules
try:
    import FreeCAD
    import Part
    import Mesh
    FREECAD_AVAILABLE = True
except ImportError:
    FREECAD_AVAILABLE = False
    logger.warning("FreeCAD modules not available, metrics extraction will be limited")


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
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
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
        
        # Initialize CPU percent by calling once and discarding result
        # psutil requires an initial call to cpu_percent() to establish a baseline
        # for subsequent percentage calculations. The first call always returns 0.0
        if self._process:
            try:
                _ = self._process.cpu_percent()  # Establish baseline for CPU percentage calculation
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        
        # Capture CPU start
        if RESOURCE_AVAILABLE:
            try:
                rusage = resource.getrusage(resource.RUSAGE_SELF)
                self._cpu_start = {
                    'user': rusage.ru_utime,
                    'system': rusage.ru_stime
                }
            except Exception:
                self._cpu_start = None
        else:
            self._cpu_start = None
        
        # Capture memory start
        if self._process:
            try:
                self._memory_start = self._process.memory_info().rss / (1024 * 1024)  # MB
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
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
            if not FREECAD_AVAILABLE:
                raise ImportError("FreeCAD modules not available")
            
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
            if not FREECAD_AVAILABLE:
                raise ImportError("FreeCAD modules not available")
            
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
            if not FREECAD_AVAILABLE:
                raise ImportError("FreeCAD modules not available")
            
            metrics = VolumeMetrics()
            
            # Get shape and collect all materials
            if hasattr(document, 'Objects'):
                shapes = []
                materials_found = []
                for obj in document.Objects:
                    if hasattr(obj, 'Shape') and obj.Shape and not obj.Shape.isNull():
                        shapes.append(obj.Shape)
                        # Collect material property from each object
                        if hasattr(obj, 'Material') and obj.Material:
                            mat_str = str(obj.Material)
                            if mat_str and mat_str not in materials_found:
                                materials_found.append(mat_str)
                
                # Handle multiple materials
                if not material and materials_found:
                    if len(materials_found) > 1:
                        logger.warning(
                            f"Multiple materials found in assembly: {materials_found}. "
                            f"Using first material '{materials_found[0]}' for density lookup. "
                            "Consider weighted average for accurate mass calculation."
                        )
                    material = materials_found[0]
                
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
                    # ASCII STL - count lines efficiently without loading entire file
                    with open(stl_path, 'r', encoding='utf-8', errors='ignore') as ascii_f:
                        # Use generator expression to count facet lines without loading all into memory
                        metrics.triangle_count = sum(1 for line in ascii_f if 'facet normal' in line)
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
                if not FREECAD_AVAILABLE:
                    raise ImportError("FreeCAD Mesh module not available")
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
            telemetry.worker_thread_id = threading.current_thread().ident
        except Exception:
            pass
        
        # Capture CPU metrics
        if RESOURCE_AVAILABLE and self._cpu_start:
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
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
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