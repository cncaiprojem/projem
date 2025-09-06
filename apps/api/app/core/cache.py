"""
Task 7.13: Performance Tuning and Caching Strategy

This module implements a comprehensive caching strategy with:
- Deterministic cache key generation with engine fingerprint
- Redis caching layer with compression (zstd)
- Two-tier geometry memoization (L1 in-process LRU, L2 Redis)
- Stampede control with singleflight locks
- In-flight request coalescing
- Tag-based cache invalidation
- Metrics and monitoring

Features:
- Engine fingerprint for cache determinism
- Canonical parameter normalization
- Redis with TTL-based eviction
- zstd compression for large values
- Stale-while-revalidate pattern
- Cache hit rate tracking
- Turkish error message support
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import platform
import random
import re
import subprocess
import sys
import threading
import time
import unicodedata
from collections import OrderedDict
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from functools import lru_cache
from typing import Any, Awaitable, Callable

import redis.asyncio as redis_async
import redis
from pydantic import BaseModel, Field

try:
    import zstandard as zstd
    ZSTD_AVAILABLE = True
except ImportError:
    ZSTD_AVAILABLE = False
    import gzip  # Fallback to gzip if zstd not available

from ..core.environment import environment as settings
from ..core.logging import get_logger
from ..core.telemetry import create_span
from ..core import metrics
from ..middleware.correlation_middleware import get_correlation_id

logger = get_logger(__name__)


class CacheErrorCode(str, Enum):
    """Cache error codes."""
    CACHE_MISS = "CACHE_MISS"
    CACHE_ERROR = "CACHE_ERROR"
    SERIALIZATION_ERROR = "SERIALIZATION_ERROR"
    COMPRESSION_ERROR = "COMPRESSION_ERROR"
    LOCK_TIMEOUT = "LOCK_TIMEOUT"
    REDIS_CONNECTION_ERROR = "REDIS_CONNECTION_ERROR"
    INVALID_KEY = "INVALID_KEY"
    TTL_EXPIRED = "TTL_EXPIRED"


class CacheException(Exception):
    """Cache operation exception."""
    def __init__(
        self,
        message: str,
        error_code: CacheErrorCode,
        turkish_message: str | None = None,
        details: dict[str, Any] | None = None
    ):
        super().__init__(message)
        self.error_code = error_code
        self.turkish_message = turkish_message or message
        self.details = details or {}


class CacheTier(str, Enum):
    """Cache tier levels."""
    L1_MEMORY = "l1_memory"
    L2_REDIS = "l2_redis"


class CacheFlowType(str, Enum):
    """Cache flow types for key generation."""
    PROMPT = "prompt"
    PARAMS = "params"
    UPLOAD = "upload"
    ASSEMBLY = "a4"
    GEOMETRY = "geom"
    EXPORT = "export"
    METRICS = "metrics"
    AI_SUGGESTION = "ai"
    DOC_TEMPLATE = "doc"


class EngineFingerprint(BaseModel):
    """Engine fingerprint for cache determinism."""
    freecad_version: str = Field(description="FreeCAD version")
    occt_version: str = Field(description="OpenCASCADE version")
    python_version: str = Field(description="Python major.minor version")
    mesh_params_version: str = Field(default="m1", description="Meshing parameters version")
    git_sha: str = Field(description="Git commit SHA")
    enabled_workbenches: list[str] = Field(default_factory=list, description="Enabled workbenches")
    feature_flags: dict[str, bool] = Field(default_factory=dict, description="Feature flags")
    
    def to_string(self) -> str:
        """Generate fingerprint string."""
        workbenches = ",".join(sorted(self.enabled_workbenches))
        flags = ",".join(f"{k}={v}" for k, v in sorted(self.feature_flags.items()))
        return (
            f"fc{{{self.freecad_version}}}-"
            f"occt{{{self.occt_version}}}-"
            f"py{{{self.python_version}}}-"
            f"mesh{{{self.mesh_params_version}}}-"
            f"git{{{self.git_sha}}}-"
            f"wb{{{workbenches}}}-"
            f"flags{{{flags}}}"
        )


class CacheConfig(BaseModel):
    """Cache configuration."""
    # Redis settings
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis connection URL")
    redis_pool_size: int = Field(default=10, description="Redis connection pool size")
    redis_decode_responses: bool = Field(default=False, description="Decode Redis responses")
    
    # TTL settings (in seconds)
    ttl_geometry: int = Field(default=86400, description="Geometry/BREP TTL (24h)")
    ttl_mesh: int = Field(default=604800, description="Mesh/export TTL (7d)")
    ttl_ai_suggestion: int = Field(default=21600, description="AI suggestion TTL (6h)")
    ttl_metrics: int = Field(default=2592000, description="Metrics TTL (30d)")
    ttl_doc_template: int = Field(default=604800, description="Document template TTL (7d)")
    ttl_default: int = Field(default=3600, description="Default TTL (1h)")
    
    # Compression settings
    compression_enabled: bool = Field(default=True, description="Enable compression")
    compression_threshold_bytes: int = Field(default=4096, description="Min size for compression (4KB)")
    compression_level: int = Field(default=6, description="zstd compression level (1-22)")
    
    # L1 cache settings
    l1_max_size: int = Field(default=5000, description="L1 LRU cache max entries")
    l1_memory_limit_mb: int = Field(default=512, description="L1 memory limit in MB")
    
    # Stampede control
    lock_timeout_seconds: int = Field(default=120, description="Singleflight lock timeout")
    stale_while_revalidate_seconds: int = Field(default=300, description="Serve stale for 5 min")
    
    # Performance settings
    pipeline_batch_size: int = Field(default=100, description="Redis pipeline batch size")
    enable_cache_metrics: bool = Field(default=True, description="Enable cache metrics")
    
    @classmethod
    def from_env(cls) -> "CacheConfig":
        """Create config from environment variables."""
        return cls(
            redis_url=getattr(settings, "REDIS_URL", "redis://localhost:6379/0"),
            redis_pool_size=getattr(settings, "REDIS_POOL_SIZE", 10),
            compression_enabled=getattr(settings, "CACHE_COMPRESSION_ENABLED", True),
            l1_max_size=getattr(settings, "CACHE_L1_MAX_SIZE", 5000),
            enable_cache_metrics=getattr(settings, "CACHE_METRICS_ENABLED", True),
        )


class Canonicalizer:
    """Canonicalize parameters for deterministic cache keys."""
    
    @staticmethod
    def normalize_json(data: Any, is_prompt: bool = False) -> str:
        """
        Normalize JSON data for consistent hashing.
        - Sort keys recursively
        - Remove null/empty values
        - Coerce booleans
        - Round floats to 1e-6
        - Normalize strings with NFKC
        - Apply PII masking for prompts
        """
        def normalize_value(value: Any, depth: int = 0) -> Any:
            if value is None or value == "" or value == [] or value == {}:
                return None  # Will be filtered out
            
            if isinstance(value, bool):
                return value  # Keep as bool
            
            if isinstance(value, (int, float)):
                if isinstance(value, float):
                    # Round to 1e-6, clamp denormals
                    if abs(value) < 1e-10:
                        return 0.0
                    return round(value, 6)
                return value
            
            if isinstance(value, Decimal):
                return float(value)
            
            if isinstance(value, str):
                # Normalize unicode
                normalized = unicodedata.normalize('NFKC', value)
                # Trim and collapse whitespace
                normalized = ' '.join(normalized.split())
                
                if is_prompt and depth == 0:
                    # Apply PII masking for top-level prompt strings
                    normalized = Canonicalizer._mask_pii(normalized)
                    # Lowercase free text (preserve quoted strings)
                    normalized = Canonicalizer._lowercase_non_quoted(normalized)
                
                return normalized
            
            if isinstance(value, dict):
                # Sort keys and recurse
                sorted_dict = OrderedDict()
                for key in sorted(value.keys()):
                    normalized_val = normalize_value(value[key], depth + 1)
                    if normalized_val is not None:
                        sorted_dict[key] = normalized_val
                return dict(sorted_dict) if sorted_dict else None
            
            if isinstance(value, (list, tuple)):
                normalized_list = []
                for item in value:
                    normalized_item = normalize_value(item, depth + 1)
                    if normalized_item is not None:
                        normalized_list.append(normalized_item)
                return normalized_list if normalized_list else None
            
            # For other types, convert to string
            return str(value)
        
        normalized = normalize_value(data)
        if normalized is None:
            normalized = {}
        
        # Use separators without spaces for compact representation
        return json.dumps(normalized, separators=(',', ':'), ensure_ascii=True)
    
    @staticmethod
    def _mask_pii(text: str) -> str:
        """Mask potential PII in text."""
        # Email addresses
        text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]', text)
        # Phone numbers (basic pattern)
        text = re.sub(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE]', text)
        # Credit card numbers (basic pattern)
        text = re.sub(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b', '[CARD]', text)
        # SSN (US)
        text = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', '[SSN]', text)
        return text
    
    @staticmethod
    def _lowercase_non_quoted(text: str) -> str:
        """Lowercase text except quoted strings."""
        parts = []
        in_quote = False
        quote_char = None
        current = []
        
        for char in text:
            if not in_quote and char in ('"', "'"):
                if current:
                    parts.append(''.join(current).lower())
                    current = []
                in_quote = True
                quote_char = char
                parts.append(char)
            elif in_quote and char == quote_char:
                parts.append(''.join(current))
                parts.append(char)
                current = []
                in_quote = False
                quote_char = None
            else:
                current.append(char)
        
        if current:
            if in_quote:
                parts.append(''.join(current))
            else:
                parts.append(''.join(current).lower())
        
        return ''.join(parts)
    
    @staticmethod
    def canonicalize_upload(file_bytes: bytes, import_opts: dict[str, Any]) -> str:
        """Canonicalize upload parameters."""
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        opts_canonical = Canonicalizer.normalize_json(import_opts)
        return f"{file_hash}|{opts_canonical}"
    
    @staticmethod
    def canonicalize_assembly(bom: list[dict], constraints: list[dict], placements: list[dict]) -> str:
        """Canonicalize Assembly4 parameters."""
        # Sort BOM by link path
        sorted_bom = sorted(bom, key=lambda x: x.get('link_path', ''))
        # Sort constraints by type and name
        sorted_constraints = sorted(constraints, key=lambda x: (x.get('type', ''), x.get('name', '')))
        # Normalize placements to 1e-6
        normalized_placements = []
        for placement in placements:
            if isinstance(placement, dict):
                normalized = {}
                for key, value in placement.items():
                    if isinstance(value, (float, int)):
                        normalized[key] = round(float(value), 6)
                    else:
                        normalized[key] = value
                normalized_placements.append(normalized)
        
        return Canonicalizer.normalize_json({
            'bom': sorted_bom,
            'constraints': sorted_constraints,
            'placements': normalized_placements
        })


class CacheKeyGenerator:
    """Generate deterministic cache keys."""
    
    def __init__(self, engine_fingerprint: EngineFingerprint):
        self.engine_fingerprint = engine_fingerprint
        self.engine_str = engine_fingerprint.to_string()
    
    def generate_key(
        self,
        flow_type: CacheFlowType,
        canonical_data: str,
        artifact_type: str = "data"
    ) -> str:
        """
        Generate cache key in format:
        mgf:v2:{engine}:flow:{flow_type}:{artifact_type}:{hash}
        """
        # Combine engine fingerprint with canonical data
        combined = f"{self.engine_str}|{canonical_data}"
        
        # Generate SHA256 hash and encode as base64 (for URL safety)
        hash_bytes = hashlib.sha256(combined.encode('utf-8')).digest()
        # Use full base64 URL-safe encoding for collision resistance
        # Full SHA256 = 256 bits = 32 bytes = ~43 chars in base64
        hash_b64 = base64.urlsafe_b64encode(hash_bytes).decode('ascii').rstrip('=')
        
        # Build key using full engine string and full hash for collision resistance
        # Keep key reasonable by using abbreviations but preserve uniqueness
        key = f"mgf:v2:{self.engine_str}:f:{flow_type.value}:a:{artifact_type}:{hash_b64}"
        
        return key
    
    def generate_tag_key(self) -> str:
        """Generate tag key for this engine fingerprint."""
        return f"mgf:tag:{self.engine_str}"
    
    def generate_lock_key(self, cache_key: str) -> str:
        """Generate lock key for stampede control."""
        return f"mgf:lock:{cache_key}"


class InFlightCoalescer:
    """Coalesce concurrent identical requests per worker."""
    
    def __init__(self):
        self._requests: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()
    
    async def coalesce(self, key: str, func: Callable[[], Awaitable[Any]]) -> Any:
        """Coalesce concurrent requests for the same key."""
        # Check if request already exists (follower path)
        async with self._lock:
            if key in self._requests:
                # Wait for existing request
                future = self._requests[key]
                logger.debug("Coalescing request", key=key)
                metrics.mgf_cache_coalesced_total.inc()
        
        # If we found an existing future, await it outside the lock
        if 'future' in locals():
            try:
                return await future
            except Exception:
                # Re-raise exception from the original request
                raise
        
        # Leader path: create new future and execute
        async with self._lock:
            # Double-check pattern in case another task became leader
            if key in self._requests:
                future = self._requests[key]
                logger.debug("Coalescing request (race condition)", key=key)
                metrics.mgf_cache_coalesced_total.inc()
        
        # If we found a future after double-check, await it outside the lock
        if 'future' in locals():
            try:
                return await future
            except Exception:
                raise
        
        # We are the leader - create future and register it
        future = asyncio.Future()
        async with self._lock:
            self._requests[key] = future
        
        try:
            # Execute function (outside of lock)
            result = await func()
            future.set_result(result)
            return result
        except Exception as e:
            future.set_exception(e)
            raise
        finally:
            # Clean up - only remove if it's our future
            async with self._lock:
                if self._requests.get(key) is future:
                    self._requests.pop(key, None)


class L1Cache:
    """In-process LRU cache (L1)."""
    
    def __init__(self, config: CacheConfig):
        self.config = config
        self._cache: dict[str, tuple[Any, float, int]] = {}  # key -> (value, timestamp, size_bytes)
        self._access_order: list[str] = []
        self._total_size_bytes = 0
        self._lock = threading.RLock()
        self._max_memory_bytes = config.l1_memory_limit_mb * 1024 * 1024
    
    def get(self, key: str) -> Any | None:
        """Get value from L1 cache."""
        with self._lock:
            if key not in self._cache:
                return None
            
            value, timestamp, size_bytes = self._cache[key]
            
            # Move to end (most recently used)
            self._access_order.remove(key)
            self._access_order.append(key)
            
            metrics.mgf_cache_hits_total.labels(cache="l1").inc()
            return value
    
    def set(self, key: str, value: Any, size_bytes: int | None = None) -> bool:
        """Set value in L1 cache."""
        if size_bytes is None:
            # Estimate size
            try:
                size_bytes = len(json.dumps(value, default=str))
            except (TypeError, OverflowError, ValueError) as e:
                logger.debug(f"Failed to estimate size for L1 cache: {e}")
                size_bytes = 1000  # Default estimate
        
        with self._lock:
            # Check if we need to evict
            while (
                (len(self._cache) >= self.config.l1_max_size or
                 self._total_size_bytes + size_bytes > self._max_memory_bytes) and
                self._access_order
            ):
                # Evict least recently used
                evict_key = self._access_order.pop(0)
                if evict_key in self._cache:
                    _, _, evict_size = self._cache[evict_key]
                    del self._cache[evict_key]
                    self._total_size_bytes -= evict_size
                    metrics.mgf_cache_evictions_total.labels(cache="l1").inc()
            
            # Add new entry
            if key in self._cache:
                # Update existing
                _, _, old_size = self._cache[key]
                self._total_size_bytes -= old_size
                self._access_order.remove(key)
            
            self._cache[key] = (value, time.time(), size_bytes)
            self._access_order.append(key)
            self._total_size_bytes += size_bytes
            
            return True
    
    def delete(self, key: str) -> bool:
        """Delete value from L1 cache."""
        with self._lock:
            if key not in self._cache:
                return False
            
            _, _, size_bytes = self._cache[key]
            del self._cache[key]
            self._access_order.remove(key)
            self._total_size_bytes -= size_bytes
            
            return True
    
    def clear(self):
        """Clear L1 cache."""
        with self._lock:
            self._cache.clear()
            self._access_order.clear()
            self._total_size_bytes = 0


class RedisCache:
    """Redis cache layer (L2) with compression and stampede control."""
    
    def __init__(self, config: CacheConfig):
        self.config = config
        self._pool = None
        self._async_pool = None
        self._compressor = None
        
        # Initialize compressor
        if config.compression_enabled:
            if ZSTD_AVAILABLE:
                self._compressor = zstd.ZstdCompressor(level=config.compression_level)
                self._decompressor = zstd.ZstdDecompressor()
                logger.info("Using zstd compression", level=config.compression_level)
            else:
                logger.warning("zstd not available, using gzip fallback")
    
    @property
    def pool(self) -> redis.ConnectionPool:
        """Get or create sync Redis connection pool."""
        if self._pool is None:
            self._pool = redis.ConnectionPool.from_url(
                self.config.redis_url,
                max_connections=self.config.redis_pool_size,
                decode_responses=self.config.redis_decode_responses
            )
        return self._pool
    
    @property
    def async_pool(self) -> redis_async.ConnectionPool:
        """Get or create async Redis connection pool."""
        if self._async_pool is None:
            self._async_pool = redis_async.ConnectionPool.from_url(
                self.config.redis_url,
                max_connections=self.config.redis_pool_size,
                decode_responses=self.config.redis_decode_responses
            )
        return self._async_pool
    
    def _compress(self, data: bytes) -> tuple[bytes, bool]:
        """Compress data if above threshold."""
        if not self.config.compression_enabled:
            return data, False
        
        if len(data) < self.config.compression_threshold_bytes:
            return data, False
        
        try:
            if ZSTD_AVAILABLE:
                compressed = self._compressor.compress(data)
            else:
                compressed = gzip.compress(data, compresslevel=6)
            
            # Only use compressed if smaller
            if len(compressed) < len(data):
                return compressed, True
        except Exception as e:
            logger.warning("Compression failed", error=str(e))
        
        return data, False
    
    def _decompress(self, data: bytes, is_compressed: bool) -> bytes:
        """Decompress data if compressed."""
        if not is_compressed:
            return data
        
        try:
            if ZSTD_AVAILABLE:
                return self._decompressor.decompress(data)
            else:
                return gzip.decompress(data)
        except Exception as e:
            logger.error("Decompression failed", error=str(e))
            raise CacheException(
                "Failed to decompress cache data",
                CacheErrorCode.COMPRESSION_ERROR,
                "Önbellek verisi açılamadı"
            )
    
    async def get(self, key: str) -> Any | None:
        """Get value from Redis with decompression."""
        try:
            async with redis_async.Redis(connection_pool=self.async_pool) as client:
                # Get value and metadata
                pipe = client.pipeline()
                pipe.get(key)
                pipe.hget(f"{key}:meta", "compressed")
                pipe.hget(f"{key}:meta", "content_type")
                results = await pipe.execute()
                
                if results[0] is None:
                    metrics.mgf_cache_misses_total.labels(cache="l2").inc()
                    return None
                
                # Decompress if needed
                is_compressed = results[1] == b"1" if results[1] else False
                data = self._decompress(results[0], is_compressed)
                
                # Deserialize based on content type
                content_type = results[2].decode() if results[2] else "json"
                if content_type == "json":
                    value = json.loads(data.decode())
                elif content_type == "bytes":
                    value = data
                else:
                    value = data.decode()
                
                metrics.mgf_cache_hits_total.labels(cache="l2").inc()
                return value
                
        except redis_async.RedisError as e:
            logger.error("Redis get failed", key=key, error=str(e))
            metrics.mgf_cache_errors_total.labels(operation="get").inc()
            return None
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        content_type: str = "json"
    ) -> bool:
        """Set value in Redis with compression and TTL."""
        try:
            # Serialize value
            if content_type == "json":
                data = json.dumps(value, default=str).encode()
            elif content_type == "bytes":
                data = value if isinstance(value, bytes) else str(value).encode()
            else:
                data = str(value).encode()
            
            # Compress if needed
            compressed_data, is_compressed = self._compress(data)
            
            async with redis_async.Redis(connection_pool=self.async_pool) as client:
                # Set value and metadata atomically
                pipe = client.pipeline()
                
                if ttl:
                    pipe.setex(key, ttl, compressed_data)
                else:
                    pipe.set(key, compressed_data)
                
                # Set metadata
                pipe.hset(f"{key}:meta", mapping={
                    "compressed": "1" if is_compressed else "0",
                    "content_type": content_type,
                    "original_size": len(data),
                    "compressed_size": len(compressed_data),
                    "timestamp": int(time.time())
                })
                
                if ttl:
                    pipe.expire(f"{key}:meta", ttl)
                
                await pipe.execute()
                
                metrics.mgf_cache_sets_total.labels(
                    cache="l2",
                    compressed=str(is_compressed)
                ).inc()
                
                return True
                
        except redis_async.RedisError as e:
            logger.error("Redis set failed", key=key, error=str(e))
            metrics.mgf_cache_errors_total.labels(operation="set").inc()
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete value from Redis."""
        try:
            async with redis_async.Redis(connection_pool=self.async_pool) as client:
                pipe = client.pipeline()
                pipe.delete(key)
                pipe.delete(f"{key}:meta")
                results = await pipe.execute()
                return results[0] > 0
        except redis_async.RedisError as e:
            logger.error("Redis delete failed", key=key, error=str(e))
            return False
    
    async def acquire_lock(self, key: str, timeout: int) -> bool:
        """Acquire singleflight lock for stampede control."""
        try:
            async with redis_async.Redis(connection_pool=self.async_pool) as client:
                # SET NX PX for atomic lock acquisition
                result = await client.set(
                    key,
                    "1",
                    nx=True,
                    px=timeout * 1000  # Convert to milliseconds
                )
                return result is not None
        except redis_async.RedisError as e:
            logger.error("Lock acquisition failed", key=key, error=str(e))
            return False
    
    async def release_lock(self, key: str):
        """Release singleflight lock."""
        try:
            async with redis_async.Redis(connection_pool=self.async_pool) as client:
                await client.delete(key)
        except redis_async.RedisError as e:
            logger.error("Lock release failed", key=key, error=str(e))
    
    async def add_to_tag(self, tag_key: str, cache_key: str):
        """Add cache key to tag set for invalidation."""
        try:
            async with redis_async.Redis(connection_pool=self.async_pool) as client:
                await client.sadd(tag_key, cache_key)
        except redis_async.RedisError as e:
            logger.error("Tag addition failed", tag_key=tag_key, error=str(e))
    
    async def invalidate_tag(self, tag_key: str) -> int:
        """Invalidate all cache keys in a tag."""
        try:
            async with redis_async.Redis(connection_pool=self.async_pool) as client:
                # Use sscan_iter for non-blocking iteration of large sets
                deleted = 0
                batch = []
                
                async for key in client.sscan_iter(tag_key):
                    batch.append(key)
                    
                    # Process batch when it reaches the configured size
                    if len(batch) >= self.config.pipeline_batch_size:
                        pipe = client.pipeline()
                        for batch_key in batch:
                            pipe.delete(batch_key)
                            pipe.delete(f"{batch_key}:meta")
                        results = await pipe.execute()
                        deleted += sum(1 for r in results[::2] if r > 0)
                        batch = []
                
                # Process remaining items in batch
                if batch:
                    pipe = client.pipeline()
                    for batch_key in batch:
                        pipe.delete(batch_key)
                        pipe.delete(f"{batch_key}:meta")
                    results = await pipe.execute()
                    deleted += sum(1 for r in results[::2] if r > 0)
                
                # Clear tag set
                await client.delete(tag_key)
                
                logger.info("Tag invalidated", tag_key=tag_key, keys_deleted=deleted)
                return deleted
                
        except redis_async.RedisError as e:
            logger.error("Tag invalidation failed", tag_key=tag_key, error=str(e))
            return 0
    
    async def close(self):
        """Close Redis connection pools."""
        if self._pool:
            self._pool.disconnect()
        if self._async_pool:
            await self._async_pool.disconnect()


