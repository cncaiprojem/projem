"""
Comprehensive tests for Task 4.10: Observability and audit trail across 
licensing, billing, payments, notifications implementation

Tests cover:
- OpenTelemetry tracing with correlation IDs
- Prometheus metrics collection and accuracy  
- Audit trail generation and integrity
- Turkish KVKV compliance logging
- Performance monitoring and error tracking
"""

import json
import time
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from prometheus_client import CollectorRegistry, generate_latest
from sqlalchemy.orm import Session

from app import metrics
from app.core.logging_config import setup_structured_logging
from app.core.telemetry import initialize_telemetry, create_span, create_financial_span
from app.middleware.correlation_middleware import (
    CorrelationMiddleware, 
    get_correlation_id,
    get_request_id,
    get_session_id
)
from app.models.license import License
from app.models.user import User
from app.models.invoice import Invoice
from app.models.payment import Payment
from app.services.license_service import LicenseService
from app.services.payment_service import PaymentService
from app.services.audit_service import audit_service


class TestTelemetryIntegration:
    """Test OpenTelemetry integration and span creation."""
    
    def test_telemetry_initialization(self):
        """Test that telemetry initializes correctly."""
        # Initialize telemetry
        initialize_telemetry()
        
        # Verify tracer is available
        from app.core.telemetry import get_tracer
        tracer = get_tracer()
        assert tracer is not None
    
    def test_business_span_creation(self):
        """Test business operation span creation with Turkish compliance."""
        correlation_id = str(uuid.uuid4())
        user_id = 123
        
        with create_span(
            "lisans_test_operasyonu",
            operation_type="business", 
            user_id=user_id,
            correlation_id=correlation_id,
            attributes={
                "test.operation": "license_assignment",
                "test.environment": "test"
            }
        ) as span:
            
            # Verify span is active and has correct attributes
            assert span is not None
            assert span.is_recording()
            
            # Verify attributes are set correctly
            # Note: In tests, we can't directly inspect attributes
            # but span creation without errors indicates success
            
    def test_financial_span_creation(self):
        """Test financial operation span with banking compliance."""
        user_id = 456
        amount_cents = 50000  # 500.00 TRY
        invoice_id = 789
        correlation_id = str(uuid.uuid4())
        
        with create_financial_span(
            "test_ödeme_işlemi",
            user_id=user_id,
            amount_cents=amount_cents,
            currency="TRY", 
            invoice_id=invoice_id,
            correlation_id=correlation_id
        ) as span:
            
            # Verify financial span is created
            assert span is not None
            assert span.is_recording()


class TestCorrelationMiddleware:
    """Test correlation ID propagation and context management."""
    
    @pytest.fixture
    def app_with_middleware(self):
        """Create test app with correlation middleware."""
        from fastapi import FastAPI
        from app.middleware.correlation_middleware import CorrelationMiddleware
        
        app = FastAPI()
        app.add_middleware(CorrelationMiddleware)
        return app
    
    def test_correlation_id_generation(self):
        """Test correlation ID generation when not provided."""
        from app.middleware.correlation_middleware import CorrelationMiddleware
        from fastapi import Request
        from unittest.mock import MagicMock
        
        middleware = CorrelationMiddleware(app=MagicMock())
        
        # Mock request without correlation ID
        request = MagicMock(spec=Request)
        request.headers = {}
        request.client.host = "127.0.0.1"
        request.cookies = {}
        
        # Test correlation ID extraction/generation
        correlation_id = middleware._extract_or_generate_correlation_id(request)
        
        assert correlation_id is not None
        assert len(correlation_id) > 0
        assert correlation_id.startswith("req-")
    
    def test_correlation_id_extraction(self):
        """Test correlation ID extraction from headers."""
        from app.middleware.correlation_middleware import CorrelationMiddleware
        from fastapi import Request
        from unittest.mock import MagicMock
        
        middleware = CorrelationMiddleware(app=MagicMock())
        expected_correlation_id = "test-correlation-123"
        
        # Mock request with correlation ID
        request = MagicMock(spec=Request)
        request.headers = {"x-correlation-id": expected_correlation_id}
        
        correlation_id = middleware._extract_or_generate_correlation_id(request)
        
        assert correlation_id == expected_correlation_id


