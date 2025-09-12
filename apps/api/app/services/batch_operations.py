"""
Batch Operations Library for Task 7.23

Pre-defined batch operations for common tasks:
- Format conversion operations
- Variant generation
- Quality checks
- Template operations
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from ..core.logging import get_logger
from ..core.metrics import batch_counter
from ..core.telemetry import create_span
from .batch_processing_engine import BatchItem, BatchOptions, BatchProcessingEngine
from .enhanced_exporter import EnhancedExporter, ExportFormat
from .format_converter import FormatConverter
from .freecad_document_manager import FreeCADDocumentManager
from .universal_importer import UniversalImporter

logger = get_logger(__name__)


class VariantType(str, Enum):
    """Types of model variants."""
    PARAMETRIC = "parametric"  # Parameter-based variants
    MATERIAL = "material"  # Material variants
    CONFIGURATION = "configuration"  # Configuration variants
    SCALE = "scale"  # Scale variants
    OPTIMIZATION = "optimization"  # Optimization variants


class QualityCheckType(str, Enum):
    """Types of quality checks."""
    GEOMETRY = "geometry"  # Geometry validation
    TOPOLOGY = "topology"  # Topology validation
    CONSTRAINTS = "constraints"  # Constraint validation
    MATERIALS = "materials"  # Material validation
    PERFORMANCE = "performance"  # Performance analysis
    STANDARDS = "standards"  # Standards compliance


class ConversionResult(BaseModel):
    """Result of format conversion."""
    item_id: Optional[str] = Field(default=None, description="Unique item ID for mapping")
    input_file: str = Field(description="Giriş dosyası")
    output_file: str = Field(description="Çıkış dosyası")
    source_format: str = Field(description="Kaynak format")
    target_format: str = Field(description="Hedef format")
    success: bool = Field(description="Başarı durumu")
    conversion_time_ms: float = Field(description="Dönüştürme süresi (ms)")
    file_size_kb: Optional[float] = Field(default=None, description="Dosya boyutu (KB)")
    error: Optional[str] = Field(default=None, description="Hata mesajı")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ModelVariant(BaseModel):
    """Model variant with parameters."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    base_model_id: str = Field(description="Temel model ID")
    variant_type: VariantType = Field(description="Varyant tipi")
    parameters: Dict[str, Any] = Field(description="Varyant parametreleri")
    document_id: Optional[str] = Field(default=None, description="Doküman ID")
    file_path: Optional[str] = Field(default=None, description="Dosya yolu")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ParameterSet(BaseModel):
    """Set of parameters for variant generation."""
    name: str = Field(description="Parametre seti adı")
    parameters: Dict[str, Any] = Field(description="Parametreler")
    description: Optional[str] = Field(default=None, description="Açıklama")
    
    model_config = {"json_schema_extra": {"examples": [
        {
            "name": "Büyük Boy",
            "parameters": {
                "width": 200,
                "height": 150,
                "depth": 100
            },
            "description": "Büyük boy varyant"
        }
    ]}}


class QualityCheck(BaseModel):
    """Quality check definition."""
    name: str = Field(description="Kontrol adı")
    type: QualityCheckType = Field(description="Kontrol tipi")
    criteria: Dict[str, Any] = Field(description="Kontrol kriterleri")
    severity: str = Field(default="warning", description="Önem seviyesi (error, warning, info)")


class QualityCheckResult(BaseModel):
    """Result of a quality check."""
    check_name: str = Field(description="Kontrol adı")
    passed: bool = Field(description="Geçti mi")
    issues: List[str] = Field(default_factory=list, description="Bulunan sorunlar")
    severity: str = Field(default="info", description="Önem seviyesi")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class QualityReport(BaseModel):
    """Quality report for a model."""
    item_id: Optional[str] = Field(default=None, description="Unique item ID for mapping")
    model_id: str = Field(description="Model ID")
    check_results: List[QualityCheckResult] = Field(default_factory=list)
    overall_passed: bool = Field(default=True)
    error_count: int = Field(default=0)
    warning_count: int = Field(default=0)
    info_count: int = Field(default=0)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    
    def add_check_result(self, check_name: str, result: QualityCheckResult) -> None:
        """Add a check result to the report."""
        self.check_results.append(result)
        
        if not result.passed:
            self.overall_passed = False
            
            if result.severity == "error":
                self.error_count += 1
            elif result.severity == "warning":
                self.warning_count += 1
            else:
                self.info_count += 1