class CacheManager:
    """Main cache manager with two-tier caching and stampede control."""
    
    def __init__(self, config: CacheConfig | None = None):
        self.config = config or CacheConfig.from_env()
        self.l1_cache = L1Cache(self.config)
        self.l2_cache = RedisCache(self.config)
        self.coalescer = InFlightCoalescer()
        self._engine_fingerprint = None
        self._key_generator = None
    
    @property
    def engine_fingerprint(self) -> EngineFingerprint:
        """Get or create engine fingerprint."""
        if self._engine_fingerprint is None:
            # Get FreeCAD version info
            try:
                import FreeCAD
                fc_version = FreeCAD.Version()[0]  # Major version
                # Note: OCCT version would need to be extracted from FreeCAD build info
                occt_version = "7.8.1"  # Default for FreeCAD 1.1.0
            except ImportError:
                fc_version = "1.1.0"
                occt_version = "7.8.1"
            
            # Get Python version
            py_version = f"{sys.version_info.major}.{sys.version_info.minor}"
            
            # Get git SHA - prefer environment variable to avoid subprocess calls
            git_sha = os.environ.get("GIT_SHA", "unknown")
            # Only fallback to subprocess if we're in a synchronous context during initialization
            # This is cached once per worker, so the blocking call only happens once
            if git_sha == "unknown":
                try:
                    # Since this is called during worker initialization (not in async context),
                    # subprocess.run is acceptable here. For runtime async calls, the cached
                    # fingerprint will be used without any subprocess calls.
                    result = subprocess.run(
                        ["git", "rev-parse", "HEAD"],
                        capture_output=True,
                        text=True,
                        timeout=1
                    )
                    if result.returncode == 0:
                        git_sha = result.stdout.strip()
                        # Cache in environment for future workers
                        os.environ["GIT_SHA"] = git_sha
                except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError) as e:
                    logger.debug(f"Failed to get git SHA: {e}")
                    # Use a deterministic fallback for cache key consistency
                    git_sha = "development"
            
            self._engine_fingerprint = EngineFingerprint(
                freecad_version=fc_version,
                occt_version=occt_version,
                python_version=py_version,
                mesh_params_version="m1",
                git_sha=git_sha,
                enabled_workbenches=["Part", "Mesh", "Draft"],
                feature_flags={"localeC": True, "TopoNaming": False}
            )
        
        return self._engine_fingerprint
    
    @property
    def key_generator(self) -> CacheKeyGenerator:
        """Get cache key generator."""
        if self._key_generator is None:
            self._key_generator = CacheKeyGenerator(self.engine_fingerprint)
        return self._key_generator
    
    def get_ttl(self, flow_type: CacheFlowType) -> int:
        """Get TTL for flow type."""
        ttl_map = {
            CacheFlowType.GEOMETRY: self.config.ttl_geometry,
            CacheFlowType.EXPORT: self.config.ttl_mesh,
            CacheFlowType.AI_SUGGESTION: self.config.ttl_ai_suggestion,
            CacheFlowType.METRICS: self.config.ttl_metrics,
            CacheFlowType.DOC_TEMPLATE: self.config.ttl_doc_template,
        }
        return ttl_map.get(flow_type, self.config.ttl_default)
    
    async def get(
        self,
        flow_type: CacheFlowType,
        canonical_data: str,
        artifact_type: str = "data"
    ) -> Any | None:
        """Get value from cache (L1 -> L2)."""
        correlation_id = get_correlation_id()
        
        with create_span("cache_get", correlation_id=correlation_id) as span:
            span.set_attribute("cache.flow_type", flow_type.value)
            span.set_attribute("cache.artifact_type", artifact_type)
            
            # Generate cache key
            cache_key = self.key_generator.generate_key(flow_type, canonical_data, artifact_type)
            
            # Check L1
            value = self.l1_cache.get(cache_key)
            if value is not None:
                span.set_attribute("cache.hit", True)
                span.set_attribute("cache.tier", "l1")
                return value
            
            # Check L2
            value = await self.l2_cache.get(cache_key)
            if value is not None:
                # Populate L1
                self.l1_cache.set(cache_key, value)
                span.set_attribute("cache.hit", True)
                span.set_attribute("cache.tier", "l2")
                return value
            
            span.set_attribute("cache.hit", False)
            return None
    
    async def set(
        self,
        flow_type: CacheFlowType,
        canonical_data: str,
        value: Any,
        artifact_type: str = "data",
        ttl: int | None = None
    ) -> bool:
        """Set value in cache (L1 + L2)."""
        correlation_id = get_correlation_id()
        
        with create_span("cache_set", correlation_id=correlation_id) as span:
            span.set_attribute("cache.flow_type", flow_type.value)
            span.set_attribute("cache.artifact_type", artifact_type)
            
            # Generate cache key
            cache_key = self.key_generator.generate_key(flow_type, canonical_data, artifact_type)
            
            # Use default TTL if not specified
            if ttl is None:
                ttl = self.get_ttl(flow_type)
            
            # Set in L1
            self.l1_cache.set(cache_key, value)
            
            # Set in L2
            success = await self.l2_cache.set(cache_key, value, ttl)
            
            # Add to tag for invalidation
            if success:
                tag_key = self.key_generator.generate_tag_key()
                await self.l2_cache.add_to_tag(tag_key, cache_key)
            
            span.set_attribute("cache.set_success", success)
            return success
    
    async def get_or_compute(
        self,
        flow_type: CacheFlowType,
        canonical_data: str,
        compute_func: Callable[[], Awaitable[Any]],
        artifact_type: str = "data",
        ttl: int | None = None
    ) -> Any:
        """Get from cache or compute with stampede control."""
        correlation_id = get_correlation_id()
        
        # Coalesce concurrent requests
        cache_key = self.key_generator.generate_key(flow_type, canonical_data, artifact_type)
        
        async def _get_or_compute():
            # Try cache first
            value = await self.get(flow_type, canonical_data, artifact_type)
            if value is not None:
                return value
            
            # Acquire lock for stampede control
            lock_key = self.key_generator.generate_lock_key(cache_key)
            lock_acquired = await self.l2_cache.acquire_lock(
                lock_key,
                self.config.lock_timeout_seconds
            )
            
            if not lock_acquired:
                # Another request is computing, try to get stale value
                logger.debug("Lock not acquired, checking for stale value", cache_key=cache_key)
                
                # Check if we can serve stale
                stale_value = await self.l2_cache.get(f"{cache_key}:stale")
                if stale_value is not None:
                    metrics.mgf_cache_stale_served_total.inc()
                    logger.info("Serving stale value", cache_key=cache_key)
                    return stale_value
                
                # Polling loop with exponential backoff to prevent thundering herd
                max_wait_time = self.config.lock_timeout_seconds
                wait_ms = 200  # Start with 200ms
                start_time = time.time()  # Use time.time() for accurate elapsed time tracking
                
                while True:
                    # Calculate actual elapsed time
                    elapsed_time = time.time() - start_time
                    if elapsed_time >= max_wait_time:
                        break
                    
                    # Apply multiplicative jitter: random.uniform(0.8, 1.2)
                    jitter = random.uniform(0.8, 1.2)
                    actual_wait = (wait_ms / 1000.0) * jitter  # Convert to seconds with jitter
                    
                    # Don't exceed remaining time
                    remaining_time = max_wait_time - elapsed_time
                    if actual_wait > remaining_time:
                        actual_wait = remaining_time
                    
                    await asyncio.sleep(actual_wait)
                    
                    # Check if value is now available
                    value = await self.get(flow_type, canonical_data, artifact_type)
                    if value is not None:
                        final_elapsed = time.time() - start_time
                        logger.debug(f"Value available after {final_elapsed:.1f}s wait", cache_key=cache_key)
                        return value
                    
                    # Exponential backoff: wait_ms * 2, cap at 1000ms (1 second)
                    wait_ms = min(wait_ms * 2, 1000)
                
                # Timeout reached, raise exception instead of computing
                final_elapsed = time.time() - start_time
                logger.warning(f"Lock wait timeout after {final_elapsed:.1f}s", cache_key=cache_key)
                raise CacheException(
                    f"Cache lock timeout after {final_elapsed:.1f}s",
                    CacheErrorCode.LOCK_TIMEOUT,
                    f"Önbellek kilidi {final_elapsed:.1f} saniye sonra zaman aşımına uğradı",
                    {"cache_key": cache_key, "wait_time": final_elapsed}
                )
            
            try:
                # Double-check cache (another request might have computed)
                value = await self.get(flow_type, canonical_data, artifact_type)
                if value is not None:
                    return value
                
                # Compute value
                logger.info("Computing value", flow_type=flow_type.value)
                start_time = time.time()
                
                value = await compute_func()
                
                compute_time = time.time() - start_time
                metrics.mgf_compute_seconds.labels(
                    flow=flow_type.value,
                    warm="false"
                ).observe(compute_time)
                
                # Store in cache
                await self.set(flow_type, canonical_data, value, artifact_type, ttl)
                
                # Store stale copy for future use
                await self.l2_cache.set(
                    f"{cache_key}:stale",
                    value,
                    self.config.stale_while_revalidate_seconds,
                    "json"
                )
                
                return value
                
            finally:
                if lock_acquired:
                    await self.l2_cache.release_lock(lock_key)
        
        # Use coalescer to handle concurrent identical requests
        return await self.coalescer.coalesce(cache_key, _get_or_compute)
    
    async def invalidate_engine(self, old_fingerprint: EngineFingerprint | None = None):
        """Invalidate all cache entries for an engine fingerprint."""
        if old_fingerprint:
            old_generator = CacheKeyGenerator(old_fingerprint)
            tag_key = old_generator.generate_tag_key()
        else:
            tag_key = self.key_generator.generate_tag_key()
        
        deleted = await self.l2_cache.invalidate_tag(tag_key)
        
        # Clear L1 as well
        self.l1_cache.clear()
        
        logger.info("Engine cache invalidated", tag_key=tag_key, deleted=deleted)
        return deleted
    
    async def close(self):
        """Close cache connections."""
        await self.l2_cache.close()


