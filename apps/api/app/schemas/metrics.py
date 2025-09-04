"""
Metrics schemas for Task 7.10

Comprehensive Pydantic schemas for model metrics including:
- Shape topology metrics
- Bounding box dimensions
- Volume and mass calculations
- Mesh/tessellation metrics
- Runtime telemetry
- Turkish localization support
"""

import locale as system_locale
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict

# Constants
METERS_TO_MILLIMETERS = 1000


class ModelMetricsBase(BaseModel):
    """Base schema for model metrics."""
    
    model_config = ConfigDict(
        json_encoders={
            Decimal: lambda v: float(v)  # Convert Decimal to float for JSON serialization
        }
    )


class ShapeMetricsSchema(ModelMetricsBase):
    """Shape topology metrics."""
    
    solids: int = Field(description="Katı şekil sayısı / Number of solid shapes")
    faces: int = Field(description="Yüzey sayısı / Number of faces")
    edges: int = Field(description="Kenar sayısı / Number of edges")
    vertices: int = Field(description="Köşe sayısı / Number of vertices")
    is_closed: bool = Field(description="Kapalı mı / Whether shape is closed")
    is_valid: bool = Field(description="Geçerli mi / Whether shape is valid")
    shape_type: Optional[str] = Field(None, description="Şekil tipi / Shape type")


class BoundingBoxMetricsSchema(ModelMetricsBase):
    """Bounding box dimensional metrics."""
    
    width_m: float = Field(description="Genişlik (m) / Width in meters")
    height_m: float = Field(description="Yükseklik (m) / Height in meters")
    depth_m: float = Field(description="Derinlik (m) / Depth in meters")
    center: List[float] = Field(description="Merkez noktası [x,y,z] / Center point")
    min_point: List[float] = Field(description="Minimum köşe [x,y,z] / Minimum corner")
    max_point: List[float] = Field(description="Maksimum köşe [x,y,z] / Maximum corner")
    diagonal_m: Optional[float] = Field(None, description="Köşegen uzunluğu (m) / Diagonal length")


class VolumeMetricsSchema(ModelMetricsBase):
    """Volume and mass metrics."""
    
    volume_m3: Optional[float] = Field(None, description="Hacim (m³) / Volume in cubic meters")
    surface_area_m2: Optional[float] = Field(None, description="Yüzey alanı (m²) / Surface area")
    material_name: Optional[str] = Field(None, description="Malzeme adı / Material name")
    density_kg_m3: Optional[float] = Field(None, description="Yoğunluk (kg/m³) / Density")
    density_source: Optional[str] = Field(None, description="Yoğunluk kaynağı / Density source")
    mass_kg: Optional[float] = Field(None, description="Kütle (kg) / Mass in kilograms")


class MeshMetricsSchema(ModelMetricsBase):
    """Mesh tessellation metrics."""
    
    triangle_count: Optional[int] = Field(None, description="Üçgen sayısı / Number of triangles")
    vertex_count: Optional[int] = Field(None, description="Köşe sayısı / Number of vertices")
    linear_deflection: Optional[float] = Field(None, description="Doğrusal sapma / Linear deflection")
    angular_deflection: Optional[float] = Field(None, description="Açısal sapma / Angular deflection")
    relative: Optional[bool] = Field(None, description="Göreli sapma / Relative deflection")
    stl_hash: Optional[str] = Field(None, description="STL dosya özeti / STL file hash")


class RuntimeTelemetrySchema(ModelMetricsBase):
    """Runtime performance telemetry."""
    
    duration_ms: int = Field(description="Toplam süre (ms) / Total duration")
    phase_timings: Optional[Dict[str, int]] = Field(None, description="Faz süreleri / Phase timings")
    cpu_user_s: Optional[float] = Field(None, description="CPU kullanıcı süresi (s) / User CPU time")
    cpu_system_s: Optional[float] = Field(None, description="CPU sistem süresi (s) / System CPU time")
    cpu_percent_peak: Optional[float] = Field(None, description="CPU tepe kullanımı (%) / Peak CPU usage")
    ram_peak_mb: Optional[float] = Field(None, description="Bellek tepe kullanımı (MB) / Peak RAM usage")
    ram_delta_mb: Optional[float] = Field(None, description="Bellek değişimi (MB) / Memory delta")
    worker_pid: Optional[int] = Field(None, description="İşlem ID / Process ID")
    worker_hostname: Optional[str] = Field(None, description="Sunucu adı / Worker hostname")
    worker_thread_id: Optional[int] = Field(None, description="İş parçacığı ID / Thread ID")
    queue_name: Optional[str] = Field(None, description="Kuyruk adı / Queue name")


class ModelMetricsSchema(ModelMetricsBase):
    """Complete model metrics schema."""
    
    shape: Optional[ShapeMetricsSchema] = Field(None, description="Şekil analizi / Shape analysis")
    bounding_box: Optional[BoundingBoxMetricsSchema] = Field(None, description="Sınır kutusu / Bounding box")
    volume: Optional[VolumeMetricsSchema] = Field(None, description="Hacim ve kütle / Volume and mass")
    mesh: Optional[MeshMetricsSchema] = Field(None, description="Ağ metrikleri / Mesh metrics")
    telemetry: Optional[RuntimeTelemetrySchema] = Field(None, description="Çalışma zamanı telemetrisi / Runtime telemetry")
    
    metrics_version: str = Field(default="1.0.0", description="Metrik şema sürümü / Metrics schema version")
    request_id: Optional[str] = Field(None, description="İstek ID / Request correlation ID")
    job_id: Optional[str] = Field(None, description="İş ID / Job identifier")
    timestamp: Optional[str] = Field(None, description="Zaman damgası / Extraction timestamp")
    warnings: List[str] = Field(default_factory=list, description="Uyarılar / Non-fatal warnings")
    errors: List[str] = Field(default_factory=list, description="Hatalar / Extraction errors")


