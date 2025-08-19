"""
Notification template model for Task 4.7 - Reusable email/SMS templates.
Ultra-enterprise template system with versioning and Turkish localization.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import NotificationChannel, NotificationTemplateType

if TYPE_CHECKING:
    from .notification_delivery import NotificationDelivery


class NotificationTemplate(Base, TimestampMixin):
    """Reusable notification templates for email/SMS with Turkish localization.

    Task 4.7 Implementation:
    - Supports D-7, D-3, D-1 license reminder templates
    - HTML + plain text for emails, SMS optimized for 160 chars
    - Template variables with JSON schema validation
    - Version control and active template management
    - Turkish language support with fallback to English
    """

    __tablename__ = "notification_templates"

    # Primary key
    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment="Unique template identifier"
    )

    # Template classification
    type: Mapped[NotificationTemplateType] = mapped_column(
        nullable=False, index=True, comment="Template type for specific use cases"
    )

    channel: Mapped[NotificationChannel] = mapped_column(
        nullable=False, index=True, comment="Delivery channel: email or SMS"
    )

    # Localization
    language: Mapped[str] = mapped_column(
        String(5), nullable=False, server_default="tr-TR", comment="Language code (tr-TR, en-US)"
    )

    # Template metadata
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="Human-readable template name"
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Template description for administration"
    )

    # Template content
    subject_template: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Email subject template (null for SMS)"
    )

    body_template: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Email HTML or SMS text template"
    )

    plain_text_template: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Email plain text fallback"
    )

    # Template variables and validation
    variables: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default="{}",
        comment="Required template variables as JSON schema",
    )

    max_length: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="Max rendered length (160 for SMS)"
    )

    # Versioning and lifecycle
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1", comment="Template version number"
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="true",
        index=True,
        comment="Whether template is currently active",
    )

    # Relationships
    notifications: Mapped[list["NotificationDelivery"]] = relationship(
        "NotificationDelivery", back_populates="template", lazy="select"
    )

    # Ultra-enterprise constraints and indexes
    __table_args__ = (
        # SMS templates cannot have subjects
        CheckConstraint(
            "(channel = 'sms' AND subject_template IS NULL) OR channel = 'email'",
            name="ck_notification_templates_sms_no_subject",
        ),
        # SMS templates must have exactly 160 char limit
        CheckConstraint(
            "(channel = 'sms' AND max_length = 160) OR (channel = 'email' AND max_length IS NULL)",
            name="ck_notification_templates_sms_max_length",
        ),
        # Name must be meaningful length
        CheckConstraint("length(name) >= 3", name="ck_notification_templates_name_length"),
        # Version must be positive
        CheckConstraint("version >= 1", name="ck_notification_templates_version_positive"),
        # Only one active template per type+channel+language
        Index(
            "uq_notification_templates_active",
            "type",
            "channel",
            "language",
            unique=True,
            postgresql_where="is_active = true",
        ),
        # Performance indexes
        Index("idx_notification_templates_type_channel", "type", "channel"),
        Index("idx_notification_templates_active_lang", "is_active", "language"),
        Index("idx_notification_templates_variables", "variables", postgresql_using="gin"),
    )

    def __repr__(self) -> str:
        return f"<NotificationTemplate(id={self.id}, type={self.type.value}, channel={self.channel.value})>"

    def __str__(self) -> str:
        return f"Template {self.name} ({self.type.value}, {self.channel.value})"

    @property
    def is_email(self) -> bool:
        """Check if this is an email template."""
        return self.channel == NotificationChannel.EMAIL

    @property
    def is_sms(self) -> bool:
        """Check if this is an SMS template."""
        return self.channel == NotificationChannel.SMS

    @property
    def has_subject(self) -> bool:
        """Check if template has a subject (email only)."""
        return self.is_email and self.subject_template is not None

    @property
    def variable_names(self) -> list[str]:
        """Get list of required variable names."""
        if not isinstance(self.variables, dict):
            return []
        return list(self.variables.keys())

    def validate_variables(self, variables: dict) -> tuple[bool, list[str]]:
        """Validate provided variables against template requirements.

        Args:
            variables: Variables to validate

        Returns:
            Tuple of (is_valid, missing_variables)
        """
        required_vars = set(self.variable_names)
        provided_vars = set(variables.keys())
        missing = list(required_vars - provided_vars)
        return len(missing) == 0, missing

    def render_subject(self, variables: dict) -> Optional[str]:
        """Render subject template with variables.

        Args:
            variables: Template variables

        Returns:
            Rendered subject or None for SMS
        """
        if not self.has_subject:
            return None

        try:
            return self.subject_template.format(**variables)
        except KeyError as e:
            raise ValueError(f"Missing variable in subject: {e}")
        except Exception as e:
            raise ValueError(f"Subject rendering error: {e}")

    def render_body(self, variables: dict) -> str:
        """Render body template with variables.

        Args:
            variables: Template variables

        Returns:
            Rendered body text
        """
        try:
            rendered = self.body_template.format(**variables)

            # Check SMS length limit
            if self.is_sms and self.max_length and len(rendered) > self.max_length:
                raise ValueError(f"SMS body exceeds {self.max_length} characters: {len(rendered)}")

            return rendered
        except KeyError as e:
            raise ValueError(f"Missing variable in body: {e}")
        except Exception as e:
            raise ValueError(f"Body rendering error: {e}")

    def render_plain_text(self, variables: dict) -> Optional[str]:
        """Render plain text template with variables.

        Args:
            variables: Template variables

        Returns:
            Rendered plain text or None if not available
        """
        if not self.plain_text_template:
            return None

        try:
            return self.plain_text_template.format(**variables)
        except KeyError as e:
            raise ValueError(f"Missing variable in plain text: {e}")
        except Exception as e:
            raise ValueError(f"Plain text rendering error: {e}")

    def render_all(self, variables: dict) -> dict:
        """Render all template components with variables.

        Args:
            variables: Template variables

        Returns:
            Dictionary with rendered content: subject, body, plain_text
        """
        # Validate variables first
        is_valid, missing = self.validate_variables(variables)
        if not is_valid:
            raise ValueError(f"Missing required variables: {', '.join(missing)}")

        return {
            "subject": self.render_subject(variables),
            "body": self.render_body(variables),
            "plain_text": self.render_plain_text(variables),
        }

    def deactivate(self) -> None:
        """Deactivate this template."""
        self.is_active = False

    def activate(self) -> None:
        """Activate this template."""
        self.is_active = True

    def increment_version(self) -> None:
        """Increment template version."""
        self.version += 1

    @classmethod
    def get_active_template(
        cls,
        db: Session,
        template_type: NotificationTemplateType,
        channel: NotificationChannel,
        language: str = "tr-TR",
    ) -> Optional["NotificationTemplate"]:
        """Get active template for type, channel, and language.

        Args:
            db: Database session (passed as parameter for proper session management)
            template_type: Template type to find
            channel: Delivery channel
            language: Language code (defaults to Turkish)

        Returns:
            Active template or None if not found
        """
        from sqlalchemy.orm import Session

        return (
            db.query(cls)
            .filter(
                cls.type == template_type,
                cls.channel == channel,
                cls.language == language,
                cls.is_active == True,
            )
            .first()
        )

    @classmethod
    def create_license_reminder_templates(cls, db_session) -> list["NotificationTemplate"]:
        """Create default license reminder templates.

        Args:
            db_session: Database session

        Returns:
            List of created templates
        """
        templates = []

        # D-7 Email Template
        templates.append(
            cls(
                type=NotificationTemplateType.LICENSE_REMINDER_D7,
                channel=NotificationChannel.EMAIL,
                language="tr-TR",
                name="Lisans Süresi 7 Gün Kaldı",
                subject_template="FreeCAD Lisansınız 7 Gün İçinde Sona Eriyor",
                body_template="""
