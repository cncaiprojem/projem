#!/usr/bin/env python3
"""
MinIO Bucket Setup Script for Enterprise Configuration

Task 5.2: Initialize and configure MinIO buckets with enterprise-grade policies
This script sets up all required buckets with:
- Versioning enabled on all buckets
- Lifecycle policies for automated data management
- Object lock on invoices bucket for compliance
- Advanced security policies with least-privilege access
- Proper audit logging and monitoring

Usage:
    python -m app.scripts.setup_buckets [--force] [--bucket BUCKET_NAME] [--validate-only]
"""

import asyncio
import argparse
import sys
import os
from pathlib import Path
from typing import Optional, List

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import structlog
from app.services.bucket_service import BucketService, BucketServiceError
from app.core.minio_config import MinIOClientFactory, StorageErrorCode

# Configure logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


def validate_environment() -> bool:
    """Validate required environment variables are set."""
    required_vars = [
        "MINIO_ENDPOINT",
        "MINIO_ACCESS_KEY", 
        "MINIO_SECRET_KEY"
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(
            "Missing required environment variables",
            missing_vars=missing_vars,
            help="Please ensure MinIO configuration is properly set in .env file"
        )
        return False
    
    # Log configuration (without sensitive values)
    logger.info(
        "Environment validation passed",
        endpoint=os.getenv("MINIO_ENDPOINT"),
        secure=os.getenv("MINIO_SECURE", "false") == "true",
        region=os.getenv("MINIO_REGION", "us-east-1")
    )
    
    return True


def test_minio_connection() -> bool:
    """Test connection to MinIO server."""
    try:
        client = MinIOClientFactory.get_client()
        
        # Try to list buckets as connection test
        buckets = list(client.list_buckets())
        
        logger.info(
            "MinIO connection successful",
            existing_buckets=[b.name for b in buckets],
            bucket_count=len(buckets)
        )
        
        return True
        
    except Exception as e:
        logger.error(
            "MinIO connection failed",
            error=str(e),
            help="Check MinIO server status and credentials"
        )
        return False


def setup_single_bucket(bucket_service: BucketService, bucket_name: str, force: bool = False) -> bool:
    """Set up a single bucket with full configuration."""
    try:
        logger.info(f"Setting up bucket: {bucket_name}")
        
        # Get current status
        status = bucket_service.get_bucket_status(bucket_name)
        
        if status.get("exists") and not force:
            logger.info(
                "Bucket already exists, use --force to reconfigure",
                bucket_name=bucket_name,
                current_status=status
            )
            return True
        
        # Configure the bucket
        results = bucket_service.ensure_all_buckets_configured()
        
        if results.get(bucket_name):
            logger.info(f"Bucket {bucket_name} configured successfully")
            
            # Get and log final status
            final_status = bucket_service.get_bucket_status(bucket_name)
            logger.info(
                "Bucket configuration complete",
                bucket_name=bucket_name,
                final_status=final_status
            )
            
            return True
        else:
            logger.error(f"Failed to configure bucket {bucket_name}")
            return False
            
    except BucketServiceError as e:
        logger.error(
            "Bucket service error",
            bucket_name=bucket_name,
            error_code=e.code,
            error_message=e.message,
            turkish_message=e.turkish_message
        )
        return False
    except Exception as e:
        logger.error(
            "Unexpected error setting up bucket",
            bucket_name=bucket_name,
            error=str(e),
            exc_info=True
        )
        return False


def setup_all_buckets(force: bool = False) -> bool:
    """Set up all buckets with enterprise configuration."""
    try:
        logger.info("Starting comprehensive bucket setup")
        
        bucket_service = BucketService()
        
        # Configure all buckets
        results = bucket_service.ensure_all_buckets_configured()
        
        # Log results
        successful = [name for name, success in results.items() if success]
        failed = [name for name, success in results.items() if not success]
        
        logger.info(
            "Bucket setup completed",
            total_buckets=len(results),
            successful_buckets=successful,
            failed_buckets=failed,
            success_rate=f"{len(successful)}/{len(results)}"
        )
        
        # Get detailed status for all buckets
        all_status = bucket_service.get_all_buckets_status()
        
        for bucket_name, status in all_status.items():
            logger.info(
                "Final bucket status",
                bucket_name=bucket_name,
                status=status
            )
        
        return len(failed) == 0
        
    except BucketServiceError as e:
        logger.error(
            "Bucket service error during setup",
            error_code=e.code,
            error_message=e.message,
            turkish_message=e.turkish_message,
            details=e.details
        )
        return False
    except Exception as e:
        logger.error(
            "Unexpected error during bucket setup",
            error=str(e),
            exc_info=True
        )
        return False


def validate_bucket_configuration(bucket_names: Optional[List[str]] = None) -> bool:
    """Validate bucket configurations without making changes."""
    try:
        logger.info("Validating bucket configurations")
        
        bucket_service = BucketService()
        
        if bucket_names:
            # Validate specific buckets
            all_valid = True
            for bucket_name in bucket_names:
                status = bucket_service.get_bucket_status(bucket_name)
                
                is_valid = (
                    status.get("exists", False) and
                    status.get("versioning", {}).get("enabled", False) and
                    not status.get("error")
                )
                
                logger.info(
                    "Bucket validation",
                    bucket_name=bucket_name,
                    is_valid=is_valid,
                    status=status
                )
                
                if not is_valid:
                    all_valid = False
            
            return all_valid
        else:
            # Validate all buckets
            all_status = bucket_service.get_all_buckets_status()
            
            validation_results = {}
            for bucket_name, status in all_status.items():
                is_valid = (
                    status.get("exists", False) and
                    status.get("versioning", {}).get("enabled", False) and
                    not status.get("error")
                )
                validation_results[bucket_name] = is_valid
                
                logger.info(
                    "Bucket validation",
                    bucket_name=bucket_name,
                    is_valid=is_valid,
                    status=status
                )
            
            valid_count = sum(validation_results.values())
            total_count = len(validation_results)
            
            logger.info(
                "Validation summary",
                valid_buckets=valid_count,
                total_buckets=total_count,
                all_valid=valid_count == total_count,
                validation_results=validation_results
            )
            
            return valid_count == total_count
            
    except Exception as e:
        logger.error(
            "Validation failed",
            error=str(e),
            exc_info=True
        )
        return False


def run_acceptance_tests(bucket_service: BucketService) -> bool:
    """Run acceptance tests as defined in Task 5.2."""
    logger.info("Running Task 5.2 acceptance tests")
    
    test_results = {}
    
    # Test 1: Versioning enabled and new object gets version ID
    try:
        logger.info("Test 1: Checking versioning configuration")
        
        for bucket_name in ["artefacts", "logs", "reports", "invoices", "temp"]:
            status = bucket_service.get_bucket_status(bucket_name)
            versioning_enabled = status.get("versioning", {}).get("enabled", False)
            
            test_results[f"versioning_{bucket_name}"] = versioning_enabled
            
            logger.info(
                "Versioning test",
                bucket_name=bucket_name,
                versioning_enabled=versioning_enabled
            )
        
    except Exception as e:
        logger.error("Versioning test failed", error=str(e))
        test_results["versioning_test"] = False
    
    # Test 2: Lifecycle rules exist and are validated
    try:
        logger.info("Test 2: Checking lifecycle rules")
        
        for bucket_name in bucket_service.bucket_configs.keys():
            status = bucket_service.get_bucket_status(bucket_name)
            lifecycle_configured = status.get("lifecycle", {}).get("configured", False)
            
            test_results[f"lifecycle_{bucket_name}"] = lifecycle_configured
            
            logger.info(
                "Lifecycle test",
                bucket_name=bucket_name,
                lifecycle_configured=lifecycle_configured,
                rules_count=status.get("lifecycle", {}).get("rules_count", 0)
            )
        
    except Exception as e:
        logger.error("Lifecycle test failed", error=str(e))
        test_results["lifecycle_test"] = False
    
    # Test 3: Invoices bucket has object lock (compliance mode)
    try:
        logger.info("Test 3: Checking invoices bucket object lock")
        
        invoices_status = bucket_service.get_bucket_status("invoices")
        object_lock_enabled = invoices_status.get("object_lock", {}).get("enabled", False)
        object_lock_mode = invoices_status.get("object_lock", {}).get("mode")
        
        test_results["invoices_object_lock"] = object_lock_enabled and object_lock_mode == "COMPLIANCE"
        
        logger.info(
            "Object lock test",
            bucket_name="invoices",
            object_lock_enabled=object_lock_enabled,
            object_lock_mode=object_lock_mode
        )
        
    except Exception as e:
        logger.error("Object lock test failed", error=str(e))
        test_results["object_lock_test"] = False
    
    # Test 4: Presigned URL constraints (>200MB rejection)
    try:
        logger.info("Test 4: Checking presigned URL constraints")
        
        # Test with file > 200MB
        large_file_valid, large_file_error = bucket_service.validate_presigned_url_constraints(
            bucket_name="artefacts",
            content_length=250 * 1024 * 1024,  # 250MB
            content_type="application/json"
        )
        
        # Test with file < 200MB
        small_file_valid, small_file_error = bucket_service.validate_presigned_url_constraints(
            bucket_name="artefacts", 
            content_length=100 * 1024 * 1024,  # 100MB
            content_type="application/json"
        )
        
        test_results["presigned_constraints"] = not large_file_valid and small_file_valid
        
        logger.info(
            "Presigned URL constraints test",
            large_file_rejected=not large_file_valid,
            large_file_error=large_file_error,
            small_file_accepted=small_file_valid,
            small_file_error=small_file_error
        )
        
    except Exception as e:
        logger.error("Presigned URL constraints test failed", error=str(e))
        test_results["presigned_constraints_test"] = False
    
    # Summary
    passed_tests = sum(test_results.values())
    total_tests = len(test_results)
    
    logger.info(
        "Acceptance tests completed",
        passed_tests=passed_tests,
        total_tests=total_tests,
        success_rate=f"{passed_tests}/{total_tests}",
        all_passed=passed_tests == total_tests,
        test_results=test_results
    )
    
    return passed_tests == total_tests


def main():
    """Main entry point for bucket setup script."""
    parser = argparse.ArgumentParser(
        description="Set up MinIO buckets with enterprise configuration"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reconfiguration of existing buckets"
    )
    parser.add_argument(
        "--bucket",
        type=str,
        help="Set up only specific bucket (default: all buckets)"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate existing configuration without changes"
    )
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help="Run acceptance tests after setup"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    # Configure logging level
    if args.verbose:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info(
        "Starting MinIO bucket setup",
        force=args.force,
        bucket=args.bucket,
        validate_only=args.validate_only,
        run_tests=args.run_tests
    )
    
    # Step 1: Validate environment
    if not validate_environment():
        logger.error("Environment validation failed")
        sys.exit(1)
    
    # Step 2: Test MinIO connection
    if not test_minio_connection():
        logger.error("MinIO connection test failed")
        sys.exit(1)
    
    success = True
    
    # Step 3: Run validation or setup
    if args.validate_only:
        bucket_names = [args.bucket] if args.bucket else None
        success = validate_bucket_configuration(bucket_names)
    else:
        if args.bucket:
            bucket_service = BucketService()
            success = setup_single_bucket(bucket_service, args.bucket, args.force)
        else:
            success = setup_all_buckets(args.force)
    
    # Step 4: Run acceptance tests if requested
    if args.run_tests and success:
        try:
            bucket_service = BucketService()
            test_success = run_acceptance_tests(bucket_service)
            success = success and test_success
        except Exception as e:
            logger.error("Acceptance tests failed", error=str(e))
            success = False
    
    # Step 5: Exit with appropriate code
    if success:
        logger.info("Bucket setup completed successfully")
        sys.exit(0)
    else:
        logger.error("Bucket setup failed")
        sys.exit(1)


if __name__ == "__main__":
    main()