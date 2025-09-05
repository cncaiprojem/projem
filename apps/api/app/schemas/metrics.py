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
            Decimal: str  # Preserve exact precision by converting to string
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
    
    width_m: Decimal = Field(description="Genişlik (m) / Width in meters")
    height_m: Decimal = Field(description="Yükseklik (m) / Height in meters")
    depth_m: Decimal = Field(description="Derinlik (m) / Depth in meters")
    center: List[Decimal] = Field(description="Merkez noktası [x,y,z] / Center point")
    min_point: List[Decimal] = Field(description="Minimum köşe [x,y,z] / Minimum corner")
    max_point: List[Decimal] = Field(description="Maksimum köşe [x,y,z] / Maximum corner")
    diagonal_m: Optional[Decimal] = Field(None, description="Köşegen uzunluğu (m) / Diagonal length")
    
    def to_turkish(self) -> Dict[str, Any]:
        """Convert to Turkish localized format."""
        return {
            "genişlik_m": str(self.width_m) if self.width_m is not None else None,
            "yükseklik_m": str(self.height_m) if self.height_m is not None else None,
            "derinlik_m": str(self.depth_m) if self.depth_m is not None else None,
            "merkez": [str(v) for v in self.center] if self.center else None,
            "min_nokta": [str(v) for v in self.min_point] if self.min_point else None,
            "maks_nokta": [str(v) for v in self.max_point] if self.max_point else None,
            "köşegen_m": str(self.diagonal_m) if self.diagonal_m is not None else None
        }


class VolumeMetricsSchema(ModelMetricsBase):
    """Volume and mass metrics."""
    
    volume_m3: Optional[Decimal] = Field(None, description="Hacim (m³) / Volume in cubic meters")
    surface_area_m2: Optional[Decimal] = Field(None, description="Yüzey alanı (m²) / Surface area")
    material_name: Optional[str] = Field(None, description="Malzeme adı / Material name")
    density_kg_m3: Optional[Decimal] = Field(None, description="Yoğunluk (kg/m³) / Density")
    density_source: Optional[str] = Field(None, description="Yoğunluk kaynağı / Density source")
    mass_kg: Optional[Decimal] = Field(None, description="Kütle (kg) / Mass in kilograms")
    
    def to_turkish(self) -> Dict[str, Any]:
        """Convert to Turkish localized format."""
        return {
            "hacim_m3": str(self.volume_m3) if self.volume_m3 is not None else None,
            "yüzey_alanı_m2": str(self.surface_area_m2) if self.surface_area_m2 is not None else None,
            "malzeme": self.material_name,
            "yoğunluk_kg_m3": str(self.density_kg_m3) if self.density_kg_m3 is not None else None,
            "yoğunluk_kaynağı": self.density_source,
            "kütle_kg": str(self.mass_kg) if self.mass_kg is not None else None
        }


class MeshMetricsSchema(ModelMetricsBase):
    """Mesh tessellation metrics."""
    
    triangle_count: Optional[int] = Field(None, description="Üçgen sayısı / Number of triangles")
    vertex_count: Optional[int] = Field(None, description="Köşe sayısı / Number of vertices")
    linear_deflection: Optional[Decimal] = Field(None, description="Doğrusal sapma / Linear deflection")
    angular_deflection: Optional[Decimal] = Field(None, description="Açısal sapma / Angular deflection")
    relative: Optional[bool] = Field(None, description="Göreli sapma / Relative deflection")
    stl_hash: Optional[str] = Field(None, description="STL dosya özeti / STL file hash")
    
    def to_turkish(self) -> Dict[str, Any]:
        """Convert to Turkish localized format."""
        return {
            "üçgen_sayısı": self.triangle_count,
            "köşe_sayısı": self.vertex_count,
            "doğrusal_sapma": str(self.linear_deflection) if self.linear_deflection is not None else None,
            "açısal_sapma": str(self.angular_deflection) if self.angular_deflection is not None else None,
            "göreli": self.relative,
            "stl_özeti": self.stl_hash[:8] if self.stl_hash else None
        }


