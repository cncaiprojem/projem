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

from .artefact import Artefact
from .audit_log import AuditLog
from .base import Base, TimestampMixin, metadata
from .cam_run import CamRun
from .erp_mes_sync import ErpMesSync
from .idempotency import IdempotencyKey
from .invoice import Invoice
from .job import Job
from .license import License
from .machine import Machine
from .magic_link import MagicLink
from .material import Material
from .model import Model
from .notification import Notification
from .oidc_account import OIDCAccount
from .payment import Payment
from .security_event import SecurityEvent
from .session import Session
from .sim_run import SimRun
from .tool import Tool
from .user import User
from .webhook_event import WebhookEvent

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
    "OIDCAccount",
    "MagicLink",

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

    # Concurrency & Deduplication
    "IdempotencyKey",
    "WebhookEvent",
]

# All Task Master ERD models are now included in the main __all__ list above

# Import and setup ultra enterprise validators
from .validators import (
    AuditChainValidator,
    EnhancedSecurityValidator,
    EnumValidator,
    FinancialPrecisionValidator,
    IdempotencyKeyValidator,
    JSONBValidator,
    TurkishComplianceValidator,
    setup_model_validators,
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
