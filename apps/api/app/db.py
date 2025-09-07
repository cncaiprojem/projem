from contextlib import contextmanager
from typing import AsyncGenerator, Generator, Optional, Any
import redis.asyncio as redis
from fastapi import Request

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import scoped_session, sessionmaker

from .config import settings
from .core.logging import get_logger

logger = get_logger(__name__)


engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True))

# Async engine and session for WebSocket/SSE support
async_database_url = settings.database_url.replace('postgresql://', 'postgresql+asyncpg://')
async_database_url = async_database_url.replace('postgresql+psycopg2://', 'postgresql+asyncpg://')
async_engine = create_async_engine(async_database_url, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@contextmanager
def db_session() -> Generator:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_db() -> Generator:
    """FastAPI dependency for database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def check_db() -> bool:
    """Check database connectivity."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error("Database health check failed", exc_info=True, extra={
            'operation': 'check_db',
            'error_type': type(e).__name__
        })
        return False


async def check_redis(redis_client: Optional[redis.Redis]) -> bool:
    """Check Redis connectivity."""
    if not redis_client:
        return False
        
    try:
        await redis_client.ping()
        return True
    except Exception as e:
        logger.error("Redis health check failed", exc_info=True, extra={
            'operation': 'check_redis',
            'error_type': type(e).__name__
        })
        return False


# Redis connection management for FastAPI application lifecycle
async def create_redis_client() -> redis.Redis:
    """
    Create Redis client with enterprise security configuration.
    
    Returns:
        Configured Redis client instance
        
    Raises:
        Exception: If Redis connection cannot be established
    """
    try:
        redis_client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
            retry_on_error=[redis.ConnectionError, redis.TimeoutError],
            max_connections=20,
            health_check_interval=30
        )
        
        # Test connection
        await redis_client.ping()
        
        logger.info("Redis client created successfully", extra={
            'operation': 'create_redis_client',
            'redis_url': settings.redis_url.split('@')[-1] if '@' in settings.redis_url else settings.redis_url
        })
        
        return redis_client
        
    except Exception as e:
        logger.error("Failed to create Redis client", exc_info=True, extra={
            'operation': 'create_redis_client',
            'error_type': type(e).__name__
        })
        raise


async def close_redis_client(redis_client: Optional[redis.Redis]) -> None:
    """
    Safely close Redis connection.
    
    Args:
        redis_client: Redis client to close
    """
    if redis_client:
        try:
            await redis_client.close()
            logger.info("Redis client closed successfully", extra={
                'operation': 'close_redis_client'
            })
        except Exception as e:
            logger.error("Error closing Redis client", exc_info=True, extra={
                'operation': 'close_redis_client',
                'error_type': type(e).__name__
            })


def get_redis(request: Request) -> redis.Redis:
    """
    FastAPI dependency for Redis client.
    
    Args:
        request: FastAPI request object
        
    Returns:
        Redis client from application state
        
    Raises:
        RuntimeError: If Redis client is not initialized
    """
    redis_client = getattr(request.app.state, 'redis', None)
    if redis_client is None:
        logger.error("Redis client not initialized in app state", extra={
            'operation': 'get_redis'
        })
        raise RuntimeError("Redis client not initialized. Ensure startup event handler is configured.")
    
    return redis_client


