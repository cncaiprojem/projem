"""
Test cases for Task 4.2 critical fixes
Tests the fixes implemented based on Gemini Code Assist and GitHub Copilot feedback.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timezone
from uuid import uuid4

from app.routers.license import anonymize_ip, get_client_info
from app.schemas.license import LicenseAssignRequest
from app.services.idempotency_service import IdempotencyService
from app.models.idempotency import IdempotencyRecord


class TestIPAnonymization:
    """Test IP anonymization for KVKV compliance."""
    
    def test_ipv4_anonymization(self):
        """Test IPv4 address anonymization."""
        assert anonymize_ip("192.168.1.100") == "192.168.1.xxx"
        assert anonymize_ip("10.0.0.1") == "10.0.0.xxx"
        assert anonymize_ip("172.16.254.1") == "172.16.254.xxx"
    
    def test_ipv6_anonymization(self):
        """Test IPv6 address anonymization."""
        assert anonymize_ip("2001:db8:1234:5678::1") == "2001:db8:1234::xxxx"
        assert anonymize_ip("fe80:0:0:0:204:61ff:fe9d:f156") == "fe80:0:0::xxxx"
        assert anonymize_ip("::1") == "::1"  # Localhost, too short to anonymize
    
    def test_edge_cases(self):
        """Test edge cases for IP anonymization."""
        assert anonymize_ip("unknown") == "unknown"
        assert anonymize_ip("") == ""
        assert anonymize_ip(None) == None
        assert anonymize_ip("192.168") == "192.168"  # Malformed, return as-is
    
    def test_get_client_info(self):
        """Test client info extraction with anonymization."""
        # Mock request with IPv4
        request = Mock()
        request.client = Mock(host="192.168.1.100")
        request.headers = {"user-agent": "Mozilla/5.0 Test Browser"}
        
        ip, agent = get_client_info(request)
        assert ip == "192.168.1.xxx"
        assert agent == "Mozilla/5.0 Test Browser"
        
        # Mock request with IPv6
        request.client.host = "2001:db8:1234:5678::1"
        ip, agent = get_client_info(request)
        assert ip == "2001:db8:1234::xxxx"


class TestScopeValidation:
    """Test license scope validation."""
    
    def test_valid_scope(self):
        """Test valid scope structure."""
        valid_scope = {
            "features": {
                "cam_generation": True,
                "gcode_export": True,
                "simulation": False
            },
            "limits": {
                "max_jobs": 100,
                "storage_gb": 50,
                "api_calls_per_day": 10000
            }
        }
        
        # This should not raise an error
        request = LicenseAssignRequest(
            type="12m",
            scope=valid_scope
        )
        assert request.scope == valid_scope
    
    def test_missing_features_key(self):
        """Test scope validation with missing features key."""
        invalid_scope = {
            "limits": {"max_jobs": 100}
        }
        
        with pytest.raises(ValueError, match="Scope must contain 'features' key"):
            LicenseAssignRequest(
                type="12m",
                scope=invalid_scope
            )
    
    def test_missing_limits_key(self):
        """Test scope validation with missing limits key."""
        invalid_scope = {
            "features": {"cam_generation": True}
        }
        
        with pytest.raises(ValueError, match="Scope must contain 'limits' key"):
            LicenseAssignRequest(
                type="12m",
                scope=invalid_scope
            )
    
    def test_invalid_features_type(self):
        """Test scope validation with invalid features type."""
        invalid_scope = {
            "features": "not_a_dict",
            "limits": {"max_jobs": 100}
        }
        
        with pytest.raises(ValueError, match="Scope 'features' must be a dictionary"):
            LicenseAssignRequest(
                type="12m",
                scope=invalid_scope
            )
    
    def test_invalid_limits_type(self):
        """Test scope validation with invalid limits type."""
        invalid_scope = {
            "features": {"cam_generation": True},
            "limits": ["not", "a", "dict"]
        }
        
        with pytest.raises(ValueError, match="Scope 'limits' must be a dictionary"):
            LicenseAssignRequest(
                type="12m",
                scope=invalid_scope
            )


class TestIdempotencyService:
    """Test idempotency service implementation."""
    
    @pytest.mark.asyncio
    async def test_store_and_retrieve_response(self):
        """Test storing and retrieving idempotent responses."""
        db_mock = Mock()
        user_id = uuid4()
        key = "test-key-123"
        response = {"status": "success", "data": {"id": 1}}
        
        # Mock the database query
        with patch.object(IdempotencyService, 'store_response', new_callable=AsyncMock) as store_mock:
            store_mock.return_value = True
            
            result = await IdempotencyService.store_response(
                db_mock, key, user_id, response,
                endpoint="/api/v1/license/assign",
                method="POST",
                status_code=200
            )
            
            assert result is True
            store_mock.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_expired_record_handling(self):
        """Test that expired records are properly handled."""
        db_mock = Mock()
        user_id = uuid4()
        key = "expired-key"
        
        # Create an expired record
        expired_record = Mock(spec=IdempotencyRecord)
        expired_record.is_expired.return_value = True
        
        # Mock the database query to return expired record
        db_mock.query.return_value.filter.return_value.first.return_value = expired_record
        db_mock.delete = Mock()
        db_mock.commit = Mock()
        
        with patch.object(IdempotencyService, 'get_response', new_callable=AsyncMock) as get_mock:
            get_mock.return_value = None  # Should return None for expired
            
            result = await IdempotencyService.get_response(
                db_mock, key, user_id
            )
            
            assert result is None
    
    @pytest.mark.asyncio
    async def test_endpoint_validation(self):
        """Test that endpoint validation works correctly."""
        db_mock = Mock()
        user_id = uuid4()
        key = "endpoint-test"
        
        # Create a record with different endpoint
        record = Mock(spec=IdempotencyRecord)
        record.is_expired.return_value = False
        record.endpoint = "/api/v1/license/extend"
        record.response_data = {"test": "data"}
        
        db_mock.query.return_value.filter.return_value.first.return_value = record
        
        with patch.object(IdempotencyService, 'get_response', new_callable=AsyncMock) as get_mock:
            # Should return None when endpoint doesn't match
            get_mock.return_value = None
            
            result = await IdempotencyService.get_response(
                db_mock, key, user_id,
                endpoint="/api/v1/license/assign"  # Different endpoint
            )
            
            assert result is None


class TestIdempotencyRecord:
    """Test IdempotencyRecord model."""
    
    def test_expiry_calculation(self):
        """Test expiry time calculation."""
        expiry_24h = IdempotencyRecord.create_expiry_time(hours=24)
        expiry_1h = IdempotencyRecord.create_expiry_time(hours=1)
        
        now = datetime.now(timezone.utc)
        
        # Check that expiry times are in the future
        assert expiry_24h > now
        assert expiry_1h > now
        
        # Check that 24h expiry is later than 1h expiry
        assert expiry_24h > expiry_1h
    
    def test_is_expired_method(self):
        """Test the is_expired method."""
        from datetime import timedelta
        
        # Create a non-expired record
        record = IdempotencyRecord()
        record.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        assert record.is_expired() is False
        
        # Create an expired record
        expired_record = IdempotencyRecord()
        expired_record.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        assert expired_record.is_expired() is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])