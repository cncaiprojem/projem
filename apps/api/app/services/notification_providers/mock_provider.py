"""
Mock notification provider for Task 4.7 - Testing and development.
Simulates real provider behavior without external API calls.
"""

import asyncio
import hashlib
import hmac
import random
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .base import NotificationProvider, NotificationResult, EmailNotification, SMSNotification


class MockNotificationProvider(NotificationProvider):
    """Mock notification provider for testing and development.
    
    Task 4.7 Implementation:
    - Simulates both email and SMS sending
    - Configurable success/failure rates for testing
    - Webhook signature verification simulation
    - Delivery status tracking simulation
    - Turkish character handling testing
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize mock provider.
        
        Args:
            config: Mock provider configuration
                - success_rate: Success rate (0.0 to 1.0)
                - delay_ms: Simulated API delay in milliseconds
                - webhook_secret: Secret for webhook signature testing
        """
        super().__init__("Mock Provider", config)
        self._message_store: Dict[str, Dict[str, Any]] = {}
    
    def _validate_config(self) -> None:
        """Validate mock provider configuration."""
        success_rate = self.config.get('success_rate', 0.95)
        if not 0.0 <= success_rate <= 1.0:
            raise ValueError("success_rate must be between 0.0 and 1.0")
        
        delay_ms = self.config.get('delay_ms', 100)
        if not isinstance(delay_ms, (int, float)) or delay_ms < 0:
            raise ValueError("delay_ms must be a non-negative number")
    
    async def send_email(self, notification: EmailNotification) -> NotificationResult:
        """Simulate sending an email notification.
        
        Args:
            notification: Email notification data
            
        Returns:
            Simulated notification result
        """
        # Simulate API delay
        delay_ms = self.config.get('delay_ms', 100)
        await asyncio.sleep(delay_ms / 1000.0)
        
        # Validate email
        try:
            recipient = self.sanitize_email(notification.recipient)
        except ValueError as e:
            return self.create_error_result(
                error_code="invalid_email",
                error_message=str(e)
            )
        
        # Simulate success/failure based on configuration
        success_rate = self.config.get('success_rate', 0.95)
        is_success = random.random() < success_rate
        
        if is_success:
            message_id = f"mock_email_{uuid.uuid4().hex[:12]}"
            
            # Store message for status tracking
            self._message_store[message_id] = {
                'type': 'email',
                'recipient': recipient,
                'subject': notification.subject,
                'body': notification.html_body,
                'sent_at': datetime.now(timezone.utc).isoformat(),
                'status': 'sent'
            }
            
            return self.create_success_result(
                message_id=message_id,
                provider_response={
                    'mock_id': message_id,
                    'recipient': recipient,
                    'subject': notification.subject,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'status': 'sent'
                }
            )
        else:
            # Simulate various failure scenarios
            error_scenarios = [
                ('invalid_recipient', 'Email address does not exist'),
                ('rate_limit', 'Rate limit exceeded'),
                ('temporary_failure', 'Temporary service unavailable'),
                ('blocked_content', 'Content blocked by spam filter')
            ]
            error_code, error_message = random.choice(error_scenarios)
            
            return self.create_error_result(
                error_code=error_code,
                error_message=error_message,
                http_status_code=400 if error_code == 'invalid_recipient' else 500
            )
    
    async def send_sms(self, notification: SMSNotification) -> NotificationResult:
        """Simulate sending an SMS notification.
        
        Args:
            notification: SMS notification data
            
        Returns:
            Simulated notification result
        """
        # Simulate API delay
        delay_ms = self.config.get('delay_ms', 150)
        await asyncio.sleep(delay_ms / 1000.0)
        
        # Validate and format phone number
        try:
            recipient = self.format_phone_number(notification.recipient)
        except Exception as e:
            return self.create_error_result(
                error_code="invalid_phone",
                error_message=f"Invalid phone number: {e}"
            )
        
        # Check SMS length
        message = self.encode_turkish_text(notification.message)
        if len(message) > 160:
            message = self.truncate_sms(message, 160)
        
        # Simulate success/failure
        success_rate = self.config.get('success_rate', 0.92)  # Slightly lower for SMS
        is_success = random.random() < success_rate
        
        if is_success:
            message_id = f"mock_sms_{uuid.uuid4().hex[:12]}"
            
            # Store message for status tracking
            self._message_store[message_id] = {
                'type': 'sms',
                'recipient': recipient,
                'message': message,
                'sent_at': datetime.now(timezone.utc).isoformat(),
                'status': 'sent'
            }
            
            return self.create_success_result(
                message_id=message_id,
                provider_response={
                    'mock_id': message_id,
                    'recipient': recipient,
                    'message_length': len(message),
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'status': 'sent'
                }
            )
        else:
            # Simulate SMS-specific failure scenarios
            error_scenarios = [
                ('invalid_number', 'Phone number is invalid or unreachable'),
                ('carrier_blocked', 'Message blocked by carrier'),
                ('insufficient_credit', 'Insufficient account balance'),
                ('content_filtered', 'Message content filtered')
            ]
            error_code, error_message = random.choice(error_scenarios)
            
            return self.create_error_result(
                error_code=error_code,
                error_message=error_message,
                http_status_code=400 if 'invalid' in error_code else 500
            )
    
    def verify_webhook_signature(self, signature: str, payload: bytes) -> bool:
        """Simulate webhook signature verification.
        
        Args:
            signature: Webhook signature
            payload: Raw webhook payload
            
        Returns:
            True if signature is valid
        """
        webhook_secret = self.config.get('webhook_secret')
        if not webhook_secret:
            return True  # Allow all if no secret configured
        
        # Simulate signature verification (HMAC-SHA256)
        try:
            expected_signature = hmac.new(
                webhook_secret.encode('utf-8'),
                payload,
                hashlib.sha256
            ).hexdigest()
            
            # Remove 'sha256=' prefix if present
            if signature.startswith('sha256='):
                signature = signature[7:]
            
            return hmac.compare_digest(expected_signature, signature)
        except Exception:
            return False
    
    def parse_webhook_event(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Simulate parsing webhook event.
        
        Args:
            payload: Webhook payload
            
        Returns:
            Parsed event data
        """
        event_type = payload.get('event_type', 'delivery_status')
        message_id = payload.get('message_id')
        
        if not message_id:
            return None
        
        # Simulate delivery status updates
        status_options = ['sent', 'delivered', 'failed', 'bounced']
        new_status = payload.get('status', random.choice(status_options))
        
        # Update stored message status
        if message_id in self._message_store:
            self._message_store[message_id]['status'] = new_status
        
        return {
            'event_type': event_type,
            'message_id': message_id,
            'status': new_status,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'provider': 'mock'
        }
    
    def get_delivery_status(self, message_id: str) -> Optional[str]:
        """Get simulated delivery status.
        
        Args:
            message_id: Mock message ID
            
        Returns:
            Current delivery status
        """
        message = self._message_store.get(message_id)
        if message:
            return message.get('status')
        return None
    
    def simulate_webhook_event(self, message_id: str, event_type: str = 'delivered') -> Dict[str, Any]:
        """Generate a mock webhook event for testing.
        
        Args:
            message_id: Message ID to generate event for
            event_type: Type of event to simulate
            
        Returns:
            Mock webhook payload
        """
        return {
            'event_type': 'delivery_status',
            'message_id': message_id,
            'status': event_type,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'provider': 'mock',
            'mock_event': True
        }
    
    def get_stored_messages(self) -> Dict[str, Dict[str, Any]]:
        """Get all stored messages for testing.
        
        Returns:
            Dictionary of stored messages
        """
        return self._message_store.copy()
    
    def clear_stored_messages(self) -> None:
        """Clear stored messages."""
        self._message_store.clear()
    
    def set_success_rate(self, rate: float) -> None:
        """Update success rate for testing.
        
        Args:
            rate: New success rate (0.0 to 1.0)
        """
        if not 0.0 <= rate <= 1.0:
            raise ValueError("Success rate must be between 0.0 and 1.0")
        self.config['success_rate'] = rate
    
    def set_delay(self, delay_ms: float) -> None:
        """Update API delay for testing.
        
        Args:
            delay_ms: New delay in milliseconds
        """
        if delay_ms < 0:
            raise ValueError("Delay must be non-negative")
        self.config['delay_ms'] = delay_ms