"""
Legacy models module for backward compatibility.
All models are now in the models/ package.
"""

# Import all models from the new modular structure
from .models import (
    # Base
    Base,
    TimestampMixin,
    metadata,
    
    # User & Auth
    User,
    Session,
    License,
    
    # Billing
    Invoice,
    Payment,
    
    # Core Business
    Model,
    Job,
    CamRun,
    SimRun,
    Artefact,
    
    # Reference Data
    Machine,
    Material,
    Tool,
    
    # System
    Notification,
    ErpMesSync,
    AuditLog,
    SecurityEvent,
)

# Re-export for backward compatibility
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


