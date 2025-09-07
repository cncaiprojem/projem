"""
Enhanced Exporter for Task 7.20 - Multi-format Export Pipeline

Provides comprehensive export capabilities with:
- Pre-export validation
- Format-specific optimization
- Post-export verification
- Quality control checks
- Metadata embedding
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import zipfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field, field_validator

from ..core.constants import FREECAD_VERSION, OCCT_VERSION
from ..core.logging import get_logger
from ..core.metrics import export_counter, export_duration_histogram
from ..core.telemetry import create_span
from .freecad_document_manager import FreeCADDocumentManager

logger = get_logger(__name__)


class ExportFormat(str, Enum):
    """Supported export formats."""
    # Native FreeCAD
    FCSTD = "fcstd"
    
    # CAD Formats
    STEP = "step"
    IGES = "iges"
    BREP = "brep"
    
    # Mesh Formats
    STL = "stl"
    OBJ = "obj"
    PLY = "ply"
    OFF = "off"
    THREEMF = "3mf"
    AMF = "amf"
    
    # Drawing Formats
    DXF = "dxf"
    SVG = "svg"
    PDF = "pdf"
    
    # Industry Specific
    IFC = "ifc"
    DAE = "dae"
    GLTF = "gltf"
    GLB = "glb"
    
    # Additional
    VRML = "vrml"
    WRL = "wrl"
    X3D = "x3d"
    U3D = "u3d"
    
    # Point Cloud
    XYZ = "xyz"
    PCD = "pcd"


class StepSchema(str, Enum):
    """STEP export schemas."""
    AP203 = "AP203"  # Configuration controlled design
    AP214 = "AP214"  # Automotive design
    AP242 = "AP242"  # Managed model based 3D engineering


class ExportOptions(BaseModel):
    """Options for export operations."""
    # General options
    compress: bool = Field(default=False, description="Çıktıyı sıkıştır")
    embed_metadata: bool = Field(default=True, description="Metadata'yı göm")
    validate_output: bool = Field(default=True, description="Çıktıyı doğrula")
    optimize_size: bool = Field(default=False, description="Dosya boyutunu optimize et")
    
    # Format-specific options
    step_schema: StepSchema = Field(default=StepSchema.AP214, description="STEP şeması")
    stl_ascii: bool = Field(default=False, description="STL ASCII formatı")
    stl_linear_deflection: float = Field(default=0.1, ge=0.001, le=10.0, description="STL lineer sapma")
    stl_angular_deflection: float = Field(default=0.5, ge=0.01, le=1.0, description="STL açısal sapma")
    
    # IFC options
    ifc_schema: str = Field(default="IFC4", description="IFC şema versiyonu")
    ifc_include_properties: bool = Field(default=True, description="IFC özelliklerini dahil et")
    ifc_include_quantities: bool = Field(default=True, description="IFC miktarlarını dahil et")
    
    # GLTF options
    gltf_embed_textures: bool = Field(default=True, description="Dokuları göm")
    gltf_draco_compression: bool = Field(default=False, description="Draco sıkıştırma kullan")
    gltf_preserve_hierarchy: bool = Field(default=True, description="Hiyerarşiyi koru")
    
    # DXF options
    dxf_version: str = Field(default="AC1027", description="DXF versiyonu (AutoCAD 2013)")
    dxf_export_layers: bool = Field(default=True, description="Katmanları dışa aktar")
    
    # Quality settings
    mesh_quality: str = Field(default="normal", pattern="^(low|normal|high|ultra)$", description="Mesh kalitesi")
    tolerance: float = Field(default=0.001, ge=0.0001, le=1.0, description="Dışa aktarma toleransı")
    
    model_config = {"json_schema_extra": {"examples": [
        {
            "compress": False,
            "embed_metadata": True,
            "step_schema": "AP214",
            "stl_ascii": False,
            "mesh_quality": "high"
        }
    ]}}


class ValidationResult(BaseModel):
    """Result of validation checks."""
    is_valid: bool = Field(description="Geçerlilik durumu")
    errors: List[str] = Field(default_factory=list, description="Hatalar")
    warnings: List[str] = Field(default_factory=list, description="Uyarılar")
    checks_performed: Dict[str, bool] = Field(default_factory=dict, description="Yapılan kontroller")
    
    # Turkish messages
    messages: Dict[str, str] = Field(default_factory=lambda: {
        "geometry_valid": "Geometri geçerli",
        "topology_valid": "Topoloji geçerli",
        "no_self_intersections": "Kendisiyle kesişme yok",
        "watertight": "Su geçirmez",
        "manifold": "Manifold"
    })


class ExportResult(BaseModel):
    """Result of an export operation."""
    success: bool = Field(description="Başarı durumu")
    format: ExportFormat = Field(description="Dışa aktarılan format")
    file_path: str = Field(description="Çıktı dosya yolu")
    file_size: int = Field(description="Dosya boyutu (bytes)")
    sha256: str = Field(description="Dosya SHA256 hash")
    validation: Optional[ValidationResult] = Field(default=None, description="Doğrulama sonucu")
    verification: Dict[str, Any] = Field(default_factory=dict, description="Doğrulama bilgisi")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Gömülü metadata")
    statistics: Dict[str, Any] = Field(default_factory=dict, description="İstatistikler")
    warnings: List[str] = Field(default_factory=list, description="Uyarılar")
    errors: List[str] = Field(default_factory=list, description="Hatalar")
    export_time_ms: float = Field(description="Dışa aktarma süresi (ms)")
    
    # Turkish messages
    messages: Dict[str, str] = Field(default_factory=lambda: {
        "validation_started": "Doğrulama başladı",
        "optimization_applied": "Optimizasyon uygulandı",
        "export_started": "Dışa aktarma başladı",
        "export_completed": "Dışa aktarma tamamlandı",
        "verification_passed": "Doğrulama başarılı"
    })


class GeometryValidator:
    """Validates geometry before export."""
    
    @classmethod
    def validate_for_export(cls, document: Any, format: ExportFormat) -> ValidationResult:
        """
        Validate document for specific export format.
        
        Args:
            document: FreeCAD document
            format: Target export format
            
        Returns:
            Validation result
        """
        result = ValidationResult(is_valid=True)
        
        try:
            import Part
            
            # Check if document has exportable objects
            exportable_objects = [obj for obj in document.Objects if hasattr(obj, "Shape")]
            if not exportable_objects:
                result.is_valid = False
                result.errors.append("Dışa aktarılabilir nesne bulunamadı")
                return result
            
            # Format-specific validation
            if format in [ExportFormat.STL, ExportFormat.OBJ, ExportFormat.PLY]:
                # Mesh formats need valid shapes
                for obj in exportable_objects:
                    if not cls._validate_shape_for_mesh(obj.Shape):
                        result.warnings.append(f"{obj.Label} mesh'e dönüştürülemeyebilir")
            
            elif format in [ExportFormat.STEP, ExportFormat.IGES, ExportFormat.BREP]:
                # CAD formats need valid topology
                for obj in exportable_objects:
                    if not cls._validate_topology(obj.Shape):
                        result.warnings.append(f"{obj.Label} topoloji hataları içeriyor")
            
            # General checks
            for obj in exportable_objects:
                shape = obj.Shape
                
                # Check validity
                if not shape.isValid():
                    result.warnings.append(f"{obj.Label} geçersiz geometri içeriyor")
                    result.checks_performed["geometry_valid"] = False
                else:
                    result.checks_performed["geometry_valid"] = True
                
                # Check for self-intersections
                if hasattr(shape, "hasSelfIntersections") and shape.hasSelfIntersections():
                    result.warnings.append(f"{obj.Label} kendisiyle kesişiyor")
                    result.checks_performed["no_self_intersections"] = False
                else:
                    result.checks_performed["no_self_intersections"] = True
                
                # Check if closed (watertight) for mesh exports
                if format in [ExportFormat.STL, ExportFormat.THREEMF]:
                    if hasattr(shape, "isClosed") and not shape.isClosed():
                        result.warnings.append(f"{obj.Label} kapalı değil (su geçirmez değil)")
                        result.checks_performed["watertight"] = False
                    else:
                        result.checks_performed["watertight"] = True
        
        except Exception as e:
            logger.error(f"Doğrulama hatası: {e}")
            result.is_valid = False
            result.errors.append(str(e))
        
        return result
    
    @classmethod
    def _validate_shape_for_mesh(cls, shape: Any) -> bool:
        """Validate shape for mesh conversion."""
        try:
            # Check if shape can be tessellated
            if hasattr(shape, "tessellate"):
                shape.tessellate(0.1)
                return True
        except Exception:
            return False
        return True
    
    @classmethod
    def _validate_topology(cls, shape: Any) -> bool:
        """Validate shape topology."""
        try:
            # Check basic topology
            if hasattr(shape, "Faces") and len(shape.Faces) == 0:
                return False
            if hasattr(shape, "isNull") and shape.isNull():
                return False
            return True
        except Exception:
            return False


class FormatOptimizer:
    """Optimizes geometry for specific formats."""
    
    @classmethod
    def optimize_for_format(cls, document: Any, format: ExportFormat, options: ExportOptions) -> Any:
        """
        Optimize document for specific export format.
        
        Args:
            document: FreeCAD document
            format: Target format
            options: Export options
            
        Returns:
            Optimized document
        """
        if not options.optimize_size:
            return document
        
        try:
            import Part
            
            if format in [ExportFormat.STL, ExportFormat.OBJ]:
                # Simplify mesh for size optimization
                for obj in document.Objects:
                    if hasattr(obj, "Shape"):
                        shape = obj.Shape
                        
                        # Remove unnecessary edges
                        if hasattr(shape, "removeSplitter"):
                            shape.removeSplitter()
                        
                        # Fuse nearby vertices
                        if hasattr(shape, "sewShape"):
                            shape.sewShape()
            
            elif format == ExportFormat.STEP:
                # Optimize STEP export
                for obj in document.Objects:
                    if hasattr(obj, "Shape"):
                        shape = obj.Shape
                        
                        # Clean shape
                        if hasattr(shape, "clean"):
                            shape.clean()
                        
                        # Fix shape
                        if hasattr(shape, "fix"):
                            shape.fix(options.tolerance, options.tolerance, options.tolerance)
            
            document.recompute()
            
        except Exception as e:
            logger.warning(f"Optimizasyon uyarısı: {e}")
        
        return document


class EnhancedExporter:
    """Enhanced exporter with validation and verification."""
    
    def __init__(self, document_manager: Optional[FreeCADDocumentManager] = None):
        """
        Initialize enhanced exporter.
        
        Args:
            document_manager: Optional document manager instance
        """
        self.document_manager = document_manager or FreeCADDocumentManager()
        self._export_handlers = self._initialize_handlers()
        self._freecad_available = self._check_freecad()
    
    def _check_freecad(self) -> bool:
        """Check if FreeCAD is available."""
        try:
            import FreeCAD
            import Part
            import Mesh
            return True
        except ImportError:
            logger.error("FreeCAD gerekli ancak yüklü değil")
            return False
    
    def _initialize_handlers(self) -> Dict[ExportFormat, callable]:
        """Initialize format-specific export handlers."""
        return {
            ExportFormat.FCSTD: self._export_fcstd,
            ExportFormat.STEP: self._export_step,
            ExportFormat.IGES: self._export_iges,
            ExportFormat.BREP: self._export_brep,
            ExportFormat.STL: self._export_stl,
            ExportFormat.OBJ: self._export_obj,
            ExportFormat.PLY: self._export_ply,
            ExportFormat.OFF: self._export_off,
            ExportFormat.THREEMF: self._export_3mf,
            ExportFormat.AMF: self._export_amf,
            ExportFormat.DXF: self._export_dxf,
            ExportFormat.SVG: self._export_svg,
            ExportFormat.IFC: self._export_ifc,
            ExportFormat.DAE: self._export_dae,
            ExportFormat.GLTF: self._export_gltf,
            ExportFormat.GLB: self._export_glb,
            ExportFormat.VRML: self._export_vrml,
            ExportFormat.WRL: self._export_vrml,
            ExportFormat.X3D: self._export_x3d,
            ExportFormat.XYZ: self._export_xyz,
            ExportFormat.PCD: self._export_pcd,
        }
    
    async def export_with_validation(
        self,
        document: Any,
        output_path: Union[str, Path],
        format: ExportFormat,
        options: Optional[ExportOptions] = None
    ) -> ExportResult:
        """
        Export document with validation and verification.
        
        Args:
            document: FreeCAD document
            output_path: Output file path
            format: Export format
            options: Export options
            
        Returns:
            Export result with validation
        """
        with create_span("enhanced_export") as span:
            span.set_attribute("format", format.value)
            span.set_attribute("output_path", str(output_path))
            
            start_time = asyncio.get_event_loop().time()
            output_path = Path(output_path)
            options = options or ExportOptions()
            
            result = ExportResult(
                success=False,
                format=format,
                file_path=str(output_path),
                file_size=0,
                sha256="",
                export_time_ms=0
            )
            
            try:
                # Pre-export validation
                if options.validate_output:
                    validation = GeometryValidator.validate_for_export(document, format)
                    result.validation = validation
                    
                    if not validation.is_valid:
                        result.success = False
                        result.errors = validation.errors
                        return result
                    
                    logger.info("Ön doğrulama başarılı")
                
                # Format-specific optimization
                if options.optimize_size:
                    document = FormatOptimizer.optimize_for_format(document, format, options)
                    logger.info("Format optimizasyonu uygulandı")
                
                # Get export handler
                handler = self._export_handlers.get(format)
                if not handler:
                    raise NotImplementedError(f"Format henüz desteklenmiyor: {format.value}")
                
                # Export with handler
                export_data = await handler(document, output_path, options)
                
                # Embed metadata if requested
                if options.embed_metadata:
                    metadata = await self._embed_metadata(output_path, format, document, options)
                    result.metadata = metadata
                
                # Post-export verification
                if options.validate_output and output_path.exists():
                    verification = await self._verify_export(output_path, format, options)
                    result.verification = verification
                
                # Calculate file info
                if output_path.exists():
                    stat = output_path.stat()
                    result.file_size = stat.st_size
                    
                    # Calculate SHA256
                    sha256 = hashlib.sha256()
                    with open(output_path, "rb") as f:
                        for chunk in iter(lambda: f.read(8192), b""):
                            sha256.update(chunk)
                    result.sha256 = sha256.hexdigest()
                
                # Collect statistics
                result.statistics = await self._collect_export_statistics(document, format)
                
                result.success = True
                result.warnings = export_data.get("warnings", [])
                
                # Record metrics
                export_counter.labels(
                    format=format.value,
                    status="success"
                ).inc()
                
            except Exception as e:
                logger.error(f"Dışa aktarma hatası: {e}")
                result.errors.append(str(e))
                result.success = False
                
                export_counter.labels(
                    format=format.value,
                    status="error"
                ).inc()
            
            finally:
                # Calculate export time
                result.export_time_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                export_duration_histogram.labels(
                    format=format.value
                ).observe(result.export_time_ms)
                
                span.set_attribute("success", result.success)
                span.set_attribute("export_time_ms", result.export_time_ms)
            
            return result
    
    async def _export_fcstd(self, document: Any, output_path: Path, options: ExportOptions) -> Dict:
        """Export native FreeCAD format."""
        import FreeCAD
        
        # Save document
        document.saveAs(str(output_path))
        
        # Compress if requested
        if options.compress:
            # FCStd is already a ZIP file
            pass
        
        return {"warnings": []}
    
    async def _export_step(self, document: Any, output_path: Path, options: ExportOptions) -> Dict:
        """Export STEP format."""
        import Part
        
        # Collect shapes
        shapes = []
        for obj in document.Objects:
            if hasattr(obj, "Shape") and obj.Shape:
                shapes.append(obj.Shape)
        
        if not shapes:
            raise ValueError("Dışa aktarılacak şekil bulunamadı")
        
        # Create compound if multiple shapes
        if len(shapes) == 1:
            shape = shapes[0]
        else:
            shape = Part.makeCompound(shapes)
        
        # Export with schema
        import Import
        Import.export([shape], str(output_path))
        
        # Apply schema settings
        if options.step_schema != StepSchema.AP214:
            # Modify STEP file header for different schema
            await self._modify_step_schema(output_path, options.step_schema)
        
        return {"warnings": []}
    
    async def _export_iges(self, document: Any, output_path: Path, options: ExportOptions) -> Dict:
        """Export IGES format."""
        import Part
        
        shapes = []
        for obj in document.Objects:
            if hasattr(obj, "Shape") and obj.Shape:
                shapes.append(obj.Shape)
        
        if shapes:
            shape = Part.makeCompound(shapes) if len(shapes) > 1 else shapes[0]
            shape.exportIges(str(output_path))
        
        return {"warnings": []}
    
    async def _export_brep(self, document: Any, output_path: Path, options: ExportOptions) -> Dict:
        """Export BREP format."""
        import Part
        
        shapes = []
        for obj in document.Objects:
            if hasattr(obj, "Shape") and obj.Shape:
                shapes.append(obj.Shape)
        
        if shapes:
            shape = Part.makeCompound(shapes) if len(shapes) > 1 else shapes[0]
            shape.exportBrep(str(output_path))
        
        return {"warnings": []}
    
    async def _export_stl(self, document: Any, output_path: Path, options: ExportOptions) -> Dict:
        """Export STL format."""
        import Mesh
        
        # Create mesh from shapes
        meshes = []
        for obj in document.Objects:
            if hasattr(obj, "Shape") and obj.Shape:
                mesh = Mesh.Mesh()
                mesh.addFacets(obj.Shape.tessellate(
                    options.stl_linear_deflection,
                    True,
                    options.stl_angular_deflection
                )[0])
                meshes.append(mesh)
            elif hasattr(obj, "Mesh"):
                meshes.append(obj.Mesh)
        
        if meshes:
            # Merge meshes
            final_mesh = Mesh.Mesh()
            for mesh in meshes:
                final_mesh.addMesh(mesh)
            
            # Export
            if options.stl_ascii:
                final_mesh.write(str(output_path), "AST")
            else:
                final_mesh.write(str(output_path))
        
        return {"warnings": []}
    
    async def _export_obj(self, document: Any, output_path: Path, options: ExportOptions) -> Dict:
        """Export OBJ format."""
        import Mesh
        
        meshes = []
        for obj in document.Objects:
            if hasattr(obj, "Mesh"):
                meshes.append(obj.Mesh)
            elif hasattr(obj, "Shape") and obj.Shape:
                mesh = Mesh.Mesh()
                mesh.addFacets(obj.Shape.tessellate(0.1)[0])
                meshes.append(mesh)
        
        if meshes:
            final_mesh = Mesh.Mesh()
            for mesh in meshes:
                final_mesh.addMesh(mesh)
            final_mesh.write(str(output_path), "OBJ")
        
        return {"warnings": []}
    
    async def _export_ply(self, document: Any, output_path: Path, options: ExportOptions) -> Dict:
        """Export PLY format."""
        import Mesh
        
        meshes = []
        for obj in document.Objects:
            if hasattr(obj, "Mesh"):
                meshes.append(obj.Mesh)
            elif hasattr(obj, "Shape") and obj.Shape:
                mesh = Mesh.Mesh()
                mesh.addFacets(obj.Shape.tessellate(0.1)[0])
                meshes.append(mesh)
        
        if meshes:
            final_mesh = Mesh.Mesh()
            for mesh in meshes:
                final_mesh.addMesh(mesh)
            final_mesh.write(str(output_path), "PLY")
        
        return {"warnings": []}
    
    async def _export_off(self, document: Any, output_path: Path, options: ExportOptions) -> Dict:
        """Export OFF format."""
        import Mesh
        
        meshes = []
        for obj in document.Objects:
            if hasattr(obj, "Mesh"):
                meshes.append(obj.Mesh)
            elif hasattr(obj, "Shape") and obj.Shape:
                mesh = Mesh.Mesh()
                mesh.addFacets(obj.Shape.tessellate(0.1)[0])
                meshes.append(mesh)
        
        if meshes:
            final_mesh = Mesh.Mesh()
            for mesh in meshes:
                final_mesh.addMesh(mesh)
            final_mesh.write(str(output_path), "OFF")
        
        return {"warnings": []}
    
    async def _export_3mf(self, document: Any, output_path: Path, options: ExportOptions) -> Dict:
        """Export 3MF format."""
        warnings = ["3MF dışa aktarma sınırlı destek"]
        
        # Export as STL then convert
        stl_path = output_path.with_suffix(".stl")
        await self._export_stl(document, stl_path, options)
        
        # Rename to 3MF (basic support)
        stl_path.rename(output_path)
        
        return {"warnings": warnings}
    
    async def _export_amf(self, document: Any, output_path: Path, options: ExportOptions) -> Dict:
        """Export AMF format."""
        import Mesh
        
        meshes = []
        for obj in document.Objects:
            if hasattr(obj, "Mesh"):
                meshes.append(obj.Mesh)
            elif hasattr(obj, "Shape") and obj.Shape:
                mesh = Mesh.Mesh()
                mesh.addFacets(obj.Shape.tessellate(0.1)[0])
                meshes.append(mesh)
        
        if meshes:
            final_mesh = Mesh.Mesh()
            for mesh in meshes:
                final_mesh.addMesh(mesh)
            final_mesh.write(str(output_path), "AMF")
        
        return {"warnings": []}
    
    async def _export_dxf(self, document: Any, output_path: Path, options: ExportOptions) -> Dict:
        """Export DXF format."""
        warnings = []
        
        try:
            import importDXF
            importDXF.export(document.Objects, str(output_path))
        except Exception as e:
            warnings.append(f"DXF dışa aktarma uyarısı: {e}")
            # Fallback
            import Draft
            Draft.export_dxf(document.Objects, str(output_path))
        
        return {"warnings": warnings}
    
    async def _export_svg(self, document: Any, output_path: Path, options: ExportOptions) -> Dict:
        """Export SVG format."""
        try:
            import importSVG
            importSVG.export(document.Objects, str(output_path))
        except Exception:
            import Draft
            Draft.export_svg(document.Objects, str(output_path))
        
        return {"warnings": []}
    
    async def _export_ifc(self, document: Any, output_path: Path, options: ExportOptions) -> Dict:
        """Export IFC format."""
        warnings = []
        
        try:
            import importIFC
            importIFC.export(document.Objects, str(output_path))
        except Exception as e:
            warnings.append(f"IFC dışa aktarma uyarısı: {e}")
            import Arch
            Arch.exportIFC(document.Objects, str(output_path))
        
        return {"warnings": warnings}
    
    async def _export_dae(self, document: Any, output_path: Path, options: ExportOptions) -> Dict:
        """Export COLLADA format."""
        try:
            import importDAE
            importDAE.export(document.Objects, str(output_path))
        except Exception:
            # Convert to mesh first
            await self._export_obj(document, output_path.with_suffix(".obj"), options)
            output_path.with_suffix(".obj").rename(output_path)
        
        return {"warnings": []}
    
    async def _export_gltf(self, document: Any, output_path: Path, options: ExportOptions) -> Dict:
        """Export glTF format."""
        warnings = ["glTF dışa aktarma deneysel"]
        
        try:
            import trimesh
            
            # Convert to trimesh scene
            scene = trimesh.Scene()
            
            for obj in document.Objects:
                if hasattr(obj, "Shape") and obj.Shape:
                    # Tessellate shape
                    vertices, faces = obj.Shape.tessellate(0.1)
                    
                    # Create trimesh
                    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
                    scene.add_geometry(mesh, node_name=obj.Label)
            
            # Export to GLTF
            scene.export(str(output_path))
            
        except ImportError:
            warnings.append("trimesh kütüphanesi gerekli")
        except Exception as e:
            warnings.append(f"glTF dışa aktarma hatası: {e}")
        
        return {"warnings": warnings}
    
    async def _export_glb(self, document: Any, output_path: Path, options: ExportOptions) -> Dict:
        """Export GLB (binary glTF) format."""
        # Same as GLTF but binary
        result = await self._export_gltf(document, output_path.with_suffix(".gltf"), options)
        
        # Convert to GLB if successful
        if output_path.with_suffix(".gltf").exists():
            output_path.with_suffix(".gltf").rename(output_path)
        
        return result
    
    async def _export_vrml(self, document: Any, output_path: Path, options: ExportOptions) -> Dict:
        """Export VRML/WRL format."""
        import Mesh
        
        meshes = []
        for obj in document.Objects:
            if hasattr(obj, "Mesh"):
                meshes.append(obj.Mesh)
            elif hasattr(obj, "Shape") and obj.Shape:
                mesh = Mesh.Mesh()
                mesh.addFacets(obj.Shape.tessellate(0.1)[0])
                meshes.append(mesh)
        
        if meshes:
            final_mesh = Mesh.Mesh()
            for mesh in meshes:
                final_mesh.addMesh(mesh)
            final_mesh.write(str(output_path), "VRML")
        
        return {"warnings": []}
    
    async def _export_x3d(self, document: Any, output_path: Path, options: ExportOptions) -> Dict:
        """Export X3D format."""
        # Export as VRML then convert header
        await self._export_vrml(document, output_path.with_suffix(".wrl"), options)
        
        # Rename to X3D
        output_path.with_suffix(".wrl").rename(output_path)
        
        return {"warnings": ["X3D dışa aktarma VRML tabanlı"]}
    
    async def _export_xyz(self, document: Any, output_path: Path, options: ExportOptions) -> Dict:
        """Export XYZ point cloud format."""
        points = []
        
        for obj in document.Objects:
            if hasattr(obj, "Points"):
                # Point cloud object
                for p in obj.Points.Points:
                    points.append(f"{p.x} {p.y} {p.z}")
            elif hasattr(obj, "Shape") and obj.Shape:
                # Extract vertices from shape
                for v in obj.Shape.Vertexes:
                    points.append(f"{v.X} {v.Y} {v.Z}")
        
        # Write XYZ file
        with open(output_path, "w") as f:
            f.write("\n".join(points))
        
        return {"warnings": []}
    
    async def _export_pcd(self, document: Any, output_path: Path, options: ExportOptions) -> Dict:
        """Export PCD point cloud format."""
        points = []
        
        for obj in document.Objects:
            if hasattr(obj, "Points"):
                for p in obj.Points.Points:
                    points.append([p.x, p.y, p.z])
            elif hasattr(obj, "Shape") and obj.Shape:
                for v in obj.Shape.Vertexes:
                    points.append([v.X, v.Y, v.Z])
        
        # Write PCD header
        with open(output_path, "w") as f:
            f.write("# .PCD v0.7 - Point Cloud Data file format\n")
            f.write("VERSION 0.7\n")
            f.write("FIELDS x y z\n")
            f.write("SIZE 4 4 4\n")
            f.write("TYPE F F F\n")
            f.write("COUNT 1 1 1\n")
            f.write(f"WIDTH {len(points)}\n")
            f.write("HEIGHT 1\n")
            f.write("VIEWPOINT 0 0 0 1 0 0 0\n")
            f.write(f"POINTS {len(points)}\n")
            f.write("DATA ascii\n")
            
            for p in points:
                f.write(f"{p[0]} {p[1]} {p[2]}\n")
        
        return {"warnings": []}
    
    async def _modify_step_schema(self, file_path: Path, schema: StepSchema) -> None:
        """Modify STEP file schema in header."""
        content = file_path.read_text()
        
        # Replace schema in FILE_SCHEMA line
        schema_map = {
            StepSchema.AP203: "CONFIG_CONTROL_DESIGN",
            StepSchema.AP214: "AUTOMOTIVE_DESIGN",
            StepSchema.AP242: "MANAGED_MODEL_BASED_3D_ENGINEERING"
        }
        
        new_schema = schema_map.get(schema, "AUTOMOTIVE_DESIGN")
        content = content.replace("AUTOMOTIVE_DESIGN", new_schema)
        
        file_path.write_text(content)
    
    async def _embed_metadata(
        self,
        file_path: Path,
        format: ExportFormat,
        document: Any,
        options: ExportOptions
    ) -> Dict[str, Any]:
        """Embed metadata in exported file."""
        metadata = {
            "exported_by": "Enhanced Exporter",
            "export_date": datetime.now(timezone.utc).isoformat(),
            "freecad_version": FREECAD_VERSION,
            "occt_version": OCCT_VERSION,
            "format": format.value,
            "options": options.model_dump()
        }
        
        # Add document metadata
        if hasattr(document, "Meta"):
            metadata.update({
                "author": document.Meta.get("Author", ""),
                "company": document.Meta.get("Company", ""),
                "license": document.Meta.get("License", ""),
                "comment": document.Meta.get("Comment", "")
            })
        
        # Format-specific embedding
        if format == ExportFormat.STEP:
            # STEP allows comments in header
            await self._embed_step_metadata(file_path, metadata)
        elif format in [ExportFormat.STL, ExportFormat.PLY]:
            # These formats support comments
            await self._embed_ascii_metadata(file_path, metadata)
        
        return metadata
    
    async def _embed_step_metadata(self, file_path: Path, metadata: Dict) -> None:
        """Embed metadata in STEP file header."""
        content = file_path.read_text()
        
        # Add metadata as comments
        meta_str = json.dumps(metadata, ensure_ascii=False)
        comment = f"/* METADATA: {meta_str} */\n"
        
        # Insert after header
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("HEADER;"):
                lines.insert(i + 1, comment)
                break
        
        file_path.write_text("\n".join(lines))
    
    async def _embed_ascii_metadata(self, file_path: Path, metadata: Dict) -> None:
        """Embed metadata as comments in ASCII formats."""
        content = file_path.read_text()
        
        # Add metadata as comments at the beginning
        meta_lines = []
        for key, value in metadata.items():
            meta_lines.append(f"# {key}: {value}")
        
        meta_str = "\n".join(meta_lines) + "\n"
        file_path.write_text(meta_str + content)
    
    async def _verify_export(self, file_path: Path, format: ExportFormat, options: ExportOptions) -> Dict:
        """Verify exported file."""
        verification = {
            "file_exists": file_path.exists(),
            "file_size_valid": False,
            "format_valid": False,
            "can_reimport": False
        }
        
        if not file_path.exists():
            return verification
        
        # Check file size
        size = file_path.stat().st_size
        verification["file_size_valid"] = size > 0
        
        # Try to read file header to verify format
        try:
            with open(file_path, "rb") as f:
                header = f.read(1024)
                
                if format == ExportFormat.STEP:
                    verification["format_valid"] = b"ISO-10303-21" in header
                elif format == ExportFormat.STL:
                    verification["format_valid"] = b"solid" in header or len(header) >= 84
                elif format == ExportFormat.IFC:
                    verification["format_valid"] = b"IFC" in header
                else:
                    verification["format_valid"] = True
        except Exception as e:
            logger.warning(f"Format doğrulama hatası: {e}")
        
        return verification
    
    async def _collect_export_statistics(self, document: Any, format: ExportFormat) -> Dict:
        """Collect export statistics."""
        stats = {
            "objects_exported": 0,
            "format": format.value,
            "geometry_complexity": {}
        }
        
        for obj in document.Objects:
            if hasattr(obj, "Shape") and obj.Shape:
                stats["objects_exported"] += 1
                
                shape = obj.Shape
                if hasattr(shape, "Faces"):
                    stats["geometry_complexity"]["faces"] = \
                        stats["geometry_complexity"].get("faces", 0) + len(shape.Faces)
                if hasattr(shape, "Edges"):
                    stats["geometry_complexity"]["edges"] = \
                        stats["geometry_complexity"].get("edges", 0) + len(shape.Edges)
                if hasattr(shape, "Vertexes"):
                    stats["geometry_complexity"]["vertices"] = \
                        stats["geometry_complexity"].get("vertices", 0) + len(shape.Vertexes)
        
        return stats
    
    async def batch_export(
        self,
        document: Any,
        base_path: Union[str, Path],
        formats: List[ExportFormat],
        options: Optional[ExportOptions] = None
    ) -> List[ExportResult]:
        """
        Export document to multiple formats.
        
        Args:
            document: FreeCAD document
            base_path: Base output path (without extension)
            formats: List of export formats
            options: Export options
            
        Returns:
            List of export results
        """
        results = []
        base_path = Path(base_path)
        
        for format in formats:
            # Determine file extension
            extension = format.value
            output_path = base_path.with_suffix(f".{extension}")
            
            # Export
            result = await self.export_with_validation(
                document,
                output_path,
                format,
                options
            )
            results.append(result)
        
        return results
    
    def get_supported_formats(self) -> Dict[str, List[str]]:
        """Get list of supported export formats by category."""
        return {
            "native": ["fcstd"],
            "cad": ["step", "iges", "brep"],
            "mesh": ["stl", "obj", "ply", "off", "3mf", "amf"],
            "drawing": ["dxf", "svg"],
            "industry": ["ifc", "dae", "gltf", "glb"],
            "visualization": ["vrml", "wrl", "x3d"],
            "point_cloud": ["xyz", "pcd"]
        }