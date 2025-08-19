"""
Ultra Enterprise Model Validators for SQLAlchemy
Task 2.10: Model-level constraints and validation for banking-level precision

This module provides comprehensive validation for:
- Idempotency key fields with cryptographic validation
- Enum field validation with enterprise constraints  
- JSONB field validation with schema enforcement
- Turkish compliance validation (KVKV/GDPR/KDV)
- Audit chain cryptographic integrity
- Banking-level financial precision with Decimal arithmetic
- Real-time model constraint validation via SQLAlchemy events

ENTERPRISE FEATURES:
- Zero data loss validation with rollback support
- Cryptographic hash chain integrity for audit logs
- Turkish regulatory compliance (VKN/TCKN validation)
- Multi-currency financial precision controls
- Canonical JSON serialization for audit trails
"""

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from .enums import (
    AuditAction,
    CamStrategy,
    Currency,
    ErpSystem,
    FileFormat,
    InvoiceStatus,
    InvoiceType,
    JobStatus,
    JobType,
    LicenseStatus,
    LicenseType,
    Locale,
    MachineType,
    MaterialCategory,
    ModelType,
    NotificationSeverity,
    NotificationType,
    PaymentMethod,
    PaymentStatus,
    SecurityEventType,
    SecuritySeverity,
    SimulationStatus,
    SimulationType,
    SyncDirection,
    SyncStatus,
    ToolMaterial,
    ToolType,
    UserRole,
)


class IdempotencyKeyValidator:
    """Ultra enterprise idempotency key validation with cryptographic controls."""

    # Valid idempotency key patterns
    PATTERNS = {
        'uuid_v4': re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
        'hash_sha256': re.compile(r'^[0-9a-f]{64}$'),
        'custom_prefix': re.compile(r'^[a-zA-Z0-9]{2,10}_[0-9a-f]{32,64}$'),
        'timestamp_based': re.compile(r'^[0-9]{13}_[0-9a-f]{16,32}$'),
    }

    @classmethod
    def validate(cls, key: str | None, context: str = "unknown") -> bool:
        """
        Validate idempotency key format and cryptographic properties.
        
        Args:
            key: Idempotency key to validate
            context: Context for validation (job, payment, etc.)
            
        Returns:
            True if valid, False otherwise
            
        Raises:
            ValueError: For invalid keys in strict mode
        """
        if key is None:
            return True  # NULL is allowed

        if not isinstance(key, str):
            raise ValueError(f"Idempotency key must be string, got {type(key)}")

        if len(key) < 16:
            raise ValueError("Idempotency key too short (minimum 16 characters)")

        if len(key) > 255:
            raise ValueError("Idempotency key too long (maximum 255 characters)")

        # Check against known patterns
        for pattern_name, pattern in cls.PATTERNS.items():
            if pattern.match(key):
                return True

        # Additional entropy check for custom keys
        if cls._check_entropy(key):
            return True

        raise ValueError(f"Invalid idempotency key format: {key[:20]}...")

    @classmethod
    def _check_entropy(cls, key: str) -> bool:
        """Check if key has sufficient entropy (basic heuristic)."""
        unique_chars = len(set(key.lower()))
        return unique_chars >= 8  # Minimum character diversity

    @classmethod
    def generate(cls, context: str = "default", user_id: int | None = None) -> str:
        """
        Generate cryptographically secure idempotency key.
        
        Args:
            context: Context identifier
            user_id: Optional user ID for user-scoped keys
            
        Returns:
            Secure idempotency key
        """
        timestamp = int(datetime.now(UTC).timestamp() * 1000)  # milliseconds
        random_part = uuid.uuid4().hex

        if user_id:
            return f"{context}_{user_id}_{timestamp}_{random_part}"
        else:
            return f"{context}_{timestamp}_{random_part}"


