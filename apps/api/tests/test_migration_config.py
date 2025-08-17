"""
Migration Test Configuration - Task 2.9

Configuration settings and fixtures for migration and integrity testing
with banking-level precision and Turkish compliance requirements.
"""

from __future__ import annotations

import os
import pytest
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from tests.utils.migration_test_helpers import (
    MigrationTestEnvironment,
    AuditChainValidator,
    FinancialPrecisionValidator,
    PerformanceProfiler,
    MigrationSafetyChecker,
    TestDataFactory
)


# Test configuration constants
class MigrationTestConfig:
    """Configuration constants for migration testing."""
    
    # Database settings
    BASE_DATABASE_URL = os.getenv(
        "DATABASE_URL", 
        "postgresql+psycopg2://freecad:password@localhost:5432/freecad"
    )
    
    # Performance thresholds
    SLOW_QUERY_THRESHOLD_SECONDS = 1.0
    MAX_MIGRATION_TIME_SECONDS = 30.0
    
    # Audit chain settings
    GENESIS_HASH = "0" * 64
    
    # Turkish compliance settings
    DEFAULT_CURRENCY = "TRY"
    KDV_TAX_RATE = 20  # Turkish VAT rate
    
    # Test data limits
    MAX_TEST_RECORDS = 1000
    TEST_BATCH_SIZE = 100


# Pytest fixtures for migration testing
@pytest.fixture(scope="session")
def migration_test_config():
    """Provide migration test configuration."""
    return MigrationTestConfig()


@pytest.fixture(scope="function")
def isolated_migration_env(migration_test_config):
    """
    Provide isolated migration test environment.
    
    Creates a temporary database for each test function to ensure
    complete isolation and prevent test interference.
    """
    with MigrationTestEnvironment(migration_test_config.BASE_DATABASE_URL) as (engine, alembic_config):
        yield engine, alembic_config


@pytest.fixture(scope="function")
def migration_session(isolated_migration_env) -> Generator[Session, None, None]:
    """
    Provide database session for migration testing.
    
    Uses the isolated migration environment to ensure test isolation.
    """
    engine, _ = isolated_migration_env
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(scope="function")
def audit_chain_validator():
    """Provide audit chain validator for testing cryptographic integrity."""
    return AuditChainValidator()


@pytest.fixture(scope="function")
def financial_validator():
    """Provide financial precision validator for Turkish compliance."""
    return FinancialPrecisionValidator()


@pytest.fixture(scope="function")
def performance_profiler(isolated_migration_env):
    """Provide performance profiler for query optimization testing."""
    engine, _ = isolated_migration_env
    return PerformanceProfiler(engine)


@pytest.fixture(scope="function")
def migration_safety_checker(isolated_migration_env):
    """Provide migration safety checker for enterprise deployment safety."""
    engine, _ = isolated_migration_env
    return MigrationSafetyChecker()


@pytest.fixture(scope="function")
def test_data_factory():
    """Provide test data factory for consistent test data generation."""
    return TestDataFactory()


# Specialized fixtures for specific test scenarios
@pytest.fixture(scope="function")
def turkish_compliance_data(test_data_factory):
    """
    Provide test data specifically designed for Turkish compliance testing.
    
    Includes proper Turkish phone numbers, KVKV compliance data,
    and financial data with proper KDV calculations.
    """
    return {
        "users": [
            {
                **test_data_factory.create_test_user("kvkv_test"),
                "phone": "+905551234567",  # Valid Turkish mobile
                "full_name": "KVKV Test Kullanıcısı",  # Turkish name
            },
            {
                **test_data_factory.create_test_user("gdpr_test"),
                "phone": "+905557654321",
                "full_name": "GDPR Test Kullanıcısı",
            }
        ],
        "invoices": [
            test_data_factory.create_test_invoice(1, amount_try=100.00),  # Basic invoice
            test_data_factory.create_test_invoice(2, amount_try=1250.50),  # With decimals
        ],
        "audit_payloads": [
            test_data_factory.create_test_audit_payload("USER_CREATED", 1),
            test_data_factory.create_test_audit_payload("GDPR_CONSENT", 1),
            test_data_factory.create_test_audit_payload("KVKV_DATA_REQUEST", 2),
        ]
    }


