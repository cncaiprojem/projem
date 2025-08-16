"""
FastAPI application with comprehensive structlog integration.
This file can replace main.py once testing is complete.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import settings
from .instrumentation import setup_metrics, setup_tracing, setup_celery_instrumentation
from .sentry_setup import setup_sentry

# Import new structured logging
from .core.logging import configure_structlog, get_logger, log_security_event
from .middleware.logging import LoggingMiddleware
from .core.database_logging import setup_database_logging

# Import existing middleware
from .middleware import SecurityHeadersMiddleware, CORSMiddlewareStrict
from .middleware.limiter import RateLimitMiddleware

# Import routers
from .routers import auth as auth_router
from .routers import health as health_router
from .routers import freecad as freecad_router
from .routers import assemblies as assemblies_router
from .routers import cam as cam_router
from .routers.cad import cam2 as cam2_router
from .routers import jobs as jobs_router
from .routers import admin_dlq as admin_dlq_router
from .routers import admin_unmask as admin_unmask_router
from .routers import designs as designs_router
from .routers import projects as projects_router
from .routers import design as design_router
from .routers import cad as cad_router
from .routers import tooling as tooling_router
from .routers import reports as reports_router
from .routers import setups as setups_router
from .routers import fixtures as fixtures_router

try:
    from .routers import sim as sim_router  # type: ignore
    _sim_available = True
except Exception:
    sim_router = None  # type: ignore
    _sim_available = False

from .events import router as events_router
from .settings import app_settings as appset

# Configure structured logging first
configure_structlog()

# Get logger for this module
logger = get_logger(__name__)

# Setup other observability tools
setup_tracing()
setup_sentry()

# Log application startup
logger.info(
    "application_startup",
    event="Uygulama başlatılıyor",
    environment=settings.ENVIRONMENT if hasattr(settings, "ENVIRONMENT") else "unknown",
    version="0.1.0",
)

# Create FastAPI app
app = FastAPI(
    title="FreeCAD Üretim Platformu API",
    version="0.1.0",
    docs_url="/docs" if settings.ENVIRONMENT == "development" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT == "development" else None,
)

# Add middleware in correct order (last added is executed first)
app.add_middleware(
    LoggingMiddleware,
    slow_request_threshold_ms=1000,
    excluded_paths=["/health", "/ready", "/metrics"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CORSMiddlewareStrict)
app.add_middleware(RateLimitMiddleware)

# Setup metrics and instrumentation
setup_metrics(app)
setup_celery_instrumentation()

# Custom exception handlers with structured logging
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors with structured logging."""
    logger.warning(
        "validation_error",
        event="Doğrulama hatası",
        path=request.url.path,
        method=request.method,
        errors=exc.errors(),
        body=exc.body if hasattr(exc, "body") else None,
    )
    
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Doğrulama hatası",
            "errors": exc.errors(),
        },
    )

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle HTTP exceptions with structured logging."""
    # Log different levels based on status code
    if exc.status_code >= 500:
        logger.error(
            "http_exception",
            status_code=exc.status_code,
            detail=exc.detail,
            path=request.url.path,
            method=request.method,
        )
    elif exc.status_code == 401:
        log_security_event(
            "authentication_required",
            ip_address=request.client.host if request.client else None,
            details={
                "path": request.url.path,
                "method": request.method,
            }
        )
    elif exc.status_code == 403:
        log_security_event(
            "forbidden_access",
            ip_address=request.client.host if request.client else None,
            details={
                "path": request.url.path,
                "method": request.method,
            }
        )
    elif exc.status_code >= 400:
        logger.warning(
            "http_client_error",
            status_code=exc.status_code,
            detail=exc.detail,
            path=request.url.path,
            method=request.method,
        )
    
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions with structured logging."""
    logger.error(
        "unhandled_exception",
        event="Beklenmeyen hata",
        error=str(exc),
        error_type=type(exc).__name__,
        path=request.url.path,
        method=request.method,
        exc_info=True,
    )
    
    # Log as security event if it looks suspicious
    if "injection" in str(exc).lower() or "exploit" in str(exc).lower():
        log_security_event(
            "potential_attack",
            ip_address=request.client.host if request.client else None,
            details={
                "path": request.url.path,
                "method": request.method,
                "error": str(exc),
            }
        )
    
    return JSONResponse(
        status_code=500,
        content={"detail": "İç sunucu hatası"},
    )

# Application lifecycle events
@app.on_event("startup")
async def startup_event():
    """Log application startup completion."""
    logger.info(
        "application_ready",
        event="Uygulama hazır",
        routers_count=len(app.routes),
        middleware_count=len(app.middleware),
        sim_available=_sim_available,
    )
    
    # Setup database logging if engine is available
    try:
        from .db import engine
        setup_database_logging(
            engine,
            log_queries=settings.ENVIRONMENT == "development",
            slow_query_threshold_ms=500,
        )
        logger.info("database_logging_configured", event="Veritabanı loglama yapılandırıldı")
    except Exception as e:
        logger.warning(
            "database_logging_setup_failed",
            error=str(e),
        )

@app.on_event("shutdown")
async def shutdown_event():
    """Log application shutdown."""
    logger.info(
        "application_shutdown",
        event="Uygulama kapatılıyor",
    )

# Include routers
app.include_router(health_router.router)
app.include_router(auth_router.router)
app.include_router(freecad_router.router)
app.include_router(assemblies_router.router)
app.include_router(cam_router.router)
app.include_router(cam2_router)
app.include_router(jobs_router.router)
app.include_router(admin_dlq_router.router)
app.include_router(admin_unmask_router.router)
app.include_router(designs_router.router)
app.include_router(projects_router.router)
app.include_router(design_router.router)
app.include_router(cad_router.router)
app.include_router(tooling_router.router)
app.include_router(reports_router.router)
app.include_router(setups_router.router)
app.include_router(fixtures_router.router)
app.include_router(events_router)

if _sim_available and sim_router:
    app.include_router(sim_router.router)
    logger.info("sim_router_included", event="Simülasyon router'ı eklendi")
else:
    logger.warning("sim_router_unavailable", event="Simülasyon router'ı kullanılamıyor")