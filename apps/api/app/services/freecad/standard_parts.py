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
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from ...core.logging import get_logger

logger = get_logger(__name__)


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

# Use provided document and component ID from the caller context.
# Variables 'doc' and 'comp_id' are injected during script execution.

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

# Use provided document and component ID from the caller context.
# Variables 'doc' and 'comp_id' are injected during script execution.

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
        self._load_templates()
    
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
            # Return error with known standards
            known = list(self.CATALOG.keys())
            logger.warning(f"Unknown standard: {standard}. Known: {known}")
            return {
                "error": f"Unknown standard: {standard}",
                "known_standards": known
            }
        
        # Check if size is supported
        if size not in part_def.sizes:
            return {
                "error": f"Size {size} not available for {standard}",
                "available_sizes": part_def.sizes
            }
        
        # Parse size parameters based on part type
        if part_def.category == PartCategory.FASTENERS:
            params = self._parse_fastener_size(size)
        elif part_def.category == PartCategory.BEARINGS:
            params = self._parse_bearing_size(size)
        else:
            params = part_def.get_size_parameters(size)
        
        if not params:
            return {
                "error": f"Could not parse size: {size}",
                "format_hint": self._get_size_format_hint(part_def.category)
            }
        
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
            result["script"] = part_def.template_script.format(**params)
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
        """Parse fastener size like M6x20."""
        try:
            if "M" in size:
                parts = size.replace("M", "").split("x")
                diameter = float(parts[0])
                length = float(parts[1]) if len(parts) > 1 else diameter * 2.5
                
                return {
                    "diameter": diameter,
                    "length": length,
                    "thread_pitch": diameter * 0.125,  # Standard coarse pitch
                    "head_diameter": diameter * 1.5,   # Hex head approx
                    "head_height": diameter * 0.7      # Standard proportion
                }
        except (ValueError, IndexError):
            return None
        return None
    
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
        
        # Fill template
        try:
            script = part.template_script.format(**params)
            return script
        except KeyError as e:
            logger.error(f"Missing parameter in template: {e}")
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


# Global library instance
standard_parts_library = StandardPartsLibrary()