# LEGACY AUTH FILE - DEPRECATED
# This file is being replaced by the new Task 3.3 JWT implementation
# with ultra enterprise security standards.
#
# New implementation locations:
# - services/jwt_service.py (JWT token management)
# - services/token_service.py (Refresh token management)
# - middleware/jwt_middleware.py (JWT authentication middleware)
# - routers/auth_jwt.py (JWT auth endpoints)

from fastapi import HTTPException, status
from .schemas import TokenPair, UserOut

def create_token_pair(email: str) -> TokenPair:
    """DEPRECATED: Use services.jwt_service.JWTService instead"""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Legacy JWT implementation disabled. Use new Task 3.3 JWT system."
    )

def get_current_user(*args, **kwargs) -> UserOut:
    """DEPRECATED: Use middleware.jwt_middleware instead"""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Legacy JWT implementation disabled. Use new JWT middleware."
    )

def dev_login(*args, **kwargs) -> TokenPair:
    """DEPRECATED: Use new dev auth system"""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Legacy dev login disabled."
    )


