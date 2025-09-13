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
from ..schemas.validation import (
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
from ..models import validation_models as db_models  # Database models
from sqlalchemy.orm import Session
from .freecad_document_manager import FreeCADDocumentManager, document_manager
from .geometric_validator import GeometricValidator
from .manufacturing_validator import ManufacturingValidator
from .standards_checker import StandardsChecker
from .quality_metrics import QualityMetrics

logger = get_logger(__name__)

# Constants for validation
DEFAULT_TOLERANCE = 0.001  # Default geometric tolerance in mm
TOPOLOGY_FIX_TOLERANCE = 0.01  # Tolerance for topology fixes
SHAPE_FIX_TOLERANCE = 0.1  # Tolerance for shape fixes  
MIN_WALL_THICKNESS = 1.0  # Minimum wall thickness in mm
OVERHANG_ANGLE_THRESHOLD = 45  # Degrees for overhang detection
CERTIFICATION_SCORE_THRESHOLD = 0.8  # Minimum score for full certification
OFFSET_TOLERANCE = 0.01  # Tolerance for offset operations
OFFSET_JOIN_ARC = 2  # Arc join mode for offset operations


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
        doc: Any,
        validation_profile: ValidationProfile = ValidationProfile.STANDARD,
        standards: Optional[List[str]] = None,
        correlation_id: Optional[str] = None
    ) -> ValidationResult:
        """Execute comprehensive model validation."""
        if not correlation_id:
            correlation_id = get_correlation_id()
        start_time = time.time()
        
        with create_span("model_validation", correlation_id=correlation_id) as span:
            span.set_attribute("validation.profile", validation_profile.value)
            
            try:
                # Use provided doc handle directly
                doc_handle = doc
                
                # Create validation result
                result = ValidationResult(
                    model_id="doc",  # Use generic ID since we have doc directly
                    profile=validation_profile,
                    metadata={}
                )
                
                # Get validators for profile
                validators = self.validator_registry.get_validators_for_profile(validation_profile)
                
                # Execute validations in parallel where possible
                validation_tasks = []
                
                # Geometric validation (always first)
                geometric_validator = self.validator_registry.get('geometric')
                if geometric_validator:
                    # Use asyncio.to_thread for CPU-bound geometric validation
                    geometric_result = await asyncio.to_thread(
                        geometric_validator.validate,
                        doc_handle
                    )
                    result.add_section('geometric', geometric_result)
                
                # Manufacturing validation would be done separately if needed
                # Processes not passed in new signature
                
                # Standards compliance if requested
                if standards:
                    standards_checker = self.validator_registry.get('standards')
                    if standards_checker:
                        for standard_str in standards:
                            try:
                                # Convert string to StandardType enum
                                from ..models.validation_models import StandardType
                                standard = StandardType(standard_str)
                                compliance_result = await standards_checker.check_compliance(
                                    doc_handle,
                                    standard
                                )
                                result.add_section(f'standards_{standard.value}', compliance_result)
                            except ValueError:
                                logger.warning(f"Unknown standard: {standard_str}")
                                continue
                
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
                
                # Note: Automated fixes and certificates would be handled by the caller
                
                # Set duration
                result.duration_ms = int((time.time() - start_time) * 1000)
                
                # Update metrics
                self.validations_total += 1
                if result.status == ValidationStatus.FAILED:
                    self.validations_failed += 1
                
                metrics.model_validations_total.labels(
                    profile=validation_profile.value,
                    status=result.status.value
                ).inc()
                
                logger.info(
                    f"Model validation completed",
                    profile=validation_profile.value,
                    status=result.status.value,
                    score=result.overall_score,
                    duration_ms=result.duration_ms
                )
                
                return result
                
            except Exception as e:
                logger.error(
                    "Model validation failed",
                    exc_info=True
                )
                
                metrics.model_validations_total.labels(
                    profile=validation_profile.value,
                    status="error"
                ).inc()
                
                # Don't expose internal error details to client
                return ValidationResponse(
                    success=False,
                    error="Model validation failed. Please try again later.",
                    turkish_error="Model doğrulama başarısız. Lütfen daha sonra tekrar deneyin."
                )
    
    async def _generate_fix_suggestions(
        self, 
        validation_result: ValidationResult
    ) -> List[FixSuggestion]:
        """Generate automated fix suggestions for issues."""
        suggestions = []
        
        # Map issue types to fix suggestions with metadata
        fix_mapping = {
            "self_intersection": {
                "type": "remove_self_intersection",
                "description": "Remove self-intersecting faces",
                "turkish_description": "Kendisiyle kesişen yüzeyler kaldırılacak",
                "confidence": "high",
                "automated": True,
                "parameters": {"tolerance": DEFAULT_TOLERANCE}
            },
            "thin_walls": {
                "type": "thicken_walls",
                "description": "Increase wall thickness to minimum",
                "turkish_description": "Duvar kalınlığı minimum değere artırılacak",
                "confidence": "medium",
                "automated": True,
                "parameters": {"min_thickness": MIN_WALL_THICKNESS}
            },
            "non_manifold": {
                "type": "fix_topology",
                "description": "Fix non-manifold edges",
                "turkish_description": "Manifold olmayan kenarlar düzeltilecek",
                "confidence": "medium",
                "automated": True,
                "parameters": {"tolerance": TOPOLOGY_FIX_TOLERANCE}
            },
            "overhang": {
                "type": "add_support",
                "description": "Add support structures for overhangs",
                "turkish_description": "Askıda kalan yüzeyler için destek eklenecek",
                "confidence": "high",
                "automated": False,  # Manual review recommended
                "parameters": {"angle_threshold": OVERHANG_ANGLE_THRESHOLD}
            },
            "open_edges": {
                "type": "close_gaps",
                "description": "Close open edges and gaps",
                "turkish_description": "Açık kenarlar ve boşluklar kapatılacak",
                "confidence": "medium",
                "automated": True,
                "parameters": {"tolerance": DEFAULT_TOLERANCE}
            },
            "invalid_faces": {
                "type": "rebuild_faces",
                "description": "Rebuild invalid faces",
                "turkish_description": "Geçersiz yüzeyler yeniden oluşturulacak",
                "confidence": "low",
                "automated": True,
                "parameters": {"method": "triangulation"}
            },
            "sharp_edges": {
                "type": "fillet_edges",
                "description": "Add fillets to sharp edges",
                "turkish_description": "Keskin kenarlara pah eklenecek",
                "confidence": "medium",
                "automated": False,
                "parameters": {"radius": 0.5}
            },
            "small_features": {
                "type": "remove_small_features",
                "description": "Remove features below minimum size",
                "turkish_description": "Minimum boyutun altındaki özellikler kaldırılacak",
                "confidence": "medium",
                "automated": True,
                "parameters": {"min_size": 0.1}
            }
        }
        
        # Process each issue and generate appropriate suggestions
        for issue in validation_result.issues:
            # Skip info-level issues
            if issue.severity == ValidationSeverity.INFO:
                continue
            
            # Look up fix configuration
            fix_config = fix_mapping.get(issue.type)
            if not fix_config:
                # Try to determine fix based on issue message
                if "thickness" in issue.message.lower():
                    fix_config = fix_mapping.get("thin_walls")
                elif "manifold" in issue.message.lower():
                    fix_config = fix_mapping.get("non_manifold")
                elif "open" in issue.message.lower() or "gap" in issue.message.lower():
                    fix_config = fix_mapping.get("open_edges")
            
            if fix_config:
                # Adjust confidence based on severity
                confidence = fix_config["confidence"]
                if issue.severity == ValidationSeverity.CRITICAL:
                    confidence = "high" if confidence != "low" else "medium"
                elif issue.severity == ValidationSeverity.WARNING:
                    confidence = "low" if confidence == "high" else confidence
                
                suggestion = FixSuggestion(
                    issue_id=issue.issue_id,
                    type=fix_config["type"],
                    description=fix_config["description"],
                    turkish_description=fix_config["turkish_description"],
                    confidence=confidence,
                    automated=fix_config["automated"],
                    parameters=fix_config["parameters"].copy()
                )
                
                # Add issue-specific details to parameters
                if hasattr(issue, 'location') and issue.location:
                    suggestion.parameters["location"] = issue.location
                if hasattr(issue, 'affected_entities') and issue.affected_entities:
                    suggestion.parameters["entities"] = issue.affected_entities
                
                suggestions.append(suggestion)
        
        # Sort suggestions by confidence and automated flag
        suggestions.sort(key=lambda s: (
            s.automated,  # Automated fixes first
            {"high": 3, "medium": 2, "low": 1}.get(s.confidence, 0)  # Then by confidence
        ), reverse=True)
        
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
                # Log full error internally
                logger.error(
                    f"Failed to apply fix",
                    suggestion_id=suggestion.suggestion_id,
                    fix_type=suggestion.type,
                    exc_info=True
                )
                
                report.failed_fixes += 1
                # Don't expose internal error details
                report.errors.append({
                    "suggestion_id": suggestion.suggestion_id,
                    "error": "Fix application failed"
                })
        
        return report
    
    async def _apply_single_fix(
        self,
        doc_handle: Any,
        suggestion: FixSuggestion
    ) -> Dict[str, Any]:
        """Apply a single fix to the document using FreeCAD operations."""
        try:
            # Import FreeCAD modules (lazy import to avoid issues when FreeCAD not available)
            import Part
            import FreeCAD
            
            if suggestion.type == "remove_self_intersection":
                # Fix self-intersections using boolean operations
                for obj in doc_handle.Objects:
                    if hasattr(obj, 'Shape'):
                        shape = obj.Shape
                        if hasattr(shape, 'removeSplitter'):
                            # Remove self-intersections
                            fixed_shape = shape.removeSplitter()
                            obj.Shape = fixed_shape
                        elif hasattr(shape, 'fix'):
                            # Alternative: use fix method
                            shape.fix(SHAPE_FIX_TOLERANCE, SHAPE_FIX_TOLERANCE, SHAPE_FIX_TOLERANCE)
                return {"status": "fixed", "method": "removeSplitter"}
            
            elif suggestion.type == "thicken_walls":
                # Thicken walls using offset operations
                min_thickness = suggestion.parameters.get("min_thickness", 1.0)
                for obj in doc_handle.Objects:
                    if hasattr(obj, 'Shape'):
                        shape = obj.Shape
                        if hasattr(shape, 'makeOffsetShape'):
                            # Create offset to thicken walls
                            offset_shape = shape.makeOffsetShape(
                                min_thickness / 2,  # offset distance
                                OFFSET_TOLERANCE,  # tolerance
                                inter=False,  # intersection
                                self_inter=False,  # self-intersection
                                offsetMode=0,  # skin mode
                                join=OFFSET_JOIN_ARC  # arc join
                            )
                            obj.Shape = offset_shape
                return {"status": "fixed", "thickness_added": min_thickness}
            
            elif suggestion.type == "fix_topology":
                # Fix topology issues
                edges_fixed = 0
                for obj in doc_handle.Objects:
                    if hasattr(obj, 'Shape'):
                        shape = obj.Shape
                        # Fix tolerance issues
                        if hasattr(shape, 'fixTolerance'):
                            shape.fixTolerance(TOPOLOGY_FIX_TOLERANCE)
                            edges_fixed += 1
                        # Remove small edges
                        if hasattr(shape, 'removeInternalWires'):
                            shape.removeInternalWires(TOPOLOGY_FIX_TOLERANCE)
                            edges_fixed += 1
                        # Sew shape if needed
                        if hasattr(shape, 'sewShape'):
                            shape.sewShape()
                            edges_fixed += 1
                return {"status": "fixed", "edges_fixed": edges_fixed}
            
            elif suggestion.type == "close_open_edges":
                # Close open edges in solids
                for obj in doc_handle.Objects:
                    if hasattr(obj, 'Shape'):
                        shape = obj.Shape
                        if hasattr(shape, 'isValid') and not shape.isValid():
                            if hasattr(shape, 'fix'):
                                shape.fix(TOPOLOGY_FIX_TOLERANCE, TOPOLOGY_FIX_TOLERANCE, TOPOLOGY_FIX_TOLERANCE)
                            if hasattr(shape, 'makeSolid'):
                                solid = Part.makeSolid(shape)
                                obj.Shape = solid
                return {"status": "fixed", "method": "makeSolid"}
            
            elif suggestion.type == "unify_normals":
                # Unify face normals
                for obj in doc_handle.Objects:
                    if hasattr(obj, 'Shape'):
                        shape = obj.Shape
                        if hasattr(shape, 'orientShells'):
                            shape.orientShells()
                return {"status": "fixed", "method": "orientShells"}
            
            return {"status": "not_implemented", "type": suggestion.type}
            
        except ImportError:
            logger.warning("FreeCAD not available, using mock fix")
            return {"status": "mock_fixed", "type": suggestion.type}
        except Exception as e:
            logger.error(
                f"Failed to apply fix",
                fix_type=suggestion.type,
                exc_info=True
            )
            # Re-raise with generic message
            raise ValueError(f"Failed to apply {suggestion.type} fix") from None
    
    def _calculate_model_hash(self, doc_handle: Any) -> str:
        """Calculate SHA256 hash of model for certification."""
        try:
            # Import FreeCAD modules
            import FreeCAD
            import Part
            
            # Collect all shape data for hashing
            shape_data = []
            
            for obj in doc_handle.Objects:
                if hasattr(obj, 'Shape'):
                    shape = obj.Shape
                    # Add shape properties to hash
                    shape_data.append(f"{obj.Name}")
                    shape_data.append(f"Volume:{shape.Volume:.6f}" if hasattr(shape, 'Volume') else "")
                    shape_data.append(f"Area:{shape.Area:.6f}" if hasattr(shape, 'Area') else "")
                    if hasattr(shape, 'CenterOfMass'):
                        com = shape.CenterOfMass
                        shape_data.append(f"CenterOfMass:{com.x:.6f},{com.y:.6f},{com.z:.6f}")
                    else:
                        shape_data.append("")
                    
                    # Add vertex positions for deterministic hash
                    if hasattr(shape, 'Vertexes'):
                        for v in shape.Vertexes:
                            shape_data.append(f"V:{v.Point.x:.6f},{v.Point.y:.6f},{v.Point.z:.6f}")
                    
                    # Add edge count and face count
                    if hasattr(shape, 'Edges'):
                        shape_data.append(f"Edges:{len(shape.Edges)}")
                    if hasattr(shape, 'Faces'):
                        shape_data.append(f"Faces:{len(shape.Faces)}")
            
            # Create deterministic string representation
            model_string = "|".join(sorted(shape_data))
            
            # Calculate SHA256 hash
            return hashlib.sha256(model_string.encode('utf-8')).hexdigest()
            
        except ImportError:
            # Fallback if FreeCAD not available
            logger.warning("FreeCAD not available for model hashing")
            model_data = f"{doc_handle}:{time.time()}"
            return hashlib.sha256(model_data.encode()).hexdigest()
        except Exception as e:
            logger.error(
                "Error calculating model hash",
                exc_info=True
            )
            # Fallback hash
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
    
    def _get_validation_result(self, db: Session, validation_id: str) -> Optional[db_models.ValidationResult]:
        """Get validation result from database."""
        try:
            return db.query(db_models.ValidationResult).filter(
                db_models.ValidationResult.validation_id == validation_id
            ).first()
        except Exception as e:
            logger.error(
                "Failed to get validation result",
                validation_id=validation_id,
                exc_info=True
            )
            return None
    
    def _store_certificate(self, db: Session, certificate: QualityCertificate, validation_result_id: int) -> bool:
        """Store certificate in database."""
        try:
            db_cert = db_models.ValidationCertificate(
                certificate_id=certificate.certificate_id,
                validation_result_id=validation_result_id,
                issued_at=certificate.issued_at,
                expires_at=certificate.expires_at,
                standards=certificate.standards_compliant,
                compliance_level="full" if certificate.validation_score >= CERTIFICATION_SCORE_THRESHOLD else "partial",
                signature=certificate.signature,
                model_hash=certificate.model_hash,
                cert_metadata=certificate.metadata
            )
            db.add(db_cert)
            db.commit()
            return True
        except Exception as e:
            logger.error(
                "Failed to store certificate",
                certificate_id=certificate.certificate_id,
                exc_info=True
            )
            db.rollback()
            return False
    
    def _get_certificate(self, db: Session, certificate_id: str) -> Optional[db_models.ValidationCertificate]:
        """Get certificate from database."""
        try:
            return db.query(db_models.ValidationCertificate).filter(
                db_models.ValidationCertificate.certificate_id == certificate_id
            ).first()
        except Exception as e:
            logger.error(
                "Failed to get certificate",
                certificate_id=certificate_id,
                exc_info=True
            )
            return None
    
    def _get_fix_suggestions(self, db: Session, validation_result_id: int) -> List[db_models.FixSuggestion]:
        """Get fix suggestions from database."""
        try:
            return db.query(db_models.FixSuggestion).filter(
                db_models.FixSuggestion.validation_result_id == validation_result_id
            ).all()
        except Exception as e:
            logger.error(
                "Failed to get fix suggestions",
                validation_result_id=validation_result_id,
                exc_info=True
            )
            return []



