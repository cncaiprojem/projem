"""
Authentication-specific rate limiting for Task 3.1.
Provides fine-grained rate limiting for authentication endpoints.
"""

import time
from collections import defaultdict, deque
from collections.abc import Callable
from functools import wraps

from fastapi import HTTPException, Request, status


class SimpleRateLimiter:
    """Simple in-memory rate limiter for authentication endpoints."""

    def __init__(self):
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def is_allowed(self, key: str, limit: int, window: int) -> bool:
        """
        Check if request is allowed based on rate limit.
        
        Args:
            key: Unique identifier for the client
            limit: Maximum number of requests
            window: Time window in seconds
            
        Returns:
            True if request is allowed, False otherwise
        """
        now = time.time()
        bucket = self._buckets[key]

        # Remove old entries outside the window
        while bucket and (now - bucket[0]) > window:
            bucket.popleft()

        # Check if limit is exceeded
        if len(bucket) >= limit:
            return False

        # Add current request
        bucket.append(now)
        return True

    def get_reset_time(self, key: str, window: int) -> int:
        """Get timestamp when rate limit resets."""
        bucket = self._buckets.get(key)
        if not bucket:
            return int(time.time())

        return int(bucket[0] + window) if bucket else int(time.time())


# Global rate limiter instance
rate_limiter = SimpleRateLimiter()


class RateLimitDecorator:
    """Rate limit decorator for FastAPI endpoints."""

    def __init__(self, rate: str):
        """
        Initialize rate limiter.
        
        Args:
            rate: Rate limit in format "requests/time" (e.g., "5/minute", "10/hour")
        """
        self.limit, self.window = self._parse_rate(rate)

    def _parse_rate(self, rate: str) -> tuple[int, int]:
        """Parse rate limit string."""
        try:
            count, period = rate.split("/")
            count = int(count)

            if period == "second":
                window = 1
            elif period == "minute":
                window = 60
            elif period == "hour":
                window = 3600
            else:
                raise ValueError(f"Unknown period: {period}")

            return count, window
        except Exception:
            # Default to 10 per minute
            return 10, 60

    def _get_client_key(self, request: Request) -> str:
        """Get unique client identifier."""
        # Use IP address as primary identifier
        ip = None
        if hasattr(request, "client") and request.client:
            ip = request.client.host

        # Check for forwarded IP headers
        if not ip and "x-forwarded-for" in request.headers:
            ip = request.headers["x-forwarded-for"].split(",")[0].strip()
        elif not ip and "x-real-ip" in request.headers:
            ip = request.headers["x-real-ip"]

        return ip or "unknown"

    def __call__(self, func: Callable) -> Callable:
        """Decorator function."""
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Find request object in arguments
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

            # Also check kwargs
            if not request:
                request = kwargs.get("request")

            if request:
                client_key = self._get_client_key(request)

                if not rate_limiter.is_allowed(client_key, self.limit, self.window):
                    reset_time = rate_limiter.get_reset_time(client_key, self.window)

                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Çok fazla istek. Lütfen daha sonra tekrar deneyin.",
                        headers={
                            "Retry-After": str(reset_time - int(time.time())),
                            "X-RateLimit-Limit": str(self.limit),
                            "X-RateLimit-Window": str(self.window),
                            "X-RateLimit-Reset": str(reset_time),
                        }
                    )

            return await func(*args, **kwargs)

        return wrapper


def limit(rate: str):
    """
    Rate limiting decorator.
    
    Usage:
        @limit("5/minute")
        async def my_endpoint():
            pass
    
    Args:
        rate: Rate limit in format "count/period" where period is second, minute, or hour
    """
    return RateLimitDecorator(rate)


# Convenience instances for common rate limits
limiter = type('Limiter', (), {
    'limit': limit
})()
