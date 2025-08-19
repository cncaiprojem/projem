"""
DEPRECATED: This file has been replaced by the comprehensive audit system.
Use the following services instead:

- app.services.audit_service.py - Main audit logging service
- app.services.security_event_service.py - Security event tracking
- app.services.pii_masking_service.py - PII masking and KVKV compliance
- app.helpers.audit_chain.py - Enhanced audit chain helpers

This file will be removed in the next cleanup cycle.
"""

import warnings
from typing import Any


def audit(event: str, **fields: Any) -> None:
    """DEPRECATED: Use AuditService.create_audit_entry() instead."""
    warnings.warn(
        "audit() function is deprecated. Use AuditService.create_audit_entry() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    # Legacy compatibility - will be removed
    pass
