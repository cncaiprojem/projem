"""Payment provider factory - Task 4.6."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ...core.environment import environment
from .base import PaymentProvider
from .stripe_provider import StripeProvider
from .mock_provider import MockProvider


class PaymentProviderFactory:
    """Factory for creating payment provider instances."""
    
    _providers = {
        "stripe": StripeProvider,
        "mock": MockProvider,
    }
    
    @classmethod
    def create_provider(
        self,
        provider_name: str,
        config: Optional[Dict[str, Any]] = None
    ) -> PaymentProvider:
        """Create a payment provider instance.
        
        Args:
            provider_name: Name of the provider ("stripe", "mock", etc.)
            config: Optional configuration override
            
        Returns:
            PaymentProvider instance
            
        Raises:
            ValueError: If provider is not supported
        """
        if provider_name not in self._providers:
            raise ValueError(
                f"Unsupported payment provider: {provider_name}. "
                f"Supported providers: {list(self._providers.keys())}"
            )
        
        # Get default configuration
        default_config = self._get_default_config(provider_name)
        
        # Merge with provided config
        if config:
            default_config.update(config)
        
        provider_class = self._providers[provider_name]
        return provider_class(default_config)
    
    @classmethod
    def get_supported_providers(self) -> list[str]:
        """Get list of supported provider names."""
        return list(self._providers.keys())
    
    @classmethod
    def register_provider(self, name: str, provider_class: type[PaymentProvider]) -> None:
        """Register a new payment provider.
        
        Args:
            name: Provider name identifier
            provider_class: Provider class that extends PaymentProvider
        """
        if not issubclass(provider_class, PaymentProvider):
            raise ValueError("Provider class must extend PaymentProvider")
        
        self._providers[name] = provider_class
    
    @classmethod
    def _get_default_config(self, provider_name: str) -> Dict[str, Any]:
        """Get default configuration for a provider."""
        # Use the environment instance directly
        
        if provider_name == "stripe":
            return {
                "api_key": environment.STRIPE_SECRET_KEY,
                "webhook_secret": environment.STRIPE_WEBHOOK_SECRET,
                "environment": environment.STRIPE_ENVIRONMENT
            }
        elif provider_name == "mock":
            return {
                "test_mode": True,
                "fail_percentage": 0.0,
            }
        
        return {}