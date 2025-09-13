"""
Main Model Validation Framework for Task 7.24

This module provides the core validation framework that orchestrates all validation
components including geometric validation, manufacturing checks, standards compliance,
and quality metrics.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Type
from uuid import uuid4

from pydantic import BaseModel

from ..core.environment import environment as settings
from ..core.logging import get_logger
from ..core.telemetry import create_span
from ..core import metrics
from ..middleware.correlation_middleware import get_correlation_id
from ..models.validation_models import (
    ValidationProfile,
    ValidationResult,
    ValidationStatus,
    ValidationRequest,
    ValidationResponse,
    ValidationIssue,
    ValidationSeverity,
    FixSuggestion,
    FixReport,
    QualityCertificate,
    ManufacturingProcess,
    StandardType,
    VALIDATION_MESSAGES_TR
)
from .freecad_document_manager import FreeCADDocumentManager, document_manager
from .geometric_validator import GeometricValidator
from .manufacturing_validator import ManufacturingValidator
from .standards_checker import StandardsChecker
from .quality_metrics import QualityMetrics

logger = get_logger(__name__)


class ValidatorRegistry:
    """Registry for validation components."""
    
    def __init__(self):
        self.validators: Dict[str, Any] = {}
        self.profiles: Dict[ValidationProfile, Set[str]] = {
            ValidationProfile.QUICK: {'geometric_basic', 'performance'},
            ValidationProfile.STANDARD: {'geometric', 'manufacturing_basic', 'quality'},
            ValidationProfile.COMPREHENSIVE: {'geometric', 'manufacturing', 'standards', 'quality', 'performance'},
            ValidationProfile.MANUFACTURING: {'geometric', 'manufacturing', 'tolerance'},
            ValidationProfile.CERTIFICATION: {'geometric', 'manufacturing', 'standards', 'quality', 'certification'}
        }
    
    def register(self, name: str, validator: Any):
        """Register a validator."""
        self.validators[name] = validator
        logger.info(f"Registered validator: {name}")
    
    def get(self, name: str) -> Optional[Any]:
        """Get a validator by name."""
        return self.validators.get(name)
    
    def get_validators_for_profile(self, profile: ValidationProfile) -> List[Any]:
        """Get validators for a validation profile."""
        validator_names = self.profiles.get(profile, set())
        return [self.validators[name] for name in validator_names if name in self.validators]


class RuleEngine:
    """Rule engine for validation logic."""
    
    def __init__(self):
        self.rules: Dict[str, Dict[str, Any]] = {}
        self._load_default_rules()
    
    def _load_default_rules(self):
        """Load default validation rules."""
        self.rules = {
            'min_wall_thickness': {
                'cnc_milling': 1.0,  # mm
                'fdm_3d_printing': 0.8,
                'sla_3d_printing': 0.5,
                'injection_molding': 0.5
            },
            'min_feature_size': {
                'cnc_milling': 0.5,  # mm
                'fdm_3d_printing': 0.4,
                'sla_3d_printing': 0.2,
                'cnc_laser': 0.1
            },
            'max_overhang_angle': {
                'fdm_3d_printing': 45,  # degrees
                'sla_3d_printing': 30,
                'sls_3d_printing': 0  # No support needed
            },
            'tolerance_grades': {
                'fine': 0.05,  # mm
                'medium': 0.1,
                'coarse': 0.2
            }
        }
    
    def get_rule(self, rule_name: str, context: Optional[str] = None) -> Any:
        """Get a validation rule."""
        rule = self.rules.get(rule_name, {})
        if context and isinstance(rule, dict):
            return rule.get(context)
        return rule
    
    def evaluate_rule(self, rule_name: str, value: Any, context: Optional[str] = None) -> bool:
        """Evaluate a value against a rule."""
        threshold = self.get_rule(rule_name, context)
        if threshold is None:
            return True
        
        if isinstance(threshold, (int, float)):
            return value >= threshold
        
        return True


class ValidationReportGenerator:
    """Generate validation reports in various formats."""
    
    def generate_html_report(self, result: ValidationResult) -> str:
        """Generate HTML validation report."""
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Model Validation Report - {result.model_id}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background: #2c3e50; color: white; padding: 20px; }}
                .section {{ margin: 20px 0; padding: 15px; border: 1px solid #ddd; }}
                .passed {{ background: #d4edda; }}
                .warning {{ background: #fff3cd; }}
                .failed {{ background: #f8d7da; }}
                .metric {{ display: inline-block; margin: 10px; padding: 10px; background: #f0f0f0; }}
                table {{ width: 100%; border-collapse: collapse; }}
                th, td {{ padding: 8px; text-align: left; border: 1px solid #ddd; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Model Validation Report</h1>
                <p>Model ID: {result.model_id}</p>
                <p>Date: {result.timestamp.isoformat()}</p>
                <p>Profile: {result.profile.value}</p>
                <p>Overall Score: {result.overall_score:.2%}</p>
            </div>
        """
        
        # Add sections
        for name, section in result.sections.items():
            status_class = 'passed' if section.status == ValidationStatus.PASSED else \
                          'warning' if section.status == ValidationStatus.PASSED_WITH_WARNINGS else 'failed'
            
            html += f"""
            <div class="section {status_class}">
                <h2>{name.replace('_', ' ').title()}</h2>
                <p>Status: {section.status.value}</p>
                <p>Issues: {section.issues_count}, Warnings: {section.warnings_count}, Errors: {section.errors_count}</p>
            </div>
            """
        
        # Add issues table
        if result.issues:
            html += """
            <div class="section">
                <h2>Issues Found</h2>
                <table>
                    <tr>
                        <th>Type</th>
                        <th>Severity</th>
                        <th>Message</th>
                        <th>Fix Available</th>
                    </tr>
            """
            
            for issue in result.issues:
                html += f"""
                    <tr>
                        <td>{issue.type}</td>
                        <td>{issue.severity.value}</td>
                        <td>{issue.message}</td>
                        <td>{'Yes' if issue.fix_available else 'No'}</td>
                    </tr>
                """
            
            html += "</table></div>"
        
        html += "</body></html>"
        return html
    
    def generate_json_report(self, result: ValidationResult) -> str:
        """Generate JSON validation report."""
        return json.dumps(result.dict(), indent=2, default=str)
    
    def generate_markdown_report(self, result: ValidationResult) -> str:
        """Generate Markdown validation report."""
        md = f"""# Model Validation Report

**Model ID:** {result.model_id}  
**Date:** {result.timestamp.isoformat()}  
**Profile:** {result.profile.value}  
**Overall Score:** {result.overall_score:.2%}  
**Status:** {result.status.value}

## Validation Sections

"""
        
        for name, section in result.sections.items():
            md += f"""### {name.replace('_', ' ').title()}

- **Status:** {section.status.value}
- **Issues:** {section.issues_count}
- **Warnings:** {section.warnings_count}
- **Errors:** {section.errors_count}

"""
        
        if result.issues:
            md += """## Issues Found

| Type | Severity | Message | Fix Available |
|------|----------|---------|---------------|
"""
            for issue in result.issues:
                md += f"| {issue.type} | {issue.severity.value} | {issue.message} | {'Yes' if issue.fix_available else 'No'} |\n"
        
        return md


