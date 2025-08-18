"""
Legacy Settings Module - DEPRECATED
Imports from environment.py for backward compatibility

**IMPORTANT**: This module is deprecated as part of Task 3.12 Gemini Code Assist fixes.
All configuration has been consolidated into apps/api/app/core/environment.py

This file now serves as a compatibility layer to prevent breaking existing imports.
New code should import directly from environment.py.
"""

from __future__ import annotations

import warnings
from typing import Any

# Import the consolidated environment configuration
from .environment import UltraEnterpriseEnvironment, environment

# Issue deprecation warning
warnings.warn(
    "DEPRECATION WARNING: apps.api.app.core.settings is deprecated. "
    "Use apps.api.app.core.environment instead. This fixes Task 3.12 "
    "Gemini Code Assist feedback about configuration duplication.",
    DeprecationWarning,
    stacklevel=2
)


class UltraEnterpriseSettings(UltraEnterpriseEnvironment):
    """
    DEPRECATED: Legacy settings class for backward compatibility.
    
    This class inherits from UltraEnterpriseEnvironment to maintain
    compatibility with existing code while consolidating configuration.
    
    **Migration Path**:
    - Replace imports: from .settings import UltraEnterpriseSettings
    - With: from .environment import UltraEnterpriseEnvironment
    """
    
    def __init__(self, **kwargs: Any) -> None:
        # Issue warning on instantiation
        warnings.warn(
            "UltraEnterpriseSettings is deprecated. Use UltraEnterpriseEnvironment instead.",
            DeprecationWarning,
            stacklevel=2
        )
        super().__init__(**kwargs)


# Provide backward compatibility alias
ultra_enterprise_settings = environment