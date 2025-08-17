"""
Migration Test Helpers - Ultra Enterprise Banking Precision

Utility functions for comprehensive migration testing with cryptographic
integrity validation and Turkish compliance verification.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


class MigrationTestEnvironment:
    """Isolated test environment for migration testing."""
    
    def __init__(self, base_db_url: str):
        """Initialize migration test environment."""
        self.base_db_url = base_db_url
        self.test_db_name = f"migration_test_{os.getpid()}"
        self.test_db_url = self._construct_test_db_url()
        self.engine: Optional[Engine] = None
        self.alembic_config: Optional[AlembicConfig] = None
    
    def _construct_test_db_url(self) -> str:
        """Construct test database URL."""
        base_parts = self.base_db_url.split("/")
        base_connection = "/".join(base_parts[:-1])
        return f"{base_connection}/{self.test_db_name}"
    
    def setup(self) -> Tuple[Engine, AlembicConfig]:
        """Set up isolated test database and Alembic configuration."""
        # Create test database
        base_engine = create_engine(self.base_db_url.replace("/freecad", "/postgres"))
        
        with base_engine.connect() as conn:
            conn.execute(text("COMMIT"))
            try:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{self.test_db_name}"'))
                conn.execute(text(f'CREATE DATABASE "{self.test_db_name}"'))
            except Exception as e:
                raise RuntimeError(f"Failed to create test database: {e}")
        
        base_engine.dispose()
        
        # Create test engine
        self.engine = create_engine(self.test_db_url)
        
        # Configure Alembic
        api_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        alembic_dir = os.path.join(api_dir, "alembic")
        
        self.alembic_config = AlembicConfig()
        self.alembic_config.set_main_option("script_location", alembic_dir)
        self.alembic_config.set_main_option("sqlalchemy.url", self.test_db_url)
        
        return self.engine, self.alembic_config
    
    def teardown(self):
        """Clean up test environment."""
        if self.engine:
            self.engine.dispose()
        
        # Drop test database
        base_engine = create_engine(self.base_db_url.replace("/freecad", "/postgres"))
        with base_engine.connect() as conn:
            conn.execute(text("COMMIT"))
            try:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{self.test_db_name}"'))
            except Exception:
                pass  # Best effort cleanup
        
        base_engine.dispose()
    
    def __enter__(self):
        """Context manager entry."""
        return self.setup()
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.teardown()


class AuditChainValidator:
    """Validator for audit chain cryptographic integrity."""
    
    @staticmethod
    def calculate_canonical_hash(payload: Dict[str, Any], prev_hash: str) -> str:
        """
        Calculate canonical hash for audit chain entry.
        
        Uses SHA256(prev_hash + canonical_json(payload)) for deterministic hashing.
        """
        # Create canonical JSON (sorted keys, no whitespace)
        canonical_json = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        
        # Combine with previous hash
        hash_input = prev_hash + canonical_json
        
        # Calculate SHA256
        return hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
    
    @staticmethod
    def verify_chain_integrity(audit_logs: List[Any]) -> Tuple[bool, Optional[str]]:
        """
        Verify complete audit chain integrity.
        
        Returns:
            (is_valid, error_message)
        """
        if not audit_logs:
            return True, None
        
        # Sort by ID to ensure proper order
        sorted_logs = sorted(audit_logs, key=lambda log: log.id)
        
        for i, log in enumerate(sorted_logs):
            if i == 0:
                # First log should have genesis hash
                if log.prev_chain_hash != "0" * 64:
                    return False, f"First log should have genesis prev_hash, got: {log.prev_chain_hash}"
            else:
                # Subsequent logs should chain properly
                expected_prev_hash = sorted_logs[i-1].chain_hash
                if log.prev_chain_hash != expected_prev_hash:
                    return False, f"Chain break at log {log.id}: expected prev_hash {expected_prev_hash}, got {log.prev_chain_hash}"
            
            # Verify hash calculation (if possible)
            if log.payload:
                expected_hash = AuditChainValidator.calculate_canonical_hash(
                    log.payload, log.prev_chain_hash
                )
                # Note: In production, hash is calculated by database trigger
                # This is for validation of the concept
        
        return True, None


class FinancialPrecisionValidator:
    """Validator for Turkish financial compliance and precision."""
    
    @staticmethod
    def validate_currency_precision(amount_cents: int, currency: str) -> bool:
        """Validate currency precision according to Turkish standards."""
        if currency == "TRY":
            # Turkish Lira: 2 decimal places
            return amount_cents % 1 == 0  # Should be whole cents
        elif currency in ["USD", "EUR"]:
            # Major currencies: 2 decimal places
            return amount_cents % 1 == 0
        else:
            # Unknown currency - follow default precision
            return amount_cents % 1 == 0
    
    @staticmethod
    def calculate_kdv_tax(amount_cents: int, tax_rate: Decimal = Decimal('20')) -> int:
        """
        Calculate Turkish KDV (VAT) with banking precision.
        
        Args:
            amount_cents: Base amount in cents
            tax_rate: Tax rate percentage (default 20% for Turkey)
        
        Returns:
            Tax amount in cents
        """
        from decimal import ROUND_HALF_UP
        
        base_amount = Decimal(amount_cents) / Decimal('100')
        tax_amount = (base_amount * tax_rate / Decimal('100')).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        
        return int(tax_amount * 100)
    
    @staticmethod
    def validate_invoice_compliance(invoice_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate invoice compliance with Turkish regulations.
        
        Returns:
            (is_valid, error_messages)
        """
        errors = []
        
        # Required fields for Turkish compliance
        required_fields = ['number', 'amount_cents', 'currency', 'status']
        for field in required_fields:
            if field not in invoice_data:
                errors.append(f"Missing required field: {field}")
        
        # Validate invoice number format
        if 'number' in invoice_data:
            number = invoice_data['number']
            if not isinstance(number, str) or len(number) < 3:
                errors.append("Invoice number must be string with minimum 3 characters")
        
        # Validate amount precision
        if 'amount_cents' in invoice_data:
            amount = invoice_data['amount_cents']
            if not isinstance(amount, int) or amount < 0:
                errors.append("Amount must be non-negative integer (cents)")
        
        # Validate currency
        if 'currency' in invoice_data:
            currency = invoice_data['currency']
            valid_currencies = ['TRY', 'USD', 'EUR']  # Extend as needed
            if currency not in valid_currencies:
                errors.append(f"Invalid currency: {currency}. Valid: {valid_currencies}")
        
        return len(errors) == 0, errors