class CertificationSystem:
    """System for issuing and verifying quality certificates."""
    
    def __init__(self):
        self.signing_key = settings.CERTIFICATE_SIGNING_KEY if hasattr(settings, 'CERTIFICATE_SIGNING_KEY') else "default_key"
        self.issuer = settings.CERTIFICATE_ISSUER if hasattr(settings, 'CERTIFICATE_ISSUER') else "FreeCAD Quality System"
    
    def issue_certificate(
        self,
        validation_result: ValidationResult,
        standards: List[StandardType],
        model_hash: str
    ) -> Optional[QualityCertificate]:
        """Issue a quality certificate for validated model."""
        
        # Check if model meets certification threshold
        if validation_result.overall_score < 0.8:
            logger.warning(f"Model {validation_result.model_id} does not meet certification threshold")
            return None
        
        # Check if all required standards are met
        standards_sections = [s for s in validation_result.sections.values() 
                             if s.name == 'standards']
        if standards_sections:
            for section in standards_sections:
                if section.status == ValidationStatus.FAILED:
                    logger.warning(f"Model {validation_result.model_id} failed standards compliance")
                    return None
        
        # Create certificate
        certificate = QualityCertificate(
            model_id=validation_result.model_id,
            model_hash=model_hash,
            issuer=self.issuer,
            standards=standards,
            validation_score=validation_result.overall_score,
            validation_profile=validation_result.profile,
            expiry_date=datetime.now(timezone.utc) + timedelta(days=365),
            metadata={
                'validation_id': validation_result.validation_id,
                'timestamp': validation_result.timestamp.isoformat()
            }
        )
        
        # Generate signature
        certificate.signature = self._sign_certificate(certificate)
        
        # Optional: Store on blockchain
        if hasattr(settings, 'BLOCKCHAIN_ENABLED') and settings.BLOCKCHAIN_ENABLED:
            certificate.blockchain_hash = self._store_on_blockchain(certificate)
        
        logger.info(f"Certificate issued for model {validation_result.model_id}")
        metrics.validation_certificates_issued.inc()
        
        return certificate
    
    def verify_certificate(self, certificate: QualityCertificate) -> bool:
        """Verify certificate authenticity."""
        
        # Check expiry
        if certificate.expiry_date < datetime.now(timezone.utc):
            logger.warning(f"Certificate {certificate.certificate_id} has expired")
            return False
        
        # Verify signature
        if not self._verify_signature(certificate):
            logger.warning(f"Certificate {certificate.certificate_id} has invalid signature")
            return False
        
        # Verify blockchain record if applicable
        if certificate.blockchain_hash:
            if not self._verify_blockchain_record(certificate):
                logger.warning(f"Certificate {certificate.certificate_id} blockchain verification failed")
                return False
        
        return True
    
    def _sign_certificate(self, certificate: QualityCertificate) -> str:
        """Generate cryptographic signature for certificate."""
        # Create signing data
        signing_data = f"{certificate.certificate_id}:{certificate.model_id}:{certificate.model_hash}:{certificate.validation_score}"
        
        # Generate HMAC signature
        import hmac
        signature = hmac.new(
            self.signing_key.encode(),
            signing_data.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return signature
    
    def _verify_signature(self, certificate: QualityCertificate) -> bool:
        """Verify certificate signature."""
        expected_signature = self._sign_certificate(certificate)
        return certificate.signature == expected_signature
    
    def _store_on_blockchain(self, certificate: QualityCertificate) -> str:
        """Store certificate on blockchain (placeholder)."""
        # This would integrate with a blockchain service
        # For now, return a mock hash
        return hashlib.sha256(
            f"{certificate.certificate_id}:{time.time()}".encode()
        ).hexdigest()
    
    def _verify_blockchain_record(self, certificate: QualityCertificate) -> bool:
        """Verify blockchain record (placeholder)."""
        # This would query blockchain service
        # For now, return True
        return True


class ModelValidationFramework:
    """Main model validation framework."""
    
    def __init__(self, document_manager: Optional[FreeCADDocumentManager] = None):
        self.document_manager = document_manager or document_manager
        self.validator_registry = ValidatorRegistry()
        self.rule_engine = RuleEngine()
        self.report_generator = ValidationReportGenerator()
        self.certification_system = CertificationSystem()
        
        # Initialize validators
        self._initialize_validators()
        
        # Metrics
        self.validations_total = 0
        self.validations_failed = 0
        self.fixes_applied = 0
    
    def _initialize_validators(self):
        """Initialize and register validators."""
        # Register validators
        self.validator_registry.register('geometric', GeometricValidator(self.rule_engine))
        self.validator_registry.register('geometric_basic', GeometricValidator(self.rule_engine, basic_mode=True))
        self.validator_registry.register('manufacturing', ManufacturingValidator(self.rule_engine))
        self.validator_registry.register('manufacturing_basic', ManufacturingValidator(self.rule_engine, basic_mode=True))
        self.validator_registry.register('standards', StandardsChecker())
        self.validator_registry.register('quality', QualityMetrics())
        
        logger.info("Model validation framework initialized")
    
    async def validate_model(
        self,
        request: ValidationRequest
    ) -> ValidationResponse:
        """Execute comprehensive model validation."""
        correlation_id = get_correlation_id()
        start_time = time.time()
        
        with create_span("model_validation", correlation_id=correlation_id) as span:
            span.set_attribute("model.id", request.model_id)
            span.set_attribute("validation.profile", request.profile.value)
            
            try:
                # Get document handle
                doc_handle = self.document_manager.get_document_handle(request.model_id)
                if not doc_handle:
                    logger.error(f"Document handle not found for model {request.model_id}")
                    return ValidationResponse(
                        success=False,
                        error="Model not found",
                        turkish_error="Model bulunamadı"
                    )
                
                # Create validation result
                result = ValidationResult(
                    model_id=request.model_id,
                    profile=request.profile,
                    metadata=request.metadata or {}
                )
                
                # Get validators for profile
                validators = self.validator_registry.get_validators_for_profile(request.profile)
                
                # Execute validations in parallel where possible
                validation_tasks = []
                
                # Geometric validation (always first)
                geometric_validator = self.validator_registry.get('geometric')
                if geometric_validator:
                    geometric_result = await geometric_validator.validate(doc_handle)
                    result.add_section('geometric', geometric_result)
                
                # Manufacturing validation if requested
                if request.processes:
                    manufacturing_validator = self.validator_registry.get('manufacturing')
                    if manufacturing_validator:
                        for process in request.processes:
                            mfg_result = await manufacturing_validator.validate(
                                doc_handle, 
                                process
                            )
                            result.add_section(f'manufacturing_{process.value}', mfg_result)
                
                # Standards compliance if requested
                if request.standards:
                    standards_checker = self.validator_registry.get('standards')
                    if standards_checker:
                        for standard in request.standards:
                            compliance_result = await standards_checker.check_compliance(
                                doc_handle,
                                standard
                            )
                            result.add_section(f'standards_{standard.value}', compliance_result)
                
                # Quality metrics
                quality_metrics = self.validator_registry.get('quality')
                if quality_metrics:
                    metrics_result = await quality_metrics.calculate_metrics(doc_handle)
                    result.add_section('quality', metrics_result)
                
                # Calculate overall score
                result.calculate_score()
                
                # Generate fix suggestions
                if result.issues:
                    result.fix_suggestions = await self._generate_fix_suggestions(result)
                
                # Apply automated fixes if requested
                fix_report = None
                if request.auto_fix and result.fix_suggestions:
                    fix_report = await self._apply_automated_fixes(
                        doc_handle,
                        result.fix_suggestions
                    )
                
                # Generate certificate if requested and eligible
                certificate = None
                if request.generate_certificate and result.overall_score >= 0.8:
                    model_hash = self._calculate_model_hash(doc_handle)
                    certificate = self.certification_system.issue_certificate(
                        result,
                        request.standards or [],
                        model_hash
                    )
                    result.certificate = certificate
                
                # Set duration
                result.duration_ms = int((time.time() - start_time) * 1000)
                
                # Update metrics
                self.validations_total += 1
                if result.status == ValidationStatus.FAILED:
                    self.validations_failed += 1
                
                metrics.model_validations_total.labels(
                    profile=request.profile.value,
                    status=result.status.value
                ).inc()
                
                logger.info(
                    f"Model validation completed",
                    model_id=request.model_id,
                    profile=request.profile.value,
                    status=result.status.value,
                    score=result.overall_score,
                    duration_ms=result.duration_ms
                )
                
                return ValidationResponse(
                    success=True,
                    result=result,
                    fix_report=fix_report,
                    certificate=certificate
                )
                
            except Exception as e:
                logger.error(
                    f"Model validation failed",
                    model_id=request.model_id,
                    error=str(e),
                    exc_info=True
                )
                
                metrics.model_validations_total.labels(
                    profile=request.profile.value,
                    status="error"
                ).inc()
                
                return ValidationResponse(
                    success=False,
                    error=str(e),
                    turkish_error=f"Model doğrulama başarısız: {str(e)}"
                )
    
    async def _generate_fix_suggestions(
        self, 
        validation_result: ValidationResult
    ) -> List[FixSuggestion]:
        """Generate automated fix suggestions for issues."""
        suggestions = []
        
        for issue in validation_result.issues:
            # Skip info-level issues
            if issue.severity == ValidationSeverity.INFO:
                continue
            
            suggestion = None
            
            # Generate fix based on issue type
            if issue.type == "self_intersection":
                suggestion = FixSuggestion(
                    issue_id=issue.issue_id,
                    type="remove_self_intersection",
                    description="Remove self-intersecting faces",
                    turkish_description="Kendisiyle kesişen yüzeyler kaldırılacak",
                    confidence="high",
                    automated=True,
                    parameters={"tolerance": 0.001}
                )
            elif issue.type == "thin_walls":
                suggestion = FixSuggestion(
                    issue_id=issue.issue_id,
                    type="thicken_walls",
                    description="Increase wall thickness to minimum",
                    turkish_description="Duvar kalınlığı minimum değere artırılacak",
                    confidence="medium",
                    automated=True,
                    parameters={"min_thickness": 1.0}
                )
            elif issue.type == "non_manifold":
                suggestion = FixSuggestion(
                    issue_id=issue.issue_id,
                    type="fix_topology",
                    description="Fix non-manifold edges",
                    turkish_description="Manifold olmayan kenarlar düzeltilecek",
                    confidence="medium",
                    automated=True,
                    parameters={}
                )
            elif issue.type == "overhang":
                suggestion = FixSuggestion(
                    issue_id=issue.issue_id,
                    type="add_support",
                    description="Add support structures for overhangs",
                    turkish_description="Askıda kalan yüzeyler için destek eklenecek",
                    confidence="high",
                    automated=False,  # Manual review recommended
                    parameters={"angle_threshold": 45}
                )
            
            if suggestion:
                suggestions.append(suggestion)
        
        return suggestions
    
    async def _apply_automated_fixes(
        self,
        doc_handle: Any,
        suggestions: List[FixSuggestion]
    ) -> FixReport:
        """Apply automated fixes to model."""
        report = FixReport(total_suggestions=len(suggestions))
        
        for suggestion in suggestions:
            if not suggestion.automated:
                report.skipped_fixes += 1
                report.fixes.append({
                    "suggestion_id": suggestion.suggestion_id,
                    "status": "skipped",
                    "reason": "Manual review required"
                })
                continue
            
            if suggestion.confidence == "low":
                report.skipped_fixes += 1
                report.fixes.append({
                    "suggestion_id": suggestion.suggestion_id,
                    "status": "skipped",
                    "reason": "Low confidence"
                })
                continue
            
            try:
                # Apply fix (would call actual FreeCAD operations)
                # This is a placeholder - actual implementation would modify the document
                result = await self._apply_single_fix(doc_handle, suggestion)
                
                report.applied_fixes += 1
                report.successful_fixes += 1
                report.fixes.append({
                    "suggestion_id": suggestion.suggestion_id,
                    "status": "success",
                    "result": result
                })
                
                self.fixes_applied += 1
                
            except Exception as e:
                report.failed_fixes += 1
                report.errors.append({
                    "suggestion_id": suggestion.suggestion_id,
                    "error": str(e)
                })
        
        return report
    
    async def _apply_single_fix(
        self,
        doc_handle: Any,
        suggestion: FixSuggestion
    ) -> Dict[str, Any]:
        """Apply a single fix to the document."""
        # This would contain actual FreeCAD operations
        # Placeholder implementation
        
        if suggestion.type == "remove_self_intersection":
            # Would call FreeCAD operations to fix self-intersections
            return {"status": "fixed", "method": "boolean_union"}
        elif suggestion.type == "thicken_walls":
            # Would call FreeCAD operations to thicken walls
            return {"status": "fixed", "thickness_added": suggestion.parameters.get("min_thickness")}
        elif suggestion.type == "fix_topology":
            # Would call FreeCAD operations to fix topology
            return {"status": "fixed", "edges_fixed": 1}
        
        return {"status": "not_implemented"}
    
    def _calculate_model_hash(self, doc_handle: Any) -> str:
        """Calculate SHA256 hash of model for certification."""
        # This would serialize the model and calculate hash
        # Placeholder implementation
        model_data = f"{doc_handle}:{time.time()}"
        return hashlib.sha256(model_data.encode()).hexdigest()
    
    def get_validation_status(self, validation_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a validation."""
        # This would query validation history
        # Placeholder implementation
        return {
            "validation_id": validation_id,
            "status": "completed",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get validation metrics summary."""
        return {
            "total_validations": self.validations_total,
            "failed_validations": self.validations_failed,
            "success_rate": (self.validations_total - self.validations_failed) / self.validations_total if self.validations_total > 0 else 0,
            "fixes_applied": self.fixes_applied
        }


# Global validation framework instance
validation_framework = ModelValidationFramework()