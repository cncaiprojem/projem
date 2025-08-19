"""
Test suite for security event model functionality.
Tests enterprise security monitoring and incident tracking.
"""

import pytest
from datetime import datetime, timezone
from ipaddress import IPv4Address, IPv6Address

from app.models.security_event import SecurityEvent


class TestSecurityEventEnterprise:
    """Test enterprise security event functionality."""

    def test_create_security_event_basic(self):
        """Test basic security event creation."""
        event = SecurityEvent(
            user_id=123,
            type="LOGIN_FAILED",
            ip="192.168.1.100",
            ua="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            created_at=datetime.now(timezone.utc),
        )

        assert event.user_id == 123
        assert event.type == "LOGIN_FAILED"
        assert event.ip == "192.168.1.100"
        assert event.ua is not None
        assert event.created_at is not None

    def test_create_security_event_anonymous(self):
        """Test anonymous security event creation."""
        event = SecurityEvent(
            user_id=None,  # Anonymous
            type="BRUTE_FORCE_DETECTED",
            ip="10.0.0.50",
            ua=None,
            created_at=datetime.now(timezone.utc),
        )

        assert event.user_id is None
        assert event.type == "BRUTE_FORCE_DETECTED"
        assert event.ip == "10.0.0.50"
        assert event.ua is None

    def test_create_security_event_ipv6(self):
        """Test security event with IPv6 address."""
        event = SecurityEvent(
            user_id=456,
            type="ACCESS_DENIED",
            ip="2001:0db8:85a3:0000:0000:8a2e:0370:7334",
            ua="curl/7.68.0",
            created_at=datetime.now(timezone.utc),
        )

        assert event.ip == "2001:0db8:85a3:0000:0000:8a2e:0370:7334"
        assert event.type == "ACCESS_DENIED"

    def test_security_event_properties(self):
        """Test security event property methods."""
        # Anonymous event
        anonymous_event = SecurityEvent(
            user_id=None,
            type="DDOS_DETECTED",
            ip="1.2.3.4",
            ua=None,
            created_at=datetime.now(timezone.utc),
        )

        assert anonymous_event.is_anonymous
        assert not anonymous_event.is_authenticated
        assert anonymous_event.has_ip
        assert not anonymous_event.has_user_agent

        # Authenticated event
        auth_event = SecurityEvent(
            user_id=789,
            type="PRIVILEGE_ESCALATION",
            ip="172.16.0.100",
            ua="CustomApp/1.0",
            created_at=datetime.now(timezone.utc),
        )

        assert not auth_event.is_anonymous
        assert auth_event.is_authenticated
        assert auth_event.has_ip
        assert auth_event.has_user_agent

        # Event without IP
        no_ip_event = SecurityEvent(
            user_id=100,
            type="INTERNAL_ERROR",
            ip=None,
            ua="InternalService/2.0",
            created_at=datetime.now(timezone.utc),
        )

        assert not no_ip_event.has_ip
        assert no_ip_event.has_user_agent

        # Event with empty user agent
        empty_ua_event = SecurityEvent(
            user_id=200,
            type="API_ACCESS",
            ip="10.10.10.10",
            ua="",  # Empty string
            created_at=datetime.now(timezone.utc),
        )

        assert not empty_ua_event.has_user_agent

    def test_create_login_failed_factory(self):
        """Test login failed factory method."""
        event = SecurityEvent.create_login_failed(user_id=123, ip="192.168.1.50", ua="Firefox/91.0")

        assert event.user_id == 123
        assert event.type == "LOGIN_FAILED"
        assert event.ip == "192.168.1.50"
        assert event.ua == "Firefox/91.0"

        # Test anonymous login failed
        anon_event = SecurityEvent.create_login_failed(ip="203.0.113.1")

        assert anon_event.user_id is None
        assert anon_event.type == "LOGIN_FAILED"
        assert anon_event.ip == "203.0.113.1"
        assert anon_event.ua is None

    def test_create_access_denied_factory(self):
        """Test access denied factory method."""
        event = SecurityEvent.create_access_denied(
            user_id=456, ip="10.0.0.25", ua="Chrome/96.0.4664.110"
        )

        assert event.user_id == 456
        assert event.type == "ACCESS_DENIED"
        assert event.ip == "10.0.0.25"
        assert event.ua == "Chrome/96.0.4664.110"

    def test_create_suspicious_activity_factory(self):
        """Test suspicious activity factory method."""
        event = SecurityEvent.create_suspicious_activity(
            user_id=789, activity_type="multiple_devices", ip="172.16.1.200", ua="Mobile App/3.0"
        )

        assert event.user_id == 789
        assert event.type == "SUSPICIOUS_MULTIPLE_DEVICES"
        assert event.ip == "172.16.1.200"
        assert event.ua == "Mobile App/3.0"

        # Test with anonymous user
        anon_event = SecurityEvent.create_suspicious_activity(
            user_id=None, activity_type="rate_limit_exceeded"
        )

        assert anon_event.user_id is None
        assert anon_event.type == "SUSPICIOUS_RATE_LIMIT_EXCEEDED"

    def test_is_login_related(self):
        """Test login-related event detection."""
        login_events = [
            SecurityEvent(type="LOGIN_FAILED", user_id=1, created_at=datetime.now(timezone.utc)),
            SecurityEvent(type="LOGIN_SUCCESS", user_id=1, created_at=datetime.now(timezone.utc)),
            SecurityEvent(type="LOGIN_BLOCKED", user_id=1, created_at=datetime.now(timezone.utc)),
            SecurityEvent(
                type="BRUTE_FORCE_DETECTED", user_id=None, created_at=datetime.now(timezone.utc)
            ),
            SecurityEvent(type="ACCOUNT_LOCKED", user_id=1, created_at=datetime.now(timezone.utc)),
        ]

        for event in login_events:
            assert event.is_login_related(), f"Event {event.type} should be login-related"

        non_login_events = [
            SecurityEvent(type="ACCESS_DENIED", user_id=1, created_at=datetime.now(timezone.utc)),
            SecurityEvent(type="DATA_BREACH", user_id=None, created_at=datetime.now(timezone.utc)),
            SecurityEvent(
                type="PRIVILEGE_ESCALATION", user_id=1, created_at=datetime.now(timezone.utc)
            ),
        ]

        for event in non_login_events:
            assert not event.is_login_related(), f"Event {event.type} should not be login-related"

    def test_is_access_related(self):
        """Test access-related event detection."""
        access_events = [
            SecurityEvent(type="ACCESS_DENIED", user_id=1, created_at=datetime.now(timezone.utc)),
            SecurityEvent(
                type="PRIVILEGE_ESCALATION", user_id=1, created_at=datetime.now(timezone.utc)
            ),
            SecurityEvent(
                type="UNAUTHORIZED_ACCESS", user_id=1, created_at=datetime.now(timezone.utc)
            ),
            SecurityEvent(
                type="RESOURCE_ACCESS_DENIED", user_id=1, created_at=datetime.now(timezone.utc)
            ),
        ]

        for event in access_events:
            assert event.is_access_related(), f"Event {event.type} should be access-related"

        non_access_events = [
            SecurityEvent(type="LOGIN_FAILED", user_id=1, created_at=datetime.now(timezone.utc)),
            SecurityEvent(type="DATA_BREACH", user_id=None, created_at=datetime.now(timezone.utc)),
            SecurityEvent(
                type="DDOS_DETECTED", user_id=None, created_at=datetime.now(timezone.utc)
            ),
        ]

        for event in non_access_events:
            assert not event.is_access_related(), f"Event {event.type} should not be access-related"

    def test_is_suspicious(self):
        """Test suspicious activity detection."""
        suspicious_events = [
            SecurityEvent(
                type="SUSPICIOUS_LOGIN", user_id=1, created_at=datetime.now(timezone.utc)
            ),
            SecurityEvent(
                type="SUSPICIOUS_ACTIVITY", user_id=1, created_at=datetime.now(timezone.utc)
            ),
            SecurityEvent(
                type="BRUTE_FORCE_DETECTED", user_id=None, created_at=datetime.now(timezone.utc)
            ),
            SecurityEvent(
                type="RATE_LIMIT_EXCEEDED", user_id=1, created_at=datetime.now(timezone.utc)
            ),
            SecurityEvent(
                type="UNUSUAL_LOCATION", user_id=1, created_at=datetime.now(timezone.utc)
            ),
            SecurityEvent(
                type="MULTIPLE_DEVICES", user_id=1, created_at=datetime.now(timezone.utc)
            ),
        ]

        for event in suspicious_events:
            assert event.is_suspicious(), f"Event {event.type} should be suspicious"

        normal_events = [
            SecurityEvent(type="LOGIN_SUCCESS", user_id=1, created_at=datetime.now(timezone.utc)),
            SecurityEvent(type="ACCESS_GRANTED", user_id=1, created_at=datetime.now(timezone.utc)),
            SecurityEvent(type="SESSION_CREATED", user_id=1, created_at=datetime.now(timezone.utc)),
        ]

        for event in normal_events:
            assert not event.is_suspicious(), f"Event {event.type} should not be suspicious"

    def test_repr(self):
        """Test string representation."""
        event = SecurityEvent(
            id=123,
            user_id=456,
            type="LOGIN_FAILED",
            ip="192.168.1.100",
            ua="TestAgent/1.0",
            created_at=datetime.now(timezone.utc),
        )

        repr_str = repr(event)
        assert "SecurityEvent" in repr_str
        assert "id=123" in repr_str
        assert "type='LOGIN_FAILED'" in repr_str
        assert "user_id=456" in repr_str
        assert "ip='192.168.1.100'" in repr_str

    def test_repr_anonymous(self):
        """Test string representation for anonymous event."""
        event = SecurityEvent(
            id=789,
            user_id=None,
            type="DDOS_DETECTED",
            ip="203.0.113.50",
            ua=None,
            created_at=datetime.now(timezone.utc),
        )

        repr_str = repr(event)
        assert "SecurityEvent" in repr_str
        assert "id=789" in repr_str
        assert "type='DDOS_DETECTED'" in repr_str
        assert "user_id=None" in repr_str
        assert "ip='203.0.113.50'" in repr_str

    def test_security_event_types_turkish_compliance(self):
        """Test security event types for Turkish compliance."""
        # Test common Turkish security event patterns
        turkish_events = [
            SecurityEvent(
                type="KIMLIK_DOGRULAMA_HATASI", user_id=1, created_at=datetime.now(timezone.utc)
            ),
            SecurityEvent(type="YETKISIZ_ERISIM", user_id=1, created_at=datetime.now(timezone.utc)),
            SecurityEvent(
                type="SUPHELI_AKTIVITE", user_id=1, created_at=datetime.now(timezone.utc)
            ),
            SecurityEvent(
                type="SISTEM_GUVENLIK_IHLALI", user_id=None, created_at=datetime.now(timezone.utc)
            ),
        ]

        for event in turkish_events:
            assert event.type is not None
            assert len(event.type) > 0

    def test_high_frequency_logging(self):
        """Test that security events can be created at high frequency."""
        events = []
        base_time = datetime.now(timezone.utc)

        # Simulate high-frequency security events
        for i in range(1000):
            event = SecurityEvent(
                user_id=i % 10 if i % 10 != 0 else None,  # Mix of users and anonymous
                type=f"EVENT_TYPE_{i % 5}",
                ip=f"192.168.1.{i % 255}",
                ua=f"Agent/{i % 3 + 1}.0" if i % 3 != 0 else None,
                created_at=base_time,
            )
            events.append(event)

        assert len(events) == 1000
        assert all(event.type is not None for event in events)
        assert all(event.created_at == base_time for event in events)

    def test_security_event_ip_validation_patterns(self):
        """Test various IP address patterns for security events."""
        ip_patterns = [
            "127.0.0.1",  # Localhost
            "192.168.1.100",  # Private Class C
            "10.0.0.50",  # Private Class A
            "172.16.5.200",  # Private Class B
            "203.0.113.1",  # Public IP (RFC5737 test range)
            "2001:db8::1",  # IPv6
            "::1",  # IPv6 localhost
            "fe80::1",  # IPv6 link-local
        ]

        for ip in ip_patterns:
            event = SecurityEvent(
                user_id=1,
                type="IP_TEST",
                ip=ip,
                ua="TestAgent/1.0",
                created_at=datetime.now(timezone.utc),
            )
            assert event.ip == ip
            assert event.has_ip

    def test_user_agent_patterns(self):
        """Test various user agent patterns."""
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36",
            "curl/7.68.0",
            "PostmanRuntime/7.29.0",
            "FreeCAD-CNC-Platform/1.0",
            "TurkishCAMSystem/2.1 (Enterprise)",
            "",  # Empty user agent
            None,  # No user agent
        ]

        for ua in user_agents:
            event = SecurityEvent(
                user_id=1,
                type="USER_AGENT_TEST",
                ip="192.168.1.1",
                ua=ua,
                created_at=datetime.now(timezone.utc),
            )
            assert event.ua == ua

            if ua and ua.strip():
                assert event.has_user_agent
            else:
                assert not event.has_user_agent
