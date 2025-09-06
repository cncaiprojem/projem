"""
Test suite for Task 7.13: Performance Tuning and Caching Strategy

Tests:
- Cache key generation with engine fingerprint
- Two-tier caching (L1 + L2)
- Canonicalization and normalization
- Compression with zstd
- Stampede control and coalescing
- Cache invalidation
- Performance benchmarks
"""

import asyncio
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis.asyncio as redis_async

# Optional: freezegun for time-based tests
try:
    from freezegun import freeze_time
except ImportError:
    freeze_time = None

from apps.api.app.core.cache import (
    CacheConfig,
    CacheManager,
    CacheFlowType,
    CacheKeyGenerator,
    Canonicalizer,
    EngineFingerprint,
    L1Cache,
    RedisCache,
    InFlightCoalescer,
    get_cache_manager
)


@pytest.fixture
async def redis_test_client():
    """Provide isolated Redis client for testing."""
    import redis
    import random
    
    # Use a random database number for test isolation
    test_db = random.randint(10, 15)
    
    try:
        # Test connection
        sync_client = redis.Redis(host='localhost', port=6379, db=test_db)
        sync_client.ping()
        
        # Create async client
        async_client = redis_async.Redis(host='localhost', port=6379, db=test_db)
        
        # Clear database before test
        await async_client.flushdb()
        
        yield async_client
        
        # Cleanup after test
        await async_client.flushdb()
        await async_client.close()
        
    except (redis.ConnectionError, redis.RedisError, ImportError) as e:
        pytest.skip(f"Redis not available for testing: {e}")


@pytest.fixture
def cache_config(redis_test_client):
    """Provide test cache configuration."""
    return CacheConfig(
        redis_url=f"redis://localhost:6379/{redis_test_client.connection_pool.connection_kwargs['db']}",
        l1_max_size=10,
        l1_memory_limit_mb=10,
        compression_enabled=True,
        compression_threshold_bytes=100
    )


class TestEngineFingerprint:
    """Test engine fingerprint generation."""
    
    def test_fingerprint_string_generation(self):
        """Test fingerprint string is deterministic."""
        fingerprint = EngineFingerprint(
            freecad_version="1.1.0",
            occt_version="7.8.1",
            python_version="3.11",
            mesh_params_version="m1",
            git_sha="abcd123efgh456",
            enabled_workbenches=["Part", "Mesh", "Draft"],
            feature_flags={"localeC": True, "TopoNaming": False}
        )
        
        result = fingerprint.to_string()
        
        # Check format
        assert "fc{1.1.0}" in result
        assert "occt{7.8.1}" in result
        assert "py{3.11}" in result
        assert "mesh{m1}" in result
        assert "git{abcd123}" in result  # Should truncate to 7 chars
        assert "wb{Draft,Mesh,Part}" in result  # Should be sorted
        assert "flags{TopoNaming=False,localeC=True}" in result  # Should be sorted
    
    def test_fingerprint_uniqueness(self):
        """Test that different configurations produce different fingerprints."""
        fp1 = EngineFingerprint(
            freecad_version="1.1.0",
            occt_version="7.8.1",
            python_version="3.11",
            mesh_params_version="m1",
            git_sha="abcd123",
            enabled_workbenches=["Part"],
            feature_flags={}
        )
        
        fp2 = EngineFingerprint(
            freecad_version="1.1.0",
            occt_version="7.8.2",  # Different OCCT
            python_version="3.11",
            mesh_params_version="m1",
            git_sha="abcd123",
            enabled_workbenches=["Part"],
            feature_flags={}
        )
        
        assert fp1.to_string() != fp2.to_string()


