"""
Metrics schemas for FreeCAD export operations.

Provides Pydantic models for tracking and reporting metrics from
FreeCAD document exports with proper Decimal precision handling.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN
from typing import Dict, List, Optional, Any
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, ConfigDict
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema


class JobMetrics(BaseModel):
    """Metrics extracted from FreeCAD document for job tracking."""
    
    model_config = ConfigDict(
        json_encoders={Decimal: lambda v: float(v)},
        json_schema_mode_override='validation'
    )
    
    # Document metrics
    object_count: int = Field(description="Total number of objects in document")
    face_count: int = Field(description="Total number of faces in all shapes")
    edge_count: int = Field(description="Total number of edges in all shapes")
    vertex_count: int = Field(description="Total number of vertices in all shapes")
    
    # Geometric metrics (using Decimal for precision)
    volume: Decimal = Field(
        description="Total volume in mm³",
        json_schema_extra={'format': 'decimal'}
    )
    surface_area: Decimal = Field(
        description="Total surface area in mm²",
        json_schema_extra={'format': 'decimal'}
    )
    bounding_box_volume: Decimal = Field(
        description="Bounding box volume in mm³",
        json_schema_extra={'format': 'decimal'}
    )
    
    # Material metrics
    material_type: Optional[str] = Field(None, description="Material type if specified")
    material_density: Optional[Decimal] = Field(
        None,
        description="Material density in g/cm³",
        json_schema_extra={'format': 'decimal'}
    )
    estimated_mass: Optional[Decimal] = Field(
        None,
        description="Estimated mass in grams",
        json_schema_extra={'format': 'decimal'}
    )
    
    # Export metadata
    export_formats: List[str] = Field(description="Formats exported")
    export_timestamp: datetime = Field(description="When export occurred")
    export_duration_ms: int = Field(description="Total export time in milliseconds")
    
    # Job metadata
    job_id: Optional[str] = Field(None, description="Associated job ID")
    queue_name: Optional[str] = Field(None, description="Queue used for processing")
    
    @field_validator('volume', 'surface_area', 'bounding_box_volume', 'material_density', 'estimated_mass', mode='before')
    @classmethod
    def ensure_decimal(cls, v: Any) -> Optional[Decimal]:
        """Ensure Decimal type for precision fields."""
        if v is None:
            return None
        if isinstance(v, Decimal):
            return v
        return Decimal(str(v))
    
    @field_validator('volume', 'surface_area', 'bounding_box_volume', 'estimated_mass')
    @classmethod
    def quantize_engineering_values(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        """Apply engineering rounding (ROUND_HALF_EVEN) for consistency."""
        if v is None:
            return None
        # Round to 6 decimal places for engineering precision
        return v.quantize(Decimal('0.000001'), rounding=ROUND_HALF_EVEN)
    
    def format_large_numbers(self) -> Dict[str, str]:
        """
        Format numeric metrics with thousands separators.
        
        Returns locale-independent, thread-safe formatted strings.
        """
        formatted = {}
        
        # Format counts with thousands separators
        formatted['object_count'] = self._format_with_separator(self.object_count)
        formatted['face_count'] = self._format_with_separator(self.face_count)
        formatted['edge_count'] = self._format_with_separator(self.edge_count)
        formatted['vertex_count'] = self._format_with_separator(self.vertex_count)
        
        # Format volumes and areas with decimal precision
        formatted['volume'] = self._format_decimal_with_separator(self.volume)
        formatted['surface_area'] = self._format_decimal_with_separator(self.surface_area)
        formatted['bounding_box_volume'] = self._format_decimal_with_separator(self.bounding_box_volume)
        
        if self.estimated_mass:
            formatted['estimated_mass'] = self._format_decimal_with_separator(self.estimated_mass)
        
        formatted['export_duration_ms'] = self._format_with_separator(self.export_duration_ms)
        
        return formatted
    
    @staticmethod
    def _format_with_separator(value: int) -> str:
        """
        Format integer with thousands separator using Pythonic approach.
        
        Uses built-in format specifier for thread-safe, locale-independent formatting.
        """
        return f'{value:,}'
    
    @staticmethod
    def _format_decimal_with_separator(value: Optional[Decimal]) -> str:
        """
        Format Decimal with thousands separator using Pythonic approach.
        
        Maintains precision while adding separators in a thread-safe manner.
        """
        if value is None:
            return "N/A"
        
        # Convert to string maintaining full precision
        str_value = str(value)
        
        # Split into integer and decimal parts
        if '.' in str_value:
            integer_part, decimal_part = str_value.split('.')
        else:
            integer_part, decimal_part = str_value, ''
        
        # Format integer part with separator using built-in formatter
        # This is more Pythonic than manual string building
        if integer_part.startswith('-'):
            sign = '-'
            integer_part = integer_part[1:]
        else:
            sign = ''
        
        # Use format specifier for clean separation
        formatted_int = f'{int(integer_part):,}'
        
        # Reconstruct with decimal part if present, stripping trailing zeros
        if decimal_part:
            # Remove trailing zeros but keep at least one digit after decimal
            decimal_part = decimal_part.rstrip('0') or '0'
            # If all zeros were stripped, don't include decimal point
            if decimal_part == '0':
                return f'{sign}{formatted_int}.0'
            return f'{sign}{formatted_int}.{decimal_part}'
        return f'{sign}{formatted_int}'
    
    def to_prometheus_labels(self) -> Dict[str, str]:
        """Convert metrics to Prometheus-compatible label format."""
        labels = {}
        
        if self.job_id:
            labels['job_id'] = self.job_id
        if self.queue_name:
            labels['queue'] = self.queue_name
        if self.material_type:
            labels['material'] = self.material_type
        
        # Add format counts
        labels['format_count'] = str(len(self.export_formats))
        labels['primary_format'] = self.export_formats[0] if self.export_formats else 'none'
        
        return labels


class ExportMetrics(BaseModel):
    """Aggregated metrics for a complete export operation."""
    
    model_config = ConfigDict(
        json_encoders={Decimal: lambda v: float(v)},
        json_schema_mode_override='validation'
    )
    
    job_metrics: JobMetrics = Field(description="Core job metrics")
    format_metrics: Dict[str, Dict[str, Any]] = Field(
        description="Per-format export metrics"
    )
    validation_passed: bool = Field(
        default=True,
        description="Whether all validations passed"
    )
    validation_errors: List[str] = Field(
        default_factory=list,
        description="Any validation errors encountered"
    )
    
    def aggregate_stats(self) -> Dict[str, Any]:
        """Generate aggregated statistics from all metrics."""
        stats = {
            'total_formats': len(self.format_metrics),
            'total_export_size': sum(
                m.get('size', 0) for m in self.format_metrics.values()
            ),
            'average_export_time': (
                self.job_metrics.export_duration_ms / len(self.format_metrics)
                if self.format_metrics else 0
            ),
            'validation_status': 'PASSED' if self.validation_passed else 'FAILED',
            'formatted_numbers': self.job_metrics.format_large_numbers()
        }
        
        return stats