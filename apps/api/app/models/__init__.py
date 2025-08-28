"""
Database models package for the FreeCAD CNC/CAM/CAD Production Platform.
Task 2.10: Ultra Enterprise SQLAlchemy models with banking-level precision.

This package contains all SQLAlchemy ORM models organized by domain with:
- Automatic enterprise validation via SQLAlchemy events
- Banking-level financial precision with Decimal arithmetic
- Turkish compliance (KVKV/GDPR/KDV) built-in
- Cryptographic audit chain integrity
- Idempotency key validation with enterprise constraints
"""

from .base import Base, TimestampMixin, metadata
from .user import User
from .session import Session
from .license import License
from .license_audit import LicenseAudit
from .invoice import Invoice
from .payment import Payment, PaymentWebhookEvent, PaymentAuditLog
from .model import Model
from .ai_suggestions import AISuggestion
from .topology_hashes import TopologyHash
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
from .oidc_account import OIDCAccount
from .magic_link import MagicLink
from .mfa_backup_code import MFABackupCode

# Import enums for external use
from .enums import *

# All models are now in the models/ package - no additional modules needed
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
    "LicenseAudit",
    "OIDCAccount",
    "MagicLink",
    "MFABackupCode",
    
    # Billing
    "Invoice",
    "Payment",
    "PaymentWebhookEvent",
    "PaymentAuditLog",
    
    # Core Business
    "Model",
    "AISuggestion",
    "TopologyHash",
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

# All Task Master ERD models are now included in the main __all__ list above

# Import and setup ultra enterprise validators
from .validators import (
    IdempotencyKeyValidator,
    EnumValidator, 
    JSONBValidator,
    FinancialPrecisionValidator,
    AuditChainValidator,
    TurkishComplianceValidator,
    EnhancedSecurityValidator,
    setup_model_validators
)

# Automatically setup enterprise validation when models are imported
setup_model_validators()

# Add validators to __all__ for external use
__all__.extend([
    "IdempotencyKeyValidator",
    "EnumValidator", 
    "JSONBValidator",
    "FinancialPrecisionValidator",
    "AuditChainValidator",
    "TurkishComplianceValidator",
    "EnhancedSecurityValidator",
])