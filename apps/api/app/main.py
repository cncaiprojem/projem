from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from .config import settings
from .db import create_redis_client, close_redis_client
from .core.logging import get_logger

logger = get_logger(__name__)
from .instrumentation import setup_metrics, setup_tracing, setup_celery_instrumentation
from .sentry_setup import setup_sentry
from .logging_setup import setup_logging
from .middleware import SecurityHeadersMiddleware, CORSMiddlewareStrict, XSSDetectionMiddleware
from .middleware.limiter import RateLimitMiddleware
from .middleware.csrf_middleware import CSRFProtectionMiddleware
from .middleware.dev_mode_middleware import (
    DevModeMiddleware, 
    ProductionHardeningMiddleware, 
    EnvironmentValidationMiddleware
)
from .services.rate_limiting_service import rate_limiting_service
from .services.environment_service import environment_service
from .core.environment import environment
from .routers import auth as auth_router
from .routers import auth_jwt as auth_jwt_router
from .routers import auth_enterprise as auth_enterprise_router
from .routers import oidc_auth as oidc_auth_router
from .routers import magic_link_auth as magic_link_auth_router
from .routers import mfa as mfa_router  # Task 3.7: MFA TOTP router
from .routers import health as health_router
from .routers import freecad as freecad_router
from .routers import assemblies as assemblies_router
from .routers import cam as cam_router
# from .routers.cad import cam2 as cam2_router  # Temporarily disabled
from .routers import jobs as jobs_router
from .routers import admin_dlq as admin_dlq_router
from .routers import admin_unmask as admin_unmask_router
from .routers import designs as designs_router  # Re-enabled with RBAC protection
from .routers import admin_users as admin_users_router  # New admin router
from .routers import me as me_router  # New user profile router
from .routers import security as security_router  # Security endpoints (Task 3.10)
from .routers import environment as environment_router  # Environment endpoints (Task 3.12)
# Legacy routers disabled - not part of Task Master ERD
# from .routers import projects as projects_router
# from .routers import design as design_router
# from .routers import cad as cad_router
# from .routers import tooling as tooling_router
# from .routers import reports as reports_router
# from .routers import setups as setups_router
# from .routers import fixtures as fixtures_router
try:
    from .routers import sim as sim_router  # type: ignore
    _sim_available = True
except Exception:
    sim_router = None  # type: ignore
    _sim_available = False
from .events import router as events_router
from .settings import app_settings as appset


