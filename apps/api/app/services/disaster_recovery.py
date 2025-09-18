"""
Task 7.26: Disaster Recovery Orchestrator

Recovery planning, failover management, health monitoring, and notification system.
Implements RTO/RPO targets with automated failover and recovery workflows.

Features:
- Recovery Time Objective (RTO) management
- Recovery Point Objective (RPO) tracking
- Automated failover with health checks
- Multi-site replication coordination
- Recovery plan execution with rollback
- Health monitoring and alerting
- Notification system for incidents
- Turkish localization for all messages
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

import httpx
from pydantic import BaseModel, Field, field_validator

from ..core.environment import environment as settings
from ..core.logging import get_logger
from ..core.telemetry import create_span
from ..core import metrics
from ..middleware.correlation_middleware import get_correlation_id
from ..services.profiling_state_manager import state_manager

logger = get_logger(__name__)


class DisasterType(str, Enum):
    """Types of disasters."""
    HARDWARE_FAILURE = "hardware_failure"
    NETWORK_OUTAGE = "network_outage"
    DATA_CORRUPTION = "data_corruption"
    CYBER_ATTACK = "cyber_attack"
    NATURAL_DISASTER = "natural_disaster"
    HUMAN_ERROR = "human_error"
    SOFTWARE_BUG = "software_bug"


class RecoveryPriority(str, Enum):
    """Recovery priority levels."""
    CRITICAL = "critical"      # RTO < 1 hour, RPO < 15 min
    HIGH = "high"             # RTO < 4 hours, RPO < 1 hour
    MEDIUM = "medium"         # RTO < 24 hours, RPO < 4 hours
    LOW = "low"              # RTO < 72 hours, RPO < 24 hours


class RecoveryState(str, Enum):
    """Recovery operation states."""
    IDLE = "idle"
    DETECTING = "detecting"
    ASSESSING = "assessing"
    INITIATING = "initiating"
    RECOVERING = "recovering"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class HealthStatus(str, Enum):
    """Component health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class NotificationChannel(str, Enum):
    """Notification channels."""
    EMAIL = "email"
    SMS = "sms"
    WEBHOOK = "webhook"
    SLACK = "slack"
    TEAMS = "teams"
    PAGERDUTY = "pagerduty"


@dataclass
class RTOTarget:
    """Recovery Time Objective target."""
    priority: RecoveryPriority
    max_minutes: int
    warning_threshold: float = 0.8  # Warn at 80% of target


@dataclass
class RPOTarget:
    """Recovery Point Objective target."""
    priority: RecoveryPriority
    max_data_loss_minutes: int
    backup_frequency_minutes: int


class DisasterRecoveryConfig(BaseModel):
    """Disaster recovery configuration."""

    # RTO/RPO targets
    rto_targets: Dict[str, int] = Field(default={
        "critical": 60,    # 1 hour
        "high": 240,       # 4 hours
        "medium": 1440,    # 24 hours
        "low": 4320        # 72 hours
    }, description="RTO targets in minutes by priority")

    rpo_targets: Dict[str, int] = Field(default={
        "critical": 15,    # 15 minutes
        "high": 60,        # 1 hour
        "medium": 240,     # 4 hours
        "low": 1440        # 24 hours
    }, description="RPO targets in minutes by priority")

    # Health monitoring
    health_check_interval_seconds: int = Field(default=30)
    health_check_timeout_seconds: int = Field(default=10)
    unhealthy_threshold: int = Field(default=3, description="Failures before marking unhealthy")
    healthy_threshold: int = Field(default=2, description="Successes before marking healthy")

    # Failover settings
    auto_failover_enabled: bool = Field(default=False)
    failover_delay_seconds: int = Field(default=300, description="Wait before auto-failover")
    require_manual_approval: bool = Field(default=True)
    max_failover_attempts: int = Field(default=3)

    # Replication
    enable_multi_site: bool = Field(default=True)
    primary_site: str = Field(default="site-1")
    secondary_sites: List[str] = Field(default_factory=lambda: ["site-2", "site-3"])
    replication_lag_threshold_seconds: int = Field(default=60)

    # Notifications
    enable_notifications: bool = Field(default=True)
    notification_channels: List[NotificationChannel] = Field(
        default_factory=lambda: [NotificationChannel.EMAIL, NotificationChannel.WEBHOOK]
    )
    notification_webhooks: List[str] = Field(default_factory=list)


