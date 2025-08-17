"""
Test suite for audit log hash-chain integrity functionality.
Tests the cryptographic hash-chain implementation for regulatory compliance.
"""

import hashlib
import json
import pytest
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from app.models.audit_log import AuditLog


class TestAuditLogHashChain:
    """Test hash-chain functionality in audit logs."""
    
    def test_compute_chain_hash_empty_payload(self):
        """Test hash computation with empty payload."""
        prev_hash = "0" * 64
        payload = None
        
        expected_hash = hashlib.sha256(prev_hash.encode('utf-8')).hexdigest()
        actual_hash = AuditLog.compute_chain_hash(prev_hash, payload)
        
        assert actual_hash == expected_hash
        assert len(actual_hash) == 64
        assert all(c in '0123456789abcdef' for c in actual_hash)
    
    def test_compute_chain_hash_with_payload(self):
        """Test hash computation with structured payload."""
        prev_hash = "a" * 64
        payload = {
            "action": "CREATE",
            "entity": "job",
            "entity_id": 123,
            "changes": {
                "status": {"old": None, "new": "pending"},
                "priority": {"old": None, "new": "high"}
            }
        }
        
        # Create canonical JSON
        canonical_json = json.dumps(
            payload,
            sort_keys=True,
            separators=(',', ':'),
            ensure_ascii=False
        )
        
        expected_input = prev_hash + canonical_json
        expected_hash = hashlib.sha256(expected_input.encode('utf-8')).hexdigest()
        
        actual_hash = AuditLog.compute_chain_hash(prev_hash, payload)
        
        assert actual_hash == expected_hash
        assert len(actual_hash) == 64
    
    def test_compute_chain_hash_consistent(self):
        """Test that hash computation is consistent for same input."""
        prev_hash = "f" * 64
        payload = {"test": "data", "number": 42}
        
        hash1 = AuditLog.compute_chain_hash(prev_hash, payload)
        hash2 = AuditLog.compute_chain_hash(prev_hash, payload)
        
        assert hash1 == hash2
    
    def test_compute_chain_hash_different_for_different_payload(self):
        """Test that different payloads produce different hashes."""
        prev_hash = "b" * 64
        payload1 = {"action": "CREATE"}
        payload2 = {"action": "UPDATE"}
        
        hash1 = AuditLog.compute_chain_hash(prev_hash, payload1)
        hash2 = AuditLog.compute_chain_hash(prev_hash, payload2)
        
        assert hash1 != hash2
    
    def test_compute_chain_hash_order_independence(self):
        """Test that JSON key order doesn't affect hash."""
        prev_hash = "c" * 64
        payload1 = {"b": 2, "a": 1}
        payload2 = {"a": 1, "b": 2}
        
        hash1 = AuditLog.compute_chain_hash(prev_hash, payload1)
        hash2 = AuditLog.compute_chain_hash(prev_hash, payload2)
        
        assert hash1 == hash2  # Should be same due to sort_keys=True
    
    def test_genesis_hash(self):
        """Test genesis hash generation."""
        genesis = AuditLog.get_genesis_hash()
        
        assert genesis == "0" * 64
        assert len(genesis) == 64
    
    def test_verify_chain_integrity_genesis(self):
        """Test chain verification for genesis entry."""
        audit_log = AuditLog(
            scope_type="system",
            scope_id=None,
            actor_user_id=None,
            event_type="SYSTEM_START",
            payload={"message": "System initialized"},
            prev_chain_hash="0" * 64,
            chain_hash=AuditLog.compute_chain_hash("0" * 64, {"message": "System initialized"}),
            created_at=datetime.now(timezone.utc)
        )
        
        # Genesis entry should verify with None as previous
        assert audit_log.verify_chain_integrity(None)
    
    def test_verify_chain_integrity_valid_chain(self):
        """Test chain verification for valid sequence."""
        # Create first entry
        payload1 = {"action": "CREATE", "entity": "user"}
        chain_hash1 = AuditLog.compute_chain_hash("0" * 64, payload1)
        
        entry1 = AuditLog(
            scope_type="user",
            scope_id=1,
            actor_user_id=None,
            event_type="CREATE",
            payload=payload1,
            prev_chain_hash="0" * 64,
            chain_hash=chain_hash1,
            created_at=datetime.now(timezone.utc)
        )
        
        # Create second entry
        payload2 = {"action": "UPDATE", "entity": "user"}
        chain_hash2 = AuditLog.compute_chain_hash(chain_hash1, payload2)
        
        entry2 = AuditLog(
            scope_type="user",
            scope_id=1,
            actor_user_id=1,
            event_type="UPDATE",
            payload=payload2,
            prev_chain_hash=chain_hash1,
            chain_hash=chain_hash2,
            created_at=datetime.now(timezone.utc)
        )
        
        # Both should verify
        assert entry1.verify_chain_integrity(None)
        assert entry2.verify_chain_integrity(entry1)
    
    def test_verify_chain_integrity_broken_prev_hash(self):
        """Test chain verification fails with incorrect prev_hash."""
        # Create first entry
        payload1 = {"action": "CREATE"}
        chain_hash1 = AuditLog.compute_chain_hash("0" * 64, payload1)
        
        entry1 = AuditLog(
            scope_type="user",
            scope_id=1,
            actor_user_id=None,
            event_type="CREATE",
            payload=payload1,
            prev_chain_hash="0" * 64,
            chain_hash=chain_hash1,
            created_at=datetime.now(timezone.utc)
        )
        
        # Create second entry with wrong prev_hash
        payload2 = {"action": "UPDATE"}
        chain_hash2 = AuditLog.compute_chain_hash("x" * 64, payload2)  # Wrong prev hash
        
        entry2 = AuditLog(
            scope_type="user",
            scope_id=1,
            actor_user_id=1,
            event_type="UPDATE",
            payload=payload2,
            prev_chain_hash="x" * 64,  # Should be chain_hash1
            chain_hash=chain_hash2,
            created_at=datetime.now(timezone.utc)
        )
        
        # Second entry should fail verification
        assert entry1.verify_chain_integrity(None)
        assert not entry2.verify_chain_integrity(entry1)
    
    def test_verify_chain_integrity_tampered_payload(self):
        """Test chain verification fails with tampered payload."""
        # Create entry with correct hash
        payload = {"action": "CREATE", "amount": 100}
        chain_hash = AuditLog.compute_chain_hash("0" * 64, payload)
        
        entry = AuditLog(
            scope_type="payment",
            scope_id=1,
            actor_user_id=1,
            event_type="CREATE",
            payload=payload,
            prev_chain_hash="0" * 64,
            chain_hash=chain_hash,
            created_at=datetime.now(timezone.utc)
        )
        
        # Tamper with payload after creation
        entry.payload = {"action": "CREATE", "amount": 1000}  # Changed amount
        
        # Should fail verification due to tampered payload
        assert not entry.verify_chain_integrity(None)
    
    def test_payload_field_operations(self):
        """Test payload field helper methods."""
        payload = {
            "user": {"id": 123, "email": "test@example.com"},
            "metadata": {"source": "api", "version": "1.0"},
            "changes": [{"field": "status", "old": "draft", "new": "active"}]
        }
        
        audit_log = AuditLog(
            scope_type="user",
            scope_id=123,
            actor_user_id=1,
            event_type="UPDATE",
            payload=payload,
            prev_chain_hash="0" * 64,
            chain_hash="test_hash" * 8,  # 64 chars
            created_at=datetime.now(timezone.utc)
        )
        
        # Test get_payload_field
        assert audit_log.get_payload_field("user.id") == 123
        assert audit_log.get_payload_field("user.email") == "test@example.com"
        assert audit_log.get_payload_field("metadata.source") == "api"
        assert audit_log.get_payload_field("nonexistent", "default") == "default"
        
        # Test add_payload_field
        audit_log.add_payload_field("new.nested.field", "value")
        assert audit_log.payload["new"]["nested"]["field"] == "value"
        
        audit_log.add_payload_field("top_level", 42)
        assert audit_log.payload["top_level"] == 42
    
    def test_payload_field_operations_empty_payload(self):
        """Test payload operations with initially empty payload."""
        audit_log = AuditLog(
            scope_type="system",
            scope_id=None,
            actor_user_id=None,
            event_type="TEST",
            payload=None,
            prev_chain_hash="0" * 64,
            chain_hash="test_hash" * 8,
            created_at=datetime.now(timezone.utc)
        )
        
        # Test get with empty payload
        assert audit_log.get_payload_field("any.field") is None
        assert audit_log.get_payload_field("any.field", "default") == "default"
        
        # Test add with empty payload
        audit_log.add_payload_field("first.field", "value")
        assert audit_log.payload == {"first": {"field": "value"}}
    
    def test_audit_log_properties(self):
        """Test audit log property methods."""
        # System action (no user)
        system_log = AuditLog(
            scope_type="system",
            scope_id=None,
            actor_user_id=None,
            event_type="MAINTENANCE",
            payload=None,
            prev_chain_hash="0" * 64,
            chain_hash="test_hash" * 8,
            created_at=datetime.now(timezone.utc)
        )
        
        assert system_log.is_system_action
        assert not system_log.is_user_action
        
        # User action
        user_log = AuditLog(
            scope_type="job",
            scope_id=123,
            actor_user_id=456,
            event_type="CREATE",
            payload=None,
            prev_chain_hash="test_hash" * 8,
            chain_hash="next_hash" * 8,
            created_at=datetime.now(timezone.utc)
        )
        
        assert not user_log.is_system_action
        assert user_log.is_user_action
    
    def test_repr(self):
        """Test string representation."""
        audit_log = AuditLog(
            id=123,
            scope_type="job",
            scope_id=456,
            actor_user_id=789,
            event_type="UPDATE",
            payload=None,
            prev_chain_hash="0" * 64,
            chain_hash="test_hash" * 8,
            created_at=datetime.now(timezone.utc)
        )
        
        repr_str = repr(audit_log)
        assert "AuditLog" in repr_str
        assert "id=123" in repr_str
        assert "event_type='UPDATE'" in repr_str
        assert "scope=job:456" in repr_str
    
    def test_hash_chain_with_unicode(self):
        """Test hash chain works correctly with Unicode characters."""
        prev_hash = "0" * 64
        payload = {
            "message": "Kullanıcı oluşturuldu",  # Turkish text
            "description": "İş tamamlandı ✓",     # Turkish + emoji
            "data": {"türk": "değer", "中文": "数据"}  # Mixed scripts
        }
        
        hash1 = AuditLog.compute_chain_hash(prev_hash, payload)
        hash2 = AuditLog.compute_chain_hash(prev_hash, payload)
        
        # Should be consistent
        assert hash1 == hash2
        assert len(hash1) == 64
        
        # Verify it produces valid audit log
        audit_log = AuditLog(
            scope_type="user",
            scope_id=1,
            actor_user_id=1,
            event_type="CREATE",
            payload=payload,
            prev_chain_hash=prev_hash,
            chain_hash=hash1,
            created_at=datetime.now(timezone.utc)
        )
        
        assert audit_log.verify_chain_integrity(None)