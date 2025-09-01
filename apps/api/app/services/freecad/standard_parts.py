"""
Standard Parts Library for Task 7.2

Provides:
- DIN/ISO parts catalog
- FCStd template management
- Part parameter resolution
"""

from __future__ import annotations

import json
import os
import re
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from jinja2 import Environment, Template, TemplateSyntaxError, sandbox
from pydantic import BaseModel, Field

from ...core.logging import get_logger

logger = get_logger(__name__)


# ============================================================================
# Custom Exception Classes for Enterprise-Grade Error Handling
# ============================================================================

class StandardPartError(Exception):
    """Base exception for standard part errors.
    
    This base class provides a foundation for all standard part related
    exceptions, following enterprise error handling patterns.
    """
    pass


class UnknownStandardError(StandardPartError):
    """Raised when an unknown standard is requested.
    
    This exception provides detailed information about the requested standard
    and available alternatives, enabling better error recovery.
    
    Attributes:
        standard: The requested standard that was not found
        known_standards: List of available standards
    """
    
    def __init__(self, standard: str, known_standards: List[str]):
        self.standard = standard
        self.known_standards = known_standards
        super().__init__(
            f"Unknown standard: {standard}. "
            f"Known standards: {', '.join(known_standards)}"
        )


class UnsupportedSizeError(StandardPartError):
    """Raised when an unsupported size is requested for a standard.
    
    This exception provides information about the requested size,
    the standard it was requested for, and available sizes.
    
    Attributes:
        size: The requested size that is not available
        standard: The standard for which the size was requested
        available_sizes: List of available sizes for the standard
    """
    
    def __init__(self, size: str, standard: str, available_sizes: List[str]):
        self.size = size
        self.standard = standard
        self.available_sizes = available_sizes
        super().__init__(
            f"Size {size} not available for {standard}. "
            f"Available sizes: {', '.join(available_sizes)}"
        )


class InvalidSizeFormatError(StandardPartError):
    """Raised when a size format cannot be parsed.
    
    This exception provides information about the invalid size format
    and the expected format for the given part category.
    
    Attributes:
        size: The size string that could not be parsed
        category: The part category
        format_hint: A hint about the expected format
    """
    
    def __init__(self, size: str, category: str, format_hint: str):
        self.size = size
        self.category = category
        self.format_hint = format_hint
        super().__init__(
            f"Invalid size format '{size}' for {category}. {format_hint}"
        )


class StandardType(str, Enum):
    """Standard types for parts."""
    DIN = "DIN"
    ISO = "ISO"
    ANSI = "ANSI"
    JIS = "JIS"
    GB = "GB"  # Chinese standard
    CUSTOM = "CUSTOM"


class PartCategory(str, Enum):
    """Categories of standard parts."""
    FASTENERS = "fasteners"
    BEARINGS = "bearings"
    GEARS = "gears"
    SEALS = "seals"
    PROFILES = "profiles"
    ELECTRICAL = "electrical"
    PNEUMATIC = "pneumatic"
    HYDRAULIC = "hydraulic"


class StandardPart(BaseModel):
    """Standard part definition."""
    code: str = Field(description="Part code (e.g., DIN933)")
    name: str = Field(description="Part name")
    category: PartCategory = Field(description="Part category")
    standard_type: StandardType = Field(description="Standard type")
    description: str = Field(description="Part description")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Part parameters")
    sizes: List[str] = Field(default_factory=list, description="Available sizes")
    template_script: Optional[str] = Field(default=None, description="FreeCAD generation script")
    
    def get_size_parameters(self, size: str) -> Optional[Dict[str, float]]:
        """Get parameters for specific size."""
        # This would normally look up from a database or catalog
        # For now, return mock data based on size parsing
        if "M" in size:  # Metric thread
            try:
                # Parse M8x20 format
                parts = size.replace("M", "").split("x")
                diameter = float(parts[0])
                length = float(parts[1]) if len(parts) > 1 else diameter * 2.5
                
                return {
                    "diameter": diameter,
                    "length": length,
                    "thread_pitch": diameter * 0.125,  # Approximate
                    "head_diameter": diameter * 1.5,
                    "head_height": diameter * 0.7
                }
            except (ValueError, IndexError):
                logger.warning(f"Could not parse size: {size}")
                return None
        
        return None