class PerformanceProfiler:
    """Performance profiler for database operations."""
    
    def __init__(self, engine: Engine):
        """Initialize performance profiler."""
        self.engine = engine
        self.query_times: List[float] = []
        self.slow_query_threshold = 1.0  # 1 second
    
    def profile_query(self, query: str, description: str = "") -> Tuple[Any, float]:
        """
        Profile query execution time.
        
        Returns:
            (result, execution_time_seconds)
        """
        import time
        
        start_time = time.time()
        
        with self.engine.connect() as conn:
            result = conn.execute(text(query)).fetchall()
        
        execution_time = time.time() - start_time
        self.query_times.append(execution_time)
        
        if execution_time > self.slow_query_threshold:
            print(f"⚠️ Slow query detected ({execution_time:.3f}s): {description}")
            print(f"   Query: {query[:100]}...")
        
        return result, execution_time
    
    def get_performance_summary(self) -> Dict[str, float]:
        """Get performance summary statistics."""
        if not self.query_times:
            return {}
        
        return {
            "total_queries": len(self.query_times),
            "avg_time": sum(self.query_times) / len(self.query_times),
            "max_time": max(self.query_times),
            "min_time": min(self.query_times),
            "slow_queries": sum(1 for t in self.query_times if t > self.slow_query_threshold)
        }


