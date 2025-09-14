"""
API endpoints for Model Validation and Quality Assurance (Task 7.24)

Provides REST API for:
- Model validation with different profiles
- Manufacturing feasibility checks
- Standards compliance verification
- Quality certification
"""

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, UTC, timezone
import asyncio
import tempfile
import os
import json
import uuid
import shutil
from pathlib import Path

# Constants for default values
DEFAULT_FEASIBILITY_SCORE = 0.85  # Default feasibility score when calculation is not available
DEFAULT_COMPLEXITY_SCORE = 50.0  # Default complexity score for models
DEFAULT_QUALITY_GRADE = "B"  # Default quality grade when not calculated

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.logging import get_logger
from app.core.telemetry import tracer
from app.core.metrics import (
    validation_operations_total,
    validation_duration_seconds,
    validation_issues_total,
    certificate_operations_total
)
from app.models.user import User
from app.schemas.validation import (
    ValidationRequest,
    ValidationResponse,
    ValidationResult,
    ManufacturingValidationRequest,
    ManufacturingValidationResponse,
    StandardsComplianceRequest,
    ComplianceResult,
    QualityMetricsResponse,
    QualityCertificate,
    CertificateRequest,
    CertificateVerificationRequest,
    FixSuggestion,
    AutoFixRequest,
    FixReport,
    ValidationProfile,
    ManufacturingProcess
)
from app.services.model_validation import ModelValidationFramework, AutoFixSuggestions
from app.services.freecad_document_manager import FreeCADDocumentManager
from app.services.freecad_service import FreeCADService
from app.services.manufacturing_validator import ManufacturingValidator
from app.services.standards_checker import StandardsChecker
from app.services.quality_metrics import QualityMetrics
from app.services.storage_client import storage_client

# Database models
from sqlalchemy import select
from app.models.validation_models import (
    ValidationResultModel,
    CertificateModel,
    FixSuggestionModel
)

# Initialize logger
logger = get_logger(__name__)

# Quantity discount thresholds and rates
QUANTITY_LARGE = 100
QUANTITY_MEDIUM = 50
QUANTITY_SMALL = 10
DISCOUNT_LARGE = 0.85
DISCOUNT_MEDIUM = 0.9
DISCOUNT_SMALL = 0.95

# Import FreeCAD with proper error handling
try:
    import FreeCAD
    import Import
except ImportError:
    FreeCAD = None
    Import = None
    logger.warning("FreeCAD not available - validation features will be limited")

router = APIRouter(prefix="/model-validation", tags=["Model Validation"])

# Initialize services
validation_framework = ModelValidationFramework()
doc_manager = FreeCADDocumentManager()
freecad_service = FreeCADService()


def _normalize_material_spec(material: Any) -> Optional[Dict[str, Any]]:
    """
    Normalize material specification to consistent dict format.
    
    Args:
        material: Material specification (string or dict)
        
    Returns:
        Normalized material spec as dict or None
    """
    if not material:
        return None
    
    if isinstance(material, str):
        # Convert string to dict format for consistency
        return {'type': material}
    elif isinstance(material, dict):
        return material
    else:
        # Log unexpected type and return None
        logger.warning(f"Unexpected material type: {type(material)}")
        return None


