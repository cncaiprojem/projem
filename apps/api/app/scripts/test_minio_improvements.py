#!/usr/bin/env python
"""
Smoke test for MinIO configuration improvements.

Tests the enhanced MinIO client configuration and S3 service
with real connections to verify all improvements work correctly.

Run with: python -m app.scripts.test_minio_improvements
"""

import asyncio
import io
import logging
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.core.minio_config import (
    MinIOClientFactory,
    get_minio_client,
    validate_object_key,
    StorageErrorCode,
)
from app.services.s3_service import S3Service, get_s3_service_async
from app.schemas.file_schemas import BucketType

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_object_key_validation():
    """Test object key validation function."""
    logger.info("Testing object key validation...")
    
    # Test valid keys
    valid_keys = [
        "file.txt",
        "path/to/file.pdf",
        "2024/01/15/document.doc",
        "job_123/model.stl"
    ]
    
    for key in valid_keys:
        try:
            sanitized = validate_object_key(key)
            logger.info(f"✓ Valid key: {key} -> {sanitized}")
        except ValueError as e:
            logger.error(f"✗ Unexpected error for {key}: {e}")
            return False
    
    # Test invalid keys
    invalid_keys = [
        "",  # Empty
        "../../../etc/passwd",  # Path traversal
        "file<name>.txt",  # Invalid character
        "file\x00name.txt",  # Control character
        "a" * 1025,  # Too long
    ]
    
    for key in invalid_keys:
        try:
            validate_object_key(key)
            logger.error(f"✗ Should have rejected: {key}")
            return False
        except ValueError as e:
            logger.info(f"✓ Correctly rejected: {key} - {str(e)[:50]}")
    
    logger.info("Object key validation tests passed!")
    return True


def test_minio_client_singleton():
    """Test MinIO client singleton pattern."""
    logger.info("Testing MinIO client singleton...")
    
    try:
        # Get client multiple times
        client1 = get_minio_client()
        client2 = get_minio_client()
        
        # Should be same instance
        if client1 is not client2:
            logger.error("✗ Client instances are not the same!")
            return False
        
        logger.info("✓ Singleton pattern working correctly")
        
        # Test force new
        client3 = MinIOClientFactory.get_client(force_new=True)
        logger.info("✓ Force new client creation successful")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Client singleton test failed: {e}")
        return False


def test_minio_connection():
    """Test MinIO connection with retry logic."""
    logger.info("Testing MinIO connection...")
    
    try:
        client = get_minio_client()
        
        # Try to list buckets as connection test
        buckets = client.list_buckets()
        logger.info(f"✓ Connected to MinIO, found {len(buckets)} buckets")
        
        for bucket in buckets[:5]:  # Show first 5
            logger.info(f"  - {bucket.name}")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Connection test failed: {e}")
        return False


