"""
Main authentication router - redirects to enterprise authentication.
This maintains compatibility while directing to the new ultra enterprise auth system.
"""

from fastapi import APIRouter
from .auth_enterprise import router as enterprise_router
from .auth_legacy import router as legacy_router

# Main auth router uses the enterprise authentication system
router = enterprise_router

# Legacy router is available for development/compatibility
__all__ = ["router", "legacy_router"]


