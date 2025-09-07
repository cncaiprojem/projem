"""
API Endpoints for Task 7.20 - Multi-format Import/Export Pipeline

Provides comprehensive REST API for:
- Universal import with 30+ formats
- Enhanced export with validation
- Format conversion
- Batch operations
- Format information
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_async_db
from ...core.logging import get_logger
from ...core.security import get_current_user
from ...core.telemetry import create_span
from ...models.user import User
from ...models.artefact import Artefact
from ...schemas.artefact import ArtefactCreate
from ...services.artefact_service import ArtefactService
from ...services.universal_importer import (
    ImportFormat,
    ImportOptions,
    ImportResult,
    UniversalImporter,
)
from ...services.enhanced_exporter import (
    EnhancedExporter,
    ExportFormat,
    ExportOptions,
    ExportResult,
)
from ...services.format_converter import (
    ConversionOptions,
    ConversionResult,
    FormatConverter,
)
from ...services.batch_import_export import (
    BatchOptions,
    BatchProcessor,
    BatchProgress,
    BatchResult,
)
from ...services.freecad_document_manager import FreeCADDocumentManager
from ...services.storage_client import StorageClient

logger = get_logger(__name__)

router = APIRouter(prefix="/import-export", tags=["import-export"])

# Service instances (could be dependency injected)
importer = UniversalImporter()
exporter = EnhancedExporter()
converter = FormatConverter()
batch_processor = BatchProcessor()
document_manager = FreeCADDocumentManager()
storage_client = StorageClient()


class ImportRequest(BaseModel):
    """Request model for import operation."""
    file_url: Optional[str] = Field(None, description="Dosya URL'si (S3/MinIO)")
    artefact_id: Optional[int] = Field(None, description="Artefakt ID")
    job_id: int = Field(description="İş ID")
    options: Optional[ImportOptions] = Field(default_factory=ImportOptions)
    
    model_config = {"json_schema_extra": {"examples": [
        {
            "file_url": "s3://bucket/file.step",
            "job_id": 123,
            "options": {
                "preserve_materials": True,
                "unit_system": "metric"
            }
        }
    ]}}


class ExportRequest(BaseModel):
    """Request model for export operation."""
    document_id: str = Field(description="Doküman ID")
    format: ExportFormat = Field(description="Hedef format")
    options: Optional[ExportOptions] = Field(default_factory=ExportOptions)
    
    model_config = {"json_schema_extra": {"examples": [
        {
            "document_id": "doc_123",
            "format": "step",
            "options": {
                "step_schema": "AP214",
                "embed_metadata": True
            }
        }
    ]}}


class ConversionRequest(BaseModel):
    """Request model for conversion operation."""
    source_url: Optional[str] = Field(None, description="Kaynak dosya URL")
    source_artefact_id: Optional[int] = Field(None, description="Kaynak artefakt ID")
    target_format: str = Field(description="Hedef format")
    options: Optional[ConversionOptions] = Field(default_factory=ConversionOptions)
    
    model_config = {"json_schema_extra": {"examples": [
        {
            "source_url": "s3://bucket/file.stl",
            "target_format": "step",
            "options": {
                "quality": "high",
                "fit_surfaces": True
            }
        }
    ]}}


class BatchImportRequest(BaseModel):
    """Request model for batch import."""
    file_urls: List[str] = Field(description="Dosya URL listesi")
    options: Optional[BatchOptions] = Field(default_factory=BatchOptions)
    import_options: Optional[ImportOptions] = Field(default_factory=ImportOptions)
    job_id_prefix: str = Field(default="batch", description="İş ID öneki")


class BatchExportRequest(BaseModel):
    """Request model for batch export."""
    document_ids: List[str] = Field(description="Doküman ID listesi")
    formats: List[ExportFormat] = Field(description="Hedef formatlar")
    options: Optional[BatchOptions] = Field(default_factory=BatchOptions)
    export_options: Optional[ExportOptions] = Field(default_factory=ExportOptions)


class BatchConversionRequest(BaseModel):
    """Request model for batch conversion."""
    conversions: List[Dict[str, str]] = Field(description="Dönüşüm listesi")
    options: Optional[BatchOptions] = Field(default_factory=BatchOptions)
    conversion_options: Optional[ConversionOptions] = Field(default_factory=ConversionOptions)


class FormatInfo(BaseModel):
    """Information about a supported format."""
    format: str = Field(description="Format kodu")
    name: str = Field(description="Format adı")
    category: str = Field(description="Kategori")
    extensions: List[str] = Field(description="Dosya uzantıları")
    mime_types: List[str] = Field(default_factory=list, description="MIME tipleri")
    can_import: bool = Field(description="İçe aktarılabilir")
    can_export: bool = Field(description="Dışa aktarılabilir")
    description: str = Field(description="Açıklama")
    
    # Turkish descriptions
    description_tr: str = Field(description="Türkçe açıklama")


@router.post("/import", response_model=ImportResult, summary="İçe Aktar")
async def import_file(
    file: UploadFile = File(..., description="İçe aktarılacak dosya"),
    job_id: int = Form(..., description="İş ID"),
    preserve_materials: bool = Form(True, description="Malzemeleri koru"),
    unit_system: str = Form("metric", description="Birim sistemi"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> ImportResult:
    """
    Import a file with universal format support.
    
    Supports 30+ formats including:
    - CAD: STEP, IGES, BREP
    - Mesh: STL, OBJ, PLY
    - BIM: IFC
    - Web3D: GLTF, GLB
    """
    with create_span("api_import_file") as span:
        span.set_attribute("filename", file.filename)
        span.set_attribute("job_id", job_id)
        
        try:
            # Save uploaded file temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp:
                content = await file.read()
                tmp.write(content)
                tmp_path = Path(tmp.name)
            
            # Create import options
            import_options = ImportOptions(
                preserve_materials=preserve_materials,
                unit_system=unit_system
            )
            
            # Import file
            result = await importer.import_file(
                tmp_path,
                job_id,
                import_options
            )
            
            if result.success:
                # Create artefact record
                artefact_service = ArtefactService(db)
                artefact_data = ArtefactCreate(
                    name=file.filename,
                    type="imported_model",
                    s3_key=f"imports/{job_id}/{file.filename}",
                    mime_type=file.content_type or "application/octet-stream",
                    size=result.file_size,
                    metadata={
                        "format": result.format.value,
                        "import_metadata": result.metadata,
                        "statistics": result.statistics
                    }
                )
                
                await artefact_service.create_artefact(
                    artefact_data,
                    current_user.id,
                    job_id
                )
            
            # Clean up temp file
            tmp_path.unlink(missing_ok=True)
            
            return result
            
        except Exception as e:
            logger.error(f"İçe aktarma hatası: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"İçe aktarma başarısız: {str(e)}"
            )


@router.post("/export", response_model=ExportResult, summary="Dışa Aktar")
async def export_document(
    request: ExportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> ExportResult:
    """
    Export a document with validation and optimization.
    
    Features:
    - Pre-export validation
    - Format-specific optimization
    - Post-export verification
    - Metadata embedding
    """
    with create_span("api_export_document") as span:
        span.set_attribute("document_id", request.document_id)
        span.set_attribute("format", request.format.value)
        
        try:
            # Get document
            doc_data = await document_manager.get_document(request.document_id)
            document = doc_data["document"]
            
            # Create temp output file
            output_path = Path(tempfile.mktemp(suffix=f".{request.format.value}"))
            
            # Export with validation
            result = await exporter.export_with_validation(
                document,
                output_path,
                request.format,
                request.options
            )
            
            if result.success:
                # Upload to S3
                s3_key = f"exports/{request.document_id}/{output_path.name}"
                with open(output_path, "rb") as f:
                    storage_client.upload_file(f, "artefacts", s3_key)
                
                # Create artefact record
                artefact_service = ArtefactService(db)
                artefact_data = ArtefactCreate(
                    name=output_path.name,
                    type="exported_model",
                    s3_key=s3_key,
                    mime_type="application/octet-stream",
                    size=result.file_size,
                    metadata={
                        "format": result.format.value,
                        "export_metadata": result.metadata,
                        "validation": result.validation.model_dump() if result.validation else None
                    }
                )
                
                await artefact_service.create_artefact(
                    artefact_data,
                    current_user.id,
                    None
                )
            
            # Clean up temp file
            output_path.unlink(missing_ok=True)
            
            return result
            
        except Exception as e:
            logger.error(f"Dışa aktarma hatası: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Dışa aktarma başarısız: {str(e)}"
            )


@router.post("/convert", response_model=ConversionResult, summary="Dönüştür")
async def convert_format(
    file: UploadFile = File(..., description="Dönüştürülecek dosya"),
    target_format: str = Form(..., description="Hedef format"),
    quality: str = Form("normal", description="Dönüştürme kalitesi"),
    preserve_topology: bool = Form(True, description="Topolojiyi koru"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> ConversionResult:
    """
    Convert file between formats.
    
    Supports intelligent conversion with:
    - Automatic path detection
    - Topology preservation
    - Reverse engineering (STL to STEP)
    - BIM conversion (IFC <-> FCStd)
    """
    with create_span("api_convert_format") as span:
        span.set_attribute("filename", file.filename)
        span.set_attribute("target_format", target_format)
        
        try:
            # Save uploaded file
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp:
                content = await file.read()
                tmp.write(content)
                input_path = Path(tmp.name)
            
            # Create output path
            output_path = Path(tempfile.mktemp(suffix=f".{target_format}"))
            
            # Create conversion options
            conversion_options = ConversionOptions(
                quality=quality,
                preserve_topology=preserve_topology
            )
            
            # Convert
            result = await converter.convert(
                input_path,
                output_path,
                options=conversion_options,
                job_id=hash(file.filename)
            )
            
            if result.success:
                # Upload to S3
                s3_key = f"conversions/{Path(file.filename).stem}_to_{target_format}.{target_format}"
                with open(output_path, "rb") as f:
                    storage_client.upload_file(f, "artefacts", s3_key)
                
                # Create artefact record
                artefact_service = ArtefactService(db)
                artefact_data = ArtefactCreate(
                    name=output_path.name,
                    type="converted_model",
                    s3_key=s3_key,
                    mime_type="application/octet-stream",
                    size=result.file_size_after,
                    metadata={
                        "source_format": result.source_format,
                        "target_format": result.target_format,
                        "conversion_method": result.conversion_method.value,
                        "quality_metrics": result.quality_metrics
                    }
                )
                
                await artefact_service.create_artefact(
                    artefact_data,
                    current_user.id,
                    None
                )
            
            # Clean up temp files
            input_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)
            
            return result
            
        except Exception as e:
            logger.error(f"Dönüştürme hatası: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Dönüştürme başarısız: {str(e)}"
            )


@router.post("/batch-import", response_model=BatchResult, summary="Toplu İçe Aktarma")
async def batch_import(
    request: BatchImportRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> BatchResult:
    """
    Batch import multiple files.
    
    Features:
    - Parallel processing
    - Progress tracking
    - Error recovery
    - Adaptive resource management
    """
    with create_span("api_batch_import") as span:
        span.set_attribute("file_count", len(request.file_urls))
        
        try:
            # Download files from URLs
            file_paths = []
            for url in request.file_urls:
                # Download from S3 or external URL
                # This is simplified - real implementation would handle various URL types
                file_paths.append(url)
            
            # Start batch import
            result = await batch_processor.batch_import(
                file_paths,
                request.options,
                request.import_options,
                request.job_id_prefix
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Toplu içe aktarma hatası: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Toplu içe aktarma başarısız: {str(e)}"
            )


@router.post("/batch-export", response_model=BatchResult, summary="Toplu Dışa Aktarma")
async def batch_export(
    request: BatchExportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> BatchResult:
    """
    Batch export multiple documents.
    
    Features:
    - Multiple format export
    - Parallel processing
    - Output organization
    """
    with create_span("api_batch_export") as span:
        span.set_attribute("document_count", len(request.document_ids))
        span.set_attribute("format_count", len(request.formats))
        
        try:
            # Get documents
            documents = []
            for doc_id in request.document_ids:
                doc_data = await document_manager.get_document(doc_id)
                documents.append(doc_data["document"])
            
            # Create output directory
            output_dir = Path(tempfile.mkdtemp())
            
            # Start batch export
            result = await batch_processor.batch_export(
                documents,
                output_dir,
                request.formats,
                request.options,
                request.export_options
            )
            
            # Upload results to S3
            if result.success:
                for export_result in result.results:
                    if export_result.success:
                        file_path = Path(export_result.file_path)
                        s3_key = f"batch_exports/{file_path.name}"
                        with open(file_path, "rb") as f:
                            storage_client.upload_file(f, "artefacts", s3_key)
            
            return result
            
        except Exception as e:
            logger.error(f"Toplu dışa aktarma hatası: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Toplu dışa aktarma başarısız: {str(e)}"
            )


@router.post("/batch-convert", response_model=BatchResult, summary="Toplu Dönüştürme")
async def batch_convert(
    request: BatchConversionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> BatchResult:
    """
    Batch convert multiple files.
    
    Features:
    - Multiple conversion paths
    - Intelligent routing
    - Parallel processing
    """
    with create_span("api_batch_convert") as span:
        span.set_attribute("conversion_count", len(request.conversions))
        
        try:
            # Start batch conversion
            result = await batch_processor.batch_convert(
                request.conversions,
                request.options,
                request.conversion_options
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Toplu dönüştürme hatası: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Toplu dönüştürme başarısız: {str(e)}"
            )


@router.get("/formats", response_model=List[FormatInfo], summary="Desteklenen Formatlar")
async def get_supported_formats(
    category: Optional[str] = Query(None, description="Kategori filtresi"),
    operation: Optional[str] = Query(None, description="İşlem tipi (import/export)"),
) -> List[FormatInfo]:
    """
    Get list of supported formats.
    
    Categories:
    - native: FreeCAD native formats
    - cad: CAD exchange formats
    - mesh: Mesh/3D printing formats
    - drawing: 2D drawing formats
    - industry: Industry-specific formats
    - point_cloud: Point cloud formats
    """
    formats = []
    
    # Define format information
    format_data = {
        "fcstd": FormatInfo(
            format="fcstd",
            name="FreeCAD Standard",
            category="native",
            extensions=[".fcstd"],
            mime_types=["application/x-freecad"],
            can_import=True,
            can_export=True,
            description="FreeCAD native format with full parametric data",
            description_tr="FreeCAD yerel formatı, tam parametrik veri"
        ),
        "step": FormatInfo(
            format="step",
            name="STEP",
            category="cad",
            extensions=[".step", ".stp"],
            mime_types=["model/step", "application/step"],
            can_import=True,
            can_export=True,
            description="Standard for Exchange of Product data",
            description_tr="Ürün verisi değişimi standardı"
        ),
        "iges": FormatInfo(
            format="iges",
            name="IGES",
            category="cad",
            extensions=[".iges", ".igs"],
            mime_types=["model/iges"],
            can_import=True,
            can_export=True,
            description="Initial Graphics Exchange Specification",
            description_tr="İlk Grafik Değişim Spesifikasyonu"
        ),
        "stl": FormatInfo(
            format="stl",
            name="STL",
            category="mesh",
            extensions=[".stl"],
            mime_types=["model/stl", "application/sla"],
            can_import=True,
            can_export=True,
            description="Stereolithography format for 3D printing",
            description_tr="3D baskı için stereolitografi formatı"
        ),
        "obj": FormatInfo(
            format="obj",
            name="Wavefront OBJ",
            category="mesh",
            extensions=[".obj"],
            mime_types=["model/obj"],
            can_import=True,
            can_export=True,
            description="Wavefront 3D object format",
            description_tr="Wavefront 3D nesne formatı"
        ),
        "ifc": FormatInfo(
            format="ifc",
            name="IFC",
            category="industry",
            extensions=[".ifc"],
            mime_types=["application/x-step"],
            can_import=True,
            can_export=True,
            description="Industry Foundation Classes for BIM",
            description_tr="BIM için Endüstri Temel Sınıfları"
        ),
        "gltf": FormatInfo(
            format="gltf",
            name="glTF",
            category="industry",
            extensions=[".gltf", ".glb"],
            mime_types=["model/gltf+json", "model/gltf-binary"],
            can_import=True,
            can_export=True,
            description="GL Transmission Format for web 3D",
            description_tr="Web 3D için GL İletim Formatı"
        ),
        "dxf": FormatInfo(
            format="dxf",
            name="DXF",
            category="drawing",
            extensions=[".dxf"],
            mime_types=["image/vnd.dxf"],
            can_import=True,
            can_export=True,
            description="Drawing Exchange Format",
            description_tr="Çizim Değişim Formatı"
        ),
        "xyz": FormatInfo(
            format="xyz",
            name="XYZ Point Cloud",
            category="point_cloud",
            extensions=[".xyz"],
            mime_types=["text/plain"],
            can_import=True,
            can_export=True,
            description="Simple XYZ point cloud format",
            description_tr="Basit XYZ nokta bulutu formatı"
        ),
    }
    
    # Filter by category
    if category:
        format_data = {k: v for k, v in format_data.items() if v.category == category}
    
    # Filter by operation
    if operation == "import":
        format_data = {k: v for k, v in format_data.items() if v.can_import}
    elif operation == "export":
        format_data = {k: v for k, v in format_data.items() if v.can_export}
    
    formats = list(format_data.values())
    
    return formats


@router.get("/conversion-matrix", summary="Dönüşüm Matrisi")
async def get_conversion_matrix() -> Dict[str, List[str]]:
    """
    Get supported conversion paths between formats.
    
    Returns a dictionary mapping source formats to
    list of supported target formats.
    """
    return converter.get_supported_conversions()


@router.get("/batch-progress/{batch_id}", response_model=BatchProgress, summary="Toplu İşlem İlerlemesi")
async def get_batch_progress(
    batch_id: str,
    current_user: User = Depends(get_current_user),
) -> BatchProgress:
    """
    Get progress of a batch operation.
    
    Returns current progress including:
    - Files processed
    - Success/failure counts
    - Estimated time remaining
    """
    progress = batch_processor.get_progress()
    
    if not progress:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="İlerleme bilgisi bulunamadı"
        )
    
    return progress


@router.get("/download/{artefact_id}", summary="İndir")
async def download_converted_file(
    artefact_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> FileResponse:
    """
    Download a converted/exported file.
    
    Returns the file as a download response.
    """
    try:
        # Get artefact
        artefact_service = ArtefactService(db)
        artefact = await artefact_service.get_artefact(artefact_id, current_user)
        
        if not artefact:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dosya bulunamadı"
            )
        
        # Generate presigned URL
        url = storage_client.generate_presigned_url(
            "artefacts",
            artefact.s3_key,
            expiration=3600
        )
        
        # Download file
        import requests
        response = requests.get(url)
        
        # Save to temp file
        temp_file = Path(tempfile.mktemp(suffix=Path(artefact.name).suffix))
        temp_file.write_bytes(response.content)
        
        return FileResponse(
            path=str(temp_file),
            filename=artefact.name,
            media_type=artefact.mime_type
        )
        
    except Exception as e:
        logger.error(f"İndirme hatası: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"İndirme başarısız: {str(e)}"
        )