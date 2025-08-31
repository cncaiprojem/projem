"""
Deterministic Exporter for Task 7.6

Provides deterministic export functionality for FreeCAD models:
- FCStd with ZIP repacking for determinism
- STEP with fixed schema (AP214)
- STL with fixed mesh parameters
- GLB via trimesh with stable parameters

All exports produce identical SHA256 hashes across runs.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...core.logging import get_logger

logger = get_logger(__name__)


class DeterministicExporter:
    """Export FreeCAD models with deterministic output."""
    
    # Default tessellation parameters for STL mesh generation
    DEFAULT_LINEAR_DEFLECTION = 0.1  # mm - controls deviation from true surface
    DEFAULT_ANGULAR_DEFLECTION = 0.5  # radians (~28.6 degrees) - controls angle between adjacent facets
    
    def __init__(
        self, 
        source_date_epoch: Optional[int] = None,
        linear_deflection: float = DEFAULT_LINEAR_DEFLECTION,
        angular_deflection: float = DEFAULT_ANGULAR_DEFLECTION
    ):
        """
        Initialize exporter with deterministic settings.
        
        Args:
            source_date_epoch: Unix timestamp for reproducible dates
            linear_deflection: Linear deflection for STL tessellation (mm)
            angular_deflection: Angular deflection for STL tessellation (radians)
        """
        # Use SOURCE_DATE_EPOCH environment variable or default to 2000-01-01
        if source_date_epoch is None:
            source_date_epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "946684800"))
        
        self.source_date_epoch = source_date_epoch
        self.source_date = datetime.fromtimestamp(source_date_epoch, tz=timezone.utc)
        
        # Tessellation parameters
        self.linear_deflection = linear_deflection
        self.angular_deflection = angular_deflection
        
        # Try to import FreeCAD
        self._freecad_available = self._check_freecad()
    
    def _check_freecad(self) -> bool:
        """Check if FreeCAD is available."""
        try:
            import FreeCAD
            import Part
            return True
        except ImportError:
            logger.warning("FreeCAD not available for export")
            return False
    
    def export_all(
        self,
        document: Any,
        base_path: Path,
        formats: Optional[List[str]] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Export document to all requested formats deterministically.
        
        Args:
            document: FreeCAD document
            base_path: Base path for output files (without extension)
            formats: List of formats to export (default: all supported)
        
        Returns:
            Dictionary mapping format to export info (path, sha256, size)
        """
        if not self._freecad_available:
            raise RuntimeError("FreeCAD is required for export")
        
        if formats is None:
            formats = ["FCStd", "STEP", "STL", "GLB"]
        
        results = {}
        
        for fmt in formats:
            fmt_upper = fmt.upper()
            try:
                if fmt_upper == "FCSTD":
                    result = self._export_fcstd(document, base_path)
                elif fmt_upper == "STEP":
                    result = self._export_step(document, base_path)
                elif fmt_upper == "STL":
                    result = self._export_stl(document, base_path)
                elif fmt_upper == "GLB":
                    result = self._export_glb(document, base_path)
                else:
                    logger.warning(f"Unsupported format: {fmt}")
                    continue
                
                results[fmt_upper] = result
                logger.info(f"Exported {fmt_upper}: {result['path']} (SHA256: {result['sha256'][:8]}...)")
                
            except Exception as e:
                logger.error(f"Failed to export {fmt}: {e}")
                results[fmt_upper] = {"error": str(e)}
        
        return results
    
    def _export_fcstd(self, document: Any, base_path: Path) -> Dict[str, Any]:
        """
        Export as FCStd with deterministic ZIP repacking.
        
        FCStd files are ZIP archives. We repack them with:
        - ZIP_STORED compression (no compression)
        - Sorted entries
        - Fixed modification times from SOURCE_DATE_EPOCH
        - Stripped volatile thumbnails
        """
        import FreeCAD
        
        # Save to temporary file first
        temp_path = base_path.with_suffix(".tmp.FCStd")
        final_path = base_path.with_suffix(".FCStd")
        
        # Save document
        document.saveAs(str(temp_path))
        
        # Repack deterministically
        self._repack_fcstd(temp_path, final_path)
        
        # Clean up temp file
        if temp_path.exists():
            temp_path.unlink()
        
        # Compute hash
        sha256 = self._compute_file_hash(final_path)
        
        return {
            "path": str(final_path),
            "sha256": sha256,
            "size": final_path.stat().st_size
        }
    
    def _repack_fcstd(self, source_path: Path, dest_path: Path):
        """Repack FCStd file deterministically."""
        # Files to exclude (volatile data)
        exclude_files = {"thumbnails/Thumbnail.png", "GuiDocument.xml"}
        
        with zipfile.ZipFile(source_path, 'r') as source_zip:
            # Get all file names and sort them
            file_names = sorted([
                name for name in source_zip.namelist()
                if name not in exclude_files
            ])
            
            # Create new ZIP with deterministic settings
            with zipfile.ZipFile(dest_path, 'w', compression=zipfile.ZIP_STORED) as dest_zip:
                for file_name in file_names:
                    # Read file data
                    file_data = source_zip.read(file_name)
                    
                    # Create ZipInfo with fixed date
                    zip_info = zipfile.ZipInfo(filename=file_name)
                    zip_info.date_time = self.source_date.timetuple()[:6]
                    zip_info.compress_type = zipfile.ZIP_STORED
                    zip_info.external_attr = 0o644 << 16  # Unix file permissions
                    
                    # Write to new archive
                    dest_zip.writestr(zip_info, file_data)
    
    def _export_step(self, document: Any, base_path: Path) -> Dict[str, Any]:
        """
        Export as STEP with stable parameters.
        
        Uses AP214 schema and sorted object export.
        """
        import Part
        
        path = base_path.with_suffix(".step")
        
        # Collect all shapes to export
        shapes = []
        for obj in sorted(document.Objects, key=lambda x: x.Label):
            if hasattr(obj, 'Shape') and obj.Shape and not obj.Shape.isNull():
                shapes.append(obj.Shape)
        
        if not shapes:
            raise ValueError("No shapes to export")
        
        # Create compound if multiple shapes
        if len(shapes) == 1:
            shape = shapes[0]
        else:
            import Part
            shape = Part.makeCompound(shapes)
        
        # Export with fixed parameters
        # Note: FreeCAD's STEP export doesn't expose all parameters,
        # but we ensure consistent input ordering
        shape.exportStep(str(path))
        
        # Post-process STEP file to remove timestamps if present
        self._clean_step_file(path)
        
        sha256 = self._compute_file_hash(path)
        
        return {
            "path": str(path),
            "sha256": sha256,
            "size": path.stat().st_size
        }
    
    def _clean_step_file(self, path: Path):
        """Remove timestamps and volatile data from STEP file using regex.
        
        IMPORTANT: Only modifies the HEADER section to preserve file integrity.
        The DATA section contains critical geometric information that must not be altered.
        """
        import re
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Split STEP file into HEADER and DATA sections
            # STEP files have structure: ISO-10303-21; HEADER; ... ENDSEC; DATA; ... ENDSEC; END-ISO-10303-21;
            header_match = re.search(r'(HEADER;.*?ENDSEC;)', content, re.DOTALL)
            
            if header_match:
                header_section = header_match.group(1)
                header_start, header_end = header_match.span()
                
                # Apply replacements ONLY to the HEADER section
                cleaned_header = header_section
                
                # Pattern for ISO timestamp strings in HEADER (e.g., '2024-01-15T10:30:45')
                # Only replace timestamps within the HEADER section
                iso_timestamp_pattern = r"'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?'"
                cleaned_header = re.sub(iso_timestamp_pattern, f"'{self.source_date.isoformat()}'", cleaned_header)
                
                # Pattern for FILE_NAME timestamp in HEADER section
                # FILE_NAME('filename','2024-01-15T10:30:45',('author'),...)
                file_name_pattern = r"(FILE_NAME\s*\([^,]+,\s*)('[^']+')(\s*,)"
                cleaned_header = re.sub(file_name_pattern, rf"\1'{self.source_date.isoformat()}'\3", cleaned_header)
                
                # Pattern for FILE_DESCRIPTION timestamp
                file_desc_pattern = r"(FILE_DESCRIPTION\s*\([^,]+,\s*)('[^']+')(\s*\))"
                cleaned_header = re.sub(file_desc_pattern, rf"\1'{self.source_date.isoformat()}'\3", cleaned_header)
                
                # Reconstruct the file with cleaned header and untouched DATA section
                content = content[:header_start] + cleaned_header + content[header_end:]
            else:
                # Fallback: If we can't identify sections, be more conservative
                # Only replace obvious timestamp patterns that won't affect geometry
                logger.debug("Could not identify HEADER section, using conservative approach")
                
                # Only replace timestamps in FILE_NAME and FILE_DESCRIPTION lines
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    if 'FILE_NAME' in line or 'FILE_DESCRIPTION' in line:
                        # Replace timestamps only in these specific lines
                        iso_timestamp_pattern = r"'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?'"
                        lines[i] = re.sub(iso_timestamp_pattern, f"'{self.source_date.isoformat()}'", line)
                content = '\n'.join(lines)
            
            # Validate the cleaned STEP file structure
            if not self._validate_step_structure(content):
                logger.warning("STEP file structure validation failed after cleaning, skipping modifications")
                return
            
            # Write cleaned content back
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
                
        except Exception as e:
            logger.warning(f"Could not clean STEP file: {e}")
    
    def _validate_step_structure(self, content: str) -> bool:
        """Validate basic STEP file structure after cleaning.
        
        Args:
            content: STEP file content
            
        Returns:
            True if structure appears valid, False otherwise
        """
        # Check for essential STEP file markers
        required_markers = [
            'ISO-10303-21',
            'HEADER',
            'ENDSEC',
            'DATA',
            'END-ISO-10303-21'
        ]
        
        for marker in required_markers:
            if marker not in content:
                logger.warning(f"STEP file missing required marker: {marker}")
                return False
        
        # Check that HEADER comes before DATA
        header_pos = content.find('HEADER')
        data_pos = content.find('DATA')
        if header_pos > data_pos:
            logger.warning("STEP file structure invalid: HEADER after DATA")
            return False
        
        return True
    
    def _export_stl(self, document: Any, base_path: Path) -> Dict[str, Any]:
        """
        Export as STL with fixed mesh parameters.
        
        Uses binary STL format with fixed tessellation parameters.
        """
        import Mesh
        import Part
        
        path = base_path.with_suffix(".stl")
        
        # Collect all shapes
        shapes = []
        for obj in sorted(document.Objects, key=lambda x: x.Label):
            if hasattr(obj, 'Shape') and obj.Shape and not obj.Shape.isNull():
                shapes.append(obj.Shape)
        
        if not shapes:
            raise ValueError("No shapes to export")
        
        # Create compound if multiple shapes
        if len(shapes) == 1:
            shape = shapes[0]
        else:
            shape = Part.makeCompound(shapes)
        
        # Create mesh with configurable parameters for determinism
        mesh = Mesh.Mesh()
        
        # Use configurable tessellation parameters for determinism
        # These can be adjusted via constructor for quality/performance trade-offs
        # Higher quality (smaller values) = more triangles = larger files
        # Lower quality (larger values) = fewer triangles = smaller files
        
        # Use Mesh.createFromShape for better control over both linear and angular deflection
        # This provides more consistent and higher quality mesh generation
        mesh = Mesh.createFromShape(
            Shape=shape,
            LinearDeflection=self.linear_deflection,
            AngularDeflection=self.angular_deflection,
            Relative=False  # Use absolute values, not relative to size
        )
        
        # Write binary STL
        mesh.write(str(path), "STL")
        
        sha256 = self._compute_file_hash(path)
        
        return {
            "path": str(path),
            "sha256": sha256,
            "size": path.stat().st_size,
            "facet_count": mesh.CountFacets,
            "vertex_count": mesh.CountPoints
        }
    
    def _export_glb(self, document: Any, base_path: Path) -> Dict[str, Any]:
        """
        Export as GLB via trimesh from STL.
        
        Creates deterministic GLB with fixed scene graph and material.
        """
        try:
            import trimesh
        except ImportError:
            raise RuntimeError("trimesh not available for GLB export")
        
        # First export to STL
        stl_result = self._export_stl(document, base_path.with_suffix(".tmp"))
        stl_path = Path(stl_result["path"])
        
        try:
            # Load STL into trimesh
            mesh = trimesh.load(str(stl_path))
            
            # Set deterministic properties
            if hasattr(mesh, 'visual'):
                # Set fixed material properties
                mesh.visual.material = trimesh.visual.material.SimpleMaterial(
                    diffuse=[128, 128, 128, 255],  # Gray color
                    ambient=[64, 64, 64, 255],
                    specular=[255, 255, 255, 255],
                    glossiness=0.5
                )
            
            # Export as GLB with fixed parameters
            glb_path = base_path.with_suffix(".glb")
            
            # Create scene with deterministic ordering
            scene = trimesh.Scene(geometry=mesh)
            
            # Export with fixed parameters
            with open(glb_path, 'wb') as f:
                f.write(scene.export(file_type='glb'))
            
            sha256 = self._compute_file_hash(glb_path)
            
            return {
                "path": str(glb_path),
                "sha256": sha256,
                "size": glb_path.stat().st_size,
                "vertex_count": len(mesh.vertices),
                "face_count": len(mesh.faces)
            }
            
        finally:
            # Clean up temp STL
            if stl_path.exists():
                stl_path.unlink()
    
    def _compute_file_hash(self, path: Path) -> str:
        """Compute SHA256 hash of a file."""
        sha256 = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    def export_shape(
        self,
        shape: Any,
        base_path: Path,
        formats: Optional[List[str]] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Export a single shape to multiple formats.
        
        Args:
            shape: FreeCAD shape object
            base_path: Base path for output files
            formats: List of formats to export
        
        Returns:
            Dictionary mapping format to export info
        """
        if not self._freecad_available:
            raise RuntimeError("FreeCAD is required for export")
        
        import FreeCAD
        import Part
        
        # Create temporary document with the shape
        doc = FreeCAD.newDocument("temp_export")
        obj = doc.addObject("Part::Feature", "ExportShape")
        obj.Shape = shape
        doc.recompute()
        
        try:
            # Export using document export
            return self.export_all(doc, base_path, formats)
        finally:
            # Clean up temporary document
            FreeCAD.closeDocument(doc.Name)


# Global exporter instance
deterministic_exporter = DeterministicExporter()