class TestCanonicalizer:
    """Test parameter canonicalization."""
    
    def test_normalize_json_basic(self):
        """Test basic JSON normalization."""
        data = {
            "b": 2,
            "a": 1,
            "c": {
                "nested": True,
                "values": [3, 1, 2]
            }
        }
        
        result = Canonicalizer.normalize_json(data)
        parsed = json.loads(result)
        
        # Keys should be sorted
        assert list(parsed.keys()) == ["a", "b", "c"]
        assert list(parsed["c"].keys()) == ["nested", "values"]
    
    def test_normalize_json_removes_empty(self):
        """Test that empty values are removed."""
        data = {
            "a": 1,
            "b": None,
            "c": "",
            "d": [],
            "e": {},
            "f": "value"
        }
        
        result = Canonicalizer.normalize_json(data)
        parsed = json.loads(result)
        
        assert "b" not in parsed
        assert "c" not in parsed
        assert "d" not in parsed
        assert "e" not in parsed
        assert parsed == {"a": 1, "f": "value"}
    
    def test_normalize_json_float_rounding(self):
        """Test float rounding to 1e-6."""
        data = {
            "precise": 1.123456789,
            "denormal": 1e-12,
            "normal": 42.0
        }
        
        result = Canonicalizer.normalize_json(data)
        parsed = json.loads(result)
        
        assert parsed["precise"] == 1.123457  # Rounded to 6 decimals
        assert parsed["denormal"] == 0.0  # Clamped
        assert parsed["normal"] == 42.0
    
    def test_normalize_json_unicode(self):
        """Test Unicode normalization."""
        data = {
            "text": "Café  \t\n  Test",  # Multiple spaces and tabs
            "unicode": "ﬁ",  # Ligature that should be normalized
        }
        
        result = Canonicalizer.normalize_json(data)
        parsed = json.loads(result)
        
        assert parsed["text"] == "Café Test"  # Collapsed whitespace
        assert parsed["unicode"] == "fi"  # NFKC normalization
    
    def test_pii_masking(self):
        """Test PII masking in prompts."""
        text = "Contact me at john@example.com or 555-123-4567"
        masked = Canonicalizer._mask_pii(text)
        
        assert "[EMAIL]" in masked
        assert "[PHONE]" in masked
        assert "john@example.com" not in masked
        assert "555-123-4567" not in masked
    
    def test_lowercase_non_quoted(self):
        """Test lowercasing except quoted strings."""
        text = 'Create a "Box Model" with SIZE parameter'
        result = Canonicalizer._lowercase_non_quoted(text)
        
        assert result == 'create a "Box Model" with size parameter'
    
    def test_canonicalize_upload(self):
        """Test upload canonicalization."""
        file_bytes = b"test file content"
        import_opts = {"format": "STEP", "tolerance": 0.001}
        
        result = Canonicalizer.canonicalize_upload(file_bytes, import_opts)
        
        # Should contain file hash and normalized options
        assert "|" in result
        parts = result.split("|")
        assert len(parts[0]) == 64  # SHA256 hex length
        assert "STEP" in parts[1]


class TestCacheKeyGenerator:
    """Test cache key generation."""
    
    def test_key_format(self):
        """Test cache key format."""
        fingerprint = EngineFingerprint(
            freecad_version="1.1.0",
            occt_version="7.8.1",
            python_version="3.11",
            mesh_params_version="m1",
            git_sha="abcd123",
            enabled_workbenches=["Part"],
            feature_flags={}
        )
        
        generator = CacheKeyGenerator(fingerprint)
        
        key = generator.generate_key(
            CacheFlowType.GEOMETRY,
            "canonical_data",
            "brep"
        )
        
        # Check key format
        assert key.startswith("mgf:v2:")
        assert ":f:geom:" in key  # Abbreviated format uses 'f:' for flow
        assert ":a:brep:" in key  # Abbreviated format uses 'a:' for artifact
        # Hash should be at the end - full base64 SHA256 is ~43 chars
        parts = key.split(":")
        assert len(parts[-1]) > 40  # Full base64 SHA256 hash (256 bits = ~43 chars in base64)
    
    def test_deterministic_keys(self):
        """Test that same inputs produce same keys."""
        fingerprint = EngineFingerprint(
            freecad_version="1.1.0",
            occt_version="7.8.1",
            python_version="3.11",
            mesh_params_version="m1",
            git_sha="abcd123",
            enabled_workbenches=["Part"],
            feature_flags={}
        )
        
        generator = CacheKeyGenerator(fingerprint)
        
        key1 = generator.generate_key(CacheFlowType.PARAMS, "data", "result")
        key2 = generator.generate_key(CacheFlowType.PARAMS, "data", "result")
        
        assert key1 == key2
    
    def test_different_engines_different_keys(self):
        """Test that different engines produce different keys."""
        fp1 = EngineFingerprint(
            freecad_version="1.1.0",
            occt_version="7.8.1",
            python_version="3.11",
            mesh_params_version="m1",
            git_sha="abcd123",
            enabled_workbenches=["Part"],
            feature_flags={}
        )
        
        fp2 = EngineFingerprint(
            freecad_version="1.1.0",
            occt_version="7.8.2",  # Different version
            python_version="3.11",
            mesh_params_version="m1",
            git_sha="abcd123",
            enabled_workbenches=["Part"],
            feature_flags={}
        )
        
        gen1 = CacheKeyGenerator(fp1)
        gen2 = CacheKeyGenerator(fp2)
        
        key1 = gen1.generate_key(CacheFlowType.PARAMS, "data", "result")
        key2 = gen2.generate_key(CacheFlowType.PARAMS, "data", "result")
        
        assert key1 != key2


