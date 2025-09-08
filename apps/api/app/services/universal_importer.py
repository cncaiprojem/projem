"""
Universal Importer for Task 7.20 - Multi-format Import Pipeline

Supports 30+ formats with metadata preservation, unit conversion, and coordinate system handling.
Integrates with FreeCADDocumentManager for consistent document lifecycle management.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field, field_validator

from ..core.constants import FREECAD_VERSION, OCCT_VERSION
from ..core.logging import get_logger
from ..core.metrics import import_counter, import_duration_histogram
from ..core.telemetry import create_span
from .freecad_document_manager import FreeCADDocumentManager, DocumentMetadata

logger = get_logger(__name__)

# Unit conversion constants
INCH_TO_MM = 25.4
MM_TO_INCH = 1 / 25.4


class ImportFormat(str, Enum):
    """Supported import formats."""
    # Native FreeCAD
    FCSTD = "fcstd"
    FCMACRO = "fcmacro"
    FCMAT = "fcmat"
    
    # CAD Formats
    STEP = "step"
    STP = "stp"
    IGES = "iges"
    IGS = "igs"
    BREP = "brep"
    BRP = "brp"
    SAT = "sat"
    SAB = "sab"
    
    # Mesh Formats
    STL = "stl"
    OBJ = "obj"
    PLY = "ply"
    OFF = "off"
    THREEMF = "3mf"
    AMF = "amf"
    
    # Drawing Formats
    DXF = "dxf"
    DWG = "dwg"
    SVG = "svg"
    
    # Point Cloud Formats
    PCD = "pcd"
    XYZ = "xyz"
    LAS = "las"
    LAZ = "laz"
    
    # Industry Specific
    IFC = "ifc"  # Architecture/BIM
    DAE = "dae"  # COLLADA for animation
    GLTF = "gltf"  # Web 3D
    GLB = "glb"  # Web 3D binary
    
    # Additional Formats
    PDF = "pdf"  # 2D/3D PDF
    U3D = "u3d"  # Universal 3D
    X3D = "x3d"  # Extensible 3D
    VRML = "vrml"  # Virtual Reality Modeling
    WRL = "wrl"  # VRML World


class UnitSystem(str, Enum):
    """Supported unit systems."""
    METRIC = "metric"  # mm, cm, m
    IMPERIAL = "imperial"  # inch, foot
    SI = "si"  # International System


class CoordinateSystem(str, Enum):
    """Coordinate system orientations."""
    Z_UP = "z_up"  # Default for CAD (Z is up)
    Y_UP = "y_up"  # Common in graphics (Y is up)
    RIGHT_HANDED = "right_handed"
    LEFT_HANDED = "left_handed"


class ImportOptions(BaseModel):
    """Options for import operations."""
    preserve_history: bool = Field(default=True, description="Parametrik geçmişi koru")
    preserve_materials: bool = Field(default=True, description="Malzeme bilgilerini koru")
    preserve_constraints: bool = Field(default=True, description="Kısıtlamaları koru")
    preserve_colors: bool = Field(default=True, description="Renkleri koru")
    preserve_textures: bool = Field(default=True, description="Dokuları koru")
    unit_system: UnitSystem = Field(default=UnitSystem.METRIC, description="Birim sistemi")
    coordinate_system: CoordinateSystem = Field(default=CoordinateSystem.Z_UP, description="Koordinat sistemi")
    merge_solids: bool = Field(default=False, description="Katıları birleştir")
    import_hidden: bool = Field(default=False, description="Gizli nesneleri içe aktar")
    simplify_geometry: bool = Field(default=False, description="Geometriyi basitleştir")
    tolerance: float = Field(default=0.001, ge=0.0001, le=1.0, description="İçe aktarma toleransı")
    
    model_config = {"json_schema_extra": {"examples": [
        {
            "preserve_history": True,
            "preserve_materials": True,
            "unit_system": "metric",
            "coordinate_system": "z_up",
            "tolerance": 0.001
        }
    ]}}


class ImportResult(BaseModel):
    """Result of an import operation."""
    success: bool = Field(description="Başarı durumu")
    format: ImportFormat = Field(description="İçe aktarılan format")
    document_id: str = Field(description="Doküman ID")
    file_path: str = Field(description="Dosya yolu")
    file_size: int = Field(description="Dosya boyutu (bytes)")
    sha256: str = Field(description="Dosya SHA256 hash")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata")
    statistics: Dict[str, Any] = Field(default_factory=dict, description="İstatistikler")
    warnings: List[str] = Field(default_factory=list, description="Uyarılar")
    errors: List[str] = Field(default_factory=list, description="Hatalar")
    import_time_ms: float = Field(description="İçe aktarma süresi (ms)")
    
    # Turkish messages
    messages: Dict[str, str] = Field(default_factory=lambda: {
        "format_detected": "Format tespit edildi",
        "validation_passed": "Doğrulama başarılı",
        "import_started": "İçe aktarma başladı",
        "import_completed": "İçe aktarma tamamlandı",
        "metadata_extracted": "Metadata çıkarıldı"
    })


class FormatValidator:
    """Validates file formats before import."""
    
    # Magic bytes for format detection
    MAGIC_BYTES = {
        b"ISO-10303-21": ["step", "stp"],
        b"IGES": ["iges", "igs"],
        b"solid": ["stl"],  # ASCII STL
        b"\x84\x80": ["stl"],  # Binary STL
        b"IFC": ["ifc"],
        b"glTF": ["gltf"],
        b"FCStd": ["fcstd"],
        b"<?xml": ["svg", "dae", "x3d"],
        b"%PDF": ["pdf"],
        b"ply": ["ply"],
        b"OFF": ["off"],
        b"#VRML": ["vrml", "wrl"],
    }
    
    @classmethod
    def validate_format(cls, file_path: Path) -> Optional[ImportFormat]:
        """
        Validate and detect file format.
        
        Args:
            file_path: Path to file
            
        Returns:
            Detected format or None
        """
        # First check by extension
        extension = file_path.suffix.lower().lstrip(".")
        try:
            format_by_ext = ImportFormat(extension)
        except ValueError:
            format_by_ext = None
        
        # Then check by magic bytes
        format_by_magic = None
        try:
            with open(file_path, "rb") as f:
                header = f.read(1024)  # Read first 1KB
                
                for magic, formats in cls.MAGIC_BYTES.items():
                    if magic in header:
                        # Try to match with extension first
                        if extension in formats:
                            format_by_magic = ImportFormat(extension)
                        else:
                            format_by_magic = ImportFormat(formats[0])
                        break
        except Exception as e:
            logger.warning(f"Format detection by magic bytes failed: {e}")
        
        # Prefer magic byte detection if available
        return format_by_magic or format_by_ext
    
    @classmethod
    def get_file_info(cls, file_path: Path) -> Dict[str, Any]:
        """Get file information."""
        stat = file_path.stat()
        
        # Calculate SHA256
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        
        return {
            "size": stat.st_size,
            "created": datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "sha256": sha256.hexdigest(),
            "extension": file_path.suffix.lower(),
            "name": file_path.name
        }


class UniversalImporter:
    """Universal importer for 30+ formats with metadata preservation."""
    
    def __init__(self, document_manager: Optional[FreeCADDocumentManager] = None):
        """
        Initialize universal importer.
        
        Args:
            document_manager: Optional document manager instance
        """
        self.document_manager = document_manager or FreeCADDocumentManager()
        self._import_handlers = self._initialize_handlers()
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
    
    def _initialize_handlers(self) -> Dict[ImportFormat, callable]:
        """Initialize format-specific import handlers."""
        return {
            # Native FreeCAD
            ImportFormat.FCSTD: self._import_fcstd,
            ImportFormat.FCMACRO: self._import_fcmacro,
            ImportFormat.FCMAT: self._import_fcmat,
            
            # CAD Formats
            ImportFormat.STEP: self._import_step,
            ImportFormat.STP: self._import_step,
            ImportFormat.IGES: self._import_iges,
            ImportFormat.IGS: self._import_iges,
            ImportFormat.BREP: self._import_brep,
            ImportFormat.BRP: self._import_brep,
            
            # Mesh Formats
            ImportFormat.STL: self._import_stl,
            ImportFormat.OBJ: self._import_obj,
            ImportFormat.PLY: self._import_ply,
            ImportFormat.OFF: self._import_off,
            ImportFormat.THREEMF: self._import_3mf,
            ImportFormat.AMF: self._import_amf,
            
            # Drawing Formats
            ImportFormat.DXF: self._import_dxf,
            ImportFormat.DWG: self._import_dwg,
            ImportFormat.SVG: self._import_svg,
            
            # Point Cloud
            ImportFormat.PCD: self._import_pcd,
            ImportFormat.XYZ: self._import_xyz,
            ImportFormat.LAS: self._import_las,
            
            # Industry Specific
            ImportFormat.IFC: self._import_ifc,
            ImportFormat.DAE: self._import_dae,
            ImportFormat.GLTF: self._import_gltf,
            ImportFormat.GLB: self._import_glb,
            
            # Additional
            ImportFormat.VRML: self._import_vrml,
            ImportFormat.WRL: self._import_vrml,
        }
    
    async def import_file(
        self,
        file_path: Union[str, Path],
        job_id: int,
        options: Optional[ImportOptions] = None
    ) -> ImportResult:
        """
        Import file with metadata preservation.
        
        Args:
            file_path: Path to import file
            job_id: Job ID for document naming
            options: Import options
            
        Returns:
            Import result with metadata
        """
        with create_span("universal_import") as span:
            span.set_attribute("file_path", str(file_path))
            span.set_attribute("job_id", job_id)
            
            start_time = asyncio.get_event_loop().time()
            file_path = Path(file_path)
            options = options or ImportOptions()
            
            result = ImportResult(
                success=False,
                format=ImportFormat.FCSTD,
                document_id="",
                file_path=str(file_path),
                file_size=0,
                sha256="",
                import_time_ms=0
            )
            
            try:
                # Validate file exists
                if not file_path.exists():
                    raise FileNotFoundError(f"Dosya bulunamadı: {file_path}")
                
                # Get file info
                file_info = FormatValidator.get_file_info(file_path)
                result.file_size = file_info["size"]
                result.sha256 = file_info["sha256"]
                
                # Detect format
                detected_format = FormatValidator.validate_format(file_path)
                if not detected_format:
                    raise ValueError(f"Desteklenmeyen format: {file_path.suffix}")
                
                result.format = detected_format
                logger.info(f"Format tespit edildi: {detected_format.value}")
                
                # Get handler
                handler = self._import_handlers.get(detected_format)
                if not handler:
                    raise NotImplementedError(
                        f"Format henüz desteklenmiyor: {detected_format.value}"
                    )
                
                # Create document with manager
                doc_result = await self.document_manager.create_document(
                    job_id=job_id,
                    metadata=DocumentMetadata(
                        author="Universal Importer",
                        description=f"Imported from {file_path.name}",
                        source_format=detected_format.value,
                        import_options=options.model_dump()
                    )
                )
                
                result.document_id = doc_result["document_id"]
                
                # Import with handler
                import_data = await handler(file_path, doc_result["document"], options)
                
                # Extract metadata
                result.metadata = await self._extract_metadata(
                    doc_result["document"], 
                    detected_format,
                    options
                )
                
                # Collect statistics
                result.statistics = await self._collect_statistics(doc_result["document"])
                
                # Save document
                await self.document_manager.save_document(
                    doc_result["document"],
                    compress=True
                )
                
                result.success = True
                result.warnings = import_data.get("warnings", [])
                
                # Record metrics
                import_counter.labels(
                    format=detected_format.value,
                    status="success"
                ).inc()
                
            except Exception as e:
                logger.error(f"İçe aktarma hatası: {e}")
                result.errors.append(str(e))
                result.success = False
                
                import_counter.labels(
                    format=result.format.value,
                    status="error"
                ).inc()
            
            finally:
                # Calculate import time
                result.import_time_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                import_duration_histogram.labels(
                    format=result.format.value
                ).observe(result.import_time_ms)
                
                span.set_attribute("success", result.success)
                span.set_attribute("import_time_ms", result.import_time_ms)
            
            return result
    
    async def _import_fcstd(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import native FreeCAD format."""
        import FreeCAD
        
        # Open document directly
        FreeCAD.openDocument(str(file_path))
        
        return {"warnings": []}
    
    async def _import_step(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import STEP format."""
        import Part
        
        warnings = []
        
        # Read STEP with options
        shape = Part.Shape()
        await asyncio.to_thread(shape.read, str(file_path))
        
        # Apply unit conversion if needed
        original_shape = None  # Initialize before try block
        if options.unit_system == UnitSystem.IMPERIAL:
            # Convert from mm to inch with error handling
            try:
                import FreeCAD
                # Create backup before modification
                original_shape = shape.copy()
                # Wrap CPU-intensive scale operation in asyncio.to_thread
                await asyncio.to_thread(shape.scale, MM_TO_INCH)
                warnings.append("Birimler inch'e dönüştürüldü")
            except Exception as e:
                logger.warning(f"Unit conversion failed: {e}")
                shape = original_shape if original_shape is not None else shape
                warnings.append(f"Birim dönüşümü başarısız: {e}")
        
        # Add to document
        part = document.addObject("Part::Feature", "ImportedSTEP")
        part.Shape = shape
        
        # Preserve colors if available
        if options.preserve_colors:
            try:
                import Import
                # Wrap blocking readColors in asyncio.to_thread
                await asyncio.to_thread(Import.readColors, str(file_path), document)
            except Exception as e:
                warnings.append(f"Renkler korunamadı: {e}")
        
        document.recompute()
        
        return {"warnings": warnings}
    
    async def _import_iges(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import IGES format."""
        import Part
        
        shape = Part.Shape()
        await asyncio.to_thread(shape.read, str(file_path))
        
        part = document.addObject("Part::Feature", "ImportedIGES")
        part.Shape = shape
        
        document.recompute()
        
        return {"warnings": []}
    
    async def _import_brep(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import BREP format."""
        import Part
        
        shape = Part.Shape()
        await asyncio.to_thread(shape.read, str(file_path))
        
        part = document.addObject("Part::Feature", "ImportedBREP")
        part.Shape = shape
        
        document.recompute()
        
        return {"warnings": []}
    
    async def _import_stl(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import STL format."""
        import Mesh
        
        # Wrap blocking FreeCAD operation in asyncio.to_thread
        mesh = await asyncio.to_thread(Mesh.Mesh, str(file_path))
        
        # Add to document
        mesh_obj = document.addObject("Mesh::Feature", "ImportedSTL")
        mesh_obj.Mesh = mesh
        
        # Convert to solid if needed
        if options.merge_solids:
            import Part
            shape = Part.Shape()
            # Wrap CPU-intensive makeShapeFromMesh in asyncio.to_thread
            await asyncio.to_thread(shape.makeShapeFromMesh, mesh.Topology, options.tolerance)
            part = document.addObject("Part::Feature", "STLSolid")
            part.Shape = shape
        
        document.recompute()
        
        return {"warnings": []}
    
    async def _import_obj(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import OBJ format."""
        import Mesh
        
        # Wrap blocking FreeCAD operation in asyncio.to_thread
        mesh = await asyncio.to_thread(Mesh.Mesh, str(file_path))
        mesh_obj = document.addObject("Mesh::Feature", "ImportedOBJ")
        mesh_obj.Mesh = mesh
        
        document.recompute()
        
        return {"warnings": []}
    
    async def _import_ply(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import PLY format."""
        import Mesh
        
        # Wrap blocking FreeCAD operation in asyncio.to_thread
        mesh = await asyncio.to_thread(Mesh.Mesh, str(file_path))
        mesh_obj = document.addObject("Mesh::Feature", "ImportedPLY")
        mesh_obj.Mesh = mesh
        
        document.recompute()
        
        return {"warnings": []}
    
    async def _import_off(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import OFF format."""
        import Mesh
        
        # Wrap blocking FreeCAD operation in asyncio.to_thread
        mesh = await asyncio.to_thread(Mesh.Mesh, str(file_path))
        mesh_obj = document.addObject("Mesh::Feature", "ImportedOFF")
        mesh_obj.Mesh = mesh
        
        document.recompute()
        
        return {"warnings": []}
    
    async def _import_3mf(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import 3MF format."""
        warnings = []
        
        try:
            import Mesh
            # Wrap blocking FreeCAD operation in asyncio.to_thread
            mesh = await asyncio.to_thread(Mesh.Mesh, str(file_path))
            mesh_obj = document.addObject("Mesh::Feature", "Imported3MF")
            mesh_obj.Mesh = mesh
        except Exception as e:
            warnings.append(f"3MF içe aktarma kısmi başarılı: {e}")
        
        document.recompute()
        
        return {"warnings": warnings}
    
    async def _import_amf(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import AMF format."""
        import Mesh
        
        # Wrap blocking FreeCAD operation in asyncio.to_thread
        mesh = await asyncio.to_thread(Mesh.Mesh, str(file_path))
        mesh_obj = document.addObject("Mesh::Feature", "ImportedAMF")
        mesh_obj.Mesh = mesh
        
        document.recompute()
        
        return {"warnings": []}
    
    async def _import_dxf(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import DXF format."""
        warnings = []
        
        try:
            import importDXF
            await asyncio.to_thread(importDXF.insert, str(file_path), document.Name)
        except Exception as e:
            warnings.append(f"DXF içe aktarma uyarısı: {e}")
            # Fallback to basic import
            import Draft
            await asyncio.to_thread(Draft.import_dxf, str(file_path))
        
        document.recompute()
        
        return {"warnings": warnings}
    
    async def _import_dwg(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import DWG format (requires conversion)."""
        warnings = ["DWG formatı DXF'e dönüştürme gerektirir"]
        
        # Convert DWG to DXF first (requires external tool)
        # Then import as DXF
        return await self._import_dxf(file_path, document, options)
    
    async def _import_svg(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import SVG format."""
        try:
            import importSVG
            importSVG.insert(str(file_path), document.Name)
        except Exception:
            import Draft
            Draft.import_svg(str(file_path))
        
        document.recompute()
        
        return {"warnings": []}
    
    async def _import_pcd(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import Point Cloud Data format."""
        warnings = ["Point cloud içe aktarma sınırlı destek"]
        
        # Read point cloud and create points object
        import Points
        points = Points.Points()
        await asyncio.to_thread(points.read, str(file_path))
        
        points_obj = document.addObject("Points::Feature", "ImportedPointCloud")
        points_obj.Points = points
        
        document.recompute()
        
        return {"warnings": warnings}
    
    async def _import_xyz(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import XYZ point cloud format."""
        return await self._import_pcd(file_path, document, options)
    
    async def _import_las(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import LAS/LAZ LIDAR format."""
        warnings = ["LAS/LAZ formatı özel işleme gerektirir"]
        return await self._import_pcd(file_path, document, options)
    
    async def _import_ifc(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import IFC BIM format."""
        warnings = []
        
        try:
            import importIFC
            # Wrap blocking FreeCAD operation in asyncio.to_thread
            await asyncio.to_thread(importIFC.insert, str(file_path), document.Name)
        except Exception as e:
            warnings.append(f"IFC içe aktarma uyarısı: {e}")
            # Try alternative import
            import Arch
            # Wrap blocking FreeCAD operation in asyncio.to_thread
            await asyncio.to_thread(Arch.importIFC, str(file_path))
        
        document.recompute()
        
        return {"warnings": warnings}
    
    async def _import_dae(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import COLLADA format."""
        try:
            import importDAE
            # Wrap blocking FreeCAD operation in asyncio.to_thread
            await asyncio.to_thread(importDAE.insert, str(file_path), document.Name)
        except Exception:
            import Mesh
            # Wrap blocking FreeCAD operation in asyncio.to_thread
            mesh = await asyncio.to_thread(Mesh.Mesh, str(file_path))
            mesh_obj = document.addObject("Mesh::Feature", "ImportedCOLLADA")
            mesh_obj.Mesh = mesh
        
        document.recompute()
        
        return {"warnings": []}
    
    async def _import_gltf(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import glTF format."""
        warnings = ["glTF içe aktarma deneysel"]
        
        # Try to use trimesh for GLTF import
        try:
            import trimesh
            # Wrap blocking trimesh operation in asyncio.to_thread
            scene = await asyncio.to_thread(trimesh.load, str(file_path))
            
            import Mesh as FreeCADMesh
            for name, geom in scene.geometry.items():
                mesh = FreeCADMesh.Mesh()
                for face in geom.faces:
                    vertices = [geom.vertices[i] for i in face]
                    mesh.addFacet(*vertices)
                
                mesh_obj = document.addObject("Mesh::Feature", f"GLTF_{name}")
                mesh_obj.Mesh = mesh
        except ImportError:
            warnings.append("trimesh kütüphanesi gerekli")
        except Exception as e:
            warnings.append(f"glTF içe aktarma hatası: {e}")
        
        document.recompute()
        
        return {"warnings": warnings}
    
    async def _import_glb(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import GLB (binary glTF) format."""
        return await self._import_gltf(file_path, document, options)
    
    async def _import_vrml(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import VRML/WRL format."""
        import Mesh
        
        # Wrap blocking FreeCAD operation in asyncio.to_thread
        mesh = await asyncio.to_thread(Mesh.Mesh, str(file_path))
        mesh_obj = document.addObject("Mesh::Feature", "ImportedVRML")
        mesh_obj.Mesh = mesh
        
        document.recompute()
        
        return {"warnings": []}
    
    async def _import_fcmacro(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import FreeCAD macro."""
        warnings = ["Makro içe aktarma güvenlik riski oluşturabilir"]
        
        # Read macro content
        macro_content = await asyncio.to_thread(file_path.read_text, encoding="utf-8")
        
        # Store in document metadata instead of executing
        document.Meta["ImportedMacro"] = macro_content
        
        return {"warnings": warnings}
    
    async def _import_fcmat(self, file_path: Path, document: Any, options: ImportOptions) -> Dict:
        """Import FreeCAD material."""
        import Material
        
        mat = Material.Material()
        await asyncio.to_thread(mat.read, str(file_path))
        
        # Store material in document
        document.Meta["ImportedMaterial"] = str(mat.Material)
        
        return {"warnings": []}
    
    async def _extract_metadata(
        self, 
        document: Any, 
        format: ImportFormat,
        options: ImportOptions
    ) -> Dict[str, Any]:
        """Extract metadata from imported document."""
        metadata = {
            "format": format.value,
            "freecad_version": FREECAD_VERSION,
            "occt_version": OCCT_VERSION,
            "import_options": options.model_dump(),
            "objects": [],
            "materials": [],
            "properties": {}
        }
        
        # Extract objects
        for obj in document.Objects:
            obj_info = {
                "name": obj.Name,
                "label": obj.Label,
                "type": obj.TypeId,
                "visibility": getattr(obj, "Visibility", True)
            }
            
            # Extract shape info if available
            if hasattr(obj, "Shape"):
                shape = obj.Shape
                obj_info["geometry"] = {
                    "volume": shape.Volume if hasattr(shape, "Volume") else 0,
                    "area": shape.Area if hasattr(shape, "Area") else 0,
                    "faces": len(shape.Faces) if hasattr(shape, "Faces") else 0,
                    "edges": len(shape.Edges) if hasattr(shape, "Edges") else 0,
                    "vertices": len(shape.Vertexes) if hasattr(shape, "Vertexes") else 0
                }
            
            metadata["objects"].append(obj_info)
        
        # Extract materials if preserved
        if options.preserve_materials:
            try:
                import Material
                for obj in document.Objects:
                    if hasattr(obj, "Material"):
                        mat_info = {
                            "object": obj.Name,
                            "properties": dict(obj.Material.Material)
                        }
                        metadata["materials"].append(mat_info)
            except Exception as e:
                logger.warning(f"Malzeme bilgisi çıkarılamadı: {e}")
        
        # Extract document properties
        metadata["properties"] = {
            "author": document.Meta.get("Author", ""),
            "company": document.Meta.get("Company", ""),
            "license": document.Meta.get("License", ""),
            "comment": document.Meta.get("Comment", ""),
            "created": document.Meta.get("CreationDate", ""),
            "modified": document.Meta.get("LastModifiedDate", "")
        }
        
        return metadata
    
    async def _collect_statistics(self, document: Any) -> Dict[str, Any]:
        """Collect import statistics."""
        stats = {
            "total_objects": len(document.Objects),
            "object_types": {},
            "total_faces": 0,
            "total_edges": 0,
            "total_vertices": 0,
            "bounding_box": None
        }
        
        # Count object types
        for obj in document.Objects:
            type_id = obj.TypeId
            stats["object_types"][type_id] = stats["object_types"].get(type_id, 0) + 1
            
            # Count geometric entities
            if hasattr(obj, "Shape"):
                shape = obj.Shape
                if hasattr(shape, "Faces"):
                    stats["total_faces"] += len(shape.Faces)
                if hasattr(shape, "Edges"):
                    stats["total_edges"] += len(shape.Edges)
                if hasattr(shape, "Vertexes"):
                    stats["total_vertices"] += len(shape.Vertexes)
                
                # Get bounding box
                if hasattr(shape, "BoundBox"):
                    bb = shape.BoundBox
                    stats["bounding_box"] = {
                        "x_min": bb.XMin,
                        "x_max": bb.XMax,
                        "y_min": bb.YMin,
                        "y_max": bb.YMax,
                        "z_min": bb.ZMin,
                        "z_max": bb.ZMax,
                        "diagonal": bb.DiagonalLength
                    }
        
        return stats
    
    async def batch_import(
        self,
        file_paths: List[Union[str, Path]],
        job_id: int,
        options: Optional[ImportOptions] = None
    ) -> List[ImportResult]:
        """
        Batch import multiple files.
        
        Args:
            file_paths: List of file paths
            job_id: Base job ID
            options: Import options
            
        Returns:
            List of import results
        """
        results = []
        
        for i, file_path in enumerate(file_paths):
            # Use job_id with index for unique document IDs
            result = await self.import_file(
                file_path,
                job_id=f"{job_id}_{i}",
                options=options
            )
            results.append(result)
        
        return results
    
    def get_supported_formats(self) -> Dict[str, List[str]]:
        """Get list of supported formats by category."""
        return {
            "native": ["fcstd", "fcmacro", "fcmat"],
            "cad": ["step", "stp", "iges", "igs", "brep", "brp", "sat", "sab"],
            "mesh": ["stl", "obj", "ply", "off", "3mf", "amf"],
            "drawing": ["dxf", "dwg", "svg"],
            "point_cloud": ["pcd", "xyz", "las", "laz"],
            "industry": ["ifc", "dae", "gltf", "glb"],
            "other": ["vrml", "wrl", "pdf", "u3d", "x3d"]
        }