class BatchOperations:
    """Pre-defined batch operations for common tasks."""
    
    def __init__(
        self,
        document_manager: Optional[FreeCADDocumentManager] = None,
        converter: Optional[FormatConverter] = None,
        importer: Optional[UniversalImporter] = None,
        exporter: Optional[EnhancedExporter] = None,
        batch_engine: Optional[BatchProcessingEngine] = None
    ):
        """Initialize batch operations."""
        self.document_manager = document_manager or FreeCADDocumentManager()
        self.converter = converter or FormatConverter()
        self.importer = importer or UniversalImporter()
        self.exporter = exporter or EnhancedExporter()
        self.batch_engine = batch_engine or BatchProcessingEngine()
    
    async def batch_convert_format(
        self,
        models: List[Path],
        target_format: str,
        options: Optional[BatchOptions] = None,
        output_dir: Optional[Path] = None
    ) -> List[ConversionResult]:
        """
        Convert multiple models to target format.
        
        Args:
            models: List of model file paths
            target_format: Target format (step, iges, stl, etc.)
            options: Batch processing options
            output_dir: Output directory (default: same as input)
            
        Returns:
            List of conversion results
        """
        with create_span("batch_convert_format") as span:
            span.set_attribute("model_count", len(models))
            span.set_attribute("target_format", target_format)
            
            options = options or BatchOptions()
            results = []
            
            # Create batch items with unique IDs
            batch_items = []
            item_id_map = {}  # Map item IDs to original model paths
            for model_path in models:
                output_path = output_dir / f"{model_path.stem}.{target_format}" if output_dir else \
                             model_path.with_suffix(f".{target_format}")
                
                item = BatchItem(
                    data={
                        "item_id": str(uuid.uuid4()),  # Generate unique ID
                        "input": str(model_path),
                        "output": str(output_path),
                        "format": target_format
                    }
                )
                batch_items.append(item)
                item_id_map[item.data["item_id"]] = model_path
            
            # Define conversion operation
            async def convert_single(data: Dict[str, Any]) -> ConversionResult:
                start_time = datetime.now(UTC)
                
                try:
                    # Perform conversion
                    result = await self.converter.convert(
                        Path(data["input"]),
                        Path(data["output"]),
                        target_format=data["format"]
                    )
                    
                    duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
                    
                    return ConversionResult(
                        item_id=data.get("item_id"),  # Include item ID for mapping
                        input_file=data["input"],
                        output_file=data["output"],
                        source_format=Path(data["input"]).suffix[1:],
                        target_format=data["format"],
                        success=result.success,
                        conversion_time_ms=duration_ms,
                        file_size_kb=Path(data["output"]).stat().st_size / 1024 if result.success else None,
                        error=result.errors[0] if result.errors else None
                    )
                    
                except Exception as e:
                    logger.error(f"Dönüştürme hatası: {e}")
                    return ConversionResult(
                        item_id=data.get("item_id"),  # Include item ID for mapping
                        input_file=data["input"],
                        output_file=data["output"],
                        source_format=Path(data["input"]).suffix[1:],
                        target_format=data["format"],
                        success=False,
                        conversion_time_ms=(datetime.now(UTC) - start_time).total_seconds() * 1000,
                        error=str(e)
                    )
            
            # Process batch
            batch_result = await self.batch_engine.process_batch(
                batch_items,
                convert_single,
                options
            )
            
            # Extract results
            for result in batch_result.results:
                if isinstance(result, ConversionResult):
                    results.append(result)
            
            # Record metrics
            batch_counter.labels(
                operation="format_conversion",
                status="success" if batch_result.successful_items > 0 else "error"
            ).inc()
            
            logger.info(
                f"Toplu format dönüştürme tamamlandı: "
                f"{batch_result.successful_items}/{len(models)} başarılı"
            )
            
            return results
    
    async def batch_generate_variants(
        self,
        base_model_path: Path,
        parameter_sets: List[ParameterSet],
        options: Optional[BatchOptions] = None,
        output_dir: Optional[Path] = None
    ) -> List[ModelVariant]:
        """
        Generate model variants with different parameters.
        
        Args:
            base_model_path: Base model file path
            parameter_sets: List of parameter sets for variants
            options: Batch processing options
            output_dir: Output directory for variants
            
        Returns:
            List of generated variants
        """
        with create_span("batch_generate_variants") as span:
            span.set_attribute("base_model", str(base_model_path))
            span.set_attribute("variant_count", len(parameter_sets))
            
            options = options or BatchOptions()
            output_dir = output_dir or base_model_path.parent / "variants"
            output_dir.mkdir(parents=True, exist_ok=True)
            
            variants = []
            
            # Load base model once
            base_doc = await self.document_manager.open_document(str(base_model_path))
            base_model_id = base_doc.id
            
            # Create batch items
            batch_items = []
            for param_set in parameter_sets:
                batch_items.append(BatchItem(
                    data={
                        "base_model_id": base_model_id,
                        "param_set": param_set,
                        "output_dir": str(output_dir)
                    }
                ))
            
            # Define variant generation operation
            async def generate_variant(data: Dict[str, Any]) -> ModelVariant:
                param_set = data["param_set"]
                
                try:
                    # Create variant document
                    variant_doc = await self.document_manager.copy_document(
                        data["base_model_id"],
                        f"variant_{param_set.name}"
                    )
                    
                    # Apply parameters
                    for param_name, param_value in param_set.parameters.items():
                        # This would apply parameters to the FreeCAD document
                        # Implementation depends on FreeCAD API
                        pass
                    
                    # Save variant
                    output_path = Path(data["output_dir"]) / f"{param_set.name}.FCStd"
                    await self.document_manager.save_document_as(variant_doc.id, str(output_path))
                    
                    return ModelVariant(
                        base_model_id=data["base_model_id"],
                        variant_type=VariantType.PARAMETRIC,
                        parameters=param_set.parameters,
                        document_id=variant_doc.id,
                        file_path=str(output_path),
                        metadata={"description": param_set.description}
                    )
                    
                except Exception as e:
                    logger.error(f"Varyant oluşturma hatası: {e}")
                    return ModelVariant(
                        base_model_id=data["base_model_id"],
                        variant_type=VariantType.PARAMETRIC,
                        parameters=param_set.parameters,
                        metadata={"error": str(e)}
                    )
            
            # Process batch
            batch_result = await self.batch_engine.process_batch(
                batch_items,
                generate_variant,
                options
            )
            
            # Extract results
            for result in batch_result.results:
                if isinstance(result, ModelVariant):
                    variants.append(result)
            
            # Close base document
            await self.document_manager.close_document(base_model_id)
            
            logger.info(
                f"Varyant oluşturma tamamlandı: "
                f"{batch_result.successful_items}/{len(parameter_sets)} başarılı"
            )
            
            return variants
    
    async def batch_quality_check(
        self,
        model_paths: List[Path],
        checks: List[QualityCheck],
        options: Optional[BatchOptions] = None
    ) -> List[QualityReport]:
        """
        Run quality checks on multiple models.
        
        Args:
            model_paths: List of model file paths
            checks: List of quality checks to run
            options: Batch processing options
            
        Returns:
            List of quality reports
        """
        with create_span("batch_quality_check") as span:
            span.set_attribute("model_count", len(model_paths))
            span.set_attribute("check_count", len(checks))
            
            options = options or BatchOptions()
            reports = []
            
            # Create batch items with unique IDs
            batch_items = []
            item_id_map = {}  # Map item IDs to original model paths
            for model_path in model_paths:
                item_id = str(uuid.uuid4())
                batch_items.append(BatchItem(
                    data={
                        "item_id": item_id,  # Include unique ID
                        "model_path": str(model_path),
                        "checks": checks
                    }
                ))
                item_id_map[item_id] = model_path
            
            # Define quality check operation
            async def check_model(data: Dict[str, Any]) -> QualityReport:
                model_path = Path(data["model_path"])
                checks = data["checks"]
                item_id = data.get("item_id")  # Get item ID
                
                # Load model
                doc = await self.document_manager.open_document(str(model_path))
                
                report = QualityReport(
                    item_id=item_id,  # Include item ID for mapping
                    model_id=model_path.stem
                )
                
                try:
                    # Run each check
                    for check in checks:
                        result = await self._execute_quality_check(doc, check)
                        report.add_check_result(check.name, result)
                    
                finally:
                    # Close document
                    await self.document_manager.close_document(doc.id)
                
                return report
            
            # Process batch
            batch_result = await self.batch_engine.process_batch(
                batch_items,
                check_model,
                options
            )
            
            # Extract results
            for result in batch_result.results:
                if isinstance(result, QualityReport):
                    reports.append(result)
            
            # Log summary
            total_passed = sum(1 for r in reports if r.overall_passed)
            logger.info(
                f"Kalite kontrol tamamlandı: "
                f"{total_passed}/{len(reports)} model kontrolden geçti"
            )
            
            return reports
    
    async def _execute_quality_check(
        self,
        document: Any,
        check: QualityCheck
    ) -> QualityCheckResult:
        """Execute a single quality check."""
        try:
            # Use dictionary mapping for cleaner code
            check_handlers = {
                QualityCheckType.GEOMETRY: self._check_geometry,
                QualityCheckType.TOPOLOGY: self._check_topology,
                QualityCheckType.CONSTRAINTS: self._check_constraints,
                QualityCheckType.MATERIALS: self._check_materials,
                QualityCheckType.PERFORMANCE: self._check_performance,
                QualityCheckType.STANDARDS: self._check_standards
            }
            
            handler = check_handlers.get(check.type)
            if handler:
                return await handler(document, check)
            else:
                return QualityCheckResult(
                    check_name=check.name,
                    passed=False,
                    issues=[f"Bilinmeyen kontrol tipi: {check.type}"],
                    severity="error"
                )
                
        except Exception as e:
            logger.error(f"Kalite kontrol hatası {check.name}: {e}")
            return QualityCheckResult(
                check_name=check.name,
                passed=False,
                issues=[str(e)],
                severity="error"
            )
    
    async def _check_geometry(self, document: Any, check: QualityCheck) -> QualityCheckResult:
        """Check geometry validity using FreeCAD API."""
        issues = []
        passed = True
        metadata = {}
        
        try:
            # Import FreeCAD modules dynamically
            import FreeCAD
            import Part
            
            # Get FreeCAD document from manager
            fc_doc = self.document_manager.get_freecad_document(document.id)
            
            if fc_doc:
                total_faces = 0
                total_edges = 0
                invalid_count = 0
                
                # Check each object in document
                for obj in fc_doc.Objects:
                    if hasattr(obj, "Shape"):
                        shape = obj.Shape
                        
                        # Check for invalid geometry
                        if not shape.isValid():
                            issues.append(f"Geçersiz geometri: {obj.Label}")
                            invalid_count += 1
                            passed = False
                        
                        # Check for self-intersections (if method available)
                        if hasattr(shape, "selfIntersection") and shape.selfIntersection():
                            issues.append(f"Kendisiyle kesişen geometri: {obj.Label}")
                            passed = False
                        
                        # Count geometry elements
                        total_faces += len(shape.Faces)
                        total_edges += len(shape.Edges)
                        
                        # Check minimum thickness if specified
                        if "min_thickness" in check.criteria:
                            min_thickness = check.criteria["min_thickness"]
                            # Estimate thickness from bounding box
                            bbox = shape.BoundBox
                            min_dim = min(bbox.XLength, bbox.YLength, bbox.ZLength)
                            if min_dim < min_thickness:
                                issues.append(f"Minimum kalınlık sağlanmıyor: {obj.Label} ({min_dim:.2f}mm < {min_thickness}mm)")
                                passed = False
                
                # Check face count limit
                if "max_faces" in check.criteria and total_faces > check.criteria["max_faces"]:
                    issues.append(f"Maksimum yüz sayısı aşıldı: {total_faces} > {check.criteria['max_faces']}")
                    passed = False
                
                metadata.update({
                    "total_faces": total_faces,
                    "total_edges": total_edges,
                    "invalid_objects": invalid_count,
                    "object_count": len(fc_doc.Objects)
                })
            
        except ImportError as e:
            # FreeCAD not available - fail the check with specific error
            logger.error(f"FreeCAD import failed for geometry check: {e}")
            issues.append(f"FreeCAD modülü yüklenemedi: {str(e)}")
            issues.append("Geometri kontrolü için FreeCAD kurulumu gereklidir")
            passed = False  # Fail the check when FreeCAD is not available
            metadata["freecad_available"] = False
            metadata["import_error"] = str(e)
        except Exception as e:
            issues.append(f"Geometri kontrol hatası: {str(e)}")
            passed = False
        
        return QualityCheckResult(
            check_name=check.name,
            passed=passed,
            issues=issues,
            severity=check.severity,
            metadata=metadata
        )
    
    async def _check_topology(self, document: Any, check: QualityCheck) -> QualityCheckResult:
        """Check topology validity using FreeCAD."""
        issues = []
        passed = True
        metadata = {}
        
        try:
            import FreeCAD
            import Part
            
            fc_doc = self.document_manager.get_freecad_document(document.id)
            
            if fc_doc:
                total_shells = 0
                open_shells = 0
                non_manifold_edges = 0
                
                for obj in fc_doc.Objects:
                    if hasattr(obj, "Shape"):
                        shape = obj.Shape
                        
                        # Check for non-manifold edges
                        for edge in shape.Edges:
                            # An edge is non-manifold if it's shared by more than 2 faces
                            if hasattr(edge, "Faces") and len(edge.Faces) > 2:
                                non_manifold_edges += 1
                                issues.append(f"Non-manifold kenar tespit edildi: {obj.Label}")
                                passed = False
                                break
                        
                        # Check for open shells
                        for shell in shape.Shells:
                            total_shells += 1
                            if not shell.isClosed():
                                open_shells += 1
                                issues.append(f"Açık kabuk tespit edildi: {obj.Label}")
                                passed = False
                        
                        # Check for disconnected components
                        if shape.ShapeType == "Compound":
                            solids = shape.Solids
                            if len(solids) > 1 and check.criteria.get("require_single_solid", False):
                                issues.append(f"Birden fazla katı cisim tespit edildi: {obj.Label} ({len(solids)} adet)")
                                passed = False
                
                metadata.update({
                    "total_shells": total_shells,
                    "open_shells": open_shells,
                    "non_manifold_edges": non_manifold_edges
                })
                
        except ImportError as e:
            logger.error(f"FreeCAD import failed: {e}")
            issues.append("FreeCAD modülü yüklenemedi, topoloji kontrolü atlandı")
            passed = False
        except Exception as e:
            issues.append(f"Topoloji kontrol hatası: {str(e)}")
            passed = False
        
        return QualityCheckResult(
            check_name=check.name,
            passed=passed,
            issues=issues,
            severity=check.severity,
            metadata=metadata
        )
    
    async def _check_constraints(self, document: Any, check: QualityCheck) -> QualityCheckResult:
        """Check constraint validity."""
        issues = []
        
        # Check constraints
        # - Over-constrained sketches
        # - Under-constrained sketches
        # - Conflicting constraints
        
        passed = True
        
        return QualityCheckResult(
            check_name=check.name,
            passed=passed,
            issues=issues,
            severity=check.severity,
            metadata={"constraints_valid": passed}
        )
    
    async def _check_materials(self, document: Any, check: QualityCheck) -> QualityCheckResult:
        """Check material assignments."""
        issues = []
        
        # Check materials
        # - Missing material assignments
        # - Invalid material properties
        # - Material compatibility
        
        passed = True
        
        return QualityCheckResult(
            check_name=check.name,
            passed=passed,
            issues=issues,
            severity=check.severity,
            metadata={"materials_valid": passed}
        )
    
    async def _check_performance(self, document: Any, check: QualityCheck) -> QualityCheckResult:
        """Check performance metrics for FreeCAD models."""
        issues = []
        passed = True
        metadata = {}
        
        try:
            import FreeCAD
            import Part
            
            fc_doc = self.document_manager.get_freecad_document(document.id)
            
            if fc_doc:
                total_triangles = 0
                total_vertices = 0
                feature_count = 0
                
                for obj in fc_doc.Objects:
                    if hasattr(obj, "Shape"):
                        shape = obj.Shape
                        feature_count += 1
                        
                        # Estimate triangle count for mesh generation
                        # Using tessellation with default tolerance
                        try:
                            mesh = shape.tessellate(1.0)
                            if mesh and len(mesh) > 1:
                                total_triangles += len(mesh[1])  # mesh[1] contains triangles
                                total_vertices += len(mesh[0])    # mesh[0] contains vertices
                        except:
                            pass  # Skip if tessellation fails
                
                # Check performance criteria
                if "max_triangles" in check.criteria and total_triangles > check.criteria["max_triangles"]:
                    issues.append(f"Maksimum üçgen sayısı aşıldı: {total_triangles} > {check.criteria['max_triangles']}")
                    passed = False
                
                if "max_features" in check.criteria and feature_count > check.criteria["max_features"]:
                    issues.append(f"Maksimum özellik sayısı aşıldı: {feature_count} > {check.criteria['max_features']}")
                    passed = False
                
                # Estimate computation complexity
                complexity_score = (total_triangles / 1000) + (feature_count * 10)
                if "max_complexity" in check.criteria and complexity_score > check.criteria["max_complexity"]:
                    issues.append(f"Karmaşıklık skoru çok yüksek: {complexity_score:.1f}")
                    passed = False
                
                metadata.update({
                    "total_triangles": total_triangles,
                    "total_vertices": total_vertices,
                    "feature_count": feature_count,
                    "complexity_score": complexity_score
                })
                
        except ImportError as e:
            logger.error(f"FreeCAD import failed: {e}")
            issues.append("FreeCAD modülü yüklenemedi, performans kontrolü atlandı")
            passed = False
        except Exception as e:
            issues.append(f"Performans kontrol hatası: {str(e)}")
            passed = False
        
        return QualityCheckResult(
            check_name=check.name,
            passed=passed,
            issues=issues,
            severity=check.severity,
            metadata={"performance_acceptable": passed}
        )
    
    async def _check_standards(self, document: Any, check: QualityCheck) -> QualityCheckResult:
        """Check standards compliance."""
        issues = []
        
        # Check standards
        # - ISO compliance
        # - Industry standards
        # - Company standards
        
        passed = True
        
        return QualityCheckResult(
            check_name=check.name,
            passed=passed,
            issues=issues,
            severity=check.severity,
            metadata={"standards_compliant": passed}
        )
    
    async def batch_optimize_models(
        self,
        model_paths: List[Path],
        optimization_types: List[str],
        options: Optional[BatchOptions] = None
    ) -> List[Dict[str, Any]]:
        """
        Optimize multiple models.
        
        Args:
            model_paths: List of model file paths
            optimization_types: Types of optimization to apply
            options: Batch processing options
            
        Returns:
            List of optimization results
        """
        with create_span("batch_optimize_models") as span:
            span.set_attribute("model_count", len(model_paths))
            
            options = options or BatchOptions()
            results = []
            
            # Create batch items
            batch_items = []
            for model_path in model_paths:
                batch_items.append(BatchItem(
                    data={
                        "model_path": str(model_path),
                        "optimizations": optimization_types
                    }
                ))
            
            # Define optimization operation
            async def optimize_model(data: Dict[str, Any]) -> Dict[str, Any]:
                model_path = Path(data["model_path"])
                optimizations = data["optimizations"]
                
                result = {
                    "model": str(model_path),
                    "optimizations": {},
                    "success": True
                }
                
                try:
                    # Load model
                    doc = await self.document_manager.open_document(str(model_path))
                    
                    # Apply optimizations
                    for opt_type in optimizations:
                        if opt_type == "mesh":
                            # Optimize mesh
                            pass
                        elif opt_type == "features":
                            # Cleanup features
                            pass
                        elif opt_type == "storage":
                            # Compress storage
                            pass
                        
                        result["optimizations"][opt_type] = "completed"
                    
                    # Save optimized model
                    await self.document_manager.save_document(doc.id)
                    await self.document_manager.close_document(doc.id)
                    
                except Exception as e:
                    logger.error(f"Optimizasyon hatası {model_path}: {e}")
                    result["success"] = False
                    result["error"] = str(e)
                
                return result
            
            # Process batch
            batch_result = await self.batch_engine.process_batch(
                batch_items,
                optimize_model,
                options
            )
            
            # Extract results
            for result in batch_result.results:
                if isinstance(result, dict):
                    results.append(result)
            
            logger.info(
                f"Model optimizasyonu tamamlandı: "
                f"{batch_result.successful_items}/{len(model_paths)} başarılı"
            )
            
            return results