class TestL1Cache:
    """Test L1 in-process cache."""
    
    def test_basic_operations(self):
        """Test get/set/delete operations."""
        config = CacheConfig(l1_max_size=10, l1_memory_limit_mb=1)
        cache = L1Cache(config)
        
        # Set value
        assert cache.set("key1", "value1")
        
        # Get value
        assert cache.get("key1") == "value1"
        
        # Delete value
        assert cache.delete("key1")
        assert cache.get("key1") is None
    
    def test_lru_eviction(self):
        """Test LRU eviction when cache is full."""
        config = CacheConfig(l1_max_size=3, l1_memory_limit_mb=1)
        cache = L1Cache(config)
        
        # Fill cache
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        
        # Access key1 to make it recently used
        cache.get("key1")
        
        # Add new key, should evict key2 (least recently used)
        cache.set("key4", "value4")
        
        assert cache.get("key1") == "value1"  # Still there
        assert cache.get("key2") is None  # Evicted
        assert cache.get("key3") == "value3"  # Still there
        assert cache.get("key4") == "value4"  # New entry
    
    def test_memory_limit_eviction(self):
        """Test eviction based on memory limit."""
        config = CacheConfig(
            l1_max_size=100,  # High limit
            l1_memory_limit_mb=0.001  # Very low memory limit (1KB)
        )
        cache = L1Cache(config)
        
        # Add large values
        large_value = "x" * 500  # 500 bytes
        cache.set("key1", large_value)
        cache.set("key2", large_value)
        cache.set("key3", large_value)
        
        # Should have evicted some entries due to memory limit
        active_keys = sum(1 for k in ["key1", "key2", "key3"] if cache.get(k) is not None)
        assert active_keys < 3  # Some should be evicted


@pytest.mark.asyncio
class TestRedisCache:
    """Test Redis cache layer."""
    
    @pytest.fixture
    async def redis_cache(self):
        """Create Redis cache instance."""
        config = CacheConfig(
            redis_url="redis://localhost:6379/15",  # Use test database
            compression_enabled=True,
            compression_threshold_bytes=100
        )
        cache = RedisCache(config)
        yield cache
        await cache.close()
    
    @patch('apps.api.app.core.cache.redis_async.Redis')
    async def test_get_miss(self, mock_redis_class):
        """Test cache miss."""
        mock_client = AsyncMock()
        mock_redis_class.return_value.__aenter__.return_value = mock_client
        
        mock_pipe = AsyncMock()
        mock_client.pipeline.return_value = mock_pipe
        mock_pipe.execute.return_value = [None, None, None]
        
        config = CacheConfig()
        cache = RedisCache(config)
        
        result = await cache.get("test_key")
        assert result is None
    
    @patch('apps.api.app.core.cache.redis_async.Redis')
    async def test_set_with_compression(self, mock_redis_class):
        """Test setting value with compression."""
        mock_client = AsyncMock()
        mock_redis_class.return_value.__aenter__.return_value = mock_client
        
        mock_pipe = AsyncMock()
        mock_client.pipeline.return_value = mock_pipe
        mock_pipe.execute.return_value = [True, True, True]
        
        config = CacheConfig(compression_enabled=True, compression_threshold_bytes=10)
        cache = RedisCache(config)
        
        # Large value that should be compressed
        large_value = {"data": "x" * 1000}
        
        result = await cache.set("test_key", large_value, ttl=3600)
        assert result is True
        
        # Check that pipeline was called
        assert mock_pipe.setex.called or mock_pipe.set.called
        assert mock_pipe.hset.called
    
    @patch('apps.api.app.core.cache.redis_async.Redis')
    async def test_stampede_control_lock(self, mock_redis_class):
        """Test singleflight lock acquisition."""
        mock_client = AsyncMock()
        mock_redis_class.return_value.__aenter__.return_value = mock_client
        
        # First call succeeds (lock acquired)
        mock_client.set.return_value = True
        
        config = CacheConfig()
        cache = RedisCache(config)
        
        acquired = await cache.acquire_lock("lock_key", timeout=10)
        assert acquired is True
        
        # Check SET NX PX was called
        mock_client.set.assert_called_with("lock_key", "1", nx=True, px=10000)