@pytest.fixture(scope="function")
def performance_test_data():
    """
    Provide test data for performance testing scenarios.
    
    Creates larger datasets to test query performance and index usage
    under realistic load conditions.
    """
    return {
        "user_count": 100,
        "job_count": 500,
        "audit_log_count": 1000,
        "batch_size": 50
    }


@pytest.fixture(scope="function")
def enterprise_security_data():
    """
    Provide test data for enterprise security testing.
    
    Includes audit logs with proper chain integrity, security events,
    and compliance-related data for banking-level security testing.
    """
    return {
        "security_events": [
            {
                "event_type": "LOGIN_ATTEMPT",
                "severity": "info",
                "metadata": {"ip": "192.168.1.100", "user_agent": "Test Browser"}
            },
            {
                "event_type": "FAILED_LOGIN",
                "severity": "warning", 
                "metadata": {"ip": "192.168.1.100", "attempts": 3}
            },
            {
                "event_type": "SUSPICIOUS_ACTIVITY",
                "severity": "critical",
                "metadata": {"pattern": "brute_force", "blocked": True}
            }
        ],
        "audit_chain_scenarios": [
            {"operation": "CREATE", "scope": "user", "critical": False},
            {"operation": "UPDATE", "scope": "user", "critical": False},
            {"operation": "DELETE", "scope": "user", "critical": True},
            {"operation": "FINANCIAL_TRANSACTION", "scope": "payment", "critical": True},
            {"operation": "SECURITY_CHANGE", "scope": "system", "critical": True}
        ]
    }


# Test markers for categorizing tests
pytest_plugins = []

# Custom markers for test organization
pytestmark = [
    pytest.mark.migration,  # All tests in this module are migration tests
]

# Migration test markers
migration_markers = [
    "migration_safety",      # Tests for migration upgrade/downgrade safety
    "constraint_validation", # Tests for database constraint enforcement
    "audit_integrity",       # Tests for audit chain cryptographic integrity
    "performance_validation",# Tests for query performance and index usage
    "turkish_compliance",    # Tests for Turkish regulatory compliance
    "enterprise_security",   # Tests for enterprise-grade security features
]

# Register custom markers
for marker in migration_markers:
    pytest.mark.__dict__[marker] = pytest.mark.__dict__.get(marker, pytest.mark)


# Test helper functions
def skip_if_no_database():
    """Skip test if database is not available."""
    try:
        from app.core.database import engine
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        return False
    except Exception:
        return True


def skip_if_no_migration_env():
    """Skip test if migration environment is not properly configured."""
    try:
        from alembic.config import Config as AlembicConfig
        api_dir = os.path.dirname(os.path.dirname(__file__))
        alembic_dir = os.path.join(api_dir, "alembic")
        
        if not os.path.exists(alembic_dir):
            return True
        
        config = AlembicConfig()
        config.set_main_option("script_location", alembic_dir)
        return False
    except Exception:
        return True


# Test configuration validation
def validate_test_environment():
    """Validate that the test environment is properly configured."""
    issues = []
    
    # Check database connectivity
    if skip_if_no_database():
        issues.append("Database not accessible")
    
    # Check migration environment
    if skip_if_no_migration_env():
        issues.append("Alembic migration environment not configured")
    
    # Check required environment variables
    required_env_vars = ["DATABASE_URL"]
    for var in required_env_vars:
        if not os.getenv(var):
            issues.append(f"Missing environment variable: {var}")
    
    return issues


# Auto-validation on import
if __name__ != "__main__":
    # Only validate when imported (not when run directly)
    env_issues = validate_test_environment()
    if env_issues:
        import warnings
        warnings.warn(
            f"Migration test environment issues detected: {', '.join(env_issues)}. "
            "Some tests may be skipped.",
            UserWarning
        )


# Export configuration and fixtures
__all__ = [
    'MigrationTestConfig',
    'isolated_migration_env',
    'migration_session',
    'audit_chain_validator',
    'financial_validator', 
    'performance_profiler',
    'migration_safety_checker',
    'test_data_factory',
    'turkish_compliance_data',
    'performance_test_data',
    'enterprise_security_data',
    'skip_if_no_database',
    'skip_if_no_migration_env',
    'validate_test_environment'
]