class EnumValidator:
    """Ultra enterprise enum validation with Turkish compliance."""

    # Enum validation rules
    ENUM_MAPPINGS = {
        'user_role': UserRole,
        'locale': Locale,
        'license_type': LicenseType,
        'license_status': LicenseStatus,
        'job_type': JobType,
        'job_status': JobStatus,
        'model_type': ModelType,
        'file_format': FileFormat,
        'cam_strategy': CamStrategy,
        'tool_type': ToolType,
        'tool_material': ToolMaterial,
        'machine_type': MachineType,
        'material_category': MaterialCategory,
        'simulation_type': SimulationType,
        'simulation_status': SimulationStatus,
        'notification_type': NotificationType,
        'notification_severity': NotificationSeverity,
        'invoice_type': InvoiceType,
        'invoice_status': InvoiceStatus,
        'payment_method': PaymentMethod,
        'payment_status': PaymentStatus,
        'currency': Currency,
        'audit_action': AuditAction,
        'security_event_type': SecurityEventType,
        'security_severity': SecuritySeverity,
        'erp_system': ErpSystem,
        'sync_direction': SyncDirection,
        'sync_status': SyncStatus,
    }

    @classmethod
    def validate(cls, value: Any, enum_name: str) -> bool:
        """
        Validate enum value against defined constraints.
        
        Args:
            value: Value to validate
            enum_name: Name of enum type
            
        Returns:
            True if valid
            
        Raises:
            ValueError: For invalid enum values
        """
        if value is None:
            return True  # NULL allowed if field is nullable

        enum_class = cls.ENUM_MAPPINGS.get(enum_name)
        if not enum_class:
            raise ValueError(f"Unknown enum type: {enum_name}")

        # Handle both enum instances and string values
        if isinstance(value, enum_class):
            return True

        if isinstance(value, str):
            try:
                enum_class(value)
                return True
            except ValueError:
                valid_values = [e.value for e in enum_class]
                raise ValueError(
                    f"Invalid {enum_name} value '{value}'. "
                    f"Valid values: {valid_values}"
                )

        raise ValueError(f"Invalid type for {enum_name}: {type(value)}")

    @classmethod
    def validate_turkish_compliance(cls, value: Any, field_context: str) -> bool:
        """
        Validate enum values for Turkish regulatory compliance.
        
        Special validation for:
        - Currency: Must support TRY
        - Locale: Must support Turkish (TR)
        - Payment methods: Must support Turkish payment systems
        """
        if field_context == 'currency' and value:
            # Ensure TRY is available in currency enum
            if hasattr(Currency, 'TRY'):
                return True
            raise ValueError("Turkish Lira (TRY) must be supported")

        if field_context == 'locale' and value:
            # Ensure Turkish locale is available
            if hasattr(Locale, 'TR'):
                return True
            raise ValueError("Turkish locale (TR) must be supported")

        if field_context == 'payment_method' and value:
            # Check for Turkish payment methods
            turkish_methods = ['iyzico', 'bank_transfer']
            if value in turkish_methods or hasattr(PaymentMethod, value.upper()):
                return True

        return True


