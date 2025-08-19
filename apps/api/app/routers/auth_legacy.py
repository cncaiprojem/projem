"""
Legacy authentication router for development compatibility.
Kept for development mode and backward compatibility.
"""

from fastapi import APIRouter, Depends

from ..auth import dev_login, get_current_user
from ..schemas import TokenPair, UserOut

router = APIRouter(prefix="/api/v1/auth-dev", tags=["Kimlik Doğrulama (Legacy/Dev)"])


@router.post("/dev-login", response_model=TokenPair)
def dev_login_route(token_pair: TokenPair = Depends(dev_login)) -> TokenPair:
    """Development mode login (only available when dev_auth_bypass=true)."""
    return token_pair


@router.get("/me", response_model=UserOut)
def me(user: UserOut = Depends(get_current_user)) -> UserOut:
    """Get current user information."""
    return user
