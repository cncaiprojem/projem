"""
Database models package for the FreeCAD CNC/CAM/CAD Production Platform.

This package contains all SQLAlchemy ORM models organized by domain.
"""

from .base import Base, TimestampMixin, metadata
from .user import User
from .session import Session
from .license import License
from .invoice import Invoice
from .payment import Payment
from .model import Model
from .job import Job
from .cam_run import CamRun
from .sim_run import SimRun
from .artefact import Artefact
from .machine import Machine
from .material import Material
from .notification import Notification
from .erp_mes_sync import ErpMesSync
from .audit_log import AuditLog
from .security_event import SecurityEvent
from .tool import Tool

# Import additional models from separate modules to ensure they're registered
try:
    from ..models_cutting import CuttingData
    from ..models_project import (
        Project, ProjectFile, AIQnA, Fixture, Setup, Op3D, Collision, PostRun
    )
    from ..models_tooling import (
        ToolLegacy, Holder, ToolPreset, ShopPackage
    )
    _additional_models_loaded = True
except ImportError:
    _additional_models_loaded = False

__all__ = [
    # Base
    "Base",
    "TimestampMixin",
    "metadata",
    
    # User & Auth
    "User",
    "Session",
    "License",
    
    # Billing
    "Invoice",
    "Payment",
    
    # Core Business
    "Model",
    "Job",
    "CamRun",
    "SimRun",
    "Artefact",
    
    # Reference Data
    "Machine",
    "Material",
    "Tool",
    
    # System
    "Notification",
    "ErpMesSync",
    "AuditLog",
    "SecurityEvent",
]

# Add additional models to __all__ if they were loaded successfully
if _additional_models_loaded:
    __all__.extend([
        # Cutting Data
        "CuttingData",
        
        # Project Management
        "Project",
        "ProjectFile", 
        "AIQnA",
        "Fixture",
        "Setup",
        "Op3D",
        "Collision",
        "PostRun",
        
        # Tooling (Legacy)
        "ToolLegacy",
        "Holder",
        "ToolPreset", 
        "ShopPackage",
    ])