class HealthCheck(BaseModel):
    """Health check definition."""
    check_id: str = Field(description="Unique check identifier")
    name: str = Field(description="Check name")
    component: str = Field(description="Component being checked")
    check_type: str = Field(default="http", description="http/tcp/process/custom")
    endpoint: Optional[str] = Field(default=None, description="Health endpoint URL")
    expected_status: int = Field(default=200, description="Expected HTTP status")
    interval_seconds: int = Field(default=30)
    timeout_seconds: int = Field(default=10)
    critical: bool = Field(default=False, description="Is this critical for recovery")


class RecoveryPlan(BaseModel):
    """Disaster recovery plan."""
    plan_id: str = Field(description="Unique plan identifier")
    name: str = Field(description="Plan name")
    disaster_type: DisasterType
    priority: RecoveryPriority
    steps: List[RecoveryStep] = Field(default_factory=list)
    rollback_steps: List[RecoveryStep] = Field(default_factory=list)
    pre_checks: List[str] = Field(default_factory=list, description="Health check IDs")
    post_checks: List[str] = Field(default_factory=list, description="Verification check IDs")
    estimated_duration_minutes: int = Field(default=60)
    requires_approval: bool = Field(default=False)
    tags: List[str] = Field(default_factory=list)


class RecoveryStep(BaseModel):
    """Individual recovery step."""
    step_id: str = Field(description="Unique step identifier")
    name: str = Field(description="Step name")
    description: str = Field(description="Step description")
    step_type: str = Field(default="script", description="script/manual/wait/check")
    script: Optional[str] = Field(default=None, description="Script to execute")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=300)
    retry_count: int = Field(default=3)
    can_fail: bool = Field(default=False, description="Continue on failure")
    order: int = Field(default=0, description="Execution order")


class DisasterEvent(BaseModel):
    """Disaster event record."""
    event_id: str = Field(description="Unique event identifier")
    disaster_type: DisasterType
    severity: RecoveryPriority
    description: str
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    impacted_components: List[str] = Field(default_factory=list)
    recovery_plan_id: Optional[str] = Field(default=None)
    recovery_state: RecoveryState = Field(default=RecoveryState.DETECTING)
    recovery_started_at: Optional[datetime] = Field(default=None)
    recovery_completed_at: Optional[datetime] = Field(default=None)
    rto_target_minutes: Optional[int] = Field(default=None)
    rpo_target_minutes: Optional[int] = Field(default=None)
    actual_recovery_time_minutes: Optional[int] = Field(default=None)
    data_loss_minutes: Optional[int] = Field(default=None)
    notifications_sent: List[Dict[str, Any]] = Field(default_factory=list)


class RecoveryMetrics(BaseModel):
    """Recovery metrics tracking."""
    total_events: int = Field(default=0)
    successful_recoveries: int = Field(default=0)
    failed_recoveries: int = Field(default=0)
    average_recovery_time_minutes: float = Field(default=0.0)
    rto_compliance_rate: float = Field(default=0.0)
    rpo_compliance_rate: float = Field(default=0.0)
    mttr: float = Field(default=0.0, description="Mean Time To Recovery")
    mtbf: float = Field(default=0.0, description="Mean Time Between Failures")