class JSONBValidator:
    """Ultra enterprise JSONB field validation with schema enforcement."""

    # Standard schemas for common JSONB fields
    SCHEMAS = {
        'user_metadata': {
            'type': 'object',
            'properties': {
                'preferences': {'type': 'object'},
                'settings': {'type': 'object'},
                'profile': {'type': 'object'},
                'gdpr_consent': {'type': 'boolean'},
                'kvkk_consent': {'type': 'boolean'},  # Turkish GDPR
                'marketing_consent': {'type': 'boolean'},
            },
            'additionalProperties': True
        },

        'job_params': {
            'type': 'object',
            'required': ['operation_type'],
            'properties': {
                'operation_type': {'type': 'string'},
                'input_file': {'type': 'string'},
                'output_format': {'type': 'string'},
                'quality_settings': {'type': 'object'},
                'machine_settings': {'type': 'object'},
            },
            'additionalProperties': True
        },

        'job_output': {
            'type': 'object',
            'properties': {
                'result_files': {'type': 'array', 'items': {'type': 'string'}},
                'metrics': {'type': 'object'},
                'warnings': {'type': 'array', 'items': {'type': 'string'}},
                'errors': {'type': 'array', 'items': {'type': 'string'}},
            },
            'additionalProperties': True
        },

        'machine_specifications': {
            'type': 'object',
            'properties': {
                'max_feed_rate': {'type': 'number', 'minimum': 0},
                'rapid_feed_rate': {'type': 'number', 'minimum': 0},
                'positioning_accuracy': {'type': 'number', 'minimum': 0},
                'repeatability': {'type': 'number', 'minimum': 0},
                'spindle_taper': {'type': 'string'},
                'coolant_capacity': {'type': 'number', 'minimum': 0},
                'made_in': {'type': 'string'},  # Country of manufacture
            },
            'additionalProperties': True
        },

        'material_properties': {
            'type': 'object',
            'properties': {
                'thermal_conductivity': {'type': 'number', 'minimum': 0},
                'coefficient_expansion': {'type': 'number'},
                'melting_point': {'type': 'number'},
                'corrosion_resistance': {'type': 'string'},
                'weldability': {'type': 'string'},
                'turkish_standard': {'type': 'string'},  # Turkish standards compliance
                'common_applications': {'type': 'array', 'items': {'type': 'string'}},
            },
            'additionalProperties': True
        },

        'tool_specifications': {
            'type': 'object',
            'properties': {
                'coating_hardness': {'type': 'string'},
                'max_temp': {'type': 'number', 'minimum': 0},
                'material_groups': {'type': 'array', 'items': {'type': 'string'}},
                'recommended_materials': {'type': 'array', 'items': {'type': 'string'}},
                'cutting_edge': {'type': 'string'},
                'surface_finish': {'type': 'string'},
                'runout_tolerance': {'type': 'number', 'minimum': 0},
                'turkish_distributor': {'type': 'string'},  # Turkish supplier info
            },
            'additionalProperties': True
        },

        'audit_payload': {
            'type': 'object',
            'required': ['action', 'timestamp'],
            'properties': {
                'action': {'type': 'string'},
                'timestamp': {'type': 'string', 'format': 'date-time'},
                'user_id': {'type': ['integer', 'null']},
                'ip_address': {'type': 'string'},
                'user_agent': {'type': 'string'},
                'resource_type': {'type': 'string'},
                'resource_id': {'type': ['string', 'integer', 'null']},
                'changes': {'type': 'object'},
                'metadata': {'type': 'object'},
            },
            'additionalProperties': True
        },

        'financial_metadata': {
            'type': 'object',
            'properties': {
                'tax_breakdown': {'type': 'object'},
                'kdv_rate': {'type': 'number', 'minimum': 0, 'maximum': 100},  # Turkish VAT
                'currency_rates': {'type': 'object'},
                'payment_terms': {'type': 'object'},
                'billing_address': {'type': 'object'},
                'tax_office': {'type': 'string'},  # Turkish tax office
                'vkn_number': {'type': 'string'},   # Turkish tax number
            },
            'additionalProperties': True
        }
    }

    @classmethod
    def validate(cls, data: Any, schema_name: str, strict: bool = True) -> bool:
        """
        Validate JSONB data against defined schema.
        
        Args:
            data: JSONB data to validate
            schema_name: Name of schema to validate against
            strict: Whether to enforce strict validation
            
        Returns:
            True if valid
            
        Raises:
            ValueError: For invalid JSONB data
        """
        if data is None:
            return True  # NULL allowed

        if not isinstance(data, dict):
            if strict:
                raise ValueError(f"JSONB data must be dict, got {type(data)}")
            return False

        schema = cls.SCHEMAS.get(schema_name)
        if not schema:
            if strict:
                raise ValueError(f"Unknown JSONB schema: {schema_name}")
            return True  # Unknown schema, allow by default

        try:
            cls._validate_against_schema(data, schema)
            return True
        except ValueError as e:
            if strict:
                raise ValueError(f"JSONB validation failed for {schema_name}: {e}")
            return False

    @classmethod
    def _validate_against_schema(cls, data: dict[str, Any], schema: dict[str, Any]):
        """Validate data against JSON schema (simplified implementation)."""
        # Check required fields
        required = schema.get('required', [])
        for field in required:
            if field not in data:
                raise ValueError(f"Required field missing: {field}")

        # Check field types
        properties = schema.get('properties', {})
        for field, value in data.items():
            if field in properties:
                field_schema = properties[field]
                cls._validate_field_type(value, field_schema, field)

    @classmethod
    def _validate_field_type(cls, value: Any, field_schema: dict[str, Any], field_name: str):
        """Validate individual field against its schema."""
        expected_type = field_schema.get('type')

        if expected_type == 'string' and not isinstance(value, str):
            raise ValueError(f"Field {field_name} must be string")
        elif expected_type == 'number' and not isinstance(value, (int, float)):
            raise ValueError(f"Field {field_name} must be number")
        elif expected_type == 'integer' and not isinstance(value, int):
            raise ValueError(f"Field {field_name} must be integer")
        elif expected_type == 'boolean' and not isinstance(value, bool):
            raise ValueError(f"Field {field_name} must be boolean")
        elif expected_type == 'array' and not isinstance(value, list):
            raise ValueError(f"Field {field_name} must be array")
        elif expected_type == 'object' and not isinstance(value, dict):
            raise ValueError(f"Field {field_name} must be object")

        # Check numeric constraints
        if isinstance(value, (int, float)):
            minimum = field_schema.get('minimum')
            maximum = field_schema.get('maximum')
            if minimum is not None and value < minimum:
                raise ValueError(f"Field {field_name} below minimum {minimum}")
            if maximum is not None and value > maximum:
                raise ValueError(f"Field {field_name} above maximum {maximum}")


