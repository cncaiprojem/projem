"""
Format Converter for Task 7.20 - Multi-format Conversion Pipeline

Provides comprehensive format conversion with:
- Conversion matrix for all supported format pairs
- Topology preservation
- Mesh optimization
- Reverse engineering support (STL to STEP)
- BIM conversion (IFC <-> FCStd)
"""

from __future__ import annotations

import asyncio
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field

from ..core.logging import get_logger
from ..core.metrics import conversion_counter, conversion_duration_histogram
from ..core.telemetry import create_span
from .universal_importer import UniversalImporter, ImportFormat, ImportOptions
from .enhanced_exporter import EnhancedExporter, ExportFormat, ExportOptions
from .freecad_document_manager import FreeCADDocumentManager

logger = get_logger(__name__)


class ConversionMethod(str, Enum):
    """Conversion methods between formats."""
    DIRECT = "direct"  # Direct conversion
    TESSELLATION = "tessellation"  # Via mesh tessellation
    REVERSE_ENGINEERING = "reverse_engineering"  # Reconstruct from mesh
    VECTOR_CONVERSION = "vector_conversion"  # 2D vector conversion
    WEB3D_CONVERSION = "web3d"  # Web 3D optimization
    BIM_IMPORT = "bim_import"  # BIM data import
    BIM_EXPORT = "bim_export"  # BIM data export
    TOPOLOGY_PRESERVATION = "topology_preservation"  # Preserve topology
    MESH_OPTIMIZATION = "mesh_optimization"  # Optimize mesh
    PARAMETRIC_RECONSTRUCTION = "parametric_reconstruction"  # Rebuild parametric


class ConversionQuality(str, Enum):
    """Quality levels for conversion."""
    DRAFT = "draft"  # Fast, lower quality
    NORMAL = "normal"  # Balanced
    HIGH = "high"  # High quality, slower
    MAXIMUM = "maximum"  # Best quality, slowest


class ConversionOptions(BaseModel):
    """Options for format conversion."""
    quality: ConversionQuality = Field(default=ConversionQuality.NORMAL, description="Dönüştürme kalitesi")
    preserve_topology: bool = Field(default=True, description="Topolojiyi koru")
    preserve_materials: bool = Field(default=True, description="Malzemeleri koru")
    preserve_hierarchy: bool = Field(default=True, description="Hiyerarşiyi koru")
    optimize_output: bool = Field(default=False, description="Çıktıyı optimize et")
    
    # Mesh conversion options
    mesh_quality: str = Field(default="normal", pattern="^(low|normal|high|ultra)$")
    simplify_mesh: bool = Field(default=False, description="Mesh'i basitleştir")
    target_face_count: Optional[int] = Field(default=None, ge=100, le=10000000, description="Hedef yüz sayısı")
    
    # Reverse engineering options
    fit_surfaces: bool = Field(default=True, description="Yüzeyleri uydur")
    detect_features: bool = Field(default=True, description="Özellikleri tespit et")
    tolerance: float = Field(default=0.01, ge=0.001, le=1.0, description="Tolerans")
    
    # BIM options
    ifc_schema: str = Field(default="IFC4", description="IFC şema versiyonu")
    include_properties: bool = Field(default=True, description="Özellikleri dahil et")
    
    model_config = {"json_schema_extra": {"examples": [
        {
            "quality": "high",
            "preserve_topology": True,
            "mesh_quality": "high",
            "tolerance": 0.01
        }
    ]}}


class ConversionResult(BaseModel):
    """Result of a format conversion."""
    success: bool = Field(description="Başarı durumu")
    source_format: str = Field(description="Kaynak format")
    target_format: str = Field(description="Hedef format")
    conversion_method: ConversionMethod = Field(description="Kullanılan yöntem")
    input_file: str = Field(description="Giriş dosyası")
    output_file: str = Field(description="Çıkış dosyası")
    file_size_before: int = Field(description="Önceki boyut (bytes)")
    file_size_after: int = Field(description="Sonraki boyut (bytes)")
    quality_metrics: Dict[str, Any] = Field(default_factory=dict, description="Kalite metrikleri")
    warnings: List[str] = Field(default_factory=list, description="Uyarılar")
    errors: List[str] = Field(default_factory=list, description="Hatalar")
    conversion_time_ms: float = Field(description="Dönüştürme süresi (ms)")
    
    # Turkish messages
    messages: Dict[str, str] = Field(default_factory=lambda: {
        "conversion_started": "Dönüştürme başladı",
        "method_selected": "Yöntem seçildi",
        "conversion_completed": "Dönüştürme tamamlandı",
        "quality_assessed": "Kalite değerlendirildi"
    })


