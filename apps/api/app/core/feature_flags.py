"""
Task 7.18: Feature Flags System for Model Generation Flows

Runtime configurable feature flags using Pydantic Settings with:
- Environment variable support
- Runtime toggle without restart
- Default values for development/production
"""

from __future__ import annotations

import os
from typing import Optional, Dict, Any
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .logging import get_logger

logger = get_logger(__name__)


class FeatureFlags(BaseSettings):
    """
    Feature flags for controlling model generation flows.
    All flags can be overridden via environment variables.
    """
    
    model_config = SettingsConfigDict(
        env_prefix="FEATURE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        validate_default=True,
        extra="ignore"
    )
    
    # Core model generation flows
    enable_ai_prompt_flow: bool = Field(
        default=True,
        description="Enable AI-based prompt to model generation"
    )
    
    enable_upload_flow: bool = Field(
        default=True,
        description="Enable direct CAD file upload and processing"
    )
    
    enable_parametric_flow: bool = Field(
        default=True,
        description="Enable parametric model generation"
    )
    
    # Experimental features
    enable_assembly4: bool = Field(
        default=False,
        description="Enable Assembly4 workbench (experimental)"
    )
    
    enable_assembly3: bool = Field(
        default=False,
        description="Enable Assembly3 workbench (experimental)"
    )
    
    enable_material_framework: bool = Field(
        default=True,
        description="Enable Material Framework for material definitions"
    )
    
    # Processing features
    enable_preview_generation: bool = Field(
        default=True,
        description="Enable 3D preview generation for models"
    )
    
    enable_mesh_optimization: bool = Field(
        default=True,
        description="Enable mesh optimization for exports"
    )
    
    enable_geometry_validation: bool = Field(
        default=True,
        description="Enable geometry validation checks"
    )
    
    enable_auto_healing: bool = Field(
        default=True,
        description="Enable automatic shape healing for invalid geometry"
    )
    
    # Performance and resource management
    max_concurrent_freecad_workers: int = Field(
        default=4,
        ge=1,
        le=16,
        description="Maximum concurrent FreeCAD worker processes"
    )
    
    max_model_complexity: int = Field(
        default=10000,
        ge=100,
        le=1000000,
        description="Maximum allowed model complexity (faces)"
    )
    
    enable_worker_pooling: bool = Field(
        default=True,
        description="Enable FreeCAD worker process pooling"
    )
    
    enable_memory_monitoring: bool = Field(
        default=True,
        description="Enable memory usage monitoring for workers"
    )
    
    # Security features
    enable_script_sandboxing: bool = Field(
        default=True,
        description="Enable Python script sandboxing in FreeCAD"
    )
    
    enable_input_validation: bool = Field(
        default=True,
        description="Enable strict input validation for all flows"
    )
    
    enable_path_traversal_protection: bool = Field(
        default=True,
        description="Enable path traversal attack protection"
    )
    
    enable_macro_execution: bool = Field(
        default=False,
        description="Allow execution of FreeCAD macros"
    )
    
    # Export features
    enable_step_export: bool = Field(
        default=True,
        description="Enable STEP format export"
    )
    
    enable_stl_export: bool = Field(
        default=True,
        description="Enable STL format export"
    )
    
    enable_iges_export: bool = Field(
        default=True,
        description="Enable IGES format export"
    )
    
    enable_obj_export: bool = Field(
        default=True,
        description="Enable OBJ format export"
    )
    
    enable_gcode_generation: bool = Field(
        default=True,
        description="Enable G-code generation for CNC"
    )
    
    # AI/ML features
    enable_ai_suggestions: bool = Field(
        default=True,
        description="Enable AI-powered design suggestions"
    )
    
    enable_ai_error_correction: bool = Field(
        default=True,
        description="Enable AI-based error correction"
    )
    
    enable_prompt_caching: bool = Field(
        default=True,
        description="Enable caching of AI prompt results"
    )
    
    # Monitoring and debugging
    enable_performance_metrics: bool = Field(
        default=True,
        description="Enable performance metrics collection"
    )
    
    enable_debug_logging: bool = Field(
        default=False,
        description="Enable verbose debug logging"
    )
    
    enable_trace_logging: bool = Field(
        default=False,
        description="Enable trace-level logging for debugging"
    )
    
    enable_job_archiving: bool = Field(
        default=True,
        description="Enable archiving of completed jobs"
    )
    
    # Integration features
    enable_webhook_notifications: bool = Field(
        default=False,
        description="Enable webhook notifications for job events"
    )
    
    enable_email_notifications: bool = Field(
        default=False,
        description="Enable email notifications for job completion"
    )
    
    enable_erp_integration: bool = Field(
        default=False,
        description="Enable ERP system integration"
    )
    
    # Experimental/Beta features
    enable_beta_features: bool = Field(
        default=False,
        description="Enable all beta features"
    )
    
    enable_alpha_features: bool = Field(
        default=False,
        description="Enable all alpha features (unstable)"
    )
    
    def is_enabled(self, flag_name: str) -> bool:
        """Check if a feature flag is enabled."""
        if not hasattr(self, flag_name):
            logger.warning(f"Unknown feature flag: {flag_name}")
            return False
        
        value = getattr(self, flag_name)
        
        # Log feature flag access for monitoring
        logger.debug(
            "Feature flag accessed",
            flag=flag_name,
            value=value
        )
        
        return bool(value)
    
    def get_enabled_features(self) -> Dict[str, bool]:
        """Get all enabled feature flags."""
        features = {}
        for field_name, field_info in self.model_fields.items():
            if field_name.startswith("enable_"):
                features[field_name] = getattr(self, field_name)
        return features
    
    def get_disabled_features(self) -> Dict[str, bool]:
        """Get all disabled feature flags."""
        features = {}
        for field_name, field_info in self.model_fields.items():
            if field_name.startswith("enable_") and not getattr(self, field_name):
                features[field_name] = False
        return features
    
    def toggle_feature(self, flag_name: str, value: bool) -> bool:
        """
        Toggle a feature flag at runtime.
        Note: This only affects the current instance, not environment variables.
        """
        if not hasattr(self, flag_name):
            logger.error(f"Cannot toggle unknown feature flag: {flag_name}")
            return False
        
        old_value = getattr(self, flag_name)
        setattr(self, flag_name, value)
        
        logger.info(
            "Feature flag toggled",
            flag=flag_name,
            old_value=old_value,
            new_value=value
        )
        
        return True
    
    def reset_to_defaults(self) -> None:
        """Reset all flags to their default values."""
        for field_name, field_info in self.model_fields.items():
            if hasattr(field_info, "default"):
                setattr(self, field_name, field_info.default)
        
        logger.info("Feature flags reset to defaults")
    
    def apply_profile(self, profile: str) -> None:
        """Apply a predefined feature flag profile."""
        profiles = {
            "development": {
                "enable_debug_logging": True,
                "enable_trace_logging": False,
                "enable_beta_features": True,
                "enable_alpha_features": False,
                "enable_script_sandboxing": False,
                "enable_macro_execution": True,
                "max_concurrent_freecad_workers": 8
            },
            "staging": {
                "enable_debug_logging": False,
                "enable_trace_logging": False,
                "enable_beta_features": True,
                "enable_alpha_features": False,
                "enable_script_sandboxing": True,
                "enable_macro_execution": False,
                "max_concurrent_freecad_workers": 6
            },
            "production": {
                "enable_debug_logging": False,
                "enable_trace_logging": False,
                "enable_beta_features": False,
                "enable_alpha_features": False,
                "enable_script_sandboxing": True,
                "enable_macro_execution": False,
                "max_concurrent_freecad_workers": 4
            },
            "security_hardened": {
                "enable_script_sandboxing": True,
                "enable_input_validation": True,
                "enable_path_traversal_protection": True,
                "enable_macro_execution": False,
                "enable_assembly4": False,
                "enable_assembly3": False,
                "enable_beta_features": False,
                "enable_alpha_features": False,
                "max_concurrent_freecad_workers": 2
            },
            "performance": {
                "enable_worker_pooling": True,
                "enable_memory_monitoring": True,
                "enable_mesh_optimization": True,
                "enable_preview_generation": False,
                "enable_performance_metrics": True,
                "max_concurrent_freecad_workers": 8
            }
        }
        
        if profile not in profiles:
            logger.error(f"Unknown profile: {profile}")
            return
        
        for flag_name, value in profiles[profile].items():
            if hasattr(self, flag_name):
                setattr(self, flag_name, value)
        
        logger.info(f"Applied feature flag profile: {profile}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Export all feature flags as dictionary."""
        return self.model_dump()
    
    def validate_configuration(self) -> List[str]:
        """Validate feature flag configuration for conflicts."""
        issues = []
        
        # Check for conflicting assembly workbenches
        if self.enable_assembly3 and self.enable_assembly4:
            issues.append(
                "Both Assembly3 and Assembly4 are enabled. "
                "Only one assembly workbench should be active."
            )
        
        # Check for security conflicts
        if self.enable_macro_execution and self.enable_script_sandboxing:
            issues.append(
                "Macro execution is enabled with script sandboxing. "
                "This may cause compatibility issues."
            )
        
        # Check for performance conflicts
        if self.max_concurrent_freecad_workers > 8 and self.enable_memory_monitoring:
            issues.append(
                "High worker count with memory monitoring may impact performance."
            )
        
        # Check for experimental features in production
        if os.getenv("ENVIRONMENT") == "production":
            if self.enable_alpha_features or self.enable_beta_features:
                issues.append(
                    "Experimental features are enabled in production environment."
                )
        
        return issues


# Global feature flags instance (singleton)
_feature_flags: Optional[FeatureFlags] = None


@lru_cache(maxsize=1)
def get_feature_flags() -> FeatureFlags:
    """Get global feature flags instance (cached singleton)."""
    global _feature_flags
    if _feature_flags is None:
        _feature_flags = FeatureFlags()
        
        # Validate configuration
        issues = _feature_flags.validate_configuration()
        if issues:
            for issue in issues:
                logger.warning(f"Feature flag configuration issue: {issue}")
        
        # Apply environment-based profile if set
        env_profile = os.getenv("FEATURE_PROFILE")
        if env_profile:
            _feature_flags.apply_profile(env_profile)
        
        # Log enabled features
        enabled = _feature_flags.get_enabled_features()
        logger.info(
            "Feature flags initialized",
            enabled_count=sum(1 for v in enabled.values() if v),
            total_count=len(enabled)
        )
    
    return _feature_flags


def reset_feature_flags() -> None:
    """Reset feature flags (mainly for testing)."""
    global _feature_flags
    _feature_flags = None
    get_feature_flags.cache_clear()


# Convenience decorators for feature flag checks
def requires_feature(flag_name: str):
    """Decorator to check if a feature is enabled before executing."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            flags = get_feature_flags()
            if not flags.is_enabled(flag_name):
                logger.warning(
                    f"Feature '{flag_name}' is disabled, skipping {func.__name__}"
                )
                return None
            return func(*args, **kwargs)
        return wrapper
    return decorator


def experimental_feature(func):
    """Decorator to mark a function as experimental."""
    def wrapper(*args, **kwargs):
        flags = get_feature_flags()
        if not (flags.enable_beta_features or flags.enable_alpha_features):
            logger.warning(
                f"Experimental feature {func.__name__} requires beta/alpha features enabled"
            )
            return None
        
        logger.info(f"Executing experimental feature: {func.__name__}")
        return func(*args, **kwargs)
    return wrapper