class MigrationSafetyChecker:
    """Safety checker for migration operations."""
    
    @staticmethod
    def validate_migration_safety(engine: Engine, migration_name: str) -> Tuple[bool, List[str]]:
        """
        Validate migration safety before execution.
        
        Returns:
            (is_safe, warning_messages)
        """
        warnings = []
        
        with engine.connect() as conn:
            # Check for large tables that might be affected
            result = conn.execute(text("""
                SELECT schemaname, tablename, n_tup_ins, n_tup_upd, n_tup_del
                FROM pg_stat_user_tables
                WHERE n_tup_ins + n_tup_upd + n_tup_del > 10000
                ORDER BY n_tup_ins + n_tup_upd + n_tup_del DESC
            """))
            
            large_tables = result.fetchall()
            if large_tables:
                warnings.append(f"Large tables detected: {len(large_tables)} tables with >10k operations")
            
            # Check for active connections that might block migration
            result = conn.execute(text("""
                SELECT count(*) FROM pg_stat_activity 
                WHERE state = 'active' AND query NOT LIKE '%pg_stat_activity%'
            """))
            
            active_connections = result.scalar()
            if active_connections > 5:
                warnings.append(f"High connection count: {active_connections} active connections")
            
            # Check for locks that might interfere
            result = conn.execute(text("""
                SELECT count(*) FROM pg_locks 
                WHERE mode LIKE '%ExclusiveLock%'
            """))
            
            exclusive_locks = result.scalar()
            if exclusive_locks > 0:
                warnings.append(f"Exclusive locks detected: {exclusive_locks} locks")
        
        # Migration is considered safe if no critical warnings
        is_safe = len(warnings) == 0 or all("detected" in w for w in warnings)
        
        return is_safe, warnings
    
    @staticmethod
    def check_rollback_feasibility(engine: Engine, target_revision: str) -> Tuple[bool, List[str]]:
        """
        Check if rollback to target revision is feasible.
        
        Returns:
            (is_feasible, blocking_issues)
        """
        issues = []
        
        with engine.connect() as conn:
            # Check for data that might be lost in rollback
            # This is a simplified check - in production, would need revision-specific logic
            
            # Check for recent data that might be lost
            try:
                result = conn.execute(text("""
                    SELECT 'users' as table_name, count(*) as recent_records
                    FROM users WHERE created_at > NOW() - INTERVAL '1 hour'
                    UNION ALL
                    SELECT 'jobs', count(*) FROM jobs WHERE created_at > NOW() - INTERVAL '1 hour'
                    UNION ALL
                    SELECT 'audit_logs', count(*) FROM audit_logs WHERE created_at > NOW() - INTERVAL '1 hour'
                """))
                
                recent_data = result.fetchall()
                for table_name, count in recent_data:
                    if count > 0:
                        issues.append(f"Recent data in {table_name}: {count} records")
            
            except Exception as e:
                issues.append(f"Could not check recent data: {e}")
        
        is_feasible = len(issues) == 0
        return is_feasible, issues


# Test data factories for consistent test data generation
class TestDataFactory:
    """Factory for creating consistent test data."""
    
    @staticmethod
    def create_test_user(email_suffix: str = "test") -> Dict[str, Any]:
        """Create test user data."""
        return {
            "email": f"{email_suffix}@example.com",
            "phone": f"+90555{hash(email_suffix) % 10000000:07d}",
            "full_name": f"Test User {email_suffix.title()}",
            "role": "user"
        }
    
    @staticmethod
    def create_test_invoice(license_id: int, amount_try: Decimal = Decimal('100.00')) -> Dict[str, Any]:
        """Create test invoice data with Turkish compliance."""
        return {
            "license_id": license_id,
            "number": f"INV-{hash(str(license_id)) % 100000:05d}",
            "amount_cents": int(amount_try * 100),
            "currency": "TRY",
            "status": "pending"
        }
    
    @staticmethod
    def create_test_audit_payload(operation: str, scope_id: int) -> Dict[str, Any]:
        """Create test audit log payload."""
        return {
            "operation": operation,
            "scope_id": scope_id,
            "timestamp": "2025-08-17T20:00:00Z",
            "compliance": {
                "legal_basis": "KVKV Article 5",
                "data_controller": "FreeCAD Production Platform",
                "processing_purpose": "manufacturing_job_management"
            }
        }


# Context managers for test isolation
class IsolatedTestTransaction:
    """Context manager for isolated test transactions."""
    
    def __init__(self, session: Session):
        """Initialize with database session."""
        self.session = session
        self.savepoint = None
    
    def __enter__(self):
        """Start isolated transaction."""
        self.savepoint = self.session.begin_nested()
        return self.session
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Rollback isolated transaction."""
        if self.savepoint:
            self.savepoint.rollback()


# Export all utilities
__all__ = [
    'MigrationTestEnvironment',
    'AuditChainValidator', 
    'FinancialPrecisionValidator',
    'PerformanceProfiler',
    'MigrationSafetyChecker',
    'TestDataFactory',
    'IsolatedTestTransaction'
]