"""
License notification scheduler tasks for Task 4.8.
Ultra-enterprise Celery Beat scheduler for D-7/3/1 license expiry notifications.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, List

from celery import current_task
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..core.database import get_db_session
from ..models.license import License
from ..models.notification_delivery import NotificationDelivery
from ..models.notification_template import NotificationTemplate
from ..models.user import User
from ..models.enums import (
    NotificationChannel,
    NotificationProvider,
    NotificationStatus,
    NotificationTemplateType,
)
from ..services.template_service import TemplateService
from .worker import celery_app

# Configure logging
logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="scan_licenses_for_notifications",
    queue="cpu",
    max_retries=3,
    default_retry_delay=300,  # 5 minutes
)
def scan_licenses(self) -> Dict:
    """
    Task 4.8: Daily scan at 02:00 UTC for D-7/3/1 license notifications.

    Scans active licenses that expire in 7, 3, or 1 days and enqueues
    email/SMS notifications with idempotent duplicate prevention.

    Returns:
        Dict with scan results and metrics
    """
    task_id = self.request.id
    logger.info(f"[TASK-4.8] Starting license notification scan - Task ID: {task_id}")

    scan_metrics = {
        "task_id": task_id,
        "scan_time": datetime.now(timezone.utc).isoformat(),
        "days_out_counts": {7: 0, 3: 0, 1: 0},
        "notifications_queued": {7: 0, 3: 0, 1: 0},
        "duplicates_skipped": {7: 0, 3: 0, 1: 0},
        "total_processed": 0,
        "errors": [],
    }

    try:
        with get_db_session() as db:
            # Query active licenses expiring in 7, 3, or 1 days
            for days_out in [7, 3, 1]:
                try:
                    licenses = _get_licenses_expiring_in_days(db, days_out)
                    scan_metrics["days_out_counts"][days_out] = len(licenses)

                    logger.info(
                        f"[TASK-4.8] Found {len(licenses)} licenses expiring in {days_out} days"
                    )

                    for license_obj in licenses:
                        try:
                            # Process license for email and SMS notifications
                            email_queued = _enqueue_license_notification(
                                db, license_obj, days_out, NotificationChannel.EMAIL
                            )
                            sms_queued = _enqueue_license_notification(
                                db, license_obj, days_out, NotificationChannel.SMS
                            )

                            if email_queued:
                                scan_metrics["notifications_queued"][days_out] += 1
                            else:
                                scan_metrics["duplicates_skipped"][days_out] += 1

                            if sms_queued:
                                scan_metrics["notifications_queued"][days_out] += 1
                            else:
                                scan_metrics["duplicates_skipped"][days_out] += 1

                            scan_metrics["total_processed"] += 1

                        except Exception as e:
                            error_msg = f"License {license_obj.id} processing failed: {str(e)}"
                            logger.error(f"[TASK-4.8] {error_msg}")
                            scan_metrics["errors"].append(
                                {
                                    "license_id": license_obj.id,
                                    "days_out": days_out,
                                    "error": error_msg,
                                }
                            )

                except Exception as e:
                    error_msg = f"Days-out {days_out} scan failed: {str(e)}"
                    logger.error(f"[TASK-4.8] {error_msg}")
                    scan_metrics["errors"].append({"days_out": days_out, "error": error_msg})

            # Commit all changes at the end
            db.commit()

    except Exception as e:
        logger.error(f"[TASK-4.8] License scan failed: {str(e)}")
        scan_metrics["errors"].append({"global_error": str(e)})
        raise self.retry(exc=e, countdown=self.default_retry_delay)

    # Log final metrics
    total_queued = sum(scan_metrics["notifications_queued"].values())
    total_skipped = sum(scan_metrics["duplicates_skipped"].values())

    logger.info(
        f"[TASK-4.8] Scan completed - "
        f"Processed: {scan_metrics['total_processed']}, "
        f"Queued: {total_queued}, "
        f"Skipped: {total_skipped}, "
        f"Errors: {len(scan_metrics['errors'])}"
    )

    # Log detailed metrics for each days_out
    for days_out in [7, 3, 1]:
        logger.info(
            f"[TASK-4.8] D-{days_out}: "
            f"Licenses: {scan_metrics['days_out_counts'][days_out]}, "
            f"Queued: {scan_metrics['notifications_queued'][days_out]}, "
            f"Skipped: {scan_metrics['duplicates_skipped'][days_out]}"
        )

    return scan_metrics


def _get_licenses_expiring_in_days(db: Session, days_out: int) -> List[License]:
    """
    Query active licenses that expire in exactly N days.

    Uses DATE_TRUNC for index-optimized queries and eager loading to prevent N+1.

    Args:
        db: Database session
        days_out: Number of days (7, 3, or 1)

    Returns:
        List of License objects with user relationships loaded
    """
    # Calculate the date range for licenses expiring in exactly N days
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    target_date = today + timedelta(days=days_out)
    next_date = target_date + timedelta(days=1)

    # Use ORM query with eager loading to prevent N+1 queries
    licenses = (
        db.query(License)
        .options(
            joinedload(License.user)  # Eager load user relationship
        )
        .join(User)
        .filter(
            License.status == "active", License.ends_at >= target_date, License.ends_at < next_date
        )
        .order_by(License.ends_at.asc())
        .all()
    )

    return licenses


def _enqueue_license_notification(
    db: Session, license_obj: License, days_out: int, channel: NotificationChannel
) -> bool:
    """
    Enqueue a single license notification with idempotency.

    Uses ON CONFLICT DO NOTHING for duplicate prevention per Task 4.8 requirements.

    Args:
        db: Database session
        license_obj: License object
        days_out: Days until expiration
        channel: Email or SMS

    Returns:
        True if notification was queued, False if duplicate was skipped
    """
    user = license_obj.user

    # Skip if user doesn't have contact info for this channel
    if channel == NotificationChannel.EMAIL and not user.email:
        logger.warning(f"[TASK-4.8] User {user.id} has no email for license {license_obj.id}")
        return False

    if channel == NotificationChannel.SMS and not user.phone:
        logger.warning(f"[TASK-4.8] User {user.id} has no phone for license {license_obj.id}")
        return False

    # Get notification template
    # Map days_out to template type using dictionary for DRY principle
    template_type_map = {
        7: NotificationTemplateType.LICENSE_REMINDER_D7,
        3: NotificationTemplateType.LICENSE_REMINDER_D3,
        1: NotificationTemplateType.LICENSE_REMINDER_D1,
    }
    template_type = template_type_map.get(days_out)
    if not template_type:
        logger.error(f"[TASK-4.8] Invalid days_out value: {days_out}")
        return False

    template = (
        db.query(NotificationTemplate)
        .filter(
            NotificationTemplate.type == template_type,
            NotificationTemplate.channel == channel,
            NotificationTemplate.is_active == True,
        )
        .first()
    )

    if not template:
        logger.error(f"[TASK-4.8] No template found for type={template_type}, channel={channel}")
        return False

    # Prepare template variables
    variables = {
        "user_name": user.full_name or user.email,
        "user_email": user.email,
        "license_type": license_obj.type,
        "days_remaining": days_out,
        "ends_at": license_obj.ends_at.strftime("%d.%m.%Y %H:%M"),
        "ends_at_date": license_obj.ends_at.strftime("%d.%m.%Y"),
        "renewal_link": f"{settings.frontend_url}/license/renew/{license_obj.id}",
        "support_email": settings.support_email or "destek@example.com",
        "company_name": "FreeCAD Production Platform",
    }

    # Render template content
    try:
        template_service = TemplateService(db)
        rendered_content = template_service.render_template(template=template, variables=variables)
    except Exception as e:
        logger.error(f"[TASK-4.8] Template rendering failed for {template_type}: {str(e)}")
        return False

    # Determine recipient and provider
    recipient = user.email if channel == NotificationChannel.EMAIL else user.phone
    primary_provider = (
        NotificationProvider.POSTMARK
        if channel == NotificationChannel.EMAIL
        else NotificationProvider.TWILIO
    )

    # Create notification with duplicate prevention
    try:
        # Use raw SQL with ON CONFLICT DO NOTHING for idempotency
        insert_sql = text("""
            INSERT INTO notifications_delivery (
                user_id, license_id, template_id, channel, recipient, days_out,
                subject, body, variables, status, priority, primary_provider,
                created_at, updated_at
            ) VALUES (
                :user_id, :license_id, :template_id, :channel, :recipient, :days_out,
                :subject, :body, :variables, :status, :priority, :primary_provider,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            ON CONFLICT (license_id, days_out, channel) 
            DO NOTHING
            RETURNING id
        """)

        result = db.execute(
            insert_sql,
            {
                "user_id": user.id,
                "license_id": license_obj.id,
                "template_id": template.id,
                "channel": channel.value,
                "recipient": recipient,
                "days_out": days_out,
                "subject": rendered_content.get("subject"),
                "body": rendered_content["body"],
                "variables": variables,
                "status": NotificationStatus.QUEUED.value,
                "priority": "high" if days_out == 1 else "normal",
                "primary_provider": primary_provider.value,
            },
        )

        # Check if row was inserted (not a duplicate)
        inserted_row = result.fetchone()
        if inserted_row:
            notification_id = inserted_row[0]
            logger.info(
                f"[TASK-4.8] Queued {channel.value} notification {notification_id} "
                f"for license {license_obj.id} (D-{days_out})"
            )

            # Enqueue the actual send task
            send_email_sms.delay(notification_id)
            return True
        else:
            logger.debug(
                f"[TASK-4.8] Skipped duplicate {channel.value} notification "
                f"for license {license_obj.id} (D-{days_out})"
            )
            return False

    except IntegrityError as e:
        # Handle race conditions gracefully
        logger.debug(f"[TASK-4.8] Duplicate notification skipped due to race condition: {str(e)}")
        db.rollback()
        return False
    except Exception as e:
        logger.error(f"[TASK-4.8] Failed to create notification: {str(e)}")
        db.rollback()
        raise


@celery_app.task(
    bind=True,
    name="send_email_sms",
    queue="cpu",
    max_retries=3,
    default_retry_delay=60,  # 1 minute
)
def send_email_sms(self, notification_id: int) -> Dict:
    """
    Task 4.8: Send email/SMS notification with provider fallback.

    This task is enqueued by scan_licenses() for each notification that needs to be sent.

    Args:
        notification_id: NotificationDelivery ID to process

    Returns:
        Dict with send results
    """
    task_id = self.request.id
    logger.info(f"[TASK-4.8] Processing notification {notification_id} - Task ID: {task_id}")

    send_metrics = {
        "task_id": task_id,
        "notification_id": notification_id,
        "send_time": datetime.now(timezone.utc).isoformat(),
        "status": "unknown",
        "provider_used": None,
        "error": None,
    }

    try:
        with get_db_session() as db:
            # Get notification
            notification = db.get(NotificationDelivery, notification_id)
            if not notification:
                error_msg = f"Notification {notification_id} not found"
                logger.error(f"[TASK-4.8] {error_msg}")
                send_metrics["error"] = error_msg
                return send_metrics

            # Skip if already sent
            if notification.status != NotificationStatus.QUEUED:
                logger.info(
                    f"[TASK-4.8] Notification {notification_id} already processed "
                    f"(status: {notification.status.value})"
                )
                send_metrics["status"] = notification.status.value
                return send_metrics

            # Import notification service here to avoid circular imports
            from ..services.notification_service import NotificationService

            # Send notification
            notification_service = NotificationService(db)
            success = notification_service.send_notification(notification)

            if success:
                send_metrics["status"] = "sent"
                send_metrics["provider_used"] = (
                    notification.actual_provider.value if notification.actual_provider else None
                )
                logger.info(
                    f"[TASK-4.8] Successfully sent notification {notification_id} "
                    f"via {send_metrics['provider_used']}"
                )
            else:
                send_metrics["status"] = "failed"
                send_metrics["error"] = notification.error_message
                logger.error(
                    f"[TASK-4.8] Failed to send notification {notification_id}: "
                    f"{notification.error_message}"
                )

                # Retry if possible
                if notification.can_retry:
                    raise self.retry(exc=Exception(notification.error_message))

            db.commit()

    except Exception as e:
        error_msg = str(e)
        logger.error(f"[TASK-4.8] Send task failed: {error_msg}")
        send_metrics["error"] = error_msg
        send_metrics["status"] = "error"

        # Retry with exponential backoff
        raise self.retry(
            exc=e, countdown=min(self.default_retry_delay * (2**self.request.retries), 1800)
        )

    return send_metrics


# Task routing configuration for license notification tasks
celery_app.conf.task_routes.update(
    {
        "scan_licenses_for_notifications": {
            "queue": "cpu",
            "priority": settings.queue_priority_normal,
            "routing_key": "cpu",
        },
        "send_email_sms": {
            "queue": "cpu",
            "priority": settings.queue_priority_high,
            "routing_key": "cpu",
        },
    }
)
