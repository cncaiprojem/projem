"""
Comprehensive tests for structured logging with structlog.
"""

import json
import logging
import time
from io import StringIO
from unittest.mock import Mock, patch, MagicMock
import asyncio

import pytest
import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.logging import (
    configure_structlog,
    get_logger,
    log_execution,
    log_database_query,
    log_external_api_call,
    log_security_event,
    request_id_ctx,
    user_id_ctx,
    task_id_ctx,
)
from app.middleware.logging import LoggingMiddleware, generate_request_id
from app.core.celery_logging import log_task_execution, LoggingTask
from app.core.database_logging import setup_database_logging, QueryLogger, log_transaction


class TestStructlogConfiguration:
    """Test structlog configuration and basic logging."""

    def test_development_configuration(self, monkeypatch):
        """Test development environment configuration."""
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        # Reconfigure structlog
        configure_structlog()

        logger = get_logger("test")

        # Capture logs
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            logger.info("test_message", key="value")
            output = mock_stdout.getvalue()

        # Should have colorful output in development
        assert "test_message" in output
        assert "key" in output
        assert "value" in output

    def test_production_configuration(self, monkeypatch):
        """Test production environment configuration."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("LOG_LEVEL", "INFO")

        # Reconfigure structlog
        configure_structlog()

        logger = get_logger("test")

        # Capture logs
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            logger.info("test_message", key="value")
            output = mock_stdout.getvalue()

        # Should have JSON output in production
        try:
            log_entry = json.loads(output.strip())
            assert log_entry["event"] == "test_message"
            assert log_entry["key"] == "value"
            assert "timestamp" in log_entry
        except json.JSONDecodeError:
            pytest.fail("Production logs should be valid JSON")

    def test_context_variables(self):
        """Test context variable propagation."""
        logger = get_logger("test")

        # Set context variables
        request_id_ctx.set("req-123")
        user_id_ctx.set("user-456")
        task_id_ctx.set("task-789")

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            logger.info("context_test")
            output = mock_stdout.getvalue()

        # Context should be included in logs
        assert "req-123" in output
        assert "user-456" in output
        assert "task-789" in output

        # Clear context
        request_id_ctx.set(None)
        user_id_ctx.set(None)
        task_id_ctx.set(None)

    def test_turkish_message_mapping(self):
        """Test Turkish message translations."""
        logger = get_logger("test")

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            logger.info("request_started")
            output = mock_stdout.getvalue()

        # Should include Turkish translation
        assert "İstek başlatıldı" in output or "message_tr" in output

    def test_sensitive_data_masking(self):
        """Test sensitive data masking."""
        logger = get_logger("test")

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            logger.info(
                "test",
                password="secret123",
                token="bearer_token_xyz",
                api_key="sk-1234567890",
                credit_card="4111111111111111",
            )
            output = mock_stdout.getvalue()

        # Sensitive data should be masked
        assert "secret123" not in output
        assert "bearer_token_xyz" not in output
        assert "1234567890" not in output
        assert "4111111111111111" not in output
        assert "***" in output


class TestLogExecutionDecorator:
    """Test the log_execution decorator."""

    @pytest.mark.asyncio
    async def test_async_function_logging(self):
        """Test logging of async functions."""

        @log_execution(level="INFO", include_args=True, include_result=True)
        async def async_test_function(x: int, y: int) -> int:
            await asyncio.sleep(0.01)
            return x + y

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = await async_test_function(2, 3)
            output = mock_stdout.getvalue()

        assert result == 5
        assert "function_entry" in output
        assert "function_exit" in output
        assert "async_test_function" in output
        assert "[2, 3]" in output  # args should be logged
        assert "5" in output  # result should be logged

    def test_sync_function_logging(self):
        """Test logging of sync functions."""

        @log_execution(level="DEBUG", include_args=False, include_result=False)
        def sync_test_function(x: int, y: int) -> int:
            time.sleep(0.01)
            return x * y

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = sync_test_function(4, 5)
            output = mock_stdout.getvalue()

        assert result == 20
        assert "function_entry" in output
        assert "function_exit" in output
        assert "sync_test_function" in output
        assert "elapsed_ms" in output

    @pytest.mark.asyncio
    async def test_function_error_logging(self):
        """Test logging of function errors."""

        @log_execution()
        async def failing_function():
            raise ValueError("Test error")

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            with pytest.raises(ValueError):
                await failing_function()
            output = mock_stdout.getvalue()

        assert "function_error" in output
        assert "Test error" in output
        assert "ValueError" in output

    def test_slow_function_warning(self):
        """Test slow function detection."""

        @log_execution()
        def slow_function():
            time.sleep(1.1)  # Sleep for more than 1 second
            return "done"

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = slow_function()
            output = mock_stdout.getvalue()

        assert result == "done"
        assert "slow_function_execution" in output or "WARNING" in output


class TestLoggingMiddleware:
    """Test the FastAPI logging middleware."""

    def test_request_logging(self):
        """Test basic request/response logging."""
        app = FastAPI()

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        app.add_middleware(LoggingMiddleware)
        client = TestClient(app)

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            response = client.get("/test")
            output = mock_stdout.getvalue()

        assert response.status_code == 200
        assert "request_started" in output
        assert "request_completed" in output
        assert "GET" in output
        assert "/test" in output

    def test_correlation_id_generation(self):
        """Test correlation ID generation and propagation."""
        app = FastAPI()

        @app.get("/test")
        def test_endpoint(request: Request):
            return {"request_id": request_id_ctx.get()}

        app.add_middleware(LoggingMiddleware)
        client = TestClient(app)

        response = client.get("/test")
        assert response.status_code == 200

        # Should have X-Request-ID header
        assert "X-Request-ID" in response.headers
        request_id = response.headers["X-Request-ID"]
        assert len(request_id) > 0

    def test_slow_request_warning(self):
        """Test slow request detection."""
        app = FastAPI()

        @app.get("/slow")
        def slow_endpoint():
            time.sleep(1.1)
            return {"message": "slow"}

        app.add_middleware(LoggingMiddleware, slow_request_threshold_ms=1000)
        client = TestClient(app)

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            response = client.get("/slow")
            output = mock_stdout.getvalue()

        assert response.status_code == 200
        assert "slow_request" in output or "WARNING" in output

    def test_error_logging(self):
        """Test error response logging."""
        app = FastAPI()

        @app.get("/error")
        def error_endpoint():
            raise HTTPException(status_code=500, detail="Internal error")

        app.add_middleware(LoggingMiddleware)
        client = TestClient(app)

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            response = client.get("/error")
            output = mock_stdout.getvalue()

        assert response.status_code == 500
        assert "ERROR" in output or "http_response_error" in output

    def test_security_event_logging(self):
        """Test security event logging for auth failures."""
        app = FastAPI()

        @app.get("/protected")
        def protected_endpoint():
            raise HTTPException(status_code=401, detail="Unauthorized")

        app.add_middleware(LoggingMiddleware)
        client = TestClient(app)

        with patch("app.core.logging.log_security_event") as mock_security_log:
            response = client.get("/protected")

            # Should log security event
            mock_security_log.assert_called()
            call_args = mock_security_log.call_args
            assert call_args[0][0] == "authentication_failed"


class TestDatabaseLogging:
    """Test database query logging."""

    def test_query_logging(self):
        """Test basic query logging."""
        with patch("app.core.logging.get_logger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            log_database_query(
                query="SELECT * FROM users WHERE id = ?", params={"id": 1}, duration_ms=50
            )

            mock_logger.debug.assert_called_once()
            call_args = mock_logger.debug.call_args
            assert "database_query" in call_args[0]
            assert call_args[1]["duration_ms"] == 50

    def test_slow_query_warning(self):
        """Test slow query detection."""
        with patch("app.core.logging.get_logger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            log_database_query(query="SELECT * FROM large_table", duration_ms=1500)

            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert "slow_database_query" in call_args[0]

    def test_query_logger_context_manager(self):
        """Test QueryLogger context manager."""
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            with QueryLogger("user_fetch", user_id=123) as qlog:
                time.sleep(0.01)
                qlog.log_info(user_count=5)

            output = mock_stdout.getvalue()

        assert "database_operation_start" in output
        assert "database_operation_complete" in output
        assert "user_fetch" in output
        assert "user_count" in output

    @log_transaction("test_transaction")
    def sample_transaction(value):
        """Sample function with transaction logging."""
        return value * 2

    def test_transaction_decorator(self):
        """Test transaction logging decorator."""
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = self.sample_transaction(5)
            output = mock_stdout.getvalue()

        assert result == 10
        assert "database_transaction_start" in output
        assert "database_transaction_complete" in output
        assert "test_transaction" in output


class TestCeleryLogging:
    """Test Celery task logging."""

    def test_task_execution_decorator(self):
        """Test Celery task execution decorator."""

        @log_task_execution(include_args=True, include_result=True)
        def sample_task(x, y):
            return x + y

        with patch("app.core.celery_logging.current_task") as mock_task:
            mock_task.request.id = "task-123"
            mock_task.name = "sample_task"

            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                result = sample_task(10, 20)
                output = mock_stdout.getvalue()

            assert result == 30
            assert "task_execution_start" in output
            assert "task_execution_complete" in output
            assert "task-123" in output

    def test_logging_task_class(self):
        """Test LoggingTask base class."""
        task = LoggingTask()
        task.name = "test_task"
        task.request = Mock(id="task-456")
        task.__module__ = "test_module"

        # Mock the parent call method
        with patch.object(LoggingTask, "__call__", return_value="result"):
            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                result = task(1, 2, key="value")
                output = mock_stdout.getvalue()

        assert "task_call" in output
        assert "task-456" in output


class TestSecurityLogging:
    """Test security event logging."""

    def test_security_event_logging(self):
        """Test logging of security events."""
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            log_security_event(
                "failed_login",
                user_id="user-123",
                ip_address="192.168.1.1",
                details={"attempts": 3},
            )
            output = mock_stdout.getvalue()

        assert "security_event" in output or "WARNING" in output
        assert "failed_login" in output
        assert "user-123" in output
        assert "192.168.1.1" in output

    def test_critical_security_event(self):
        """Test logging of critical security events."""
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            log_security_event(
                "intrusion_attempt", ip_address="10.0.0.1", details={"method": "SQL injection"}
            )
            output = mock_stdout.getvalue()

        assert "CRITICAL" in output or "critical_security_event" in output
        assert "intrusion_attempt" in output


class TestExternalAPILogging:
    """Test external API call logging."""

    def test_successful_api_call_logging(self):
        """Test logging of successful API calls."""
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            log_external_api_call(
                service="github",
                method="GET",
                url="https://api.github.com/users/test",
                status_code=200,
                duration_ms=150,
            )
            output = mock_stdout.getvalue()

        assert "external_api_call" in output
        assert "github" in output
        assert "200" in output or "status_code" in output

    def test_failed_api_call_logging(self):
        """Test logging of failed API calls."""
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            log_external_api_call(
                service="payment_gateway",
                method="POST",
                url="https://api.payment.com/charge",
                status_code=500,
                error="Internal server error",
            )
            output = mock_stdout.getvalue()

        assert "ERROR" in output or "external_api_error" in output
        assert "payment_gateway" in output
        assert "Internal server error" in output

    def test_slow_api_call_warning(self):
        """Test slow API call detection."""
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            log_external_api_call(
                service="slow_service",
                method="GET",
                url="https://slow.api.com/data",
                status_code=200,
                duration_ms=6000,
            )
            output = mock_stdout.getvalue()

        assert "WARNING" in output or "slow_external_api_call" in output
        assert "6000" in output or "duration_ms" in output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
