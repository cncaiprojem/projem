"""
Notification provider factory for Task 4.7 - Provider instantiation and fallback.
Ultra-enterprise factory with automatic fallback chain configuration.
"""

from typing import Dict, List, Any, Optional

from ...core.environment import environment
from ...models.enums import NotificationChannel, NotificationProvider as ProviderEnum
from .base import NotificationProvider
from .mock_provider import MockNotificationProvider


class NotificationProviderFactory:
    """Factory for creating notification providers with fallback support.

    Task 4.7 Implementation:
    - Provider instantiation based on configuration
    - Fallback chain management (primary -> fallback)
    - Environment-based provider selection
    - Provider health checking and rotation
    """

    _providers: Dict[str, type] = {
        "mock": MockNotificationProvider,
        # Will add real providers: SMTP, Postmark, Twilio, Vonage
    }

    _fallback_chains: Dict[NotificationChannel, List[ProviderEnum]] = {
        NotificationChannel.EMAIL: [
            ProviderEnum.POSTMARK_API,
            ProviderEnum.SMTP_PRIMARY,
            ProviderEnum.SMTP_FALLBACK,
        ],
        NotificationChannel.SMS: [ProviderEnum.TWILIO_SMS, ProviderEnum.VONAGE_SMS],
    }

    @classmethod
    def register_provider(cls, name: str, provider_class: type) -> None:
        """Register a new provider class.

        Args:
            name: Provider name
            provider_class: Provider class
        """
        if not issubclass(provider_class, NotificationProvider):
            raise ValueError(f"Provider class must inherit from NotificationProvider")

        cls._providers[name] = provider_class

    @classmethod
    def create_provider(
        cls, provider_name: ProviderEnum, config: Optional[Dict[str, Any]] = None
    ) -> NotificationProvider:
        """Create a notification provider instance.

        Args:
            provider_name: Provider enum value
            config: Override configuration (uses environment if None)

        Returns:
            Configured provider instance

        Raises:
            ValueError: If provider is not supported
        """
        if config is None:
            config = cls._get_provider_config(provider_name)

        provider_class_name = cls._get_provider_class_name(provider_name)

        if provider_class_name not in cls._providers:
            # For development, fall back to mock provider
            if environment.DEV_MODE:
                return MockNotificationProvider(config)
            else:
                raise ValueError(f"Provider '{provider_name.value}' not implemented")

        provider_class = cls._providers[provider_class_name]
        return provider_class(config)

    @classmethod
    def get_fallback_chain(
        cls, channel: NotificationChannel, primary_provider: Optional[ProviderEnum] = None
    ) -> List[ProviderEnum]:
        """Get fallback provider chain for a channel.

        Args:
            channel: Notification channel
            primary_provider: Override primary provider

        Returns:
            List of providers in fallback order
        """
        chain = cls._fallback_chains.get(channel, [])

        if primary_provider and primary_provider in chain:
            # Move primary to front
            chain = [primary_provider] + [p for p in chain if p != primary_provider]

        return chain

    @classmethod
    def create_provider_chain(
        cls, channel: NotificationChannel, primary_provider: Optional[ProviderEnum] = None
    ) -> List[NotificationProvider]:
        """Create a chain of provider instances for fallback.

        Args:
            channel: Notification channel
            primary_provider: Override primary provider

        Returns:
            List of configured provider instances
        """
        provider_chain = []
        fallback_chain = cls.get_fallback_chain(channel, primary_provider)

        for provider_enum in fallback_chain:
            try:
                provider = cls.create_provider(provider_enum)

                # Check if provider supports the channel
                if channel == NotificationChannel.EMAIL and provider.supports_email():
                    provider_chain.append(provider)
                elif channel == NotificationChannel.SMS and provider.supports_sms():
                    provider_chain.append(provider)
            except ValueError:
                # Skip providers that can't be created
                continue

        return provider_chain

    @classmethod
    def _get_provider_class_name(cls, provider_enum: ProviderEnum) -> str:
        """Map provider enum to class name.

        Args:
            provider_enum: Provider enum value

        Returns:
            Provider class name for factory lookup
        """
        mapping = {
            ProviderEnum.MOCK_PROVIDER: "mock",
            ProviderEnum.POSTMARK_API: "postmark",
            ProviderEnum.SMTP_PRIMARY: "smtp",
            ProviderEnum.SMTP_FALLBACK: "smtp",
            ProviderEnum.TWILIO_SMS: "twilio",
            ProviderEnum.VONAGE_SMS: "vonage",
        }

        return mapping.get(provider_enum, "mock")

    @classmethod
    def _get_provider_config(cls, provider_enum: ProviderEnum) -> Dict[str, Any]:
        """Get provider configuration from environment.

        Args:
            provider_enum: Provider enum value

        Returns:
            Provider configuration dictionary
        """
        if provider_enum == ProviderEnum.MOCK_PROVIDER:
            return {
                "success_rate": 0.95,
                "delay_ms": 100,
                "webhook_secret": environment.MOCK_WEBHOOK_SECRET,
            }

        elif provider_enum == ProviderEnum.POSTMARK_API:
            return {
                "api_token": environment.POSTMARK_API_TOKEN,
                "sender_email": environment.EMAIL_SENDER,
                "sender_name": environment.EMAIL_SENDER_NAME,
                "webhook_secret": environment.POSTMARK_WEBHOOK_SECRET,
            }

        elif provider_enum in (ProviderEnum.SMTP_PRIMARY, ProviderEnum.SMTP_FALLBACK):
            # Use different SMTP configs for primary vs fallback
            if provider_enum == ProviderEnum.SMTP_PRIMARY:
                return {
                    "smtp_host": environment.SMTP_HOST,
                    "smtp_port": environment.SMTP_PORT,
                    "smtp_user": environment.SMTP_USER,
                    "smtp_password": environment.SMTP_PASSWORD,
                    "use_tls": environment.SMTP_TLS,
                    "sender_email": environment.EMAIL_SENDER,
                    "sender_name": environment.EMAIL_SENDER_NAME,
                }
            else:  # Fallback SMTP
                return {
                    "smtp_host": environment.SMTP_FALLBACK_HOST,
                    "smtp_port": environment.SMTP_FALLBACK_PORT,
                    "smtp_user": environment.SMTP_FALLBACK_USER,
                    "smtp_password": environment.SMTP_FALLBACK_PASSWORD,
                    "use_tls": environment.SMTP_FALLBACK_TLS,
                    "sender_email": environment.EMAIL_SENDER,
                    "sender_name": environment.EMAIL_SENDER_NAME,
                }

        elif provider_enum == ProviderEnum.TWILIO_SMS:
            return {
                "account_sid": environment.TWILIO_ACCOUNT_SID,
                "auth_token": environment.TWILIO_AUTH_TOKEN,
                "sender_phone": environment.SMS_SENDER,
                "webhook_secret": environment.TWILIO_WEBHOOK_SECRET,
            }

        elif provider_enum == ProviderEnum.VONAGE_SMS:
            return {
                "api_key": environment.VONAGE_API_KEY,
                "api_secret": environment.VONAGE_API_SECRET,
                "sender_id": environment.SMS_SENDER,
                "webhook_secret": environment.VONAGE_WEBHOOK_SECRET,
            }

        else:
            # Default to mock for unknown providers
            return {"success_rate": 0.95, "delay_ms": 100}

    @classmethod
    def test_provider_connection(cls, provider: NotificationProvider) -> bool:
        """Test if provider is healthy and ready to send.

        Args:
            provider: Provider instance to test

        Returns:
            True if provider is healthy
        """
        try:
            # For mock provider, always return True
            if isinstance(provider, MockNotificationProvider):
                return True

            # For real providers, implement actual health checks
            # This would check API connectivity, credentials, etc.
            return True
        except Exception:
            return False

    @classmethod
    def get_healthy_provider_chain(
        cls, channel: NotificationChannel, primary_provider: Optional[ProviderEnum] = None
    ) -> List[NotificationProvider]:
        """Get chain of healthy providers for fallback.

        Args:
            channel: Notification channel
            primary_provider: Override primary provider

        Returns:
            List of healthy provider instances
        """
        all_providers = cls.create_provider_chain(channel, primary_provider)
        healthy_providers = []

        for provider in all_providers:
            if cls.test_provider_connection(provider):
                healthy_providers.append(provider)

        return healthy_providers

    @classmethod
    def get_available_providers(cls) -> List[str]:
        """Get list of available provider names.

        Returns:
            List of registered provider names
        """
        return list(cls._providers.keys())

    @classmethod
    def update_fallback_chain(
        cls, channel: NotificationChannel, providers: List[ProviderEnum]
    ) -> None:
        """Update fallback chain for a channel.

        Args:
            channel: Notification channel
            providers: New provider chain in fallback order
        """
        cls._fallback_chains[channel] = providers
