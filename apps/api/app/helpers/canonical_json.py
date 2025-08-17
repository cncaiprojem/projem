"""
Canonical JSON implementation for audit chain integrity.
Task 2.10: Ultra Enterprise canonical JSON with cryptographic hash chains.

This module provides utilities for creating canonical JSON representations
that are suitable for cryptographic hashing and audit trails. It ensures
consistent ordering and formatting across different systems and languages.
"""

import json
import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional, Union
from uuid import UUID


class CanonicalJSONEncoder:
    """Ultra enterprise canonical JSON encoder for audit chains."""
    
    @staticmethod
    def canonicalize(data: Any) -> str:
        """
        Convert any Python object to canonical JSON string.
        
        RULES FOR CANONICAL JSON:
        1. Objects (dictionaries) have keys sorted alphabetically
        2. No extra whitespace - compact representation
        3. Unicode characters are escaped using \\uXXXX notation
        4. Special Python types are converted to standard JSON types
        5. Timestamps are converted to ISO 8601 UTC format
        6. Decimals are converted to strings to preserve precision
        7. UUIDs are converted to string representation
        8. None values are converted to null
        
        Args:
            data: Python object to canonicalize
            
        Returns:
            Canonical JSON string suitable for hashing
            
        Raises:
            TypeError: If data contains non-serializable objects
        """
        return json.dumps(
            data,
            ensure_ascii=True,      # Escape Unicode characters
            sort_keys=True,         # Sort object keys alphabetically
            separators=(',', ':'),  # No extra whitespace
            default=CanonicalJSONEncoder._serialize_special_types
        )
    
    @staticmethod
    def _serialize_special_types(obj: Any) -> Union[str, int, float, bool, None]:
        """
        Serialize special Python types to JSON-compatible types.
        
        Args:
            obj: Object to serialize
            
        Returns:
            JSON-compatible representation
            
        Raises:
            TypeError: If object type is not supported
        """
        if isinstance(obj, datetime):
            # Convert to UTC and format as ISO 8601
            if obj.tzinfo is None:
                obj = obj.replace(tzinfo=timezone.utc)
            return obj.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        elif isinstance(obj, Decimal):
            # Convert Decimal to string to preserve precision
            return str(obj)
        
        elif isinstance(obj, UUID):
            # Convert UUID to string
            return str(obj)
        
        elif hasattr(obj, '__dict__'):
            # Convert objects with __dict__ to dictionary
            return {key: value for key, value in obj.__dict__.items() 
                   if not key.startswith('_')}
        
        elif hasattr(obj, 'isoformat'):  # date objects
            return obj.isoformat()
        
        else:
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class AuditChainManager:
    """Ultra enterprise audit chain manager with cryptographic integrity."""
    
    @staticmethod
    def create_audit_record(
        action: str,
        entity_type: str,
        entity_id: Optional[Union[str, int]] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        changes: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        session_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a canonical audit record for hash chain.
        
        Args:
            action: Action performed (e.g., 'create', 'update', 'delete')
            entity_type: Type of entity affected (e.g., 'user', 'job', 'invoice')
            entity_id: ID of the affected entity
            entity_data: Complete state of the entity after the action
            changes: Field-level changes (before/after values)
            user_id: ID of the user performing the action
            ip_address: IP address of the client
            user_agent: User agent string of the client
            session_id: Session ID of the user
            metadata: Additional metadata for the audit record
            
        Returns:
            Canonical audit record dictionary
        """
        # Create base audit record with required fields
        audit_record = {
            'action': action,
            'entity_type': entity_type,
            'timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        }
        
        # Add optional fields only if they have values
        if entity_id is not None:
            audit_record['entity_id'] = str(entity_id)
        
        if entity_data is not None:
            audit_record['entity_data'] = entity_data
        
        if changes is not None:
            audit_record['changes'] = changes
        
        if user_id is not None:
            audit_record['user_id'] = user_id
        
        if ip_address is not None:
            audit_record['ip_address'] = ip_address
        
        if user_agent is not None:
            audit_record['user_agent'] = user_agent
        
        if session_id is not None:
            audit_record['session_id'] = session_id
        
        if metadata is not None:
            audit_record['metadata'] = metadata
        
        return audit_record
    
    @staticmethod
    def compute_hash_chain(
        audit_record: Dict[str, Any],
        previous_hash: Optional[str] = None
    ) -> str:
        """
        Compute cryptographic hash for audit chain.
        
        Args:
            audit_record: Canonical audit record dictionary
            previous_hash: Hash of the previous audit log entry
            
        Returns:
            SHA-256 hash in lowercase hexadecimal format (64 characters)
        """
        # Create canonical JSON representation
        canonical_json = CanonicalJSONEncoder.canonicalize(audit_record)
        
        # Create chain input by combining previous hash with current record
        if previous_hash:
            chain_input = f"{previous_hash}:{canonical_json}"
        else:
            # First entry in chain - no previous hash
            chain_input = canonical_json
        
        # Compute SHA-256 hash
        return hashlib.sha256(chain_input.encode('utf-8')).hexdigest()
    
    @staticmethod
    def verify_hash_chain(
        current_hash: str,
        audit_record: Dict[str, Any],
        previous_hash: Optional[str] = None
    ) -> bool:
        """
        Verify integrity of audit chain hash.
        
        Args:
            current_hash: Hash to verify
            audit_record: Audit record that generated the hash
            previous_hash: Previous hash in the chain
            
        Returns:
            True if hash is valid, False otherwise
        """
        expected_hash = AuditChainManager.compute_hash_chain(audit_record, previous_hash)
        return current_hash == expected_hash
    
    @staticmethod
    def create_field_changes(
        old_values: Dict[str, Any],
        new_values: Dict[str, Any],
        exclude_fields: Optional[set] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Create field-level change tracking for audit records.
        
        Args:
            old_values: Previous field values
            new_values: New field values  
            exclude_fields: Set of field names to exclude from tracking
            
        Returns:
            Dictionary of field changes in format:
            {
                "field_name": {
                    "old": old_value,
                    "new": new_value
                }
            }
        """
        if exclude_fields is None:
            exclude_fields = {
                'updated_at', 'last_login_at', 'created_at',  # Timestamp fields
                'password_hash', 'refresh_token_hash',        # Security fields
                'chain_hash', 'prev_chain_hash'               # Audit fields
            }
        
        changes = {}
        
        # Find all field names
        all_fields = set(old_values.keys()) | set(new_values.keys())
        
        for field in all_fields:
            if field in exclude_fields:
                continue
            
            old_value = old_values.get(field)
            new_value = new_values.get(field)
            
            # Only record actual changes
            if old_value != new_value:
                changes[field] = {
                    'old': old_value,
                    'new': new_value
                }
        
        return changes
    
    @staticmethod
    def sanitize_for_audit(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize data for audit trail - remove sensitive information.
        
        Args:
            data: Data dictionary to sanitize
            
        Returns:
            Sanitized data safe for audit trail
        """
        sensitive_fields = {
            'password_hash', 'refresh_token_hash', 'access_token_jti',
            'provider_ref', 'api_key', 'secret_key', 'private_key',
            'credit_card_number', 'ssn', 'tax_number'
        }
        
        sanitized = {}
        for key, value in data.items():
            if key in sensitive_fields:
                # Replace sensitive data with metadata
                if value:
                    sanitized[key] = f"[REDACTED_{type(value).__name__.upper()}]"
                else:
                    sanitized[key] = None
            else:
                sanitized[key] = value
        
        return sanitized


# Turkish compliance helpers
class TurkishComplianceHelper:
    """Helper utilities for Turkish regulatory compliance."""
    
    @staticmethod
    def validate_vkn(vkn: str) -> bool:
        """
        Validate Turkish tax number (VKN - Vergi Kimlik Numarası).
        
        Args:
            vkn: Turkish tax number to validate
            
        Returns:
            True if valid VKN format
        """
        if not vkn or not isinstance(vkn, str):
            return False
        
        # Remove spaces and non-digits
        vkn = ''.join(filter(str.isdigit, vkn))
        
        # VKN must be exactly 10 digits
        if len(vkn) != 10:
            return False
        
        # Cannot start with 0
        if vkn[0] == '0':
            return False
        
        # VKN checksum validation algorithm
        try:
            digits = [int(d) for d in vkn]
            
            # Calculate checksum
            total = 0
            for i in range(9):
                total += digits[i] * (10 - i)
            
            check_digit = total % 11
            if check_digit < 2:
                return check_digit == digits[9]
            else:
                return (11 - check_digit) == digits[9]
                
        except (ValueError, IndexError):
            return False
    
    @staticmethod
    def validate_tckn(tckn: str) -> bool:
        """
        Validate Turkish citizen ID (TCKN - T.C. Kimlik Numarası).
        
        Args:
            tckn: Turkish citizen ID to validate
            
        Returns:
            True if valid TCKN format
        """
        if not tckn or not isinstance(tckn, str):
            return False
        
        # Remove spaces and non-digits
        tckn = ''.join(filter(str.isdigit, tckn))
        
        # TCKN must be exactly 11 digits
        if len(tckn) != 11:
            return False
        
        # Cannot start with 0
        if tckn[0] == '0':
            return False
        
        # TCKN checksum validation algorithm
        try:
            digits = [int(d) for d in tckn]
            
            # Calculate checksums
            odd_sum = sum(digits[i] for i in range(0, 9, 2))  # 1st, 3rd, 5th, 7th, 9th
            even_sum = sum(digits[i] for i in range(1, 8, 2))  # 2nd, 4th, 6th, 8th
            
            # Check 10th digit
            check10 = ((odd_sum * 7) - even_sum) % 10
            if check10 != digits[9]:
                return False
            
            # Check 11th digit
            check11 = (odd_sum + even_sum + digits[9]) % 10
            return check11 == digits[10]
            
        except (ValueError, IndexError):
            return False
    
    @staticmethod
    def format_turkish_currency(amount_cents: int) -> str:
        """
        Format amount in cents as Turkish Lira currency.
        
        Args:
            amount_cents: Amount in cents
            
        Returns:
            Formatted currency string (e.g., "1.234,56 TL")
        """
        if amount_cents is None:
            return "0,00 TL"
        
        # Convert cents to lira
        lira = abs(amount_cents) / 100
        
        # Format with Turkish number conventions (comma for decimal, dot for thousands)
        formatted = f"{lira:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        
        # Add currency symbol and negative sign if needed
        sign = '-' if amount_cents < 0 else ''
        return f"{sign}{formatted} TL"


# Export main classes and functions
__all__ = [
    'CanonicalJSONEncoder',
    'AuditChainManager', 
    'TurkishComplianceHelper'
]