class RuntimeTelemetrySchema(ModelMetricsBase):
    """Runtime performance telemetry."""
    
    duration_ms: int = Field(description="Toplam süre (ms) / Total duration")
    phase_timings: Optional[Dict[str, int]] = Field(None, description="Faz süreleri / Phase timings")
    cpu_user_s: Optional[Decimal] = Field(None, description="CPU kullanıcı süresi (s) / User CPU time")
    cpu_system_s: Optional[Decimal] = Field(None, description="CPU sistem süresi (s) / System CPU time")
    cpu_percent_avg: Optional[Decimal] = Field(None, description="CPU ortalama kullanımı (%) / Average CPU usage")
    ram_peak_mb: Optional[Decimal] = Field(None, description="Bellek tepe kullanımı (MB) / Peak RAM usage")
    ram_delta_mb: Optional[Decimal] = Field(None, description="Bellek değişimi (MB) / Memory delta")
    worker_pid: Optional[int] = Field(None, description="İşlem ID / Process ID")
    worker_hostname: Optional[str] = Field(None, description="Sunucu adı / Worker hostname")
    worker_thread_id: Optional[int] = Field(None, description="İş parçacığı ID / Thread ID")
    queue_name: Optional[str] = Field(None, description="Kuyruk adı / Queue name")
    
    def to_turkish(self) -> Dict[str, Any]:
        """Convert to Turkish localized format."""
        return {
            "süre_ms": self.duration_ms,
            "faz_süreleri": self.phase_timings,
            "cpu_kullanıcı_sn": str(self.cpu_user_s) if self.cpu_user_s is not None else None,
            "cpu_sistem_sn": str(self.cpu_system_s) if self.cpu_system_s is not None else None,
            "cpu_ortalama_yüzde": str(self.cpu_percent_avg) if self.cpu_percent_avg is not None else None,
            "bellek_tepe_mb": str(self.ram_peak_mb) if self.ram_peak_mb is not None else None,
            "bellek_delta_mb": str(self.ram_delta_mb) if self.ram_delta_mb is not None else None,
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
    
    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={
            Decimal: str  # Preserve exact precision by converting to string
        }
    )
    
    # Key metrics
    solids_count: Optional[int] = Field(None, description="Katı sayısı / Number of solids")
    faces_count: Optional[int] = Field(None, description="Yüzey sayısı / Number of faces")
    volume_m3: Optional[Decimal] = Field(None, description="Hacim (m³) / Volume")
    mass_kg: Optional[Decimal] = Field(None, description="Kütle (kg) / Mass")
    triangles_count: Optional[int] = Field(None, description="Üçgen sayısı / Triangle count")
    
    # Dimensions
    width_mm: Optional[Decimal] = Field(None, description="Genişlik (mm) / Width in mm")
    height_mm: Optional[Decimal] = Field(None, description="Yükseklik (mm) / Height in mm")
    depth_mm: Optional[Decimal] = Field(None, description="Derinlik (mm) / Depth in mm")
    
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
                "width_mm": metrics.bounding_box.width_m * Decimal(str(METERS_TO_MILLIMETERS)),
                "height_mm": metrics.bounding_box.height_m * Decimal(str(METERS_TO_MILLIMETERS)),
                "depth_mm": metrics.bounding_box.depth_m * Decimal(str(METERS_TO_MILLIMETERS))
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
    "cpu_percent_avg": "CPU Ortalama (%)",
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
        # Use str() to preserve exact Decimal value without float conversion
        formatted = str(value)
    elif isinstance(value, int):
        # For integers, don't add decimal places
        if decimals == 0:
            formatted = str(value)
        else:
            # Convert int to Decimal for consistent formatting when decimals needed
            value = Decimal(str(value))
            precision = Decimal(f'1e-{decimals}')
            value = value.quantize(precision, rounding=ROUND_HALF_UP)
            # Use str() to preserve exact value
            formatted = str(value)
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
    
    # Number formatting - thread-safe, no locale changes
    if isinstance(value, (float, Decimal, int)):
        # Determine decimal places based on type
        # Integers should not have decimal places added
        is_integer = isinstance(value, int) or (isinstance(value, Decimal) and value % 1 == 0)
        decimals = 0 if is_integer else 3
        
        # Use custom locale-independent formatting for thread safety
        # This avoids setlocale() which is not thread-safe
        if locale_code == "tr":
            # Turkish: period as thousands separator, comma as decimal separator
            return _format_number_locale_independent(value, thousands_sep='.', decimal_sep=',', decimals=decimals)
        else:
            # English: comma as thousands separator, period as decimal separator
            return _format_number_locale_independent(value, thousands_sep=',', decimal_sep='.', decimals=decimals)
    
    return str(value)