"""
Base model classes and mixins for SQLAlchemy ORM.
Task 2.10: Enhanced with ultra enterprise validation and Turkish compliance.
"""

from datetime import datetime, timezone
from typing import Any
from decimal import Decimal

from sqlalchemy import MetaData, DateTime, func, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# Enterprise-grade naming conventions for PostgreSQL 17.6
# These conventions ensure consistent, predictable naming across all database objects
# following PostgreSQL best practices and enterprise standards
convention = {
    # Index naming: ix_tablename_column or ix_tablename_column1_column2 for composite
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    
    # Unique constraint naming: uq_tablename_column
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    
    # Check constraint naming: ck_tablename_constraintname
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    
    # Foreign key naming: fk_tablename_column_reftable
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    
    # Primary key naming: pk_tablename
    "pk": "pk_%(table_name)s",
    
    # Additional constraint types for comprehensive coverage
    # Exclusion constraints (PostgreSQL-specific)
    "exclude": "ex_%(table_name)s_%(constraint_name)s",
    
    # Partial unique indexes (when condition is specified)
    "partial_unique": "puq_%(table_name)s_%(column_0_name)s",
}

metadata = MetaData(naming_convention=convention)


class Base(DeclarativeBase):
    """
    Ultra Enterprise base class for all database models.
    
    Features:
    - Automatic validation via SQLAlchemy events
    - Security-first serialization with sensitive field exclusion
    - Banking-level precision for financial calculations
    - Turkish compliance helpers (KVKV/GDPR/KDV)
    """
    
    metadata = metadata
    
    def __repr__(self) -> str:
        """Default representation showing class name and primary key."""
        if hasattr(self, 'id'):
            return f"<{self.__class__.__name__}(id={self.id})>"
        return f"<{self.__class__.__name__}>"
    
    def to_dict(self, exclude: set[str] | None = None) -> dict[str, Any]:
        """
        Convert model instance to dictionary with security controls.
        
        SECURITY NOTE: Sensitive fields are automatically excluded by default to prevent
        data leakage. Always review what data is being serialized for API responses.
        Consider using Pydantic schemas for API endpoints instead of direct model serialization.
        
        Args:
            exclude: Set of column names to exclude from output (for security)
        
        Returns:
            Dictionary representation of the model
        """
        if exclude is None:
            exclude = set()
        
        # Always exclude sensitive columns by default
        default_exclude = {
            'password_hash', 'refresh_token_hash', 'chain_hash', 'prev_chain_hash',
            'access_token_jti', 'provider_ref'  # Additional sensitive fields
        }
        exclude = exclude | default_exclude
        
        result = {}
        for column in self.__table__.columns:
            if column.name in exclude:
                continue
                
            value = getattr(self, column.name)
            if isinstance(value, datetime):
                value = value.isoformat()
            result[column.name] = value
        return result
    
    def validate_enterprise_constraints(self) -> bool:
        """
        Validate enterprise-level constraints for this model instance.
        
        This method is called automatically by SQLAlchemy events but can also
        be called manually for validation during development.
        
        Returns:
            True if all validations pass
            
        Raises:
            ValueError: If any validation fails
        """
        # Import here to avoid circular imports
        from .validators import (
            IdempotencyKeyValidator, EnumValidator, JSONBValidator,
            FinancialPrecisionValidator, AuditChainValidator
        )
        
        table_name = self.__tablename__
        
        # Validate idempotency key if present
        if hasattr(self, 'idempotency_key'):
            IdempotencyKeyValidator.validate(
                self.idempotency_key, 
                context=table_name
            )
        
        # Validate enum fields
        for column in self.__table__.columns:
            if hasattr(column.type, 'enum_class'):  # SQLAlchemy enum
                value = getattr(self, column.name)
                EnumValidator.validate(value, column.name)
        
        # Validate JSONB fields
        for column in self.__table__.columns:
            if column.type.__class__.__name__ == 'JSONB':
                value = getattr(self, column.name)
                if value is not None:
                    schema_name = f"{table_name}_{column.name}"
                    JSONBValidator.validate(value, schema_name, strict=False)
        
        # Validate financial precision for monetary fields
        if table_name in ['invoices', 'payments']:
            for column in self.__table__.columns:
                if column.name.endswith('_cents'):
                    value = getattr(self, column.name)
                    FinancialPrecisionValidator.validate_amount_cents(value, column.name)
        
        # Validate audit chain for audit logs
        if table_name == 'audit_logs':
            if hasattr(self, 'chain_hash'):
                AuditChainValidator.validate_hash_format(self.chain_hash, 'chain_hash')
            if hasattr(self, 'prev_chain_hash'):
                AuditChainValidator.validate_hash_format(self.prev_chain_hash, 'prev_chain_hash')
        
        return True
    
    def get_financial_amount_decimal(self, field_name: str) -> Decimal:
        """
        Get financial amount as Decimal with banking-level precision.
        
        Args:
            field_name: Name of the amount field (without _cents suffix)
            
        Returns:
            Decimal representation with proper precision
            
        Raises:
            ValueError: If field doesn't exist or isn't a financial field
        """
        cents_field = f"{field_name}_cents"
        if not hasattr(self, cents_field):
            raise ValueError(f"Financial field {cents_field} not found")
        
        amount_cents = getattr(self, cents_field)
        if amount_cents is None:
            return Decimal('0.00')
        
        from .validators import FinancialPrecisionValidator
        return FinancialPrecisionValidator.cents_to_decimal(amount_cents)
    
    def set_financial_amount_decimal(self, field_name: str, amount: Decimal) -> None:
        """
        Set financial amount from Decimal with banking-level precision.
        
        Args:
            field_name: Name of the amount field (without _cents suffix)
            amount: Decimal amount to set
            
        Raises:
            ValueError: If field doesn't exist or amount is invalid
        """
        cents_field = f"{field_name}_cents"
        if not hasattr(self, cents_field):
            raise ValueError(f"Financial field {cents_field} not found")
        
        from .validators import FinancialPrecisionValidator
        amount_cents = FinancialPrecisionValidator.decimal_to_cents(amount)
        setattr(self, cents_field, amount_cents)


class TimestampMixin:
    """Mixin for adding created_at and updated_at timestamps."""
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now()
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now()
    )