<html>
<body>
    <h2>Merhaba {user_name},</h2>
    <p><strong>FreeCAD lisansınızın süresi {days_remaining} gün sonra sona erecek.</strong></p>
    <p>Lisans bitiş tarihi: <strong>{ends_at}</strong></p>
    <p>Kesintisiz hizmet almaya devam etmek için lütfen lisansınızı yenileyin:</p>
    <p><a href="{renewal_link}" style="background-color: #007cba; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Lisansı Yenile</a></p>
    <p>Sorularınız için destek ekibimizle iletişime geçebilirsiniz.</p>
    <p>FreeCAD Ekibi</p>
</body>
</html>""",
                plain_text_template="""Merhaba {user_name},

FreeCAD lisansınızın süresi {days_remaining} gün sonra sona erecek.
Lisans bitiş tarihi: {ends_at}

Kesintisiz hizmet almaya devam etmek için lütfen lisansınızı yenileyin:
{renewal_link}

Sorularınız için destek ekibimizle iletişime geçebilirsiniz.

FreeCAD Ekibi""",
                variables={
                    "user_name": "string",
                    "days_remaining": "integer",
                    "ends_at": "datetime",
                    "renewal_link": "string",
                },
            )
        )

        # Add all templates to session
        for template in templates:
            db_session.add(template)

        return templates