class ModelMetricsSummary(BaseModel):
    """Summary metrics for display."""
    
    model_config = ConfigDict(from_attributes=True)
    
    # Key metrics
    solids_count: Optional[int] = Field(None, description="Katı sayısı / Number of solids")
    faces_count: Optional[int] = Field(None, description="Yüzey sayısı / Number of faces")
    volume_m3: Optional[float] = Field(None, description="Hacim (m³) / Volume")
    mass_kg: Optional[float] = Field(None, description="Kütle (kg) / Mass")
    triangles_count: Optional[int] = Field(None, description="Üçgen sayısı / Triangle count")
    
    # Dimensions
    width_mm: Optional[float] = Field(None, description="Genişlik (mm) / Width in mm")
    height_mm: Optional[float] = Field(None, description="Yükseklik (mm) / Height in mm")
    depth_mm: Optional[float] = Field(None, description="Derinlik (mm) / Depth in mm")
    
    # Performance
    extraction_time_ms: Optional[int] = Field(None, description="Çıkarım süresi (ms) / Extraction time")
    
    @classmethod
    def from_full_metrics(cls, metrics: ModelMetricsSchema) -> "ModelMetricsSummary":
        """Create summary from full metrics using declarative initialization."""
        # Build kwargs declaratively
        kwargs = {}
        
        # Shape metrics
        if metrics.shape:
            kwargs.update({
                "solids_count": metrics.shape.solids,
                "faces_count": metrics.shape.faces
            })
        
        # Volume metrics
        if metrics.volume:
            kwargs.update({
                "volume_m3": metrics.volume.volume_m3,
                "mass_kg": metrics.volume.mass_kg
            })
        
        # Mesh metrics
        if metrics.mesh:
            kwargs["triangles_count"] = metrics.mesh.triangle_count
        
        # Bounding box - convert to mm for display
        if metrics.bounding_box:
            kwargs.update({
                "width_mm": metrics.bounding_box.width_m * METERS_TO_MILLIMETERS,
                "height_mm": metrics.bounding_box.height_m * METERS_TO_MILLIMETERS,
                "depth_mm": metrics.bounding_box.depth_m * METERS_TO_MILLIMETERS
            })
        
        # Performance
        if metrics.telemetry:
            kwargs["extraction_time_ms"] = metrics.telemetry.duration_ms
        
        return cls(**kwargs)


# Turkish display mappings
TURKISH_METRIC_LABELS = {
    "solids": "Katılar",
    "faces": "Yüzeyler",
    "edges": "Kenarlar",
    "vertices": "Köşeler",
    "triangles": "Üçgenler",
    "bounding_box": "Sınır Kutusu",
    "width": "Genişlik",
    "height": "Yükseklik",
    "depth": "Derinlik",
    "volume": "Hacim",
    "mass": "Kütle",
    "material": "Malzeme",
    "density": "Yoğunluk",
    "duration_ms": "Süre (ms)",
    "cpu_user_s": "CPU Kullanıcı (sn)",
    "cpu_system_s": "CPU Sistem (sn)",
    "cpu_percent_peak": "CPU Tepe (%)",
    "ram_peak_mb": "Bellek Tepe (MB)",
    "units": "Birimler"
}


def format_metric_for_display(value: Any, locale_code: str = "en") -> str:
    """
    Format metric value for display with proper localization.
    
    Uses locale-aware formatting for numbers when available,
    falls back to manual formatting if locale module fails.
    
    Args:
        value: Metric value to format
        locale_code: Locale code (en, tr)
    
    Returns:
        Formatted string
    """
    if value is None:
        return "-"
    
    # Boolean formatting
    if isinstance(value, bool):
        if locale_code == "tr":
            return "Evet" if value else "Hayır"
        return "Yes" if value else "No"
    
    # Number formatting
    if isinstance(value, (float, Decimal, int)):
        # Try locale-aware formatting first
        try:
            if locale_code == "tr":
                # Set Turkish locale if available
                try:
                    system_locale.setlocale(system_locale.LC_NUMERIC, 'tr_TR.UTF-8')
                except:
                    # Fallback to C locale if Turkish not available
                    system_locale.setlocale(system_locale.LC_NUMERIC, 'C')
                
                # Use locale formatting
                if isinstance(value, (int, Decimal)):
                    formatted = system_locale.format_string("%.3f", float(value), grouping=True)
                else:
                    formatted = system_locale.format_string("%.3f", value, grouping=True)
                
                # Reset locale to default
                system_locale.setlocale(system_locale.LC_NUMERIC, '')
                return formatted
            else:
                # English formatting with thousands separator
                return f"{value:,.3f}"
        except Exception:
            # Fallback to manual formatting if locale fails
            if locale_code == "tr":
                # Turkish: comma as decimal, period as thousands
                return f"{value:,.3f}".replace(".", "X").replace(",", ".").replace("X", ",")
            else:
                return f"{value:,.3f}"
    
    return str(value)