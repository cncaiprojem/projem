"""
Unit tests for ultra enterprise Session model (Task 3.2).
Tests banking-level session security features and constraints.
"""

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.models.session import Session
from app.models.user import User
from tests.utils.migration_test_helpers import create_test_user


class TestSessionModel:
    """Test ultra enterprise Session model functionality."""

    def test_session_creation_with_defaults(self, db: DBSession):
        """Test creating session with default factory method."""
        user = create_test_user(db, email="test@example.com")

        session = Session.create_default_session(
            user_id=user.id,
            refresh_token_hash="a" * 128,  # Valid SHA512 hex length
            device_fingerprint="test-device-123",
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0 Test Browser",
        )

        # Verify all fields are set correctly
        assert isinstance(session.id, uuid.UUID)
        assert session.user_id == user.id
        assert session.refresh_token_hash == "a" * 128
        assert session.device_fingerprint == "test-device-123"
        assert session.ip_address == "192.168.1.100"
        assert session.user_agent == "Mozilla/5.0 Test Browser"
        assert session.is_suspicious is False
        assert session.kvkv_logged is True
        assert session.revoked_at is None
        assert session.revocation_reason is None
        assert session.rotated_from is None

        # Verify timestamps
        now = datetime.now(timezone.utc)
        assert abs((session.created_at - now).total_seconds()) < 5
        assert abs((session.last_used_at - now).total_seconds()) < 5
        assert session.expires_at > now
        assert abs((session.expires_at - now - timedelta(hours=168)).total_seconds()) < 5

        # Save to database
        db.add(session)
        db.commit()

        # Verify it can be retrieved
        retrieved = db.query(Session).filter(Session.id == session.id).first()
        assert retrieved is not None
        assert retrieved.user_id == user.id

    def test_session_properties(self, db: DBSession):
        """Test session property methods."""
        user = create_test_user(db, email="test@example.com")

        # Create session expiring in 1 hour
        session = Session.create_default_session(
            user_id=user.id, refresh_token_hash="b" * 128, expires_in_hours=1
        )

        # Test active session properties
        assert session.is_active is True
        assert session.is_expired is False
        assert session.expires_in_seconds > 3590  # Close to 1 hour
        assert session.age_in_seconds < 10  # Just created
        assert session.is_near_expiry(threshold_minutes=120) is True  # Expires within 2 hours

        # Test expired session
        with patch("app.models.session.datetime") as mock_datetime:
            future_time = datetime.now(timezone.utc) + timedelta(hours=2)
            mock_datetime.now.return_value = future_time

            assert session.is_expired is True
            assert session.is_active is False
            assert session.expires_in_seconds < 0

    def test_session_revocation(self, db: DBSession):
        """Test session revocation functionality."""
        user = create_test_user(db, email="test@example.com")

        session = Session.create_default_session(user_id=user.id, refresh_token_hash="c" * 128)

        # Initially not revoked
        assert session.revoked_at is None
        assert session.revocation_reason is None
        assert session.is_active is True

        # Revoke session
        revoke_time = datetime.now(timezone.utc)
        session.revoke("logout")

        # Verify revocation
        assert session.revoked_at is not None
        assert session.revocation_reason == "logout"
        assert session.is_active is False
        assert abs((session.revoked_at - revoke_time).total_seconds()) < 5

    def test_session_suspicious_flagging(self, db: DBSession):
        """Test suspicious activity flagging."""
        user = create_test_user(db, email="test@example.com")

        session = Session.create_default_session(user_id=user.id, refresh_token_hash="d" * 128)

        # Initially not suspicious
        assert session.is_suspicious is False

        # Flag as suspicious
        session.flag_suspicious()
        assert session.is_suspicious is True

    def test_session_expiration_extension(self, db: DBSession):
        """Test session expiration extension."""
        user = create_test_user(db, email="test@example.com")

        session = Session.create_default_session(
            user_id=user.id, refresh_token_hash="e" * 128, expires_in_hours=1
        )

        original_expires = session.expires_at

        # Extend expiration
        session.extend_expiration(extension_hours=24)

        # Verify extension
        assert session.expires_at > original_expires
        expected_expires = datetime.now(timezone.utc) + timedelta(hours=24)
        assert abs((session.expires_at - expected_expires).total_seconds()) < 5

        # Test extension of revoked session (should not work)
        session.revoke("test")
        session.extend_expiration(extension_hours=48)
        # Should not change after revocation
        assert abs((session.expires_at - expected_expires).total_seconds()) < 5

    def test_session_last_used_update(self, db: DBSession):
        """Test last used timestamp update."""
        user = create_test_user(db, email="test@example.com")

        session = Session.create_default_session(user_id=user.id, refresh_token_hash="f" * 128)

        original_last_used = session.last_used_at

        # Wait a moment and update
        import time

        time.sleep(0.1)

        session.update_last_used()

        # Verify update
        assert session.last_used_at > original_last_used

    def test_session_rotation_chain(self, db: DBSession):
        """Test session rotation chain tracking."""
        user = create_test_user(db, email="test@example.com")

        # Create root session
        session1 = Session.create_default_session(user_id=user.id, refresh_token_hash="g" * 128)
        db.add(session1)
        db.flush()

        # Create rotated session
        session2 = Session.create_default_session(user_id=user.id, refresh_token_hash="h" * 128)
        session2.rotated_from = session1.id
        db.add(session2)
        db.flush()

        # Create another rotation
        session3 = Session.create_default_session(user_id=user.id, refresh_token_hash="i" * 128)
        session3.rotated_from = session2.id
        db.add(session3)
        db.commit()

        # Test rotation chain length
        assert session1.get_rotation_chain_length() == 0  # Root
        assert session2.get_rotation_chain_length() == 1
        assert session3.get_rotation_chain_length() == 2

        # Test relationships
        db.refresh(session1)
        db.refresh(session2)
        db.refresh(session3)

        assert session2.parent_session == session1
        assert session3.parent_session == session2
        assert len(session1.rotated_sessions) == 1
        assert session1.rotated_sessions[0] == session2

    def test_refresh_token_hash_length_constraint(self, db: DBSession):
        """Test refresh token hash length constraint."""
        user = create_test_user(db, email="test@example.com")

        # Test invalid hash length (too short)
        session = Session(
            user_id=user.id,
            refresh_token_hash="short",  # Invalid length
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        db.add(session)

        with pytest.raises(IntegrityError) as exc_info:
            db.commit()

        assert "ck_sessions_refresh_token_hash_length" in str(exc_info.value)
        db.rollback()

    def test_revocation_reason_constraint(self, db: DBSession):
        """Test revocation reason constraint."""
        user = create_test_user(db, email="test@example.com")

        session = Session.create_default_session(user_id=user.id, refresh_token_hash="j" * 128)

        # Set invalid revocation reason
        session.revoked_at = datetime.now(timezone.utc)
        session.revocation_reason = "invalid_reason"

        db.add(session)

        with pytest.raises(IntegrityError) as exc_info:
            db.commit()

        assert "ck_sessions_revocation_reason_valid" in str(exc_info.value)
        db.rollback()

    def test_self_rotation_constraint(self, db: DBSession):
        """Test self-rotation prevention constraint."""
        user = create_test_user(db, email="test@example.com")

        session = Session.create_default_session(user_id=user.id, refresh_token_hash="k" * 128)
        db.add(session)
        db.flush()

        # Try to set session as rotated from itself
        session.rotated_from = session.id

        with pytest.raises(IntegrityError) as exc_info:
            db.commit()

        assert "ck_sessions_no_self_rotation" in str(exc_info.value)
        db.rollback()

    def test_expires_after_created_constraint(self, db: DBSession):
        """Test expiration after creation constraint."""
        user = create_test_user(db, email="test@example.com")

        now = datetime.now(timezone.utc)
        session = Session(
            user_id=user.id,
            refresh_token_hash="l" * 128,
            created_at=now,
            expires_at=now - timedelta(hours=1),  # Expires before creation
        )

        db.add(session)

        with pytest.raises(IntegrityError) as exc_info:
            db.commit()

        assert "ck_sessions_expires_after_created" in str(exc_info.value)
        db.rollback()

    def test_unique_refresh_token_hash(self, db: DBSession):
        """Test unique constraint on refresh token hash."""
        user = create_test_user(db, email="test@example.com")

        # Create first session
        session1 = Session.create_default_session(user_id=user.id, refresh_token_hash="m" * 128)
        db.add(session1)
        db.commit()

        # Try to create second session with same hash
        session2 = Session.create_default_session(
            user_id=user.id,
            refresh_token_hash="m" * 128,  # Same hash
        )
        db.add(session2)

        with pytest.raises(IntegrityError) as exc_info:
            db.commit()

        # Should fail on unique constraint
        assert "duplicate key value" in str(exc_info.value).lower()
        db.rollback()

    def test_session_user_relationship(self, db: DBSession):
        """Test session-user relationship."""
        user = create_test_user(db, email="test@example.com")

        session = Session.create_default_session(user_id=user.id, refresh_token_hash="n" * 128)

        db.add(session)
        db.commit()

        # Test relationship from session to user
        db.refresh(session)
        assert session.user == user

        # Test relationship from user to sessions
        db.refresh(user)
        assert session in user.sessions
        assert len(user.sessions) == 1

    def test_session_repr(self, db: DBSession):
        """Test session string representation."""
        user = create_test_user(db, email="test@example.com")

        session = Session.create_default_session(user_id=user.id, refresh_token_hash="o" * 128)

        repr_str = repr(session)
        assert "Session" in repr_str
        assert str(session.id) in repr_str
        assert str(user.id) in repr_str
        assert "revoked=False" in repr_str

        # Test revoked session representation
        session.revoke("test")
        repr_str = repr(session)
        assert "revoked=True" in repr_str

    def test_session_cascade_delete(self, db: DBSession):
        """Test cascade delete when user is deleted."""
        user = create_test_user(db, email="test@example.com")

        session = Session.create_default_session(user_id=user.id, refresh_token_hash="p" * 128)

        db.add(session)
        db.commit()

        session_id = session.id

        # Delete user
        db.delete(user)
        db.commit()

        # Session should be deleted due to CASCADE
        deleted_session = db.query(Session).filter(Session.id == session_id).first()
        assert deleted_session is None