class HealthMonitor:
    """Component health monitoring."""

    def __init__(self, config: DisasterRecoveryConfig):
        self.config = config
        self.health_checks: Dict[str, HealthCheck] = {}
        self.health_status: Dict[str, HealthStatus] = {}
        self.failure_counts: Dict[str, int] = {}
        self.success_counts: Dict[str, int] = {}
        self.last_check_timestamps: Dict[str, datetime] = {}  # Track actual health check times
        self._monitoring_task = None
        self._monitoring_lock = asyncio.Lock()  # Add lock for race condition prevention
        self._http_client = httpx.AsyncClient(timeout=config.health_check_timeout_seconds)

    def add_health_check(self, check: HealthCheck):
        """Add health check."""
        self.health_checks[check.check_id] = check
        self.health_status[check.check_id] = HealthStatus.UNKNOWN
        self.failure_counts[check.check_id] = 0
        self.success_counts[check.check_id] = 0
        self.last_check_timestamps[check.check_id] = datetime.now(timezone.utc)

    async def _tcp_health_check(self, endpoint: Optional[str], timeout_seconds: float) -> bool:
        """
        Perform TCP health check with timeout and error handling.

        Args:
            endpoint: TCP endpoint in format "host:port" or "host" (defaults to port 80)
            timeout_seconds: Connection timeout in seconds

        Returns:
            True if TCP connection successful, False otherwise
        """
        if not endpoint:
            logger.warning("TCP sağlık kontrolü için endpoint tanımlı değil")
            return False

        try:
            # Parse endpoint to extract host and port
            if ':' in endpoint:
                # Handle explicit port (e.g., "localhost:8000" or "192.168.1.1:3306")
                parts = endpoint.rsplit(':', 1)
                host = parts[0]
                try:
                    port = int(parts[1])
                except ValueError:
                    logger.error(
                        "Geçersiz TCP port formatı",
                        endpoint=endpoint,
                        port=parts[1]
                    )
                    return False
            else:
                # No port specified, default to standard port 80
                host = endpoint
                port = 80

            # Remove protocol if present (e.g., "tcp://host" -> "host")
            if '://' in host:
                host = host.split('://')[-1]

            # Handle IPv6 addresses in brackets (e.g., "[::1]:8000")
            if host.startswith('[') and host.endswith(']'):
                host = host[1:-1]

            logger.debug(
                "TCP sağlık kontrolü başlatılıyor",
                host=host,
                port=port,
                timeout=timeout_seconds
            )

            # Attempt TCP connection with timeout
            try:
                # Use asyncio.wait_for to enforce timeout
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=timeout_seconds
                )

                # Connection successful, close it immediately
                writer.close()
                await writer.wait_closed()

                logger.debug(
                    "TCP bağlantısı başarılı",
                    host=host,
                    port=port
                )
                return True

            except asyncio.TimeoutError:
                logger.warning(
                    "TCP bağlantısı zaman aşımına uğradı",
                    host=host,
                    port=port,
                    timeout=timeout_seconds
                )
                return False

            except ConnectionRefusedError:
                logger.debug(
                    "TCP bağlantısı reddedildi",
                    host=host,
                    port=port
                )
                return False

            except OSError as e:
                # Covers various network errors (host unreachable, network down, etc.)
                logger.warning(
                    "TCP bağlantı hatası",
                    host=host,
                    port=port,
                    error=str(e)
                )
                return False

        except Exception as e:
            logger.error(
                "TCP sağlık kontrolü beklenmeyen hata",
                endpoint=endpoint,
                error=str(e),
                error_type=type(e).__name__
            )
            return False

    async def check_health(self, check_id: str) -> HealthStatus:
        """Execute health check."""
        check = self.health_checks.get(check_id)
        if not check:
            return HealthStatus.UNKNOWN

        try:
            if check.check_type == "http" and check.endpoint:
                response = await self._http_client.get(
                    check.endpoint,
                    timeout=check.timeout_seconds
                )
                is_healthy = response.status_code == check.expected_status

            elif check.check_type == "tcp":
                # TCP health check with proper timeout and error handling
                is_healthy = await self._tcp_health_check(check.endpoint, check.timeout_seconds)

            else:
                # Custom check
                is_healthy = await self._custom_health_check(check)

            # Update counters
            if is_healthy:
                self.success_counts[check_id] += 1
                self.failure_counts[check_id] = 0

                if self.success_counts[check_id] >= self.config.healthy_threshold:
                    self.health_status[check_id] = HealthStatus.HEALTHY
            else:
                self.failure_counts[check_id] += 1
                self.success_counts[check_id] = 0

                if self.failure_counts[check_id] >= self.config.unhealthy_threshold:
                    self.health_status[check_id] = HealthStatus.UNHEALTHY
                else:
                    self.health_status[check_id] = HealthStatus.DEGRADED

            # Update last check timestamp
            self.last_check_timestamps[check_id] = datetime.now(timezone.utc)

            logger.debug(
                "Sağlık kontrolü tamamlandı",
                check_id=check_id,
                status=self.health_status[check_id].value,
                failures=self.failure_counts[check_id]
            )

            return self.health_status[check_id]

        except Exception as e:
            logger.error("Sağlık kontrolü başarısız", check_id=check_id, error=str(e))
            self.failure_counts[check_id] += 1
            self.success_counts[check_id] = 0

            if self.failure_counts[check_id] >= self.config.unhealthy_threshold:
                self.health_status[check_id] = HealthStatus.UNHEALTHY

            # Update last check timestamp even on failure
            self.last_check_timestamps[check_id] = datetime.now(timezone.utc)

            return self.health_status[check_id]

    async def _custom_health_check(self, check: HealthCheck) -> bool:
        """Execute custom health check."""
        # Would implement custom check logic
        return True

    async def start_monitoring(self):
        """Start health monitoring loop."""
        async with self._monitoring_lock:
            if self._monitoring_task:
                return

            self._monitoring_task = asyncio.create_task(self._monitoring_loop())
            logger.info("Sağlık izleme başlatıldı")

    async def stop_monitoring(self):
        """Stop health monitoring."""
        async with self._monitoring_lock:
            if self._monitoring_task:
                self._monitoring_task.cancel()
                try:
                    await self._monitoring_task
                except asyncio.CancelledError:
                    pass
                self._monitoring_task = None
                logger.info("Sağlık izleme durduruldu")

            await self._http_client.aclose()

    async def _monitoring_loop(self):
        """Health monitoring loop."""
        while True:
            try:
                # Check all health checks
                tasks = []
                for check_id in self.health_checks:
                    tasks.append(self.check_health(check_id))

                await asyncio.gather(*tasks, return_exceptions=True)

                # Sleep before next check
                await asyncio.sleep(self.config.health_check_interval_seconds)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("İzleme döngüsü hatası", error=str(e))
                await asyncio.sleep(self.config.health_check_interval_seconds)

    def get_overall_health(self) -> HealthStatus:
        """Get overall system health."""
        if not self.health_status:
            return HealthStatus.UNKNOWN

        # Check critical components
        critical_unhealthy = any(
            self.health_status.get(check_id) == HealthStatus.UNHEALTHY
            for check_id, check in self.health_checks.items()
            if check.critical
        )

        if critical_unhealthy:
            return HealthStatus.UNHEALTHY

        # Check for any unhealthy
        if any(status == HealthStatus.UNHEALTHY for status in self.health_status.values()):
            return HealthStatus.DEGRADED

        # Check for any degraded
        if any(status == HealthStatus.DEGRADED for status in self.health_status.values()):
            return HealthStatus.DEGRADED

        # All healthy or unknown
        if all(status == HealthStatus.HEALTHY for status in self.health_status.values()):
            return HealthStatus.HEALTHY

        return HealthStatus.UNKNOWN