@router.post("/validate", response_model=ValidationResponse)
async def validate_model(
    request: ValidationRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Validate a FreeCAD model with specified profile and standards.
    
    Profiles:
    - quick: Basic geometry checks
    - standard: Geometry + manufacturability
    - comprehensive: All checks including standards
    - manufacturing: Focus on manufacturability
    - certification: Full validation for certification
    """
    with tracer.start_as_current_span("validate_model") as span:
        span.set_attribute("user.id", current_user.id)
        span.set_attribute("validation.profile", request.profile)
        span.set_attribute("validation.standards", len(request.standards) if request.standards else 0)
        
        try:
            # Load document
            doc = await doc_manager.load_document(request.document_path)
            if not doc:
                raise HTTPException(status_code=404, detail="Model bulunamadı")
            
            # Execute validation
            result = await validation_framework.validate_model(
                doc=doc,
                validation_profile=request.profile,
                standards=request.standards,
                correlation_id=request.correlation_id
            )
            
            # Store validation result in database
            validation_model = ValidationResultModel(
                validation_id=result.validation_id,
                model_id=result.model_id,
                user_id=current_user.id,
                profile=result.profile.value,
                status=result.status.value,
                overall_score=result.overall_score,
                sections_json=json.dumps({
                    name: section.dict() if hasattr(section, 'dict') else str(section) 
                    for name, section in result.sections.items()
                }),
                issues_json=json.dumps([issue.dict() if hasattr(issue, 'dict') else str(issue) for issue in result.issues]),
                duration_ms=result.duration_ms if hasattr(result, 'duration_ms') else 0
            )
            
            db.add(validation_model)
            await db.commit()
            
            # Update metrics
            validation_operations_total.labels(
                operation="validate",
                profile=request.profile,
                status="success"
            ).inc()
            
            if result.issues:
                for issue in result.issues:
                    validation_issues_total.labels(
                        type=issue.type,
                        severity=issue.severity
                    ).inc()
            
            # Generate report if requested
            report_url = None
            if request.generate_report:
                report = await validation_framework.report_generator.generate_report(
                    result,
                    format=request.report_format
                )
                # Store report and get URL
                report_url = await _store_report(report, current_user.id, db)
            
            # Schedule background cleanup
            if request.auto_cleanup:
                background_tasks.add_task(
                    doc_manager.cleanup_document,
                    doc.Name
                )
            
            return ValidationResponse(
                success=True,
                result=result,
                validation_id=result.validation_id
            )
            
        except ValueError as e:
            validation_operations_total.labels(
                operation="validate",
                profile=request.profile,
                status="error"
            ).inc()
            span.record_exception(e)
            raise HTTPException(status_code=400, detail="Geçersiz istek. Lütfen model formatını kontrol edin.")
        except Exception as e:
            validation_operations_total.labels(
                operation="validate",
                profile=request.profile,
                status="error"
            ).inc()
            span.record_exception(e)
            raise HTTPException(status_code=500, detail="Doğrulama hatası. Model dosyası kontrol edilemedi.")


@router.post("/validate/manufacturing", response_model=ManufacturingValidationResponse)
async def validate_manufacturing(
    request: ManufacturingValidationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Validate model for specific manufacturing process.
    
    Processes:
    - cnc_milling, cnc_turning, cnc_laser, cnc_plasma
    - printing_fdm, printing_sla, printing_sls
    - injection_molding, sheet_metal, casting
    """
    with tracer.start_as_current_span("validate_manufacturing") as span:
        span.set_attribute("manufacturing.process", request.process)
        span.set_attribute("machine.id", request.machine_spec.get("id", "unknown"))
        
        try:
            # Load document
            doc = await doc_manager.load_document(request.document_path)
            if not doc:
                raise HTTPException(status_code=404, detail="Model bulunamadı")
            
            # Extract shape from document first - needed for all processes
            shape = None
            for obj in doc.Objects:
                if hasattr(obj, 'Shape'):
                    shape = obj.Shape
                    break
            if not shape:
                raise HTTPException(status_code=400, detail="Model geometri içermiyor")
            
            # Get manufacturing validator
            validator = ManufacturingValidator()
            
            # Execute process-specific validation
            if request.process.startswith("cnc_"):
                result = await asyncio.to_thread(
                    validator.validate_for_cnc,
                    doc,
                    request.machine_spec
                )
            elif request.process.startswith("printing_"):
                result = await asyncio.to_thread(
                    validator.validate_for_3d_printing,
                    shape,
                    request.machine_spec
                )
            elif request.process == "injection_molding":
                # Use general validate for injection molding for now
                result = await asyncio.to_thread(
                    validator.validate,
                    doc,
                    request.process,  # Add the missing process parameter
                    request.machine_spec
                )
            else:
                raise HTTPException(status_code=400, detail="Desteklenmeyen üretim yöntemi")
            
            # Estimate cost and lead time using real geometry-based calculation
            # Extract material spec with clear priority order:
            # 1. Direct material field on request (highest priority)
            # 2. Material from machine_spec (fallback)
            material_spec = None
            
            # First priority: direct material field on request
            if hasattr(request, 'material') and request.material:
                material_spec = _normalize_material_spec(request.material)
            # Second priority: material from machine_spec (only if no direct material)
            elif request.machine_spec and 'material' in request.machine_spec:
                material_from_spec = request.machine_spec['material']
                material_spec = _normalize_material_spec(material_from_spec)
            
            unit_cost = result.cost_estimate if hasattr(result, 'cost_estimate') else validator._estimate_cost(shape, request.process, material_spec)
            unit_lead_time = result.lead_time_estimate if hasattr(result, 'lead_time_estimate') else validator._estimate_lead_time(shape, request.process)
            
            # Scale cost by quantity with volume discounts
            quantity_discount = 1.0
            if request.quantity > QUANTITY_LARGE:
                quantity_discount = DISCOUNT_LARGE  # 15% discount for 100+
            elif request.quantity > QUANTITY_MEDIUM:
                quantity_discount = DISCOUNT_MEDIUM   # 10% discount for 50+
            elif request.quantity > QUANTITY_SMALL:
                quantity_discount = DISCOUNT_SMALL  # 5% discount for 10+
            
            estimation = {
                "cost": float(unit_cost) * request.quantity * quantity_discount,
                "lead_time": unit_lead_time + (request.quantity // 100)  # Add days for large batches
            }
            
            validation_operations_total.labels(
                operation="validate_manufacturing",
                profile=request.process,
                status="success"
            ).inc()
            
            return ManufacturingValidationResponse(
                process=request.process,
                is_feasible=result.feasible,
                feasibility_score=result.feasibility_score if hasattr(result, 'feasibility_score') else DEFAULT_FEASIBILITY_SCORE,
                issues=result.issues,
                warnings=result.warnings,
                suggestions=result.suggestions,
                cost_estimate=estimation.get("cost"),
                lead_time_days=estimation.get("lead_time"),
                recommendations=result.material_recommendations if hasattr(result, 'material_recommendations') else [],
                machine_compatibility=result.machine_compatibility if hasattr(result, 'machine_compatibility') else {"compatible": True, "notes": []},
                process_parameters=result.process_parameters
            )
            
        except ValueError as e:
            validation_operations_total.labels(
                operation="validate_manufacturing",
                profile=request.process,
                status="error"
            ).inc()
            span.record_exception(e)
            raise HTTPException(status_code=400, detail="Geçersiz istek. Lütfen parametreleri kontrol edin.")
        except Exception as e:
            validation_operations_total.labels(
                operation="validate_manufacturing",
                profile=request.process,
                status="error"
            ).inc()
            span.record_exception(e)
            raise HTTPException(status_code=500, detail="Üretim doğrulama hatası. Parametre ayarlarını kontrol edin.")


@router.post("/validate/standards", response_model=List[ComplianceResult])
async def check_standards_compliance(
    request: StandardsComplianceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Check model compliance with industry standards.
    
    Supported standards:
    - ISO 10303 (STEP)
    - ASME Y14.5 (GD&T)
    - ISO 2768 (General tolerances)
    - CE (European conformity)
    """
    with tracer.start_as_current_span("check_standards_compliance") as span:
        span.set_attribute("standards.count", len(request.standards))
        
        try:
            # Load document
            doc = await doc_manager.load_document(request.document_path)
            if not doc:
                raise HTTPException(status_code=404, detail="Model bulunamadı")
            
            # Check each standard
            checker = StandardsChecker()
            
            results = []
            for standard in request.standards:
                result = await asyncio.to_thread(
                    checker.check_compliance,
                    doc,
                    standard
                )
                results.append(result)
                
                # Update metrics
                validation_operations_total.labels(
                    operation="check_standards",
                    profile=standard,
                    status="compliant" if result.compliant else "non_compliant"
                ).inc()
            
            return results
            
        except Exception as e:
            span.record_exception(e)
            raise HTTPException(status_code=500, detail="Standart uyumluluk hatası. Doğrulama tamamlanamadı.")


@router.get("/metrics/{document_id}", response_model=QualityMetricsResponse)
async def get_quality_metrics(
    document_id: str,
    recalculate: bool = Query(False, description="Force recalculation"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get quality metrics for a model."""
    with tracer.start_as_current_span("get_quality_metrics") as span:
        span.set_attribute("document.id", document_id)
        span.set_attribute("recalculate", recalculate)
        
        try:
            # Load document
            doc = await doc_manager.get_document(document_id)
            if not doc:
                raise HTTPException(status_code=404, detail="Model bulunamadı")
            
            # Calculate metrics
            metrics_calculator = QualityMetrics()
            
            report = await asyncio.to_thread(
                metrics_calculator.calculate_metrics,
                doc
            )
            
            return QualityMetricsResponse(
                document_id=document_id,
                timestamp=datetime.now(timezone.utc),
                quality_score=report.overall_score,
                grade=report.grade if hasattr(report, 'grade') else DEFAULT_QUALITY_GRADE,
                metrics=report.metrics,
                complexity=report.complexity_score if hasattr(report, 'complexity_score') else DEFAULT_COMPLEXITY_SCORE,
                manufacturing_readiness=report.manufacturing_readiness,
                issues_by_category=report.issues_by_category if hasattr(report, 'issues_by_category') else {},
                improvement_areas=report.improvement_areas if hasattr(report, 'improvement_areas') else []
            )
            
        except Exception as e:
            span.record_exception(e)
            raise HTTPException(status_code=500, detail="Metrik hesaplama hatası. Analiz tamamlanamadı.")


@router.post("/certificate/issue", response_model=QualityCertificate)
async def issue_certificate(
    request: CertificateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Issue quality certificate for validated model."""
    with tracer.start_as_current_span("issue_certificate") as span:
        span.set_attribute("validation.id", request.validation_id)
        
        try:
            # Get validation result
            validation_result = await _get_validation_result(
                request.validation_id,
                db
            )
            
            if not validation_result:
                raise HTTPException(
                    status_code=404,
                    detail="Doğrulama sonucu bulunamadı"
                )
            
            if validation_result.overall_score < 0.8:
                raise HTTPException(
                    status_code=400,
                    detail="Model sertifika için yeterli puanı alamadı"
                )
            
            # Issue certificate
            certificate = await validation_framework.certification_system.issue_certificate(
                validation_result=validation_result,
                standards=request.standards,
                issuer=f"{current_user.name} ({current_user.company})"
            )
            
            # Store certificate in database
            await _store_certificate(certificate, db)
            
            certificate_operations_total.labels(
                operation="issue",
                status="success"
            ).inc()
            
            return certificate
            
        except HTTPException:
            raise
        except Exception as e:
            certificate_operations_total.labels(
                operation="issue",
                status="error"
            ).inc()
            span.record_exception(e)
            raise HTTPException(status_code=500, detail="Sertifika düzenleme hatası. Gereksinimler sağlanmadı.")


@router.post("/certificate/verify")
async def verify_certificate(
    request: CertificateVerificationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Verify certificate authenticity."""
    with tracer.start_as_current_span("verify_certificate") as span:
        span.set_attribute("certificate.id", request.certificate_id)
        
        try:
            # Get certificate from database
            certificate = await _get_certificate(request.certificate_id, db)
            
            if not certificate:
                raise HTTPException(
                    status_code=404,
                    detail="Sertifika bulunamadı"
                )
            
            # Verify certificate
            is_valid = await validation_framework.certification_system.verify_certificate(
                certificate
            )
            
            certificate_operations_total.labels(
                operation="verify",
                status="valid" if is_valid else "invalid"
            ).inc()
            
            return {
                "certificate_id": request.certificate_id,
                "valid": is_valid,
                "issuer": certificate.issuer,
                "issued_date": certificate.issued_date,
                "expiry_date": certificate.expiry_date,
                "standards": certificate.standards
            }
            
        except HTTPException:
            raise
        except Exception as e:
            span.record_exception(e)
            raise HTTPException(status_code=500, detail="Sertifika doğrulama hatası. Sertifika geçersiz.")


@router.post("/fix/suggest", response_model=List[FixSuggestion])
async def suggest_fixes(
    validation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Generate fix suggestions for validation issues."""
    with tracer.start_as_current_span("suggest_fixes") as span:
        span.set_attribute("validation.id", validation_id)
        
        try:
            # Get validation result
            validation_result = await _get_validation_result(validation_id, db)
            
            if not validation_result:
                raise HTTPException(
                    status_code=404,
                    detail="Doğrulama sonucu bulunamadı"
                )
            
            # Generate suggestions
            fix_generator = AutoFixSuggestions()
            
            suggestions = fix_generator.suggest_fixes(validation_result)
            
            return suggestions
            
        except Exception as e:
            span.record_exception(e)
            raise HTTPException(status_code=500, detail="Öneri oluşturma hatası. Analiz tamamlanamadı.")


@router.post("/fix/apply", response_model=FixReport)
async def apply_fixes(
    request: AutoFixRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Apply automated fixes to model."""
    with tracer.start_as_current_span("apply_fixes") as span:
        span.set_attribute("document.path", request.document_path)
        span.set_attribute("fixes.count", len(request.fix_ids))
        span.set_attribute("auto_approve", request.auto_approve)
        
        try:
            # Load document
            doc = await doc_manager.load_document(request.document_path)
            if not doc:
                raise HTTPException(status_code=404, detail="Model bulunamadı")
            
            # Get selected suggestions
            suggestions = await _get_fix_suggestions(request.fix_ids, db)
            
            # Apply fixes
            fix_generator = AutoFixSuggestions()
            
            report = await fix_generator.apply_automated_fixes(
                doc=doc,
                suggestions=suggestions,
                auto_approve=request.auto_approve
            )
            
            # Save updated document if requested
            if request.save_result:
                output_path = request.output_path or request.document_path
                await doc_manager.save_document(doc, output_path)
                report.saved_to = output_path
            
            # Schedule re-validation if requested
            if request.revalidate:
                background_tasks.add_task(
                    _revalidate_model,
                    doc,
                    current_user.id,
                    db
                )
            
            return report
            
        except Exception as e:
            span.record_exception(e)
            raise HTTPException(status_code=500, detail="Düzeltme uygulama hatası. İşlem gerçekleştirilemedi.")


@router.post("/upload-and-validate")
async def upload_and_validate(
    file: UploadFile = File(...),
    profile: ValidationProfile = Query(ValidationProfile.STANDARD),
    standards: Optional[List[str]] = Query(None),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Upload a model file and validate it."""
    with tracer.start_as_current_span("upload_and_validate") as span:
        span.set_attribute("file.name", file.filename)
        span.set_attribute("file.size", file.size if hasattr(file, 'size') else 0)
        span.set_attribute("validation.profile", profile)
        
        tmp_path = None
        doc = None
        try:
            # Save uploaded file temporarily using streaming to avoid memory issues
            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=Path(file.filename).suffix
            ) as tmp_file:
                # Use streaming copy instead of loading entire file into memory
                await asyncio.to_thread(shutil.copyfileobj, file.file, tmp_file)
                tmp_path = tmp_file.name
            
            # Load into FreeCAD
            doc = None
            
            # Import based on file type
            file_ext = Path(file.filename).suffix.lower()
            if file_ext in ['.fcstd', '.FCStd']:
                # For FCStd files, open the document directly and assign it
                doc = FreeCAD.openDocument(tmp_path)
            elif file_ext in ['.step', '.stp', '.STEP', '.STP', '.iges', '.igs', '.IGES', '.IGS']:
                # For STEP/IGES files, create new document and import
                doc = FreeCAD.newDocument("UploadedModel")
                Import.insert(tmp_path, doc.Name)
            else:
                raise HTTPException(status_code=400, detail="Desteklenmeyen dosya formatı")
            
            # Validate
            validation_result = await validation_framework.validate_model(
                doc=doc,
                validation_profile=profile,
                standards=standards
            )
            
            # Schedule cleanup for later
            if tmp_path:
                background_tasks.add_task(os.unlink, tmp_path)
            if doc:
                background_tasks.add_task(FreeCAD.closeDocument, doc.Name)
            
            return ValidationResponse(
                success=True,
                result=validation_result,
                validation_id=validation_result.validation_id
            )
            
        except HTTPException:
            # Re-raise HTTPException as-is
            _cleanup_resources(tmp_path, doc)
            raise
        except Exception as e:
            span.record_exception(e)
            _cleanup_resources(tmp_path, doc)
            raise HTTPException(status_code=500, detail="Yükleme ve doğrulama hatası. Dosya işlenemedi.")


# Helper functions
def _cleanup_resources(tmp_path: Optional[str], doc: Optional[Any]) -> None:
    """Clean up temporary file and FreeCAD document resources."""
    if tmp_path and os.path.exists(tmp_path):
        try:
            os.unlink(tmp_path)
        except Exception:
            logger.debug("Best effort cleanup failed for temporary file")
    
    if doc:
        try:
            # Use the module-level FreeCAD import
            FreeCAD.closeDocument(doc.Name)
        except Exception:
            logger.debug("Best effort document cleanup failed")


async def _store_report(report: str, user_id: int, db: AsyncSession) -> str:
    """Store validation report and return URL."""
    try:
        
        # Generate unique report ID
        report_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat()
        
        # Create report metadata
        report_data = {
            "report_id": report_id,
            "user_id": user_id,
            "timestamp": timestamp,
            "content": report
        }
        
        # Store report in MinIO
        bucket = "validation-reports"
        object_name = f"reports/{user_id}/{report_id}.json"
        
        # Ensure bucket exists
        await storage_client.ensure_bucket_exists(bucket)
        
        # Upload report
        await storage_client.upload_json(
            bucket=bucket,
            object_name=object_name,
            data=report_data
        )
        
        # Generate presigned URL (24 hour expiry)
        presigned_url = await storage_client.get_presigned_url(
            bucket=bucket,
            object_name=object_name,
            expiry=86400
        )
        
        return presigned_url
        
    except Exception as e:
        logger.error(f"Failed to store report: {e}")
        # Return fallback URL
        return f"/api/v2/reports/validation/error"


async def _get_validation_result(
    validation_id: str,
    db: AsyncSession
) -> Optional[ValidationResult]:
    """Get validation result from database."""
    try:
        stmt = select(ValidationResultModel).where(
            ValidationResultModel.validation_id == validation_id
        )
        result = await db.execute(stmt)
        validation_model = result.scalar_one_or_none()
        
        if validation_model:
            # Convert database model to response model
            return ValidationResult(
                validation_id=validation_model.validation_id,
                model_id=validation_model.model_id,
                profile=validation_model.profile,
                status=validation_model.status,
                overall_score=validation_model.overall_score,
                sections=json.loads(validation_model.sections_json) if validation_model.sections_json else {},
                issues=json.loads(validation_model.issues_json) if validation_model.issues_json else [],
                timestamp=validation_model.created_at,
                duration_ms=validation_model.duration_ms
            )
        
        return None
        
    except Exception as e:
        logger.error(f"Failed to get validation result: {e}")
        return None


async def _store_certificate(
    certificate: QualityCertificate,
    db: AsyncSession
):
    """Store certificate in database."""
    try:
        cert_model = CertificateModel(
            certificate_id=certificate.certificate_id,
            validation_id=certificate.validation_id,
            model_id=certificate.model_id,
            issued_date=certificate.issued_date,
            expiry_date=certificate.expiry_date,
            standards_met=json.dumps(certificate.standards_met),
            signature=certificate.signature,
            metadata_json=json.dumps(certificate.metadata) if certificate.metadata else None
        )
        
        db.add(cert_model)
        await db.commit()
        
    except Exception as e:
        logger.error(f"Failed to store certificate: {e}")
        await db.rollback()
        raise


async def _get_certificate(
    certificate_id: str,
    db: AsyncSession
) -> Optional[QualityCertificate]:
    """Get certificate from database."""
    try:
        stmt = select(CertificateModel).where(
            CertificateModel.certificate_id == certificate_id
        )
        result = await db.execute(stmt)
        cert_model = result.scalar_one_or_none()
        
        if cert_model:
            return QualityCertificate(
                certificate_id=cert_model.certificate_id,
                validation_id=cert_model.validation_id,
                model_id=cert_model.model_id,
                issued_date=cert_model.issued_date,
                expiry_date=cert_model.expiry_date,
                standards_met=json.loads(cert_model.standards_met) if cert_model.standards_met else [],
                signature=cert_model.signature,
                metadata=json.loads(cert_model.metadata_json) if cert_model.metadata_json else {}
            )
        
        return None
        
    except Exception as e:
        logger.error(f"Failed to get certificate: {e}")
        return None


async def _get_fix_suggestions(
    fix_ids: List[str],
    db: AsyncSession
) -> List[FixSuggestion]:
    """Get fix suggestions by IDs."""
    try:
        stmt = select(FixSuggestionModel).where(
            FixSuggestionModel.suggestion_id.in_(fix_ids)
        )
        result = await db.execute(stmt)
        suggestion_models = result.scalars().all()
        
        suggestions = []
        for model in suggestion_models:
            suggestions.append(FixSuggestion(
                suggestion_id=model.suggestion_id,
                issue_id=model.issue_id,
                type=model.type,
                description=model.description,
                turkish_description=model.turkish_description,
                confidence=model.confidence,
                automated=model.automated,
                parameters=json.loads(model.parameters_json) if model.parameters_json else {}
            ))
        
        return suggestions
        
    except Exception as e:
        logger.error(f"Failed to get fix suggestions: {e}")
        return []


async def _revalidate_model(
    doc: Any,  # FreeCAD.Document
    user_id: int,
    db: AsyncSession,
    original_profile: Optional[ValidationProfile] = None,
    original_standards: Optional[List[str]] = None
) -> ValidationResult:
    """Re-validate model after fixes using original validation parameters.
    
    Args:
        doc: FreeCAD document to validate
        user_id: User ID for tracking
        db: Database session
        original_profile: Original validation profile used (default: COMPREHENSIVE)
        original_standards: Original standards checked (default: None)
    """
    try:
        # Use original validation parameters or defaults
        profile = original_profile or ValidationProfile.COMPREHENSIVE
        standards = original_standards
        
        # Create validation framework
        framework = ModelValidationFramework()
        
        # Run validation with same parameters as original
        result = await framework.validate_model(
            doc=doc,
            validation_profile=profile,
            standards=standards,
            correlation_id=str(user_id)
        )
        
        # Store result in database
        validation_model = ValidationResultModel(
            validation_id=result.validation_id,
            model_id=result.model_id,
            user_id=user_id,
            profile=result.profile.value,
            status=result.status.value,
            overall_score=result.overall_score,
            sections_json=json.dumps({
                name: section.dict() if hasattr(section, 'dict') else str(section)
                for name, section in result.sections.items()
            }),
            issues_json=json.dumps([issue.dict() if hasattr(issue, 'dict') else str(issue) for issue in result.issues]),
            duration_ms=result.duration_ms
        )
        
        db.add(validation_model)
        await db.commit()
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to revalidate model: {e}")
        await db.rollback()
        raise