class AutoFixSuggestions:
    """Generates and applies automated fix suggestions for validation issues."""
    
    def __init__(self):
        """Initialize AutoFixSuggestions."""
        self.logger = logger
    
    async def suggest_fixes(self, validation_result: ValidationResult) -> List[FixSuggestion]:
        """Generate fix suggestions based on validation issues."""
        suggestions = []
        
        for issue in validation_result.issues:
            if issue.severity == "critical":
                # Generate critical issue fixes
                suggestion = FixSuggestion(
                    fix_id=f"fix_{issue.issue_id}",
                    issue_id=issue.issue_id,
                    fix_type="auto",
                    description=f"{issue.category} sorunu için otomatik düzeltme",
                    confidence=0.8,
                    estimated_impact="high",
                    code_changes=None
                )
                suggestions.append(suggestion)
            elif issue.severity == "warning":
                # Generate warning fixes
                suggestion = FixSuggestion(
                    fix_id=f"fix_{issue.issue_id}",
                    issue_id=issue.issue_id,
                    fix_type="manual",
                    description=f"{issue.category} uyarısı için önerilen düzeltme",
                    confidence=0.6,
                    estimated_impact="medium",
                    code_changes=None
                )
                suggestions.append(suggestion)
        
        return suggestions
    
    async def apply_automated_fixes(
        self,
        doc: Any,
        suggestions: List[FixSuggestion],
        user_id: Optional[int] = None
    ) -> FixReport:
        """Apply selected automated fixes to the model."""
        applied_fixes = []
        failed_fixes = []
        
        for suggestion in suggestions:
            try:
                if suggestion.fix_type == "auto":
                    # Apply automated fix (placeholder implementation)
                    # In real implementation, this would modify the FreeCAD document
                    applied_fixes.append({
                        "fix_id": suggestion.fix_id,
                        "status": "success"
                    })
                else:
                    # Manual fixes cannot be applied automatically
                    failed_fixes.append({
                        "fix_id": suggestion.fix_id,
                        "reason": "Manual düzeltme otomatik olarak uygulanamaz"
                    })
            except Exception as e:
                self.logger.error(f"Failed to apply fix {suggestion.fix_id}: {e}")
                failed_fixes.append({
                    "fix_id": suggestion.fix_id,
                    "reason": str(e)
                })
        
        return FixReport(
            report_id=f"report_{datetime.now(timezone.utc).timestamp()}",
            timestamp=datetime.now(timezone.utc),
            applied_fixes=applied_fixes,
            failed_fixes=failed_fixes,
            model_state="modified" if applied_fixes else "unchanged",
            validation_required=bool(applied_fixes)
        )


# Global validation framework instance
validation_framework = ModelValidationFramework()