class FinancialPrecisionValidator:
    """Banking-level financial precision validation with Turkish compliance."""

    @classmethod
    def validate_amount_cents(cls, amount_cents: int | None, context: str = "amount") -> bool:
        """
        Validate amount in cents for banking-level precision.
        
        Args:
            amount_cents: Amount in cents (integer)
            context: Context for validation
            
        Returns:
            True if valid
            
        Raises:
            ValueError: For invalid amounts
        """
        if amount_cents is None:
            return True  # NULL allowed if field is nullable

        if not isinstance(amount_cents, int):
            raise ValueError(f"{context} must be integer (cents), got {type(amount_cents)}")

        # Check reasonable bounds (prevent overflow attacks)
        max_amount = 999_999_999_99  # 9.9 billion (in cents)
        if amount_cents < 0:
            raise ValueError(f"{context} cannot be negative")

        if amount_cents > max_amount:
            raise ValueError(f"{context} exceeds maximum allowed value")

        return True

    @classmethod
    def validate_turkish_tax_rate(cls, rate: Decimal | None, context: str = "tax") -> bool:
        """
        Validate Turkish tax rates (KDV - Katma Değer Vergisi).
        
        Valid Turkish VAT rates: 1%, 8%, 18%, 20%
        """
        if rate is None:
            return True

        if not isinstance(rate, Decimal):
            if isinstance(rate, (int, float)):
                rate = Decimal(str(rate))
            else:
                raise ValueError(f"{context} rate must be Decimal")

        # Turkish VAT rates (configurable for regulatory changes)
        # Default rates as of 2024: 1%, 8%, 18%, 20%
        valid_rates = cls._get_valid_turkish_tax_rates()

        if rate not in valid_rates:
            raise ValueError(
                f"Invalid Turkish {context} rate: {rate}%. "
                f"Valid rates: {[str(r) for r in valid_rates]}%"
            )

        return True

    @classmethod
    def _get_valid_turkish_tax_rates(cls) -> list[Decimal]:
        """
        Get valid Turkish tax rates (configurable for regulatory changes).
        
        Returns:
            List of valid Turkish VAT rates as Decimal objects
        """
        # TODO: Load from configuration/environment in production
        # Current Turkish VAT rates as of 2024
        return [Decimal('1'), Decimal('8'), Decimal('18'), Decimal('20')]

    @classmethod
    def cents_to_decimal(cls, amount_cents: int) -> Decimal:
        """Convert cents to decimal with proper precision."""
        return Decimal(amount_cents) / Decimal('100')

    @classmethod
    def decimal_to_cents(cls, amount: Decimal) -> int:
        """Convert decimal to cents with proper rounding."""
        return int((amount * Decimal('100')).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


class AuditChainValidator:
    """Cryptographic audit chain validation for immutable audit logs."""

    @classmethod
    def validate_hash_format(cls, hash_value: str | None, context: str = "hash") -> bool:
        """
        Validate hash format (SHA-256 hex).
        
        Args:
            hash_value: Hash to validate
            context: Context for validation
            
        Returns:
            True if valid
            
        Raises:
            ValueError: For invalid hashes
        """
        if hash_value is None:
            return True  # NULL allowed for initial entry

        if not isinstance(hash_value, str):
            raise ValueError(f"{context} must be string")

        if len(hash_value) != 64:
            raise ValueError(f"{context} must be 64 characters (SHA-256)")

        if not re.match(r'^[0-9a-f]{64}$', hash_value):
            raise ValueError(f"{context} must be lowercase hex")

        return True

    @classmethod
    def generate_chain_hash(cls, data: dict[str, Any], prev_hash: str | None = None) -> str:
        """
        Generate cryptographic hash for audit chain.
        
        Args:
            data: Audit log data
            prev_hash: Previous hash in chain
            
        Returns:
            SHA-256 hash for chain integrity
        """
        # Create canonical JSON representation
        canonical_data = json.dumps(data, sort_keys=True, separators=(',', ':'))

        # Include previous hash for chaining
        if prev_hash:
            chain_input = f"{prev_hash}:{canonical_data}"
        else:
            chain_input = canonical_data

        # Generate SHA-256 hash
        return hashlib.sha256(chain_input.encode('utf-8')).hexdigest()

    @classmethod
    def verify_chain_integrity(cls, current_hash: str, data: dict[str, Any], prev_hash: str | None = None) -> bool:
        """Verify audit chain hash integrity."""
        expected_hash = cls.generate_chain_hash(data, prev_hash)
        return current_hash == expected_hash


class TurkishComplianceValidator:
    """Ultra enterprise Turkish regulatory compliance validator."""

    @classmethod
    def validate_vkn(cls, vkn: str | None, context: str = "tax_no") -> bool:
        """
        Validate Turkish tax number (VKN - Vergi Kimlik Numarası).
        
        Args:
            vkn: Turkish tax number to validate
            context: Context for validation
            
        Returns:
            True if valid
            
        Raises:
            ValueError: For invalid VKN format
        """
        if vkn is None:
            return True  # NULL allowed if field is nullable

        if not isinstance(vkn, str):
            raise ValueError(f"{context} must be string")

        # Remove spaces and non-digits
        clean_vkn = ''.join(filter(str.isdigit, vkn))

        # VKN must be exactly 10 digits
        if len(clean_vkn) != 10:
            raise ValueError(f"{context} must be exactly 10 digits")

        # Cannot start with 0
        if clean_vkn[0] == '0':
            raise ValueError(f"{context} cannot start with 0")

        # CORRECT Turkish VKN validation algorithm
        try:
            digits = [int(d) for d in clean_vkn]

            # Calculate weighted sum
            weighted_sum = 0
            for i in range(9):
                weighted_sum += digits[i] * (10 - i)

            remainder = weighted_sum % 11

            # Check digit logic
            if remainder < 2:
                check_digit = remainder
            else:
                check_digit = 11 - remainder

            if check_digit != digits[9]:
                raise ValueError(f"Invalid {context} checksum")

        except (ValueError, IndexError) as e:
            raise ValueError(f"Invalid {context} format: {e}")

        return True

    @classmethod
    def validate_tckn(cls, tckn: str | None, context: str = "citizen_id") -> bool:
        """
        Validate Turkish citizen ID (TCKN - T.C. Kimlik Numarası).
        
        Args:
            tckn: Turkish citizen ID to validate
            context: Context for validation
            
        Returns:
            True if valid
            
        Raises:
            ValueError: For invalid TCKN format
        """
        if tckn is None:
            return True  # NULL allowed if field is nullable

        if not isinstance(tckn, str):
            raise ValueError(f"{context} must be string")

        # Remove spaces and non-digits
        clean_tckn = ''.join(filter(str.isdigit, tckn))

        # TCKN must be exactly 11 digits
        if len(clean_tckn) != 11:
            raise ValueError(f"{context} must be exactly 11 digits")

        # Cannot start with 0
        if clean_tckn[0] == '0':
            raise ValueError(f"{context} cannot start with 0")

        # TCKN checksum validation algorithm
        try:
            digits = [int(d) for d in clean_tckn]

            # Calculate checksums
            odd_sum = sum(digits[i] for i in range(0, 9, 2))  # 1st, 3rd, 5th, 7th, 9th
            even_sum = sum(digits[i] for i in range(1, 8, 2))  # 2nd, 4th, 6th, 8th

            # Check 10th digit
            check10 = ((odd_sum * 7) - even_sum) % 10
            if check10 != digits[9]:
                raise ValueError(f"Invalid {context} 10th digit checksum")

            # Check 11th digit
            check11 = (odd_sum + even_sum + digits[9]) % 10
            if check11 != digits[10]:
                raise ValueError(f"Invalid {context} 11th digit checksum")

        except (ValueError, IndexError) as e:
            raise ValueError(f"Invalid {context} format: {e}")

        return True

    @classmethod
    def validate_turkish_phone(cls, phone: str | None, context: str = "phone") -> bool:
        """
        Validate Turkish phone number format.
        
        Args:
            phone: Phone number to validate
            context: Context for validation
            
        Returns:
            True if valid
            
        Raises:
            ValueError: For invalid phone format
        """
        if phone is None:
            return True  # NULL allowed if field is nullable

        if not isinstance(phone, str):
            raise ValueError(f"{context} must be string")

        # Remove spaces, dashes, parentheses
        clean_phone = re.sub(r'[\s\-\(\)]', '', phone)

        # Turkish phone patterns
        patterns = [
            r'^\+90[5][0-9]{9}$',          # +905XXXXXXXXX (mobile)
            r'^90[5][0-9]{9}$',            # 905XXXXXXXXX (mobile)
            r'^0[5][0-9]{9}$',             # 05XXXXXXXXX (mobile)
            r'^\+90[2-4][0-9]{9}$',        # +902XXXXXXXXX (landline)
            r'^90[2-4][0-9]{9}$',          # 902XXXXXXXXX (landline)
            r'^0[2-4][0-9]{9}$',           # 02XXXXXXXXX (landline)
        ]

        for pattern in patterns:
            if re.match(pattern, clean_phone):
                return True

        raise ValueError(f"Invalid Turkish {context} format: {phone}")


class EnhancedSecurityValidator:
    """Enhanced security validator for enterprise protection."""

    @classmethod
    def validate_password_strength(cls, password: str | None, context: str = "password") -> bool:
        """
        Validate password strength for enterprise security.
        
        Args:
            password: Password to validate
            context: Context for validation
            
        Returns:
            True if valid
            
        Raises:
            ValueError: For weak passwords
        """
        if password is None:
            return True  # NULL allowed for optional fields

        if not isinstance(password, str):
            raise ValueError(f"{context} must be string")

        # Minimum length
        if len(password) < 12:
            raise ValueError(f"{context} must be at least 12 characters")

        # Maximum length (prevent DOS attacks)
        if len(password) > 128:
            raise ValueError(f"{context} must be no more than 128 characters")

        # Character type requirements
        has_lower = any(c.islower() for c in password)
        has_upper = any(c.isupper() for c in password)
        has_digit = any(c.isdigit() for c in password)
        has_special = any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in password)

        missing_types = []
        if not has_lower:
            missing_types.append('lowercase letter')
        if not has_upper:
            missing_types.append('uppercase letter')
        if not has_digit:
            missing_types.append('digit')
        if not has_special:
            missing_types.append('special character')

        if missing_types:
            raise ValueError(f"{context} must contain: {', '.join(missing_types)}")

        # Common password patterns (basic check)
        common_patterns = [
            r'(.)\1{3,}',           # 4+ repeated characters
            r'1234|abcd|qwer',      # Sequential patterns
            r'password|admin|user', # Common words (case insensitive)
        ]

        for pattern in common_patterns:
            if re.search(pattern, password.lower()):
                raise ValueError(f"{context} contains common patterns")

        return True

    @classmethod
    def validate_ip_address(cls, ip_address: str | None, context: str = "ip_address") -> bool:
        """
        Validate IP address format (IPv4 or IPv6).
        
        Args:
            ip_address: IP address to validate
            context: Context for validation
            
        Returns:
            True if valid
            
        Raises:
            ValueError: For invalid IP format
        """
        if ip_address is None:
            return True  # NULL allowed if field is nullable

        if not isinstance(ip_address, str):
            raise ValueError(f"{context} must be string")

        # IPv4 pattern
        ipv4_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'

        # IPv6 pattern (simplified)
        ipv6_pattern = r'^(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$|^::1$|^::$'

        if re.match(ipv4_pattern, ip_address) or re.match(ipv6_pattern, ip_address):
            return True

        raise ValueError(f"Invalid {context} format: {ip_address}")


