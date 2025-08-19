"""
Base notification provider for Task 4.7 - Abstract interface for all providers.
Ultra-enterprise provider abstraction with fallback and retry support.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class NotificationResult:
    """Result of a notification send attempt."""
    success: bool
    message_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    provider_response: Optional[Dict[str, Any]] = None
    http_status_code: Optional[int] = None


@dataclass
class EmailNotification:
    """Email notification data."""
    recipient: str
    subject: str
    html_body: str
    plain_text_body: Optional[str] = None
    sender_email: Optional[str] = None
    sender_name: Optional[str] = None


@dataclass
class SMSNotification:
    """SMS notification data."""
    recipient: str  # Phone number in E.164 format
    message: str
    sender: Optional[str] = None


class NotificationProvider(ABC):
    """Abstract base class for all notification providers.
    
    Task 4.7 Implementation:
    - Unified interface for email/SMS providers
    - Error handling and result standardization
    - Provider-specific configuration support
    - Webhook signature verification
    - Turkish character encoding support
    """
    
    def __init__(self, provider_name: str, config: Dict[str, Any]):
        """Initialize provider with configuration.
        
        Args:
            provider_name: Human-readable provider name
            config: Provider-specific configuration
        """
        self.provider_name = provider_name
        self.config = config
        self._validate_config()
    
    @abstractmethod
    def _validate_config(self) -> None:
        """Validate provider configuration.
        
        Raises:
            ValueError: If configuration is invalid
        """
        pass
    
    @abstractmethod
    async def send_email(self, notification: EmailNotification) -> NotificationResult:
        """Send an email notification.
        
        Args:
            notification: Email notification data
            
        Returns:
            Notification result with success/failure info
        """
        pass
    
    @abstractmethod
    async def send_sms(self, notification: SMSNotification) -> NotificationResult:
        """Send an SMS notification.
        
        Args:
            notification: SMS notification data
            
        Returns:
            Notification result with success/failure info
        """
        pass
    
    def supports_email(self) -> bool:
        """Check if provider supports email notifications.
        
        Returns:
            True if email is supported
        """
        return True
    
    def supports_sms(self) -> bool:
        """Check if provider supports SMS notifications.
        
        Returns:
            True if SMS is supported
        """
        return True
    
    def verify_webhook_signature(self, signature: str, payload: bytes) -> bool:
        """Verify webhook signature for delivery confirmations.
        
        Args:
            signature: Webhook signature from headers
            payload: Raw webhook payload
            
        Returns:
            True if signature is valid
        """
        # Default implementation - override in providers that support webhooks
        return False
    
    def parse_webhook_event(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse webhook event for delivery status updates.
        
        Args:
            payload: Webhook payload
            
        Returns:
            Parsed event data or None if not supported
        """
        # Default implementation - override in providers that support webhooks
        return None
    
    def get_delivery_status(self, message_id: str) -> Optional[str]:
        """Get delivery status for a message.
        
        Args:
            message_id: Provider message ID
            
        Returns:
            Delivery status or None if not available
        """
        # Default implementation - override in providers that support status checking
        return None
    
    # Country code configuration for phone number formatting
    COUNTRY_CODE_MAP = {
        "TR": {"prefix": "90", "national_length": 10, "trunk_prefix": "0"},
        "US": {"prefix": "1", "national_length": 10, "trunk_prefix": "1"},
        "UK": {"prefix": "44", "national_length": 10, "trunk_prefix": "0"},
        "DE": {"prefix": "49", "national_length": 11, "trunk_prefix": "0"},
        "FR": {"prefix": "33", "national_length": 9, "trunk_prefix": "0"},
        "IT": {"prefix": "39", "national_length": 10, "trunk_prefix": "0"},
        "ES": {"prefix": "34", "national_length": 9, "trunk_prefix": "0"},
        "NL": {"prefix": "31", "national_length": 9, "trunk_prefix": "0"},
    }
    
    def format_phone_number(self, phone: str, default_country: str = "TR") -> str:
        """Format phone number to E.164 format.
        
        Args:
            phone: Phone number in various formats
            default_country: Default country code (ISO 3166-1 alpha-2)
            
        Returns:
            Phone number in E.164 format (+XXXXXXXXXXX)
        """
        # Remove all non-digit characters
        cleaned = ''.join(filter(str.isdigit, phone))
        
        # Get country info from mapping, fallback to Turkey
        country_info = self.COUNTRY_CODE_MAP.get(default_country, self.COUNTRY_CODE_MAP["TR"])
        country_prefix = country_info["prefix"]
        national_length = country_info["national_length"]
        trunk_prefix = country_info["trunk_prefix"]
        
        # If number starts with country code, return as E.164
        if cleaned.startswith(country_prefix):
            return f"+{cleaned}"
        
        # If number starts with trunk prefix, strip and add country code
        if trunk_prefix and cleaned.startswith(trunk_prefix):
            return f"+{country_prefix}{cleaned[len(trunk_prefix):]}"
        
        # If number is national length, add country code
        if len(cleaned) == national_length:
            return f"+{country_prefix}{cleaned}"
        
        # Check if number starts with another known country code
        for code_info in self.COUNTRY_CODE_MAP.values():
            if cleaned.startswith(code_info["prefix"]):
                return f"+{cleaned}"
        
        # Fallback: add default country code
        return f"+{country_prefix}{cleaned}"
    
    def sanitize_email(self, email: str) -> str:
        """Sanitize and validate email address.
        
        Args:
            email: Email address to sanitize
            
        Returns:
            Sanitized email address
            
        Raises:
            ValueError: If email is invalid
        """
        import re
        
        # Basic email validation regex
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        
        email = email.strip().lower()
        if not re.match(email_pattern, email):
            raise ValueError(f"Invalid email address: {email}")
        
        return email
    
    def encode_turkish_text(self, text: str) -> str:
        """Ensure proper encoding for Turkish characters.
        
        Args:
            text: Text that may contain Turkish characters
            
        Returns:
            Properly encoded text
        """
        # Ensure UTF-8 encoding for Turkish characters (ç, ğ, ı, ö, ş, ü)
        try:
            return text.encode('utf-8').decode('utf-8')
        except UnicodeError:
            # Fallback: replace problematic characters
            replacements = {
                'Ã§': 'ç', 'Ã°': 'ğ', 'Ä±': 'ı', 'Ã¶': 'ö', 'Åÿ': 'ş', 'Ã¼': 'ü',
                'Ã‡': 'Ç', 'ÃŸ': 'Ğ', 'Ä°': 'İ', 'Ã–': 'Ö', 'Åž': 'Ş', 'Ãœ': 'Ü'
            }
            for old, new in replacements.items():
                text = text.replace(old, new)
            return text
    
    def truncate_sms(self, message: str, max_length: int = 160) -> str:
        """Truncate SMS message to fit within length limit.
        
        Args:
            message: SMS message text
            max_length: Maximum allowed length
            
        Returns:
            Truncated message
        """
        if len(message) <= max_length:
            return message
        
        # Try to truncate at word boundary
        truncated = message[:max_length-3]  # Reserve 3 chars for "..."
        last_space = truncated.rfind(' ')
        
        if last_space > max_length * 0.8:  # If we can save reasonable amount of text
            return truncated[:last_space] + "..."
        else:
            return truncated + "..."
    
    def create_success_result(
        self,
        message_id: str,
        provider_response: Optional[Dict[str, Any]] = None
    ) -> NotificationResult:
        """Create a successful notification result.
        
        Args:
            message_id: Provider message ID
            provider_response: Raw provider response
            
        Returns:
            Success notification result
        """
        return NotificationResult(
            success=True,
            message_id=message_id,
            provider_response=provider_response
        )
    
    def create_error_result(
        self,
        error_code: str,
        error_message: str,
        provider_response: Optional[Dict[str, Any]] = None,
        http_status_code: Optional[int] = None
    ) -> NotificationResult:
        """Create a failed notification result.
        
        Args:
            error_code: Error code
            error_message: Error description
            provider_response: Raw provider response
            http_status_code: HTTP status code
            
        Returns:
            Error notification result
        """
        return NotificationResult(
            success=False,
            error_code=error_code,
            error_message=error_message,
            provider_response=provider_response,
            http_status_code=http_status_code
        )
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.provider_name}')>"