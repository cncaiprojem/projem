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
from datetime import datetime, UTC
import tempfile
import os
import json
from pathlib import Path

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.telemetry import tracer
from app.core.metrics import (
    validation_operations_total,
    validation_duration_seconds,
    validation_issues_total,
    certificate_operations_total
)
from app.models.user import User
from app.models.validation_models import (
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
from app.services.model_validation import ModelValidationFramework
from app.services.freecad_document_manager import FreeCADDocumentManager
from app.services.freecad_service import FreeCADService
import FreeCAD

router = APIRouter(prefix="/model-validation", tags=["Model Validation"])

# Initialize services
validation_framework = ModelValidationFramework()
doc_manager = FreeCADDocumentManager()
freecad_service = FreeCADService()


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
                validation_id=result.validation_id,
                model_id=result.model_id,
                profile=result.profile,
                timestamp=result.timestamp,
                overall_score=result.overall_score,
                grade=result.grade,
                passed=result.passed,
                sections=result.sections,
                issues=result.issues,
                metrics=result.metrics,
                report_url=report_url,
                correlation_id=result.correlation_id
            )
            
        except Exception as e:
            validation_operations_total.labels(
                operation="validate",
                profile=request.profile,
                status="error"
            ).inc()
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"Doğrulama hatası: {str(e)}")


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
            
            # Get manufacturing validator
            from app.services.manufacturing_validator import ManufacturingValidator
            validator = ManufacturingValidator()
            
            # Execute process-specific validation
            if request.process.startswith("cnc_"):
                result = await validator.validate_for_cnc(
                    doc,
                    request.machine_spec
                )
            elif request.process.startswith("printing_"):
                # Get first shape for 3D printing validation
                shape = None
                for obj in doc.Objects:
                    if hasattr(obj, 'Shape'):
                        shape = obj.Shape
                        break
                if not shape:
                    raise ValueError("Model geometri içermiyor")
                    
                result = await validator.validate_for_3d_printing(
                    shape,
                    request.machine_spec
                )
            elif request.process == "injection_molding":
                result = await validator.validate_for_injection_molding(
                    doc,
                    request.machine_spec
                )
            else:
                raise ValueError(f"Desteklenmeyen üretim yöntemi: {request.process}")
            
            # Estimate cost and lead time
            estimation = await validator.estimate_manufacturing(
                doc,
                request.process,
                request.material,
                request.quantity
            )
            
            validation_operations_total.labels(
                operation="validate_manufacturing",
                profile=request.process,
                status="success"
            ).inc()
            
            return ManufacturingValidationResponse(
                process=request.process,
                feasible=result.feasible,
                issues=result.issues,
                warnings=result.warnings,
                suggestions=result.suggestions,
                estimated_cost=estimation.get("cost"),
                estimated_lead_time=estimation.get("lead_time"),
                material_recommendations=result.material_recommendations,
                process_parameters=result.process_parameters
            )
            
        except Exception as e:
            validation_operations_total.labels(
                operation="validate_manufacturing",
                profile=request.process,
                status="error"
            ).inc()
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"Üretim doğrulama hatası: {str(e)}")


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
            from app.services.standards_checker import StandardsChecker
            checker = StandardsChecker()
            
            results = []
            for standard in request.standards:
                result = await checker.check_compliance(doc, standard)
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
            raise HTTPException(status_code=500, detail=f"Standart uyumluluk hatası: {str(e)}")


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
            from app.services.quality_metrics import QualityMetrics
            metrics_calculator = QualityMetrics()
            
            report = await metrics_calculator.calculate_metrics(doc)
            
            return QualityMetricsResponse(
                document_id=document_id,
                timestamp=datetime.now(UTC),
                overall_score=report.overall_score,
                grade=report.grade,
                metrics=report.metrics,
                complexity=report.complexity_score,
                manufacturing_readiness=report.manufacturing_readiness
            )
            
        except Exception as e:
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"Metrik hesaplama hatası: {str(e)}")


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
            raise HTTPException(status_code=500, detail=f"Sertifika düzenleme hatası: {str(e)}")


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
            raise HTTPException(status_code=500, detail=f"Sertifika doğrulama hatası: {str(e)}")


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
            from app.services.model_validation import AutoFixSuggestions
            fix_generator = AutoFixSuggestions()
            
            suggestions = await fix_generator.suggest_fixes(validation_result)
            
            return suggestions
            
        except Exception as e:
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"Öneri oluşturma hatası: {str(e)}")


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
            from app.services.model_validation import AutoFixSuggestions
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
            raise HTTPException(status_code=500, detail=f"Düzeltme uygulama hatası: {str(e)}")


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
        
        try:
            # Save uploaded file temporarily
            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=Path(file.filename).suffix
            ) as tmp_file:
                content = await file.read()
                tmp_file.write(content)
                tmp_path = tmp_file.name
            
            # Load into FreeCAD
            doc = FreeCAD.newDocument("UploadedModel")
            
            # Import based on file type
            file_ext = Path(file.filename).suffix.lower()
            if file_ext in ['.fcstd', '.FCStd']:
                FreeCAD.openDocument(tmp_path)
            elif file_ext in ['.step', '.stp', '.STEP', '.STP']:
                import Import
                Import.insert(tmp_path, doc.Name)
            elif file_ext in ['.iges', '.igs', '.IGES', '.IGS']:
                import Import
                Import.insert(tmp_path, doc.Name)
            else:
                raise ValueError(f"Desteklenmeyen dosya formatı: {file_ext}")
            
            # Validate
            validation_result = await validation_framework.validate_model(
                doc=doc,
                validation_profile=profile,
                standards=standards
            )
            
            # Clean up
            background_tasks.add_task(os.unlink, tmp_path)
            background_tasks.add_task(FreeCAD.closeDocument, doc.Name)
            
            return ValidationResponse(
                validation_id=validation_result.validation_id,
                model_id=validation_result.model_id,
                profile=validation_result.profile,
                timestamp=validation_result.timestamp,
                overall_score=validation_result.overall_score,
                grade=validation_result.grade,
                passed=validation_result.passed,
                sections=validation_result.sections,
                issues=validation_result.issues,
                metrics=validation_result.metrics
            )
            
        except Exception as e:
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"Yükleme ve doğrulama hatası: {str(e)}")


# Helper functions
async def _store_report(report: str, user_id: int, db: AsyncSession) -> str:
    """Store validation report and return URL."""
    # Implementation would store report in MinIO/S3
    # and return a presigned URL
    return f"/api/v2/reports/validation/{report.validation_id}"


async def _get_validation_result(
    validation_id: str,
    db: AsyncSession
) -> Optional[ValidationResult]:
    """Get validation result from database."""
    # Implementation would retrieve from database
    # For now, return mock
    return None


async def _store_certificate(
    certificate: QualityCertificate,
    db: AsyncSession
):
    """Store certificate in database."""
    # Implementation would store in database
    pass


async def _get_certificate(
    certificate_id: str,
    db: AsyncSession
) -> Optional[QualityCertificate]:
    """Get certificate from database."""
    # Implementation would retrieve from database
    return None


async def _get_fix_suggestions(
    fix_ids: List[str],
    db: AsyncSession
) -> List[FixSuggestion]:
    """Get fix suggestions by IDs."""
    # Implementation would retrieve from database
    return []


async def _revalidate_model(
    doc: FreeCAD.Document,
    user_id: int,
    db: AsyncSession
):
    """Re-validate model after fixes."""
    # Implementation would re-run validation
    pass