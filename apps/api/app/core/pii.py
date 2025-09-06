"""
PII (Personally Identifiable Information) Masking Module

This module provides comprehensive PII detection and masking capabilities
for Turkish and international data formats, including:
- Turkish TC Kimlik No validation
- Credit card validation (Luhn algorithm)
- Email, phone, IP addresses
- API keys and tokens
- File paths containing user information
"""

from __future__ import annotations

import re
from typing import Any, Dict


class PIIMasker:
    """Utility class for masking PII in logs and error messages."""
    
    @staticmethod
    def _is_valid_tc_kimlik_no(number: str) -> bool:
        """Validate Turkish TC Kimlik No with checksum algorithm.
        
        TC Kimlik No validation rules:
        - Must be 11 digits
        - First digit cannot be 0
        - 10th digit = ((sum of odd positions * 7) - sum of even positions) mod 10
        - 11th digit = sum of first 10 digits mod 10
        """
        if not number.isdigit() or len(number) != 11 or number[0] == '0':
            return False
        
        digits = [int(d) for d in number]
        
        # Calculate 10th digit checksum
        odd_sum = sum(digits[i] for i in range(0, 9, 2))  # positions 1,3,5,7,9
        even_sum = sum(digits[i] for i in range(1, 8, 2))  # positions 2,4,6,8
        tenth_digit = (odd_sum * 7 - even_sum) % 10
        
        if digits[9] != tenth_digit:
            return False
        
        # Calculate 11th digit checksum
        eleventh_digit = sum(digits[:10]) % 10
        
        return digits[10] == eleventh_digit
    
    @staticmethod
    def _is_valid_credit_card(number: str) -> bool:
        """Validate credit card number using Luhn algorithm.
        
        Luhn algorithm:
        1. Double every second digit from right to left
        2. If doubling results in a number > 9, sum the digits
        3. Sum all digits
        4. Valid if sum mod 10 == 0
        """
        # Remove spaces and hyphens
        cleaned = re.sub(r'[\s-]', '', number)
        
        if not cleaned.isdigit() or len(cleaned) < 13 or len(cleaned) > 19:
            return False
        
        def luhn_checksum(card_number: str) -> int:
            digits = [int(d) for d in card_number]
            # Reverse for easier processing
            digits.reverse()
            
            total = 0
            for i, digit in enumerate(digits):
                if i % 2 == 1:  # Every second digit (from right)
                    doubled = digit * 2
                    if doubled > 9:
                        # Sum the digits (e.g., 16 -> 1 + 6 = 7)
                        total += doubled // 10 + doubled % 10
                    else:
                        total += doubled
                else:
                    total += digit
            
            return total % 10
        
        return luhn_checksum(cleaned) == 0
    
    @classmethod
    def _mask_tc_kimlik_no(cls, match):
        """Mask Turkish TC Kimlik No only if valid."""
        number = match.group(0)
        if cls._is_valid_tc_kimlik_no(number):
            return '[tc_no redacted]'
        return number
    
    @classmethod
    def _mask_credit_card(cls, match):
        """Mask credit card only if valid according to Luhn algorithm."""
        number = match.group(0)
        if cls._is_valid_credit_card(number):
            return '[card redacted]'
        return number
    
    # PII patterns for masking
    PATTERNS = {
        'email': (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[email redacted]'),
        'phone': (r'\b(?:\+?90|0)?(?:\s*\(?5\d{2}\)?[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}|\d{3}[\s.-]?\d{3}[\s.-]?\d{4})\b', '[phone redacted]'),
        'jwt': (r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[token redacted]'),
        'api_key': (r'\b(?:api[_-]?key|apikey|token)["\']?\s*[:=]\s*["\']?([A-Za-z0-9_-]{20,})["\']?', '[api_key redacted]'),
        'ip_address': (r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '[ip redacted]'),
        'home_dir': (r'(?:/home/[^/\s]+|/Users/[^/\s]+|C:\\Users\\[^\\]+)', '[path redacted]'),
    }
    
    # Special patterns that require validation
    VALIDATION_PATTERNS = {
        'credit_card': (r'\b(?:\d{4}[\s-]?){3,4}\d{1,4}\b', _mask_credit_card),
        'tc_kimlik_no': (r'\b\d{11}\b', _mask_tc_kimlik_no),
    }
    
    @classmethod
    def mask_text(cls, text: str) -> str:
        """Mask PII in text."""
        if not text:
            return text
        
        masked = text
        
        # Apply simple patterns first
        for pattern_name, (pattern, replacement) in cls.PATTERNS.items():
            masked = re.sub(pattern, replacement, masked, flags=re.IGNORECASE)
        
        # Apply validation-based patterns
        for pattern_name, (pattern, validator_func) in cls.VALIDATION_PATTERNS.items():
            # Pass the class method with cls bound
            masked = re.sub(pattern, lambda m: validator_func.__func__(cls, m), masked)
        
        return masked
    
    @classmethod
    def _mask_recursive(cls, obj: Any) -> Any:
        """Helper to recursively mask any data structure."""
        if isinstance(obj, str):
            return cls.mask_text(obj)
        elif isinstance(obj, dict):
            return cls.mask_dict(obj)
        elif isinstance(obj, list):
            return [cls._mask_recursive(item) for item in obj]
        elif isinstance(obj, tuple):
            return tuple(cls._mask_recursive(item) for item in obj)
        elif isinstance(obj, set):
            return {cls._mask_recursive(item) for item in obj}
        else:
            # For other types (int, float, bool, None, etc.), return as-is
            return obj
    
    @classmethod
    def mask_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively mask PII in dictionary."""
        if not data:
            return data
        
        masked = {}
        for key, value in data.items():
            # Mask sensitive keys entirely
            if any(sensitive in key.lower() for sensitive in ['password', 'secret', 'token', 'key', 'auth']):
                masked[key] = '[redacted]'
            else:
                # Use recursive helper for all value types
                masked[key] = cls._mask_recursive(value)
        
        return masked