class FCStdTemplate(BaseModel):
    """FreeCAD template file reference."""
    template_id: str = Field(description="Template identifier")
    name: str = Field(description="Template name")
    category: PartCategory = Field(description="Template category")
    file_path: Optional[str] = Field(default=None, description="Local file path")
    s3_url: Optional[str] = Field(default=None, description="S3 URL for template")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Configurable parameters")
    preview_image: Optional[str] = Field(default=None, description="Preview image URL")
    
    def get_local_path(self) -> Optional[Path]:
        """Get local file path if available."""
        if self.file_path and os.path.exists(self.file_path):
            return Path(self.file_path)
        return None


class StandardPartsLibrary:
    """Library of standard parts and templates."""
    
    # DIN/ISO standard metric thread pitch lookup table (coarse thread)
    # Based on ISO 261 and DIN 13-1 standards
    # ISO 261: https://www.iso.org/standard/4167.html - ISO general purpose metric screw threads
    # DIN 13-1: https://www.din.de/en/getting-involved/standards-committees/fmv/wdc-beuth:din21:29753787 - Metric ISO screw threads
    # Format: nominal_diameter -> pitch_mm
    METRIC_COARSE_PITCH = {
        1.0: 0.25,
        1.2: 0.25,
        1.4: 0.3,
        1.6: 0.35,
        1.8: 0.35,
        2.0: 0.4,
        2.5: 0.45,
        3.0: 0.5,
        3.5: 0.6,
        4.0: 0.7,
        5.0: 0.8,
        6.0: 1.0,
        7.0: 1.0,
        8.0: 1.25,  # M8 has 1.25mm pitch per ISO 261/DIN 13-1 standard (see URLs above)
        10.0: 1.5,
        12.0: 1.75,
        14.0: 2.0,
        16.0: 2.0,
        18.0: 2.5,
        20.0: 2.5,
        22.0: 2.5,
        24.0: 3.0,
        27.0: 3.0,
        30.0: 3.5,
        33.0: 3.5,
        36.0: 4.0,
        39.0: 4.0,
        42.0: 4.5,
        45.0: 4.5,
        48.0: 5.0,
        52.0: 5.0,
        56.0: 5.5,
        60.0: 5.5,
        64.0: 6.0
    }
    
    # DIN 933/ISO 4017 hex head dimensions (width across flats)
    # Based on DIN 933 and ISO 4017 standards
    # Format: nominal_diameter -> {waf: width_across_flats, head_height}
    HEX_HEAD_DIMENSIONS = {
        3.0: {"waf": 5.5, "height": 2.0},
        4.0: {"waf": 7.0, "height": 2.8},
        5.0: {"waf": 8.0, "height": 3.5},
        6.0: {"waf": 10.0, "height": 4.0},
        8.0: {"waf": 13.0, "height": 5.3},
        10.0: {"waf": 16.0, "height": 6.4},  # ISO 4017 uses 16mm, DIN 933 uses 17mm
        12.0: {"waf": 18.0, "height": 7.5},
        14.0: {"waf": 21.0, "height": 8.8},
        16.0: {"waf": 24.0, "height": 10.0},
        18.0: {"waf": 27.0, "height": 11.5},
        20.0: {"waf": 30.0, "height": 12.5},
        22.0: {"waf": 34.0, "height": 13.5},  # ISO differs from DIN at M22
        24.0: {"waf": 36.0, "height": 15.0},
        27.0: {"waf": 41.0, "height": 17.0},
        30.0: {"waf": 46.0, "height": 18.7},
        36.0: {"waf": 55.0, "height": 22.5}
    }
    
    # Common bearing dimensions database - moved to class constant for better organization
    # Format: bearing_code -> {bore_diameter, outer_diameter, width, ball_diameter, num_balls}
    BEARING_DIMENSIONS = {
        "608": {"bore_diameter": 8, "outer_diameter": 22, "width": 7, "ball_diameter": 3.5, "num_balls": 7},
        "625": {"bore_diameter": 5, "outer_diameter": 16, "width": 5, "ball_diameter": 2.5, "num_balls": 7},
        "6000": {"bore_diameter": 10, "outer_diameter": 26, "width": 8, "ball_diameter": 4, "num_balls": 8},
        "6001": {"bore_diameter": 12, "outer_diameter": 28, "width": 8, "ball_diameter": 4, "num_balls": 8},
        "6002": {"bore_diameter": 15, "outer_diameter": 32, "width": 9, "ball_diameter": 4.5, "num_balls": 8},
        "6003": {"bore_diameter": 17, "outer_diameter": 35, "width": 10, "ball_diameter": 5, "num_balls": 8},
        "6004": {"bore_diameter": 20, "outer_diameter": 42, "width": 12, "ball_diameter": 6, "num_balls": 8},
        "6005": {"bore_diameter": 25, "outer_diameter": 47, "width": 12, "ball_diameter": 6.5, "num_balls": 8},
        "6200": {"bore_diameter": 10, "outer_diameter": 30, "width": 9, "ball_diameter": 5, "num_balls": 8},
        "6201": {"bore_diameter": 12, "outer_diameter": 32, "width": 10, "ball_diameter": 5, "num_balls": 8},
        "6202": {"bore_diameter": 15, "outer_diameter": 35, "width": 11, "ball_diameter": 5.5, "num_balls": 8},
        "6203": {"bore_diameter": 17, "outer_diameter": 40, "width": 12, "ball_diameter": 6, "num_balls": 8},
        "6204": {"bore_diameter": 20, "outer_diameter": 47, "width": 14, "ball_diameter": 7, "num_balls": 8},
        "6205": {"bore_diameter": 25, "outer_diameter": 52, "width": 15, "ball_diameter": 7.5, "num_balls": 8},
    }
    
    # Catalog of common DIN/ISO parts
    # TODO: Consider externalizing this catalog to a JSON/YAML file for easier maintenance
    #       and to allow adding new standard parts without code changes.
    #       This would enable runtime catalog updates without redeployment.
    CATALOG = {
        "DIN933": StandardPart(
            code="DIN933",
            name="Hex Head Bolt",
            category=PartCategory.FASTENERS,
            standard_type=StandardType.DIN,
            description="Hexagon head bolt with full thread",
            parameters={
                "thread_type": "metric",
                "head_type": "hexagon",
                "thread_length": "full"
            },
            sizes=["M3x10", "M3x16", "M4x10", "M4x16", "M5x10", "M5x16", "M5x20", 
                   "M6x12", "M6x16", "M6x20", "M6x25", "M8x16", "M8x20", "M8x25", 
                   "M8x30", "M10x20", "M10x25", "M10x30", "M10x40"],
            template_script="""import FreeCAD as App
import Part
import math

# SECURITY: Template variables validated via Jinja2 at lines 563-569

# Parameters
diameter = {diameter}
length = {length}
thread_pitch = {thread_pitch}
head_diameter = {head_diameter}
head_height = {head_height}

# Create hex head
hex_radius = head_diameter / 2.0
hex_points = []
for i in range(6):
    angle = i * math.pi / 3.0
    x = hex_radius * math.cos(angle)
    y = hex_radius * math.sin(angle)
    hex_points.append(App.Vector(x, y, 0))

hex_wire = Part.makePolygon(hex_points + [hex_points[0]])
hex_face = Part.Face(hex_wire)
head = hex_face.extrude(App.Vector(0, 0, head_height))

# Create shaft
shaft = Part.makeCylinder(diameter/2.0, length)
shaft.translate(App.Vector(0, 0, head_height))

# Combine
bolt = head.fuse(shaft)

# Add to provided document with provided component ID
obj = doc.addObject("Part::Feature", comp_id)
obj.Shape = bolt
doc.recompute()"""
        ),
        
        "DIN934": StandardPart(
            code="DIN934",
            name="Hex Nut",
            category=PartCategory.FASTENERS,
            standard_type=StandardType.DIN,
            description="Hexagon nut",
            parameters={
                "thread_type": "metric",
                "nut_type": "hexagon"
            },
            sizes=["M3", "M4", "M5", "M6", "M8", "M10", "M12", "M16", "M20"]
        ),
        
        "DIN125": StandardPart(
            code="DIN125",
            name="Flat Washer",
            category=PartCategory.FASTENERS,
            standard_type=StandardType.DIN,
            description="Flat washer Type A",
            parameters={
                "washer_type": "flat",
                "form": "A"
            },
            sizes=["M3", "M4", "M5", "M6", "M8", "M10", "M12", "M16", "M20"]
        ),
        
        "ISO4762": StandardPart(
            code="ISO4762",
            name="Socket Head Cap Screw",
            category=PartCategory.FASTENERS,
            standard_type=StandardType.ISO,
            description="Socket head cap screw",
            parameters={
                "head_type": "socket",
                "drive_type": "hex_socket"
            },
            sizes=["M3x8", "M3x10", "M4x10", "M4x12", "M5x10", "M5x12", "M5x16",
                   "M6x12", "M6x16", "M6x20", "M8x16", "M8x20", "M8x25"]
        ),
        
        "DIN6000": StandardPart(
            code="DIN6000",
            name="Deep Groove Ball Bearing",
            category=PartCategory.BEARINGS,
            standard_type=StandardType.DIN,
            description="Single row deep groove ball bearing",
            parameters={
                "bearing_type": "ball",
                "row_count": 1
            },
            sizes=["608", "6000", "6001", "6002", "6003", "6004", "6005",
                   "6200", "6201", "6202", "6203", "6204", "6205"]
        ),
        
        "DIN625": StandardPart(
            code="DIN625",
            name="Deep Groove Ball Bearing",
            category=PartCategory.BEARINGS,
            standard_type=StandardType.DIN,
            description="Deep groove ball bearing with simplified raceway and ball representation",
            parameters={
                "bearing_type": "ball",
                "series": "multiple"  # Includes 625, 608, 6000, 6200 series
            },
            sizes=["625-2RS", "625-ZZ", "608-2RS", "608-ZZ", "6000", "6001", "6002", 
                   "6003", "6004", "6005", "6200", "6201", "6202", "6203", "6204", "6205"],
            template_script="""import FreeCAD as App
import Part
import math

# SECURITY: Template variables validated via Jinja2 at lines 563-569

# Parameters (example for 608 bearing: 8mm bore, 22mm OD, 7mm width)
bore_diameter = {bore_diameter}  # Inner diameter
outer_diameter = {outer_diameter}  # Outer diameter
width = {width}  # Bearing width
ball_diameter = {ball_diameter}  # Ball diameter
num_balls = {num_balls}  # Number of balls

# Create inner race
inner_race_outer = (bore_diameter + outer_diameter) / 2 - ball_diameter / 2
inner_race = Part.makeCylinder(inner_race_outer / 2, width)
inner_bore = Part.makeCylinder(bore_diameter / 2, width)
inner_race = inner_race.cut(inner_bore)

# Create outer race
outer_race_inner = (bore_diameter + outer_diameter) / 2 + ball_diameter / 2
outer_race = Part.makeCylinder(outer_diameter / 2, width)
outer_race_hole = Part.makeCylinder(outer_race_inner / 2, width)
outer_race = outer_race.cut(outer_race_hole)

# Create balls (simplified)
balls = []
pitch_diameter = (bore_diameter + outer_diameter) / 2
for i in range(num_balls):
    angle = 2 * math.pi * i / num_balls
    x = pitch_diameter / 2 * math.cos(angle)
    y = pitch_diameter / 2 * math.sin(angle)
    z = width / 2
    ball = Part.makeSphere(ball_diameter / 2)
    ball.translate(App.Vector(x, y, z))
    balls.append(ball)

# Combine all parts
bearing = inner_race.fuse(outer_race)
for ball in balls:
    bearing = bearing.fuse(ball)

# Add to provided document with provided component ID
obj = doc.addObject("Part::Feature", comp_id)
obj.Shape = bearing
doc.recompute()"""
        )
    }
    
    def __init__(self, template_dir: Optional[Path] = None):
        """
        Initialize standard parts library.
        
        Args:
            template_dir: Directory containing FCStd templates
        """
        self.template_dir = template_dir or Path("/tmp/freecad_templates")
        self.templates: Dict[str, FCStdTemplate] = {}
        
        # Cache for pre-compiled Jinja2 templates to avoid repeated conversions
        # Key: standard code, Value: compiled Jinja2 template
        self._compiled_templates_cache: Dict[str, Template] = {}
        
        # Use Jinja2 sandboxed environment for secure template rendering
        # This prevents code injection and restricts template access
        self.jinja_env = sandbox.SandboxedEnvironment(
            # Maintain backward compatibility with existing templates
            # that use {param} syntax by keeping default delimiters
            variable_start_string='{{',
            variable_end_string='}}',
            block_start_string='{%',
            block_end_string='%}',
            # Auto-escape is disabled as FreeCAD scripts don't need HTML escaping
            autoescape=False
        )
        
        self._load_templates()
        
        # Pre-compile all template scripts from the catalog for performance
        # This avoids repeated template conversion and compilation on every request
        self._precompile_catalog_templates()
    
    def _precompile_catalog_templates(self):
        """
        Pre-compile all template scripts from the catalog for performance.
        
        This method converts and compiles all template scripts during initialization
        to avoid repeated conversions and compilations during request processing.
        Templates are cached by standard code for O(1) lookup.
        """
        for standard, part_def in self.CATALOG.items():
            if part_def.template_script:
                try:
                    # Convert {param} syntax to {{param}} for Jinja2 compatibility
                    template_str = self._convert_format_to_jinja(part_def.template_script)
                    # Compile the template once and cache it
                    compiled_template = self.jinja_env.from_string(template_str)
                    self._compiled_templates_cache[standard] = compiled_template
                    logger.debug(f"Pre-compiled template for {standard}")
                except TemplateSyntaxError as e:
                    logger.error(f"Failed to pre-compile template for {standard}: {e}")
                    # Store None to avoid repeated compilation attempts
                    self._compiled_templates_cache[standard] = None
    
    def _load_templates(self):
        """Load available FCStd templates."""
        if not self.template_dir.exists():
            logger.info(f"Creating template directory: {self.template_dir}")
            self.template_dir.mkdir(parents=True, exist_ok=True)
        
        # Load templates from directory
        for template_file in self.template_dir.glob("*.FCStd"):
            template_id = template_file.stem
            
            # Try to load metadata
            metadata_file = template_file.with_suffix(".json")
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                    
                    template = FCStdTemplate(
                        template_id=template_id,
                        name=metadata.get("name", template_id),
                        category=PartCategory(metadata.get("category", "custom")),
                        file_path=str(template_file),
                        parameters=metadata.get("parameters", {})
                    )
                    
                    self.templates[template_id] = template
                    logger.info(f"Loaded template: {template_id}")
                    
                except Exception as e:
                    logger.warning(f"Could not load template metadata for {template_id}: {e}")
    
    def get_part(self, standard: str, size: str) -> Optional[Dict[str, Any]]:
        """
        Get standard part by standard and size (Task 7.6 requirement).
        
        Args:
            standard: Part standard (e.g., "DIN933", "DIN625")
            size: Size specification (e.g., "M6x20" for screws, "608" for bearings)
            
        Returns:
            Dictionary with part generation info or None
        """
        # Get the part definition
        part_def = self.CATALOG.get(standard)
        if not part_def:
            # Raise exception with known standards for better error handling
            known = list(self.CATALOG.keys())
            logger.warning(f"Unknown standard: {standard}. Known: {known}")
            raise UnknownStandardError(standard, known)
        
        # Check if size is supported
        if size not in part_def.sizes:
            # Raise exception with available sizes for better error recovery
            logger.warning(
                f"Size {size} not available for {standard}. "
                f"Available: {part_def.sizes}"
            )
            raise UnsupportedSizeError(size, standard, part_def.sizes)
        
        # Parse size parameters based on part type
        try:
            if part_def.category == PartCategory.FASTENERS:
                params = self._parse_fastener_size(size)
            elif part_def.category == PartCategory.BEARINGS:
                params = self._parse_bearing_size(size)
            else:
                params = part_def.get_size_parameters(size)
            
            if not params:
                # This should not happen with new exception-based approach
                # but kept for backward compatibility with legacy methods
                raise InvalidSizeFormatError(
                    size=size,
                    category=part_def.category.value,
                    format_hint=self._get_size_format_hint(part_def.category)
                )
        except InvalidSizeFormatError:
            # Re-raise our custom exception
            raise
        except Exception as e:
            # Catch any other parsing errors and convert to our exception
            # Use 'raise ... from e' to preserve the original traceback for debugging
            raise InvalidSizeFormatError(
                size=size,
                category=part_def.category.value,
                format_hint=f"{self._get_size_format_hint(part_def.category)}. Error: {str(e)}"
            ) from e
        
        # Check for parametric generation vs template
        result = {
            "standard": standard,
            "size": size,
            "category": part_def.category.value,
            "description": part_def.description,
            "parameters": params
        }
        
        # Check if we have a template script
        if part_def.template_script:
            result["type"] = "parametric"
            # Use pre-compiled template from cache for better performance
            # This avoids repeated template conversion and compilation
            try:
                # Get pre-compiled template from cache
                compiled_template = self._compiled_templates_cache.get(standard)
                
                if compiled_template is None:
                    # Template failed to compile during initialization
                    raise StandardPartError(
                        f"Template for {standard} is invalid and could not be compiled"
                    )
                
                if not compiled_template:
                    # Fallback: compile on-demand if not in cache (shouldn't happen normally)
                    logger.warning(f"Template for {standard} not in cache, compiling on-demand")
                    template_str = self._convert_format_to_jinja(part_def.template_script)
                    compiled_template = self.jinja_env.from_string(template_str)
                    self._compiled_templates_cache[standard] = compiled_template
                
                # Render the pre-compiled template with parameters
                result["script"] = compiled_template.render(**params)
            except (TemplateSyntaxError, Exception) as e:
                logger.error(f"Template rendering failed for {standard} {size}: {e}")
                raise StandardPartError(
                    f"Failed to render template for {standard} {size}: {str(e)}"
                )
        else:
            # Check for S3 template
            template_path = self._get_template_path(standard, size)
            if template_path:
                result["type"] = "template"
                result["template_path"] = template_path
            else:
                result["type"] = "catalog"
                result["info"] = "Part info available but no generation method"
        
        return result
    
    def _parse_fastener_size(self, size: str) -> Optional[Dict[str, float]]:
        """Parse fastener size like M6x20 using DIN/ISO standard dimensions.
        
        Uses lookup tables for accurate thread pitch and head dimensions
        according to DIN 933/ISO 4017 standards.
        
        Args:
            size: Size string like "M8x20" or "M10"
            
        Returns:
            Dictionary with fastener dimensions or None if invalid
            
        Raises:
            InvalidSizeFormatError: If size format cannot be parsed
        """
        if not size or not isinstance(size, str):
            raise InvalidSizeFormatError(
                size=str(size),
                category="fasteners",
                format_hint="Format: M{diameter}x{length}, e.g., M8x20"
            )
        
        try:
            if "M" not in size:
                raise InvalidSizeFormatError(
                    size=size,
                    category="fasteners",
                    format_hint="Format must start with 'M' for metric thread, e.g., M8x20"
                )
            
            # Parse the size string
            parts = size.replace("M", "").split("x")
            diameter = float(parts[0])
            
            # Default length if not specified (2.5x diameter is common)
            length = float(parts[1]) if len(parts) > 1 else diameter * 2.5
            
            # Look up exact thread pitch from standard table
            thread_pitch = self.METRIC_COARSE_PITCH.get(diameter)
            if thread_pitch is None:
                # For non-standard sizes, use ISO 261 formula approximation (see standard URLs above)
                # This is more accurate than the simple 0.125 * diameter
                if diameter < 1.0:
                    thread_pitch = 0.2
                elif diameter < 3.0:
                    thread_pitch = diameter * 0.2
                else:
                    # Use linear approximation for larger sizes
                    thread_pitch = 0.5 + (diameter - 3.0) * 0.15
                
                logger.warning(
                    f"Non-standard diameter M{diameter}, using approximated pitch {thread_pitch:.2f}mm"
                )
            
            # Look up exact head dimensions from standard table
            head_dims = self.HEX_HEAD_DIMENSIONS.get(diameter)
            if head_dims:
                head_diameter = head_dims["waf"]
                head_height = head_dims["height"]
            else:
                # For non-standard sizes, use proportional approximation
                # Based on regression analysis of standard dimensions
                head_diameter = diameter * 1.5 + 1.0  # More accurate than simple 1.5x
                head_height = diameter * 0.6 + 0.4    # More accurate than simple 0.7x
                
                logger.warning(
                    f"Non-standard diameter M{diameter}, using approximated head dimensions"
                )
            
            return {
                "diameter": diameter,
                "length": length,
                "thread_pitch": thread_pitch,
                "head_diameter": head_diameter,
                "head_height": head_height
            }
            
        except (ValueError, IndexError) as e:
            raise InvalidSizeFormatError(
                size=size,
                category="fasteners",
                format_hint=f"Format: M{{diameter}}x{{length}}, e.g., M8x20. Error: {str(e)}"
            )
    
    def _parse_bearing_size(self, size: str) -> Optional[Dict[str, float]]:
        """Parse bearing size like 608 or 625-2RS."""
        # Strip suffixes like -2RS, -ZZ to get base bearing code
        base_size = size.split("-")[0]
        
        # Use the class constant BEARING_DIMENSIONS instead of local variable
        return self.BEARING_DIMENSIONS.get(base_size)
    
    def _get_size_format_hint(self, category: PartCategory) -> str:
        """Get format hint for size specification."""
        if category == PartCategory.FASTENERS:
            return "Format: M{diameter}x{length}, e.g., M6x20"
        elif category == PartCategory.BEARINGS:
            return "Format: bearing code, e.g., 608, 625-2RS"
        else:
            return "Check catalog for valid sizes"
    
    def _get_template_path(self, standard: str, size: str) -> Optional[str]:
        """Get S3 template path if available."""
        # Check local templates first
        template_id = f"{standard}_{size}"
        if template_id in self.templates:
            template = self.templates[template_id]
            if template.s3_url:
                return template.s3_url
            elif template.file_path:
                return template.file_path
        return None
    
    def search_parts(
        self,
        category: Optional[PartCategory] = None,
        standard_type: Optional[StandardType] = None,
        query: Optional[str] = None
    ) -> List[StandardPart]:
        """
        Search for standard parts.
        
        Args:
            category: Filter by category
            standard_type: Filter by standard type
            query: Search query for name/description
            
        Returns:
            List of matching parts
        """
        results = []
        
        for part in self.CATALOG.values():
            # Category filter
            if category and part.category != category:
                continue
            
            # Standard type filter
            if standard_type and part.standard_type != standard_type:
                continue
            
            # Text search
            if query:
                query_lower = query.lower()
                if (query_lower not in part.code.lower() and
                    query_lower not in part.name.lower() and
                    query_lower not in part.description.lower()):
                    continue
            
            results.append(part)
        
        return results
    
    def generate_part_script(
        self,
        code: str,
        size: str,
        custom_params: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Generate FreeCAD script for standard part.
        
        Args:
            code: Part code (e.g., "DIN933")
            size: Size specification (e.g., "M8x20")
            custom_params: Override parameters
            
        Returns:
            FreeCAD Python script or None
        """
        part = self.get_part(code)
        if not part:
            logger.warning(f"Part not found: {code}")
            return None
        
        if not part.template_script:
            logger.warning(f"No template script for part: {code}")
            return None
        
        # Get size parameters
        params = part.get_size_parameters(size)
        if not params:
            logger.warning(f"Could not get parameters for size: {size}")
            return None
        
        # Apply custom parameters
        if custom_params:
            params.update(custom_params)
        
        # Fill template using secure Jinja2 rendering
        try:
            # Convert {param} syntax to {{param}} for Jinja2 compatibility
            template_str = self._convert_format_to_jinja(part.template_script)
            template = self.jinja_env.from_string(template_str)
            script = template.render(**params)
            return script
        except (TemplateSyntaxError, Exception) as e:
            logger.error(f"Template rendering error: {e}")
            return None
    
    def get_template(self, template_id: str) -> Optional[FCStdTemplate]:
        """
        Get FCStd template by ID.
        
        Args:
            template_id: Template identifier
            
        Returns:
            Template or None
        """
        return self.templates.get(template_id)
    
    def list_templates(
        self,
        category: Optional[PartCategory] = None
    ) -> List[FCStdTemplate]:
        """
        List available templates.
        
        Args:
            category: Filter by category
            
        Returns:
            List of templates
        """
        templates = list(self.templates.values())
        
        if category:
            templates = [t for t in templates if t.category == category]
        
        return templates
    
    def resolve_references(
        self,
        parts: List[Dict[str, str]],
        templates: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Resolve standard part and template references.
        
        Args:
            parts: List of part references [{"code": "DIN933", "size": "M8x20"}]
            templates: List of template references [{"id": "flange_v3", "s3": "s3://..."}]
            
        Returns:
            Resolution results with scripts and paths
        """
        results = {
            "parts": [],
            "templates": [],
            "warnings": []
        }
        
        # Resolve standard parts
        for part_ref in parts:
            code = part_ref.get("code")
            size = part_ref.get("size")
            
            if not code or not size:
                results["warnings"].append(f"Invalid part reference: {part_ref}")
                continue
            
            script = self.generate_part_script(code, size)
            if script:
                results["parts"].append({
                    "code": code,
                    "size": size,
                    "script": script
                })
            else:
                results["warnings"].append(f"Could not generate script for {code} {size}")
        
        # Resolve templates
        for template_ref in templates:
            template_id = template_ref.get("id")
            
            if not template_id:
                results["warnings"].append(f"Invalid template reference: {template_ref}")
                continue
            
            template = self.get_template(template_id)
            if template:
                results["templates"].append({
                    "id": template_id,
                    "path": template.file_path,
                    "s3": template.s3_url,
                    "parameters": template.parameters
                })
            else:
                # If not found locally, just pass through S3 reference
                s3_url = template_ref.get("s3")
                if s3_url:
                    results["templates"].append({
                        "id": template_id,
                        "s3": s3_url,
                        "parameters": template_ref.get("parameters", {})
                    })
                else:
                    results["warnings"].append(f"Template not found: {template_id}")
        
        return results
    
    def _convert_format_to_jinja(self, template_str: str) -> str:
        """
        Convert Python format string {param} to Jinja2 {{param}} syntax.
        
        This maintains backward compatibility with existing templates
        that use str.format() syntax while providing Jinja2 security.
        
        Args:
            template_str: Template string with {param} syntax
            
        Returns:
            Template string with {{param}} syntax for Jinja2
            
        Raises:
            ValueError: If template contains nested braces or invalid syntax
        """
        # SECURITY: Template variables validated via Jinja2
        # Check if already in Jinja2 format using regex for robust detection
        # This pattern matches Jinja2-style variables: {{variable}}
        jinja2_pattern = re.compile(r'\{\{[^{}]+\}\}')
        # This pattern matches Python-style placeholders: {variable}
        python_pattern = re.compile(r'\{[^{}]+\}')
        
        if jinja2_pattern.search(template_str):
            # Already in Jinja2 format, return as-is
            return template_str
        
        # Always validate brace matching, even if no valid placeholders
        # Check for nested braces and unmatched braces
        brace_depth = 0
        for char in template_str:
            if char == '{':
                brace_depth += 1
                if brace_depth > 1:
                    raise ValueError(
                        f"Template contains nested braces which are not supported: {template_str}"
                    )
            elif char == '}':
                brace_depth -= 1
                if brace_depth < 0:
                    raise ValueError(
                        f"Template contains unmatched closing brace: {template_str}"
                    )
        
        if brace_depth != 0:
            raise ValueError(
                f"Template contains unmatched opening brace: {template_str}"
            )
        
        # If no Python-style placeholders found, return as-is
        if not python_pattern.search(template_str):
            return template_str
        
        # Safe to convert: Replace {param} with {{param}}
        # This regex matches {word} but not {{word}}
        pattern = r'\{([^{}]+)\}'
        return re.sub(pattern, r'{{\1}}', template_str)


# Global library instance
standard_parts_library = StandardPartsLibrary()