setup_logging()
setup_tracing()
setup_sentry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown events."""
    # Startup
    logger.info("Starting FreeCAD API application", extra={
        'operation': 'application_startup',
        'version': '0.1.0'
    })
    
    try:
        # Initialize Redis client
        app.state.redis = await create_redis_client()
        logger.info("Redis client initialized successfully", extra={
            'operation': 'redis_startup'
        })
    except Exception as e:
        logger.error("Failed to initialize Redis client", exc_info=True, extra={
            'operation': 'redis_startup_failed',
            'error_type': type(e).__name__
        })
        # Continue without Redis - some features may be unavailable
        app.state.redis = None
    
    try:
        # Initialize environment service (Task 3.12)
        await environment_service.initialize()
        logger.info("Ultra-Enterprise environment service initialized successfully", extra={
            'operation': 'environment_service_startup',
            'environment': environment.ENV,
            'dev_mode': environment.is_dev_mode
        })
    except Exception as e:
        logger.error("Failed to initialize environment service", exc_info=True, extra={
            'operation': 'environment_service_startup_failed',
            'error_type': type(e).__name__
        })
        # This is critical - cannot continue without proper environment setup
        raise
    
    try:
        # Initialize enterprise rate limiting
        await rate_limiting_service.initialize()
        logger.info("Enterprise rate limiting initialized successfully", extra={
            'operation': 'rate_limiting_startup'
        })
    except Exception as e:
        logger.error("Failed to initialize rate limiting", exc_info=True, extra={
            'operation': 'rate_limiting_startup_failed',
            'error_type': type(e).__name__
        })
        # Continue without rate limiting - service will fail-open
    
    logger.info("Application startup completed", extra={
        'operation': 'application_startup_complete'
    })
    
    yield
    
    # Shutdown
    logger.info("Shutting down FreeCAD API application", extra={
        'operation': 'application_shutdown'
    })
    
    # Close Redis connection
    if hasattr(app.state, 'redis'):
        await close_redis_client(app.state.redis)
    
    # Close rate limiting service
    try:
        await rate_limiting_service.close()
        logger.info("Enterprise rate limiting closed successfully", extra={
            'operation': 'rate_limiting_shutdown'
        })
    except Exception as e:
        logger.error("Failed to close rate limiting service", exc_info=True, extra={
            'operation': 'rate_limiting_shutdown_failed',
            'error_type': type(e).__name__
        })
    
    logger.info("Application shutdown completed", extra={
        'operation': 'application_shutdown_complete'
    })


app = FastAPI(
    title="FreeCAD Üretim Platformu API",
    version="0.1.0",
    lifespan=lifespan
)
# Ultra enterprise security middleware stack (Tasks 3.8, 3.9, 3.10, 3.12)
# Order is critical for security and proper functioning
app.add_middleware(EnvironmentValidationMiddleware)    # Environment validation (Task 3.12)
app.add_middleware(ProductionHardeningMiddleware)      # Production security hardening (Task 3.12)
app.add_middleware(DevModeMiddleware)                  # Development mode features (Task 3.12)
app.add_middleware(SecurityHeadersMiddleware)          # CSP and security headers (Task 3.10)
app.add_middleware(XSSDetectionMiddleware)             # XSS detection and prevention (Task 3.10)
app.add_middleware(CSRFProtectionMiddleware)           # CSRF double-submit protection (Task 3.8)
app.add_middleware(CORSMiddlewareStrict)               # Strict CORS enforcement (Task 3.10)
app.add_middleware(RateLimitMiddleware)                # Rate limiting (Task 3.9)

setup_metrics(app)
setup_celery_instrumentation()

app.include_router(health_router.router)
app.include_router(auth_router.router)
app.include_router(auth_jwt_router.router)
app.include_router(auth_enterprise_router.router)
app.include_router(oidc_auth_router.router)
app.include_router(magic_link_auth_router.router)
app.include_router(mfa_router.router)  # Task 3.7: MFA TOTP endpoints
app.include_router(freecad_router.router)
app.include_router(assemblies_router.router)
app.include_router(cam_router.router)
# app.include_router(cam2_router)  # Temporarily disabled
app.include_router(jobs_router.router)
app.include_router(admin_dlq_router.router)
app.include_router(admin_unmask_router.router)
app.include_router(designs_router.router)  # Re-enabled with RBAC protection
app.include_router(admin_users_router.router)  # New admin router with RBAC
app.include_router(me_router.router)  # New user profile router with RBAC
app.include_router(security_router.router)  # Security endpoints (Task 3.10)
app.include_router(environment_router.router)  # Environment endpoints (Task 3.12)
app.include_router(environment_router.health_router)  # Public health endpoint (Task 3.12)
if _sim_available and sim_router is not None:
    app.include_router(sim_router.router)
app.include_router(events_router)
# Legacy routers disabled - not part of Task Master ERD
# app.include_router(projects_router.router)
# app.include_router(design_router.router)
# app.include_router(cad_router.router)
# app.include_router(tooling_router.router)
# app.include_router(reports_router.router)
# app.include_router(setups_router.router)
# app.include_router(fixtures_router.router)


@app.get("/", include_in_schema=False)
def root():
    response_data = {
        "mesaj": "FreeCAD Ultra-Enterprise API çalışıyor", 
        "env": settings.env,
        "environment": str(environment.ENV),
        "security_level": environment.security_level_display_tr
    }
    
    # Add development information if in dev mode (Task 3.12)
    if environment.is_dev_mode:
        response_data["_dev"] = {
            "mode": "development",
            "features_active": {
                "auth_bypass": environment.DEV_AUTH_BYPASS,
                "detailed_errors": environment.DEV_DETAILED_ERRORS,
                "csrf_localhost_bypass": environment.CSRF_DEV_LOCALHOST_BYPASS
            },
            "warning": "Development mode aktif - Production için uygun değil"
        }
    
    return response_data

from fastapi.responses import JSONResponse
from starlette.requests import Request


@app.exception_handler(Exception)
async def unhandled_exc(request: Request, exc: Exception):
    import logging, traceback
    logging.exception("Unhandled exception")
    origin = request.headers.get("origin")
    allowed = (not appset.cors_allowed_origins) or (origin in appset.cors_allowed_origins)
    resp = JSONResponse(status_code=500, content={"detail": str(exc)})
    if origin and allowed:
        resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Credentials"] = "false"
    return resp


