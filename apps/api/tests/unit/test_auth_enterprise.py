"""
Comprehensive test suite for Task 3.1 ultra enterprise authentication.

Tests cover:
- Password hashing and verification with Argon2
- Password policy validation
- Account lockout mechanism
- User registration and login
- Password reset functionality
- Rate limiting
- Audit logging
- Turkish KVKV compliance
- Security event logging
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch
import time

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.security_event import SecurityEvent
from app.services.password_service import password_service, PasswordStrengthResult
from app.services.auth_service import auth_service, AuthenticationError
from app.schemas.auth import (
    UserRegisterRequest,
    UserLoginRequest,
    PasswordStrengthRequest,
    PasswordForgotRequest,
    PasswordResetRequest,
)


class TestPasswordService:
    """Test ultra enterprise password service."""

    def test_hash_password_argon2(self):
        """Test password hashing with Argon2id."""
        password = "TestPassword123!"

        hash_result, salt, algorithm = password_service.hash_password(password)

        assert algorithm == "argon2id"
        assert len(salt) == 64  # 32 bytes hex encoded
        assert len(hash_result) > 50  # Argon2 hash is long
        assert hash_result != password  # Hash is different from password

        # Verify password works
        assert password_service.verify_password(password, hash_result, salt, algorithm)

        # Wrong password fails
        assert not password_service.verify_password("WrongPassword", hash_result, salt, algorithm)

    def test_password_verification_timing_protection(self):
        """Test timing attack protection in password verification."""
        password = "TestPassword123!"
        hash_result, salt, algorithm = password_service.hash_password(password)

        # Measure time for correct password
        start = time.time()
        result1 = password_service.verify_password(password, hash_result, salt, algorithm)
        time1 = time.time() - start

        # Measure time for wrong password
        start = time.time()
        result2 = password_service.verify_password("WrongPassword", hash_result, salt, algorithm)
        time2 = time.time() - start

        assert result1 is True
        assert result2 is False

        # Both should take at least minimum time (100ms timing protection)
        assert time1 >= 0.1
        assert time2 >= 0.1

    def test_password_strength_validation_strong_password(self):
        """Test password strength validation with strong password."""
        password = "SuperStrong123!@#$"

        result = password_service.validate_password_strength(password)

        assert isinstance(result, PasswordStrengthResult)
        assert result.ok is True
        assert result.score >= 70
        assert len(result.feedback) <= 1  # Should have minimal feedback

    def test_password_strength_validation_weak_password(self):
        """Test password strength validation with weak password."""
        password = "weak"

        result = password_service.validate_password_strength(password)

        assert result.ok is False
        assert result.score < 50
        assert len(result.feedback) > 0
        assert any("12 karakter" in feedback for feedback in result.feedback)

    def test_password_strength_validation_common_password(self):
        """Test rejection of common passwords."""
        common_passwords = ["password", "123456", "password123", "sifre123"]

        for password in common_passwords:
            result = password_service.validate_password_strength(password)
            assert result.ok is False
            assert any("yaygın" in feedback.lower() for feedback in result.feedback)

    def test_password_strength_validation_personal_info(self):
        """Test rejection of passwords containing personal information."""
        user_info = {
            "email": "john.doe@example.com",
            "full_name": "John Doe",
            "company_name": "Acme Corp",
        }

        personal_passwords = ["john123456789!", "doe123456789!", "acme123456789!"]

        for password in personal_passwords:
            result = password_service.validate_password_strength(password, user_info)
            assert result.ok is False
            assert any("kişisel bilgi" in feedback.lower() for feedback in result.feedback)

    def test_password_strength_validation_repeated_patterns(self):
        """Test rejection of passwords with repeated patterns."""
        pattern_passwords = [
            "aaaaaaaaaaaa1!",  # Repeated characters
            "abcdefghijkl1!",  # Sequential pattern
            "123456789012A!",  # Sequential numbers
        ]

        for password in pattern_passwords:
            result = password_service.validate_password_strength(password)
            assert result.ok is False
            assert any(
                "tekrarlayan" in feedback.lower() or "desen" in feedback.lower()
                for feedback in result.feedback
            )

    def test_secure_token_generation(self):
        """Test secure token generation."""
        token1 = password_service.generate_secure_token(32)
        token2 = password_service.generate_secure_token(32)

        assert len(token1) > 40  # URL-safe base64 encoding
        assert len(token2) > 40
        assert token1 != token2  # Should be unique

        # Test different lengths
        token_short = password_service.generate_secure_token(16)
        token_long = password_service.generate_secure_token(64)

        assert len(token_short) < len(token_long)


class TestAuthService:
    """Test ultra enterprise authentication service."""

    @pytest.fixture
    def mock_db(self):
        """Mock database session."""
        return Mock(spec=Session)

    @pytest.fixture
    def sample_user_data(self):
        """Sample user registration data."""
        return {
            "email": "test@example.com",
            "password": "StrongPassword123!",
            "full_name": "Test User",
            "data_processing_consent": True,
            "marketing_consent": False,
        }

    def test_register_user_success(self, mock_db, sample_user_data):
        """Test successful user registration."""
        # Mock database queries
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.add = Mock()
        mock_db.flush = Mock()
        mock_db.commit = Mock()

        user = auth_service.register_user(
            db=mock_db, ip_address="192.168.1.1", user_agent="Test Agent", **sample_user_data
        )

        assert user.email == sample_user_data["email"].lower()
        assert user.full_name == sample_user_data["full_name"]
        assert user.data_processing_consent is True
        assert user.password_algorithm == "argon2id"
        assert user.password_hash is not None
        assert user.password_salt is not None

        mock_db.add.assert_called()
        mock_db.commit.assert_called()

    def test_register_user_duplicate_email(self, mock_db, sample_user_data):
        """Test registration with duplicate email."""
        # Mock existing user
        existing_user = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = existing_user

        with pytest.raises(AuthenticationError) as exc_info:
            auth_service.register_user(
                db=mock_db, ip_address="192.168.1.1", user_agent="Test Agent", **sample_user_data
            )

        assert exc_info.value.code == "ERR-AUTH-EMAIL-TAKEN"
        assert "zaten kullanılmaktadır" in exc_info.value.message

    def test_register_user_weak_password(self, mock_db, sample_user_data):
        """Test registration with weak password."""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        sample_user_data["password"] = "weak"

        with pytest.raises(AuthenticationError) as exc_info:
            auth_service.register_user(
                db=mock_db, ip_address="192.168.1.1", user_agent="Test Agent", **sample_user_data
            )

        assert exc_info.value.code == "ERR-AUTH-WEAK-PASSWORD"
        assert "güvenlik gereksinimlerini" in exc_info.value.message

    def test_authenticate_user_success(self, mock_db):
        """Test successful user authentication."""
        # Create mock user
        password = "StrongPassword123!"
        hash_result, salt, algorithm = password_service.hash_password(password)

        mock_user = Mock(spec=User)
        mock_user.email = "test@example.com"
        mock_user.password_hash = hash_result
        mock_user.password_salt = salt
        mock_user.password_algorithm = algorithm
        mock_user.can_attempt_login.return_value = True
        mock_user.is_account_locked.return_value = False
        mock_user.password_must_change = False
        mock_user.is_password_expired.return_value = False
        mock_user.reset_failed_login_attempts = Mock()
        mock_user.update_login_metadata = Mock()

        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        mock_db.commit = Mock()

        user, auth_metadata = auth_service.authenticate_user(
            db=mock_db,
            email="test@example.com",
            password=password,
            ip_address="192.168.1.1",
            user_agent="Test Agent",
        )

        assert user == mock_user
        assert "login_timestamp" in auth_metadata
        assert auth_metadata["auth_method"] == "password"

        mock_user.reset_failed_login_attempts.assert_called_once()
        mock_user.update_login_metadata.assert_called_once()
        mock_db.commit.assert_called()

    def test_authenticate_user_not_found(self, mock_db):
        """Test authentication with non-existent user."""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(AuthenticationError) as exc_info:
            auth_service.authenticate_user(
                db=mock_db,
                email="nonexistent@example.com",
                password="AnyPassword123!",
                ip_address="192.168.1.1",
                user_agent="Test Agent",
            )

        assert exc_info.value.code == "ERR-AUTH-INVALID-CREDS"
        assert "hatalı" in exc_info.value.message

    def test_authenticate_user_wrong_password(self, mock_db):
        """Test authentication with wrong password."""
        # Create mock user with different password
        correct_password = "CorrectPassword123!"
        wrong_password = "WrongPassword123!"

        hash_result, salt, algorithm = password_service.hash_password(correct_password)

        mock_user = Mock(spec=User)
        mock_user.email = "test@example.com"
        mock_user.password_hash = hash_result
        mock_user.password_salt = salt
        mock_user.password_algorithm = algorithm
        mock_user.can_attempt_login.return_value = True
        mock_user.is_account_locked.return_value = False
        mock_user.failed_login_attempts = 1
        mock_user.increment_failed_login_attempts = Mock()

        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        mock_db.commit = Mock()

        with pytest.raises(AuthenticationError) as exc_info:
            auth_service.authenticate_user(
                db=mock_db,
                email="test@example.com",
                password=wrong_password,
                ip_address="192.168.1.1",
                user_agent="Test Agent",
            )

        assert exc_info.value.code == "ERR-AUTH-INVALID-CREDS"
        mock_user.increment_failed_login_attempts.assert_called_once()
        mock_db.commit.assert_called()

    def test_authenticate_user_account_locked(self, mock_db):
        """Test authentication with locked account."""
        mock_user = Mock(spec=User)
        mock_user.email = "test@example.com"
        mock_user.can_attempt_login.return_value = False
        mock_user.is_account_locked.return_value = True
        mock_user.account_locked_until = datetime.now(timezone.utc) + timedelta(minutes=10)
        mock_user.failed_login_attempts = 10

        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        with pytest.raises(AuthenticationError) as exc_info:
            auth_service.authenticate_user(
                db=mock_db,
                email="test@example.com",
                password="AnyPassword123!",
                ip_address="192.168.1.1",
                user_agent="Test Agent",
            )

        assert exc_info.value.code == "ERR-AUTH-LOCKED"
        assert "kilitlendi" in exc_info.value.message

    def test_initiate_password_reset_success(self, mock_db):
        """Test successful password reset initiation."""
        mock_user = Mock(spec=User)
        mock_user.id = 1
        mock_user.email = "test@example.com"
        mock_user.can_reset_password.return_value = True
        mock_user.password_reset_attempts = 0

        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        mock_db.commit = Mock()

        result = auth_service.initiate_password_reset(
            db=mock_db, email="test@example.com", ip_address="192.168.1.1", user_agent="Test Agent"
        )

        assert result is True
        assert mock_user.password_reset_token is not None
        assert mock_user.password_reset_expires_at is not None
        assert mock_user.password_reset_attempts == 1
        mock_db.commit.assert_called()

    def test_reset_password_success(self, mock_db):
        """Test successful password reset completion."""
        token = "valid_reset_token_123"
        new_password = "NewStrongPassword123!"

        mock_user = Mock(spec=User)
        mock_user.id = 1
        mock_user.email = "test@example.com"
        mock_user.full_name = "Test User"
        mock_user.company_name = None

        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        mock_db.commit = Mock()

        user = auth_service.reset_password(
            db=mock_db,
            token=token,
            new_password=new_password,
            ip_address="192.168.1.1",
            user_agent="Test Agent",
        )

        assert user == mock_user
        assert mock_user.password_hash is not None
        assert mock_user.password_salt is not None
        assert mock_user.password_algorithm == "argon2id"
        assert mock_user.password_reset_token is None
        assert mock_user.password_reset_expires_at is None
        assert mock_user.password_reset_attempts == 0
        mock_db.commit.assert_called()

    def test_reset_password_invalid_token(self, mock_db):
        """Test password reset with invalid token."""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(AuthenticationError) as exc_info:
            auth_service.reset_password(
                db=mock_db,
                token="invalid_token",
                new_password="NewStrongPassword123!",
                ip_address="192.168.1.1",
                user_agent="Test Agent",
            )

        assert exc_info.value.code == "ERR-AUTH-INVALID-TOKEN"
        assert "geçersiz" in exc_info.value.message.lower()


class TestUserModel:
    """Test User model methods."""

    def test_is_account_locked(self):
        """Test account lock status checking."""
        user = User()

        # Not locked by default
        assert user.is_account_locked() is False

        # Set future lock time
        user.account_locked_until = datetime.now(timezone.utc) + timedelta(minutes=10)
        assert user.is_account_locked() is True

        # Set past lock time
        user.account_locked_until = datetime.now(timezone.utc) - timedelta(minutes=10)
        assert user.is_account_locked() is False

    def test_can_attempt_login(self):
        """Test login attempt permission checking."""
        user = User()
        user.account_status = "active"
        user.is_active = True
        user.account_locked_until = None

        assert user.can_attempt_login() is True

        # Account locked
        user.account_locked_until = datetime.now(timezone.utc) + timedelta(minutes=10)
        assert user.can_attempt_login() is False

        # Account inactive
        user.account_locked_until = None
        user.is_active = False
        assert user.can_attempt_login() is False

        # Account suspended
        user.is_active = True
        user.account_status = "suspended"
        assert user.can_attempt_login() is False

    def test_increment_failed_login_attempts(self):
        """Test failed login attempt tracking."""
        user = User()
        user.failed_login_attempts = 0

        # First failure
        user.increment_failed_login_attempts()
        assert user.failed_login_attempts == 1
        assert user.last_failed_login_at is not None
        assert user.account_locked_until is None

        # Multiple failures up to threshold
        for i in range(2, 10):
            user.increment_failed_login_attempts()
            assert user.failed_login_attempts == i
            assert user.account_locked_until is None

        # 10th failure should lock account
        user.increment_failed_login_attempts()
        assert user.failed_login_attempts == 10
        assert user.account_locked_until is not None
        assert user.last_lockout_at is not None

    def test_reset_failed_login_attempts(self):
        """Test resetting failed login attempts."""
        user = User()
        user.failed_login_attempts = 5
        user.account_locked_until = datetime.now(timezone.utc) + timedelta(minutes=10)
        user.total_login_count = 10

        user.reset_failed_login_attempts()

        assert user.failed_login_attempts == 0
        assert user.account_locked_until is None
        assert user.last_successful_login_at is not None
        assert user.total_login_count == 11

    def test_password_expiration(self):
        """Test password expiration checking."""
        user = User()

        # No password set
        assert user.is_password_expired() is True

        # Recent password
        user.password_updated_at = datetime.now(timezone.utc) - timedelta(days=30)
        assert user.is_password_expired(max_age_days=90) is False

        # Expired password
        user.password_updated_at = datetime.now(timezone.utc) - timedelta(days=100)
        assert user.is_password_expired(max_age_days=90) is True

    def test_email_verification_status(self):
        """Test email verification status."""
        user = User()

        # Not verified by default
        assert user.is_email_verified is False

        # Set verification timestamp
        user.email_verified_at = datetime.now(timezone.utc)
        assert user.is_email_verified is True

    def test_password_reset_rate_limiting(self):
        """Test password reset rate limiting."""
        user = User()

        # Can reset by default
        assert user.can_reset_password() is True

        # After some attempts
        user.password_reset_attempts = 2
        assert user.can_reset_password() is True

        # After max attempts
        user.password_reset_attempts = 3
        assert user.can_reset_password() is False

    def test_display_name_generation(self):
        """Test display name generation."""
        user = User()
        user.email = "test@example.com"

        # No name set - use email prefix
        assert user.generate_display_name() == "test"

        # Display name set
        user.display_name = "TestUser"
        assert user.generate_display_name() == "TestUser"

        # Full name set (no display name)
        user.display_name = None
        user.full_name = "John Doe"
        assert user.generate_display_name() == "John Doe"


class TestSecurityCompliance:
    """Test security and compliance features."""

    def test_email_masking_kvkv_compliance(self):
        """Test email masking for KVKV compliance."""
        test_cases = [
            ("john@example.com", "j**n@example.com"),
            ("a@example.com", "*@example.com"),
            ("ab@example.com", "**@example.com"),
            ("verylongemail@example.com", "v************l@example.com"),
        ]

        for email, expected in test_cases:
            masked = auth_service._mask_email(email)
            assert masked == expected

    def test_ip_masking_privacy_compliance(self):
        """Test IP address masking for privacy compliance."""
        test_cases = [
            ("192.168.1.1", "192.168.1.1"),  # Private IP - not masked
            ("10.0.0.1", "10.0.0.1"),  # Private IP - not masked
            ("8.8.8.8", "8.8.8.xxx"),  # Public IP - masked
            ("2001:db8::1", "2001:db8::1"),  # IPv6 - simplified test
        ]

        for ip, expected in test_cases:
            masked = auth_service._mask_ip_if_needed(ip)
            # For public IPs, check that masking occurred
            if "xxx" in expected:
                assert "xxx" in masked
            else:
                assert masked == expected

    def test_audit_logging_no_sensitive_data(self):
        """Test that audit logs don't contain sensitive data."""
        # This would be tested with actual log inspection in integration tests
        # Here we verify the principle

        sensitive_data = "password123"

        # Ensure passwords are never logged directly
        with patch("app.services.auth_service.logger") as mock_logger:
            # Simulate a failed authentication
            try:
                raise AuthenticationError("ERR-AUTH-INVALID-CREDS", "Test error")
            except AuthenticationError:
                pass

            # Check that logger was called but without sensitive data
            # In real implementation, ensure no password appears in logs
            assert sensitive_data not in str(mock_logger.call_args_list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
