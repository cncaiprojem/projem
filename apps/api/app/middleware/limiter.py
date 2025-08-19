from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from ..settings import app_settings as appset


_WINDOWS: Dict[str, Tuple[int, int]] = {}
_buckets: Dict[str, Deque[float]] = defaultdict(deque)


def _parse_rule(rule: str) -> Tuple[int, float]:
    # "60/m" -> (60, 60.0)
    m = re.match(r"^(\d+)\/(s|m|h)$", rule)
    if not m:
        return 60, 60.0
    n = int(m.group(1))
    unit = m.group(2)
    window = 1.0 if unit == "s" else 60.0 if unit == "m" else 3600.0
    return n, window


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        key = None
        # Hedef yollar
        if path.startswith("/api/v1/assemblies"):
            rule = appset.rate_limit_rules.get("assemblies")
            key = "assemblies"
        elif path.startswith("/api/v1/cam/gcode"):
            rule = appset.rate_limit_rules.get("cam")
            key = "cam"
        elif (
            path.startswith("/api/v1/sim/")
            or path == "/api/v1/sim"
            or path.startswith("/api/v1/simulate")
        ):
            rule = appset.rate_limit_rules.get("simulate")
            key = "simulate"
        elif path.startswith("/api/v1/designs"):
            rule = appset.rate_limit_rules.get("designs") or "30/m"
            key = "designs"
        else:
            rule = None
        if not rule:
            return await call_next(request)
        limit, window = _parse_rule(rule)
        now = time.time()
        # Kimlik: IP + route; dev’de header’dan user_id varsa ekleyelim
        client_ip = request.client.host if request.client else "0.0.0.0"
        user_id = request.headers.get("X-User-Id")
        bucket_key = f"{key}:{client_ip}:{user_id or '-'}"
        dq = _buckets[bucket_key]
        # Eski kayıtları temizle
        while dq and (now - dq[0]) > window:
            dq.popleft()
        if len(dq) >= limit:
            return Response(
                status_code=429, content="Hız sınırı aşıldı, lütfen sonra tekrar deneyin."
            )
        dq.append(now)
        return await call_next(request)
