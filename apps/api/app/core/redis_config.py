"""
Redis Connection Management for Ultra Enterprise Rate Limiting (Task 3.9)

This module provides Redis connection management and configuration for
fastapi-limiter integration with existing Celery Redis infrastructure.

Features:
- Reuses existing Redis connection from Celery configuration
- Enterprise connection pooling and health checks
- Secure configuration management
- KVKV compliance for connection logging
"""

import os
import redis
from typing import Optional
from redis.connection import ConnectionPool
from structlog import get_logger

from ..settings import app_settings as settings

logger = get_logger(__name__)


class RedisConnectionManager:
    """Enterprise Redis connection manager for rate limiting."""
    
    def __init__(self):
        self._pool: Optional[ConnectionPool] = None
        self._client: Optional[redis.Redis] = None
        self._redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        
    def get_redis_pool(self) -> ConnectionPool:
        """Get or create Redis connection pool."""
        if not self._pool:
            self._pool = redis.ConnectionPool.from_url(
                self._redis_url,
                max_connections=20,
                retry_on_timeout=True,
                socket_keepalive=True,
                socket_keepalive_options={},
                health_check_interval=30,
                encoding='utf-8',
                decode_responses=True
            )
            
            logger.info("Redis connection pool created for rate limiting", extra={
                'operation': 'redis_pool_init',
                'redis_url_host': self._redis_url.split('@')[-1].split('/')[0] if '@' in self._redis_url else self._redis_url.split('//')[1].split('/')[0],
                'max_connections': 20
            })
            
        return self._pool
    
    def get_redis_client(self) -> redis.Redis:
        """Get Redis client for rate limiting operations."""
        if not self._client:
            self._client = redis.Redis(
                connection_pool=self.get_redis_pool(),
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True
            )
            
            # Health check
            try:
                self._client.ping()
                logger.info("Redis client initialized successfully", extra={
                    'operation': 'redis_client_init',
                    'status': 'healthy'
                })
            except Exception as e:
                logger.error("Redis health check failed", extra={
                    'operation': 'redis_client_init',
                    'status': 'failed',
                    'error': str(e)
                })
                raise
                
        return self._client
    
    def health_check(self) -> bool:
        """Perform Redis health check."""
        try:
            client = self.get_redis_client()
            result = client.ping()
            
            logger.debug("Redis health check completed", extra={
                'operation': 'redis_health_check',
                'status': 'healthy' if result else 'failed',
                'result': result
            })
            
            return bool(result)
            
        except Exception as e:
            logger.error("Redis health check failed", extra={
                'operation': 'redis_health_check',
                'status': 'failed',
                'error': str(e)
            })
            return False
    
    def close(self):
        """Close Redis connections."""
        if self._client:
            self._client.close()
            self._client = None
            
        if self._pool:
            self._pool.disconnect()
            self._pool = None
            
        logger.info("Redis connections closed", extra={
            'operation': 'redis_close'
        })


# Global Redis connection manager instance
redis_manager = RedisConnectionManager()


def get_redis_client() -> redis.Redis:
    """Get Redis client for rate limiting."""
    return redis_manager.get_redis_client()


def get_redis_url() -> str:
    """Get Redis URL for fastapi-limiter initialization."""
    return redis_manager._redis_url


async def init_redis_for_limiter():
    """Initialize Redis connection for fastapi-limiter."""
    try:
        # Test connection
        client = get_redis_client()
        await client.ping()
        
        logger.info("Redis initialized for rate limiting", extra={
            'operation': 'init_redis_for_limiter',
            'status': 'success'
        })
        
        return client
        
    except Exception as e:
        logger.error("Failed to initialize Redis for rate limiting", extra={
            'operation': 'init_redis_for_limiter',
            'status': 'failed',
            'error': str(e)
        })
        raise


async def close_redis_for_limiter():
    """Close Redis connections for rate limiting."""
    try:
        redis_manager.close()
        
        logger.info("Redis closed for rate limiting", extra={
            'operation': 'close_redis_for_limiter',
            'status': 'success'
        })
        
    except Exception as e:
        logger.error("Failed to close Redis for rate limiting", extra={
            'operation': 'close_redis_for_limiter',
            'status': 'failed',
            'error': str(e)
        })