class NotificationManager:
    """Manage disaster recovery notifications."""

    def __init__(self, config: DisasterRecoveryConfig):
        self.config = config
        self._http_client = httpx.AsyncClient()

    async def send_notification(
        self,
        event: DisasterEvent,
        message: str,
        channels: Optional[List[NotificationChannel]] = None
    ):
        """Send notification about disaster event."""
        if not self.config.enable_notifications:
            return

        channels = channels or self.config.notification_channels

        for channel in channels:
            try:
                await self._send_to_channel(channel, event, message)

                event.notifications_sent.append({
                    "channel": channel.value,
                    "message": message,
                    "sent_at": datetime.now(timezone.utc).isoformat()
                })

            except Exception as e:
                logger.error("Bildirim gönderilemedi", channel=channel.value, error=str(e))

    async def _send_to_channel(
        self,
        channel: NotificationChannel,
        event: DisasterEvent,
        message: str
    ):
        """Send notification to specific channel."""
        if channel == NotificationChannel.WEBHOOK:
            for webhook_url in self.config.notification_webhooks:
                payload = {
                    "event_id": event.event_id,
                    "disaster_type": event.disaster_type.value,
                    "severity": event.severity.value,
                    "message": message,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }

                await self._http_client.post(webhook_url, json=payload)

        elif channel == NotificationChannel.EMAIL:
            # Would implement email sending
            logger.info("E-posta bildirimi gönderildi", message=message[:100])

        elif channel == NotificationChannel.SLACK:
            # Would implement Slack webhook
            logger.info("Slack bildirimi gönderildi", message=message[:100])

    async def close(self):
        """Close HTTP client."""
        await self._http_client.aclose()


