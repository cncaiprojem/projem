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
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Union

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


class BoundingBoxMetricsSchema(ModelMetricsBase):
    """Bounding box dimensional metrics."""
    
    width_m: float = Field(description="Genişlik (m) / Width in meters")
    height_m: float = Field(description="Yükseklik (m) / Height in meters")
    depth_m: float = Field(description="Derinlik (m) / Depth in meters")
    center: List[float] = Field(description="Merkez noktası [x,y,z] / Center point")
    min_point: List[float] = Field(description="Minimum köşe [x,y,z] / Minimum corner")
    max_point: List[float] = Field(description="Maksimum köşe [x,y,z] / Maximum corner")
    diagonal_m: Optional[float] = Field(None, description="Köşegen uzunluğu (m) / Diagonal length")
    
    def to_turkish(self) -> Dict[str, Any]:
        """Convert to Turkish localized format."""
        return {
            "genişlik_m": self.width_m,
            "yükseklik_m": self.height_m,
            "derinlik_m": self.depth_m,
            "merkez": self.center,
            "min_nokta": self.min_point,
            "maks_nokta": self.max_point,
            "köşegen_m": self.diagonal_m
        }


class VolumeMetricsSchema(ModelMetricsBase):
    """Volume and mass metrics."""
    
    volume_m3: Optional[float] = Field(None, description="Hacim (m³) / Volume in cubic meters")
    surface_area_m2: Optional[float] = Field(None, description="Yüzey alanı (m²) / Surface area")
    material_name: Optional[str] = Field(None, description="Malzeme adı / Material name")
    density_kg_m3: Optional[float] = Field(None, description="Yoğunluk (kg/m³) / Density")
    density_source: Optional[str] = Field(None, description="Yoğunluk kaynağı / Density source")
    mass_kg: Optional[float] = Field(None, description="Kütle (kg) / Mass in kilograms")
    
    def to_turkish(self) -> Dict[str, Any]:
        """Convert to Turkish localized format."""
        return {
            "hacim_m3": self.volume_m3,
            "yüzey_alanı_m2": self.surface_area_m2,
            "malzeme": self.material_name,
            "yoğunluk_kg_m3": self.density_kg_m3,
            "yoğunluk_kaynağı": self.density_source,
            "kütle_kg": self.mass_kg
        }


class MeshMetricsSchema(ModelMetricsBase):
    """Mesh tessellation metrics."""
    
    triangle_count: Optional[int] = Field(None, description="Üçgen sayısı / Number of triangles")
    vertex_count: Optional[int] = Field(None, description="Köşe sayısı / Number of vertices")
    linear_deflection: Optional[float] = Field(None, description="Doğrusal sapma / Linear deflection")
    angular_deflection: Optional[float] = Field(None, description="Açısal sapma / Angular deflection")
    relative: Optional[bool] = Field(None, description="Göreli sapma / Relative deflection")
    stl_hash: Optional[str] = Field(None, description="STL dosya özeti / STL file hash")
    
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


def _format_number_locale_independent(
    value: Union[float, Decimal, int], 
    thousands_sep: str = ',', 
    decimal_sep: str = '.', 
    decimals: int = 3
) -> str:
    """
    Format a number with custom separators in a locale-independent way.
    
    This function does not rely on the system locale and produces consistent
    output regardless of the system's locale settings.
    
    Args:
        value: The number to format
        thousands_sep: Character to use for thousands separator
        decimal_sep: Character to use for decimal point
        decimals: Number of decimal places
    
    Returns:
        Formatted string with specified separators
    """
    # Handle Decimal with quantization to preserve precision
    if isinstance(value, Decimal):
        # Quantize the Decimal to the specified decimal places
        # Use string formatting to create the precision specifier
        precision = Decimal(f'1e-{decimals}')
        value = value.quantize(precision, rounding=ROUND_HALF_UP)
        # Format to fixed-point notation to avoid scientific notation
        # Use 'f' format type with explicit precision
        formatted = format(value, f'.{decimals}f')
    elif isinstance(value, int):
        # Convert int to Decimal for consistent formatting
        value = Decimal(str(value))
        precision = Decimal(f'1e-{decimals}')
        value = value.quantize(precision, rounding=ROUND_HALF_UP)
        # Format to fixed-point notation
        formatted = format(value, f'.{decimals}f')
    else:
        # For float, use standard formatting
        formatted = f"{value:.{decimals}f}"
    
    # Split on the decimal point
    parts = formatted.split('.')
    integer_part = parts[0]
    decimal_part = parts[1] if len(parts) > 1 else ""
    
    # Handle negative sign
    is_negative = integer_part.startswith('-')
    if is_negative:
        integer_part = integer_part[1:]
    
    # Add thousands separators to integer part
    # Process from right to left, adding separator every 3 digits
    formatted_integer = ""
    for i, digit in enumerate(reversed(integer_part)):
        if i > 0 and i % 3 == 0:
            formatted_integer = thousands_sep + formatted_integer
        formatted_integer = digit + formatted_integer
    
    # Add negative sign back if needed
    if is_negative:
        formatted_integer = '-' + formatted_integer
    
    # Combine integer and decimal parts with the specified decimal separator
    if decimal_part:
        return formatted_integer + decimal_sep + decimal_part
    return formatted_integer


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
        original_locale = None
        locale_changed = False
        try:
            if locale_code == "tr":
                # Save original locale
                original_locale = system_locale.getlocale(system_locale.LC_NUMERIC)
                
                # Set Turkish locale if available
                # Let outer try/except handle fallback if Turkish locale not available
                system_locale.setlocale(system_locale.LC_NUMERIC, 'tr_TR.UTF-8')
                locale_changed = True
                
                # Use locale formatting - format_string requires float, so conversion is necessary
                # This is a limitation of the locale module, not our code
                formatted = system_locale.format_string("%.3f", float(value), grouping=True)
                
                return formatted
            else:
                # English formatting with thousands separator - use locale-independent approach
                return _format_number_locale_independent(value, thousands_sep=',', decimal_sep='.', decimals=3)
        except system_locale.Error:
            # Fallback to locale-independent manual formatting if locale fails
            if locale_code == "tr":
                # Turkish: period as thousands, comma as decimal
                return _format_number_locale_independent(value, thousands_sep='.', decimal_sep=',', decimals=3)
            else:
                # English: comma as thousands, period as decimal
                return _format_number_locale_independent(value, thousands_sep=',', decimal_sep='.', decimals=3)
        finally:
            # Always reset locale to original if it was changed
            if locale_changed and original_locale is not None:
                try:
                    system_locale.setlocale(system_locale.LC_NUMERIC, original_locale)
                except system_locale.Error:
                    # If we can't restore, at least reset to default
                    system_locale.setlocale(system_locale.LC_NUMERIC, '')
    
    return str(value)