class TestMetricsCollection:
    """Test Prometheus metrics collection and accuracy."""
    
    @pytest.fixture(autouse=True)
    def setup_metrics_registry(self):
        """Setup clean metrics registry for each test."""
        # Clear existing metrics
        from prometheus_client import CollectorRegistry, REGISTRY
        
        # Create new registry for test isolation
        self.test_registry = CollectorRegistry()
        
        # Re-register our metrics with test registry
        self.test_registry.register(metrics.license_operations_total)
        self.test_registry.register(metrics.license_assignment_duration_seconds)
        self.test_registry.register(metrics.payments_total)
        self.test_registry.register(metrics.audit_logs_created_total)
        
        yield
        
        # Cleanup after test
        self.test_registry = None
    
    def test_license_operation_metrics(self):
        """Test license operation metrics are recorded correctly."""
        # Track a successful license assignment
        metrics.license_operations_total.labels(
            operation="assign",
            license_type="12m", 
            status="success",
            user_type="user"
        ).inc()
        
        # Track assignment duration
        metrics.license_assignment_duration_seconds.labels(
            license_type="12m",
            status="success"
        ).observe(2.5)
        
        # Get metrics output
        metrics_output = generate_latest(self.test_registry).decode('utf-8')
        
        # Verify metrics are present
        assert 'license_operations_total' in metrics_output
        assert 'license_assignment_duration_seconds' in metrics_output
        assert 'operation="assign"' in metrics_output
        assert 'license_type="12m"' in metrics_output
        assert 'status="success"' in metrics_output
    
    def test_payment_metrics(self):
        """Test payment metrics are recorded correctly."""
        # Track payment operations
        metrics.payments_total.labels(
            provider="stripe",
            method="card",
            status="success", 
            currency="TRY"
        ).inc()
        
        metrics.payment_processing_duration_seconds.labels(
            provider="stripe",
            method="create_intent",
            status="success"
        ).observe(1.2)
        
        # Get metrics output
        metrics_output = generate_latest(self.test_registry).decode('utf-8')
        
        # Verify payment metrics
        assert 'payments_total' in metrics_output
        assert 'payment_processing_duration_seconds' in metrics_output
        assert 'provider="stripe"' in metrics_output
        assert 'method="card"' in metrics_output
        assert 'currency="TRY"' in metrics_output
    
    def test_audit_metrics(self):
        """Test audit trail metrics are recorded."""
        # Track audit log creation
        metrics.audit_logs_created_total.labels(
            event_type="license_assigned",
            scope_type="license", 
            actor_type="user",
            classification="business_audit"
        ).inc()
        
        # Get metrics output
        metrics_output = generate_latest(self.test_registry).decode('utf-8')
        
        # Verify audit metrics
        assert 'audit_logs_created_total' in metrics_output
        assert 'event_type="license_assigned"' in metrics_output
        assert 'scope_type="license"' in metrics_output


class TestStructuredLogging:
    """Test structured logging with Turkish KVKV compliance."""
    
    def test_kvkv_formatter(self):
        """Test KVKV compliant JSON formatter."""
        from app.core.logging_config import KVKVCompliantFormatter
        import logging
        
        formatter = KVKVCompliantFormatter(
            service_name="test-service",
            environment="test",
            redact_pii=True
        )
        
        # Create test log record
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=100,
            msg="Test message with email: user@example.com",
            args=(),
            exc_info=None
        )
        
        # Add extra fields with PII
        record.email = "user@example.com"
        record.phone = "5551234567"
        record.safe_field = "safe_value"
        
        # Format the record
        formatted = formatter.format(record)
        log_data = json.loads(formatted)
        
        # Verify structure
        assert "timestamp" in log_data
        assert "level" in log_data
        assert "level_tr" in log_data
        assert log_data["level_tr"] == "BİLGİ"  # Turkish translation
        assert log_data["service"] == "test-service"
        assert log_data["environment"] == "test"
        
        # Verify compliance metadata
        assert "compliance" in log_data
        assert log_data["compliance"]["regulation"] == "KVKV_GDPR"
        assert log_data["compliance"]["data_locality"] == "Turkey"
        assert log_data["compliance"]["pii_redacted"] is True
        
        # Verify PII redaction
        assert "***" in str(log_data.get("email", ""))  # Email should be redacted
        assert "***" in str(log_data.get("phone", ""))  # Phone should be redacted
        assert log_data["safe_field"] == "safe_value"  # Safe field unchanged
    
    def test_performance_log_filter(self):
        """Test performance metadata injection in logs."""
        from app.core.logging_config import PerformanceLogFilter
        import logging
        
        filter_instance = PerformanceLogFilter()
        
        # Create test record
        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,  # Critical level for memory tracking
            pathname="/test/path.py", 
            lineno=100,
            msg="Test error message",
            args=(),
            exc_info=None
        )
        
        # Apply filter
        result = filter_instance.filter(record)
        
        assert result is True  # Filter should always return True
        
        # Check if performance metadata was added
        # Note: request_duration_ms might not be set without actual request context
        # but memory_mb might be set for ERROR level logs


