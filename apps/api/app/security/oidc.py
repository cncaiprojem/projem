"""
LEGACY OIDC JWT Token Verification - To Be Deprecated
This file contains JWT token verification logic and will be deprecated
in favor of the new OAuth2/OIDC authentication flow in Task 3.5.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional

import jwt
import requests
from fastapi import Depends, HTTPException, status, Header

from ..settings import app_settings as appset
from ..auth import dev_login


@lru_cache(maxsize=1)
def _jwks_cached() -> Dict[str, Any]:
    if not appset.oidc_jwks_url:
        raise RuntimeError("OIDC JWKS URL tanımlı değil")
    res = requests.get(appset.oidc_jwks_url, timeout=10)
    res.raise_for_status()
    return res.json()


def _get_key_for_kid(kid: str) -> Optional[Dict[str, Any]]:
    jwks = _jwks_cached()
    for k in jwks.get("keys", []):
        if k.get("kid") == kid:
            return k
    return None


@dataclass
class Principal:
    sub: str
    email: Optional[str]
    roles: List[str]


def _extract_roles(claims: Dict[str, Any]) -> List[str]:
    path = appset.roles_claim.split(".") if appset.roles_claim else []
    cur: Any = claims
    for p in path:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return []
    if isinstance(cur, list):
        return [str(x) for x in cur]
    return []


def _verify_and_decode(token: str) -> Dict[str, Any]:
    try:
        unverified = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Geçersiz token başlığı") from e
    kid = unverified.get("kid")
    if not kid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token kid eksik")
    jwk = _get_key_for_kid(kid)
    if not jwk:
        _jwks_cached.cache_clear()
        jwk = _get_key_for_kid(kid)
    if not jwk:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWKS anahtarı bulunamadı")
    try:
        audience = appset.oidc_audience or appset.oidc_client_id
        claims = jwt.decode(token, key=jwk, algorithms=[jwk.get("alg", "RS256")], audience=audience, options={"verify_aud": bool(audience)})
        return claims
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token doğrulama başarısız") from e


def get_principal(authorization: Optional[str] = Header(default=None, alias="Authorization")) -> Principal:
    # Dev-bypass: viewer rolü ver, admin değil
    if not appset.oidc_enabled:
        # dev_login endpoint ile token dağıtılıyor; burada minimal principal
        return Principal(sub="dev", email="dev@local", roles=["viewer"])
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Yetkisiz")
    token = authorization[len("Bearer ") :].strip()
    claims = _verify_and_decode(token)
    sub = claims.get("sub")
    email = claims.get("email") or claims.get("preferred_username")
    roles = _extract_roles(claims)
    if not sub:
        raise HTTPException(status_code=401, detail="Token içeriği eksik")
    return Principal(sub=sub, email=email, roles=roles)


def require_role(role: str):
    def _dep(principal: Principal = Depends(get_principal)) -> Principal:
        if role == "viewer":
            return principal
        if role == "operator":
            if any(r in principal.roles for r in ("operator", "admin")):
                return principal
        if role == "admin":
            if "admin" in principal.roles:
                return principal
        raise HTTPException(status_code=403, detail="Yetki yetersiz")
    return _dep