@pytest.mark.asyncio
class TestInFlightCoalescer:
    """Test request coalescing."""
    
    async def test_coalesce_concurrent_requests(self):
        """Test that concurrent requests are coalesced."""
        coalescer = InFlightCoalescer()
        call_count = 0
        
        async def expensive_func():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)  # Simulate work
            return f"result_{call_count}"
        
        # Start multiple concurrent requests
        tasks = [
            coalescer.coalesce("same_key", expensive_func)
            for _ in range(5)
        ]
        
        results = await asyncio.gather(*tasks)
        
        # All should get same result
        assert all(r == results[0] for r in results)
        # Function should only be called once
        assert call_count == 1
    
    async def test_different_keys_not_coalesced(self):
        """Test that different keys are not coalesced."""
        coalescer = InFlightCoalescer()
        call_count = 0
        
        async def func():
            nonlocal call_count
            call_count += 1
            return call_count
        
        # Different keys
        result1 = await coalescer.coalesce("key1", func)
        result2 = await coalescer.coalesce("key2", func)
        
        assert result1 == 1
        assert result2 == 2
        assert call_count == 2


@pytest.mark.asyncio
class TestCacheManager:
    """Test main cache manager."""
    
    @pytest.fixture
    async def cache_manager(self):
        """Create cache manager instance."""
        config = CacheConfig(
            redis_url="redis://localhost:6379/15",
            l1_max_size=10
        )
        manager = CacheManager(config)
        yield manager
        await manager.l2_cache.close()
    
    @patch('apps.api.app.core.cache.RedisCache.get')
    @patch('apps.api.app.core.cache.RedisCache.set')
    async def test_two_tier_caching(self, mock_redis_set, mock_redis_get, cache_manager):
        """Test L1 + L2 caching."""
        mock_redis_get.return_value = None
        mock_redis_set.return_value = True
        
        # First access - miss both tiers
        result = await cache_manager.get(CacheFlowType.GEOMETRY, "data", "brep")
        assert result is None
        
        # Set value
        await cache_manager.set(CacheFlowType.GEOMETRY, "data", "test_value", "brep")
        
        # Second access - should hit L1
        result = await cache_manager.get(CacheFlowType.GEOMETRY, "data", "brep")
        # L1 should have the value
        key = cache_manager.key_generator.generate_key(CacheFlowType.GEOMETRY, "data", "brep")
        assert cache_manager.l1_cache.get(key) == "test_value"
    
    @patch('apps.api.app.core.cache.RedisCache.get')
    @patch('apps.api.app.core.cache.RedisCache.set')
    @patch('apps.api.app.core.cache.RedisCache.acquire_lock')
    @patch('apps.api.app.core.cache.RedisCache.release_lock')
    async def test_get_or_compute(
        self,
        mock_release_lock,
        mock_acquire_lock,
        mock_redis_set,
        mock_redis_get,
        cache_manager
    ):
        """Test get_or_compute with stampede control."""
        mock_redis_get.return_value = None
        mock_redis_set.return_value = True
        mock_acquire_lock.return_value = True
        
        compute_called = False
        
        async def compute_func():
            nonlocal compute_called
            compute_called = True
            return "computed_value"
        
        result = await cache_manager.get_or_compute(
            CacheFlowType.PARAMS,
            "input_data",
            compute_func,
            "result"
        )
        
        assert result == "computed_value"
        assert compute_called is True
        assert mock_acquire_lock.called
        assert mock_release_lock.called
    
    @patch('apps.api.app.core.cache.RedisCache.invalidate_tag')
    async def test_engine_invalidation(self, mock_invalidate_tag, cache_manager):
        """Test cache invalidation on engine change."""
        mock_invalidate_tag.return_value = 10  # Deleted 10 keys
        
        # Clear L1 cache and invalidate L2
        deleted = await cache_manager.invalidate_engine()
        
        assert deleted == 10
        assert mock_invalidate_tag.called
        # L1 should be cleared
        assert len(cache_manager.l1_cache._cache) == 0


