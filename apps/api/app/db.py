from contextlib import contextmanager
from typing import Generator
import redis.asyncio as redis

from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker

from .config import settings


engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True))


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


def check_db() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


# Redis connection for OIDC session storage
_redis_client = None


async def get_redis() -> redis.Redis:
    """Get Redis client for OIDC state storage."""
    global _redis_client
    
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True
        )
    
    return _redis_client


async def close_redis():
    """Close Redis connection."""
    global _redis_client
    
    if _redis_client:
        await _redis_client.close()
        _redis_client = None