# Global cache manager instance
_cache_manager: CacheManager | None = None


def get_cache_manager() -> CacheManager:
    """Get or create global cache manager."""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager


# Add Prometheus metrics
if not hasattr(metrics, 'mgf_cache_hits_total'):
    from prometheus_client import Counter, Histogram, Gauge
    
    metrics.mgf_cache_hits_total = Counter(
        'mgf_cache_hits_total',
        'Total number of cache hits',
        ['cache']  # l1, l2, geom, export, metrics, ai
    )
    
    metrics.mgf_cache_misses_total = Counter(
        'mgf_cache_misses_total',
        'Total number of cache misses',
        ['cache']
    )
    
    metrics.mgf_cache_sets_total = Counter(
        'mgf_cache_sets_total',
        'Total number of cache sets',
        ['cache', 'compressed']
    )
    
    metrics.mgf_cache_errors_total = Counter(
        'mgf_cache_errors_total',
        'Total number of cache errors',
        ['operation']
    )
    
    metrics.mgf_cache_evictions_total = Counter(
        'mgf_cache_evictions_total',
        'Total number of cache evictions',
        ['cache']
    )
    
    metrics.mgf_cache_stale_served_total = Counter(
        'mgf_cache_stale_served_total',
        'Total number of stale values served'
    )
    
    metrics.mgf_cache_coalesced_total = Counter(
        'mgf_cache_coalesced_total',
        'Total number of coalesced requests'
    )
    
    metrics.mgf_compute_seconds = Histogram(
        'mgf_compute_seconds',
        'Time to compute cache misses',
        ['flow', 'warm'],
        buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0)
    )
    
    metrics.mgf_cache_get_seconds = Histogram(
        'mgf_cache_get_seconds',
        'Time to get from cache',
        ['tier'],
        buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
    )
    
    metrics.mgf_cache_set_seconds = Histogram(
        'mgf_cache_set_seconds',
        'Time to set in cache',
        ['tier'],
        buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
    )
    
    metrics.mgf_cache_keys = Gauge(
        'mgf_cache_keys',
        'Number of keys in cache',
        ['cache']
    )