"""
Ultra Enterprise Helper Functions Package
Task 2.10: App-layer helper functions for banking-level precision

This package provides helper functions with clear separation of concerns:

AUDIT CHAIN HELPERS (audit_chain.py):
- AuditChainHelper: High-level database operations and business logic for audit trail management
- AuditChainJSONHelper: Canonical JSON operations for audit chain hash consistency
- TurkishComplianceAuditHelper: Turkish regulatory compliance in audit context (KVKV/GDPR/KDV)

CANONICAL JSON HELPERS (canonical_json.py):
- CanonicalJSONEncoder: Ultra enterprise canonical JSON encoder for audit chains
- AuditChainManager: Low-level hash chain operations and cryptographic integrity validation
- TurkishComplianceHelper: Turkish compliance validation delegating to validators.py

SINGLE SOURCE OF TRUTH:
- All Turkish VKN/TCKN validation logic is in models.validators.py
- Turkish compliance helpers delegate to authoritative validators
- No duplication of validation logic across modules
"""

from .audit_chain import (
    AuditChainHelper,
    AuditChainJSONHelper, 
    TurkishComplianceAuditHelper
)
from .canonical_json import (
    CanonicalJSONEncoder,
    AuditChainManager,
    TurkishComplianceHelper
)

__all__ = [
    # Audit chain helpers
    "AuditChainHelper",
    "AuditChainJSONHelper", 
    "TurkishComplianceAuditHelper",
    # Canonical JSON helpers  
    "CanonicalJSONEncoder",
    "AuditChainManager",
    "TurkishComplianceHelper"
]