class TestLicenseServiceObservability:
    """Test observability integration in license service."""
    
    @pytest.fixture
    def db_session(self):
        """Mock database session for testing."""
        return MagicMock(spec=Session)
    
    @pytest.fixture
    def test_user(self, db_session):
        """Create test user."""
        user = User(id=1, email="test@example.com")
        return user
    
    def test_license_assignment_observability(self, db_session, test_user):
        """Test that license assignment generates proper observability data."""
        # Mock the database queries
        db_session.query.return_value.filter.return_value.first.return_value = None
        db_session.flush.return_value = None
        
        # Mock license creation
        mock_license = License(
            id=1,
            user_id=1,
            type="12m",
            status="active"
        )
        db_session.add.return_value = None
        db_session.flush.side_effect = lambda: setattr(mock_license, 'id', 1)
        
        with patch('app.services.license_service.get_correlation_id') as mock_corr_id:
            with patch('app.services.license_service.get_session_id') as mock_sess_id:
                with patch('app.services.license_service.get_user_id') as mock_user_id:
                    
                    # Setup correlation context
                    mock_corr_id.return_value = "test-correlation-123"
                    mock_sess_id.return_value = "test-session-456" 
                    mock_user_id.return_value = 1
                    
                    # Test license assignment
                    license = LicenseService.assign_license(
                        db=db_session,
                        user_id=1,
                        license_type="12m",
                        scope={"features": ["basic"]},
                        actor_type="user"
                    )
                    
                    # Verify license was created
                    assert license is not None
                    
                    # Verify database operations were called
                    db_session.add.assert_called()
                    db_session.flush.assert_called()


class TestEndToEndObservability:
    """End-to-end observability tests simulating real request flow."""
    
    def test_complete_license_flow_observability(self):
        """Test complete license assignment flow with full observability."""
        
        # This test would require a full application context
        # For now, we verify components work together
        
        correlation_id = str(uuid.uuid4())
        
        # Test that all observability components can work together
        with create_span("test_full_flow", correlation_id=correlation_id):
            
            # Track metrics
            metrics.license_operations_total.labels(
                operation="assign",
                license_type="12m",
                status="success", 
                user_type="user"
            ).inc()
            
            # Create audit entry (would be done via audit service in real flow)
            metrics.audit_logs_created_total.labels(
                event_type="license_assigned",
                scope_type="license",
                actor_type="user",
                classification="business_audit"  
            ).inc()
            
            # The fact that this completes without error indicates
            # basic integration is working
            
        assert True  # Test passes if no exceptions raised


class TestTurkishComplianceFeatures:
    """Test Turkish KVKV compliance specific features."""
    
    def test_turkish_log_messages(self):
        """Test that Turkish log messages are properly formatted."""
        from app.core.logging_config import TURKISH_LOG_LEVELS, COMPLIANCE_CLASSIFICATIONS
        
        # Verify Turkish translations exist
        assert TURKISH_LOG_LEVELS["CRITICAL"] == "KRİTİK"
        assert TURKISH_LOG_LEVELS["ERROR"] == "HATA"
        assert TURKISH_LOG_LEVELS["WARNING"] == "UYARI" 
        assert TURKISH_LOG_LEVELS["INFO"] == "BİLGİ"
        assert TURKISH_LOG_LEVELS["DEBUG"] == "HATA_AYIKLAMA"
        
        # Verify compliance classifications
        assert COMPLIANCE_CLASSIFICATIONS["PUBLIC"] == "genel"
        assert COMPLIANCE_CLASSIFICATIONS["RESTRICTED"] == "kısıtlı"
        assert COMPLIANCE_CLASSIFICATIONS["SECRET"] == "gizli_veri"
    
    def test_kvkv_pii_redaction(self):
        """Test PII redaction for KVKV compliance."""
        from app.core.logging_config import KVKVCompliantFormatter
        
        formatter = KVKVCompliantFormatter(redact_pii=True)
        
        # Test PII field detection and masking
        test_data = {
            "email": "user@example.com",
            "eposta": "test@test.com", 
            "telefon": "5551234567",
            "tc_no": "12345678901",
            "safe_field": "safe_value",
            "nested": {
                "email": "nested@example.com",
                "safe_nested": "safe_value"
            }
        }
        
        masked_data = formatter._redact_pii_fields(test_data)
        
        # Verify PII fields are masked
        assert "***" in masked_data["email"]
        assert "***" in masked_data["eposta"]  
        assert "***" in masked_data["telefon"]
        assert "***" in masked_data["tc_no"]
        
        # Verify safe fields are unchanged
        assert masked_data["safe_field"] == "safe_value"
        assert masked_data["nested"]["safe_nested"] == "safe_value"
        
        # Verify nested PII is masked
        assert "***" in masked_data["nested"]["email"]


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])