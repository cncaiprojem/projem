"""
Upload Normalization Router for Task 7.7

Provides API endpoints for CAD file upload normalization:
- POST /api/v1/normalize/upload - Normalize uploaded CAD file
- GET /api/v1/normalize/status/{job_id} - Get normalization status
- GET /api/v1/normalize/formats - List supported formats
- POST /api/v1/normalize/validate - Validate file format
"""

from pathlib import Path
from typing import Optional, List, Annotated
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.concurrency import run_in_threadpool  # For CPU-bound operations
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from ..core.database import get_db
from ..core.logging import get_logger
from ..core.telemetry import create_span
from ..core import metrics
from ..middleware.correlation_middleware import get_correlation_id
from ..services.upload_normalization_service import (
    upload_normalization_service,
    FileFormat,
    Units,
    NormalizationConfig,
    NormalizationException,
    NormalizationErrorCode,
    GeometryMetrics
)
from ..services.s3_service import s3_service
from ..services.auth_service import get_current_user
from ..models.user import User
from ..models.job import Job, JobStatus
from ..schemas.jobs import JobResponse

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/normalize",
    tags=["normalization"],
    responses={
        403: {"description": "Not authorized"},
        404: {"description": "Not found"},
        422: {"description": "Validation error"},
        500: {"description": "Internal server error"}
    }
)


class NormalizeUploadRequest(BaseModel):
    """Request model for upload normalization."""
    target_units: Units = Field(Units.MILLIMETER, description="Target units for normalization")
    declared_units: Optional[Units] = Field(None, description="User-declared units (overrides auto-detection)")
    normalize_orientation: bool = Field(True, description="Normalize to Z-up orientation")
    center_geometry: bool = Field(False, description="Center geometry at origin")
    repair_mesh: bool = Field(True, description="Attempt to repair mesh issues")
    merge_duplicates: bool = Field(True, description="Merge duplicate entities")
    validate_geometry: bool = Field(True, description="Validate geometry after normalization")
    generate_preview: bool = Field(True, description="Generate GLB preview")
    extrude_2d_thickness: Optional[float] = Field(0.5, description="Thickness for 2D extrusion in mm")
    material_name: Optional[str] = Field(None, description="Material to apply")
    tolerance: float = Field(0.001, description="Geometric tolerance in mm")


class NormalizationOptions(BaseModel):
    """
    Form data model for normalization options.
    Groups all normalization parameters for cleaner function signatures.
    """
    target_units: Units = Field(default=Units.MILLIMETER, description="Target units for normalization")
    declared_units: Optional[Units] = Field(default=None, description="User-declared units (overrides auto-detection)")
    normalize_orientation: bool = Field(default=True, description="Normalize to Z-up orientation")
    center_geometry: bool = Field(default=False, description="Center geometry at origin")
    repair_mesh: bool = Field(default=True, description="Attempt to repair mesh issues")
    merge_duplicates: bool = Field(default=True, description="Merge duplicate entities")
    validate_geometry: bool = Field(default=True, description="Validate geometry after normalization")
    generate_preview: bool = Field(default=True, description="Generate GLB preview")
    extrude_2d_thickness: float = Field(default=0.5, description="Thickness for 2D extrusion in mm")
    material_name: Optional[str] = Field(default=None, description="Material to apply")
    tolerance: float = Field(default=0.001, description="Geometric tolerance in mm")


def parse_normalization_options(
    target_units: Units = Form(Units.MILLIMETER),
    declared_units: Optional[Units] = Form(None),
    normalize_orientation: bool = Form(True),
    center_geometry: bool = Form(False),
    repair_mesh: bool = Form(True),
    merge_duplicates: bool = Form(True),
    validate_geometry: bool = Form(True),
    generate_preview: bool = Form(True),
    extrude_2d_thickness: float = Form(0.5),
    material_name: Optional[str] = Form(None),
    tolerance: float = Form(0.001)
) -> NormalizationOptions:
    """
    Dependency function to parse form data into NormalizationOptions.
    This approach maintains backward compatibility while providing cleaner signatures.
    """
    return NormalizationOptions(
        target_units=target_units,
        declared_units=declared_units,
        normalize_orientation=normalize_orientation,
        center_geometry=center_geometry,
        repair_mesh=repair_mesh,
        merge_duplicates=merge_duplicates,
        validate_geometry=validate_geometry,
        generate_preview=generate_preview,
        extrude_2d_thickness=extrude_2d_thickness,
        material_name=material_name,
        tolerance=tolerance
    )


