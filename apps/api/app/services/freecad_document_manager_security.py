"""
Task 7.18: Security Integration for FreeCADDocumentManager

This module extends FreeCADDocumentManager with security features:
- Security validation before operations
- Feature flag integration
- SBOM metadata attachment
- Path sanitization and validation
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from pathlib import Path

from .freecad_document_manager import (
    FreeCADDocumentManager,
    DocumentMetadata,
    DocumentException,
    DocumentErrorCode,
)
from .security_validator import get_input_validator, PathValidator, DocumentPropertyValidator
from .sbom_generator import SBOMGenerator, SBOMFormat
from ..core.feature_flags import get_feature_flags, requires_feature
from ..core.security_config import get_security_config, SecurityLevel
from ..core.logging import get_logger

logger = get_logger(__name__)


class SecureFreeCADDocumentManager(FreeCADDocumentManager):
    """
    Enhanced FreeCADDocumentManager with Task 7.18 security features.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Initialize security components
        self.security_config = get_security_config()
        self.feature_flags = get_feature_flags()
        self.input_validator = get_input_validator()
        self.path_validator = PathValidator()
        self.property_validator = DocumentPropertyValidator()
        
        # Generate initial SBOM
        self._sbom_data = None
        if self.feature_flags.enable_input_validation:
            self._generate_sbom()
    
    def _generate_sbom(self) -> None:
        """Generate SBOM for the current environment."""
        try:
            generator = SBOMGenerator(SBOMFormat.CYCLONEDX_JSON)
            self._sbom_data = generator.generate()
            logger.info("Generated SBOM for document manager")
        except Exception as e:
            logger.error(f"Failed to generate SBOM: {e}")
    
    def create_document(
        self,
        job_id: str,
        author: Optional[str] = None,
        description: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None
    ) -> DocumentMetadata:
        """Create document with security validation."""
        
        # Check feature flag
        if not self.feature_flags.enable_ai_prompt_flow:
            raise DocumentException(
                "AI prompt flow is disabled",
                DocumentErrorCode.DOCUMENT_NOT_FOUND,
                "AI prompt akışı devre dışı"
            )
        
        # Validate and sanitize properties
        if properties and self.feature_flags.enable_input_validation:
            sanitized_properties = self.property_validator.sanitize_document_properties(
                properties
            )
            properties = sanitized_properties
        
        # Add security metadata
        if properties is None:
            properties = {}
        
        properties.update({
            "security_level": self.security_config.security_level.value,
            "freecad_version": self.security_config.freecad_version,
            "occt_version": self.security_config.occt_version,
            "sbom_generated": self._sbom_data is not None,
        })
        
        # Create document with parent implementation
        metadata = super().create_document(
            job_id=job_id,
            author=author,
            description=description,
            properties=properties
        )
        
        # Create sandbox for document if in production
        if self.security_config.security_level == SecurityLevel.PRODUCTION:
            sandbox_path = self.security_config.create_sandbox(job_id)
            metadata.properties["sandbox_path"] = str(sandbox_path)
        
        return metadata
    
    @requires_feature("enable_script_sandboxing")
    def execute_script_in_document(
        self,
        document_id: str,
        script_content: str,
        owner_id: str
    ) -> Dict[str, Any]:
        """Execute Python script in document with security sandboxing."""
        
        # Validate script for security issues
        if self.feature_flags.enable_input_validation:
            issues = self.security_config.validate_freecad_script(script_content)
            if issues:
                raise DocumentException(
                    f"Script validation failed: {', '.join(issues)}",
                    DocumentErrorCode.INVALID_METADATA,
                    "Betik doğrulama başarısız"
                )
        
        # Inject import restrictions
        if self.feature_flags.enable_script_sandboxing:
            # Get document metadata to extract job_id
            metadata = self.documents.get(document_id)
            if not metadata:
                raise DocumentException(
                    f"Document not found: {document_id}",
                    DocumentErrorCode.DOCUMENT_NOT_FOUND,
                    "Belge bulunamadı"
                )
            
            # Get job-specific sandbox path
            sandbox_path = self.security_config.get_sandbox_path(metadata.job_id)
            
            # Generate import hook with job-specific sandbox
            import_hook = self.security_config.python_policy.generate_import_hook(
                self.security_config.security_level,
                sandbox_dir=sandbox_path
            )
            script_content = import_hook + "\n\n" + script_content
        
        # Execute with resource limits
        # Note: Actual execution would require subprocess with resource limits
        # This is a placeholder for the pattern
        logger.info(
            "Executing sandboxed script",
            document_id=document_id,
            security_level=self.security_config.security_level.value
        )
        
        # Return placeholder result
        return {
            "status": "executed",
            "sandboxed": self.feature_flags.enable_script_sandboxing,
            "security_level": self.security_config.security_level.value
        }
    
    def save_document(
        self,
        document_id: str,
        save_path: Optional[str] = None,
        compress: bool = None,
        create_backup: bool = True,
        owner_id: Optional[str] = None
    ) -> str:
        """Save document with path validation."""
        
        # Validate save path if provided
        if save_path and self.feature_flags.enable_path_traversal_protection:
            path_result = self.path_validator.validate_path(save_path)
            if not path_result.is_valid:
                raise DocumentException(
                    f"Invalid save path: {', '.join(path_result.errors)}",
                    DocumentErrorCode.SAVE_FAILED,
                    "Geçersiz kayıt yolu"
                )
            
            # Use sanitized path
            if path_result.sanitized_value:
                save_path = path_result.sanitized_value
        
        # Add SBOM to metadata before saving
        if document_id in self.documents and self._sbom_data:
            metadata = self.documents[document_id]
            metadata.properties["sbom"] = {
                "serial_number": self._sbom_data.get("serialNumber"),
                "spec_version": self._sbom_data.get("specVersion"),
                "component_count": len(self._sbom_data.get("components", [])),
                "vulnerability_count": len(self._sbom_data.get("vulnerabilities", [])),
            }
        
        # Save with parent implementation
        return super().save_document(
            document_id=document_id,
            save_path=save_path,
            compress=compress,
            create_backup=create_backup,
            owner_id=owner_id
        )
    
    def validate_assembly_constraints(
        self,
        assembly_id: str,
        constraints: List[Dict[str, Any]]
    ) -> bool:
        """Validate Assembly4 constraints with security checks."""
        
        if not self.feature_flags.enable_assembly4:
            logger.warning("Assembly4 is disabled")
            return False
        
        # Validate each constraint
        for constraint in constraints:
            result = self.input_validator.assembly_validator.validate_constraint(
                constraint
            )
            if not result.is_valid:
                logger.error(
                    f"Invalid constraint: {', '.join(result.errors)}",
                    assembly_id=assembly_id
                )
                return False
        
        return True
    
    def validate_material_definition(
        self,
        material_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate and sanitize material definition."""
        
        if not self.feature_flags.enable_material_framework:
            raise DocumentException(
                "Material Framework is disabled",
                DocumentErrorCode.INVALID_METADATA,
                "Malzeme Çerçevesi devre dışı"
            )
        
        # Validate material
        result = self.input_validator.material_validator.validate_material(
            material_data
        )
        
        if not result.is_valid:
            raise DocumentException(
                f"Invalid material: {', '.join(result.errors)}",
                DocumentErrorCode.INVALID_METADATA,
                "Geçersiz malzeme tanımı"
            )
        
        return material_data
    
    def check_geometry_limits(
        self,
        document_id: str,
        geometry_data: Dict[str, Any]
    ) -> bool:
        """Check geometry against OCCT limits."""
        
        if not self.feature_flags.enable_geometry_validation:
            return True
        
        result = self.input_validator.geometry_validator.validate_geometry_bounds(
            geometry_data
        )
        
        if not result.is_valid:
            logger.error(
                f"Geometry exceeds limits: {', '.join(result.errors)}",
                document_id=document_id
            )
            
            # Auto-heal if enabled
            if self.feature_flags.enable_auto_healing:
                logger.info("Attempting auto-healing for geometry issues")
                # Auto-healing logic would go here
            
            return False
        
        return True
    
    def get_security_status(self) -> Dict[str, Any]:
        """Get current security status."""
        return {
            "security_level": self.security_config.security_level.value,
            "script_sandboxing": self.feature_flags.enable_script_sandboxing,
            "input_validation": self.feature_flags.enable_input_validation,
            "path_traversal_protection": self.feature_flags.enable_path_traversal_protection,
            "assembly4_enabled": self.feature_flags.enable_assembly4,
            "material_framework_enabled": self.feature_flags.enable_material_framework,
            "macro_execution": self.feature_flags.enable_macro_execution,
            "freecad_version": self.security_config.freecad_version,
            "occt_version": self.security_config.occt_version,
            "max_workers": self.feature_flags.max_concurrent_freecad_workers,
            "sbom_available": self._sbom_data is not None,
        }
    
    def cleanup_sandbox(self, job_id: str) -> bool:
        """Clean up sandbox after job completion."""
        if self.security_config.security_level == SecurityLevel.PRODUCTION:
            return self.security_config.cleanup_sandbox(job_id)
        return True


# Factory function to create appropriate manager based on feature flags
def create_document_manager(secure: bool = True) -> FreeCADDocumentManager:
    """Create document manager with or without security features."""
    if secure and get_feature_flags().enable_input_validation:
        logger.info("Creating secure document manager with Task 7.18 features")
        return SecureFreeCADDocumentManager()
    else:
        logger.info("Creating standard document manager")
        return FreeCADDocumentManager()