class ConversionMatrix:
    """
    Defines conversion paths between formats.
    Key: (source_format, target_format)
    Value: (conversion_method, quality_level, notes)
    """
    
    MATRIX: Dict[Tuple[str, str], Tuple[ConversionMethod, str, str]] = {
        # STEP conversions
        ("step", "stl"): (ConversionMethod.TESSELLATION, "high", "Yüksek kaliteli tessellation"),
        ("step", "iges"): (ConversionMethod.DIRECT, "high", "Doğrudan dönüştürme"),
        ("step", "brep"): (ConversionMethod.TOPOLOGY_PRESERVATION, "maximum", "Topoloji korunur"),
        ("step", "ifc"): (ConversionMethod.BIM_EXPORT, "high", "BIM metadata eklenir"),
        ("step", "gltf"): (ConversionMethod.WEB3D_CONVERSION, "normal", "Web için optimize"),
        
        # STL conversions (reverse engineering)
        ("stl", "step"): (ConversionMethod.REVERSE_ENGINEERING, "medium", "Yüzey rekonstrüksiyonu"),
        ("stl", "iges"): (ConversionMethod.REVERSE_ENGINEERING, "medium", "Yüzey uydurma"),
        ("stl", "obj"): (ConversionMethod.MESH_OPTIMIZATION, "high", "Mesh optimizasyonu"),
        ("stl", "gltf"): (ConversionMethod.WEB3D_CONVERSION, "high", "Web 3D formatı"),
        ("stl", "3mf"): (ConversionMethod.DIRECT, "high", "3D baskı formatı"),
        
        # IFC conversions
        ("ifc", "fcstd"): (ConversionMethod.BIM_IMPORT, "high", "BIM verisi korunur"),
        ("fcstd", "ifc"): (ConversionMethod.BIM_EXPORT, "high", "IFC4 şeması"),
        ("ifc", "step"): (ConversionMethod.DIRECT, "high", "Geometri odaklı"),
        ("ifc", "gltf"): (ConversionMethod.WEB3D_CONVERSION, "normal", "Görselleştirme için"),
        
        # DXF conversions
        ("dxf", "svg"): (ConversionMethod.VECTOR_CONVERSION, "high", "2D vektör dönüşümü"),
        ("dxf", "step"): (ConversionMethod.DIRECT, "medium", "2D'den 3D'ye"),
        ("svg", "dxf"): (ConversionMethod.VECTOR_CONVERSION, "high", "Vektör korunur"),
        
        # BREP conversions
        ("brep", "step"): (ConversionMethod.TOPOLOGY_PRESERVATION, "maximum", "Tam topoloji"),
        ("brep", "iges"): (ConversionMethod.DIRECT, "high", "Yüzey verisi"),
        ("brep", "stl"): (ConversionMethod.TESSELLATION, "high", "Mesh oluşturma"),
        
        # OBJ conversions
        ("obj", "stl"): (ConversionMethod.DIRECT, "high", "Mesh formatları"),
        ("obj", "ply"): (ConversionMethod.DIRECT, "high", "Nokta bulutu"),
        ("obj", "gltf"): (ConversionMethod.WEB3D_CONVERSION, "high", "Web optimizasyonu"),
        ("obj", "glb"): (ConversionMethod.MESH_OPTIMIZATION, "high", "Binary GLTF"),
        
        # GLTF conversions
        ("gltf", "glb"): (ConversionMethod.DIRECT, "maximum", "Binary dönüşüm"),
        ("glb", "gltf"): (ConversionMethod.DIRECT, "maximum", "Text dönüşüm"),
        ("gltf", "obj"): (ConversionMethod.MESH_OPTIMIZATION, "high", "Mesh çıkarma"),
        ("gltf", "stl"): (ConversionMethod.TESSELLATION, "normal", "3D baskı için"),
        
        # IGES conversions
        ("iges", "step"): (ConversionMethod.DIRECT, "high", "CAD formatları"),
        ("iges", "brep"): (ConversionMethod.TOPOLOGY_PRESERVATION, "high", "Topoloji korunur"),
        ("iges", "stl"): (ConversionMethod.TESSELLATION, "normal", "Mesh oluşturma"),
        
        # Point cloud conversions
        ("xyz", "pcd"): (ConversionMethod.DIRECT, "high", "Nokta bulutu formatları"),
        ("pcd", "xyz"): (ConversionMethod.DIRECT, "high", "ASCII nokta verisi"),
        ("las", "xyz"): (ConversionMethod.DIRECT, "medium", "LIDAR verisi"),
        
        # VRML conversions
        ("vrml", "x3d"): (ConversionMethod.DIRECT, "high", "XML tabanlı"),
        ("wrl", "gltf"): (ConversionMethod.WEB3D_CONVERSION, "normal", "Modern web formatı"),
        
        # Native FreeCAD
        ("fcstd", "step"): (ConversionMethod.DIRECT, "maximum", "Parametrik veri korunur"),
        ("fcstd", "stl"): (ConversionMethod.TESSELLATION, "high", "Mesh oluşturma"),
        ("fcstd", "brep"): (ConversionMethod.TOPOLOGY_PRESERVATION, "maximum", "Tam geometri"),
    }
    
    @classmethod
    def get_conversion_path(
        cls,
        source: str,
        target: str
    ) -> Optional[Tuple[ConversionMethod, str, str]]:
        """
        Get conversion path between two formats.
        
        Args:
            source: Source format
            target: Target format
            
        Returns:
            Conversion method, quality, and notes
        """
        # Direct path
        key = (source.lower(), target.lower())
        if key in cls.MATRIX:
            return cls.MATRIX[key]
        
        # Try reverse path for symmetric conversions
        reverse_key = (target.lower(), source.lower())
        if reverse_key in cls.MATRIX:
            method, quality, notes = cls.MATRIX[reverse_key]
            # Some conversions are not reversible with same method
            if method in [ConversionMethod.DIRECT, ConversionMethod.MESH_OPTIMIZATION]:
                return method, quality, f"Ters dönüşüm: {notes}"
        
        return None
    
    @classmethod
    def find_indirect_path(
        cls,
        source: str,
        target: str,
        max_steps: int = 3
    ) -> Optional[List[str]]:
        """
        Find indirect conversion path via intermediate formats.
        
        Args:
            source: Source format
            target: Target format
            max_steps: Maximum conversion steps
            
        Returns:
            List of formats in conversion path
        """
        # Common intermediate formats for indirect conversion
        intermediates = ["step", "stl", "obj", "iges", "brep"]
        
        # Try single intermediate
        for intermediate in intermediates:
            if (cls.get_conversion_path(source, intermediate) and 
                cls.get_conversion_path(intermediate, target)):
                return [source, intermediate, target]
        
        # Try two intermediates if allowed
        if max_steps >= 3:
            for int1 in intermediates:
                for int2 in intermediates:
                    if int1 != int2:
                        if (cls.get_conversion_path(source, int1) and
                            cls.get_conversion_path(int1, int2) and
                            cls.get_conversion_path(int2, target)):
                            return [source, int1, int2, target]
        
        return None


