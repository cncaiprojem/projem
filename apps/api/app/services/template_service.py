"""
Template service for Task 4.7 - Notification template management and rendering.
Ultra-enterprise template system with caching, versioning, and Turkish localization.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from sqlalchemy.orm import Session

from ..models.notification_template import NotificationTemplate
from ..models.enums import NotificationChannel, NotificationTemplateType
from ..core.database import get_db

# SMS Configuration Constants
SMS_MAX_LENGTH = 160


class TemplateService:
    """Service for managing and rendering notification templates.

    Task 4.7 Implementation:
    - Template selection based on type and channel
    - Variable rendering with validation
    - Turkish localization support
    - Template caching for performance
    - Version management and fallbacks
    """

    def __init__(self, db: Session):
        """Initialize template service.

        Args:
            db: Database session
        """
        self.db = db
        self._template_cache: Dict[str, NotificationTemplate] = {}

    def get_template(
        self,
        template_type: NotificationTemplateType,
        channel: NotificationChannel,
        language: str = "tr-TR",
    ) -> Optional[NotificationTemplate]:
        """Get active template for type, channel, and language.

        Args:
            template_type: Template type
            channel: Notification channel
            language: Language code

        Returns:
            Active template or None if not found
        """
        # Check cache first
        cache_key = f"{template_type.value}:{channel.value}:{language}"
        if cache_key in self._template_cache:
            template = self._template_cache[cache_key]
            if template.is_active:
                return template
            else:
                # Remove inactive template from cache
                del self._template_cache[cache_key]

        # Query database
        template = (
            self.db.query(NotificationTemplate)
            .filter(
                NotificationTemplate.type == template_type,
                NotificationTemplate.channel == channel,
                NotificationTemplate.language == language,
                NotificationTemplate.is_active == True,
            )
            .first()
        )

        # Try fallback to English if Turkish not found
        if not template and language != "en-US":
            template = (
                self.db.query(NotificationTemplate)
                .filter(
                    NotificationTemplate.type == template_type,
                    NotificationTemplate.channel == channel,
                    NotificationTemplate.language == "en-US",
                    NotificationTemplate.is_active == True,
                )
                .first()
            )

        # Cache the template
        if template:
            self._template_cache[cache_key] = template

        return template

    def render_template(
        self, template: NotificationTemplate, variables: Dict[str, Any]
    ) -> Dict[str, Optional[str]]:
        """Render template with variables.

        Args:
            template: Template to render
            variables: Template variables

        Returns:
            Dictionary with rendered content: subject, body, plain_text

        Raises:
            ValueError: If required variables are missing or rendering fails
        """
        # Validate variables
        is_valid, missing = template.validate_variables(variables)
        if not is_valid:
            raise ValueError(f"Missing required variables: {', '.join(missing)}")

        # Render all components
        return template.render_all(variables)

    def get_license_reminder_template(
        self, days_out: int, channel: NotificationChannel, language: str = "tr-TR"
    ) -> Optional[NotificationTemplate]:
        """Get license reminder template based on days remaining.

        Args:
            days_out: Days until license expiration
            channel: Notification channel
            language: Language code

        Returns:
            Appropriate reminder template
        """
        # Map days to template types
        if days_out >= 7:
            template_type = NotificationTemplateType.LICENSE_REMINDER_D7
        elif days_out >= 3:
            template_type = NotificationTemplateType.LICENSE_REMINDER_D3
        elif days_out >= 1:
            template_type = NotificationTemplateType.LICENSE_REMINDER_D1
        else:
            template_type = NotificationTemplateType.LICENSE_EXPIRED

        return self.get_template(template_type, channel, language)

    def create_license_reminder_variables(
        self, user_name: str, days_remaining: int, ends_at: datetime, renewal_link: str
    ) -> Dict[str, Any]:
        """Create variables for license reminder templates.

        Args:
            user_name: User's name
            days_remaining: Days until expiration
            ends_at: License expiration timestamp
            renewal_link: URL for license renewal

        Returns:
            Template variables dictionary
        """
        # Format date for Turkish locale
        ends_at_formatted = ends_at.strftime("%d.%m.%Y %H:%M")

        return {
            "user_name": user_name,
            "days_remaining": days_remaining,
            "ends_at": ends_at_formatted,
            "renewal_link": renewal_link,
        }

    def render_license_reminder(
        self,
        user_name: str,
        days_remaining: int,
        ends_at: datetime,
        renewal_link: str,
        channel: NotificationChannel,
        language: str = "tr-TR",
    ) -> Optional[Dict[str, Optional[str]]]:
        """Render license reminder notification.

        Args:
            user_name: User's name
            days_remaining: Days until expiration
            ends_at: License expiration timestamp
            renewal_link: URL for license renewal
            channel: Notification channel
            language: Language code

        Returns:
            Rendered content or None if template not found
        """
        # Get appropriate template
        template = self.get_license_reminder_template(days_remaining, channel, language)
        if not template:
            return None

        # Create variables
        variables = self.create_license_reminder_variables(
            user_name, days_remaining, ends_at, renewal_link
        )

        # Render template
        try:
            return self.render_template(template, variables)
        except ValueError as e:
            # Log error and return None
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Failed to render license reminder template: {e}")
            return None

    def list_templates(
        self,
        template_type: Optional[NotificationTemplateType] = None,
        channel: Optional[NotificationChannel] = None,
        language: Optional[str] = None,
        active_only: bool = True,
    ) -> List[NotificationTemplate]:
        """List notification templates with optional filters.

        Args:
            template_type: Filter by template type
            channel: Filter by channel
            language: Filter by language
            active_only: Show only active templates

        Returns:
            List of matching templates
        """
        query = self.db.query(NotificationTemplate)

        if template_type:
            query = query.filter(NotificationTemplate.type == template_type)

        if channel:
            query = query.filter(NotificationTemplate.channel == channel)

        if language:
            query = query.filter(NotificationTemplate.language == language)

        if active_only:
            query = query.filter(NotificationTemplate.is_active == True)

        return query.order_by(
            NotificationTemplate.type,
            NotificationTemplate.channel,
            NotificationTemplate.language,
            NotificationTemplate.version.desc(),
        ).all()

    def create_template(
        self,
        template_type: NotificationTemplateType,
        channel: NotificationChannel,
        name: str,
        body_template: str,
        subject_template: Optional[str] = None,
        plain_text_template: Optional[str] = None,
        variables: Optional[Dict[str, str]] = None,
        language: str = "tr-TR",
        description: Optional[str] = None,
        max_length: Optional[int] = None,
    ) -> NotificationTemplate:
        """Create a new notification template.

        Args:
            template_type: Template type
            channel: Notification channel
            name: Template name
            body_template: Body template text
            subject_template: Subject template (email only)
            plain_text_template: Plain text version (email only)
            variables: Required variables schema
            language: Language code
            description: Template description
            max_length: Maximum length (SMS only)

        Returns:
            Created template instance

        Raises:
            ValueError: If template data is invalid
        """
        # Validation
        if channel == NotificationChannel.SMS:
            if subject_template is not None:
                raise ValueError("SMS templates cannot have subjects")
            if max_length != SMS_MAX_LENGTH:
                max_length = SMS_MAX_LENGTH

        if channel == NotificationChannel.EMAIL:
            if subject_template is None:
                raise ValueError("Email templates must have subjects")

        # Deactivate existing template if any
        existing = self.get_template(template_type, channel, language)
        if existing:
            existing.deactivate()
            self.db.flush()

        # Create new template
        template = NotificationTemplate(
            type=template_type,
            channel=channel,
            language=language,
            name=name,
            description=description,
            subject_template=subject_template,
            body_template=body_template,
            plain_text_template=plain_text_template,
            variables=variables or {},
            max_length=max_length,
            version=1,
            is_active=True,
        )

        self.db.add(template)
        self.db.flush()

        # Clear cache for this template type
        cache_key = f"{template_type.value}:{channel.value}:{language}"
        if cache_key in self._template_cache:
            del self._template_cache[cache_key]

        return template

    def update_template(self, template_id: int, **updates) -> NotificationTemplate:
        """Update an existing template.

        Args:
            template_id: Template ID to update
            **updates: Fields to update

        Returns:
            Updated template instance

        Raises:
            ValueError: If template not found or updates are invalid
        """
        template = (
            self.db.query(NotificationTemplate)
            .filter(NotificationTemplate.id == template_id)
            .first()
        )

        if not template:
            raise ValueError(f"Template {template_id} not found")

        # Update fields
        for field, value in updates.items():
            if hasattr(template, field):
                setattr(template, field, value)

        # Increment version if content changed
        content_fields = {"body_template", "subject_template", "plain_text_template", "variables"}
        if any(field in content_fields for field in updates.keys()):
            template.increment_version()

        self.db.flush()

        # Clear cache
        cache_key = f"{template.type.value}:{template.channel.value}:{template.language}"
        if cache_key in self._template_cache:
            del self._template_cache[cache_key]

        return template

    def deactivate_template(self, template_id: int) -> bool:
        """Deactivate a template.

        Args:
            template_id: Template ID to deactivate

        Returns:
            True if deactivated successfully
        """
        template = (
            self.db.query(NotificationTemplate)
            .filter(NotificationTemplate.id == template_id)
            .first()
        )

        if template:
            template.deactivate()
            self.db.flush()

            # Clear cache
            cache_key = f"{template.type.value}:{template.channel.value}:{template.language}"
            if cache_key in self._template_cache:
                del self._template_cache[cache_key]

            return True

        return False

    def clear_cache(self) -> None:
        """Clear template cache."""
        self._template_cache.clear()

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get template cache statistics.

        Returns:
            Cache statistics
        """
        return {
            "cached_templates": len(self._template_cache),
            "cache_keys": list(self._template_cache.keys()),
        }
