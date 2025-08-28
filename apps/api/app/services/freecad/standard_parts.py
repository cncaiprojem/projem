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
    
    # Catalog of common DIN/ISO parts
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

doc = App.newDocument("DIN933_Bolt")

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
Part.show(bolt)
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
                    with open(metadata_file, 'r') as f:
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
    
    def get_part(self, code: str) -> Optional[StandardPart]:
        """
        Get standard part by code.
        
        Args:
            code: Part code (e.g., "DIN933")
            
        Returns:
            Standard part definition or None
        """
        return self.CATALOG.get(code)
    
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