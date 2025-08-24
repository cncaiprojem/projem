"""
Task 6.10: Structured logging configuration with PII masking and Turkish compliance.

Implements:
- structlog with request_id, trace_id, job_id, idempotency_key fields
- PII masking for Turkish KVKV compliance
- Performance metadata injection
- Turkish log level translations
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import structlog
from contextvars import ContextVar

# Context variables for tracking request context
request_context: ContextVar[Dict[str, Any]] = ContextVar('request_context', default={})

# Turkish log level translations
TURKISH_LOG_LEVELS = {
    "CRITICAL": "KRİTİK",
    "ERROR": "HATA", 
    "WARNING": "UYARI",
    "INFO": "BİLGİ",
    "DEBUG": "HATA_AYIKLAMA"
}

# PII field patterns (Turkish and English)
PII_PATTERNS = {
    # Email patterns
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b': '***@***.***',
    # Phone patterns (Turkish format)
    r'\b(\+90|0)?[5][0-9]{9}\b': '***-***-****',
    # TC Kimlik No (Turkish ID)
    r'\b[1-9][0-9]{10}\b': '***********',
    # Credit card patterns
    r'\b[0-9]{4}[\s\-]?[0-9]{4}[\s\-]?[0-9]{4}[\s\-]?[0-9]{4}\b': '****-****-****-****',
    # IP addresses
    r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b': '***.***.***.***'
}

# PII field names to mask
PII_FIELDS = {
    'email', 'eposta', 'e_posta', 'mail',
    'phone', 'telefon', 'tel', 'gsm',
    'tc_no', 'tc_kimlik', 'kimlik_no', 'identity',
    'password', 'sifre', 'parola', 'pwd',
    'ssn', 'social_security', 
    'credit_card', 'kredi_karti', 'card_number',
    'iban', 'bank_account', 'hesap_no',
    'ip_address', 'client_ip', 'remote_addr'
}


class TurkishCompliantFormatter:
    """
    Structured log formatter with Turkish KVKV compliance and PII masking.
    """
    
    def __init__(
        self,
        service_name: str = "freecad-api",
        environment: str = "development",
        redact_pii: bool = True
    ):
        self.service_name = service_name
        self.environment = environment
        self.redact_pii = redact_pii
    
    def __call__(self, logger, method_name, event_dict):
        """
        Process log event with Turkish compliance features.
        """
        # Add timestamp in ISO format
        event_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
        
        # Add service metadata
        event_dict["service"] = self.service_name
        event_dict["environment"] = self.environment
        
        # Add log level with Turkish translation
        level = event_dict.get("level", "info").upper()
        event_dict["level"] = level.lower()
        event_dict["level_tr"] = TURKISH_LOG_LEVELS.get(level, level)
        
        # Add request context from context variables
        ctx = request_context.get({})
        if ctx:
            event_dict.update({k: v for k, v in ctx.items() if v is not None})
        
        # Add compliance metadata
        event_dict["compliance"] = {
            "regulation": "KVKV_GDPR",
            "data_locality": "Turkey", 
            "pii_redacted": self.redact_pii,
            "retention_policy": "7_years"
        }
        
        # Mask PII if enabled
        if self.redact_pii:
            event_dict = self._redact_pii_fields(event_dict)
        
        return event_dict
    
    def _redact_pii_fields(self, data: Any) -> Any:
        """
        Recursively redact PII fields from data structures.
        """
        if isinstance(data, dict):
            redacted = {}
            for key, value in data.items():
                if key.lower() in PII_FIELDS:
                    redacted[key] = self._mask_value(str(value))
                else:
                    redacted[key] = self._redact_pii_fields(value)
            return redacted
        elif isinstance(data, list):
            return [self._redact_pii_fields(item) for item in data]
        elif isinstance(data, str):
            return self._mask_patterns(data)
        else:
            return data
    
    def _mask_value(self, value: str) -> str:
        """Mask a PII value."""
        if not value or len(value) < 3:
            return "***"
        
        if "@" in value:  # Email
            parts = value.split("@")
            if len(parts) == 2:
                return f"{parts[0][:2]}***@{parts[1][:2]}***.***"
        
        # Generic masking: keep first 2 and last 1 characters
        return f"{value[:2]}***{value[-1:]}"
    
    def _mask_patterns(self, text: str) -> str:
        """Mask PII patterns in text."""
        for pattern, replacement in PII_PATTERNS.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text


class PerformanceLogFilter:
    """
    Log filter that adds performance metadata to log records.
    """
    
    def filter(self, record):
        """Add performance metadata to log records."""
        # Add memory usage for critical logs
        if record.levelno >= logging.ERROR:
            try:
                import psutil
                process = psutil.Process()
                record.memory_mb = round(process.memory_info().rss / 1024 / 1024, 2)
                record.cpu_percent = process.cpu_percent()
            except ImportError:
                pass
        
        # Add request duration if available in context
        ctx = request_context.get({})
        if 'request_start_time' in ctx:
            duration = time.time() - ctx['request_start_time']
            record.request_duration_ms = round(duration * 1000, 2)
        
        return True


def setup_structured_logging(
    service_name: str = "freecad-api",
    environment: str = "development",
    log_level: str = "INFO"
):
    """
    Configure structured logging for the application.
    """
    # Configure structlog processors
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        TurkishCompliantFormatter(
            service_name=service_name,
            environment=environment,
            redact_pii=True
        ),
        structlog.processors.JSONRenderer(sort_keys=True)
    ]
    
    # Configure structlog
    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Configure standard library logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(message)s",
        handlers=[logging.StreamHandler()]
    )
    
    # Add performance filter
    perf_filter = PerformanceLogFilter()
    root_logger = logging.getLogger()
    root_logger.addFilter(perf_filter)


def bind_request_context(**kwargs):
    """Bind request-specific context variables."""
    ctx = request_context.get({})
    ctx.update(kwargs)
    request_context.set(ctx)


def clear_request_context():
    """Clear request context variables."""
    request_context.set({})


def get_logger(name: str = None) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)


# Request context helpers
def get_request_id() -> Optional[str]:
    """Get current request ID from context."""
    return request_context.get({}).get('request_id')


def get_trace_id() -> Optional[str]:
    """Get current trace ID from context."""
    return request_context.get({}).get('trace_id')


def get_job_id() -> Optional[str]:
    """Get current job ID from context."""
    return request_context.get({}).get('job_id')


def get_idempotency_key() -> Optional[str]:
    """Get current idempotency key from context."""
    return request_context.get({}).get('idempotency_key')


def generate_request_id() -> str:
    """Generate a new request ID."""
    return f"req-{uuid.uuid4().hex[:12]}"


def generate_trace_id() -> str:
    """Generate a new trace ID."""
    return f"trace-{uuid.uuid4().hex[:16]}"