async def test_s3_service_operations():
    """Test S3 service operations."""
    logger.info("Testing S3 service operations...")
    
    try:
        async with get_s3_service_async() as s3:
            # Test 1: Upload small file
            test_content = b"Test content for MinIO improvements"
            test_stream = io.BytesIO(test_content)
            
            object_key, presigned_url = await s3.upload_file_stream(
                file_stream=test_stream,
                bucket="temp",
                filename="test_improvements.txt",
                metadata={"test": "true", "timestamp": str(time.time())}
            )
            
            logger.info(f"✓ Uploaded file: {object_key}")
            logger.info(f"  Presigned URL: {presigned_url.url[:50]}...")
            
            # Test 2: Download file
            download_stream = await s3.download_file_stream(
                bucket="temp",
                object_key=object_key
            )
            
            with download_stream as stream:
                downloaded_content = stream.read()
            
            if downloaded_content == test_content:
                logger.info("✓ Downloaded content matches uploaded")
            else:
                logger.error("✗ Downloaded content mismatch!")
                return False
            
            # Test 3: Get object info
            info = await s3.get_object_info(
                bucket="temp",
                object_key=object_key
            )
            
            if info:
                logger.info(f"✓ Object info retrieved: size={info.size}, type={info.content_type}")
            else:
                logger.error("✗ Failed to get object info")
                return False
            
            # Test 4: List objects
            objects = await s3.list_objects(
                bucket="temp",
                max_results=10
            )
            
            logger.info(f"✓ Listed {len(objects)} objects in temp bucket")
            
            # Test 5: Delete object
            deleted = await s3.delete_object(
                bucket="temp",
                object_key=object_key
            )
            
            if deleted:
                logger.info(f"✓ Deleted test object: {object_key}")
            else:
                logger.warning(f"⚠ Could not delete test object: {object_key}")
            
            return True
            
    except Exception as e:
        logger.error(f"✗ S3 service test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_streaming_large_file():
    """Test streaming for large files."""
    logger.info("Testing large file streaming...")
    
    try:
        async with get_s3_service_async() as s3:
            # Create a 10MB test file
            large_size = 10 * 1024 * 1024
            large_content = b"X" * large_size
            large_stream = io.BytesIO(large_content)
            
            logger.info(f"Uploading {large_size / 1024 / 1024:.1f}MB file...")
            start_time = time.time()
            
            object_key, _ = await s3.upload_file_stream(
                file_stream=large_stream,
                bucket="temp",
                filename="large_test.bin"
            )
            
            upload_time = time.time() - start_time
            logger.info(f"✓ Large file uploaded in {upload_time:.2f}s")
            
            # Download and verify size
            start_time = time.time()
            download_stream = await s3.download_file_stream(
                bucket="temp",
                object_key=object_key
            )
            
            with download_stream as stream:
                downloaded_size = len(stream.read())
            
            download_time = time.time() - start_time
            logger.info(f"✓ Large file downloaded in {download_time:.2f}s")
            
            if downloaded_size == large_size:
                logger.info(f"✓ Size verification passed: {downloaded_size} bytes")
            else:
                logger.error(f"✗ Size mismatch: expected {large_size}, got {downloaded_size}")
                return False
            
            # Cleanup
            await s3.delete_object("temp", object_key)
            logger.info("✓ Cleaned up large test file")
            
            return True
            
    except Exception as e:
        logger.error(f"✗ Large file streaming test failed: {e}")
        return False


def test_error_handling():
    """Test error handling with Turkish messages."""
    logger.info("Testing error handling...")
    
    try:
        s3 = S3Service()
        
        # Test downloading non-existent file
        try:
            asyncio.run(s3.download_file_stream(
                bucket="temp",
                object_key="nonexistent_file.txt"
            ))
            logger.error("✗ Should have raised error for non-existent file")
            return False
        except Exception as e:
            if hasattr(e, 'turkish_message'):
                logger.info(f"✓ Turkish error message: {e.turkish_message}")
            else:
                logger.info(f"✓ Error caught: {str(e)[:50]}")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Error handling test failed: {e}")
        return False


async def main():
    """Run all tests."""
    logger.info("=" * 60)
    logger.info("MinIO Configuration Improvements Test Suite")
    logger.info("=" * 60)
    
    all_passed = True
    
    # Test 1: Object key validation
    if not test_object_key_validation():
        all_passed = False
    
    logger.info("-" * 60)
    
    # Test 2: Client singleton
    if not test_minio_client_singleton():
        all_passed = False
    
    logger.info("-" * 60)
    
    # Test 3: MinIO connection
    if not test_minio_connection():
        all_passed = False
    
    logger.info("-" * 60)
    
    # Test 4: S3 service operations
    if not await test_s3_service_operations():
        all_passed = False
    
    logger.info("-" * 60)
    
    # Test 5: Large file streaming
    if not await test_streaming_large_file():
        all_passed = False
    
    logger.info("-" * 60)
    
    # Test 6: Error handling
    if not test_error_handling():
        all_passed = False
    
    logger.info("=" * 60)
    
    if all_passed:
        logger.info("✅ All tests passed successfully!")
        logger.info("MinIO improvements are working correctly.")
    else:
        logger.error("❌ Some tests failed. Please review the output above.")
    
    logger.info("=" * 60)
    
    # Cleanup
    MinIOClientFactory.reset()
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)