class NormalizeUploadResponse(BaseModel):
    """Response model for upload normalization."""
    success: bool = Field(..., description="Whether normalization succeeded")
    job_id: str = Field(..., description="Job ID for tracking")
    original_format: FileFormat = Field(..., description="Detected file format")
    original_units: Units = Field(..., description="Detected or declared units")
    normalized_files: dict = Field(..., description="S3 keys for normalized files")
    metrics: GeometryMetrics = Field(..., description="Geometry metrics")
    warnings: List[str] = Field(default_factory=list, description="Validation warnings")
    processing_time_ms: int = Field(..., description="Processing time in milliseconds")
    preview_url: Optional[str] = Field(None, description="Presigned URL for preview")


class SupportedFormatsResponse(BaseModel):
    """Response model for supported formats."""
    formats: List[dict] = Field(..., description="List of supported formats")
    units: List[dict] = Field(..., description="List of supported units")


class ValidateFormatRequest(BaseModel):
    """Request model for format validation."""
    filename: str = Field(..., description="Filename to validate")
    file_size_mb: float = Field(..., description="File size in MB")


class ValidateFormatResponse(BaseModel):
    """Response model for format validation."""
    valid: bool = Field(..., description="Whether format is valid")
    format: Optional[FileFormat] = Field(None, description="Detected format")
    errors: List[str] = Field(default_factory=list, description="Validation errors")
    warnings: List[str] = Field(default_factory=list, description="Validation warnings")


