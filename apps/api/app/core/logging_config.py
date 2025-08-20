"""
Ultra-Enterprise Structured Logging Configuration for Task 4.10
Enhanced logging with Turkish KVKV compliance and observability integration

Features:
- Structured JSON logging with correlation IDs
- Turkish compliance with PII redaction
- Banking-grade security log classification
- Performance optimized formatters
- Multi-level log routing and retention
- Integration with observability metrics
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import settings
from ..middleware.correlation_middleware import get_correlation_id, get_session_id

# Turkish compliance log levels with business meanings
TURKISH_LOG_LEVELS = {
    "CRITICAL": "KRİTİK",
    "ERROR": "HATA", 
    "WARNING": "UYARI",
    "INFO": "BİLGİ",
    "DEBUG": "HATA_AYIKLAMA"
}

COMPLIANCE_CLASSIFICATIONS = {
    "PUBLIC": "genel",           # Public information
    "INTERNAL": "iç_kullanım",   # Internal use only  
    "CONFIDENTIAL": "gizli",     # Confidential business data
    "RESTRICTED": "kısıtlı",     # Personal data / PII
    "SECRET": "gizli_veri"       # Financial/security data
}


class KVKVCompliantFormatter(logging.Formatter):
    """Turkish KVKV compliant JSON formatter with PII redaction."""
    
    def __init__(
        self,
        service_name: str = "freecad-api",
        environment: str = "development",
        include_correlation: bool = True,
        redact_pii: bool = True
    ):
        super().__init__()
        self.service_name = service_name
        self.environment = environment
        self.include_correlation = include_correlation
        self.redact_pii = redact_pii
        
        # PII field patterns to redact
        self.pii_patterns = {
            'email', 'e_mail', 'eposta', 'mail',
            'phone', 'telefon', 'tel', 'mobile',
            'ssn', 'tc_no', 'kimlik_no', 'identity',
            'iban', 'account', 'hesap', 'kart_no',
            'password', 'şifre', 'parola', 'secret',
            'token', 'key', 'anahtar', 'private',
            'ip_address', 'ip', 'address', 'adres'
        }
        
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as Turkish compliant JSON."""
        
        # Base log structure
        log_entry = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "level_tr": TURKISH_LOG_LEVELS.get(record.levelname, record.levelname),
            "service": self.service_name,
            "environment": self.environment,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "thread": record.thread,
            "process": record.process
        }
        
        # Add correlation IDs if available
        if self.include_correlation:
            correlation_id = get_correlation_id()
            session_id = get_session_id()
            
            if correlation_id:
                log_entry["correlation_id"] = correlation_id
            if session_id:
                log_entry["session_id"] = session_id
                
        # Add exception information
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info) if record.exc_info else None
            }
            
        # Add extra fields from record
        extra_fields = {}
        for key, value in record.__dict__.items():
            if key not in {
                'name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 
                'filename', 'module', 'lineno', 'funcName', 'created', 
                'msecs', 'relativeCreated', 'thread', 'threadName', 
                'processName', 'process', 'getMessage', 'exc_info', 'exc_text', 
                'stack_info', 'message'
            }:
                extra_fields[key] = value
                
        # Apply PII redaction to extra fields
        if self.redact_pii and extra_fields:
            extra_fields = self._redact_pii_fields(extra_fields)
            
        if extra_fields:
            log_entry.update(extra_fields)
            
        # Add compliance metadata
        log_entry["compliance"] = {
            "regulation": "KVKV_GDPR",
            "data_locality": "Turkey", 
            "retention_policy": self._get_retention_policy(record.levelname),
            "classification": self._classify_log_level(record.levelname),
            "pii_redacted": self.redact_pii
        }
        
        # Add observability metadata
        log_entry["observability"] = {
            "trace_enabled": True,
            "metrics_enabled": True,
            "audit_enabled": record.levelname in {"ERROR", "WARNING", "CRITICAL"}
        }
        
        return json.dumps(log_entry, ensure_ascii=False, separators=(',', ':'))
        
    def _redact_pii_fields(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Redact PII from log fields according to KVKV compliance."""
        redacted = {}
        
        for key, value in fields.items():
            key_lower = key.lower()
            
            # Check if field contains PII
            is_pii = any(pattern in key_lower for pattern in self.pii_patterns)
            
            if is_pii:
                if isinstance(value, str):
                    if len(value) <= 4:
                        # Fully redact short strings (4 chars or less)
                        redacted[key] = "****"
                    else:
                        # Partial redaction for longer strings
                        redacted[key] = f"{value[:2]}***{value[-1:]}"
                elif isinstance(value, (int, float)):
                    redacted[key] = "***REDACTED***"
                else:
                    redacted[key] = "***MASKED***"
            elif isinstance(value, dict):
                # Recursively redact nested dictionaries
                redacted[key] = self._redact_pii_fields(value)
            elif isinstance(value, list):
                # Redact list items if they contain dicts
                redacted[key] = [
                    self._redact_pii_fields(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                redacted[key] = value
                
        return redacted
        
    def _get_retention_policy(self, level: str) -> str:
        """Get log retention policy based on level."""
        retention_policies = {
            "CRITICAL": "7_years",      # Critical events - long retention
            "ERROR": "3_years",         # Error events - medium retention  
            "WARNING": "1_year",        # Warning events - standard retention
            "INFO": "6_months",         # Info events - short retention
            "DEBUG": "1_month"          # Debug events - minimal retention
        }
        return retention_policies.get(level, "6_months")
        
    def _classify_log_level(self, level: str) -> str:
        """Classify log level for compliance purposes."""
        classifications = {
            "CRITICAL": COMPLIANCE_CLASSIFICATIONS["SECRET"],
            "ERROR": COMPLIANCE_CLASSIFICATIONS["RESTRICTED"], 
            "WARNING": COMPLIANCE_CLASSIFICATIONS["CONFIDENTIAL"],
            "INFO": COMPLIANCE_CLASSIFICATIONS["INTERNAL"],
            "DEBUG": COMPLIANCE_CLASSIFICATIONS["INTERNAL"]
        }
        return classifications.get(level, COMPLIANCE_CLASSIFICATIONS["INTERNAL"])


class ObservabilityHandler(logging.Handler):
    """Custom handler that integrates with observability metrics."""
    
    def __init__(self, level=logging.NOTSET):
        super().__init__(level)
        self.metrics_enabled = True
        
    def emit(self, record: logging.LogRecord) -> None:
        """Emit log record and update observability metrics."""
        try:
            # Update metrics based on log level
            if self.metrics_enabled:
                self._update_metrics(record)
                
        except Exception:
            # Don't let metrics failures break logging
            self.handleError(record)
            
    def _update_metrics(self, record: logging.LogRecord) -> None:
        """Update Prometheus metrics based on log events."""
        from .. import metrics
        
        # Track log events by level and service
        service_name = getattr(record, 'service', 'freecad-api')
        
        # Update audit log metrics for important events
        if record.levelname in {"ERROR", "WARNING", "CRITICAL"}:
            event_type = getattr(record, 'event_type', 'log_event')
            scope_type = getattr(record, 'scope_type', 'application')
            actor_type = getattr(record, 'actor_type', 'system')
            classification = getattr(record, 'classification', 'internal')
            
            metrics.audit_logs_created_total.labels(
                event_type=event_type,
                scope_type=scope_type,
                actor_type=actor_type,
                classification=classification
            ).inc()
            
        # Track correlation ID propagation success
        if hasattr(record, 'correlation_id'):
            metrics.correlation_id_propagation_total.labels(
                service=service_name,
                direction="internal",
                success="true"
            ).inc()
            
        # Track PII redaction operations
        if getattr(record, 'pii_redacted', False):
            data_type = getattr(record, 'pii_data_type', 'mixed')
            masking_level = getattr(record, 'masking_level', 'medium')
            
            metrics.pii_redaction_operations_total.labels(
                data_type=data_type,
                masking_level=masking_level,
                regulation="KVKV"
            ).inc()


class PerformanceLogFilter(logging.Filter):
    """Filter to add performance metrics to log records."""
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Add performance metadata to log records."""
        
        # Add request timing if available
        from ..middleware.correlation_middleware import get_request_start_time
        start_time = get_request_start_time()
        
        if start_time:
            record.request_duration_ms = int((time.time() - start_time) * 1000)
            
        # Add memory usage for critical logs
        if record.levelname in {"CRITICAL", "ERROR"}:
            try:
                import psutil
                import os
                process = psutil.Process(os.getpid())
                record.memory_mb = int(process.memory_info().rss / 1024 / 1024)
            except Exception:
                pass
                
        return True


def setup_structured_logging(
    service_name: str = "freecad-api",
    environment: str = None,
    log_level: str = "INFO",
    enable_console: bool = True,
    enable_file: bool = False,
    log_file_path: Optional[str] = None
) -> None:
    """Setup comprehensive structured logging with Turkish KVKV compliance.
    
    Args:
        service_name: Name of the service for log identification
        environment: Deployment environment (dev, staging, prod)
        log_level: Minimum log level to capture
        enable_console: Enable console output
        enable_file: Enable file output 
        log_file_path: Path to log file if file output enabled
    """
    
    # Use settings if environment not provided
    if environment is None:
        environment = getattr(settings, 'env', 'development')
        
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        
    # Create KVKV compliant formatter
    # Use settings for PII redaction if available, otherwise default based on environment
    pii_redaction_enabled = getattr(settings, 'pii_redaction_enabled', (environment == "production"))
    formatter = KVKVCompliantFormatter(
        service_name=service_name,
        environment=environment,
        include_correlation=True,
        redact_pii=pii_redaction_enabled
    )
    
    # Create performance filter
    perf_filter = PerformanceLogFilter()
    
    # Setup console handler
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(perf_filter)
        root_logger.addHandler(console_handler)
        
    # Setup file handler
    if enable_file and log_file_path:
        log_path = Path(log_file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setFormatter(formatter)
        file_handler.addFilter(perf_filter)
        root_logger.addHandler(file_handler)
        
    # Add observability handler
    obs_handler = ObservabilityHandler()
    obs_handler.setLevel(logging.WARNING)  # Only track warnings and above
    root_logger.addHandler(obs_handler)
    
    # Configure specific loggers for better control
    
    # Suppress noisy third-party loggers in production
    if environment == "production":
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("requests").setLevel(logging.WARNING)
        logging.getLogger("fastapi").setLevel(logging.INFO)
        logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
        
    # Enhanced logging for critical business components
    business_loggers = [
        "app.services.license_service",
        "app.services.payment_service", 
        "app.services.invoice_service",
        "app.services.audit_service",
        "app.middleware.license_middleware",
        "app.middleware.correlation_middleware"
    ]
    
    for logger_name in business_loggers:
        business_logger = logging.getLogger(logger_name)
        business_logger.setLevel(logging.INFO)
        
    # Log configuration completion
    logger = logging.getLogger(__name__)
    logger.info(
        "structured_logging_yapılandırıldı",
        service=service_name,
        environment=environment,
        log_level=log_level,
        console_enabled=enable_console,
        file_enabled=enable_file,
        compliance="KVKV_GDPR",
        pii_redaction_enabled=pii_redaction_enabled,
        observability_integration=True
    )


# Export main functions
__all__ = [
    "KVKVCompliantFormatter",
    "ObservabilityHandler", 
    "PerformanceLogFilter",
    "setup_structured_logging",
    "TURKISH_LOG_LEVELS",
    "COMPLIANCE_CLASSIFICATIONS"
]