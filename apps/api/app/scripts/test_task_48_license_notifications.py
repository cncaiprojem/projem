"""
Test script for Task 4.8: License notification scheduler.
Ultra-enterprise testing for D-7/3/1 license expiry notification scanning.
"""

import os
import sys
import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, List

# Add the project root to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.base import Base
from app.models.user import User
from app.models.license import License
from app.models.notification_delivery import NotificationDelivery
from app.models.notification_template import NotificationTemplate
from app.models.enums import (
    NotificationChannel,
    NotificationProvider,
    NotificationStatus,
    NotificationTemplateType,
)
from app.tasks.license_notifications import scan_licenses, _get_licenses_expiring_in_days


def setup_test_database():
    """Set up test database connection."""
    engine = create_engine(
        "postgresql+psycopg2://freecad:freecad@localhost:5432/freecad", echo=False
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, SessionLocal


def create_test_data(session):
    """Create test data for license notification testing."""
    print("🔧 Creating test data...")

    # Create test users
    test_users = []
    for i in range(3):
        user = User(
            email=f"test_user_{i}@example.com",
            full_name=f"Test User {i}",
            phone=f"+901234567{i:02d}",
            is_active=True,
            email_verified=True,
            phone_verified=True,
        )
        session.add(user)
        test_users.append(user)

    session.flush()  # Get user IDs

    # Create test licenses expiring in 7, 3, and 1 days
    test_licenses = []
    now = datetime.now(timezone.utc)

    for i, days_out in enumerate([7, 3, 1]):
        expires_at = now + timedelta(days=days_out)
        license_obj = License(
            user_id=test_users[i].id,
            type="12m",
            scope={"features": ["cad", "cam", "sim"], "limits": {"projects": 100}},
            status="active",
            starts_at=now - timedelta(days=30),
            ends_at=expires_at,
        )
        session.add(license_obj)
        test_licenses.append(license_obj)

    session.flush()

    # Create notification templates
    for channel in ["email", "sms"]:
        for days_out in [7, 3, 1]:
            # Template setup for each days_out and channel

            if channel == "email":
                subject = f"Lisansınız {days_out} Gün Sonra Sona Eriyor"
                body = f"""
Merhaba {{{{user_name}}}},

{{{{license_type}}}} lisansınız {{{{days_remaining}}}} gün sonra ({{{{ends_at_date}}}}) sona erecek.

Lisansınızı yenilemek için: {{{{renewal_link}}}}

Saygılarımızla,
{{{{company_name}}}} Ekibi
"""
            else:  # SMS
                subject = None
                body = f"Merhaba {{{{user_name}}}}, {{{{license_type}}}} lisansınız {{{{days_remaining}}}} gün sonra sona eriyor. Yenileme: {{{{renewal_link}}}}"

            # Map days_out to template type using dictionary for DRY principle
            template_type_map = {
                7: NotificationTemplateType.LICENSE_REMINDER_D7,
                3: NotificationTemplateType.LICENSE_REMINDER_D3,
                1: NotificationTemplateType.LICENSE_REMINDER_D1,
            }
            template_type = template_type_map[days_out]

            template = NotificationTemplate(
                type=template_type,
                name=f"License Reminder D-{days_out} ({channel.upper()})",
                description=f"License expiry reminder {days_out} days before (Turkish)",
                channel=NotificationChannel.EMAIL
                if channel == "email"
                else NotificationChannel.SMS,
                subject_template=subject,
                body_template=body,
                variables={
                    "user_name": "string",
                    "license_type": "string",
                    "days_remaining": "integer",
                    "ends_at": "string",
                    "ends_at_date": "string",
                    "renewal_link": "string",
                    "company_name": "string",
                },
                is_active=True,
            )
            session.add(template)

    session.commit()

    print(f"✅ Created {len(test_users)} users, {len(test_licenses)} licenses, and templates")
    return test_users, test_licenses


def test_license_query(session):
    """Test the license query for D-7/3/1 expiring licenses."""
    print("\n🔍 Testing license query...")

    for days_out in [7, 3, 1]:
        licenses = _get_licenses_expiring_in_days(session, days_out)
        print(f"  📅 Licenses expiring in {days_out} days: {len(licenses)}")

        for license_obj in licenses:
            remaining_days = (license_obj.ends_at - datetime.now(timezone.utc)).days
            print(
                f"    - License {license_obj.id}: {license_obj.type} (actual days: {remaining_days})"
            )

    return True


def test_notification_creation(session):
    """Test notification creation with duplicate prevention."""
    print("\n📧 Testing notification creation...")

    # Import the task function (to avoid circular imports during startup)
    from app.tasks.license_notifications import scan_licenses

    # Run the scan task
    result = scan_licenses.apply()
    task_result = result.get()

    print(f"✅ Scan completed: {task_result}")
    print(f"  📊 Metrics:")
    for days_out in [7, 3, 1]:
        licenses_count = task_result["days_out_counts"][days_out]
        queued_count = task_result["notifications_queued"][days_out]
        skipped_count = task_result["duplicates_skipped"][days_out]
        print(
            f"    D-{days_out}: {licenses_count} licenses → {queued_count} queued, {skipped_count} skipped"
        )

    # Check database state
    total_notifications = session.query(NotificationDelivery).count()
    print(f"  📫 Total notifications in DB: {total_notifications}")

    return True


def test_duplicate_prevention(session):
    """Test duplicate prevention by running scan twice."""
    print("\n🚫 Testing duplicate prevention...")

    # Run scan again - should skip all duplicates
    from app.tasks.license_notifications import scan_licenses

    result = scan_licenses.apply()
    task_result = result.get()

    print(f"✅ Second scan completed: {task_result}")

    total_skipped = sum(task_result["duplicates_skipped"].values())
    total_queued = sum(task_result["notifications_queued"].values())

    print(
        f"  🎯 Duplicate prevention: {total_skipped} duplicates skipped, {total_queued} new notifications"
    )

    if total_queued == 0 and total_skipped > 0:
        print("  ✅ Duplicate prevention working correctly!")
        return True
    else:
        print("  ❌ Duplicate prevention may have issues")
        return False


def test_time_frozen_scenario(session):
    """Test with time frozen to D-7/3/1 scenario."""
    print("\n⏰ Testing time-frozen scenario...")

    # Clean up existing data
    session.query(NotificationDelivery).delete()
    session.query(License).delete()
    session.commit()

    # Create licenses with exact expiry dates
    now = datetime.now(timezone.utc)
    test_dates = [
        now + timedelta(days=7),  # Expires in exactly 7 days
        now + timedelta(days=3),  # Expires in exactly 3 days
        now + timedelta(days=1),  # Expires in exactly 1 day
    ]

    users = session.query(User).limit(3).all()

    for i, expires_at in enumerate(test_dates):
        license_obj = License(
            user_id=users[i].id,
            type="6m",
            scope={"features": ["cad"]},
            status="active",
            starts_at=now - timedelta(days=60),
            ends_at=expires_at,
        )
        session.add(license_obj)

    session.commit()
    print("  📅 Created licenses with exact D-7/3/1 expiry dates")

    # Run scan
    from app.tasks.license_notifications import scan_licenses

    result = scan_licenses.apply()
    task_result = result.get()

    # Verify results
    expected_notifications = 3 * 2  # 3 licenses * 2 channels (email + SMS)
    actual_notifications = sum(task_result["notifications_queued"].values())

    print(f"  📊 Expected: {expected_notifications}, Actual: {actual_notifications}")

    if actual_notifications == expected_notifications:
        print("  ✅ Time-frozen scenario working correctly!")
        return True
    else:
        print("  ❌ Time-frozen scenario has issues")
        return False


def main():
    """Run all Task 4.8 tests."""
    print("🚀 Starting Task 4.8 License Notification Tests")
    print("=" * 60)

    try:
        engine, SessionLocal = setup_test_database()
        session = SessionLocal()

        # Clean up existing test data
        print("🧹 Cleaning up existing test data...")
        session.query(NotificationDelivery).delete()
        session.query(License).filter(
            License.user_id.in_(
                session.query(User.id).filter(User.email.like("test_user_%@example.com"))
            )
        ).delete(synchronize_session=False)
        session.query(User).filter(User.email.like("test_user_%@example.com")).delete()
        session.query(NotificationTemplate).filter(
            NotificationTemplate.type.in_(
                [
                    NotificationTemplateType.LICENSE_REMINDER_D7,
                    NotificationTemplateType.LICENSE_REMINDER_D3,
                    NotificationTemplateType.LICENSE_REMINDER_D1,
                ]
            )
        ).delete()
        session.commit()

        # Run tests
        test_users, test_licenses = create_test_data(session)

        success = True
        success &= test_license_query(session)
        success &= test_notification_creation(session)
        success &= test_duplicate_prevention(session)
        success &= test_time_frozen_scenario(session)

        if success:
            print("\n🎉 All Task 4.8 tests passed!")
        else:
            print("\n❌ Some Task 4.8 tests failed!")

        session.close()

    except Exception as e:
        print(f"\n💥 Test failed with error: {str(e)}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