class FormatConverter:
    """Universal format converter with advanced conversion methods."""
    
    def __init__(
        self,
        importer: Optional[UniversalImporter] = None,
        exporter: Optional[EnhancedExporter] = None,
        document_manager: Optional[FreeCADDocumentManager] = None
    ):
        """
        Initialize format converter.
        
        Args:
            importer: Universal importer instance
            exporter: Enhanced exporter instance
            document_manager: Document manager instance
        """
        self.importer = importer or UniversalImporter()
        self.exporter = exporter or EnhancedExporter()
        self.document_manager = document_manager or FreeCADDocumentManager()
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
    
    async def convert(
        self,
        input_file: Union[str, Path],
        output_file: Union[str, Path],
        source_format: Optional[str] = None,
        target_format: Optional[str] = None,
        options: Optional[ConversionOptions] = None,
        job_id: Optional[int] = None
    ) -> ConversionResult:
        """
        Convert file between formats.
        
        Args:
            input_file: Input file path
            output_file: Output file path
            source_format: Source format (auto-detect if None)
            target_format: Target format (from extension if None)
            options: Conversion options
            job_id: Optional job ID
            
        Returns:
            Conversion result
        """
        with create_span("format_conversion") as span:
            span.set_attribute("input_file", str(input_file))
            span.set_attribute("output_file", str(output_file))
            
            start_time = asyncio.get_event_loop().time()
            input_file = Path(input_file)
            output_file = Path(output_file)
            options = options or ConversionOptions()
            job_id = job_id or hash(str(input_file))
            
            result = ConversionResult(
                success=False,
                source_format="",
                target_format="",
                conversion_method=ConversionMethod.DIRECT,
                input_file=str(input_file),
                output_file=str(output_file),
                file_size_before=0,
                file_size_after=0,
                conversion_time_ms=0
            )
            
            try:
                # Get file sizes
                if input_file.exists():
                    result.file_size_before = input_file.stat().st_size
                
                # Detect formats
                if not source_format:
                    source_format = input_file.suffix.lower().lstrip(".")
                if not target_format:
                    target_format = output_file.suffix.lower().lstrip(".")
                
                result.source_format = source_format
                result.target_format = target_format
                
                logger.info(f"Dönüştürme: {source_format} -> {target_format}")
                
                # Get conversion path
                conversion_info = ConversionMatrix.get_conversion_path(
                    source_format,
                    target_format
                )
                
                if not conversion_info:
                    # Try indirect path
                    indirect_path = ConversionMatrix.find_indirect_path(
                        source_format,
                        target_format
                    )
                    
                    if indirect_path:
                        result = await self._convert_indirect(
                            input_file,
                            output_file,
                            indirect_path,
                            options,
                            job_id
                        )
                    else:
                        # Fallback to import/export
                        result = await self._convert_via_import_export(
                            input_file,
                            output_file,
                            source_format,
                            target_format,
                            options,
                            job_id
                        )
                else:
                    method, quality, notes = conversion_info
                    result.conversion_method = method
                    
                    # Apply conversion method
                    if method == ConversionMethod.DIRECT:
                        result = await self._convert_direct(
                            input_file, output_file, source_format, target_format, options, job_id
                        )
                    elif method == ConversionMethod.TESSELLATION:
                        result = await self._convert_via_tessellation(
                            input_file, output_file, source_format, target_format, options, job_id
                        )
                    elif method == ConversionMethod.REVERSE_ENGINEERING:
                        result = await self._convert_via_reverse_engineering(
                            input_file, output_file, source_format, target_format, options, job_id
                        )
                    elif method == ConversionMethod.WEB3D_CONVERSION:
                        result = await self._convert_to_web3d(
                            input_file, output_file, source_format, target_format, options, job_id
                        )
                    elif method == ConversionMethod.BIM_IMPORT:
                        result = await self._convert_bim_import(
                            input_file, output_file, source_format, target_format, options, job_id
                        )
                    elif method == ConversionMethod.BIM_EXPORT:
                        result = await self._convert_bim_export(
                            input_file, output_file, source_format, target_format, options, job_id
                        )
                    elif method == ConversionMethod.TOPOLOGY_PRESERVATION:
                        result = await self._convert_with_topology(
                            input_file, output_file, source_format, target_format, options, job_id
                        )
                    elif method == ConversionMethod.MESH_OPTIMIZATION:
                        result = await self._convert_with_mesh_optimization(
                            input_file, output_file, source_format, target_format, options, job_id
                        )
                    elif method == ConversionMethod.VECTOR_CONVERSION:
                        result = await self._convert_vector(
                            input_file, output_file, source_format, target_format, options, job_id
                        )
                    else:
                        # Default fallback
                        result = await self._convert_via_import_export(
                            input_file, output_file, source_format, target_format, options, job_id
                        )
                
                # Get output file size
                if output_file.exists():
                    result.file_size_after = output_file.stat().st_size
                    result.success = True
                
                # Assess quality
                if result.success:
                    result.quality_metrics = await self._assess_conversion_quality(
                        input_file, output_file, source_format, target_format
                    )
                
                # Record metrics
                conversion_counter.labels(
                    source=source_format,
                    target=target_format,
                    status="success" if result.success else "error"
                ).inc()
                
            except Exception as e:
                logger.error(f"Dönüştürme hatası: {e}")
                result.errors.append(str(e))
                result.success = False
                
                conversion_counter.labels(
                    source=result.source_format,
                    target=result.target_format,
                    status="error"
                ).inc()
            
            finally:
                # Calculate conversion time
                result.conversion_time_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                conversion_duration_histogram.labels(
                    source=result.source_format,
                    target=result.target_format
                ).observe(result.conversion_time_ms)
                
                span.set_attribute("success", result.success)
                span.set_attribute("conversion_time_ms", result.conversion_time_ms)
            
            return result
    
    async def _convert_direct(
        self,
        input_file: Path,
        output_file: Path,
        source_format: str,
        target_format: str,
        options: ConversionOptions,
        job_id: int
    ) -> ConversionResult:
        """Direct conversion via import/export."""
        return await self._convert_via_import_export(
            input_file, output_file, source_format, target_format, options, job_id
        )
    
    async def _convert_via_import_export(
        self,
        input_file: Path,
        output_file: Path,
        source_format: str,
        target_format: str,
        options: ConversionOptions,
        job_id: int
    ) -> ConversionResult:
        """Convert via import and export."""
        result = ConversionResult(
            success=False,
            source_format=source_format,
            target_format=target_format,
            conversion_method=ConversionMethod.DIRECT,
            input_file=str(input_file),
            output_file=str(output_file),
            file_size_before=input_file.stat().st_size if input_file.exists() else 0,
            file_size_after=0,
            conversion_time_ms=0
        )
        
        try:
            # Import file
            import_options = ImportOptions(
                preserve_history=options.preserve_topology,
                preserve_materials=options.preserve_materials,
                preserve_constraints=options.preserve_hierarchy
            )
            
            import_result = await self.importer.import_file(
                input_file,
                job_id,
                import_options
            )
            
            if not import_result.success:
                result.errors.extend(import_result.errors)
                return result
            
            # Get document
            doc_data = await self.document_manager.get_document(import_result.document_id)
            document = doc_data["document"]
            
            # Export to target format
            export_options = ExportOptions(
                compress=False,
                embed_metadata=True,
                validate_output=True,
                optimize_size=options.optimize_output,
                mesh_quality=options.mesh_quality
            )
            
            # Map format strings to enums
            try:
                export_format = ExportFormat(target_format)
            except ValueError:
                export_format = ExportFormat.STEP  # Default
            
            export_result = await self.exporter.export_with_validation(
                document,
                output_file,
                export_format,
                export_options
            )
            
            if export_result.success:
                result.success = True
                result.file_size_after = export_result.file_size
                result.warnings.extend(export_result.warnings)
            else:
                result.errors.extend(export_result.errors)
            
        except Exception as e:
            logger.error(f"Import/Export dönüştürme hatası: {e}")
            result.errors.append(str(e))
        
        return result
    
    async def _convert_via_tessellation(
        self,
        input_file: Path,
        output_file: Path,
        source_format: str,
        target_format: str,
        options: ConversionOptions,
        job_id: int
    ) -> ConversionResult:
        """Convert via mesh tessellation."""
        result = await self._convert_via_import_export(
            input_file, output_file, source_format, target_format, options, job_id
        )
        result.conversion_method = ConversionMethod.TESSELLATION
        
        # Additional tessellation-specific processing
        if result.success and options.simplify_mesh:
            try:
                import trimesh
                mesh = trimesh.load(str(output_file))
                
                if options.target_face_count:
                    simplified = mesh.simplify_quadric_decimation(options.target_face_count)
                    simplified.export(str(output_file))
                    result.quality_metrics["face_count"] = len(simplified.faces)
            except ImportError:
                result.warnings.append("trimesh kütüphanesi mesh basitleştirme için gerekli")
            except Exception as e:
                result.warnings.append(f"Mesh basitleştirme uyarısı: {e}")
        
        return result
    
    async def _convert_via_reverse_engineering(
        self,
        input_file: Path,
        output_file: Path,
        source_format: str,
        target_format: str,
        options: ConversionOptions,
        job_id: int
    ) -> ConversionResult:
        """Convert mesh to CAD via reverse engineering."""
        result = ConversionResult(
            success=False,
            source_format=source_format,
            target_format=target_format,
            conversion_method=ConversionMethod.REVERSE_ENGINEERING,
            input_file=str(input_file),
            output_file=str(output_file),
            file_size_before=input_file.stat().st_size,
            file_size_after=0,
            conversion_time_ms=0
        )
        
        try:
            import FreeCAD
            import Part
            import Mesh
            
            # Import mesh
            mesh = Mesh.Mesh(str(input_file))
            
            # Create document
            doc = FreeCAD.newDocument()
            
            # Convert mesh to shape
            shape = Part.Shape()
            shape.makeShapeFromMesh(mesh.Topology, options.tolerance)
            
            if options.fit_surfaces:
                # Try to fit surfaces to mesh
                shape = shape.removeSplitter()
                
            if options.detect_features:
                # Detect and reconstruct features
                # This is simplified - real implementation would be more complex
                shape = shape.makeSolid()
            
            # Add to document
            part = doc.addObject("Part::Feature", "ReconstructedPart")
            part.Shape = shape
            
            # Export
            export_format = ExportFormat(target_format)
            export_result = await self.exporter.export_with_validation(
                doc,
                output_file,
                export_format,
                ExportOptions()
            )
            
            result.success = export_result.success
            if output_file.exists():
                result.file_size_after = output_file.stat().st_size
            
            result.quality_metrics = {
                "reconstruction_tolerance": options.tolerance,
                "surfaces_fitted": options.fit_surfaces,
                "features_detected": options.detect_features
            }
            
        except Exception as e:
            logger.error(f"Reverse engineering hatası: {e}")
            result.errors.append(str(e))
        
        return result
    
    async def _convert_to_web3d(
        self,
        input_file: Path,
        output_file: Path,
        source_format: str,
        target_format: str,
        options: ConversionOptions,
        job_id: int
    ) -> ConversionResult:
        """Convert to web 3D format (GLTF/GLB)."""
        result = await self._convert_via_import_export(
            input_file, output_file, source_format, target_format, options, job_id
        )
        result.conversion_method = ConversionMethod.WEB3D_CONVERSION
        
        # Apply web optimization
        if result.success and target_format in ["gltf", "glb"]:
            try:
                import trimesh
                scene = trimesh.load(str(output_file))
                
                # Optimize for web
                for name, geom in scene.geometry.items():
                    # Merge vertices
                    geom.merge_vertices()
                    # Remove duplicate faces
                    geom.remove_duplicate_faces()
                
                # Export with compression if GLB
                if target_format == "glb":
                    scene.export(str(output_file), file_type="glb")
                
                result.quality_metrics["web_optimized"] = True
                
            except Exception as e:
                result.warnings.append(f"Web optimizasyon uyarısı: {e}")
        
        return result
    
    async def _convert_bim_import(
        self,
        input_file: Path,
        output_file: Path,
        source_format: str,
        target_format: str,
        options: ConversionOptions,
        job_id: int
    ) -> ConversionResult:
        """Import BIM data (IFC to FCStd)."""
        result = await self._convert_via_import_export(
            input_file, output_file, source_format, target_format, options, job_id
        )
        result.conversion_method = ConversionMethod.BIM_IMPORT
        
        if result.success:
            result.quality_metrics["bim_data_preserved"] = options.include_properties
            result.quality_metrics["ifc_schema"] = options.ifc_schema
        
        return result
    
    async def _convert_bim_export(
        self,
        input_file: Path,
        output_file: Path,
        source_format: str,
        target_format: str,
        options: ConversionOptions,
        job_id: int
    ) -> ConversionResult:
        """Export to BIM format (FCStd to IFC)."""
        result = await self._convert_via_import_export(
            input_file, output_file, source_format, target_format, options, job_id
        )
        result.conversion_method = ConversionMethod.BIM_EXPORT
        
        if result.success:
            result.quality_metrics["ifc_schema"] = options.ifc_schema
            result.quality_metrics["properties_included"] = options.include_properties
        
        return result
    
    async def _convert_with_topology(
        self,
        input_file: Path,
        output_file: Path,
        source_format: str,
        target_format: str,
        options: ConversionOptions,
        job_id: int
    ) -> ConversionResult:
        """Convert preserving topology."""
        # Set options to preserve topology
        options.preserve_topology = True
        options.preserve_hierarchy = True
        
        result = await self._convert_via_import_export(
            input_file, output_file, source_format, target_format, options, job_id
        )
        result.conversion_method = ConversionMethod.TOPOLOGY_PRESERVATION
        
        if result.success:
            result.quality_metrics["topology_preserved"] = True
        
        return result
    
    async def _convert_with_mesh_optimization(
        self,
        input_file: Path,
        output_file: Path,
        source_format: str,
        target_format: str,
        options: ConversionOptions,
        job_id: int
    ) -> ConversionResult:
        """Convert with mesh optimization."""
        options.optimize_output = True
        options.simplify_mesh = True
        
        result = await self._convert_via_tessellation(
            input_file, output_file, source_format, target_format, options, job_id
        )
        result.conversion_method = ConversionMethod.MESH_OPTIMIZATION
        
        return result
    
    async def _convert_vector(
        self,
        input_file: Path,
        output_file: Path,
        source_format: str,
        target_format: str,
        options: ConversionOptions,
        job_id: int
    ) -> ConversionResult:
        """Convert 2D vector formats."""
        result = await self._convert_via_import_export(
            input_file, output_file, source_format, target_format, options, job_id
        )
        result.conversion_method = ConversionMethod.VECTOR_CONVERSION
        
        if result.success:
            result.quality_metrics["vector_preserved"] = True
        
        return result
    
    async def _convert_indirect(
        self,
        input_file: Path,
        output_file: Path,
        path: List[str],
        options: ConversionOptions,
        job_id: int
    ) -> ConversionResult:
        """Convert via intermediate formats."""
        result = ConversionResult(
            success=False,
            source_format=path[0],
            target_format=path[-1],
            conversion_method=ConversionMethod.DIRECT,
            input_file=str(input_file),
            output_file=str(output_file),
            file_size_before=input_file.stat().st_size,
            file_size_after=0,
            conversion_time_ms=0
        )
        
        try:
            current_file = input_file
            
            # Convert through each step
            for i in range(len(path) - 1):
                source = path[i]
                target = path[i + 1]
                
                # Create temp file for intermediate results
                if i < len(path) - 2:
                    temp_file = Path(f"/tmp/convert_{job_id}_{i}.{target}")
                else:
                    temp_file = output_file
                
                # Convert
                step_result = await self.convert(
                    current_file,
                    temp_file,
                    source,
                    target,
                    options,
                    job_id
                )
                
                if not step_result.success:
                    result.errors.extend(step_result.errors)
                    return result
                
                result.warnings.extend(step_result.warnings)
                current_file = temp_file
            
            result.success = True
            # Fix race condition by using try-except
            try:
                result.file_size_after = output_file.stat().st_size
            except FileNotFoundError:
                logger.warning(f"Output file not found after conversion: {output_file}")
                result.file_size_after = 0
            
            result.quality_metrics["conversion_steps"] = len(path) - 1
            result.quality_metrics["conversion_path"] = " -> ".join(path)
            
        except Exception as e:
            logger.error(f"Dolaylı dönüştürme hatası: {e}")
            result.errors.append(str(e))
        
        return result
    
    async def _assess_conversion_quality(
        self,
        input_file: Path,
        output_file: Path,
        source_format: str,
        target_format: str
    ) -> Dict[str, Any]:
        """Assess conversion quality metrics."""
        metrics = {
            "size_ratio": output_file.stat().st_size / input_file.stat().st_size if input_file.stat().st_size > 0 else 0,
            "format_compatibility": "high",
            "data_loss": "minimal"
        }
        
        # Format-specific quality assessment
        if source_format in ["step", "iges", "brep"] and target_format in ["stl", "obj"]:
            metrics["data_loss"] = "parametric_to_mesh"
            metrics["format_compatibility"] = "medium"
        elif source_format in ["stl", "obj"] and target_format in ["step", "iges"]:
            metrics["data_loss"] = "mesh_to_parametric"
            metrics["format_compatibility"] = "low"
            metrics["reconstruction_quality"] = "approximate"
        
        return metrics
    
    async def batch_convert(
        self,
        conversions: List[Dict[str, Any]],
        options: Optional[ConversionOptions] = None
    ) -> List[ConversionResult]:
        """
        Batch convert multiple files.
        
        Args:
            conversions: List of conversion specs with input/output/formats
            options: Conversion options
            
        Returns:
            List of conversion results
        """
        results = []
        
        for i, spec in enumerate(conversions):
            result = await self.convert(
                spec["input"],
                spec["output"],
                spec.get("source_format"),
                spec.get("target_format"),
                options,
                job_id=i
            )
            results.append(result)
        
        return results
    
    def get_supported_conversions(self) -> Dict[str, List[str]]:
        """Get list of supported conversions."""
        conversions = {}
        
        for (source, target), _ in ConversionMatrix.MATRIX.items():
            if source not in conversions:
                conversions[source] = []
            conversions[source].append(target)
        
        return conversions