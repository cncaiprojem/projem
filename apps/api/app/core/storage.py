"""
Singleton storage client dependency for FastAPI.

Provides a singleton storage client instance that is initialized once
at application startup to avoid redundant bucket initialization.
"""

from functools import lru_cache
from typing import Optional

from app.services.storage_client import StorageClient
import structlog

logger = structlog.get_logger(__name__)


class StorageManager:
    """Manages singleton storage client and bucket initialization."""
    
    _instance: Optional['StorageManager'] = None
    _storage_client: Optional[StorageClient] = None
    _initialized: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(StorageManager, cls).__new__(cls)
        return cls._instance
    
    def get_storage_client(self) -> StorageClient:
        """Get or create storage client instance."""
        if self._storage_client is None:
            self._storage_client = StorageClient()
        return self._storage_client
    
    async def initialize_buckets(self) -> None:
        """Initialize all required buckets with versioning and lifecycle rules."""
        if self._initialized:
            logger.info("Buckets already initialized, skipping")
            return
            
        storage_client = self.get_storage_client()
        default_bucket = "artefacts"
        
        try:
            # Enable versioning
            storage_client.enable_bucket_versioning(default_bucket)
            
            # Setup lifecycle rules
            storage_client.setup_lifecycle_rules(default_bucket)
            
            # Set private bucket policy
            storage_client.set_bucket_policy_private(default_bucket)
            
            self._initialized = True
            logger.info("Bucket initialized successfully", bucket=default_bucket)
            
        except Exception as e:
            logger.error(
                "Failed to initialize bucket",
                bucket=default_bucket,
                error=str(e),
            )
            # Don't mark as initialized on error - will retry on next startup
            raise RuntimeError(f"Failed to initialize storage bucket: {str(e)}")
    
    def reset(self) -> None:
        """Reset the storage manager (mainly for testing)."""
        self._storage_client = None
        self._initialized = False


# Singleton instance
storage_manager = StorageManager()


@lru_cache()
def get_storage_client() -> StorageClient:
    """
    FastAPI dependency to get singleton storage client.
    
    Returns:
        StorageClient: Singleton storage client instance
    """
    return storage_manager.get_storage_client()


async def initialize_storage() -> None:
    """
    Initialize storage buckets at application startup.
    Should be called in the FastAPI lifespan context manager.
    """
    await storage_manager.initialize_buckets()