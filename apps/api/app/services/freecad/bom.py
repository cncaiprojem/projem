"""
BOM (Bill of Materials) Extraction for Task 7.6

Provides BOM extraction functionality:
- Assembly tree traversal
- Part grouping by fingerprint
- Deterministic ordering
- CSV and JSON export formats
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from ...core.logging import get_logger

logger = get_logger(__name__)


class BOMItem(BaseModel):
    """Single item in Bill of Materials."""
    item_id: str = Field(description="Unique item identifier")
    designation: str = Field(description="Part designation/name")
    quantity: int = Field(description="Quantity required")
    standard: Optional[str] = Field(default=None, description="Standard (e.g., DIN933)")
    size: Optional[str] = Field(default=None, description="Size specification")
    material: Optional[str] = Field(default=None, description="Material")
    finish: Optional[str] = Field(default=None, description="Surface finish")
    refdes_paths: List[str] = Field(default_factory=list, description="Reference designator paths")
    fingerprint: str = Field(description="SHA256 fingerprint of source")
    mass: Optional[float] = Field(default=None, description="Mass in grams")
    volume: Optional[float] = Field(default=None, description="Volume in mm³")
    source_type: str = Field(description="Source type: parametric, standard, custom")
    source_file: Optional[str] = Field(default=None, description="Source file path")


class BOMSummary(BaseModel):
    """BOM summary with totals."""
    total_items: int = Field(description="Total unique items")
    total_quantity: int = Field(description="Total parts count")
    total_mass: Optional[float] = Field(default=None, description="Total mass in grams")
    total_volume: Optional[float] = Field(default=None, description="Total volume in mm³")
    has_missing_data: bool = Field(description="Whether any items have missing data")


class BillOfMaterials(BaseModel):
    """Complete Bill of Materials."""
    project: str = Field(description="Project name")
    assembly: str = Field(description="Assembly name")
    version: str = Field(description="BOM version")
    items: List[BOMItem] = Field(description="BOM items")
    summary: BOMSummary = Field(description="BOM summary")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class BOMExtractor:
    """Extract Bill of Materials from FreeCAD assemblies."""
    
    # Material densities in g/cm³ (class constant for consistency)
    MATERIAL_DENSITIES = {
        "steel": 7.85,
        "aluminum": 2.70,
        "brass": 8.40,
        "copper": 8.96,
        "abs": 1.04,
        "pla": 1.25,
        "petg": 1.27,
        "nylon": 1.14,
    }
    
    def __init__(self):
        """Initialize BOM extractor."""
        self._freecad_available = self._check_freecad()
    
    def _check_freecad(self) -> bool:
        """Check if FreeCAD is available."""
        try:
            import FreeCAD
            return True
        except ImportError:
            logger.warning("FreeCAD not available for BOM extraction")
            return False
    
    def extract_bom(
        self,
        document: Any,
        project_name: str = "Project",
        assembly_name: str = "Assembly",
        version: str = "1.0"
    ) -> BillOfMaterials:
        """
        Extract BOM from FreeCAD document.
        
        Args:
            document: FreeCAD document
            project_name: Project name
            assembly_name: Assembly name
            version: BOM version
        
        Returns:
            Bill of Materials
        """
        if not self._freecad_available:
            raise RuntimeError("FreeCAD is required for BOM extraction")
        
        # Traverse assembly tree
        items_dict = {}  # fingerprint -> BOMItem
        self._traverse_assembly(document.RootObjects, items_dict, "")
        
        # Convert to list with deterministic ordering
        items = sorted(items_dict.values(), key=lambda x: (x.designation, x.size or ""))
        
        # Calculate summary
        summary = self._calculate_summary(items)
        
        # Create BOM with deterministic timestamp from SOURCE_DATE_EPOCH
        # This ensures reproducible builds and consistent output
        source_date_epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "946684800"))  # Default: 2000-01-01
        extraction_date = datetime.fromtimestamp(source_date_epoch, tz=timezone.utc).isoformat()
        
        bom = BillOfMaterials(
            project=project_name,
            assembly=assembly_name,
            version=version,
            items=items,
            summary=summary,
            metadata={
                "extraction_date": extraction_date,
                "document_name": document.Name if hasattr(document, 'Name') else "Unknown"
            }
        )
        
        return bom
    
    def _traverse_assembly(
        self,
        objects: List[Any],
        items_dict: Dict[str, BOMItem],
        parent_path: str,
        visited: Optional[Set[str]] = None
    ):
        """
        Recursively traverse assembly tree.
        
        Args:
            objects: List of FreeCAD objects
            items_dict: Dictionary to accumulate items (by fingerprint)
            parent_path: Parent reference designator path
            visited: Set of visited object IDs to prevent cycles
        """
        if visited is None:
            visited = set()
        
        for obj in objects:
            # Skip if already visited (prevent cycles)
            obj_id = id(obj)
            if obj_id in visited:
                continue
            visited.add(obj_id)
            
            # Build reference path
            refdes = obj.Label if hasattr(obj, 'Label') else str(obj_id)
            current_path = f"{parent_path}/{refdes}" if parent_path else refdes
            
            # Check if it's a part or assembly
            if self._is_part(obj):
                # Extract part information
                part_info = self._extract_part_info(obj)
                fingerprint = part_info["fingerprint"]
                
                # Add or update item
                if fingerprint in items_dict:
                    # Update existing item
                    items_dict[fingerprint].quantity += 1
                    items_dict[fingerprint].refdes_paths.append(current_path)
                else:
                    # Create new item
                    items_dict[fingerprint] = BOMItem(
                        item_id=f"ITEM_{len(items_dict) + 1:04d}",
                        designation=part_info["designation"],
                        quantity=1,
                        standard=part_info.get("standard"),
                        size=part_info.get("size"),
                        material=part_info.get("material"),
                        finish=part_info.get("finish"),
                        refdes_paths=[current_path],
                        fingerprint=fingerprint,
                        mass=part_info.get("mass"),
                        volume=part_info.get("volume"),
                        source_type=part_info.get("source_type", "custom"),
                        source_file=part_info.get("source_file")
                    )
            
            # Check for App::Link (lightweight references)
            if hasattr(obj, 'LinkedObject') and obj.LinkedObject:
                # Follow link
                self._traverse_assembly(
                    [obj.LinkedObject],
                    items_dict,
                    current_path,
                    visited
                )
            
            # Check for nested assemblies
            if hasattr(obj, 'Group'):
                self._traverse_assembly(
                    obj.Group,
                    items_dict,
                    current_path,
                    visited
                )
            
            # Check for App::Part containers
            if obj.TypeId == "App::Part" and hasattr(obj, 'Group'):
                self._traverse_assembly(
                    obj.Group,
                    items_dict,
                    current_path,
                    visited
                )
    
    def _is_part(self, obj: Any) -> bool:
        """Check if object is a part (not an assembly container)."""
        # Check for shape
        if not hasattr(obj, 'Shape') or not obj.Shape or obj.Shape.isNull():
            return False
        
        # Skip assemblies and containers
        if obj.TypeId in ["App::Part", "App::DocumentObjectGroup"]:
            return False
        
        # Skip links (they reference other parts)
        if hasattr(obj, 'LinkedObject') and obj.LinkedObject:
            return False
        
        return True
    
    def _extract_part_info(self, obj: Any) -> Dict[str, Any]:
        """Extract information from a part object."""
        info = {
            "designation": obj.Label if hasattr(obj, 'Label') else "Unknown",
            "fingerprint": self._compute_fingerprint(obj)
        }
        
        # Extract standard part info if available
        if hasattr(obj, 'Standard'):
            info["standard"] = obj.Standard
        if hasattr(obj, 'Size'):
            info["size"] = obj.Size
        
        # Extract material
        if hasattr(obj, 'Material'):
            info["material"] = obj.Material
        elif hasattr(obj, 'MaterialName'):
            info["material"] = obj.MaterialName
        
        # Extract finish
        if hasattr(obj, 'Finish'):
            info["finish"] = obj.Finish
        elif hasattr(obj, 'SurfaceFinish'):
            info["finish"] = obj.SurfaceFinish
        
        # Calculate volume and mass
        if hasattr(obj, 'Shape') and obj.Shape:
            try:
                volume = obj.Shape.Volume  # mm³
                info["volume"] = volume
                
                # Calculate mass if material is known
                material = info.get("material", "").lower()
                if material in self.MATERIAL_DENSITIES:
                    density = self.MATERIAL_DENSITIES[material]
                    mass = volume * density / 1000  # Convert mm³ to cm³
                    info["mass"] = mass
            except Exception as e:
                logger.debug(f"Could not calculate volume/mass: {e}")
        
        # Determine source type
        if info.get("standard"):
            info["source_type"] = "standard"
        elif hasattr(obj, 'SourceType'):
            info["source_type"] = obj.SourceType
        else:
            info["source_type"] = "custom"
        
        # Get source file if available
        if hasattr(obj, 'SourceFile'):
            info["source_file"] = obj.SourceFile
        
        return info
    
    def _compute_fingerprint(self, obj: Any) -> str:
        """
        Compute SHA256 fingerprint for a part.
        
        Based on shape geometry and configuration.
        """
        hasher = hashlib.sha256()
        
        # Include object type
        hasher.update(obj.TypeId.encode('utf-8'))
        
        # Include shape data if available
        if hasattr(obj, 'Shape') and obj.Shape:
            try:
                # Use in-memory BREP export to avoid disk I/O
                brep_success = False
                if hasattr(obj.Shape, 'exportBrepToString'):
                    # Use exportBrepToString for in-memory operations (performance optimization)
                    try:
                        brep_string = obj.Shape.exportBrepToString()
                        hasher.update(brep_string.encode('utf-8'))
                        brep_success = True
                    except Exception as e:
                        # Handle BREP export failures gracefully
                        logger.debug(f"BREP in-memory export failed, falling back to bbox dimensions: {e}")
                        brep_success = False
                elif hasattr(obj.Shape, 'exportBrep'):
                    # Fallback to disk-based export only if in-memory not available
                    import tempfile
                    import os as os_module  # Alias to avoid conflict with FreeCAD os
                    
                    with tempfile.NamedTemporaryFile(suffix='.brep', delete=False) as tmp_file:
                        tmp_path = tmp_file.name
                    
                    brep_success = False
                    try:
                        obj.Shape.exportBrep(tmp_path)
                        with open(tmp_path, 'rb') as f:
                            hasher.update(f.read())
                        brep_success = True
                    except Exception as e:
                        # Handle BREP export failures gracefully
                        logger.debug(f"BREP export failed, falling back to bbox dimensions: {e}")
                    finally:
                        # Resource cleanup MUST be in finally block to guarantee execution
                        # This ensures cleanup happens even if unexpected errors occur
                        try:
                            if os_module.path.exists(tmp_path):
                                os_module.unlink(tmp_path)
                        except Exception as cleanup_error:
                            # Log cleanup failures but don't raise - cleanup is best-effort
                            logger.debug(f"Failed to clean up temporary file {tmp_path}: {cleanup_error}")
                    
                    # Fallback to bounding box dimensions if BREP export failed
                    if not brep_success:
                        bbox = obj.Shape.BoundBox
                        batch_data = '|'.join([
                            str(obj.Shape.Volume),
                            str(obj.Shape.Area),
                            str(bbox.XLength),
                            str(bbox.YLength),
                            str(bbox.ZLength)
                        ])
                        hasher.update(batch_data.encode('utf-8'))
                else:
                    # Fallback: use basic properties including bounding box dimensions
                    # Batch hash updates with delimiter for efficiency
                    bbox = obj.Shape.BoundBox
                    batch_data = '|'.join([
                        str(obj.Shape.Volume),
                        str(obj.Shape.Area),
                        str(bbox.XLength),
                        str(bbox.YLength),
                        str(bbox.ZLength)
                    ])
                    hasher.update(batch_data.encode('utf-8'))
            except Exception as e:
                logger.debug(f"Could not hash shape: {e}")
        
        # Include configuration parameters
        if hasattr(obj, 'Standard'):
            hasher.update(str(obj.Standard).encode('utf-8'))
        if hasattr(obj, 'Size'):
            hasher.update(str(obj.Size).encode('utf-8'))
        if hasattr(obj, 'Material'):
            hasher.update(str(obj.Material).encode('utf-8'))
        
        return hasher.hexdigest()
    
    def _calculate_summary(self, items: List[BOMItem]) -> BOMSummary:
        """Calculate BOM summary statistics."""
        total_quantity = sum(item.quantity for item in items)
        total_mass = None
        total_volume = None
        has_missing_data = False
        
        # Calculate totals if all data available
        all_have_mass = all(item.mass is not None for item in items)
        all_have_volume = all(item.volume is not None for item in items)
        
        if all_have_mass:
            total_mass = sum(item.mass * item.quantity for item in items)
        else:
            has_missing_data = True
        
        if all_have_volume:
            total_volume = sum(item.volume * item.quantity for item in items)
        else:
            has_missing_data = True
        
        return BOMSummary(
            total_items=len(items),
            total_quantity=total_quantity,
            total_mass=total_mass,
            total_volume=total_volume,
            has_missing_data=has_missing_data
        )
    
    def export_csv(self, bom: BillOfMaterials, file_path: Path):
        """
        Export BOM to CSV format.
        
        Args:
            bom: Bill of Materials
            file_path: Output CSV file path
        """
        with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'Item', 'Designation', 'Quantity', 'Standard', 'Size',
                'Material', 'Finish', 'Mass (g)', 'Volume (mm³)', 'RefDes'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            # Write header
            writer.writeheader()
            
            # Write items
            for item in bom.items:
                writer.writerow({
                    'Item': item.item_id,
                    'Designation': item.designation,
                    'Quantity': item.quantity,
                    'Standard': item.standard or '',
                    'Size': item.size or '',
                    'Material': item.material or '',
                    'Finish': item.finish or '',
                    'Mass (g)': f"{item.mass:.2f}" if item.mass else '',
                    'Volume (mm³)': f"{item.volume:.2f}" if item.volume else '',
                    'RefDes': '; '.join(item.refdes_paths[:3])  # First 3 refs
                })
            
            # Write summary
            writer.writerow({})  # Empty row
            writer.writerow({
                'Item': 'TOTAL',
                'Quantity': bom.summary.total_quantity,
                'Mass (g)': f"{bom.summary.total_mass:.2f}" if bom.summary.total_mass else '',
                'Volume (mm³)': f"{bom.summary.total_volume:.2f}" if bom.summary.total_volume else ''
            })
    
    def export_json(self, bom: BillOfMaterials, file_path: Path):
        """
        Export BOM to JSON format.
        
        Args:
            bom: Bill of Materials
            file_path: Output JSON file path
        """
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(bom.dict(), f, indent=2, ensure_ascii=False)


# Global BOM extractor instance
bom_extractor = BOMExtractor()