@router.post("/upload", response_model=NormalizeUploadResponse)
async def normalize_upload(
    file: UploadFile = File(..., description="CAD file to normalize"),
    options: NormalizationOptions = Depends(parse_normalization_options),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Normalize an uploaded CAD file.
    
    Supports STEP, IGES, STL, DXF, and IFC formats.
    Performs unit conversion, orientation normalization, mesh repair, and validation.
    """
    correlation_id = get_correlation_id()
    
    with create_span("normalize_upload_endpoint") as span:
        span.set_attribute("user_id", current_user.id)
        span.set_attribute("filename", file.filename)
        span.set_attribute("file_size", file.size if hasattr(file, 'size') else 0)
        
        # Early format detection for better metrics
        # Based on Prometheus best practices: always label metrics accurately
        # Use service method to avoid code duplication (DRY principle)
        file_format_for_metrics = "unknown"
        if file.filename:
            # Create a temporary Path object for format detection
            temp_file_path = Path(file.filename)
            try:
                detected_file_format = upload_normalization_service.detect_format(temp_file_path)
                # Convert FileFormat enum to string for metrics
                file_format_for_metrics = detected_file_format.value
            except NormalizationException:
                # NormalizationException is the documented exception for format detection failure
                # This is the expected exception type from the service layer
                # Keep "unknown" format for metrics when format detection fails
                file_format_for_metrics = "unknown"
        
        # Initialize job variable at the beginning of the try block for proper scoping
        # This follows Python best practices for exception handling and variable lifecycle
        job = None
        
        try:
            # Validate file size - file.size can be None if no Content-Length header
            # Using None check is more robust than hasattr as FastAPI UploadFile always has 'size' attribute
            max_size_mb = 500.0
            if file.size is not None and file.size > max_size_mb * 1024 * 1024:
                raise HTTPException(
                    status_code=413,
                    detail=f"File size exceeds maximum of {max_size_mb} MB"
                )
            
            # Create job record
            job = Job(
                user_id=current_user.id,
                status=JobStatus.PROCESSING,
                type="normalization",
                parameters={
                    "filename": file.filename,
                    "target_units": options.target_units.value,
                    "declared_units": options.declared_units.value if options.declared_units else None
                }
            )
            db.add(job)
            db.commit()
            
            # Upload original file to S3 using streaming upload
            s3_key = f"uploads/{job.id}/{file.filename}"
            
            # Use streaming upload to avoid loading entire file into memory
            try:
                # Get the file's SpooledTemporaryFile for streaming
                file_stream = file.file
                
                # Upload using the streaming method
                object_key, presigned_url = s3_service.upload_file_stream(
                    file_stream=file_stream,
                    bucket="artefacts",
                    job_id=str(job.id),
                    filename=file.filename,
                    content_type=file.content_type
                )
                
                # Update s3_key with the actual key returned
                s3_key = object_key
                
            except Exception as e:
                job.status = JobStatus.FAILED
                job.error = f"Failed to upload file to S3: {str(e)}"
                db.commit()
                raise HTTPException(
                    status_code=500,
                    detail="Failed to upload file to storage"
                )
            
            # Create normalization config from options
            config = NormalizationConfig(
                target_units=options.target_units,
                normalize_orientation=options.normalize_orientation,
                center_geometry=options.center_geometry,
                repair_mesh=options.repair_mesh,
                merge_duplicates=options.merge_duplicates,
                validate_geometry=options.validate_geometry,
                generate_preview=options.generate_preview,
                extrude_2d_thickness=options.extrude_2d_thickness,
                material_name=options.material_name,
                tolerance=options.tolerance
            )
            
            # Execute normalization using threadpool for CPU-bound operation
            # This prevents blocking the event loop during FreeCAD operations
            try:
                result = await run_in_threadpool(
                    upload_normalization_service.normalize_upload,
                    s3_key=s3_key,
                    job_id=str(job.id),
                    config=config,
                    declared_units=options.declared_units
                )
                
                # Update job with results
                job.status = JobStatus.COMPLETED
                job.result = {
                    "normalized_files": {
                        "fcstd": result.normalized_fcstd_key,
                        "step": result.normalized_step_key,
                        "stl": result.normalized_stl_key,
                        "dxf": result.normalized_dxf_key,
                        "glb": result.preview_glb_key
                    },
                    "metrics": result.metrics.model_dump(),
                    "warnings": result.warnings,
                    "file_hash": result.file_hash
                }
                db.commit()
                
                # Get presigned URL for preview if available
                preview_url = None
                if result.preview_glb_key:
                    preview_url = s3_service.get_presigned_url(result.preview_glb_key)
                
                # Track metrics
                metrics.job_normalization_api_requests.labels(
                    format=result.original_format.value,
                    status="success"
                ).inc()
                
                return NormalizeUploadResponse(
                    success=True,
                    job_id=str(job.id),
                    original_format=result.original_format,
                    original_units=result.original_units,
                    normalized_files={
                        "fcstd": result.normalized_fcstd_key,
                        "step": result.normalized_step_key,
                        "stl": result.normalized_stl_key,
                        "dxf": result.normalized_dxf_key,
                        "glb": result.preview_glb_key
                    },
                    metrics=result.metrics,
                    warnings=result.warnings,
                    processing_time_ms=result.processing_time_ms,
                    preview_url=preview_url
                )
                
            except NormalizationException as e:
                # Handle normalization errors
                job.status = JobStatus.FAILED
                job.error = e.message
                db.commit()
                
                # Track failure metrics with detected format
                # Use early-detected format for accurate metrics tracking
                metrics.job_normalization_api_requests.labels(
                    format=file_format_for_metrics,
                    status="failed"
                ).inc()
                
                # Return appropriate HTTP error based on error code
                if e.code == NormalizationErrorCode.UNSUPPORTED_FORMAT:
                    status_code = 415  # Unsupported Media Type
                elif e.code in [
                    NormalizationErrorCode.STEP_TOPOLOGY,
                    NormalizationErrorCode.STL_NOT_MANIFOLD,
                    NormalizationErrorCode.DXF_UNITS_UNKNOWN,
                    NormalizationErrorCode.VALIDATION_FAILED
                ]:
                    status_code = 422  # Unprocessable Entity
                elif e.code == NormalizationErrorCode.IFC_DEP_MISSING:
                    status_code = 501  # Not Implemented
                else:
                    status_code = 500  # Internal Server Error
                
                # Include Turkish message if available
                detail = {
                    "error": e.message,
                    "code": e.code.value,
                    "details": e.details
                }
                if e.turkish_message:
                    detail["turkish_message"] = e.turkish_message
                
                raise HTTPException(
                    status_code=status_code,
                    detail=detail
                )
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Unexpected error during normalization: {e}")
            
            # Update job status if it was created
            # Using explicit None check for cleaner, more readable code
            if job is not None:
                job.status = JobStatus.FAILED
                job.error = str(e)
                db.commit()
            
            # Track error metrics
            metrics.job_normalization_api_requests.labels(
                format="unknown",
                status="error"
            ).inc()
            
            raise HTTPException(
                status_code=500,
                detail=f"Internal server error: {str(e)}"
            )


@router.get("/status/{job_id}", response_model=JobResponse)
async def get_normalization_status(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get the status of a normalization job."""
    job = db.query(Job).filter(
        Job.id == job_id,
        Job.user_id == current_user.id,
        Job.type == "normalization"
    ).first()
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Normalization job not found"
        )
    
    # Get presigned URLs for results if completed
    if job.status == JobStatus.COMPLETED and job.result:
        normalized_files = job.result.get("normalized_files", {})
        presigned_urls = {}
        
        for file_type, s3_key in normalized_files.items():
            if s3_key:
                presigned_urls[file_type] = s3_service.get_presigned_url(s3_key)
        
        # Add presigned URLs to result
        job.result["presigned_urls"] = presigned_urls
    
    return JobResponse.model_validate(job)