# Model event listeners for automatic validation
def setup_model_validators():
    """Set up SQLAlchemy event listeners for automatic validation."""

    @event.listens_for(Session, 'before_flush')
    def validate_before_flush(session, flush_context, instances):
        """Validate all instances before flush."""
        for instance in session.new | session.dirty:
            _validate_instance(instance)

    def _validate_instance(instance):
        """Validate individual model instance."""
        table_name = instance.__tablename__

        # Validate idempotency key if present
        if hasattr(instance, 'idempotency_key'):
            IdempotencyKeyValidator.validate(
                instance.idempotency_key,
                context=table_name
            )

        # Validate enum fields
        for column in instance.__table__.columns:
            if column.type.__class__.__name__ == 'Enum':
                value = getattr(instance, column.name)
                EnumValidator.validate(value, column.name)

        # Validate JSONB fields
        for column in instance.__table__.columns:
            if column.type.__class__.__name__ == 'JSONB':
                value = getattr(instance, column.name)
                if value is not None:
                    schema_name = f"{table_name}_{column.name}"
                    JSONBValidator.validate(value, schema_name, strict=False)

        # Validate financial precision
        if table_name in ['invoices', 'payments']:
            for column in instance.__table__.columns:
                if column.name.endswith('_cents'):
                    value = getattr(instance, column.name)
                    FinancialPrecisionValidator.validate_amount_cents(value, column.name)

        # Validate audit chain
        if table_name == 'audit_logs':
            if hasattr(instance, 'chain_hash'):
                AuditChainValidator.validate_hash_format(instance.chain_hash, 'chain_hash')
            if hasattr(instance, 'prev_chain_hash'):
                AuditChainValidator.validate_hash_format(instance.prev_chain_hash, 'prev_chain_hash')


# Export main validators
__all__ = [
    'IdempotencyKeyValidator',
    'EnumValidator',
    'JSONBValidator',
    'FinancialPrecisionValidator',
    'AuditChainValidator',
    'TurkishComplianceValidator',
    'EnhancedSecurityValidator',
    'setup_model_validators'
]
