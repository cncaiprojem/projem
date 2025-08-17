"""
Integration tests for audit and security system.
Tests the complete enterprise audit trail and security monitoring integration.
"""

import hashlib
import json
import pytest
from datetime import datetime, timezone
from typing import Dict, Any, List

from app.models.audit_log import AuditLog
from app.models.security_event import SecurityEvent
from app.models.user import User


class TestAuditSecurityIntegration:
    """Integration tests for audit and security systems."""
    
    def test_complete_audit_chain_integrity(self):
        """Test complete audit chain with multiple entries."""
        # Create a series of audit entries simulating real enterprise usage
        audit_entries = []
        
        # Genesis entry (system startup)
        genesis_payload = {
            "event": "SYSTEM_STARTUP",
            "version": "1.0.0",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        genesis_hash = AuditLog.compute_chain_hash(
            AuditLog.get_genesis_hash(), 
            genesis_payload
        )
        
        genesis_entry = AuditLog(
            scope_type="system",
            scope_id=None,
            actor_user_id=None,
            event_type="SYSTEM_STARTUP",
            payload=genesis_payload,
            prev_chain_hash=AuditLog.get_genesis_hash(),
            chain_hash=genesis_hash,
            created_at=datetime.now(timezone.utc)
        )
        audit_entries.append(genesis_entry)
        
        # User creation event
        user_create_payload = {
            "entity": "user",
            "entity_id": 1,
            "action": "CREATE",
            "data": {
                "email": "admin@freecad.com",
                "role": "admin",
                "created_by": "system"
            }
        }
        user_create_hash = AuditLog.compute_chain_hash(
            genesis_hash,
            user_create_payload
        )
        
        user_create_entry = AuditLog(
            scope_type="user",
            scope_id=1,
            actor_user_id=None,  # System created
            event_type="USER_CREATE",
            payload=user_create_payload,
            prev_chain_hash=genesis_hash,
            chain_hash=user_create_hash,
            created_at=datetime.now(timezone.utc)
        )
        audit_entries.append(user_create_entry)
        
        # Job creation event
        job_create_payload = {
            "entity": "job",
            "entity_id": 101,
            "action": "CREATE",
            "data": {
                "type": "CAD_GENERATE",
                "priority": "high",
                "params": {
                    "model_type": "part",
                    "material": "aluminum"
                }
            }
        }
        job_create_hash = AuditLog.compute_chain_hash(
            user_create_hash,
            job_create_payload
        )
        
        job_create_entry = AuditLog(
            scope_type="job",
            scope_id=101,
            actor_user_id=1,  # Created by admin
            event_type="JOB_CREATE",
            payload=job_create_payload,
            prev_chain_hash=user_create_hash,
            chain_hash=job_create_hash,
            created_at=datetime.now(timezone.utc)
        )
        audit_entries.append(job_create_entry)
        
        # Payment processing event
        payment_payload = {
            "entity": "payment",
            "entity_id": 501,
            "action": "PROCESS",
            "data": {
                "amount_cents": 10000,  # $100.00
                "currency": "TRY",
                "method": "credit_card",
                "status": "completed"
            }
        }
        payment_hash = AuditLog.compute_chain_hash(
            job_create_hash,
            payment_payload
        )
        
        payment_entry = AuditLog(
            scope_type="payment",
            scope_id=501,
            actor_user_id=1,
            event_type="PAYMENT_PROCESS",
            payload=payment_payload,
            prev_chain_hash=job_create_hash,
            chain_hash=payment_hash,
            created_at=datetime.now(timezone.utc)
        )
        audit_entries.append(payment_entry)
        
        # Verify entire chain integrity
        for i, entry in enumerate(audit_entries):
            prev_entry = audit_entries[i-1] if i > 0 else None
            assert entry.verify_chain_integrity(prev_entry), f"Chain integrity failed at entry {i}"
        
        # Verify chain properties
        assert len(audit_entries) == 4
        assert audit_entries[0].is_system_action
        assert audit_entries[1].is_system_action
        assert audit_entries[2].is_user_action
        assert audit_entries[3].is_user_action
        
        # Test payload field access
        assert payment_entry.get_payload_field("data.amount_cents") == 10000
        assert payment_entry.get_payload_field("data.currency") == "TRY"
        assert payment_entry.get_payload_field("nonexistent.field") is None
    
    def test_security_event_patterns(self):
        """Test various security event patterns for enterprise monitoring."""
        security_events = []
        
        # Failed login attempt
        failed_login = SecurityEvent.create_login_failed(
            user_id=None,  # Unknown user
            ip="203.0.113.100",
            ua="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/96.0"
        )
        security_events.append(failed_login)
        
        # Brute force detection
        for i in range(5):
            brute_force_event = SecurityEvent(
                user_id=None,
                type="BRUTE_FORCE_ATTEMPT",
                ip="203.0.113.100",  # Same IP
                ua="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/96.0",
                created_at=datetime.now(timezone.utc)
            )
            security_events.append(brute_force_event)
        
        # Access denied events
        access_denied = SecurityEvent.create_access_denied(
            user_id=123,
            ip="192.168.1.50",
            ua="FreeCAD-Client/1.0"
        )
        security_events.append(access_denied)
        
        # Suspicious activity detection
        suspicious = SecurityEvent.create_suspicious_activity(
            user_id=123,
            activity_type="multiple_locations",
            ip="10.0.0.200",
            ua="Mobile-App/2.0"
        )
        security_events.append(suspicious)
        
        # Verify event properties
        assert len(security_events) == 8  # 1 failed + 5 brute force + 1 access denied + 1 suspicious
        
        # Count by type
        login_related_count = sum(1 for event in security_events if event.is_login_related())
        access_related_count = sum(1 for event in security_events if event.is_access_related())
        suspicious_count = sum(1 for event in security_events if event.is_suspicious())
        
        assert login_related_count >= 1  # At least the failed login
        assert access_related_count >= 1  # At least the access denied
        assert suspicious_count >= 6  # Brute force + suspicious activity
        
        # Verify IP patterns
        ip_counts = {}
        for event in security_events:
            if event.ip:
                ip_counts[event.ip] = ip_counts.get(event.ip, 0) + 1
        
        # Should detect multiple events from same IP (brute force pattern)
        assert any(count > 1 for count in ip_counts.values())
    
    def test_audit_and_security_correlation(self):
        """Test correlation between audit logs and security events."""
        # Simulate a security incident with audit trail
        
        # 1. Failed login attempt (security event)
        failed_login = SecurityEvent.create_login_failed(
            user_id=456,
            ip="198.51.100.50",
            ua="Automated-Bot/1.0"
        )
        
        # 2. Audit log for the failed login
        login_attempt_payload = {
            "event": "LOGIN_ATTEMPT",
            "user_id": 456,
            "ip": "198.51.100.50",
            "result": "failed",
            "reason": "invalid_credentials",
            "security_event_id": 1  # Would reference the security event
        }
        login_audit_hash = AuditLog.compute_chain_hash(
            AuditLog.get_genesis_hash(),
            login_attempt_payload
        )
        
        login_audit = AuditLog(
            scope_type="authentication",
            scope_id=456,
            actor_user_id=456,
            event_type="LOGIN_FAILED",
            payload=login_attempt_payload,
            prev_chain_hash=AuditLog.get_genesis_hash(),
            chain_hash=login_audit_hash,
            created_at=datetime.now(timezone.utc)
        )
        
        # 3. Account lockout (security event)
        account_lockout = SecurityEvent(
            user_id=456,
            type="ACCOUNT_LOCKED",
            ip="198.51.100.50",
            ua="Automated-Bot/1.0",
            created_at=datetime.now(timezone.utc)
        )
        
        # 4. Audit log for account lockout
        lockout_payload = {
            "event": "ACCOUNT_LOCKOUT",
            "user_id": 456,
            "reason": "multiple_failed_attempts",
            "trigger_ip": "198.51.100.50",
            "security_event_id": 2  # Would reference the lockout event
        }
        lockout_audit_hash = AuditLog.compute_chain_hash(
            login_audit_hash,
            lockout_payload
        )
        
        lockout_audit = AuditLog(
            scope_type="user",
            scope_id=456,
            actor_user_id=None,  # System action
            event_type="ACCOUNT_LOCKOUT",
            payload=lockout_payload,
            prev_chain_hash=login_audit_hash,
            chain_hash=lockout_audit_hash,
            created_at=datetime.now(timezone.utc)
        )
        
        # Verify correlation
        assert failed_login.type == "LOGIN_FAILED"
        assert failed_login.user_id == 456
        assert failed_login.ip == "198.51.100.50"
        
        assert login_audit.scope_id == 456
        assert login_audit.get_payload_field("ip") == "198.51.100.50"
        assert login_audit.get_payload_field("result") == "failed"
        
        assert account_lockout.type == "ACCOUNT_LOCKED"
        assert account_lockout.user_id == 456
        
        assert lockout_audit.scope_id == 456
        assert lockout_audit.get_payload_field("user_id") == 456
        assert lockout_audit.get_payload_field("trigger_ip") == "198.51.100.50"
        
        # Verify audit chain integrity
        assert login_audit.verify_chain_integrity(None)
        assert lockout_audit.verify_chain_integrity(login_audit)
    
    def test_enterprise_compliance_patterns(self):
        """Test patterns required for enterprise compliance (GDPR/KVKK)."""
        # Data processing audit trail
        gdpr_events = []
        
        # User consent granted
        consent_payload = {
            "event": "CONSENT_GRANTED",
            "user_id": 789,
            "consent_type": "data_processing",
            "purposes": ["service_provision", "analytics"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ip": "192.168.1.100",
            "legal_basis": "consent"
        }
        
        consent_hash = AuditLog.compute_chain_hash(
            AuditLog.get_genesis_hash(),
            consent_payload
        )
        
        consent_audit = AuditLog(
            scope_type="privacy",
            scope_id=789,
            actor_user_id=789,
            event_type="CONSENT_GRANTED",
            payload=consent_payload,
            prev_chain_hash=AuditLog.get_genesis_hash(),
            chain_hash=consent_hash,
            created_at=datetime.now(timezone.utc)
        )
        gdpr_events.append(consent_audit)
        
        # Data processing activity
        processing_payload = {
            "event": "DATA_PROCESSING",
            "user_id": 789,
            "processing_type": "model_generation",
            "data_categories": ["design_parameters", "user_preferences"],
            "purpose": "service_provision",
            "retention_period": "7_years",
            "processor": "freecad_engine"
        }
        
        processing_hash = AuditLog.compute_chain_hash(
            consent_hash,
            processing_payload
        )
        
        processing_audit = AuditLog(
            scope_type="privacy",
            scope_id=789,
            actor_user_id=None,  # System processing
            event_type="DATA_PROCESSING",
            payload=processing_payload,
            prev_chain_hash=consent_hash,
            chain_hash=processing_hash,
            created_at=datetime.now(timezone.utc)
        )
        gdpr_events.append(processing_audit)
        
        # Data export request
        export_payload = {
            "event": "DATA_EXPORT_REQUEST",
            "user_id": 789,
            "request_type": "full_export",
            "formats": ["json", "pdf"],
            "delivery_method": "email",
            "status": "processing"
        }
        
        export_hash = AuditLog.compute_chain_hash(
            processing_hash,
            export_payload
        )
        
        export_audit = AuditLog(
            scope_type="privacy",
            scope_id=789,
            actor_user_id=789,
            event_type="DATA_EXPORT_REQUEST",
            payload=export_payload,
            prev_chain_hash=processing_hash,
            chain_hash=export_hash,
            created_at=datetime.now(timezone.utc)
        )
        gdpr_events.append(export_audit)
        
        # Verify GDPR compliance chain
        for i, audit in enumerate(gdpr_events):
            prev_audit = gdpr_events[i-1] if i > 0 else None
            assert audit.verify_chain_integrity(prev_audit)
        
        # Verify GDPR data fields
        assert consent_audit.get_payload_field("legal_basis") == "consent"
        assert consent_audit.get_payload_field("purposes") == ["service_provision", "analytics"]
        
        assert processing_audit.get_payload_field("data_categories") == ["design_parameters", "user_preferences"]
        assert processing_audit.get_payload_field("retention_period") == "7_years"
        
        assert export_audit.get_payload_field("formats") == ["json", "pdf"]
        assert export_audit.get_payload_field("delivery_method") == "email"
    
    def test_financial_audit_precision(self):
        """Test financial audit logging with enterprise precision."""
        # Financial transaction with Turkish compliance
        financial_payload = {
            "transaction": {
                "id": "TXN-2025-001",
                "type": "service_payment",
                "amount_cents": 50000,  # 500.00 TRY
                "currency": "TRY",
                "tax_rate": "20.00",  # Turkish KDV
                "tax_amount_cents": 10000,  # 100.00 TRY
                "net_amount_cents": 40000,  # 400.00 TRY
                "customer": {
                    "id": 123,
                    "tax_number": "1234567890",
                    "type": "corporate"
                },
                "items": [
                    {
                        "description": "CAD Model Generation Service",
                        "quantity": 1,
                        "unit_price_cents": 40000,
                        "total_cents": 40000
                    }
                ]
            },
            "compliance": {
                "invoice_number": "FC-2025-001",
                "e_invoice": True,
                "turkish_compliance": True,
                "kdv_applied": True
            }
        }
        
        financial_hash = AuditLog.compute_chain_hash(
            AuditLog.get_genesis_hash(),
            financial_payload
        )
        
        financial_audit = AuditLog(
            scope_type="financial",
            scope_id=123,
            actor_user_id=1,
            event_type="PAYMENT_PROCESSED",
            payload=financial_payload,
            prev_chain_hash=AuditLog.get_genesis_hash(),
            chain_hash=financial_hash,
            created_at=datetime.now(timezone.utc)
        )
        
        # Verify financial precision
        assert financial_audit.get_payload_field("transaction.amount_cents") == 50000
        assert financial_audit.get_payload_field("transaction.currency") == "TRY"
        assert financial_audit.get_payload_field("transaction.tax_rate") == "20.00"
        assert financial_audit.get_payload_field("compliance.turkish_compliance") is True
        assert financial_audit.get_payload_field("compliance.kdv_applied") is True
        
        # Verify hash integrity with complex financial data
        assert financial_audit.verify_chain_integrity(None)
        
        # Test hash consistency with financial precision
        same_hash = AuditLog.compute_chain_hash(
            AuditLog.get_genesis_hash(),
            financial_payload
        )
        assert financial_hash == same_hash
    
    def test_unicode_and_turkish_support(self):
        """Test Unicode and Turkish language support in audit logs."""
        turkish_payload = {
            "kullanıcı": {
                "adı": "Ahmet Öztürk",
                "email": "ahmet@freecad.com.tr",
                "şehir": "İstanbul",
                "açıklama": "CAD mühendisi ve uzman kullanıcı"
            },
            "işlem": {
                "türü": "model_oluşturma",
                "açıklama": "3D parça modeli oluşturuldu",
                "malzeme": "alüminyum",
                "özellikler": ["hassas", "dayanıklı", "hafif"]
            },
            "mesaj": "İşlem başarıyla tamamlandı ✓",
            "emoji_test": "🔧⚙️🏭",
            "çok_dil": {
                "türkçe": "Merhaba dünya",
                "english": "Hello world", 
                "中文": "你好世界",
                "العربية": "مرحبا بالعالم"
            }
        }
        
        turkish_hash = AuditLog.compute_chain_hash(
            AuditLog.get_genesis_hash(),
            turkish_payload
        )
        
        turkish_audit = AuditLog(
            scope_type="kullanıcı",
            scope_id=999,
            actor_user_id=999,
            event_type="MODEL_OLUŞTURULDU",
            payload=turkish_payload,
            prev_chain_hash=AuditLog.get_genesis_hash(),
            chain_hash=turkish_hash,
            created_at=datetime.now(timezone.utc)
        )
        
        # Verify Turkish content
        assert turkish_audit.get_payload_field("kullanıcı.adı") == "Ahmet Öztürk"
        assert turkish_audit.get_payload_field("kullanıcı.şehir") == "İstanbul"
        assert turkish_audit.get_payload_field("işlem.türü") == "model_oluşturma"
        assert turkish_audit.get_payload_field("mesaj") == "İşlem başarıyla tamamlandı ✓"
        assert turkish_audit.get_payload_field("emoji_test") == "🔧⚙️🏭"
        
        # Verify multilingual support
        assert turkish_audit.get_payload_field("çok_dil.türkçe") == "Merhaba dünya"
        assert turkish_audit.get_payload_field("çok_dil.中文") == "你好世界"
        assert turkish_audit.get_payload_field("çok_dil.العربية") == "مرحبا بالعالم"
        
        # Verify hash integrity with Unicode
        assert turkish_audit.verify_chain_integrity(None)
        
        # Test hash consistency with Unicode
        same_hash = AuditLog.compute_chain_hash(
            AuditLog.get_genesis_hash(),
            turkish_payload
        )
        assert turkish_hash == same_hash