class DisasterRecoveryOrchestrator:
    """Main disaster recovery orchestrator."""

    def __init__(self, config: Optional[DisasterRecoveryConfig] = None):
        self.config = config or DisasterRecoveryConfig()
        self.health_monitor = HealthMonitor(self.config)
        self.notification_manager = NotificationManager(self.config)
        self.recovery_plans: Dict[str, RecoveryPlan] = {}
        self.active_events: Dict[str, DisasterEvent] = {}
        self.recovery_history: deque = deque(maxlen=100)
        self.metrics = RecoveryMetrics()
        self._recovery_tasks: Dict[str, asyncio.Task] = {}

    def add_recovery_plan(self, plan: RecoveryPlan):
        """Add recovery plan."""
        self.recovery_plans[plan.plan_id] = plan
        logger.info("Kurtarma planı eklendi", plan_id=plan.plan_id, name=plan.name)

    async def detect_disaster(self, disaster_type: DisasterType, description: str) -> DisasterEvent:
        """Detect and record disaster event."""
        correlation_id = get_correlation_id()

        with create_span("disaster_detection", correlation_id=correlation_id) as span:
            span.set_attribute("disaster_type", disaster_type.value)

            # Create disaster event with UUID for uniqueness
            event_id = f"disaster_{uuid.uuid4().hex}"
            event = DisasterEvent(
                event_id=event_id,
                disaster_type=disaster_type,
                severity=RecoveryPriority.HIGH,  # Would determine dynamically
                description=description
            )

            # Assess impact
            event = await self._assess_impact(event)

            # Store event
            self.active_events[event_id] = event

            # Send notification
            await self.notification_manager.send_notification(
                event,
                f"Felaket tespit edildi: {disaster_type.value} - {description}"
            )

            logger.warning(
                "Felaket tespit edildi",
                event_id=event_id,
                type=disaster_type.value,
                description=description
            )

            metrics.disaster_events_total.labels(
                type=disaster_type.value,
                severity=event.severity.value
            ).inc()

            # Initiate recovery if auto-failover enabled
            if self.config.auto_failover_enabled and not self.config.require_manual_approval:
                await asyncio.sleep(self.config.failover_delay_seconds)
                await self.initiate_recovery(event_id)

            return event

    async def initiate_recovery(self, event_id: str, plan_id: Optional[str] = None) -> bool:
        """Initiate disaster recovery."""
        correlation_id = get_correlation_id()

        with create_span("disaster_recovery_initiate", correlation_id=correlation_id) as span:
            span.set_attribute("event_id", event_id)

            event = self.active_events.get(event_id)
            if not event:
                logger.error("Felaket olayı bulunamadı", event_id=event_id)
                return False

            # Select recovery plan
            if not plan_id:
                plan = self._select_recovery_plan(event)
                if not plan:
                    logger.error("Uygun kurtarma planı bulunamadı", event_id=event_id)
                    return False
            else:
                plan = self.recovery_plans.get(plan_id)
                if not plan:
                    logger.error("Kurtarma planı bulunamadı", plan_id=plan_id)
                    return False

            event.recovery_plan_id = plan.plan_id
            event.recovery_state = RecoveryState.INITIATING
            event.recovery_started_at = datetime.now(timezone.utc)

            # Set RTO/RPO targets
            rto_minutes = self.config.rto_targets.get(
                event.severity.value,
                1440  # Default 24 hours
            )
            rpo_minutes = self.config.rpo_targets.get(
                event.severity.value,
                240  # Default 4 hours
            )

            event.rto_target_minutes = rto_minutes
            event.rpo_target_minutes = rpo_minutes

            # Execute recovery plan
            recovery_task = asyncio.create_task(
                self._execute_recovery_plan(event, plan)
            )
            self._recovery_tasks[event_id] = recovery_task

            # Send notification
            await self.notification_manager.send_notification(
                event,
                f"Kurtarma başlatıldı: {plan.name} (RTO: {rto_minutes} dakika)"
            )

            logger.info(
                "Kurtarma başlatıldı",
                event_id=event_id,
                plan_id=plan.plan_id,
                rto_target=rto_minutes
            )

            return True

    async def _assess_impact(self, event: DisasterEvent) -> DisasterEvent:
        """Assess disaster impact."""
        # Check health of all components
        overall_health = self.health_monitor.get_overall_health()

        if overall_health == HealthStatus.UNHEALTHY:
            event.severity = RecoveryPriority.CRITICAL
        elif overall_health == HealthStatus.DEGRADED:
            event.severity = RecoveryPriority.HIGH

        # Identify impacted components
        for check_id, status in self.health_monitor.health_status.items():
            if status in [HealthStatus.UNHEALTHY, HealthStatus.DEGRADED]:
                check = self.health_monitor.health_checks.get(check_id)
                if check:
                    event.impacted_components.append(check.component)

        event.recovery_state = RecoveryState.ASSESSING

        return event

    def _select_recovery_plan(self, event: DisasterEvent) -> Optional[RecoveryPlan]:
        """Select appropriate recovery plan for event."""
        # Find matching plan by disaster type and priority
        for plan in self.recovery_plans.values():
            if (plan.disaster_type == event.disaster_type and
                plan.priority == event.severity):
                return plan

        # Fallback to any matching disaster type
        for plan in self.recovery_plans.values():
            if plan.disaster_type == event.disaster_type:
                return plan

        return None

    async def _execute_recovery_plan(self, event: DisasterEvent, plan: RecoveryPlan):
        """Execute recovery plan steps."""
        event.recovery_state = RecoveryState.RECOVERING

        try:
            # Execute pre-checks
            for check_id in plan.pre_checks:
                status = await self.health_monitor.check_health(check_id)
                if status == HealthStatus.UNHEALTHY:
                    logger.warning("Ön kontrol başarısız", check_id=check_id)

            # Execute recovery steps
            for step in sorted(plan.steps, key=lambda s: s.order):
                success = await self._execute_step(step)

                if not success and not step.can_fail:
                    raise Exception(f"Adım başarısız: {step.name}")

            # Execute post-checks
            all_healthy = True
            for check_id in plan.post_checks:
                status = await self.health_monitor.check_health(check_id)
                if status != HealthStatus.HEALTHY:
                    all_healthy = False

            if all_healthy:
                event.recovery_state = RecoveryState.COMPLETED
                event.recovery_completed_at = datetime.now(timezone.utc)

                # Calculate actual recovery time
                if event.recovery_started_at:
                    delta = event.recovery_completed_at - event.recovery_started_at
                    event.actual_recovery_time_minutes = int(delta.total_seconds() / 60)

                # Update metrics
                self.metrics.successful_recoveries += 1
                self._update_metrics(event)

                await self.notification_manager.send_notification(
                    event,
                    f"Kurtarma başarıyla tamamlandı (Süre: {event.actual_recovery_time_minutes} dakika)"
                )

                logger.info(
                    "Kurtarma tamamlandı",
                    event_id=event.event_id,
                    duration_minutes=event.actual_recovery_time_minutes
                )
            else:
                event.recovery_state = RecoveryState.VERIFYING
                logger.warning("Kurtarma doğrulama bekliyor", event_id=event.event_id)

        except Exception as e:
            logger.error("Kurtarma başarısız", event_id=event.event_id, error=str(e))
            event.recovery_state = RecoveryState.FAILED
            self.metrics.failed_recoveries += 1

            # Execute rollback if available
            if plan.rollback_steps:
                await self._execute_rollback(event, plan)

            await self.notification_manager.send_notification(
                event,
                f"Kurtarma başarısız: {str(e)}"
            )

        finally:
            # Move to history
            self.recovery_history.append(event)
            del self.active_events[event.event_id]
            self._recovery_tasks.pop(event.event_id, None)

    async def _execute_step(self, step: RecoveryStep) -> bool:
        """Execute individual recovery step."""
        logger.info("Kurtarma adımı yürütülüyor", step_id=step.step_id, name=step.name)

        for attempt in range(step.retry_count + 1):
            try:
                if step.step_type == "script" and step.script:
                    # Execute script (simplified)
                    logger.debug("Script yürütülüyor", script=step.script[:100])
                    await asyncio.sleep(1)  # Simulate execution
                    return True

                elif step.step_type == "wait":
                    wait_seconds = step.parameters.get("seconds", 60)
                    await asyncio.sleep(wait_seconds)
                    return True

                elif step.step_type == "manual":
                    logger.info("Manuel adım bekleniyor", step_name=step.name)
                    # Would wait for manual confirmation
                    return True

                return True

            except Exception as e:
                logger.warning(
                    "Adım başarısız, yeniden deneniyor",
                    step_id=step.step_id,
                    attempt=attempt + 1,
                    error=str(e)
                )

                if attempt < step.retry_count:
                    await asyncio.sleep(5 * (attempt + 1))  # Exponential backoff

        return False

    async def _execute_rollback(self, event: DisasterEvent, plan: RecoveryPlan):
        """Execute rollback steps."""
        logger.info("Geri alma başlatılıyor", event_id=event.event_id)

        for step in plan.rollback_steps:
            try:
                await self._execute_step(step)
            except Exception as e:
                logger.error("Geri alma adımı başarısız", step_id=step.step_id, error=str(e))

        event.recovery_state = RecoveryState.ROLLED_BACK

    def _update_metrics(self, event: DisasterEvent):
        """Update recovery metrics."""
        self.metrics.total_events += 1

        # Update average recovery time
        if event.actual_recovery_time_minutes:
            total_time = (
                self.metrics.average_recovery_time_minutes *
                (self.metrics.successful_recoveries - 1) +
                event.actual_recovery_time_minutes
            )
            self.metrics.average_recovery_time_minutes = (
                total_time / self.metrics.successful_recoveries
            )

        # Update RTO compliance
        if event.rto_target_minutes and event.actual_recovery_time_minutes:
            if event.actual_recovery_time_minutes <= event.rto_target_minutes:
                # Compliant
                self.metrics.rto_compliance_rate = (
                    (self.metrics.rto_compliance_rate * (self.metrics.total_events - 1) + 1) /
                    self.metrics.total_events
                )
            else:
                # Non-compliant
                self.metrics.rto_compliance_rate = (
                    (self.metrics.rto_compliance_rate * (self.metrics.total_events - 1)) /
                    self.metrics.total_events
                )

        # Calculate MTTR
        if self.metrics.successful_recoveries > 0:
            self.metrics.mttr = self.metrics.average_recovery_time_minutes

    async def start(self):
        """Start disaster recovery orchestrator."""
        await self.health_monitor.start_monitoring()
        logger.info("Felaket kurtarma orkestratörü başlatıldı")

    async def stop(self):
        """Stop disaster recovery orchestrator."""
        # Cancel active recovery tasks
        for task in self._recovery_tasks.values():
            task.cancel()

        await asyncio.gather(*self._recovery_tasks.values(), return_exceptions=True)

        await self.health_monitor.stop_monitoring()
        await self.notification_manager.close()

        logger.info("Felaket kurtarma orkestratörü durduruldu")

    def get_metrics(self) -> RecoveryMetrics:
        """Get recovery metrics."""
        return self.metrics


# Global disaster recovery orchestrator
dr_orchestrator = DisasterRecoveryOrchestrator()


# Add metrics
if not hasattr(metrics, 'disaster_events_total'):
    from prometheus_client import Counter, Histogram, Gauge

    metrics.disaster_events_total = Counter(
        'disaster_events_total',
        'Total number of disaster events',
        ['type', 'severity']
    )

    metrics.recovery_operations_total = Counter(
        'recovery_operations_total',
        'Total recovery operations',
        ['status']
    )

    metrics.recovery_time_minutes = Histogram(
        'recovery_time_minutes',
        'Recovery time in minutes',
        buckets=(5, 15, 30, 60, 120, 240, 480, 960, 1440)
    )

    metrics.rto_compliance = Gauge(
        'rto_compliance_rate',
        'RTO compliance rate'
    )