@router.get("/formats", response_model=SupportedFormatsResponse)
async def get_supported_formats():
    """Get list of supported file formats and units."""
    formats = [
        {
            "format": FileFormat.STEP.value,
            "extensions": [".step", ".stp"],
            "description": "STEP - Standard for Exchange of Product Data",
            "features": ["unit_detection", "solid_modeling", "assembly_support"]
        },
        {
            "format": FileFormat.IGES.value,
            "extensions": [".iges", ".igs"],
            "description": "IGES - Initial Graphics Exchange Specification",
            "features": ["unit_detection", "surface_modeling", "legacy_support"]
        },
        {
            "format": FileFormat.STL.value,
            "extensions": [".stl"],
            "description": "STL - Stereolithography",
            "features": ["mesh_repair", "3d_printing", "unit_heuristics"]
        },
        {
            "format": FileFormat.DXF.value,
            "extensions": [".dxf"],
            "description": "DXF - Drawing Exchange Format",
            "features": ["2d_drawing", "layer_support", "extrusion_to_3d"]
        },
        {
            "format": FileFormat.IFC.value,
            "extensions": [".ifc"],
            "description": "IFC - Industry Foundation Classes",
            "features": ["bim_support", "metadata_extraction", "building_elements"]
        }
    ]
    
    units = [
        {
            "unit": Units.MILLIMETER.value,
            "symbol": "mm",
            "description": "Millimeters (default)"
        },
        {
            "unit": Units.METER.value,
            "symbol": "m",
            "description": "Meters"
        },
        {
            "unit": Units.INCH.value,
            "symbol": "in",
            "description": "Inches"
        },
        {
            "unit": Units.FOOT.value,
            "symbol": "ft",
            "description": "Feet"
        },
        {
            "unit": Units.CENTIMETER.value,
            "symbol": "cm",
            "description": "Centimeters"
        }
    ]
    
    return SupportedFormatsResponse(
        formats=formats,
        units=units
    )


@router.post("/validate", response_model=ValidateFormatResponse)
async def validate_format(
    request: ValidateFormatRequest,
    current_user: User = Depends(get_current_user)
):
    """Validate a file format before upload."""
    errors = []
    warnings = []
    
    try:
        # Detect format from filename
        file_path = Path(request.filename)
        format_type = upload_normalization_service.detect_format(file_path)
        
        # Check file size
        max_size_mb = 500.0
        if request.file_size_mb > max_size_mb:
            errors.append(f"File size ({request.file_size_mb:.1f} MB) exceeds maximum of {max_size_mb} MB")
        elif request.file_size_mb > 100.0:
            warnings.append(f"Large file size ({request.file_size_mb:.1f} MB) may take longer to process")
        
        # Format-specific warnings
        if format_type == FileFormat.STL:
            warnings.append("STL files don't contain unit information, units will be guessed")
            warnings.append("STL files may require mesh repair for proper normalization")
        elif format_type == FileFormat.DXF:
            warnings.append("DXF files may need 2D to 3D extrusion for full normalization")
        elif format_type == FileFormat.IFC:
            warnings.append("IFC import requires IfcOpenShell library on server")
        
        return ValidateFormatResponse(
            valid=len(errors) == 0,
            format=format_type if len(errors) == 0 else None,
            errors=errors,
            warnings=warnings
        )
        
    except NormalizationException as e:
        return ValidateFormatResponse(
            valid=False,
            format=None,
            errors=[e.message],
            warnings=[]
        )
    except Exception as e:
        return ValidateFormatResponse(
            valid=False,
            format=None,
            errors=[f"Validation error: {str(e)}"],
            warnings=[]
        )