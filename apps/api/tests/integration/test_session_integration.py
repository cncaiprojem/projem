"""
Integration tests for ultra enterprise session management (Task 3.2).
Tests complete session lifecycle with database transactions and security events.
"""

import pytest
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session as DBSession

from app.models.session import Session
from app.models.user import User
from app.models.security_event import SecurityEvent
from app.models.audit_log import AuditLog
from app.services.session_service import SessionService, SessionSecurityError
from app.services.auth_service import AuthService
from tests.utils.migration_test_helpers import create_test_user


class TestSessionIntegration:
    """Integration tests for complete session management workflows."""

    def setup_method(self):
        """Set up test services."""
        self.session_service = SessionService()
        self.auth_service = AuthService()
        self.session_service.session_secret = "test-secret-key-for-integration"

    def test_complete_session_lifecycle(self, db: DBSession):
        """Test complete session lifecycle from creation to cleanup."""
        # Create user
        user = create_test_user(db, email="lifecycle@example.com")

        # 1. Create session
        session, refresh_token = self.session_service.create_session(
            db=db,
            user_id=user.id,
            device_fingerprint="lifecycle-device",
            ip_address="203.0.113.10",
            user_agent="Mozilla/5.0 Integration Test",
        )

        assert session.is_active is True
        assert len(refresh_token) > 50

        # Verify database state
        db_session = db.query(Session).filter(Session.id == session.id).first()
        assert db_session is not None
        assert db_session.user_id == user.id

        # Verify security event
        create_events = (
            db.query(SecurityEvent)
            .filter(SecurityEvent.user_id == user.id, SecurityEvent.type == "SESSION_CREATED")
            .all()
        )
        assert len(create_events) == 1

        # 2. Use session (simulate token lookup)
        retrieved_session = self.session_service.get_session_by_token(db, refresh_token)
        assert retrieved_session is not None
        assert retrieved_session.id == session.id

        # 3. Rotate session
        new_session, new_token = self.session_service.rotate_session(
            db=db,
            current_refresh_token=refresh_token,
            device_fingerprint="lifecycle-device",
            ip_address="203.0.113.10",
            user_agent="Mozilla/5.0 Integration Test",
        )

        # Verify rotation
        assert new_session.id != session.id
        assert new_session.rotated_from == session.id
        assert new_token != refresh_token

        # Verify old session is revoked
        db.refresh(session)
        assert session.revoked_at is not None
        assert session.revocation_reason == "rotation"

        # Verify rotation event
        rotate_events = (
            db.query(SecurityEvent)
            .filter(SecurityEvent.user_id == user.id, SecurityEvent.type == "SESSION_ROTATED")
            .all()
        )
        assert len(rotate_events) == 1

        # 4. Manual revocation
        revoke_success = self.session_service.revoke_session(
            db=db, session_id=new_session.id, reason="user_logout", ip_address="203.0.113.10"
        )

        assert revoke_success is True

        # Verify revocation
        db.refresh(new_session)
        assert new_session.revoked_at is not None
        assert new_session.revocation_reason == "user_logout"

        # Verify revocation event
        revoke_events = (
            db.query(SecurityEvent)
            .filter(SecurityEvent.user_id == user.id, SecurityEvent.type == "SESSION_REVOKED")
            .all()
        )
        assert len(revoke_events) >= 1

        # 5. Verify old token is unusable
        old_session = self.session_service.get_session_by_token(db, refresh_token)
        assert old_session is None

        new_session_lookup = self.session_service.get_session_by_token(db, new_token)
        assert new_session_lookup is None  # Should be None after revocation

    def test_concurrent_session_management(self, db: DBSession):
        """Test managing multiple concurrent sessions for same user."""
        user = create_test_user(db, email="concurrent@example.com")

        # Create multiple sessions
        sessions = []
        tokens = []

        for i in range(3):
            session, token = self.session_service.create_session(
                db=db,
                user_id=user.id,
                device_fingerprint=f"device-{i}",
                ip_address=f"192.168.1.{100 + i}",
                user_agent=f"Browser-{i}",
            )
            sessions.append(session)
            tokens.append(token)

        # Verify all sessions are active
        active_sessions = self.session_service._get_active_sessions(db, user.id)
        assert len(active_sessions) == 3

        # Rotate one session
        rotated_session, new_token = self.session_service.rotate_session(
            db=db,
            current_refresh_token=tokens[1],
            device_fingerprint="device-1",
            ip_address="192.168.1.101",
        )

        # Verify rotation didn't affect other sessions
        active_sessions = self.session_service._get_active_sessions(db, user.id)
        assert len(active_sessions) == 3  # Still 3 (one rotated, creating new one)

        # Verify original session is revoked but others are active
        db.refresh(sessions[1])
        assert sessions[1].revoked_at is not None

        for i in [0, 2]:  # Other sessions should still be active
            db.refresh(sessions[i])
            assert sessions[i].is_active is True

        # Revoke all sessions except the rotated one
        revoked_count = self.session_service.revoke_all_user_sessions(
            db=db, user_id=user.id, reason="security_cleanup", except_session_id=rotated_session.id
        )

        assert revoked_count == 2  # Should revoke 2 remaining original sessions

        # Verify only rotated session is active
        active_sessions = self.session_service._get_active_sessions(db, user.id)
        assert len(active_sessions) == 1
        assert active_sessions[0].id == rotated_session.id

    def test_session_limit_enforcement(self, db: DBSession):
        """Test enforcement of maximum sessions per user."""
        user = create_test_user(db, email="limits@example.com")

        # Store original limit and set lower for testing
        original_limit = self.session_service.max_sessions_per_user
        self.session_service.max_sessions_per_user = 3

        try:
            # Create sessions up to limit
            sessions = []
            for i in range(3):
                session, _ = self.session_service.create_session(
                    db=db,
                    user_id=user.id,
                    device_fingerprint=f"limit-device-{i}",
                    ip_address="192.168.1.200",
                )
                sessions.append(session)

            # Verify all sessions are active
            active_sessions = self.session_service._get_active_sessions(db, user.id)
            assert len(active_sessions) == 3

            # Create one more session (should trigger limit enforcement)
            overflow_session, _ = self.session_service.create_session(
                db=db,
                user_id=user.id,
                device_fingerprint="overflow-device",
                ip_address="192.168.1.200",
            )

            # Should still have exactly the limit
            active_sessions = self.session_service._get_active_sessions(db, user.id)
            assert len(active_sessions) == 3

            # Oldest session should be revoked
            db.refresh(sessions[0])  # First created session
            assert sessions[0].revoked_at is not None

            # Verify limit exceeded event was logged
            limit_events = (
                db.query(SecurityEvent)
                .filter(
                    SecurityEvent.user_id == user.id, SecurityEvent.type == "SESSION_LIMIT_EXCEEDED"
                )
                .all()
            )
            assert len(limit_events) == 1

        finally:
            # Restore original limit
            self.session_service.max_sessions_per_user = original_limit

    def test_refresh_token_reuse_attack_simulation(self, db: DBSession):
        """Test defense against refresh token reuse attacks."""
        user = create_test_user(db, email="security@example.com")

        # Create session
        session, token = self.session_service.create_session(
            db=db, user_id=user.id, device_fingerprint="secure-device", ip_address="203.0.113.50"
        )

        # Simulate legitimate rotation
        new_session, new_token = self.session_service.rotate_session(
            db=db,
            current_refresh_token=token,
            device_fingerprint="secure-device",
            ip_address="203.0.113.50",
        )

        # Verify rotation worked
        assert new_session.rotated_from == session.id
        db.refresh(session)
        assert session.revoked_at is not None

        # Simulate attacker using old token (token reuse attack)
        with pytest.raises(SessionSecurityError) as exc_info:
            self.session_service.rotate_session(
                db=db,
                current_refresh_token=token,  # Using revoked token
                device_fingerprint="attacker-device",
                ip_address="203.0.113.99",
            )

        assert exc_info.value.code == "ERR-SESSION-INVALID-TOKEN"

        # Verify all user sessions were revoked as security measure
        active_sessions = self.session_service._get_active_sessions(db, user.id)
        assert len(active_sessions) == 0

        # Verify critical security event was logged
        reuse_events = (
            db.query(SecurityEvent)
            .filter(
                SecurityEvent.user_id == user.id,
                SecurityEvent.type == "REFRESH_TOKEN_REUSE_DETECTED",
            )
            .all()
        )
        assert len(reuse_events) == 1

        # Verify audit log was created
        security_audits = (
            db.query(AuditLog)
            .filter(AuditLog.actor_user_id == user.id, AuditLog.action == "security_breach")
            .all()
        )
        assert len(security_audits) == 1
        assert "GÜVENLIK UYARISI" in security_audits[0].description

    def test_device_fingerprint_security_analysis(self, db: DBSession):
        """Test device fingerprint analysis and security responses."""
        user1 = create_test_user(db, email="device1@example.com")
        user2 = create_test_user(db, email="device2@example.com")

        shared_fingerprint = "shared-device-fingerprint-123"

        # User1 creates session with device fingerprint
        session1, _ = self.session_service.create_session(
            db=db,
            user_id=user1.id,
            device_fingerprint=shared_fingerprint,
            ip_address="203.0.113.10",
            user_agent="Mozilla/5.0 User1",
        )

        # User2 creates session with same fingerprint (suspicious)
        session2, _ = self.session_service.create_session(
            db=db,
            user_id=user2.id,
            device_fingerprint=shared_fingerprint,
            ip_address="203.0.113.20",
            user_agent="Mozilla/5.0 User2",
        )

        # Verify suspicious device event was logged for user2
        suspicious_events = (
            db.query(SecurityEvent)
            .filter(
                SecurityEvent.user_id == user2.id,
                SecurityEvent.type == "SUSPICIOUS_DEVICE_DETECTED",
            )
            .all()
        )
        assert len(suspicious_events) == 1

        # Test device fingerprint mismatch during rotation
        session3, token3 = self.session_service.create_session(
            db=db, user_id=user1.id, device_fingerprint="original-device", ip_address="203.0.113.30"
        )

        # Rotate with different fingerprint
        new_session, _ = self.session_service.rotate_session(
            db=db,
            current_refresh_token=token3,
            device_fingerprint="different-device",
            ip_address="203.0.113.30",
        )

        # Verify device mismatch event
        mismatch_events = (
            db.query(SecurityEvent)
            .filter(
                SecurityEvent.user_id == user1.id, SecurityEvent.type == "SESSION_DEVICE_MISMATCH"
            )
            .all()
        )
        assert len(mismatch_events) == 1

        # Original session should be flagged as suspicious
        db.refresh(session3)
        assert session3.is_suspicious is True

    def test_session_expiration_and_cleanup(self, db: DBSession):
        """Test session expiration handling and cleanup processes."""
        user = create_test_user(db, email="expiry@example.com")

        # Create session with short expiration
        session, token = self.session_service.create_session(
            db=db, user_id=user.id, expires_in_hours=1, ip_address="192.168.1.100"
        )

        # Verify session is initially active
        assert session.is_active is True
        assert not session.is_expired

        # Manually expire session by setting past expiration
        session.expires_at = datetime.now(timezone.utc) - timedelta(minutes=30)
        db.commit()

        # Verify session is now expired
        db.refresh(session)
        assert session.is_expired is True
        assert not session.is_active  # Expired means not active

        # Try to use expired session token
        retrieved = self.session_service.get_session_by_token(db, token)
        assert retrieved is None  # Should not return expired session

        # Run cleanup process
        cleaned_count = self.session_service.cleanup_expired_sessions(db)
        assert cleaned_count == 1

        # Verify session is now revoked
        db.refresh(session)
        assert session.revoked_at is not None
        assert session.revocation_reason == "expired"

    def test_session_rotation_chain_tracking(self, db: DBSession):
        """Test session rotation chain tracking and limits."""
        user = create_test_user(db, email="rotation@example.com")

        # Create initial session
        current_session, current_token = self.session_service.create_session(
            db=db, user_id=user.id, device_fingerprint="rotation-device", ip_address="192.168.1.100"
        )

        # Perform multiple rotations to build chain
        rotation_count = 5
        for i in range(rotation_count):
            new_session, new_token = self.session_service.rotate_session(
                db=db,
                current_refresh_token=current_token,
                device_fingerprint="rotation-device",
                ip_address="192.168.1.100",
            )

            # Verify chain tracking
            assert new_session.rotated_from == current_session.id
            assert new_session.get_rotation_chain_length() == i + 1

            # Verify rotation event
            rotate_events = (
                db.query(SecurityEvent)
                .filter(SecurityEvent.user_id == user.id, SecurityEvent.type == "SESSION_ROTATED")
                .all()
            )
            assert len(rotate_events) == i + 1

            # Update for next iteration
            current_session = new_session
            current_token = new_token

        # Verify final chain length
        assert current_session.get_rotation_chain_length() == rotation_count

        # Verify all intermediate sessions are revoked
        all_sessions = (
            db.query(Session).filter(Session.user_id == user.id).order_by(Session.created_at).all()
        )

        assert len(all_sessions) == rotation_count + 1  # Original + rotations

        # All except the last should be revoked
        for session in all_sessions[:-1]:
            assert session.revoked_at is not None
            assert session.revocation_reason == "rotation"

        # Last session should be active
        assert all_sessions[-1].is_active is True

    def test_audit_trail_completeness(self, db: DBSession):
        """Test completeness of audit trail for session operations."""
        user = create_test_user(db, email="audit@example.com")

        # Create session
        session, token = self.session_service.create_session(
            db=db,
            user_id=user.id,
            device_fingerprint="audit-device",
            ip_address="203.0.113.100",
            user_agent="Mozilla/5.0 Audit Test",
        )

        # Rotate session
        new_session, new_token = self.session_service.rotate_session(
            db=db,
            current_refresh_token=token,
            device_fingerprint="audit-device",
            ip_address="203.0.113.100",
        )

        # Revoke session
        self.session_service.revoke_session(
            db=db, session_id=new_session.id, reason="audit_test", ip_address="203.0.113.100"
        )

        # Verify complete audit trail
        security_events = (
            db.query(SecurityEvent)
            .filter(SecurityEvent.user_id == user.id)
            .order_by(SecurityEvent.created_at)
            .all()
        )

        expected_events = ["SESSION_CREATED", "SESSION_ROTATED", "SESSION_REVOKED"]
        actual_events = [event.type for event in security_events]

        for expected in expected_events:
            assert expected in actual_events

        # Verify audit logs
        audit_logs = (
            db.query(AuditLog)
            .filter(AuditLog.actor_user_id == user.id)
            .order_by(AuditLog.created_at)
            .all()
        )

        expected_actions = ["session_created", "session_rotated", "session_revoked"]
        actual_actions = [log.action for log in audit_logs]

        for expected in expected_actions:
            assert expected in actual_actions

        # Verify metadata preservation
        for log in audit_logs:
            assert log.metadata is not None
            assert isinstance(log.metadata, dict)
            if log.action == "session_created":
                assert "session_id" in log.metadata
            elif log.action == "session_rotated":
                assert "old_session_id" in log.metadata
                assert "new_session_id" in log.metadata

    def test_kvkv_compliance_data_handling(self, db: DBSession):
        """Test Turkish KVKV compliance in session data handling."""
        user = create_test_user(db, email="kvkv@example.com")

        # Create session with public IP (should be masked)
        session, _ = self.session_service.create_session(
            db=db,
            user_id=user.id,
            device_fingerprint="kvkv-device",
            ip_address="203.0.113.123",  # Public IP
            user_agent="Mozilla/5.0 KVKV Test",
        )

        # Verify IP is masked in database
        assert session.ip_address == "203.0.113.xxx"

        # Verify KVKV logging flag is set
        assert session.kvkv_logged is True

        # Create session with private IP (should not be masked)
        private_session, _ = self.session_service.create_session(
            db=db,
            user_id=user.id,
            device_fingerprint="kvkv-device-private",
            ip_address="192.168.1.100",  # Private IP
            user_agent="Mozilla/5.0 KVKV Private",
        )

        # Private IP should not be masked
        assert private_session.ip_address == "192.168.1.100"

        # Verify security events also have masked IPs
        security_events = db.query(SecurityEvent).filter(SecurityEvent.user_id == user.id).all()

        for event in security_events:
            if event.ip:
                # Should either be masked public IP or unmasked private IP
                assert event.ip in ["203.0.113.xxx", "192.168.1.100"]