class TestPerformanceBenchmarks:
    """Performance benchmarks for cache system."""
    
    @pytest.mark.benchmark
    def test_canonicalization_performance(self, benchmark):
        """Benchmark canonicalization speed."""
        data = {
            "complex": {
                "nested": {
                    "structure": [1, 2, 3, 4, 5],
                    "with": {"many": "keys", "and": "values"}
                }
            },
            "floats": [1.123456789] * 100,
            "strings": ["test string"] * 50
        }
        
        result = benchmark(Canonicalizer.normalize_json, data)
        assert result is not None
    
    @pytest.mark.benchmark
    def test_key_generation_performance(self, benchmark):
        """Benchmark key generation speed."""
        fingerprint = EngineFingerprint(
            freecad_version="1.1.0",
            occt_version="7.8.1",
            python_version="3.11",
            mesh_params_version="m1",
            git_sha="abcd123",
            enabled_workbenches=["Part", "Mesh"],
            feature_flags={"locale": "C"}
        )
        
        generator = CacheKeyGenerator(fingerprint)
        
        result = benchmark(
            generator.generate_key,
            CacheFlowType.GEOMETRY,
            "canonical_data_string",
            "brep"
        )
        assert result.startswith("mgf:v2:")
    
    @pytest.mark.benchmark
    def test_l1_cache_performance(self, benchmark):
        """Benchmark L1 cache operations."""
        config = CacheConfig(l1_max_size=1000, l1_memory_limit_mb=10)
        cache = L1Cache(config)
        
        # Pre-populate cache
        for i in range(500):
            cache.set(f"key_{i}", f"value_{i}")
        
        def cache_operations():
            # Mix of operations
            cache.get("key_100")
            cache.set("key_999", "new_value")
            cache.get("key_200")
            cache.delete("key_999")
        
        benchmark(cache_operations)


@pytest.mark.integration
@pytest.mark.asyncio
class TestCacheIntegration:
    """Integration tests with real Redis."""
    
    async def test_full_cache_flow(self, redis_test_client, cache_config):
        """Test complete cache flow with real Redis."""
        manager = CacheManager(cache_config)
        
        try:
            # Clear any existing data
            await manager.invalidate_engine()
            
            # Test data
            test_data = {"key": "value", "number": 42}
            canonical = Canonicalizer.normalize_json(test_data)
            
            # Store in cache
            stored = await manager.set(
                CacheFlowType.PARAMS,
                canonical,
                test_data,
                "result",
                ttl=60
            )
            assert stored is True
            
            # Retrieve from cache
            retrieved = await manager.get(
                CacheFlowType.PARAMS,
                canonical,
                "result"
            )
            assert retrieved == test_data
            
            # Test get_or_compute
            compute_count = 0
            
            async def compute():
                nonlocal compute_count
                compute_count += 1
                return {"computed": True}
            
            # First call should compute
            result1 = await manager.get_or_compute(
                CacheFlowType.PARAMS,
                "compute_test",
                compute,
                "computed"
            )
            assert result1 == {"computed": True}
            assert compute_count == 1
            
            # Second call should use cache
            result2 = await manager.get_or_compute(
                CacheFlowType.PARAMS,
                "compute_test",
                compute,
                "computed"
            )
            assert result2 == {"computed": True}
            assert compute_count == 1  # Not incremented
            
        finally:
            await manager.l2_cache.close()
    
    async def test_cache_hit_rates(self, redis_test_client, cache_config):
        """Test cache hit rates meet acceptance criteria (>92%)."""
        cache_config.l1_max_size = 100  # Increase for this test
        manager = CacheManager(cache_config)
        
        try:
            # Clear cache
            await manager.invalidate_engine()
            
            # Generate test data
            test_items = []
            for i in range(100):
                data = {"item": i, "value": f"test_{i}"}
                canonical = Canonicalizer.normalize_json(data)
                test_items.append((canonical, data))
            
            # First pass - populate cache
            for canonical, data in test_items:
                await manager.set(CacheFlowType.PARAMS, canonical, data, "result")
            
            # Second pass - test hit rate
            hits = 0
            total = 0
            
            for canonical, expected_data in test_items:
                total += 1
                result = await manager.get(CacheFlowType.PARAMS, canonical, "result")
                if result == expected_data:
                    hits += 1
            
            hit_rate = hits / total
            assert hit_rate >= 0.92  # >92% hit rate
            
        finally:
            await manager.l2_cache.close()