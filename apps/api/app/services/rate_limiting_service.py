"""
Ultra Enterprise Rate Limiting Service for Task 3.9

This service implements banking-level rate limiting with Redis backend using fastapi-limiter.
Provides granular rate limiting policies with IP + user composite keying,
brute force detection, and comprehensive security event logging.

Features:
- Distributed rate limiting with Redis persistence
- Composite keying: IP + user for granular control
- Proxy-aware X-Forwarded-For handling with security validation
- Turkish localized error messages (KVKV compliance)
- Security event correlation for brute force detection
- Integration with existing audit and security systems
"""

import ipaddress
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from fastapi import HTTPException, Request, status
from fastapi_limiter import FastAPILimiter
from sqlalchemy.orm import Session
from structlog import get_logger

from ..core.redis_config import get_redis_client
from ..middleware.jwt_middleware import AuthenticatedUser
from ..models.security_event import SecurityEvent

logger = get_logger(__name__)


class RateLimitType(Enum):
    """Rate limit types for different endpoint categories."""
    LOGIN = "login"
    MAGIC_LINK_REQUEST = "magic_link_request"
    TOKEN_REFRESH = "token_refresh"
    AI_PROMPT = "ai_prompt"
    REGISTRATION = "registration"
    PASSWORD_RESET = "password_reset"
    GENERAL = "general"


@dataclass
class RateLimitPolicy:
    """Rate limiting policy configuration."""
    requests: int
    window_seconds: int
    key_type: str  # "ip", "user", "ip_user", "session"
    burst_threshold: int | None = None  # For burst detection
    description: str = ""


@dataclass
class RateLimitResult:
    """Rate limiting check result."""
    allowed: bool
    remaining: int
    reset_time: int
    retry_after: int
    limit: int
    window: int
    key: str
    policy_type: RateLimitType


