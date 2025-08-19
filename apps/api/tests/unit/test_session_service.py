"""
Unit tests for ultra enterprise SessionService (Task 3.2).
Tests banking-level session management and security features.
"""

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from sqlalchemy.orm import Session as DBSession

from app.models.session import Session
from app.models.user import User
from app.models.security_event import SecurityEvent
from app.models.audit_log import AuditLog
from app.services.session_service import SessionService, SessionSecurityError
from tests.utils.migration_test_helpers import create_test_user


class TestSessionService:
    """Test ultra enterprise SessionService functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.service = SessionService()
        self.service.session_secret = "test-secret-key-for-unit-tests"

    def test_create_session_success(self, db: DBSession):
        """Test successful session creation."""
        user = create_test_user(db, email="test@example.com")

        session, refresh_token = self.service.create_session(
            db=db,
            user_id=user.id,
            device_fingerprint="test-device-123",
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0 Test",
        )

        # Verify session properties
        assert isinstance(session, Session)
        assert session.user_id == user.id
        assert session.device_fingerprint == "test-device-123"
        assert session.ip_address == "192.168.1.xxx"  # Masked
        assert session.user_agent == "Mozilla/5.0 Test"
        assert session.is_active is True
        assert session.is_suspicious is False

        # Verify refresh token
        assert isinstance(refresh_token, str)
        assert len(refresh_token) > 50  # Should be substantial length

        # Verify token hash matches
        expected_hash = self.service._hash_refresh_token(refresh_token)
        assert session.refresh_token_hash == expected_hash

        # Verify session is persisted
        db.refresh(session)
        assert session.id is not None

        # Verify security event was logged
        security_events = (
            db.query(SecurityEvent)
            .filter(SecurityEvent.user_id == user.id, SecurityEvent.type == "SESSION_CREATED")
            .all()
        )
        assert len(security_events) == 1

        # Verify audit log was created
        audit_logs = (
            db.query(AuditLog)
            .filter(AuditLog.actor_user_id == user.id, AuditLog.action == "session_created")
            .all()
        )
        assert len(audit_logs) == 1

    def test_create_session_user_not_found(self, db: DBSession):
        """Test session creation with non-existent user."""
        with pytest.raises(SessionSecurityError) as exc_info:
            self.service.create_session(
                db=db,
                user_id=99999,  # Non-existent user
                ip_address="192.168.1.100",
            )

        assert exc_info.value.code == "ERR-SESSION-USER-NOT-FOUND"
        assert "bulunamadı" in exc_info.value.message

    def test_create_session_inactive_user(self, db: DBSession):
        """Test session creation with inactive user."""
        user = create_test_user(db, email="test@example.com")
        user.account_status = "suspended"
        db.commit()

        with pytest.raises(SessionSecurityError) as exc_info:
            self.service.create_session(db=db, user_id=user.id, ip_address="192.168.1.100")

        assert exc_info.value.code == "ERR-SESSION-USER-INACTIVE"
        assert "aktif değil" in exc_info.value.message

    def test_create_session_max_limit_exceeded(self, db: DBSession):
        """Test session creation when max sessions limit is exceeded."""
        user = create_test_user(db, email="test@example.com")

        # Create maximum allowed sessions
        for i in range(self.service.max_sessions_per_user):
            session, _ = self.service.create_session(
                db=db, user_id=user.id, device_fingerprint=f"device-{i}", ip_address="192.168.1.100"
            )

        # Verify we have max sessions
        active_sessions = self.service._get_active_sessions(db, user.id)
        assert len(active_sessions) == self.service.max_sessions_per_user

        # Create one more session (should revoke oldest)
        session, _ = self.service.create_session(
            db=db, user_id=user.id, device_fingerprint="new-device", ip_address="192.168.1.100"
        )

        # Should still have max sessions (oldest was revoked)
        active_sessions = self.service._get_active_sessions(db, user.id)
        assert len(active_sessions) == self.service.max_sessions_per_user

        # Verify security event was logged
        limit_events = (
            db.query(SecurityEvent)
            .filter(
                SecurityEvent.user_id == user.id, SecurityEvent.type == "SESSION_LIMIT_EXCEEDED"
            )
            .all()
        )
        assert len(limit_events) == 1

    def test_create_session_suspicious_device(self, db: DBSession):
        """Test session creation with suspicious device fingerprint."""
        user1 = create_test_user(db, email="user1@example.com")
        user2 = create_test_user(db, email="user2@example.com")

        shared_fingerprint = "shared-device-fingerprint"

        # Create session for user1 with device fingerprint
        self.service.create_session(
            db=db,
            user_id=user1.id,
            device_fingerprint=shared_fingerprint,
            ip_address="192.168.1.100",
        )

        # Create session for user2 with same fingerprint (suspicious)
        session2, _ = self.service.create_session(
            db=db,
            user_id=user2.id,
            device_fingerprint=shared_fingerprint,
            ip_address="192.168.1.101",
        )

        # Verify suspicious device event was logged
        suspicious_events = (
            db.query(SecurityEvent)
            .filter(
                SecurityEvent.user_id == user2.id,
                SecurityEvent.type == "SUSPICIOUS_DEVICE_DETECTED",
            )
            .all()
        )
        assert len(suspicious_events) == 1

    def test_rotate_session_success(self, db: DBSession):
        """Test successful session rotation."""
        user = create_test_user(db, email="test@example.com")

        # Create initial session
        old_session, old_token = self.service.create_session(
            db=db,
            user_id=user.id,
            device_fingerprint="test-device",
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0 Test",
        )

        old_session_id = old_session.id

        # Rotate session
        new_session, new_token = self.service.rotate_session(
            db=db,
            current_refresh_token=old_token,
            device_fingerprint="test-device",
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0 Test",
        )

        # Verify new session properties
        assert isinstance(new_session, Session)
        assert new_session.id != old_session_id
        assert new_session.user_id == user.id
        assert new_session.rotated_from == old_session_id
        assert new_session.is_active is True

        # Verify old session is revoked
        db.refresh(old_session)
        assert old_session.revoked_at is not None
        assert old_session.revocation_reason == "rotation"
        assert old_session.is_active is False

        # Verify new token is different
        assert new_token != old_token

        # Verify rotation chain length
        assert new_session.get_rotation_chain_length() == 1

        # Verify security event was logged
        rotation_events = (
            db.query(SecurityEvent)
            .filter(SecurityEvent.user_id == user.id, SecurityEvent.type == "SESSION_ROTATED")
            .all()
        )
        assert len(rotation_events) == 1

    def test_rotate_session_invalid_token(self, db: DBSession):
        """Test session rotation with invalid token."""
        with pytest.raises(SessionSecurityError) as exc_info:
            self.service.rotate_session(
                db=db, current_refresh_token="invalid-token", ip_address="192.168.1.100"
            )

        assert exc_info.value.code == "ERR-SESSION-INVALID-TOKEN"
        assert "geçersiz" in exc_info.value.message.lower()

    def test_rotate_session_reuse_detection(self, db: DBSession):
        """Test refresh token reuse detection during rotation."""
        user = create_test_user(db, email="test@example.com")

        # Create session
        session, token = self.service.create_session(
            db=db, user_id=user.id, ip_address="192.168.1.100"
        )

        # Revoke session manually (simulating previous rotation)
        session.revoke("rotation")
        db.commit()

        # Try to rotate with the revoked token (token reuse)
        with pytest.raises(SessionSecurityError) as exc_info:
            self.service.rotate_session(
                db=db, current_refresh_token=token, ip_address="192.168.1.100"
            )

        assert exc_info.value.code == "ERR-SESSION-INVALID-TOKEN"

        # Verify token reuse security event was logged
        reuse_events = (
            db.query(SecurityEvent)
            .filter(
                SecurityEvent.user_id == user.id,
                SecurityEvent.type == "REFRESH_TOKEN_REUSE_DETECTED",
            )
            .all()
        )
        assert len(reuse_events) == 1

        # Verify all user sessions were revoked
        active_sessions = self.service._get_active_sessions(db, user.id)
        assert len(active_sessions) == 0

    def test_rotate_session_device_mismatch(self, db: DBSession):
        """Test session rotation with device fingerprint mismatch."""
        user = create_test_user(db, email="test@example.com")

        # Create session with device fingerprint
        session, token = self.service.create_session(
            db=db, user_id=user.id, device_fingerprint="original-device", ip_address="192.168.1.100"
        )

        # Rotate with different device fingerprint
        new_session, _ = self.service.rotate_session(
            db=db,
            current_refresh_token=token,
            device_fingerprint="different-device",
            ip_address="192.168.1.100",
        )

        # Should succeed but log security event
        device_mismatch_events = (
            db.query(SecurityEvent)
            .filter(
                SecurityEvent.user_id == user.id, SecurityEvent.type == "SESSION_DEVICE_MISMATCH"
            )
            .all()
        )
        assert len(device_mismatch_events) == 1

        # Original session should be flagged as suspicious
        db.refresh(session)
        assert session.is_suspicious is True

    def test_rotate_session_chain_limit(self, db: DBSession):
        """Test session rotation chain length limit."""
        user = create_test_user(db, email="test@example.com")

        # Create session
        session, token = self.service.create_session(
            db=db, user_id=user.id, ip_address="192.168.1.100"
        )

        # Mock excessive rotation chain length
        with patch.object(session, "get_rotation_chain_length") as mock_chain:
            mock_chain.return_value = self.service.max_rotation_chain_length + 1

            with pytest.raises(SessionSecurityError) as exc_info:
                self.service.rotate_session(
                    db=db, current_refresh_token=token, ip_address="192.168.1.100"
                )

            assert exc_info.value.code == "ERR-SESSION-ROTATION-LIMIT"
            assert "güvenlik nedeniyle" in exc_info.value.message

    def test_revoke_session_success(self, db: DBSession):
        """Test successful session revocation."""
        user = create_test_user(db, email="test@example.com")

        # Create session
        session, _ = self.service.create_session(db=db, user_id=user.id, ip_address="192.168.1.100")

        session_id = session.id

        # Revoke session
        result = self.service.revoke_session(
            db=db, session_id=session_id, reason="user_request", ip_address="192.168.1.100"
        )

        assert result is True

        # Verify session is revoked
        db.refresh(session)
        assert session.revoked_at is not None
        assert session.revocation_reason == "user_request"
        assert session.is_active is False

        # Verify security event was logged
        revoke_events = (
            db.query(SecurityEvent)
            .filter(SecurityEvent.user_id == user.id, SecurityEvent.type == "SESSION_REVOKED")
            .all()
        )
        assert len(revoke_events) >= 1  # At least one (could be more from creation)

    def test_revoke_session_not_found(self, db: DBSession):
        """Test revoking non-existent session."""
        random_id = uuid.uuid4()

        result = self.service.revoke_session(db=db, session_id=random_id, reason="test")

        assert result is False

    def test_revoke_session_already_revoked(self, db: DBSession):
        """Test revoking already revoked session."""
        user = create_test_user(db, email="test@example.com")

        # Create and revoke session
        session, _ = self.service.create_session(db=db, user_id=user.id, ip_address="192.168.1.100")

        session_id = session.id

        # First revocation
        result1 = self.service.revoke_session(db=db, session_id=session_id, reason="first_revoke")
        assert result1 is True

        # Second revocation (should still return True)
        result2 = self.service.revoke_session(db=db, session_id=session_id, reason="second_revoke")
        assert result2 is True

        # Reason should remain from first revocation
        db.refresh(session)
        assert session.revocation_reason == "first_revoke"

    def test_revoke_all_user_sessions(self, db: DBSession):
        """Test revoking all sessions for a user."""
        user = create_test_user(db, email="test@example.com")

        # Create multiple sessions
        sessions = []
        for i in range(3):
            session, _ = self.service.create_session(
                db=db, user_id=user.id, device_fingerprint=f"device-{i}", ip_address="192.168.1.100"
            )
            sessions.append(session)

        # Revoke all except the last one
        preserved_session_id = sessions[-1].id

        revoked_count = self.service.revoke_all_user_sessions(
            db=db,
            user_id=user.id,
            reason="security_action",
            except_session_id=preserved_session_id,
            ip_address="192.168.1.100",
        )

        assert revoked_count == 2  # Should revoke 2 out of 3

        # Verify revocation status
        for i, session in enumerate(sessions[:-1]):  # All except last
            db.refresh(session)
            assert session.revoked_at is not None
            assert session.revocation_reason == "security_action"

        # Verify preserved session is still active
        db.refresh(sessions[-1])
        assert sessions[-1].revoked_at is None
        assert sessions[-1].is_active is True

        # Verify security event was logged
        bulk_revoke_events = (
            db.query(SecurityEvent)
            .filter(SecurityEvent.user_id == user.id, SecurityEvent.type == "ALL_SESSIONS_REVOKED")
            .all()
        )
        assert len(bulk_revoke_events) == 1

    def test_cleanup_expired_sessions(self, db: DBSession):
        """Test cleanup of expired sessions."""
        user = create_test_user(db, email="test@example.com")

        # Create sessions with different expiration times
        active_session, _ = self.service.create_session(
            db=db,
            user_id=user.id,
            expires_in_hours=24,  # Active
        )

        expired_session, _ = self.service.create_session(
            db=db,
            user_id=user.id,
            expires_in_hours=1,  # Will be expired
        )

        # Manually set expired session to past
        expired_session.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()

        # Run cleanup
        cleaned_count = self.service.cleanup_expired_sessions(db)

        assert cleaned_count == 1

        # Verify expired session is revoked
        db.refresh(expired_session)
        assert expired_session.revoked_at is not None
        assert expired_session.revocation_reason == "expired"

        # Verify active session is still active
        db.refresh(active_session)
        assert active_session.is_active is True

    def test_get_session_by_token(self, db: DBSession):
        """Test retrieving session by refresh token."""
        user = create_test_user(db, email="test@example.com")

        # Create session
        session, token = self.service.create_session(
            db=db, user_id=user.id, ip_address="192.168.1.100"
        )

        original_last_used = session.last_used_at

        # Retrieve session by token
        retrieved_session = self.service.get_session_by_token(db, token)

        assert retrieved_session is not None
        assert retrieved_session.id == session.id
        assert retrieved_session.user_id == user.id

        # Verify last_used_at was updated
        assert retrieved_session.last_used_at > original_last_used

    def test_get_session_by_invalid_token(self, db: DBSession):
        """Test retrieving session with invalid token."""
        retrieved_session = self.service.get_session_by_token(db, "invalid-token")
        assert retrieved_session is None

    def test_get_session_by_revoked_token(self, db: DBSession):
        """Test retrieving session with revoked token."""
        user = create_test_user(db, email="test@example.com")

        # Create and revoke session
        session, token = self.service.create_session(
            db=db, user_id=user.id, ip_address="192.168.1.100"
        )

        session.revoke("test")
        db.commit()

        # Try to retrieve revoked session
        retrieved_session = self.service.get_session_by_token(db, token)
        assert retrieved_session is None

    def test_hash_refresh_token_consistency(self):
        """Test refresh token hashing consistency."""
        token = "test-token-123"

        hash1 = self.service._hash_refresh_token(token)
        hash2 = self.service._hash_refresh_token(token)

        # Same token should produce same hash
        assert hash1 == hash2
        assert len(hash1) == 128  # SHA512 hex length

        # Different tokens should produce different hashes
        different_hash = self.service._hash_refresh_token("different-token")
        assert hash1 != different_hash

    def test_ip_masking_for_storage(self):
        """Test IP address masking for KVKV compliance."""
        # Test IPv4 masking
        ipv4 = "203.0.113.123"
        masked_ipv4 = self.service._mask_ip_for_storage(ipv4)
        assert masked_ipv4 == "203.0.113.xxx"

        # Test private IP (should not be masked)
        private_ipv4 = "192.168.1.100"
        masked_private = self.service._mask_ip_for_storage(private_ipv4)
        assert masked_private == "192.168.1.100"

        # Test IPv6 masking
        ipv6 = "2001:db8:85a3::8a2e:370:7334"
        masked_ipv6 = self.service._mask_ip_for_storage(ipv6)
        assert masked_ipv6 == "2001:db8:85a3::8a2::xxxx"

        # Test None
        assert self.service._mask_ip_for_storage(None) is None

        # Test invalid IP
        invalid = "not-an-ip"
        masked_invalid = self.service._mask_ip_for_storage(invalid)
        assert masked_invalid == "invalid_ip"

    def test_device_fingerprint_analysis(self, db: DBSession):
        """Test device fingerprint analysis for suspicious activity."""
        user1 = create_test_user(db, email="user1@example.com")
        user2 = create_test_user(db, email="user2@example.com")

        shared_fingerprint = "shared-device-123"

        # Create session for user1
        self.service.create_session(
            db=db,
            user_id=user1.id,
            device_fingerprint=shared_fingerprint,
            ip_address="192.168.1.100",
        )

        # Analyze same fingerprint for user2 (should detect sharing)
        result = self.service._analyze_device_fingerprint(
            db, user2.id, shared_fingerprint, "192.168.1.101"
        )

        assert result is not None
        assert result["type"] == "device_sharing"
        assert result["other_users_count"] == 1
        assert result["risk_level"] == "medium"

    def test_device_fingerprint_rapid_changes(self, db: DBSession):
        """Test detection of rapid device fingerprint changes."""
        user = create_test_user(db, email="test@example.com")

        # Create multiple sessions with different fingerprints
        for i in range(self.service.suspicious_activity_threshold):
            self.service.create_session(
                db=db, user_id=user.id, device_fingerprint=f"device-{i}", ip_address="192.168.1.100"
            )

        # Analyze new fingerprint (should detect rapid changes)
        result = self.service._analyze_device_fingerprint(
            db, user.id, "new-device", "192.168.1.100"
        )

        assert result is not None
        assert result["type"] == "rapid_device_changes"
        assert result["recent_fingerprints"] >= self.service.suspicious_activity_threshold
        assert result["risk_level"] == "high"