class EnterpriseRateLimitingService:
    """Ultra enterprise rate limiting service with Redis backend."""

    # Rate limiting policies per Task 3.9 requirements
    POLICIES: dict[RateLimitType, RateLimitPolicy] = {
        RateLimitType.LOGIN: RateLimitPolicy(
            requests=5,
            window_seconds=60,
            key_type="ip_user",
            burst_threshold=10,
            description="Giriş denemeleri"
        ),
        RateLimitType.MAGIC_LINK_REQUEST: RateLimitPolicy(
            requests=3,
            window_seconds=60,
            key_type="ip_user",
            burst_threshold=6,
            description="Magic link talepleri"
        ),
        RateLimitType.TOKEN_REFRESH: RateLimitPolicy(
            requests=60,
            window_seconds=60,
            key_type="session",
            burst_threshold=120,
            description="Token yenileme"
        ),
        RateLimitType.AI_PROMPT: RateLimitPolicy(
            requests=30,
            window_seconds=60,
            key_type="user",
            burst_threshold=50,
            description="AI sorguları"
        ),
        RateLimitType.REGISTRATION: RateLimitPolicy(
            requests=5,
            window_seconds=60,
            key_type="ip",
            burst_threshold=10,
            description="Kayıt denemeleri"
        ),
        RateLimitType.PASSWORD_RESET: RateLimitPolicy(
            requests=3,
            window_seconds=60,
            key_type="ip_user",
            burst_threshold=6,
            description="Şifre sıfırlama"
        ),
        RateLimitType.GENERAL: RateLimitPolicy(
            requests=100,
            window_seconds=60,
            key_type="ip",
            description="Genel API"
        )
    }

    def __init__(self):
        self.redis_client = get_redis_client()
        self._brute_force_threshold = 20  # Suspicious activity threshold
        self._brute_force_window = 300  # 5 minutes

    async def initialize(self):
        """Initialize fastapi-limiter with Redis."""
        try:
            await FastAPILimiter.init(
                redis=self.redis_client,
                prefix="rate_limit",
                default_key=self._default_key_generator
            )

            logger.info("Enterprise rate limiting initialized", extra={
                'operation': 'rate_limiting_init',
                'status': 'success',
                'policies_count': len(self.POLICIES)
            })

        except Exception as e:
            logger.error("Failed to initialize rate limiting", extra={
                'operation': 'rate_limiting_init',
                'status': 'failed',
                'error': str(e)
            })
            raise

    async def close(self):
        """Close rate limiting resources."""
        try:
            await FastAPILimiter.close()

            logger.info("Enterprise rate limiting closed", extra={
                'operation': 'rate_limiting_close',
                'status': 'success'
            })

        except Exception as e:
            logger.error("Failed to close rate limiting", extra={
                'operation': 'rate_limiting_close',
                'status': 'failed',
                'error': str(e)
            })

    def get_client_ip(self, request: Request, trust_proxy: bool = True) -> str | None:
        """
        Extract real client IP from request with proxy support.
        
        Handles X-Forwarded-For headers securely when behind trusted proxies.
        """
        ip_address = None

        if trust_proxy:
            # Check proxy headers in order of preference
            forwarded_for = request.headers.get("x-forwarded-for")
            if forwarded_for:
                # Take first IP from comma-separated list (original client)
                ip_address = forwarded_for.split(",")[0].strip()

            # Fallback to other proxy headers
            if not ip_address:
                real_ip = request.headers.get("x-real-ip")
                if real_ip:
                    ip_address = real_ip.strip()

        # Fallback to direct connection IP
        if not ip_address and hasattr(request, 'client') and request.client:
            ip_address = request.client.host

        # Validate IP address format
        if ip_address:
            try:
                ipaddress.ip_address(ip_address)
                return ip_address
            except ValueError:
                logger.warning("Invalid IP address format", extra={
                    'operation': 'get_client_ip',
                    'invalid_ip': ip_address[:20],  # Truncate for security
                    'headers': dict(request.headers)
                })
                return None

        return ip_address

    def _default_key_generator(self, request: Request) -> str:
        """Default key generator for fallback rate limiting."""
        return f"general:{self.get_client_ip(request) or 'unknown'}"

    def generate_rate_limit_key(
        self,
        request: Request,
        policy_type: RateLimitType,
        user: AuthenticatedUser | None = None,
        session_id: str | None = None
    ) -> str:
        """
        Generate rate limiting key based on policy type and context.
        
        Supports composite keying: IP + user, session-based, etc.
        """
        policy = self.POLICIES[policy_type]
        client_ip = self.get_client_ip(request) or "unknown"

        if policy.key_type == "ip":
            return f"{policy_type.value}:ip:{client_ip}"

        elif policy.key_type == "user" and user:
            return f"{policy_type.value}:user:{user.user_id}"

        elif policy.key_type == "ip_user":
            user_id = user.user_id if user else "anonymous"
            return f"{policy_type.value}:ip_user:{client_ip}:{user_id}"

        elif policy.key_type == "session" and session_id:
            return f"{policy_type.value}:session:{session_id}"

        else:
            # Fallback to IP-based limiting
            return f"{policy_type.value}:fallback:{client_ip}"

    async def check_rate_limit(
        self,
        request: Request,
        policy_type: RateLimitType,
        db: Session,
        user: AuthenticatedUser | None = None,
        session_id: str | None = None
    ) -> RateLimitResult:
        """
        Check rate limit for request and return detailed result.
        
        Also performs brute force detection and security logging.
        """
        policy = self.POLICIES[policy_type]
        key = self.generate_rate_limit_key(request, policy_type, user, session_id)

        try:
            # Check current rate limit status
            current_time = int(time.time())
            window_start = current_time - policy.window_seconds

            # Use Redis pipeline for atomic operations
            pipe = self.redis_client.pipeline()

            # Remove old entries outside window
            pipe.zremrangebyscore(key, 0, window_start)

            # Count current requests in window
            pipe.zcard(key)

            # Add current request
            pipe.zadd(key, {str(current_time): current_time})

            # Set expiration
            pipe.expire(key, policy.window_seconds)

            # Execute pipeline
            results = pipe.execute()
            current_count = results[1] + 1  # Add the new request

            # Calculate remaining and reset time
            remaining = max(0, policy.requests - current_count)
            reset_time = current_time + policy.window_seconds
            retry_after = policy.window_seconds if current_count > policy.requests else 0

            # Check if limit exceeded
            allowed = current_count <= policy.requests

            # Log rate limit check
            logger.debug("Rate limit check", extra={
                'operation': 'rate_limit_check',
                'policy_type': policy_type.value,
                'key_hash': hash(key) % 1000000,  # Anonymized key
                'current_count': current_count,
                'limit': policy.requests,
                'allowed': allowed,
                'client_ip': self.get_client_ip(request),
                'user_id': user.user_id if user else None
            })

            # Brute force detection
            if not allowed:
                await self._check_brute_force_pattern(
                    request, policy_type, db, user, current_count
                )

                # Log security event for rate limiting
                await self._log_rate_limit_event(
                    request, policy_type, db, user, current_count
                )

            return RateLimitResult(
                allowed=allowed,
                remaining=remaining,
                reset_time=reset_time,
                retry_after=retry_after,
                limit=policy.requests,
                window=policy.window_seconds,
                key=key,
                policy_type=policy_type
            )

        except Exception as e:
            logger.error("Rate limit check failed", extra={
                'operation': 'rate_limit_check',
                'policy_type': policy_type.value,
                'error': str(e),
                'client_ip': self.get_client_ip(request)
            })

            # Fail open for availability (but log the failure)
            return RateLimitResult(
                allowed=True,
                remaining=policy.requests,
                reset_time=current_time + policy.window_seconds,
                retry_after=0,
                limit=policy.requests,
                window=policy.window_seconds,
                key=key,
                policy_type=policy_type
            )

    async def _check_brute_force_pattern(
        self,
        request: Request,
        policy_type: RateLimitType,
        db: Session,
        user: AuthenticatedUser | None,
        current_count: int
    ):
        """Check for brute force attack patterns."""
        try:
            # Check if current violations exceed brute force threshold
            policy = self.POLICIES[policy_type]

            if (policy.burst_threshold and
                current_count >= policy.burst_threshold):

                # Log potential brute force attack
                client_ip = self.get_client_ip(request)

                # Create security event
                security_event = SecurityEvent(
                    event_type="potential_bruteforce_detected",
                    severity="high",
                    description=f"Potansiyel brute force saldırısı tespit edildi: {policy.description}",
                    details={
                        "policy_type": policy_type.value,
                        "request_count": current_count,
                        "burst_threshold": policy.burst_threshold,
                        "client_ip": client_ip,
                        "user_id": user.user_id if user else None,
                        "user_agent": request.headers.get("user-agent"),
                        "endpoint": str(request.url.path),
                        "detection_time": datetime.now(UTC).isoformat()
                    },
                    client_ip=client_ip,
                    user_id=user.user_id if user else None,
                    resolved=False
                )

                db.add(security_event)
                db.commit()

                logger.warning("Potential brute force attack detected", extra={
                    'operation': 'brute_force_detection',
                    'policy_type': policy_type.value,
                    'request_count': current_count,
                    'threshold': policy.burst_threshold,
                    'client_ip': client_ip,
                    'user_id': user.user_id if user else None,
                    'security_event_id': security_event.id
                })

        except Exception as e:
            logger.error("Brute force detection failed", extra={
                'operation': 'brute_force_detection',
                'error': str(e)
            })

    async def _log_rate_limit_event(
        self,
        request: Request,
        policy_type: RateLimitType,
        db: Session,
        user: AuthenticatedUser | None,
        request_count: int
    ):
        """Log rate limit violation as security event."""
        try:
            client_ip = self.get_client_ip(request)
            policy = self.POLICIES[policy_type]

            # Create security event for rate limiting
            security_event = SecurityEvent(
                event_type="rate_limited",
                severity="medium",
                description=f"Hız sınırı aşıldı: {policy.description}",
                details={
                    "policy_type": policy_type.value,
                    "request_count": request_count,
                    "limit": policy.requests,
                    "window_seconds": policy.window_seconds,
                    "client_ip": client_ip,
                    "user_id": user.user_id if user else None,
                    "user_agent": request.headers.get("user-agent"),
                    "endpoint": str(request.url.path),
                    "violation_time": datetime.now(UTC).isoformat()
                },
                client_ip=client_ip,
                user_id=user.user_id if user else None,
                resolved=True  # Rate limit violations auto-resolve
            )

            db.add(security_event)
            db.commit()

            logger.info("Rate limit event logged", extra={
                'operation': 'rate_limit_logging',
                'policy_type': policy_type.value,
                'request_count': request_count,
                'client_ip': client_ip,
                'security_event_id': security_event.id
            })

        except Exception as e:
            logger.error("Rate limit event logging failed", extra={
                'operation': 'rate_limit_logging',
                'error': str(e)
            })

    def create_rate_limit_exception(
        self,
        result: RateLimitResult,
        policy_type: RateLimitType
    ) -> HTTPException:
        """Create standardized 429 exception with Turkish localization."""
        policy = self.POLICIES[policy_type]

        # Turkish error messages per KVKV compliance
        error_messages = {
            RateLimitType.LOGIN: "Çok fazla giriş denemesi. Lütfen {retry_after} saniye sonra tekrar deneyin.",
            RateLimitType.MAGIC_LINK_REQUEST: "Çok fazla magic link talebi. Lütfen {retry_after} saniye sonra tekrar deneyin.",
            RateLimitType.TOKEN_REFRESH: "Token yenileme sınırı aşıldı. Lütfen {retry_after} saniye sonra tekrar deneyin.",
            RateLimitType.AI_PROMPT: "AI sorgu sınırı aşıldı. Lütfen {retry_after} saniye sonra tekrar deneyin.",
            RateLimitType.REGISTRATION: "Çok fazla kayıt denemesi. Lütfen {retry_after} saniye sonra tekrar deneyin.",
            RateLimitType.PASSWORD_RESET: "Şifre sıfırlama sınırı aşıldı. Lütfen {retry_after} saniye sonra tekrar deneyin.",
            RateLimitType.GENERAL: "Çok fazla istek. Lütfen {retry_after} saniye sonra tekrar deneyin."
        }

        message = error_messages.get(
            policy_type,
            "Hız sınırı aşıldı. Lütfen {retry_after} saniye sonra tekrar deneyin."
        ).format(retry_after=result.retry_after)

        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_code": "ERR-RATE-LIMIT",
                "message": message,
                "details": {
                    "limit": result.limit,
                    "window_seconds": result.window,
                    "remaining": result.remaining,
                    "reset_time": result.reset_time,
                    "policy_type": policy_type.value
                }
            },
            headers={
                "Retry-After": str(result.retry_after),
                "X-RateLimit-Limit": str(result.limit),
                "X-RateLimit-Remaining": str(result.remaining),
                "X-RateLimit-Reset": str(result.reset_time),
                "X-RateLimit-Window": str(result.window),
                "X-RateLimit-Policy": policy_type.value
            }
        )


# Global rate limiting service instance
rate_limiting_service = EnterpriseRateLimitingService()


async def get_rate_limiting_service() -> EnterpriseRateLimitingService:
    """Get the global rate limiting service."""
    return rate_limiting_service
